"""Phase E / TASK-005-C — Status Window Cancel UX 真实 Windows E2E（req 11 A–G）。

约束（req 33 延续）：所有 force kill 只针对 deterministic dummy runner 进程树
（tests/fixtures/dummy_runner.py），绝不指向真实 Hermes / WorkBuddy / Codex 会话。

覆盖（req 11）：
A. Soft cancel while Hermes（dummy 运行中）→ STOP_REQUESTED → CANCELLED；
   后续 agent 不启动（无 prompt 产物）
B. Soft cancel between agents（handshake 完成后）→ 已完成产物保留 → CANCELLED
C. Normal completion wins race → canonical SUCCESS 保持 + late cancel absorbed →
   UI 显示「任务已先完成」
D. Soft timeout → 不自动 kill → UI 提供 force option（CANCELLING + can_force）
E. Verified force（二次确认语义，确认对话框单测覆盖）→ owned dummy 进程树终止
   + 结构化 evidence + CANCELLED；unrelated sibling 存活
F. Wrong / uncertain ownership → Force refused → 目标进程存活 → UI 无法安全停止
G. Bridge/status window restart → cancellation / terminal 状态从 artifacts 恢复
   （instance B 无内存，recover_launches + collect_cancel_ui）

UI 状态断言统一走 status_window.collect_cancel_ui（collect_status 的取消 UX 层），
驱动真实 launcher + 真实 artifacts。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import psutil

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import control as control_mod
from ai_agent_framework import force_evidence as fe_mod
from ai_agent_framework.task_lifecycle import read_status

from bridge import launch_registry as reg_mod
from bridge import launcher as launcher_mod
from bridge import ownership as own_mod
from bridge import status_window as sw
from bridge.launcher import FrameworkLauncher, RESULT_CANCELLED, RESULT_FINISHED
from bridge.status_window import (
    CANCEL_UI_CANCELLED,
    CANCEL_UI_CANCELLING,
    CANCEL_UI_COMPLETED,
    CANCEL_UI_RUNNING,
    CANCEL_UI_STOP_REQUESTED,
    CANCEL_UI_STOP_UNSAFE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DUMMY_RUNNER = REPO_ROOT / "tests" / "fixtures" / "dummy_runner.py"

TID = "T-CANCEL-UI-E2E"

VALID_TASK = """# Task ID
T-CANCEL-UI-E2E

# Task Name
Phase E cancel UI E2E

# Objective
真实 Windows 状态窗口取消闭环

