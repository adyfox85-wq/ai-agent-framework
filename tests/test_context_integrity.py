"""AI Agent Framework — Context Integrity & Structured Evidence Closure 测试
（AAF-MAINT-CONTEXT-001-FIX-002）。

覆盖（FIX-002 Requirements 1–9 / 11 + Validation 项）：
- Immutable Task Snapshot：snapshot 创建、内容 = 执行 TASK、hash 单一来源
- active TASK 后续变化不影响 execution integrity；tampered snapshot 被检出
- WorkBuddy/Codex prompt 引用同一 execution snapshot
- Remote Sync 真值：Commit Sync / Tracked Working Tree / Task Remote Sync
  （tracked dirty 不得 SYNCED；预允许 untracked artifacts 不阻断）
- structured stage summary：schema validation、unknown ≠ empty
  （findings/warnings 未提供 → None/UNKNOWN，不伪装为 []）
- Narrative/JSON 一致性 guard（W1/W2/W3 → warnings 不得为 []）
- 不完整 summary 的下游 PARTIAL/UNKNOWN 显式标记 + narrative 指引
- 真实 compact WorkBuddy→Codex packet（结构化 findings/warnings 可靠传递）
- Context-size 测量证据可复算（exact fixture numbers）
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ai_agent_framework import runner as runner_mod
from ai_agent_framework.adapters import build_prompt, build_prompt_measured, legacy_build_prompt
from ai_agent_framework.context_packet import (
    STRUCTURED_RESULT_BEGIN,
    STRUCTURED_RESULT_END,
    build_stage_result,
    check_references,
    compare_packet_sizes,
    extract_and_validate_structured,
    extract_structured_tail,
    narrative_warning_count,
    read_manifest,
    read_stage_result,
    remote_sync_state,
    sha256_file,
    sha256_text,
    tracked_tree_status,
    validate_structured_summary,
    write_manifest,
    write_stage_result,
)
from ai_agent_framework.report import build_report

from tests.test_context_compaction import (
    COMPACT_TASK,
    HERMES_NARRATIVE,
    LEGACY_TASK,
    NARRATIVE_TAIL,
    WB_TAIL,
    WORKBUDDY_NARRATIVE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------- fixtures ----------

WB_TAIL_OK = (
    f"{STRUCTURED_RESULT_BEGIN}\n"
    '{"verdict": "PASS_WITH_WARNING", "blocking_rework": false, '
    '"findings": ["F1: verified"], "warnings": ["W1: minor"]}\n'
    f"{STRUCTURED_RESULT_END}"
)
WB_NARRATIVE_WITH_WARNINGS = (
    "**Result: PASS_WITH_WARNING**\n"
    "W1: warning one\n"
    "W2: warning two\n"
    "W3: warning three\n"
    "verified independently\n"
)


def _make_packet_dir(tmp_path: Path, agents: list[str]) -> Path:
    """构造带结构化 stage JSON（+ narrative md）的 output_dir。"""
    out = tmp_path / "packet"
    out.mkdir(exist_ok=True)
    narratives = {"hermes": HERMES_NARRATIVE, "workbuddy": WORKBUDDY_NARRATIVE}
    for agent in agents:
        body = narratives.get(agent, f"{agent} result body")
        (out / f"{agent}_result.md").write_text(body, encoding="utf-8")
        stage = build_stage_result(
            agent=agent,
            result_text=body,
            output_dir=out,
            head_before="a" * 40,
            head_after="b" * 40,
            changed_files=[f"{agent}_file.py"],
        )
        write_stage_result(out, stage)
    return out


def _task_file(tmp_path: Path, text: str = COMPACT_TASK) -> Path:
    tf = tmp_path / "TASK.md"
    tf.write_text(text, encoding="utf-8")
    return tf


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout.strip()


def _make_git_workspace(tmp_path: Path) -> Path:
    """构造带 origin/main 的本地 git 仓库（bare origin + baseline commit + push）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(tmp_path, "init", "--bare", "origin.git")
    _git(ws, "init", "-b", "main")
    _git(ws, "config", "user.email", "test@test")
    _git(ws, "config", "user.name", "test")
    (ws / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    _git(ws, "add", ".")
    _git(ws, "commit", "-m", "baseline")
    _git(ws, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(ws, "push", "-u", "origin", "main")
    return ws


# ---------- 1/2. Immutable Task Snapshot + Hash Single Source ----------

def test_runner_creates_snapshot_and_hash_single_source(tmp_path, monkeypatch):
    """snapshot 创建；manifest task hash == snapshot 内容 hash == snapshot 文件 hash。"""
    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            return "implemented\nchanged files: ok"
        if agent == "workbuddy":
            return "**Result: PASS**\nverified"
        return "APPROVE"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    snapshot = out / "TASK.snapshot.md"
    assert snapshot.exists()
    assert snapshot.read_text(encoding="utf-8") == COMPACT_TASK  # 内容 = 执行 TASK

    manifest = read_manifest(out)
    assert manifest is not None
    assert Path(manifest["task"]["path"]) == snapshot
    # Hash Single Source（FIX-004 Req 1/2）：manifest hash == snapshot 文件原始 bytes
    # 的 SHA-256（外部工具可复算），bytes == 文件实际大小（stat().st_size）。
    import hashlib

    raw = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert manifest["task"]["hash"] == raw
    assert manifest["task"]["hash"] == sha256_file(snapshot)
    assert manifest["task"]["bytes"] == snapshot.stat().st_size
    assert check_references(manifest) == []

    # REPORT Task Reference 也引用 snapshot
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "TASK.snapshot.md" in report
    assert manifest["task"]["hash"] in report


def test_manifest_distinguishes_intake_and_execution_task(tmp_path, monkeypatch):
    """FIX-003 Req 9：manifest 区分 intake_task（仅 provenance、无 hash）与
    execution_task（snapshot path + hash，downstream integrity 默认验证对象）。"""
    def fake_run_agent(agent, prompt, workspace):
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified", "codex": "APPROVE"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    manifest = read_manifest(out)
    assert manifest["intake_task"]["path"] == str(task_file)
    assert "hash" not in manifest["intake_task"]  # 单一 hash authority（无 intake hash）
    assert manifest["execution_task"]["path"] == str(out / "TASK.snapshot.md")
    assert manifest["execution_task"]["hash"] == sha256_file(out / "TASK.snapshot.md")
    # legacy task key 恒等于 execution_task（向后兼容 + hash 单一来源）
    assert manifest["task"] == manifest["execution_task"]
    assert check_references(manifest) == []


def test_report_original_intake_path_is_provenance_only(tmp_path):
    """FIX-003 Req 8：REPORT Task Reference 的 Task Path 指向 immutable snapshot；
    Original Intake Path 只是 provenance，不携带 hash authority。"""
    snapshot = tmp_path / "TASK.snapshot.md"
    snapshot.write_text(COMPACT_TASK, encoding="utf-8")
    active = tmp_path / "active" / "T-1.md"
    active.parent.mkdir(parents=True)
    active.write_text(COMPACT_TASK, encoding="utf-8")
    snapshot_hash = sha256_file(snapshot)

    report = build_report(
        COMPACT_TASK, ["hermes", "workbuddy", "codex"],
        {"hermes": "ok", "workbuddy": "PASS", "codex": "APPROVE"}, "SUCCESS",
        task_path=str(snapshot), task_hash=snapshot_hash,
        output_dir=str(tmp_path / "out"), intake_task_path=str(active),
    )
    ref = report.split("## Task Reference")[1].split("## Agent Results")[0]
    assert f"- Task Path: {snapshot}" in ref
    assert f"- Task Hash: {snapshot_hash}" in ref
    assert f"Original Intake Path: {active}" in ref
    # legacy 调用方（不提供 intake path）→ 无该行，REPORT 仍引用 snapshot
    report2 = build_report(
        COMPACT_TASK, ["hermes"], {"hermes": "ok"}, "SUCCESS",
        task_path=str(snapshot), task_hash=snapshot_hash,
    )
    assert "Original Intake Path" not in report2


def test_active_task_change_does_not_break_execution(tmp_path, monkeypatch):
    """active TASK 后续变化 → snapshot/hash/manifest 不变，check_references 仍通过。"""
    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            return "implemented"
        if agent == "workbuddy":
            return "**Result: PASS**\nverified"
        return "APPROVE"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    manifest_before = read_manifest(out)
    snapshot_before = (out / "TASK.snapshot.md").read_text(encoding="utf-8")

    # active 文件被修改（append 新要求）
    task_file.write_text(COMPACT_TASK + "\nRequirements:\n99. 新增要求\n", encoding="utf-8")

    manifest_after = read_manifest(out)
    assert manifest_after["task"]["hash"] == manifest_before["task"]["hash"]
    assert (out / "TASK.snapshot.md").read_text(encoding="utf-8") == snapshot_before
    assert check_references(manifest_after) == []  # integrity 不因 active 变化而破坏


def test_tampered_snapshot_detected_by_check_references(tmp_path, monkeypatch):
    """tampered snapshot → check_references 检出 hash 不匹配。"""
    def fake_run_agent(agent, prompt, workspace):
        return "ok" if agent == "hermes" else ("PASS" if agent == "workbuddy" else "APPROVE")

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    snapshot = out / "TASK.snapshot.md"
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\ntampered", encoding="utf-8")
    problems = check_references(read_manifest(out))
    assert any("hash" in p and "TASK.snapshot" in p for p in problems)


# ---------- FIX-004：Raw-Byte SHA256 / manifest bytes truth（Req 1/2/6） ----------

def test_sha256_file_hashes_raw_bytes_not_normalized_text(tmp_path):
    """FIX-004 Req 1：sha256_file 按文件原始 bytes 计算标准 SHA-256——
    CRLF/LF 文件均可由 hashlib.read_bytes / 外部标准工具直接复算；
    不再经过 read_text / 换行归一化 / encoding replacement。"""
    import hashlib

    lf = tmp_path / "lf.md"
    lf.write_text("line1\nline2\n", encoding="utf-8")
    crlf = tmp_path / "crlf.md"
    crlf.write_bytes(b"line1\r\nline2\r\n")

    assert sha256_file(lf) == hashlib.sha256(lf.read_bytes()).hexdigest()
    assert sha256_file(crlf) == hashlib.sha256(crlf.read_bytes()).hexdigest()
    # CRLF 文件 hash 必须与"原始字节"一致，而不是与换行归一化文本一致
    assert sha256_file(crlf) != sha256_text("line1\nline2\n")
    # 不可读 → None（调用方显式处理）
    assert sha256_file(tmp_path / "missing.md") is None


def test_runner_crlf_snapshot_hash_externally_reproducible(tmp_path, monkeypatch):
    """FIX-004 Req 1/2：预置 CRLF snapshot（active 文件 raw copy，模拟 launcher）→
    framework hash == hashlib.sha256(snapshot.read_bytes())，manifest bytes ==
    snapshot.stat().st_size；check_references 全部通过。"""
    import hashlib

    def fake_run_agent(agent, prompt, workspace):
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified", "codex": "APPROVE"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    body = COMPACT_TASK.replace("\n", "\r\n")
    task_file = tmp_path / "TASK.md"
    task_file.write_bytes(body.encode("utf-8"))
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "TASK.snapshot.md").write_bytes(body.encode("utf-8"))

    runner_mod.run(task_file, ws, out)

    snapshot = out / "TASK.snapshot.md"
    manifest = read_manifest(out)
    raw = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert manifest["task"]["hash"] == raw
    assert manifest["execution_task"]["hash"] == raw
    assert manifest["task"]["bytes"] == snapshot.stat().st_size
    assert manifest["execution_task"]["bytes"] == snapshot.stat().st_size
    assert check_references(manifest) == []


def test_downstream_prompts_reference_snapshot(tmp_path, monkeypatch):
    """WorkBuddy/Codex prompt 引用同一 execution snapshot（path + hash），不引用 active 文件。"""
    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            return "implemented"
        if agent == "workbuddy":
            return "**Result: PASS**\nverified"
        return "APPROVE"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    manifest = read_manifest(out)
    task_hash = manifest["task"]["hash"]
    for agent in ("workbuddy", "codex"):
        prompt = (out / f"{agent}_prompt.md").read_text(encoding="utf-8")
        assert "TASK.snapshot.md" in prompt          # 引用 snapshot
        assert task_hash in prompt                   # 同一 hash
        assert str(task_file) not in prompt          # 不引用可变化的 active 文件
        assert "execution snapshot" in prompt


# ---------- 4/5. Remote Sync 真值 ----------

def test_remote_sync_clean_and_synced(tmp_path):
    ws = _make_git_workspace(tmp_path)
    state = remote_sync_state(ws)
    assert state["is_git_repo"] is True
    assert state["commit_sync"] == "SYNCED"
    assert state["tracked_working_tree"] == "CLEAN"
    assert state["task_remote_sync"] == "SYNCED"


def test_remote_sync_tracked_dirty_not_synced(tmp_path):
    ws = _make_git_workspace(tmp_path)
    (ws / "baseline.txt").write_text("modified\n", encoding="utf-8")  # tracked 修改
    state = remote_sync_state(ws)
    # commit graph 已同步，但 tracked working tree DIRTY → Task Remote Sync 不得 SYNCED
    assert state["commit_sync"] == "SYNCED"
    assert state["tracked_working_tree"] == "DIRTY"
    assert state["task_remote_sync"] == "UNSYNCED"
    assert any("baseline.txt" in d for d in state["tracked_dirty_entries"])


def test_remote_sync_pre_allowed_untracked_does_not_fail(tmp_path):
    ws = _make_git_workspace(tmp_path)
    # 仅预允许 untracked artifacts → tracked tree 仍 CLEAN，Task Remote Sync 保持 SYNCED
    (ws / ".aaf").mkdir()
    (ws / ".aaf" / "run" / "x.json").parent.mkdir(parents=True)
    (ws / ".aaf" / "run" / "x.json").write_text("{}", encoding="utf-8")
    (ws / "scripts").mkdir()
    (ws / "scripts" / "start_bridge_hidden.vbs").write_text("' vbs", encoding="utf-8")
    (ws / "AAF_TASK004_PROCESS_CHECK.txt").write_text("check", encoding="utf-8")
    state = remote_sync_state(ws)
    assert state["tracked_working_tree"] == "CLEAN"
    assert state["task_remote_sync"] == "SYNCED"


def test_remote_sync_unpushed_commit_not_synced(tmp_path):
    ws = _make_git_workspace(tmp_path)
    (ws / "new.txt").write_text("x", encoding="utf-8")
    _git(ws, "add", ".")
    _git(ws, "commit", "-m", "unpushed")
    state = remote_sync_state(ws)
    assert state["commit_sync"] == "UNSYNCED"      # ahead=1
    assert state["tracked_working_tree"] == "CLEAN"
    assert state["task_remote_sync"] == "UNSYNCED"  # 未 push 不得 SYNCED


def test_report_remote_sync_section(tmp_path):
    sync = {
        "is_git_repo": True, "commit_sync": "SYNCED", "ahead": 0, "behind": 0,
        "has_upstream": True, "tracked_working_tree": "CLEAN",
        "tracked_dirty_entries": [], "task_remote_sync": "SYNCED",
    }
    report = build_report(
        COMPACT_TASK, ["hermes", "workbuddy", "codex"],
        {"hermes": "ok", "workbuddy": "PASS", "codex": "APPROVE"}, "SUCCESS",
        task_path=str(tmp_path / "TASK.snapshot.md"), task_hash="h" * 64,
        sync_state=sync,
    )
    assert "## Remote Sync" in report
    assert "- Commit Sync: SYNCED" in report
    assert "- Tracked Working Tree: CLEAN" in report
    assert "- Task Remote Sync: SYNCED" in report

    # tracked dirty → REPORT 明确 UNSYNCED + 列出未提交条目
    dirty = dict(sync, tracked_working_tree="DIRTY", task_remote_sync="UNSYNCED",
                 tracked_dirty_entries=[" M docs/internal/PROJECT_STATE.md"])
    report2 = build_report(
        COMPACT_TASK, ["hermes"], {"hermes": "ok"}, "SUCCESS",
        task_path=str(tmp_path / "TASK.snapshot.md"), task_hash="h" * 64, sync_state=dirty,
    )
    assert "- Task Remote Sync: UNSYNCED" in report2
    assert "docs/internal/PROJECT_STATE.md" in report2

    # legacy 调用方（无 sync_state / 非 git）→ 不输出 Remote Sync 段（不虚构）
    report3 = build_report(COMPACT_TASK, ["hermes"], {"hermes": "ok"}, "SUCCESS")
    assert "## Remote Sync" not in report3


# ---------- 6/7. Structured Result Completeness + schema validation ----------

WB_NARRATIVE_WITH_TAIL = (
    "**Result: PASS_WITH_WARNING**\n"
    "W1: minor\n"
    "verified independently\n\n"
    + WB_TAIL_OK
)


def test_structured_tail_extracted_validated_and_merged():
    data, status = extract_and_validate_structured("workbuddy", WB_NARRATIVE_WITH_TAIL)
    assert status == "OK"
    assert data["verdict"] == "PASS_WITH_WARNING"
    assert data["blocking_rework"] is False
    assert data["findings"] == ["F1: verified"]
    assert data["warnings"] == ["W1: minor"]

    stage = build_stage_result(
        agent="workbuddy", result_text=WB_NARRATIVE_WITH_TAIL, output_dir=".",
        structured=data, structured_status="OK",
    )
    assert stage["findings"] == ["F1: verified"]
    assert stage["warnings"] == ["W1: minor"]
    assert stage["summary_complete"] is True
    assert stage["structured_summary_status"] == "COMPLETE"


def test_missing_tail_unknown_not_empty():
    """未提供结构化块 → findings/warnings 为 None（UNKNOWN），绝不伪装为 []。"""
    stage = build_stage_result(
        agent="workbuddy", result_text="**Result: PASS**\nverified", output_dir=".",
    )
    assert stage["findings"] is None
    assert stage["warnings"] is None
    assert stage["summary_complete"] is False
    assert stage["structured_summary_status"] == "NOT_PROVIDED"


def test_malformed_tail_rejected():
    text = f"{STRUCTURED_RESULT_BEGIN}\n{{bad json\n{STRUCTURED_RESULT_END}"
    data, status = extract_structured_tail(text)
    assert data is None and status == "MALFORMED"
    data2, status2 = extract_and_validate_structured("workbuddy", text)
    assert data2 is None and status2 == "MALFORMED"


def test_schema_invalid_tail_rejected():
    """缺失必填字段（verdict）→ schema validation 拒绝（MALFORMED）。"""
    text = (
        f"{STRUCTURED_RESULT_BEGIN}\n"
        '{"blocking_rework": false, "findings": [], "warnings": []}\n'
        f"{STRUCTURED_RESULT_END}"
    )
    data, status = extract_and_validate_structured("workbuddy", text)
    assert data is None and status == "MALFORMED"
    # 类型错误同样拒绝
    data2, errs2 = validate_structured_summary(
        "codex", {"verdict": "APPROVE", "blocking_rework": "yes", "findings": [], "warnings": []}
    )
    assert data2 is None and any("blocking_rework" in e for e in errs2)


def test_hermes_structured_schema():
    text = (
        f"{STRUCTURED_RESULT_BEGIN}\n"
        '{"status": "SUCCESS", "commit": "abc123", "changed_files": ["a.py"], "warnings": []}\n'
        f"{STRUCTURED_RESULT_END}"
    )
    data, status = extract_and_validate_structured("hermes", text)
    assert status == "OK"
    assert data["status"] == "SUCCESS" and data["changed_files"] == ["a.py"]
    # hermes 无 verdict 要求；缺失 status → 拒绝
    data2, status2 = extract_and_validate_structured("hermes", "no tail")
    assert data2 is None and status2 == "NOT_PROVIDED"


# ---------- 9. Narrative / JSON 一致性 guard ----------

def test_narrative_warning_count():
    assert narrative_warning_count(WB_NARRATIVE_WITH_WARNINGS) == 3
    assert narrative_warning_count("no warnings here") == 0


def test_consistency_guard_warnings_not_lost():
    """WorkBuddy narrative 有 W1/W2/W3 → structured warnings=[] 必须被 guard 捕获。"""
    tail_empty = (
        f"{STRUCTURED_RESULT_BEGIN}\n"
        '{"verdict": "PASS_WITH_WARNING", "blocking_rework": false, '
        '"findings": [], "warnings": []}\n'
        f"{STRUCTURED_RESULT_END}"
    )
    body = WB_NARRATIVE_WITH_WARNINGS + "\n\n" + tail_empty
    data, status = extract_and_validate_structured("workbuddy", body)
    assert status == "OK"
    stage = build_stage_result(
        agent="workbuddy", result_text=body, output_dir=".", structured=data,
        structured_status=status,
    )
    # narrative 3 处 warning 标记 vs warnings=[] → 不得标 complete
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False
    # 且已有值保留（不静默丢信息），下游必须读 narrative
    assert stage["warnings"] == []

    # 对照：structured warnings 覆盖全部 3 条 → COMPLETE
    tail_full = (
        f"{STRUCTURED_RESULT_BEGIN}\n"
        '{"verdict": "PASS_WITH_WARNING", "blocking_rework": false, '
        '"findings": [], "warnings": ["W1: warning one", "W2: warning two", "W3: warning three"]}\n'
        f"{STRUCTURED_RESULT_END}"
    )
    data2, status2 = extract_and_validate_structured("workbuddy", WB_NARRATIVE_WITH_WARNINGS + "\n\n" + tail_full)
    stage2 = build_stage_result(
        agent="workbuddy", result_text=WB_NARRATIVE_WITH_WARNINGS + "\n\n" + tail_full,
        output_dir=".", structured=data2, structured_status=status2,
    )
    assert stage2["structured_summary_status"] == "COMPLETE"
    assert stage2["summary_complete"] is True
    assert len(stage2["warnings"]) == 3


def test_consistency_guard_verdict_not_lost():
    """narrative 显式 REQUEST_CHANGE（无通过结论）→ structured 必须反映 blocking。"""
    body = (
        "# REQUEST_CHANGE\n"
        "blocking issue found\n\n"
        + STRUCTURED_RESULT_BEGIN + "\n"
        '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}\n'
        + STRUCTURED_RESULT_END
    )
    data, status = extract_and_validate_structured("codex", body)
    stage = build_stage_result(
        agent="codex", result_text=body, output_dir=".", structured=data,
        structured_status=status,
    )
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False

    # narrative verdict 与 structured verdict 直接冲突 → 同样捕获
    body2 = (
        "**Result: PASS**\nverified\n\n"
        + STRUCTURED_RESULT_BEGIN + "\n"
        '{"verdict": "FAIL", "blocking_rework": true, "findings": ["f"], "warnings": []}\n'
        + STRUCTURED_RESULT_END
    )
    data2, status2 = extract_and_validate_structured("workbuddy", body2)
    stage2 = build_stage_result(
        agent="workbuddy", result_text=body2, output_dir=".", structured=data2,
        structured_status=status2,
    )
    assert stage2["structured_summary_status"] == "CONSISTENCY_VIOLATION"


# ---------- 8. No Silent Information Loss：下游 PARTIAL/UNKNOWN ----------

def test_incomplete_summary_marked_partial_in_downstream_prompt(tmp_path):
    """上游结构化 summary 不完整（summary_complete=false）→ 下游 prompt 显式
    PARTIAL/UNKNOWN + 必须读取 narrative；空 findings/warnings 不当完整事实。"""
    out = _make_packet_dir(tmp_path, ["hermes"])  # 无结构化块 → summary_complete=False
    prompt = build_prompt_measured(
        "workbuddy", COMPACT_TASK, {"hermes": HERMES_NARRATIVE}, tmp_path,
        output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
    )[0]
    assert "summary_complete: False" in prompt
    assert "structured_summary_status: NOT_PROVIDED" in prompt
    assert "UNKNOWN" in prompt
    assert "必须读取 narrative 全文" in prompt
    assert "不得视为" in prompt


def test_missing_stage_result_explicitly_flagged(tmp_path):
    """上游 result.json 缺失（legacy/中断目录）→ legacy 全文 fallback 之上显式
    标注缺失 + UNKNOWN 语义（FIX-002 Req 8），不静默缺信息。"""
    out = tmp_path / "packet"
    out.mkdir()
    (out / "hermes_result.md").write_text(HERMES_NARRATIVE, encoding="utf-8")  # 只有 narrative
    prompt, meta = build_prompt_measured(
        "workbuddy", COMPACT_TASK, {"hermes": HERMES_NARRATIVE}, tmp_path,
        output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
    )
    # 安全 fallback：全文嵌入（无信息丢失）
    assert "## HERMES RESULT" in prompt and NARRATIVE_TAIL in prompt
    assert meta["embedded_artifact_count"] == 1
    # 显式标注缺失 + UNKNOWN 语义
    assert "STRUCTURED SUMMARY 缺失" in prompt
    assert "FALLBACK_EMBEDDED" in prompt
    assert "hermes_result.json" in prompt
    assert "UNKNOWN" in prompt


# ---------- Validation：real compact WorkBuddy→Codex packet ----------

def test_workbuddy_to_codex_structured_packet_flow(tmp_path):
    """WorkBuddy 输出结构化 findings/warnings → Codex prompt 可靠接收（导航），
    不注入上游 narrative 全文；同一 snapshot hash 贯穿。"""
    out = tmp_path / "packet"
    out.mkdir()
    # hermes stage：无结构化块（UNKNOWN）
    (out / "hermes_result.md").write_text(HERMES_NARRATIVE, encoding="utf-8")
    h_stage = build_stage_result(
        agent="hermes", result_text=HERMES_NARRATIVE, output_dir=out,
        head_before="a" * 40, head_after="b" * 40, changed_files=["a.py"],
    )
    write_stage_result(out, h_stage)
    # workbuddy stage：结构化块（findings/warnings 明确）
    wb_body = (
        "**Result: PASS_WITH_WARNING**\n"
        "W1: minor\n"
        "W2: evidence gap\n"
        "verified independently\n\n" + WB_TAIL_OK
    )
    (out / "workbuddy_result.md").write_text(wb_body, encoding="utf-8")
    data, status = extract_and_validate_structured("workbuddy", wb_body)
    wb_stage = build_stage_result(
        agent="workbuddy", result_text=wb_body, output_dir=out,
        head_before="a" * 40, head_after="b" * 40, changed_files=[],
        structured=data, structured_status=status,
    )
    write_stage_result(out, wb_stage)
    assert wb_stage["summary_complete"] is False  # narrative W1/W2 vs tail 1 条 → PARTIAL

    tf = _task_file(tmp_path)
    task_hash = sha256_text(COMPACT_TASK)
    prompt = build_prompt_measured(
        "codex", COMPACT_TASK,
        {"hermes": HERMES_NARRATIVE, "workbuddy": wb_body}, tmp_path,
        output_dir=out, task_path=tf, task_hash=task_hash,
    )[0]
    # 结构化 findings/warnings 出现在 Codex prompt（导航）
    assert "F1: verified" in prompt
    assert "W1: minor" in prompt
    # 不注入上游 narrative 全文
    assert NARRATIVE_TAIL not in prompt
    assert WB_TAIL not in prompt
    # snapshot 引用贯穿
    assert "TASK.snapshot.md" in prompt and task_hash in prompt


# ---------- Runner 集成：structured tail 合并 ----------

def test_runner_merges_structured_tail_into_stage_result(tmp_path, monkeypatch):
    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            return "implemented"
        if agent == "workbuddy":
            return WB_NARRATIVE_WITH_WARNINGS + "\n\n" + WB_TAIL_OK
        return "APPROVE"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    wb = read_stage_result(out, "workbuddy")
    # narrative 3 处 warning vs tail 1 条 → PARTIAL（不静默当完整）
    assert wb["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert wb["summary_complete"] is False
    assert wb["warnings"] == ["W1: minor"]
    assert wb["findings"] == ["F1: verified"]

    hermes = read_stage_result(out, "hermes")
    assert hermes["findings"] is None and hermes["warnings"] is None
    assert hermes["structured_summary_status"] == "NOT_PROVIDED"


# ---------- 11. Measurement Evidence（可复算 fixture 数字） ----------

def test_context_size_fixture_exact_numbers():
    """Context-size 证据：同一 fixture 的可复算精确值（FIX-002 Req 11）。
    数字变更必须同步更新本测试常量与 docs（PROJECT_STATE / AAF_MASTER_BACKLOG）。
    workspace / packet 目录均使用固定路径（D:/ws/fixed-...），使数字与 pytest
    tmp_path 长度无关、同机反复复算一致；测试结束后清理固定目录。"""
    FIXED_WS = Path("D:/ws/fixed-workspace-path-for-reproducible-measurement")
    import shutil

    shutil.rmtree(FIXED_WS, ignore_errors=True)
    try:
        out = FIXED_WS / "packet"
        out.mkdir(parents=True)
        results = {"hermes": HERMES_NARRATIVE, "workbuddy": WORKBUDDY_NARRATIVE}
        for agent, body in results.items():
            (out / f"{agent}_result.md").write_text(body, encoding="utf-8")
            stage = build_stage_result(agent=agent, result_text=body, output_dir=out)
            write_stage_result(out, stage)
        tf = out / "TASK.snapshot.md"
        tf.write_text(COMPACT_TASK, encoding="utf-8")
        task_hash = sha256_text(COMPACT_TASK)

        old_wb = legacy_build_prompt("workbuddy", COMPACT_TASK, results, FIXED_WS)
        old_cx = legacy_build_prompt("codex", COMPACT_TASK, results, FIXED_WS)
        old_chain = len(old_wb) + len(old_cx)

        new_wb, m1 = build_prompt_measured("workbuddy", COMPACT_TASK, results, FIXED_WS,
                                           output_dir=out, task_path=tf, task_hash=task_hash)
        new_cx, m2 = build_prompt_measured("codex", COMPACT_TASK, results, FIXED_WS,
                                           output_dir=out, task_path=tf, task_hash=task_hash)
        new_chain = len(new_wb) + len(new_cx)

        # 可复算精确值（与 docs/internal 记录的测量证据一致）
        assert old_chain == 26211
        assert new_chain == 5379
        cmp = compare_packet_sizes(old_chain, new_chain)
        assert cmp["reduction_ratio"] == pytest.approx(0.7948, abs=1e-4)  # 约 80% reduction
        assert m1["embedded_artifact_count"] == 0 and m2["embedded_artifact_count"] == 0
        assert m1["referenced_artifact_count"] == 1 and m2["referenced_artifact_count"] == 2
    finally:
        shutil.rmtree(FIXED_WS, ignore_errors=True)
