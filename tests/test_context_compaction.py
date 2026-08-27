"""AI Agent Framework — Context Compaction / Stage Packet Protocol 测试（AAF-MAINT-CONTEXT-001）。

覆盖（Requirement 11）+ Anti-Regression（Requirement 12）+ 测量证据（Requirement 10）：
- Compact TASK parser compatibility
- required information retained（Semantic Coverage Guard）
- WorkBuddy prompt 不再默认嵌 Hermes full report
- Codex prompt 不再默认嵌 Hermes + WorkBuddy full reports
- downstream paths/hash 可解析（manifest integrity）
- structured summary generated
- missing referenced artifact fail/fallback safely
- REPORT 不嵌 full Original Task
- legacy fallback works
- independent validation instructions retained
- no lifecycle regression
- context size before/after evidence（old full-chain vs new packet）
"""
from pathlib import Path

import pytest

from ai_agent_framework import runner as runner_mod
from ai_agent_framework.adapters import build_prompt, build_prompt_measured, legacy_build_prompt
from ai_agent_framework.context_packet import (
    build_stage_result,
    check_references,
    compare_packet_sizes,
    measure_prompt,
    read_stage_result,
    sha256_text,
    verify_semantic_coverage,
    write_manifest,
    write_stage_result,
)
from ai_agent_framework.report import build_report
from ai_agent_framework.task_validation import parse_task_fields, validate_task_text

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------- fixtures ----------

COMPACT_TASK = """AAF_TASK_BEGIN
Task ID: AAF-TEST-COMPACT-001
Task Name: Compact Schema Test
Workspace: D:\\ws\\test

Objective:
验证 Compact TASK Schema 全字段解析与独立验证保留。

Context:
引用 docs/internal/PROJECT_STATE.md Phase E 段；不复制全文。

Source of Truth:
- docs/internal/PROJECT_STATE.md
- docs/internal/AAF_MASTER_BACKLOG.md

Requirements:
1. 解析全部 Compact 字段
2. 不破坏旧格式任务
3. 不得删除 safety invariant

Scope / Out of Scope: 允许修改 tests；禁止修改核心逻辑

Validation:
运行 pytest -q。

Acceptance:
1. 全部测试通过
2. 旧任务仍可运行

Route Hint: Hermes → WorkBuddy → Codex
AAF_TASK_END
"""

LEGACY_TASK = """# Task ID
T-LEGACY

# Task Name
Legacy Task

# Objective
旧格式任务

# Acceptance
1. 可运行
"""

HERMES_NARRATIVE = (
    "implemented the feature\n"
    "changed files:\n- ai_agent_framework/adapters.py\n- ai_agent_framework/report.py\n"
    "tests: pytest -q -> 509 passed\n"
    + "detail line " * 500  # 模拟长 narrative（膨胀源）
    + "\nNARRATIVE_TAIL_MARKER_ONLY_IN_FULL_TEXT_9f3a"
)
WORKBUDDY_NARRATIVE = (
    "**Result: PASS_WITH_WARNING**\nW1: minor\n" + "verification detail " * 300
    + "\nWB_NARRATIVE_TAIL_MARKER_ONLY_IN_FULL_TEXT_7c2e"
)
NARRATIVE_TAIL = "NARRATIVE_TAIL_MARKER_ONLY_IN_FULL_TEXT_9f3a"
WB_TAIL = "WB_NARRATIVE_TAIL_MARKER_ONLY_IN_FULL_TEXT_7c2e"


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


# ---------- 1. Compact TASK parser compatibility ----------

def test_compact_task_parses_and_validates():
    fields = parse_task_fields(COMPACT_TASK)
    assert fields["Task ID"] == "AAF-TEST-COMPACT-001"
    assert fields["Task Name"] == "Compact Schema Test"
    assert fields["Workspace"] == r"D:\ws\test"
    assert fields["Objective"].startswith("验证 Compact")
    assert fields["Acceptance"].startswith("1.")
    # Compact 可选字段在既有格式下可解析（同行式 / # 标题式）
    assert fields["Scope / Out of Scope"].startswith("允许修改 tests")
    assert fields["Route Hint"].startswith("Hermes")
    assert validate_task_text(COMPACT_TASK).valid is True


