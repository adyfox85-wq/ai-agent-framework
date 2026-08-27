"""AAF Bridge — FrameworkLauncher 测试（mock subprocess，不真实调用 Framework）。"""
import io
import os
import threading
from pathlib import Path
import pytest

from ai_agent_framework import subprocess_utils

from bridge import launcher
from bridge.launcher import (
    AlreadyRunningError,
    FrameworkLauncher,
    IDLE,
    RUNNING,
    FINISHED,
    FAILED_TO_START,
    RESULT_FINISHED,
    RESULT_FAILED,
    RESULT_REPORT_NOT_FOUND,
    RESULT_FAILED_TO_START,
)


class FakeProc:
    def __init__(self, exit_code: int = 0, stdout_text: str = ""):
        self._exit = exit_code
        self.stdout = io.StringIO(stdout_text)
        self.returncode = None

    def wait(self) -> int:
        self.returncode = self._exit
        return self._exit


@pytest.fixture
def make_launcher(monkeypatch, tmp_path):
    def _make(exit_code=0, stdout_text="", popen_raises=None):
        calls = []
        kwarg_calls = []
        if popen_raises is not None:
            def fake_popen(args, **kwargs):
                raise popen_raises
        else:
            def fake_popen(args, **kwargs):
                calls.append(args)
                kwarg_calls.append(kwargs)
                return FakeProc(exit_code=exit_code, stdout_text=stdout_text)
        monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
        done = threading.Event()
        captured = {}

        def on_finished(last, output):
            captured["last"] = last
            captured["output"] = output
            done.set()

        l = FrameworkLauncher(run_py=tmp_path / "run.py", on_finished=on_finished)
        l._fake_calls = calls
        l._fake_kwargs = kwarg_calls
        l._done = done
        l._captured = captured
        return l

    return _make


def _wait_done(l, timeout=3.0):
    l._done.wait(timeout)
    return l._done.is_set()


# ---------- 启动 / 状态机 ----------

def test_state_sequence_and_finished(make_launcher, tmp_path):
    l = make_launcher(exit_code=0)
    assert l.state == IDLE
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "REPORT.md").write_text("# REPORT", encoding="utf-8")

    started = l.launch(tmp_path / "TASK.md", str(tmp_path), out, "AAF-T1")
    assert started is True
    assert l.state == RUNNING
    assert _wait_done(l)
    assert l.state == FINISHED
    assert l.last.result == RESULT_FINISHED
    assert l.last.report_path == str(out / "REPORT.md")
    assert l.last.exit_code == 0
    # 参数正确：[python, run.py, task, --workspace, ws, --output, out]
    args = l._fake_calls[0]
    assert args[1] == str(tmp_path / "run.py")
    assert args[2] == str(tmp_path / "TASK.md")
    assert "--workspace" in args
    assert "--output" in args


def test_concurrent_launch_rejected(make_launcher, tmp_path):
    l = make_launcher(exit_code=0)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "REPORT.md").write_text("# R", encoding="utf-8")
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1") is True
    # RUNNING 期间第二次启动 → 拒绝
    with pytest.raises(AlreadyRunningError) as ei:
        l.launch(tmp_path / "T2.md", str(tmp_path), out, "AAF-T2")
    assert "AAF_TASK_ALREADY_RUNNING" in str(ei.value)


def test_startup_failure_keeps_task_and_state(make_launcher, tmp_path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text("content", encoding="utf-8")
    l = make_launcher(popen_raises=OSError(2, "no such file"))
    out = tmp_path / "out"
    out.mkdir(parents=True)

    started = l.launch(task_file, str(tmp_path), out, "AAF-T1")
    assert started is False
    assert l.state == FAILED_TO_START
    assert l.last.result == RESULT_FAILED_TO_START
    assert l.last.report_path is None
    # TASK.md 保留
    assert task_file.exists()
    assert task_file.read_text(encoding="utf-8") == "content"


# ---------- Windows no-console（AAF-v0.4-TASK-002-FIX-003） ----------

@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW 是 Windows-only flag")
def test_launcher_popen_uses_create_no_window_on_windows(make_launcher, tmp_path):
    """Windows：launcher 启动 run.py 的 Popen 必须传 CREATE_NO_WINDOW（不新建 console 窗口）。"""
    l = make_launcher(exit_code=0)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "REPORT.md").write_text("# R", encoding="utf-8")
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1") is True
    assert _wait_done(l)
    kwargs = l._fake_kwargs[0]
    assert kwargs.get("creationflags", 0) & launcher.subprocess.CREATE_NO_WINDOW, (
        f"launcher Popen 未传 CREATE_NO_WINDOW (kwargs={kwargs})"
    )
    # 原有 Popen 参数保持完整
    assert kwargs.get("stdout") == launcher.subprocess.PIPE
    assert kwargs.get("stderr") == launcher.subprocess.STDOUT
    assert kwargs.get("text") is True
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"


