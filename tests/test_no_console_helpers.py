"""AAF — Windows no-console helper subprocess 回归测试（AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001）。

覆盖确认的 console-flash 来源修复：
- git_status._git()（git rev-parse / branch / status / rev-list 等全部 helper git 调用）
- model_observation._run_readonly()（hermes/codebuddy/codex --version / --help /
  config get model / config get auxiliary / exec --help 全部 CLI 观测调用）
- context_packet.git_head / git_changed_files / _porcelain_all / remote_sync_state

原则（与 tests/test_adapters.py 的 no-console 测试同款）：
- Windows 侧：验证 subprocess 调用确实收到 CREATE_NO_WINDOW creationflags；
  Windows-only flag 相关测试按仓库惯例 skipif 非 Windows。
- 非 Windows 侧：monkeypatch subprocess_utils._IS_WINDOWS=False 验证零
  Windows-only 参数（platform-safe，两平台均可跑）。
- 全部通过 monkeypatch subprocess.run 捕获真实调用参数，不依赖肉眼观察。
- 同时断言参数列表 / cwd / capture_output / text / timeout 等既有语义完全保留。
"""
import os
import subprocess

import pytest

from ai_agent_framework import git_status as gs
from ai_agent_framework import model_observation as mo
from ai_agent_framework import subprocess_utils
from ai_agent_framework.context_packet import (
    git_changed_files,
    git_head,
    remote_sync_state,
    tracked_tree_status,
)

# 真实项目命令形态（修复不得改变任何参数）
GIT_REV_PARSE_HEAD = ["git", "rev-parse", "HEAD"]
GIT_STATUS_PORCELAIN = ["git", "status", "--porcelain", "-uall"]
GIT_IS_INSIDE = ["git", "rev-parse", "--is-inside-work-tree"]
GIT_UPSTREAM = ["git", "rev-parse", "--abbrev-ref", "@{u}"]
GIT_COUNTS = ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"]


class _FakeCompleted:
    """subprocess.CompletedProcess 最小替身（只读字段）。"""

    def __init__(self, returncode: int, stdout: str, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _install_fake_run(monkeypatch, script: dict, calls: list) -> None:
    """替换 subprocess.run：script 按 args tuple 返回 (rc, stdout, stderr)；
    calls 记录 (args, kwargs) 供断言。未命中 → rc=1。"""

    def fake_run(args, **kwargs):
        calls.append((list(args), kwargs))
        rc, out, err = script.get(tuple(args), (1, "", f"unmocked: {args}"))
        return _FakeCompleted(rc, out, err)

    monkeypatch.setattr(subprocess, "run", fake_run)


def _assert_all_creationflags(calls: list, expect_flag: bool) -> None:
    """断言每次 subprocess 调用都带（或不带）Windows creationflags。"""
    assert calls, "没有捕获到任何 subprocess 调用"
    for args, kwargs in calls:
        if expect_flag:
            assert kwargs.get("creationflags") & subprocess.CREATE_NO_WINDOW, (
                f"{args}: 未传 CREATE_NO_WINDOW → 会新建可见 console 窗口"
            )
        else:
            assert "creationflags" not in kwargs, (
                f"{args}: 非 Windows 不得传 Windows-only creationflags"
            )


# ---------------------------------------------------------------------------
# git_status._git()（全部 git helper 调用的单一 choke point）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW 是 Windows-only flag")
def test_git_status_helper_uses_create_no_window_on_windows(monkeypatch):
    """Windows：_git() 的 subprocess.run 收到 CREATE_NO_WINDOW，参数原样保留。"""
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {tuple(GIT_REV_PARSE_HEAD): (0, "abc123\n", "")},
        calls,
    )
    out = gs._git(["rev-parse", "HEAD"], "C:/ws")
    assert out == "abc123"  # 返回值语义不变
    _assert_all_creationflags(calls, expect_flag=True)
    assert calls[0][0] == GIT_REV_PARSE_HEAD  # 命令参数未变
    kw = calls[0][1]
    assert kw["cwd"] == "C:/ws"
    assert kw["capture_output"] is True and kw["text"] is True
    assert kw["encoding"] == "utf-8" and kw["errors"] == "replace"
    assert kw["timeout"] == 10.0