# Acceptance
1. 通过
"""


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    return task_file


def _old_iso(seconds: float = 60.0) -> str:
    return (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def _bridge_root_env(tmp_path, monkeypatch):
    """Core finalizer CLI 子进程从 canonical Bridge registry root（AAF_BRIDGE_DIR，
    子进程继承）推导 registry/evidence 路径——与 launcher 注入的 registry_dir 相同。"""
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path / "aaf-bridge"))
    yield tmp_path / "aaf-bridge" / "launches"


def _wait_until(fn, timeout: float = 20.0, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _taskkill(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        pass


def _launch_dummy(tmp_path: Path, *, spawn_child: bool = False, sleep: float = 300.0,
                  dummy_mode: str | None = None, monkeypatch=None) -> tuple[FrameworkLauncher, Path, Path, Path, threading.Event, dict]:
    ws = tmp_path / "ws"
    out = ws / ".aaf" / TID
    reg_dir = tmp_path / "aaf-bridge" / "launches"
    task_file = _write_task(tmp_path)
    done = threading.Event()
    captured: dict = {}

    launcher = FrameworkLauncher(
        run_py=DUMMY_RUNNER, registry_dir=reg_dir,
        on_finished=lambda last, output: (captured.__setitem__("last", last), captured.__setitem__("output", output), done.set()),
    )
    if monkeypatch is not None:
        monkeypatch.setenv("AAF_DUMMY_SLEEP", str(sleep))
        if dummy_mode:
            monkeypatch.setenv("AAF_DUMMY_MODE", dummy_mode)
        if spawn_child:
            monkeypatch.setenv("AAF_DUMMY_SPAWN_CHILD", "1")
    return launcher, task_file, ws, out, done, captured


def _wait_handshake(launcher: FrameworkLauncher, out: Path, timeout: float = 25.0) -> tuple[str, int]:
    task_id = TID
    lid = launcher._active_launch[task_id]

    def ready() -> bool:
        ctrl, _ = control_mod.read_control(out)
        if ctrl is None or ctrl.get("runner_pid") is None:
            return False
        try:
            data = read_status(out)
        except Exception:  # noqa: BLE001
            return False
        return data is not None and data.get("status") == "RUNNING"

    assert _wait_until(ready, timeout), "runner handshake / canonical RUNNING 超时"
    ctrl, _ = control_mod.read_control(out)
    return lid, int(ctrl["runner_pid"])


def _ui_state(launcher, out: Path) -> sw.CancelUi:
    """collect_status 的取消 UX 层：从真实 artifacts 推导当前 UI 状态。"""
    data = read_status(out)
    return sw.collect_cancel_ui(launcher, TID, out, data.get("status") if data else None)


def _runner_child_pid(runner_pid: int) -> int | None:
    try:
        children = psutil.Process(runner_pid).children(recursive=True)
        return children[0].pid if children else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# A. Soft cancel while Hermes（dummy 运行中）→ CANCELLED；后续 agent 不启动
# ---------------------------------------------------------------------------


def test_e2e_a_soft_cancel_while_running(tmp_path, monkeypatch):
    launcher, task_file, ws, out, done, captured = _launch_dummy(
        tmp_path, dummy_mode="cancel-aware", monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    _wait_handshake(launcher, out)

    # UI 状态：正在运行（可停止）
    assert _ui_state(launcher, out).state == CANCEL_UI_RUNNING
    assert _ui_state(launcher, out).can_stop

    # [停止当前任务] 动作（main._request_stop 的核心写入）：只写 cancel.request
    cancel_mod.write_cancel_request(out, TID)
    assert (out / "cancel.request").exists()

    # UI 状态：请求停止（等待安全退出，无 Force）——dummy 等 cancel.gate 才收敛，
    # 中间状态窗口完全确定
    cu = _ui_state(launcher, out)
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    assert not cu.can_stop and not cu.can_force
    assert sw.MSG_WAITING_EXIT in cu.message

    # 放行收敛（测试与 dummy 之间的门闩）
    (out / "cancel.gate").write_text("go", encoding="utf-8")

    # 收敛：canonical CANCELLED 全套产物
    assert done.wait(30.0), "dummy 未在软取消后收敛"
    assert captured["last"].result == RESULT_CANCELLED
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data.get("cancel_mode") == "soft"
    assert (out / "run.json").exists()
    assert (out / "REPORT.md").exists()
    # 后续 agent 不启动：无任何 agent prompt 产物
    assert not (out / "hermes_prompt.md").exists()
    assert not (out / "workbuddy_prompt.md").exists()
    assert not (out / "codex_prompt.md").exists()
    # UI 状态：已取消
    assert _ui_state(launcher, out).state == CANCEL_UI_CANCELLED


# ---------------------------------------------------------------------------
# B. Soft cancel between agents → 已完成结果保留 → CANCELLED
# ---------------------------------------------------------------------------


def test_e2e_b_soft_cancel_between_agents_preserves_results(tmp_path, monkeypatch):
    launcher, task_file, ws, out, done, captured = _launch_dummy(
        tmp_path, dummy_mode="cancel-aware", monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher, out)

    # 模拟已完成阶段的结果产物（agent 1 完成；取消只作用于后续阶段，req 14）
    (out / "hermes_result.md").write_text("已完成阶段结果保留", encoding="utf-8")

    # 两个 agent 之间发停止请求 → UI 请求停止（中间状态窗口确定）
    cancel_mod.write_cancel_request(out, TID)
    cu = _ui_state(launcher, out)
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    (out / "cancel.gate").write_text("go", encoding="utf-8")

    assert done.wait(30.0)
    assert captured["last"].result == RESULT_CANCELLED
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    # 已完成结果保留；后续未启动
    assert (out / "hermes_result.md").exists()
    assert not (out / "workbuddy_prompt.md").exists()
    assert not (out / "codex_prompt.md").exists()
    # cancel.request 保留为证据（§6.6）
    assert (out / "cancel.request").exists()
    assert _ui_state(launcher, out).state == CANCEL_UI_CANCELLED


# ---------------------------------------------------------------------------
# C. Normal completion wins race → canonical 保持 SUCCESS；late cancel absorbed
# ---------------------------------------------------------------------------


def test_e2e_c_normal_completion_wins_race(tmp_path, monkeypatch):
    launcher, task_file, ws, out, done, captured = _launch_dummy(
        tmp_path, sleep=3.0, dummy_mode="commit-success-no-derived", monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    assert done.wait(40.0)
    assert captured["last"].result == RESULT_FINISHED
    data = read_status(out)
    assert data["status"] == "SUCCESS"  # canonical 终态

    # late cancel（canonical 已终态后写入——request 只是外部意图，req 8）
    cancel_mod.write_cancel_request(out, TID)
    data = read_status(out)
    assert data["status"] == "SUCCESS"  # canonical 保持原终态，不被覆盖
    assert data["terminal_generation"] == 1
    # UI 跟随 canonical：已完成（任务已先完成）
    cu = _ui_state(launcher, out)
    assert cu.state == CANCEL_UI_COMPLETED
    assert sw.MSG_COMPLETED_FIRST in cu.message
    assert not cu.can_stop


# ---------------------------------------------------------------------------
# D. Soft timeout → 不自动 kill → UI 提供 force option
# ---------------------------------------------------------------------------


def test_e2e_d_soft_timeout_no_auto_kill_force_option(tmp_path, monkeypatch):
    launcher, task_file, ws, out, done, captured = _launch_dummy(tmp_path, monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher, out)

    # fresh 请求 → 未达超时 → UI 请求停止（无 Force）
    cancel_mod.write_cancel_request(out, TID)
    cu = _ui_state(launcher, out)
    assert cu.state == CANCEL_UI_STOP_REQUESTED and not cu.can_force

    # 旧请求（超时）→ UI 正在取消 + Force 可用；进程未被自动 kill（req 4/17）
    cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(120))
    cu = _ui_state(launcher, out)
    assert cu.state == CANCEL_UI_CANCELLING and cu.can_force
    assert "强制停止" in cu.message
    assert psutil.pid_exists(runner_pid), "soft timeout 不得自动 kill"
    ctrl, _ = control_mod.read_control(out)
    assert ctrl.get("force_terminate_requested") is not True
    entry, _ = reg_mod.read_registry(lid, root=launcher._registry_dir)
    assert "force_terminate_requested_at" not in entry  # 无任何 force 动作发生

    _taskkill(runner_pid)


# ---------------------------------------------------------------------------
# E. Verified force（二次确认语义）→ owned 进程树终止 + evidence + CANCELLED
# ---------------------------------------------------------------------------
# 二次确认对话框（ask_force_stop）由单测覆盖（confirm=False → 零终止调用）；
# 此处驱动「已确认」后的 verified backend 全链路（req 11 E）。


def test_e2e_e_verified_force_confirmed_kills_owned_tree(tmp_path, monkeypatch):
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        launcher, task_file, ws, out, done, captured = _launch_dummy(
            tmp_path, spawn_child=True, monkeypatch=monkeypatch)
        assert launcher.launch(task_file, str(ws), out, TID) is True
        lid, runner_pid = _wait_handshake(launcher, out)
        assert _wait_until(lambda: _runner_child_pid(runner_pid) is not None, 10.0), "child 派生超时"
        child_pid = _runner_child_pid(runner_pid)

        cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(120))
        cu = _ui_state(launcher, out)
        assert cu.state == CANCEL_UI_CANCELLING and cu.can_force

        # 「已确认」→ verified force-cancel backend
        res = launcher.request_force_cancel(TID)
        assert res.ok, res.refusal_reason
        assert res.verdict is not None and res.verdict.ok()
        # owned 进程树终止（runner + child）
        assert _wait_until(lambda: not psutil.pid_exists(runner_pid), 10.0)
        assert _wait_until(lambda: not psutil.pid_exists(child_pid), 10.0)
        # unrelated sibling 存活（req 10：无关进程不受影响）
        assert psutil.pid_exists(sibling.pid), "无关 sibling 被误杀！"
        # 结构化 evidence + 成功终止证明（FIX-001 req 5）
        assert res.evidence_path is not None
        ev, err = fe_mod.read_force_evidence(res.evidence_path)
        assert err is None
        assert ev["termination_exit_status"] == fe_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS
        assert ev["verification_result"] == own_mod.VERIFIED
        # canonical CANCELLED + UI 已取消
        assert res.canonical_status == "CANCELLED"
        assert done.wait(25.0)
        assert captured["last"].result == RESULT_CANCELLED
        assert _ui_state(launcher, out).state == CANCEL_UI_CANCELLED
    finally:
        _taskkill(sibling.pid)


# ---------------------------------------------------------------------------
# F. Wrong / uncertain ownership → Force refused → 目标存活 → UI 无法安全停止
# ---------------------------------------------------------------------------


def test_e2e_f_wrong_ownership_force_refused_target_alive(tmp_path, monkeypatch):
    launcher, task_file, ws, out, done, captured = _launch_dummy(tmp_path, monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher, out)
    cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(120))

    # 篡改 control runner_creation_time → ownership 失败
    control_mod.update_control(out, {"runner_creation_time": "2020-01-01T00:00:00.000"}, task_id=TID)
    verdict = own_mod.verify_runner_ownership(task_id=TID, launch_id=lid,
                                              registry_dir=launcher._registry_dir)
    assert not verdict.ok()
    res = launcher.request_force_cancel(TID, lid, require_eligibility=False)
    assert not res.ok and res.refusal_reason.startswith("OWNERSHIP_")
    assert psutil.pid_exists(runner_pid), "unverified force 不得 kill 目标进程"
    data = read_status(out)
    assert data.get("status") not in ("CANCELLED", "SUCCESS", "FAILED", "WAITING")

    # UI：backend 不明确 eligible → 无法安全停止（fail closed，req 6）
    cu = _ui_state(launcher, out)
    assert cu.state in (CANCEL_UI_STOP_UNSAFE, CANCEL_UI_CANCELLING)  # eligible=False 分支
    assert not cu.can_force
    if cu.state == CANCEL_UI_STOP_UNSAFE:
        assert "无法安全强制停止" in cu.message

    _taskkill(runner_pid)


# ---------------------------------------------------------------------------
# G. Bridge / status window restart → 状态从 artifacts 恢复（req 9/11 G）
# ---------------------------------------------------------------------------


def test_e2e_g_restart_recovers_cancel_state_from_artifacts(tmp_path, monkeypatch):
    launcher_a, task_file, ws, out, done_a, captured_a = _launch_dummy(tmp_path, monkeypatch=monkeypatch)
    assert launcher_a.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher_a, out)
    cancel_mod.write_cancel_request(out, TID)  # fresh：软取消窗口内

    # instance B：全新对象（逻辑重启；零内存）→ recover_launches 三方认证
    launcher_b = FrameworkLauncher(run_py=DUMMY_RUNNER, registry_dir=launcher_a._registry_dir)
    recovered = launcher_b.recover_launches(launcher_a._registry_dir)
    assert lid in recovered and recovered[lid].result == own_mod.REAUTHENTICATED

    # UI 状态完全由 artifacts 推导恢复：请求停止（无 Force，软窗口内）
    cu = _ui_state(launcher_b, out)
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    assert not cu.can_force

    # 同一 artifacts 在新窗口实例推导结果一致（无 UI 内存依赖）
    cu2 = sw.collect_cancel_ui(launcher_b, TID, out, read_status(out).get("status"))
    assert cu2.state == cu.state and cu2.message == cu.message

    # 超时后 force capability 经重启恢复仍可用（REAUTHENTICATED）
    cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(120))
    cu3 = _ui_state(launcher_b, out)
    assert cu3.state == CANCEL_UI_CANCELLING and cu3.can_force
    res = launcher_b.request_force_cancel(TID)
    assert res.ok, res.refusal_reason
    assert res.canonical_status == "CANCELLED"
    assert not psutil.pid_exists(runner_pid)
    assert _ui_state(launcher_b, out).state == CANCEL_UI_CANCELLED
