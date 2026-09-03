"""AAF Bridge — handoff 测试：last_run/report 读取、Git 只读快照、Handoff 构建。"""
import json
import subprocess
from pathlib import Path
import pytest

from bridge import handoff
from bridge.handoff import (
    HANDOFF_BEGIN,
    HANDOFF_END,
    GIT_NOT_APPLICABLE,
    SYNC_UNKNOWN,
    SYNC_SYNCED,
    SYNC_AHEAD,
    SYNC_BEHIND,
    SYNC_DIVERGED,
    build_handoff,
    compute_sync,
    git_snapshot,
    load_last_run,
    read_report,
)
from bridge.launcher import RunInfo, RESULT_FINISHED


def _run(args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _git_repo(tmp_path, n_commits=1):
    """初始化真实 git 仓库并提交 n 次；返回仓库路径。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["init", "-b", "main"], repo)
    _run(["config", "user.email", "test@example.com"], repo)
    _run(["config", "user.name", "Tester"], repo)
    for i in range(n_commits):
        f = repo / "f.txt"
        f.write_text(f"line{i}\n", encoding="utf-8")
        _run(["add", "f.txt"], repo)
        _run(["commit", "-m", f"c{i}"], repo)
    return repo


def _set_upstream(repo, remote_ref):
    """本地造 remote-tracking ref（不联网）并设置 tracking。"""
    _run(["remote", "add", "origin", "https://example.invalid/repo.git"], repo)
    head = _run(["rev-parse", "HEAD"], repo)
    _run(["update-ref", f"refs/remotes/origin/main", remote_ref or head], repo)
    _run(["branch", "--set-upstream-to", "origin/main", "main"], repo)


# ---------- last_run / REPORT ----------

def test_load_last_run_ok(tmp_path, monkeypatch):
    # last_run 读路径 = Bridge state root（AAF_BRIDGE_DIR 隔离；见 conftest）
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path))
    (tmp_path / "last_run.json").write_text(
        json.dumps({"task_id": "AAF-T1", "task_path": "T.md", "report_path": "R.md",
                    "exit_code": 0, "result": RESULT_FINISHED}),
        encoding="utf-8",
    )
    last = load_last_run()
    assert last is not None
    assert last.task_id == "AAF-T1"
    assert last.report_path == "R.md"


def test_load_last_run_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path / "nope"))
    assert load_last_run() is None


def test_load_last_run_corrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path))
    (tmp_path / "last_run.json").write_text("{bad json", encoding="utf-8")
    assert load_last_run() is None


def test_read_report_ok(tmp_path):
    p = tmp_path / "REPORT.md"
    p.write_text("# REPORT\n正文", encoding="utf-8")
    assert read_report(str(p)) == "# REPORT\n正文"


def test_read_report_missing(tmp_path):
    assert read_report(str(tmp_path / "nope.md")) is None
    assert read_report(None) is None


# ---------- compute_sync 纯判定 ----------

def test_compute_sync():
    assert compute_sync(0, 0, True) == SYNC_SYNCED
    assert compute_sync(1, 0, True) == SYNC_AHEAD
    assert compute_sync(0, 2, True) == SYNC_BEHIND
    assert compute_sync(1, 1, True) == SYNC_DIVERGED
    assert compute_sync(0, 0, False) == SYNC_UNKNOWN


# ---------- git_snapshot ----------

def test_git_snapshot_non_git(tmp_path):
    c = git_snapshot(str(tmp_path))
    assert c.is_git_repo is False
    assert c.remote_sync == SYNC_UNKNOWN


def test_git_snapshot_no_upstream(tmp_path):
    repo = _git_repo(tmp_path, 1)
    c = git_snapshot(str(repo))
    assert c.is_git_repo is True
    assert c.branch == "main"
    assert len(c.local_head) == 40
    assert c.working_tree == "clean"
    assert c.remote_sync == SYNC_UNKNOWN  # 无 upstream


def test_git_snapshot_synced(tmp_path):
    repo = _git_repo(tmp_path, 2)
    _set_upstream(repo, None)  # origin/main = HEAD
    c = git_snapshot(str(repo))
    assert c.remote_sync == SYNC_SYNCED
    assert c.ahead == 0 and c.behind == 0
    assert c.remote_head == c.local_head


def test_git_snapshot_ahead(tmp_path):
    repo = _git_repo(tmp_path, 2)
    _set_upstream(repo, None)
    # 本地再提交一次 → HEAD 领先 origin/main 1
    f = repo / "f.txt"
    f.write_text("extra\n", encoding="utf-8")
    _run(["add", "f.txt"], repo)
    _run(["commit", "-m", "c-extra"], repo)
    c = git_snapshot(str(repo))
    assert c.remote_sync == SYNC_AHEAD
    assert c.ahead == 1 and c.behind == 0


def test_git_snapshot_dirty(tmp_path):
    repo = _git_repo(tmp_path, 1)
    (repo / "untracked.txt").write_text("x", encoding="utf-8")
    c = git_snapshot(str(repo))
    assert c.working_tree == "dirty"


# ---------- build_handoff ----------

def test_build_handoff_git_repo(tmp_path):
    repo = _git_repo(tmp_path, 1)
    _set_upstream(repo, None)
    last = RunInfo(task_id="AAF-T1", task_path=str(repo / "T.md"),
                   report_path=str(repo / "R.md"), exit_code=0, result=RESULT_FINISHED)
    report_text = "# REPORT\n正式内容"
    closure = git_snapshot(str(repo))
    payload = build_handoff(last, report_text, closure)

    assert payload.startswith(HANDOFF_BEGIN)
    assert payload.endswith(HANDOFF_END)
    assert "Task: AAF-T1" in payload
    assert "# REPORT\n正式内容" in payload          # REPORT 原文完整
    assert "Git Branch: main" in payload
    assert "Remote Sync: SYNCED" in payload
    assert "Framework Result: FINISHED" in payload
    assert "Exit Code: 0" in payload


def test_build_handoff_non_git(tmp_path):
    last = RunInfo(task_id="AAF-T2", task_path=str(tmp_path / "T.md"),
                   report_path=str(tmp_path / "R.md"), exit_code=0, result=RESULT_FINISHED)
    closure = git_snapshot(str(tmp_path))
    payload = build_handoff(last, "report-body", closure)
    assert f"Git Status: {GIT_NOT_APPLICABLE}" in payload
    assert "Remote Sync" not in payload  # 非 git 不输出 sync 字段


def test_build_handoff_report_missing_never_fake(tmp_path):
    """REPORT 缺失时：调用方传 None，build 明确标记，不假装有内容。"""
    last = RunInfo(task_id="AAF-T3", task_path=str(tmp_path / "T.md"),
                   report_path=None, exit_code=0, result="REPORT_NOT_FOUND")
    closure = git_snapshot(str(tmp_path))
    payload = build_handoff(last, "", closure)
    assert "REPORT_NOT_FOUND" in payload