def test_git_status_helper_non_windows_no_creationflags(monkeypatch):
    """非 Windows：_git() 不传任何 Windows-only creationflags（platform-safe）。"""
    monkeypatch.setattr(subprocess_utils, "_IS_WINDOWS", False)
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {tuple(GIT_REV_PARSE_HEAD): (0, "abc123\n", "")},
        calls,
    )
    out = gs._git(["rev-parse", "HEAD"], "C:/ws")
    assert out == "abc123"
    _assert_all_creationflags(calls, expect_flag=False)


def test_git_status_helper_failure_semantics_unchanged(monkeypatch):
    """失败语义不变：非零退出 → ''；异常 → ''。"""
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {tuple(GIT_REV_PARSE_HEAD): (1, "", "not a git repo")},
        calls,
    )
    assert gs._git(["rev-parse", "HEAD"], "C:/ws") == ""
    assert len(calls) == 1

    def _raise(*a, **kw):
        raise OSError("git missing")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert gs._git(["rev-parse", "HEAD"], "C:/ws") == ""


# ---------------------------------------------------------------------------
# model_observation._run_readonly()（Hermes / CodeBuddy / Codex 观测 CLI 唯一入口）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW 是 Windows-only flag")
def test_model_observation_run_readonly_uses_create_no_window_on_windows(monkeypatch):
    """Windows：_run_readonly() 收到 CREATE_NO_WINDOW；参数 / 返回值语义不变。"""
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {("hermes", "config", "get", "model"): (0, "default: deepseek-v4-flash\n", "")},
        calls,
    )
    res = mo._run_readonly(["hermes", "config", "get", "model"])
    assert res == (0, "default: deepseek-v4-flash\n", "")  # (exit, stdout, stderr) 不变
    _assert_all_creationflags(calls, expect_flag=True)
    assert calls[0][0] == ["hermes", "config", "get", "model"]  # 参数未变
    kw = calls[0][1]
    assert kw["capture_output"] is True and kw["text"] is True
    assert kw["encoding"] == "utf-8" and kw["errors"] == "replace"
    assert kw["timeout"] == 20.0


def test_model_observation_run_readonly_non_windows_no_creationflags(monkeypatch):
    """非 Windows：_run_readonly() 不传 Windows-only creationflags。"""
    monkeypatch.setattr(subprocess_utils, "_IS_WINDOWS", False)
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {("codebuddy", "config", "get", "model"): (0, "", "")},
        calls,
    )
    assert mo._run_readonly(["codebuddy", "config", "get", "model"]) == (0, "", "")
    _assert_all_creationflags(calls, expect_flag=False)


def test_model_observation_run_readonly_exception_unchanged(monkeypatch):
    """调用失败语义不变：异常 → None（non-blocking）。"""

    def _raise(*a, **kw):
        raise OSError("no cli")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert mo._run_readonly(["hermes", "--help"]) is None


def test_discover_hermes_end_to_end_parsing_unchanged(monkeypatch):
    """真实 _run_readonly 路径下 discover_hermes 解析不变（mock CLI 输出形态）。"""
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {
            ("C:/fake/bin/hermes.exe", "--version"): (0, "Hermes Agent v0.20.5\n", ""),
            ("C:/fake/bin/hermes.exe", "config", "get", "model"): (
                0,
                "default: deepseek-v4-flash\nprovider: deepseek\nbase_url: ''\n",
                "",
            ),
            ("C:/fake/bin/hermes.exe", "config", "get", "auxiliary"): (
                1,
                "",
                "unavailable",
            ),
            ("C:/fake/bin/hermes.exe", "--help"): (0, "-m MODEL\n--provider\n", ""),
        },
        calls,
    )
    monkeypatch.setattr(mo, "_find_cli", lambda cmd: "C:/fake/bin/hermes.exe")
    mo._HELP_CACHE.clear()
    obs = mo.discover_hermes()
    assert obs["model"] == "deepseek-v4-flash"
    assert obs["provider"] == "deepseek"
    assert obs["model_source"] == mo.MODEL_SOURCE_CONFIG
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_OK
    # 全部观测 CLI 调用参数原样保留（version / config get model / auxiliary / help）
    arg_lists = [tuple(args) for args, _ in calls]
    assert ("C:/fake/bin/hermes.exe", "--version") in arg_lists
    assert ("C:/fake/bin/hermes.exe", "config", "get", "model") in arg_lists
    assert ("C:/fake/bin/hermes.exe", "--help") in arg_lists
    # 真实 Windows 上该路径同样带 CREATE_NO_WINDOW
    if os.name == "nt":
        _assert_all_creationflags(calls, expect_flag=True)