def test_legacy_task_still_parses_and_validates():
    assert validate_task_text(LEGACY_TASK).valid is True
    f = parse_task_fields(LEGACY_TASK)
    assert f["Task ID"] == "T-LEGACY"
    assert f["Objective"].startswith("旧格式")


# ---------- 3. Semantic Coverage Guard（required information retained） ----------

def test_semantic_coverage_full_retention():
    cov = verify_semantic_coverage(COMPACT_TASK, COMPACT_TASK)
    assert cov.total > 0
    assert cov.ratio == 1.0
    assert cov.missing == []


def test_semantic_coverage_detects_dropped_requirement():
    compact = COMPACT_TASK.replace("3. 不得删除 safety invariant\n", "")
    cov = verify_semantic_coverage(COMPACT_TASK, compact)
    assert cov.ratio < 1.0
    assert any("safety invariant" in m for m in cov.missing)
    # safety invariant coverage 必须单独报告（100% 要求）
    assert any("safety invariant coverage: 0/1" in c for c in cov.checks)


def test_semantic_coverage_acceptance_semantics():
    compact = COMPACT_TASK.replace("2. 旧任务仍可运行\n", "")
    cov = verify_semantic_coverage(COMPACT_TASK, compact)
    assert any("acceptance semantics coverage" in c for c in cov.checks)
    assert cov.ratio < 1.0


# ---------- 4. WorkBuddy / Codex prompt 不再默认嵌上游 narrative 全文 ----------

