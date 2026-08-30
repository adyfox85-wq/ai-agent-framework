"""AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001-FIX-001 focused tests：
normalized stage changed_files 语义修正。

背景缺陷：runner 归一化 changed_files 只用 stage 后 ``git status --porcelain``
派生——Hermes 修改文件并 commit 后工作区变干净，changed_files 错误塌缩为 []。

新语义（Framework Git 观察派生，非 agent 自报）：
- Case A：无 commit、有 tracked 工作区修改 → changed_files 含这些 tracked 文件
- Case B：stage 创建一个 commit 且结束干净 → changed_files 含
  head_before..head_after 之间提交改变的文件
- Case C：多个 commit → 反映 head_before..head_after 的 effective 文件变化
- Case D：commit + 剩余 tracked dirty → 两者并集，按 path 确定性去重
- Case E：无 commit 无 tracked 变化 → []

保持不变：
- commit / commit_changed 语义（head_before != head_after）
- PRE_ALLOWED_UNTRACKED（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）不污染 changed_files
- 行风格 = porcelain 风格（状态前缀 + 空格 + path），repo-relative
- 非 git 仓库 / 失败 → []

全部用真实 git 仓库（tmp_path + git.exe）验证，不 mock subprocess。
"""
import json
import subprocess

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework.context_packet import build_stage_result, git_changed_files

MINIMAL_TASK = """# Task ID
T-CHANGED-FILES-FIX

# Task Name
normalized stage changed_files provenance fix

# Objective
修正归一化 changed_files 语义并验证

# Route
hermes

# Acceptance
1. 通过
"""


def _git(ws, *args):
    r = subprocess.run(
        ["git", *args], cwd=str(ws), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr[-300:]}"
    return r.stdout.strip()


def _init_repo(ws, files: dict[str, str] | None = None) -> str:
    """初始化真实 git 仓库 + 初始 commit，返回 baseline HEAD。"""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "README.md").write_text("baseline\n", encoding="utf-8")
    for rel, content in (files or {}).items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "t@t")
    _git(ws, "config", "user.name", "t")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "baseline")
    return _git(ws, "rev-parse", "HEAD")


def _head(ws) -> str:
    return _git(ws, "rev-parse", "HEAD")


def _commit_all(ws, message: str) -> str:
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", message)
    return _head(ws)


# ============ Case B：commit 后工作区干净，已提交文件仍可见 ============

def test_committed_changes_returned_after_clean_commit(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws, files={"docs/one.md": "v1\n", "docs/two.md": "v1\n"})
    for rel in ("docs/one.md", "docs/two.md"):
        (ws / rel).write_text("v2\n", encoding="utf-8")
    after = _commit_all(ws, "stage commit")
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert "M docs/one.md" in files
    assert "M docs/two.md" in files
    # 工作区干净：若只用 git status 派生，此处会错误地返回 []
    assert _git(ws, "status", "--porcelain") == ""


# ============ Case A：无 commit、tracked dirty 修改 ============

def test_dirty_tracked_changes_returned_without_commit(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws)
    (ws / "README.md").write_text("dirty v2\n", encoding="utf-8")
    after = _head(ws)  # head 未变
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert "M README.md" in files
    assert before == after


# ============ Case D：committed + dirty 并集 ============