# ---------------------------------------------------------------------------
# context_packet.py 的 6 处 git 调用
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW 是 Windows-only flag")
def test_context_packet_git_calls_use_create_no_window_on_windows(monkeypatch):
    """Windows：context_packet 全部 git helper 调用都收到 CREATE_NO_WINDOW。"""
    calls: list = []
    script = {
        tuple(GIT_REV_PARSE_HEAD): (0, "abc123\n", ""),
        tuple(GIT_STATUS_PORCELAIN): (0, "?? scripts/start_bridge_hidden.vbs\n", ""),
        tuple(GIT_IS_INSIDE): (0, "true\n", ""),
        tuple(GIT_UPSTREAM): (0, "origin/main\n", ""),
        tuple(GIT_COUNTS): (0, "0\t0\n", ""),
    }
    _install_fake_run(monkeypatch, script, calls)

    assert git_head("C:/ws") == "abc123"
    assert git_changed_files("C:/ws") == []  # 预允许 untracked 过滤语义不变
    assert tracked_tree_status("C:/ws") == ("CLEAN", [])
    state = remote_sync_state("C:/ws")
    assert state["commit_sync"] == "SYNCED"
    assert state["tracked_working_tree"] == "CLEAN"
    assert state["task_remote_sync"] == "SYNCED"

    _assert_all_creationflags(calls, expect_flag=True)
    # 参数列表原样保留（4 个函数共 7 次 git 调用，全部命中预期命令：
    # status --porcelain -uall 出现 3 次 = git_changed_files + tracked_tree_status
    # 内 _porcelain_all + remote_sync_state 内部 tracked_tree_status）
    arg_lists = [tuple(args) for args, _ in calls]
    expected_counts = {
        tuple(GIT_REV_PARSE_HEAD): 1,
        tuple(GIT_STATUS_PORCELAIN): 3,
        tuple(GIT_IS_INSIDE): 1,
        tuple(GIT_UPSTREAM): 1,
        tuple(GIT_COUNTS): 1,
    }
    for expected, count in expected_counts.items():
        assert arg_lists.count(expected) == count, f"{expected}: 调用次数或参数改变"
    assert len(arg_lists) == 7


def test_context_packet_git_calls_non_windows_no_creationflags(monkeypatch):
    """非 Windows：context_packet 全部 git 调用不传 Windows-only creationflags。"""
    monkeypatch.setattr(subprocess_utils, "_IS_WINDOWS", False)
    calls: list = []
    script = {
        tuple(GIT_REV_PARSE_HEAD): (0, "abc123\n", ""),
        tuple(GIT_STATUS_PORCELAIN): (0, "", ""),
        tuple(GIT_IS_INSIDE): (0, "true\n", ""),
        tuple(GIT_UPSTREAM): (0, "origin/main\n", ""),
        tuple(GIT_COUNTS): (0, "0\t0\n", ""),
    }
    _install_fake_run(monkeypatch, script, calls)

    assert git_head("C:/ws") == "abc123"
    assert git_changed_files("C:/ws") == []
    assert remote_sync_state("C:/ws")["task_remote_sync"] == "SYNCED"
    _assert_all_creationflags(calls, expect_flag=False)


def test_context_packet_git_failure_semantics_unchanged(monkeypatch):
    """失败语义不变：非 git 仓库 → None / [] / NOT_APPLICABLE 路径保持。"""
    calls: list = []
    _install_fake_run(
        monkeypatch,
        {tuple(GIT_IS_INSIDE): (128, "", "fatal: not a git repository")},
        calls,
    )
    assert git_head("C:/ws") is None
    assert git_changed_files("C:/ws") == []
    state = remote_sync_state("C:/ws")
    assert state["commit_sync"] == "UNKNOWN"
    assert state["task_remote_sync"] == "NOT_APPLICABLE"
