"""Phase E / TASK-005-B — 真实 Windows Ownership / Force Cancel E2E（req 33/34/35）。

约束（req 33）：force kill 测试**只针对 deterministic dummy runner 进程树**
（tests/fixtures/dummy_runner.py），绝不指向真实 Hermes / WorkBuddy / Codex 会话。

E2E 1（positive，req 34）：Launcher → dummy runner（+ 子进程树）→ registry/control
handshake → ownership VERIFIED → soft cancel timeout → explicit force request →
verified process tree termination → Core recovery finalizer → task.json CANCELLED →
run.json CANCELLED → REPORT CANCELLED → last_run CANCELLED → registry EXITED；
unrelated sibling process 存活（进程树包含性）；child 进程同树死亡。

E2E 2（negative，req 34）：wrong/stale ownership evidence（tamper creation time）→
force refused → 目标进程仍存活。

E2E 3（restart reauthentication，req 35）：instance A launch → registry/control 持久化
→ instance B（新对象，逻辑重启）recover_launches → REAUTHENTICATED → force capability
可用（kill 成功）；negative：tamper control → UNCERTAIN → force refused → 存活。

W/X（req 15/17）：soft timeout 未到 → 不自动 kill、force 被拒；超时后显式 force 生效。
AH：force-kill 后 runner 非零退出不被映射为 FAILED。
AI/AJ：wait thread 触发 Core reconciliation 恢复缺 run.json / REPORT.md 的派生物。
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
from bridge.launcher import FrameworkLauncher, RESULT_CANCELLED, RESULT_FINISHED

REPO_ROOT = Path(__file__).resolve().parent.parent
DUMMY_RUNNER = REPO_ROOT / "tests" / "fixtures" / "dummy_runner.py"

TID = "T-FORCE-E2E"

VALID_TASK = """# Task ID
T-FORCE-E2E

# Task Name
Phase E force E2E

# Objective
真实 Windows force cancel 闭环