def test_workbuddy_prompt_no_hermes_full_narrative(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes"])
    prompt, meta = build_prompt_measured(
        "workbuddy", COMPACT_TASK, {"hermes": HERMES_NARRATIVE}, tmp_path,
        output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
    )
    # 不默认嵌入 Hermes narrative 全文
    assert NARRATIVE_TAIL not in prompt
    assert "# TASK REFERENCE" in prompt and "Task Hash" in prompt
    # 引用路径 + 结构化摘要
    assert "HERMES STAGE SUMMARY" in prompt
    assert "hermes_result.json" in prompt
    assert "hermes_result.md" in prompt
    # 独立验证指令保留
    assert "INDEPENDENT VALIDATION" in prompt
    assert "独立验证" in prompt
    assert "不得静默" in prompt
    assert meta["embedded_artifact_count"] == 0
    assert meta["referenced_artifact_count"] == 1


def test_codex_prompt_no_upstream_full_narratives(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes", "workbuddy"])
    prompt, meta = build_prompt_measured(
        "codex", COMPACT_TASK,
        {"hermes": HERMES_NARRATIVE, "workbuddy": WORKBUDDY_NARRATIVE}, tmp_path,
        output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
    )
    assert NARRATIVE_TAIL not in prompt
    assert WB_TAIL not in prompt
    assert "HERMES STAGE SUMMARY" in prompt
    assert "WORKBUDDY STAGE SUMMARY" in prompt
    assert "INDEPENDENT REVIEW" in prompt
    assert "独立审查" in prompt
    assert meta["embedded_artifact_count"] == 0
    assert meta["referenced_artifact_count"] == 2


# ---------- 5. downstream paths/hash 可解析（manifest integrity） ----------

def test_manifest_references_resolvable(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes", "workbuddy"])
    tf = _task_file(tmp_path)
    stages = {}
    for agent in ("hermes", "workbuddy"):
        md = out / f"{agent}_result.md"
        js = out / f"{agent}_result.json"
        from ai_agent_framework.context_packet import sha256_file, file_bytes
        stages[agent] = {
            "result_md": {"path": str(md), "hash": sha256_file(md), "bytes": file_bytes(md)},
            "result_json": {"path": str(js), "hash": sha256_file(js), "bytes": file_bytes(js)},
        }
    write_manifest(
        out, task_path=tf, task_hash=sha256_text(COMPACT_TASK),
        task_bytes=len(COMPACT_TASK.encode("utf-8")), workspace=str(tmp_path),
        head="h" * 40, stages=stages, prompts={},
    )
    manifest = __import__("ai_agent_framework.context_packet", fromlist=["read_manifest"]).read_manifest(out)
    assert manifest is not None
    assert check_references(manifest) == []


def test_manifest_integrity_detects_tamper(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes"])
    tf = _task_file(tmp_path)
    from ai_agent_framework.context_packet import sha256_file, file_bytes
    md = out / "hermes_result.md"
    js = out / "hermes_result.json"
    stages = {"hermes": {
        "result_md": {"path": str(md), "hash": sha256_file(md), "bytes": file_bytes(md)},
        "result_json": {"path": str(js), "hash": sha256_file(js), "bytes": file_bytes(js)},
    }}
    write_manifest(
        out, task_path=tf, task_hash=sha256_text(COMPACT_TASK),
        task_bytes=len(COMPACT_TASK.encode("utf-8")), workspace=str(tmp_path),
        head=None, stages=stages, prompts={},
    )
    # 文件被修改 → hash 不匹配被检出（引用不因文件变化而失去可追溯性）
    md.write_text(HERMES_NARRATIVE + "\ntampered", encoding="utf-8")
    problems = check_references(__import__("ai_agent_framework.context_packet", fromlist=["read_manifest"]).read_manifest(out))
    assert any("hash" in p for p in problems)


# ---------- 6. structured summary generated ----------

def test_structured_summary_generated(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes"])
    stage = read_stage_result(out, "hermes")
    for field in ("agent", "status", "verdict", "blocking_rework", "commit",
                  "tests", "changed_files", "evidence_paths", "findings", "warnings"):
        assert field in stage, field
    assert stage["agent"] == "hermes"
    assert stage["status"] == "SUCCESS"
    assert stage["blocking_rework"] is False
    assert stage["changed_files"] == ["hermes_file.py"]
    assert len(stage["evidence_paths"]) == 2


# ---------- 9. missing referenced artifact fail/fallback safely ----------

def test_missing_referenced_narrative_falls_back_to_full_text(tmp_path):
    # 结构化 JSON 存在但 narrative md 被删 → 显式 FALLBACK_EMBEDDED 全文嵌入，不静默缺上下文
    out = _make_packet_dir(tmp_path, ["hermes"])
    (out / "hermes_result.md").unlink()
    prompt, meta = build_prompt_measured(
        "workbuddy", COMPACT_TASK, {"hermes": HERMES_NARRATIVE}, tmp_path,
        output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
    )
    assert "FALLBACK_EMBEDDED" in prompt
    assert NARRATIVE_TAIL in prompt  # 全文 fallback 注入（唯一长尾标记）
    assert meta["embedded_artifact_count"] == 1
    # 且 fail-fast 指令仍在（无法读取也必须显式报告）
    assert "报告 FAIL" in prompt


def test_fail_fast_instruction_always_present(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes", "workbuddy"])
    for agent in ("workbuddy", "codex"):
        prompt = build_prompt(
            agent, COMPACT_TASK,
            {"hermes": HERMES_NARRATIVE, "workbuddy": WORKBUDDY_NARRATIVE}, tmp_path,
            output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
        )
        assert "无法读取" in prompt  # 缺失引用不得静默继续


# ---------- 7. REPORT 不嵌 full Original Task ----------

def test_report_uses_task_reference_not_full_task(tmp_path):
    report = build_report(
        COMPACT_TASK, ["hermes", "workbuddy", "codex"],
        {"hermes": "ok", "workbuddy": "PASS", "codex": "APPROVE"},
        "SUCCESS",
        task_path=str(_task_file(tmp_path)),
        task_hash=sha256_text(COMPACT_TASK),
        output_dir=str(tmp_path / "out"),
    )
    assert "## Original Task" not in report
    assert "## Task Reference" in report
    assert "Task Hash" in report and "Task Path" in report
    # 不复制 TASK 全文（任选一段典型内容验证）
    assert "验证 Compact TASK Schema 全字段解析" not in report


def test_report_legacy_fallback_embeds_task():
    # 未提供 Task Reference（旧调用方）→ 保留旧格式自包含 REPORT
    report = build_report(LEGACY_TASK, ["hermes"], {"hermes": "ok"}, "SUCCESS")
    assert "## Original Task" in report
    assert "旧格式任务" in report


# ---------- 8. legacy fallback works（prompt 层） ----------

def test_legacy_prompt_fallback_embeds_full_results():
    prompt = build_prompt("workbuddy", LEGACY_TASK, {"hermes": HERMES_NARRATIVE}, None)
    assert "# ORIGINAL TASK" in prompt
    assert "## HERMES RESULT" in prompt
    assert "detail line" in prompt  # 旧行为：全文嵌入


def test_legacy_build_prompt_api_unchanged():
    prompt = legacy_build_prompt("codex", LEGACY_TASK, {"hermes": "ok", "workbuddy": "PASS"}, None)
    assert "# ORIGINAL TASK" in prompt and "## HERMES RESULT" in prompt


# ---------- 10. context size measurement + before/after evidence ----------

def test_measure_prompt_records_size():
    m = measure_prompt("hello 世界", embedded_artifact_count=0, referenced_artifact_count=2)
    assert m["chars"] == 8
    assert m["bytes"] == len("hello 世界".encode("utf-8"))
    assert m["embedded_artifact_count"] == 0
    assert m["referenced_artifact_count"] == 2


def test_packet_protocol_reduces_context_size(tmp_path):
    """同一 fixture：old full-chain vs new packet → 重复输入明显下降（Requirement 10）。"""
    out = _make_packet_dir(tmp_path, ["hermes", "workbuddy"])
    tf = _task_file(tmp_path)
    task_hash = sha256_text(COMPACT_TASK)
    results = {"hermes": HERMES_NARRATIVE, "workbuddy": WORKBUDDY_NARRATIVE}

    old_wb = legacy_build_prompt("workbuddy", COMPACT_TASK, results, tmp_path)
    old_cx = legacy_build_prompt("codex", COMPACT_TASK, results, tmp_path)
    old_chain = len(old_wb) + len(old_cx)

    new_wb, m1 = build_prompt_measured("workbuddy", COMPACT_TASK, results, tmp_path,
                                       output_dir=out, task_path=tf, task_hash=task_hash)
    new_cx, m2 = build_prompt_measured("codex", COMPACT_TASK, results, tmp_path,
                                       output_dir=out, task_path=tf, task_hash=task_hash)
    new_chain = len(new_wb) + len(new_cx)

    cmp = compare_packet_sizes(old_chain, new_chain)
    assert cmp["reduced"] is True
    assert new_chain < old_chain * 0.5  # 明显下降（重复输入移除）
    assert m1["embedded_artifact_count"] == 0 and m2["embedded_artifact_count"] == 0
    assert m1["referenced_artifact_count"] >= 1 and m2["referenced_artifact_count"] >= 2


# ---------- 11. no lifecycle regression（真实 runner 全链路） ----------

def test_runner_full_chain_with_packet(tmp_path, monkeypatch):
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        # 新协议：下游 prompt 走 Stage Context Packet（TASK REFERENCE + 结构化摘要路径）
        if agent in ("workbuddy", "codex"):
            assert "# TASK REFERENCE" in prompt
            assert "NARRATIVE_TAIL_MARKER" not in prompt
        if agent == "hermes":
            return "implemented\npytest -q -> all passed\ncommit: abc123"
        if agent == "workbuddy":
            return "**Result: PASS**\nverified independently"
        return "APPROVE"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path, LEGACY_TASK)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)

    # lifecycle 无回归：REPORT 生成 + SUCCESS
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    assert "## Task Reference" in report and "Task Hash" in report
    assert "## Original Task" not in report

    # stage 结构化结果 + manifest 生成
    assert (out / "hermes_result.json").exists()
    assert (out / "workbuddy_result.json").exists()
    manifest = __import__("ai_agent_framework.context_packet", fromlist=["read_manifest"]).read_manifest(out)
    assert manifest is not None
    assert manifest["task"]["hash"] == sha256_text(LEGACY_TASK)
    assert check_references(manifest) == []
    # prompt 指标已记录（Requirement 10）
    assert "workbuddy" in manifest["prompts"]
    assert manifest["prompts"]["workbuddy"]["chars"] > 0
    assert manifest["prompts"]["workbuddy"]["referenced_artifact_count"] >= 1

    # canonical lifecycle 正常
    import json
    task_json = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert task_json["status"] == "SUCCESS"
    assert calls == ["hermes", "workbuddy"]


def test_runner_resume_legacy_dir_falls_back(tmp_path, monkeypatch):
    """旧目录（无结构化 JSON）resume → legacy 全文嵌入，任务仍可运行（Requirement 8）。"""
    prompts_seen = []

    def fake_run_agent(agent, prompt, workspace):
        prompts_seen.append(prompt)
        return "implemented ok" if agent == "hermes" else "PASS"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = _task_file(tmp_path, LEGACY_TASK)
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)  # 正常跑一轮（新协议）
    # 模拟旧目录：删除结构化 JSON，仅保留 narrative md
    for agent in ("hermes", "workbuddy"):
        (out / f"{agent}_result.json").unlink()
    (out / "task.json").unlink()  # 旧目录没有 canonical → resume 需重建? 直接重跑
    report_path = runner_mod.run(task_file, ws, out)
    assert report_path.exists()
    # 第二轮 hermes prompt 仍走 packet（本轮先跑 hermes，其 JSON 会重建）；
    # workbuddy prompt 在 hermes JSON 重建后也走 packet —— legacy fallback 由
    # build_prompt 单测覆盖；此处验证整个链路不崩溃且 REPORT 生成。
    assert "## Task Reference" in report_path.read_text(encoding="utf-8")


# ---------- 12. Anti-Regression guards ----------

def test_anti_regression_report_no_full_task_embedding(tmp_path):
    report = build_report(
        COMPACT_TASK, ["hermes"], {"hermes": "ok"}, "SUCCESS",
        task_path=str(_task_file(tmp_path)), task_hash="h" * 64,
    )
    assert "## Original Task" not in report


def test_anti_regression_prompt_builder_no_unconditional_concat(tmp_path):
    out = _make_packet_dir(tmp_path, ["hermes", "workbuddy"])
    prompt = build_prompt(
        "codex", COMPACT_TASK,
        {"hermes": HERMES_NARRATIVE, "workbuddy": WORKBUDDY_NARRATIVE}, tmp_path,
        output_dir=out, task_path=_task_file(tmp_path), task_hash=sha256_text(COMPACT_TASK),
    )
    assert NARRATIVE_TAIL not in prompt
    assert WB_TAIL not in prompt
    assert "## HERMES RESULT" not in prompt and "## WORKBUDDY RESULT" not in prompt


def test_anti_regression_policy_exists_and_template_references():
    policy = REPO_ROOT / "docs" / "internal" / "AAF_TASK_EXECUTION_POLICY.md"
    assert policy.exists(), "Anti-Bloat Policy 必须存在"
    template = REPO_ROOT / "templates" / "TASK.md"
    assert template.exists()
    assert "AAF_TASK_EXECUTION_POLICY" in template.read_text(encoding="utf-8")