def test_launcher_popen_non_windows_no_creationflags(make_launcher, tmp_path, monkeypatch):
    """非 Windows：launcher 不得传 Windows-only creationflags（platform-safe）。"""
    monkeypatch.setattr(subprocess_utils, "_IS_WINDOWS", False)
    l = make_launcher(exit_code=0)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "REPORT.md").write_text("# R", encoding="utf-8")
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1") is True
    assert _wait_done(l)
    assert "creationflags" not in l._fake_kwargs[0]


# ---------- REPORT 定位 ----------

def test_report_missing_marks_not_found(make_launcher, tmp_path):
    l = make_launcher(exit_code=0)
    out = tmp_path / "out"
    out.mkdir(parents=True)  # 无 REPORT.md
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1") is True
    assert _wait_done(l)
    assert l.state == FINISHED
    assert l.last.result == RESULT_REPORT_NOT_FOUND
    assert l.last.report_path is None


def test_failed_exit_marks_failed(make_launcher, tmp_path):
    l = make_launcher(exit_code=2)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "REPORT.md").write_text("# R", encoding="utf-8")
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1") is True
    assert _wait_done(l)
    assert l.last.result == RESULT_FAILED
    assert l.last.exit_code == 2
    assert l.last.report_path is None


# ---------- Last info 持久化 ----------

def test_last_info_persisted(make_launcher, tmp_path, monkeypatch):
    import bridge.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path / "cfg")
    l = make_launcher(exit_code=0)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "REPORT.md").write_text("# R", encoding="utf-8")
    l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1")
    assert _wait_done(l)
    saved = l.load_last()
    assert saved is not None
    assert saved.task_id == "AAF-T1"
    assert saved.result == RESULT_FINISHED
    assert saved.report_path == str(out / "REPORT.md")
    # 磁盘文件存在
    assert (tmp_path / "cfg" / "last_run.json").exists()


def test_load_last_missing_returns_none(make_launcher, tmp_path, monkeypatch):
    import bridge.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path / "nope")
    l = make_launcher(exit_code=0)
    assert l.load_last() is None


def test_output_dir_convention(tmp_path):
    p = FrameworkLauncher.default_output_dir(str(tmp_path), "AAF-T1")
    assert p == tmp_path / ".aaf" / "AAF-T1"


# ---------- 异常释放（ISSUE-1 回归） ----------

class _ExplodingProc:
    stdout = None

    def wait(self):
        raise RuntimeError("boom")


def test_wait_exception_releases_running_state(make_launcher, tmp_path, monkeypatch):
    """wait 抛异常时，state 必须从 RUNNING 释放，否则后续启动永久被拒。"""
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: _ExplodingProc())
    done = threading.Event()
    captured = {}

    def on_finished(last, output):
        captured["last"] = last
        done.set()

    l = FrameworkLauncher(run_py=tmp_path / "run.py", on_finished=on_finished)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-T1") is True
    assert l.state == RUNNING
    assert done.wait(3.0)
    # state 已释放（不再是 RUNNING），result 标记失败
    assert l.state == FINISHED
    assert l.last.result == RESULT_FAILED
    # 后续可以再次启动
    l._done = done  # 复用 fixture 辅助
    started = l.launch(tmp_path / "T2.md", str(tmp_path), out, "AAF-T2")
    assert started is True