def test_committed_plus_dirty_union(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(
        ws, files={"dirty.txt": "v1\n", "committed.txt": "v1\n"})
    (ws / "committed.txt").write_text("v2\n", encoding="utf-8")
    after = _commit_all(ws, "commit one file")
    # commit 后再修改一个 tracked 文件（不提交）
    (ws / "dirty.txt").write_text("v2-dirty\n", encoding="utf-8")
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert "M committed.txt" in files  # committed 侧
    assert "M dirty.txt" in files      # dirty 侧（worktree 修改）
    # 顺序确定性：committed 在前、dirty 在后
    assert files.index("M committed.txt") < files.index("M dirty.txt")


# ============ 重复 path 去重（commit 后继续修改同一文件） ============

def test_duplicate_paths_deduplicated(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws)
    (ws / "README.md").write_text("v2\n", encoding="utf-8")
    after = _commit_all(ws, "commit README")
    # 同一文件再改一次（不提交）→ committed 与 dirty 两侧都出现同一 path
    (ws / "README.md").write_text("v3\n", encoding="utf-8")
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert files.count("M README.md") == 1
    assert [f for f in files if "README" in f] == ["M README.md"]


# ============ Case E：无 commit 无 tracked 变化 → [] ============

def test_clean_no_change_returns_empty(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws)
    files = git_changed_files(ws, head_before=before, head_after=_head(ws))
    assert files == []


# ============ PRE_ALLOWED_UNTRACKED 不污染（Req 7/9） ============

def test_pre_allowed_untracked_not_contaminating(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws, files={"real.md": "v1\n"})
    (ws / "real.md").write_text("v2\n", encoding="utf-8")
    after = _commit_all(ws, "commit real change")
    # 预允许 untracked 常驻项在 commit 之后存在（真实场景：stage 期间它们一直
    # 是 untracked 常驻 artifact，从不进入 commit）——不得污染 changed_files
    for rel in (".aaf/x", "AAF_TASK004_PROCESS_CHECK.txt",
                "scripts/start_bridge_hidden.vbs"):
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("artifact\n", encoding="utf-8")
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert "M real.md" in files
    # 预允许 untracked 项不得作为 task changed_files 出现
    assert not any(f.startswith("??") for f in files)
    assert not any(".aaf" in f or "PROCESS_CHECK" in f or "start_bridge_hidden" in f
                   for f in files)


# ============ Case C：多 commit 的 effective 文件变化 ============

def test_multiple_commits_effective_paths(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws, files={"c1.txt": "v1\n", "c2.txt": "v1\n"})
    (ws / "c1.txt").write_text("2\n", encoding="utf-8")
    _commit_all(ws, "commit 1")
    (ws / "c2.txt").write_text("2\n", encoding="utf-8")
    after = _commit_all(ws, "commit 2")
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert "M c1.txt" in files
    assert "M c2.txt" in files


# ============ committed add / delete ============

def test_committed_add_and_delete(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws)
    (ws / "added.txt").write_text("new\n", encoding="utf-8")
    (ws / "README.md").unlink()
    after = _commit_all(ws, "add + delete")
    files = git_changed_files(ws, head_before=before, head_after=after)
    assert "A added.txt" in files
    assert "D README.md" in files


# ============ committed rename 拆解（与 status 行风格一致） ============

def test_committed_rename_decomposes(tmp_path):
    ws = tmp_path / "ws"
    before = _init_repo(ws)
    _git(ws, "mv", "README.md", "README2.md")
    after = _commit_all(ws, "rename")
    files = git_changed_files(ws, head_before=before, head_after=after)
    # --no-renames：rename 拆解为 D old + A new（不引入新的 rename 行形态）
    assert "D README.md" in files
    assert "A README2.md" in files


# ============ commit / commit_changed 语义保持 ============

def test_build_stage_result_commit_semantics_preserved(tmp_path):
    before = "a" * 40
    after = "b" * 40
    stage = build_stage_result(
        agent="hermes", result_text="done", output_dir=tmp_path,
        head_before=before, head_after=after,
        changed_files=["M docs/x.md"],
    )
    assert stage["commit"] == after
    assert stage["commit_changed"] is True
    assert stage["changed_files"] == ["M docs/x.md"]
    stage2 = build_stage_result(
        agent="hermes", result_text="done", output_dir=tmp_path,
        head_before=before, head_after=before, changed_files=["M y.md"],
    )
    assert stage2["commit_changed"] is False
    assert stage2["changed_files"] == ["M y.md"]


# ============ head 参数缺省：旧语义不变（只报工作区） ============

def test_git_changed_files_no_head_args_backward_compat(tmp_path):
    ws = tmp_path / "ws"
    _init_repo(ws)
    (ws / "README.md").write_text("dirty\n", encoding="utf-8")
    for rel in (".aaf/x", "AAF_TASK004_PROCESS_CHECK.txt",
                "scripts/start_bridge_hidden.vbs"):
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("artifact\n", encoding="utf-8")
    files = git_changed_files(ws)  # 旧调用形态
    assert "M README.md" in files
    assert not any(f.startswith("??") for f in files)


# ============ 非 git 仓库 → [] ============

def test_git_changed_files_non_git_empty(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x\n", encoding="utf-8")
    assert git_changed_files(ws, head_before="a" * 40, head_after="b" * 40) == []


# ============ Runner 接线：真实 commit 的 stage → 归一化结果正确 ============

def test_runner_normalized_result_contains_committed_changes(tmp_path, monkeypatch):
    """端到端（in-process runner）：fake hermes stage 在真实 git workspace 中
    创建 commit → hermes_result.json 的 changed_files 必须含已提交 path，
    commit == 实际 HEAD，commit_changed == true（原缺陷场景）。"""
    ws = tmp_path / "ws"
    baseline = _init_repo(ws, files={"docs/stage_output.md": "v1\n"})

    def fake_run_agent(agent, prompt, workspace):
        # Executor 行为：修改 tracked 文件并提交（Framework 观察的事实源）
        (workspace / "docs" / "stage_output.md").write_text(
            "stage result v2\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "docs/stage_output.md"], cwd=str(workspace),
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "stage commit"],
            cwd=str(workspace), check=True, capture_output=True,
        )
        return ('implemented ok\nAAF_STRUCTURED_RESULT_BEGIN\n'
                '{"status": "SUCCESS", "changed_files": [], "warnings": []}\n'
                'AAF_STRUCTURED_RESULT_END')

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    # A0 付费 guard：显式本地模型 → LOCAL_FREE 放行（不依赖真实 hermes config）
    monkeypatch.setenv("AAF_HERMES_MODEL", "qwen3:4b")
    monkeypatch.setenv("AAF_HERMES_PROVIDER", "ollama")
    monkeypatch.setenv("AAF_MODEL_OBSERVATION", "0")  # 关闭 telemetry，保持测试快速

    task_file = tmp_path / "TASK.md"
    task_file.write_text(MINIMAL_TASK, encoding="utf-8")
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)
    assert "## Current Status\nSUCCESS" in report_path.read_text(encoding="utf-8")

    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    actual_head = _head(ws)
    assert stage["commit"] == actual_head
    assert stage["commit"] != baseline
    assert stage["commit_changed"] is True
    # 归一化 changed_files 由 Framework Git 观察派生（含已提交 path），
    # 不再塌缩为 []（agent raw 块自报 [] 不影响归一化事实）
    assert "M docs/stage_output.md" in stage["changed_files"]