# Acceptance
1. 通过
"""


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    return task_file


def _old_iso(seconds: float = 60.0) -> str:
    return (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _wait_until(fn, timeout: float = 20.0, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _taskkill(pid: int) -> None:
    """测试清理：只杀测试自己创建的 dummy 进程树。"""
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
            monkeypatch.setenv("AAF_DUMMY_MODE", dummy_mode)  # Popen 继承 env → dummy 生效
        if spawn_child:
            monkeypatch.setenv("AAF_DUMMY_SPAWN_CHILD", "1")
    return launcher, task_file, ws, out, done, captured


def _wait_handshake(launcher: FrameworkLauncher, out: Path, timeout: float = 25.0) -> tuple[str, int]:
    """等待 dummy handshake + canonical RUNNING 就绪 → (launch_id, runner_pid)。

    - canonical task.json 必须存在（非终态）——recovery finalizer 的 identity 校验要求
    - registry 身份采纳是**惰性**的（在 request_force_cancel / recover 验证路径内
      完成），此处不要求 registry == control
    """
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


# ---------------------------------------------------------------------------
# W/X. soft timeout 不自动 kill；显式 force 才生效（req 15/17）
# ---------------------------------------------------------------------------


def test_wx_soft_timeout_does_not_auto_kill_then_explicit_force(tmp_path):
    launcher, task_file, ws, out, done, captured = _launch_dummy(tmp_path)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher, out)

    # 刚写入的 cancel.request（fresh）→ 未达 timeout → 不 force
    cancel_mod.write_cancel_request(out, TID)
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert not eligible and "SOFT_CANCEL_TIMEOUT_NOT_REACHED" in why
    res = launcher.request_force_cancel(TID, lid)
    assert not res.ok and "NOT_ELIGIBLE" in res.refusal_reason
    # 未自动 kill：进程存活、control 无 force 标记
    assert psutil.pid_exists(runner_pid)
    ctrl, _ = control_mod.read_control(out)
    assert ctrl["force_terminate_requested"] is False
    entry, _ = reg_mod.read_registry(lid, root=launcher._registry_dir)
    assert "force_terminate_requested_at" not in entry

    # 旧 cancel.request（60s 前）→ 达 timeout → 显式 force 生效（X）
    cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(60))
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert eligible
    res = launcher.request_force_cancel(TID, lid)
    assert res.ok, res.refusal_reason
    assert res.canonical_status == "CANCELLED"
    assert not psutil.pid_exists(runner_pid)
    assert done.wait(20.0)
    assert captured["last"].result == RESULT_CANCELLED  # AH：非零退出不映射 FAILED
    data = read_status(out)
    assert data["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# E2E 1. 正向全链路（req 34：含进程树包含 + 无关进程存活）
# ---------------------------------------------------------------------------


def test_e2e_positive_verified_force_cancel_full_chain(tmp_path, monkeypatch):
    # 无关 sibling：测试直接派生（不在 dummy 进程树内）→ force 后必须存活
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        launcher, task_file, ws, out, done, captured = _launch_dummy(tmp_path, spawn_child=True, monkeypatch=monkeypatch)
        assert launcher.launch(task_file, str(ws), out, TID) is True
        lid, runner_pid = _wait_handshake(launcher, out)
        # 等 child 派生
        assert _wait_until(lambda: psutil.pid_exists(runner_pid) and _child_pid(launcher, out) is not None), "child 派生超时"
        child_pid = _child_pid(launcher, out)

        # ownership VERIFIED（真实 live 身份；三方一致；ownership_status 含身份采纳）
        verdict = launcher.ownership_status(TID)
        assert verdict is not None and verdict.result == own_mod.VERIFIED, verdict.failures if verdict else "no verdict"

        # soft cancel → timeout → explicit force（§6B.17 完整闭环）
        cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(60))
        res = launcher.request_force_cancel(TID)
        assert res.ok, res.refusal_reason
        assert res.verdict is not None and res.verdict.ok()
        assert res.evidence_path is not None

        # verified process tree termination：owned tree 死亡（runner + child）
        assert _wait_until(lambda: not psutil.pid_exists(runner_pid), 10.0)
        assert _wait_until(lambda: not psutil.pid_exists(child_pid), 10.0)
        # unrelated sibling 存活（req 18/33：不误杀无关进程）
        assert psutil.pid_exists(sibling.pid), "无关 sibling 被误杀！"

        # force evidence（AA）：结构化 + 字段完整
        ev, err = fe_mod.read_force_evidence(res.evidence_path)
        assert err is None
        assert ev["launch_id"] == lid
        assert ev["task_id"] == TID
        assert ev["verification_result"] == own_mod.VERIFIED
        assert all(ev["verification_checks"].values())
        assert ev["termination_exit_status"] == 0 or ev["termination_exit_status"] == 128

        # Core recovery finalizer → canonical CANCELLED 全套产物
        assert res.canonical_status == "CANCELLED"
        data = read_status(out)
        assert data["status"] == "CANCELLED"
        assert data["cancel_mode"] == "force"
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert run["status"] == "CANCELLED"
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        assert "## Current Status\nCANCELLED" in report

        # wait thread → last_run 跟随 canonical（AL；AH：exit != 0 不判 FAILED）
        assert done.wait(25.0)
        assert captured["last"].result == RESULT_CANCELLED
        assert captured["last"].launch_id == lid
        assert captured["last"].exit_code != 0  # taskkill 后非零退出是 evidence

        # registry EXITED（AK）+ force evidence 字段（wait thread 的 mark_exited
        # 可能把 exit_result 更新为 canonical 结果 CANCELLED——两者都合法）
        entry, _ = reg_mod.read_registry(lid, root=launcher._registry_dir)
        assert entry["state"] == reg_mod.REGISTRY_STATE_EXITED
        assert entry["force_terminate_requested_at"]
        assert entry["force_termination_exit_status"] in (0, 128)
        assert entry["exit_result"] in ("FORCE_TERMINATED", RESULT_CANCELLED)
    finally:
        _taskkill(sibling.pid)


def _child_pid(launcher: FrameworkLauncher, out: Path) -> int | None:
    """dummy runner 派生的子进程 pid（以 control 自报的真实 runner 为父）。

    注意：registry.runner_pid 在身份采纳前可能是 Popen 直连子（uv venv 重定向壳），
    其 children 含真实 runner 本身——必须以 control.runner_pid（真实解释器）为准。
    """
    ctrl, _ = control_mod.read_control(out)
    if not ctrl or not ctrl.get("runner_pid"):
        return None
    try:
        proc = psutil.Process(int(ctrl["runner_pid"]))
    except Exception:  # noqa: BLE001
        return None
    children = proc.children(recursive=True)
    return children[0].pid if children else None


# ---------------------------------------------------------------------------
# E2E 2. negative：wrong/stale ownership evidence → force refused（req 34）
# ---------------------------------------------------------------------------


def test_e2e_negative_wrong_ownership_force_refused_target_alive(tmp_path):
    launcher, task_file, ws, out, done, captured = _launch_dummy(tmp_path)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher, out)

    # 篡改 control runner_creation_time（模拟 stale / PID-recycle 场景；registry 的
    # 身份采纳只同步 runner 自报身份，不覆盖 control——篡改 control 是确定性负路径）
    control_mod.update_control(out, {"runner_creation_time": "2020-01-01T00:00:00.000"}, task_id=TID)
    verdict = own_mod.verify_runner_ownership(task_id=TID, launch_id=lid,
                                              registry_dir=launcher._registry_dir)
    assert not verdict.ok()
    res = launcher.request_force_cancel(TID, lid, require_eligibility=False)
    assert not res.ok and res.refusal_reason.startswith("OWNERSHIP_")
    assert psutil.pid_exists(runner_pid), "unverified force 不应 kill 目标进程"
    # canonical 未被改动
    data = read_status(out)
    assert "status" in data and data["status"] not in ("CANCELLED", "SUCCESS", "FAILED", "WAITING")
    _taskkill(runner_pid)


# ---------------------------------------------------------------------------
# E2E 3. restart reauthentication（req 35）
# ---------------------------------------------------------------------------


def test_e2e_restart_reauthentication_positive(tmp_path):
    """instance A launch → 持久化 → instance B（逻辑重启）三方验证 → REAUTHENTICATED
    → force capability 可用（§6B.13；launcher_instance_id 不要求相同——V）。"""
    launcher_a, task_file, ws, out, done_a, captured_a = _launch_dummy(tmp_path)
    assert launcher_a.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher_a, out)
    cancel_mod.write_cancel_request(out, TID, requested_at=_old_iso(60))

    # instance B：全新对象（无任何 in-memory state；registry_dir 指向同一持久根）
    launcher_b = FrameworkLauncher(run_py=DUMMY_RUNNER, registry_dir=launcher_a._registry_dir)
    recovered = launcher_b.recover_launches(launcher_a._registry_dir)
    assert lid in recovered
    assert recovered[lid].result == own_mod.REAUTHENTICATED, recovered[lid].failures
    assert recovered[lid].registry["launcher_instance_id"] != launcher_b.launcher_instance_id  # V

    res = launcher_b.request_force_cancel(TID)
    assert res.ok, res.refusal_reason
    assert res.canonical_status == "CANCELLED"
    assert not psutil.pid_exists(runner_pid)
    assert read_status(out)["status"] == "CANCELLED"
    # instance B 的 wait thread 不存在（重启不接管 wait；RW-021 边界）——
    # force 的 canonical 由 request_force_cancel 同步 finalizer 提交


def test_e2e_restart_reauthentication_negative(tmp_path):
    """instance B：control 创建时间被篡改 → UNCERTAIN → force refused → 存活。"""
    launcher_a, task_file, ws, out, done_a, captured_a = _launch_dummy(tmp_path)
    assert launcher_a.launch(task_file, str(ws), out, TID) is True
    lid, runner_pid = _wait_handshake(launcher_a, out)

    control_mod.update_control(out, {"runner_creation_time": "2020-01-01T00:00:00.000"}, task_id=TID)

    launcher_b = FrameworkLauncher(run_py=DUMMY_RUNNER, registry_dir=launcher_a._registry_dir)
    recovered = launcher_b.recover_launches(launcher_a._registry_dir)
    assert lid in recovered
    assert not recovered[lid].ok()  # UNCERTAIN / STALE
    # 显式指定 launch_id（recover 未采纳 → _active_launch 无映射；仍必须走
    # ownership 拒绝路径，不得 NO_ACTIVE_LAUNCH 短路）
    res = launcher_b.request_force_cancel(TID, lid, require_eligibility=False)
    assert not res.ok and res.refusal_reason.startswith("OWNERSHIP_")
    assert psutil.pid_exists(runner_pid), "UNCERTAIN ownership 不得 force kill"
    _taskkill(runner_pid)


# ---------------------------------------------------------------------------
# AI/AJ. wait thread → Core reconciliation 恢复派生物（req 32-AI/AJ / req 27）
# ---------------------------------------------------------------------------


def test_ai_reconciliation_missing_runjson(tmp_path, monkeypatch):
    """canonical SUCCESS committed + run.json 缺失 → wait thread 触发 Core
    reconciliation → run.json 补齐跟随 canonical；last_run 跟随 canonical。"""
    launcher, task_file, ws, out, done, captured = _launch_dummy(
        tmp_path, sleep=5.0, dummy_mode="commit-success-no-runjson", monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    assert done.wait(30.0)
    assert captured["last"].result == RESULT_FINISHED
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    assert run["terminal_generation"] == 1
    data = read_status(out)
    assert data["status"] == "SUCCESS"  # canonical 未变（reconciliation 不改 canonical）
    lid = captured["last"].launch_id
    entry, _ = reg_mod.read_registry(lid, root=launcher._registry_dir)
    assert entry["state"] == reg_mod.REGISTRY_STATE_EXITED  # AK


def test_aj_reconciliation_missing_report(tmp_path, monkeypatch):
    """canonical SUCCESS committed + REPORT.md 缺失 → reconciliation 重建 REPORT。"""
    launcher, task_file, ws, out, done, captured = _launch_dummy(
        tmp_path, sleep=5.0, dummy_mode="commit-success-no-report", monkeypatch=monkeypatch)
    assert launcher.launch(task_file, str(ws), out, TID) is True
    assert done.wait(30.0)
    assert captured["last"].result == RESULT_FINISHED
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    assert read_status(out)["status"] == "SUCCESS"
