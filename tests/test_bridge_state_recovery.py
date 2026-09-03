"""AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001 — 聚焦测试。

覆盖（TASK req 11）：
- restart during live task -> same task restored as RUNNING（+ identity 保持）
- restored task retains correct task_id / launch_id / runner identity
- restart after finished task -> terminal status restored（registry ACTIVE +
  canonical terminal = 旧实例崩溃遗留 → EXITED TERMINAL + last_run 镜像）
- dead runner + non-terminal artifacts -> RECOVERY_NEEDED（绝不 FAILED）
- stale registry handled safely（terminal 收敛 / 孤儿显式 / PREPARED 保守保留）
- duplicate hotkey while running -> 无第二 runner、无 view overwrite
- valid active recovered task 优先于 last_run
- test-specific AAF_BRIDGE_DIR 防止 production last_run 污染
- F-I-RUN test fixture 不能泄漏进真实用户 state

真实子进程场景用 tests/fixtures/dummy_runner.py（sleep 模式，taskkill 收尾）与
tests/fixtures/dummy_recover_runner.py（sleep 后提交 SUCCESS canonical 全套）；
绝不指向真实 Agent 会话。全部 registry / last_run / config 落在 conftest 的
AAF_BRIDGE_DIR 隔离根内，真实 ~/.aaf-bridge 只读快照对比（零写入）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ai_agent_framework import control as control_mod
from ai_agent_framework import task_lifecycle
from ai_agent_framework.task_lifecycle import update_status, read_status

from bridge import config as cfg_mod
from bridge import duplicate as dup_mod
from bridge import intake
from bridge import launch_registry as reg_mod
from bridge import status_window as sw
from bridge import task_io
from bridge.launcher import (
    RESULT_FINISHED,
    RESULT_RECOVERY_NEEDED,
    FrameworkLauncher,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DUMMY_RUNNER = REPO_ROOT / "tests" / "fixtures" / "dummy_runner.py"
RECOVER_RUNNER = REPO_ROOT / "tests" / "fixtures" / "dummy_recover_runner.py"

REAL_STATE_DIR = Path.home() / ".aaf-bridge"
REAL_LAST_RUN = REAL_STATE_DIR / "last_run.json"
REAL_LAUNCHES_DIR = REAL_STATE_DIR / "launches"


def _task_text(ws: Path, task_id: str) -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {task_id}
Task Name: Bridge State Recovery 测试任务
Workspace: {ws}

Objective:
验证 Bridge restart 状态恢复

Acceptance:
1. 通过
AAF_TASK_END"""


def _ws(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _bridge_root() -> Path:
    """当前测试的 AAF_BRIDGE_DIR 隔离根（conftest autouse 设置）。"""
    return Path(os.environ["AAF_BRIDGE_DIR"])


def _reg_dir() -> Path:
    return _bridge_root() / "launches"


def _make_launcher(run_py: Path, done: threading.Event | None = None) -> FrameworkLauncher:
    def _on_finished(last, output):
        if done is not None:
            done.set()

    return FrameworkLauncher(run_py=run_py, registry_dir=_reg_dir(), on_finished=_on_finished)


def _wait_until(fn, timeout: float = 30.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _taskkill(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001 —— 清理失败不掩盖断言结果
        pass


def _wait_handshake_lid(lid: str, out_dir: Path, timeout: float = 20.0) -> tuple[str, int]:
    """等待 runner handshake 最终回写（control runner_pid **连续两次读数稳定**）。

    launcher 在 Popen 后先写 Popen 直连子 pid（uv venv python 重定向壳场景），
    runner handshake 随后覆盖为自报真实解释器 pid（§6A.6-4/§6B.12-G）——只读
    一次可能捕获中间值；连续两次稳定读数保证取到最终身份。
    """
    def _stable():
        prev = None
        for _ in range(2):
            ctrl, _ = control_mod.read_control(out_dir)
            cur = (ctrl or {}).get("runner_pid")
            if cur is None or cur != prev:
                prev = cur
                time.sleep(0.3)
                continue
            return cur
        return None
    assert _wait_until(lambda: _stable() is not None, timeout=timeout), \
        "runner handshake 未在限时内稳定回写 control"
    # 稳定后再做一次最终确认读取
    for _ in range(10):
        ctrl, _ = control_mod.read_control(out_dir)
        if (ctrl or {}).get("runner_pid") is not None:
            return lid, int(ctrl["runner_pid"])
        time.sleep(0.2)
    raise AssertionError("runner handshake 未在限时内回写 control")


def sw_task_current(ws: Path, tid: str, tmp_path: Path):
    """构造 launcher.current 形状的 RunInfo（resolve 优先级测试用）。"""
    from bridge.launcher import RunInfo
    return RunInfo(
        task_id=tid,
        task_path=str(tmp_path / f"{tid}.md"),
        report_path=None, exit_code=None, result="RUNNING",
        output_dir=str(ws / ".aaf" / tid), launch_id="x" * 32,
    )


def _real_snapshot() -> tuple[bytes | None, int]:
    """真实用户 Bridge state 只读快照：(last_run bytes | None, launches 文件数)。"""
    last = REAL_LAST_RUN.read_bytes() if REAL_LAST_RUN.exists() else None
    count = 0
    if REAL_LAUNCHES_DIR.is_dir():
        count = len(list(REAL_LAUNCHES_DIR.glob("*.json")))
    return last, count


def _assert_real_state_untouched(before: tuple[bytes | None, int], *test_ids: str) -> None:
    last_now, count_now = _real_snapshot()
    assert last_now == before[0], "真实 ~/.aaf-bridge/last_run.json 被测试改写（隔离失效）"
    assert count_now == before[1], "真实 ~/.aaf-bridge/launches/ 被测试写入（隔离失效）"
    if last_now:
        text = last_now.decode("utf-8", errors="replace")
        for tid in test_ids:
            assert tid not in text, f"测试身份 {tid} 泄漏进真实 last_run.json"


# ===========================================================================
# 1) restart during live task -> 同一正式任务恢复为 RUNNING（identity 保持）
# ===========================================================================

def test_restart_during_live_task_restores_same_running_task(tmp_path, monkeypatch):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-live")
    tid = "SRV-LIVE-001"
    task_file = task_io.save_task(_task_text(ws, tid), str(ws), tid)

    monkeypatch.setenv("AAF_DUMMY_SLEEP", "60")  # 足够长的 live 窗口
    launcher_a = _make_launcher(DUMMY_RUNNER)
    out_dir = launcher_a.default_output_dir(str(ws), tid)
    assert launcher_a.launch(task_file, str(ws), out_dir, tid)
    assert launcher_a.state == "RUNNING"
    lid = launcher_a._active_launch[tid]
    _wait_handshake_lid(lid, out_dir)

    # last_run 先放入无关/泄漏身份（F-I-RUN 测试身份）：恢复的 live 任务必须优先
    last_run_file = cfg_mod.state_root() / "last_run.json"
    last_run_file.parent.mkdir(parents=True, exist_ok=True)
    last_run_file.write_text(
        json.dumps({"task_id": "F-I-RUN", "result": "FAILED",
                    "output_dir": str(tmp_path / "gone")}), encoding="utf-8")

    # 实例 B = Bridge restart（零内存；同一 registry root）
    launcher_b = _make_launcher(DUMMY_RUNNER)
    recovered = launcher_b.recover_launches(_reg_dir())
    assert lid in recovered
    assert recovered[lid].result == "REAUTHENTICATED"

    # launcher state 恢复 RUNNING + current task identity（requirement 2）
    assert launcher_b.state == "RUNNING"
    cur = launcher_b.current
    assert cur is not None
    assert cur.task_id == tid
    assert cur.launch_id == lid
    assert cur.output_dir == str(out_dir)
    # runner 身份保持（registry/control 持久权威；handshake 后两者一致且指向
    # live runner——uv venv 重定向壳场景 registry 已采纳 runner 自报身份）
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    ctrl, _ = control_mod.read_control(out_dir)
    assert reg is not None and ctrl is not None
    assert reg["runner_pid"] == ctrl.get("runner_pid"), "registry/control runner 身份不一致"
    # 状态窗口绑定到该正式任务（不被 last_run / F-I-RUN 覆盖；requirement 8）
    ref = sw.resolve_current_task(launcher_b)
    assert ref is not None and ref.task_id == tid and ref.output_dir == out_dir
    # canonical RUNNING 落盘后再收集快照（避免与 runner 首写竞争）
    assert _wait_until(lambda: (read_status(out_dir) or {}).get("status") == "RUNNING")
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid
    assert snap.overall_raw == "RUNNING"

    # 清理：kill dummy 进程树，等 watcher 收敛（状态释放，不僵尸占用）
    reg = reg_mod.read_registry(lid, root=_reg_dir())[0]
    _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
    assert _wait_until(lambda: launcher_b.state != "RUNNING", timeout=30)
    assert _assert_real_state_untouched(before, "SRV-LIVE-001", "F-I-RUN") is None


# ===========================================================================
# 2) restart after finished task -> terminal status restored（旧实例崩溃遗留）
# ===========================================================================

def test_recover_terminal_after_bridge_death_restores_terminal_state(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-dead")
    tid = "SRV-DONE-001"
    out_dir = ws / ".aaf" / tid
    out_dir.mkdir(parents=True)
    (out_dir / "TASK.md").write_text(_task_text(ws, tid), encoding="utf-8")
    (out_dir / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    task_lifecycle.finalize_terminal(
        out_dir, task_id=tid, status="SUCCESS",
        task_path=str(out_dir / "TASK.md"), workspace=str(ws),
        report_path=str(out_dir / "REPORT.md"), stage="COMPLETED", phase_state="SUCCESS",
    )
    (out_dir / "run.json").write_text(
        json.dumps({"status": "SUCCESS", "task_id": tid}), encoding="utf-8")

    # registry 仍是 ACTIVE RUNNING（旧 Bridge 在 wait thread 收尾前崩溃）+ dead pid
    lid = reg_mod.new_launch_id()
    argv = [sys.executable, str(DUMMY_RUNNER), str(out_dir / "TASK.md"),
            "--workspace", str(ws), "--output", str(out_dir), "--launch-id", lid]
    reg_mod.create_prepared(
        launch_id=lid, task_id=tid, workspace=str(ws), output_dir=str(out_dir),
        expected_runner_entry="dummy_runner.py", expected_command_line=argv,
        launcher_instance_id="dead-instance", root=_reg_dir(),
    )
    reg_mod.mark_running(lid, 4_294_967_294, "2026-09-01T00:00:00.000", root=_reg_dir())
    control_mod.write_control(
        out_dir, control_mod.new_control(
            task_id=tid, workspace=str(ws), launch_id=lid,
            launcher_pid=os.getpid(), launcher_instance_id="dead-instance",
            expected_runner_entry="dummy_runner.py", expected_command_line=argv,
        ), task_id=tid,
    )
    control_mod.update_control(out_dir, {"runner_pid": 4_294_967_294,
                                         "runner_creation_time": "2026-09-01T00:00:00.000"}, task_id=tid)

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    recovered = launcher_b.recover_launches(_reg_dir())
    assert lid in recovered
    # terminal 任务绝不恢复成 RUNNING
    assert launcher_b.state != "RUNNING" and launcher_b.current is None
    # registry ACTIVE 镜像收敛 EXITED（不动 canonical）
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg is not None and reg["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert reg.get("exit_result") == "TERMINAL"
    assert launcher_b.recovered_disposition.get(lid) == "TERMINAL_RECOVERED"
    # terminal 状态镜像进 last_run（terminal-history 视角；requirement 8）
    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid
    assert launcher_b.last.result == RESULT_FINISHED
    assert launcher_b.last.report_path == str(out_dir / "REPORT.md")
    # 状态窗口绑定该任务并呈现 canonical terminal
    ref = sw.resolve_current_task(launcher_b)
    assert ref is not None and ref.task_id == tid
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid and snap.overall_raw == "SUCCESS"
    assert snap.overall == "已完成"
    assert snap.report_path == str(out_dir / "REPORT.md")
    _assert_real_state_untouched(before, tid)


# ===========================================================================
# 3) dead runner + non-terminal artifacts -> RECOVERY_NEEDED（绝不 FAILED）
# ===========================================================================

def test_dead_runner_nonterminal_is_recovery_needed_not_failed(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-orphan")
    tid = "SRV-ORPHAN-001"
    out_dir = ws / ".aaf" / tid
    out_dir.mkdir(parents=True)
    (out_dir / "TASK.md").write_text(_task_text(ws, tid), encoding="utf-8")
    update_status(out_dir, task_id=tid, status="RUNNING",
                  task_path=str(out_dir / "TASK.md"), workspace=str(ws))

    lid = reg_mod.new_launch_id()
    argv = [sys.executable, str(DUMMY_RUNNER), str(out_dir / "TASK.md"),
            "--workspace", str(ws), "--output", str(out_dir), "--launch-id", lid]
    reg_mod.create_prepared(
        launch_id=lid, task_id=tid, workspace=str(ws), output_dir=str(out_dir),
        expected_runner_entry="dummy_runner.py", expected_command_line=argv,
        launcher_instance_id="dead-instance", root=_reg_dir(),
    )
    reg_mod.mark_running(lid, 4_294_967_293, "2026-09-01T00:00:00.000", root=_reg_dir())
    control_mod.write_control(
        out_dir, control_mod.new_control(
            task_id=tid, workspace=str(ws), launch_id=lid,
            launcher_pid=os.getpid(), launcher_instance_id="dead-instance",
            expected_runner_entry="dummy_runner.py", expected_command_line=argv,
        ), task_id=tid,
    )
    control_mod.update_control(out_dir, {"runner_pid": 4_294_967_293,
                                         "runner_creation_time": "2026-09-01T00:00:00.000"}, task_id=tid)

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())
    # 显式不确定态：registry EXITED RECOVERY_NEEDED；绝不 RUNNING / FAILED
    assert launcher_b.state == "IDLE" and launcher_b.current is None
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg is not None and reg["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert reg.get("exit_result") == RESULT_RECOVERY_NEEDED
    assert launcher_b.recovered_disposition.get(lid) == "RECOVERY_NEEDED"
    assert launcher_b.last is not None
    assert launcher_b.last.result == RESULT_RECOVERY_NEEDED
    assert launcher_b.last.result != "FAILED"
    # UI 呈现：任务记录 RUNNING（canonical 未终态）+ health 只读警告——不是「执行失败」
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid
    assert snap.overall_raw in ("RUNNING", "CREATED")
    assert snap.overall != "执行失败"
    _assert_real_state_untouched(before, tid)


# ===========================================================================
# 4) stale registry handled safely（混合：terminal / orphan / PREPARED 保守）
# ===========================================================================

def test_stale_registry_mixed_handled_safely(tmp_path):
    ws = _ws(tmp_path, "ws-mixed")
    # --- terminal 条目（→ EXITED TERMINAL） ---
    tid_t = "SRV-MIX-T"
    out_t = ws / ".aaf" / tid_t
    out_t.mkdir(parents=True)
    (out_t / "TASK.md").write_text(_task_text(ws, tid_t), encoding="utf-8")
    (out_t / "REPORT.md").write_text("# REPORT\n\n## Current Status\nFAILED\n", encoding="utf-8")
    task_lifecycle.finalize_terminal(
        out_t, task_id=tid_t, status="FAILED",
        task_path=str(out_t / "TASK.md"), workspace=str(ws),
        report_path=str(out_t / "REPORT.md"), stage="COMPLETED",
    )
    lid_t = reg_mod.new_launch_id()
    argv_t = [sys.executable, "run.py", "x", "--workspace", str(ws), "--output", str(out_t)]
    reg_mod.create_prepared(launch_id=lid_t, task_id=tid_t, workspace=str(ws),
                            output_dir=str(out_t), expected_runner_entry="run.py",
                            expected_command_line=argv_t, launcher_instance_id="i", root=_reg_dir())
    reg_mod.mark_running(lid_t, 4_294_967_292, "2026-09-01T00:00:00.000", root=_reg_dir())
    control_mod.write_control(
        out_t, control_mod.new_control(task_id=tid_t, workspace=str(ws), launch_id=lid_t,
                                       launcher_pid=os.getpid(), launcher_instance_id="i",
                                       expected_runner_entry="run.py", expected_command_line=argv_t),
        task_id=tid_t)
    control_mod.update_control(out_t, {"runner_pid": 4_294_967_292,
                                       "runner_creation_time": "2026-09-01T00:00:00.000"}, task_id=tid_t)
    # --- orphan 条目（→ EXITED RECOVERY_NEEDED） ---
    tid_o = "SRV-MIX-O"
    out_o = ws / ".aaf" / tid_o
    out_o.mkdir(parents=True)
    (out_o / "TASK.md").write_text(_task_text(ws, tid_o), encoding="utf-8")
    update_status(out_o, task_id=tid_o, status="RUNNING",
                  task_path=str(out_o / "TASK.md"), workspace=str(ws))
    lid_o = reg_mod.new_launch_id()
    argv_o = [sys.executable, "run.py", "x", "--workspace", str(ws), "--output", str(out_o)]
    reg_mod.create_prepared(launch_id=lid_o, task_id=tid_o, workspace=str(ws),
                            output_dir=str(out_o), expected_runner_entry="run.py",
                            expected_command_line=argv_o, launcher_instance_id="i", root=_reg_dir())
    reg_mod.mark_running(lid_o, 4_294_967_291, "2026-09-01T00:00:00.000", root=_reg_dir())
    control_mod.write_control(
        out_o, control_mod.new_control(task_id=tid_o, workspace=str(ws), launch_id=lid_o,
                                       launcher_pid=os.getpid(), launcher_instance_id="i",
                                       expected_runner_entry="run.py", expected_command_line=argv_o),
        task_id=tid_o)
    control_mod.update_control(out_o, {"runner_pid": 4_294_967_291,
                                       "runner_creation_time": "2026-09-01T00:00:00.000"}, task_id=tid_o)
    # --- PREPARED 无 runner_pid 条目（可能正在启动 → 保守保留不动） ---
    tid_p = "SRV-MIX-P"
    out_p = ws / ".aaf" / tid_p
    out_p.mkdir(parents=True)
    lid_p = reg_mod.new_launch_id()
    argv_p = [sys.executable, "run.py", "x", "--workspace", str(ws), "--output", str(out_p)]
    reg_mod.create_prepared(launch_id=lid_p, task_id=tid_p, workspace=str(ws),
                            output_dir=str(out_p), expected_runner_entry="run.py",
                            expected_command_line=argv_p, launcher_instance_id="i", root=_reg_dir())

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    recovered = launcher_b.recover_launches(_reg_dir())
    assert set(recovered) == {lid_t, lid_o, lid_p}
    assert launcher_b.state == "IDLE"  # 无 live runner → 不伪造 RUNNING
    reg_t, _ = reg_mod.read_registry(lid_t, root=_reg_dir())
    assert reg_t["state"] == reg_mod.REGISTRY_STATE_EXITED and reg_t.get("exit_result") == "TERMINAL"
    reg_o, _ = reg_mod.read_registry(lid_o, root=_reg_dir())
    assert reg_o["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert reg_o.get("exit_result") == RESULT_RECOVERY_NEEDED
    reg_p, _ = reg_mod.read_registry(lid_p, root=_reg_dir())
    assert reg_p["state"] == reg_mod.REGISTRY_STATE_PREPARED  # 未自动处置
    # last_run 镜像 = terminal/orphan 之一（created_at 同秒平局不保证哪一 —— 均合法；
    # terminal 条目 canonical=FAILED → 镜像 FAILED 是 canonical 跟随，非伪造）
    assert launcher_b.last is not None
    assert launcher_b.last.task_id in (tid_t, tid_o)
    assert launcher_b.last.result in (RESULT_FINISHED, RESULT_RECOVERY_NEEDED, "FAILED")


# ===========================================================================
# 5) duplicate hotkey while running -> 无第二 runner、无 view overwrite
# ===========================================================================

def test_duplicate_hotkey_while_running_no_second_runner_no_view_overwrite(tmp_path, monkeypatch):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-dup")
    tid = "SRV-DUP-001"
    task_file = task_io.save_task(_task_text(ws, tid), str(ws), tid)
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "60")
    launcher_a = _make_launcher(DUMMY_RUNNER)
    out_dir = launcher_a.default_output_dir(str(ws), tid)
    assert launcher_a.launch(task_file, str(ws), out_dir, tid)
    lid, _runner_pid = _wait_handshake_lid(launcher_a._active_launch[tid], out_dir)

    # 实例 B = restart：恢复为 RUNNING（formal task 绑定）
    launcher_b = _make_launcher(DUMMY_RUNNER)
    launcher_b.recover_launches(_reg_dir())
    assert launcher_b.state == "RUNNING"
    assert launcher_b.current.task_id == tid

    # 重复 Ctrl+Alt+A（同 Task ID）→ running reject 卡片；零副作用
    cfg = cfg_mod.default_config()
    cfg["current_workspace"] = str(ws)
    plan = intake.plan_submission(_task_text(ws, tid), cfg, launcher_b)
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None and plan.duplicate.kind == dup_mod.KIND_RUNNING
    assert any("第二份 runner" in r for r in plan.reasons)
    # 无第二 runner / registry 无第二活跃条目
    active = [e for e in reg_mod.list_launches(root=_reg_dir())
              if e.get("state") in reg_mod.ACTIVE_STATES]
    assert [e["launch_id"] for e in active] == [lid]
    # formal task 绑定未被临时/测试身份覆盖
    assert launcher_b.current.task_id == tid
    assert sw.resolve_current_task(launcher_b).task_id == tid

    # 清理
    reg = reg_mod.read_registry(lid, root=_reg_dir())[0]
    _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
    assert _wait_until(lambda: launcher_b.state != "RUNNING", timeout=30)
    _assert_real_state_untouched(before, tid, "F-I-RUN")


# ===========================================================================
# 6) valid active recovered task 优先于 last_run（纯解析优先级）
# ===========================================================================

def test_recovered_active_task_takes_precedence_over_last_run(tmp_path):
    ws = _ws(tmp_path, "ws-prio")
    # last_run（兜底镜像）指向无关/泄漏身份 F-I-RUN
    last_run_file = cfg_mod.state_root() / "last_run.json"
    last_run_file.parent.mkdir(parents=True, exist_ok=True)
    last_run_file.write_text(
        json.dumps({"task_id": "F-I-RUN", "result": "FAILED",
                    "output_dir": str(tmp_path / "gone")}), encoding="utf-8")

    launcher = FrameworkLauncher(registry_dir=_reg_dir())
    launcher.state = "RUNNING"
    launcher.current = sw_task_current(ws, "SRV-PRIO-001", tmp_path)
    ref = sw.resolve_current_task(launcher)
    assert ref is not None and ref.task_id == "SRV-PRIO-001"
    assert ref.output_dir == ws / ".aaf" / "SRV-PRIO-001"
    # launcher 无内存任务时 last_run 兜底仍可用（terminal-history 角色保留）
    idle = FrameworkLauncher(registry_dir=_reg_dir())
    idle.state = "IDLE"
    ref2 = sw.resolve_current_task(idle)
    assert ref2 is not None and ref2.task_id == "F-I-RUN"  # fallback 本身仍工作


# ===========================================================================
# 7) test AAF_BRIDGE_DIR 防止 production last_run 污染 + F-I-RUN 不能泄漏
# ===========================================================================

def test_test_state_cannot_pollute_real_bridge_state(tmp_path, monkeypatch):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-leak")
    monkeypatch.setenv("AAF_RECOVER_SLEEP", "0.5")  # 快速自然完成（含 F-I-RUN 身份）
    for tid in ("SRV-LEAK-001", "F-I-RUN", "SRV-LEAK-002"):
        task_file = task_io.save_task(_task_text(ws, tid), str(ws), tid)
        launcher = _make_launcher(RECOVER_RUNNER)
        done = threading.Event()
        launcher.on_finished = lambda last, output: done.set()
        out_dir = launcher.default_output_dir(str(ws), tid)
        # 完整收尾路径（_persist_last 写入 last_run）在隔离根内执行
        assert launcher.launch(task_file, str(ws), out_dir, tid)
        assert done.wait(20.0), f"{tid} 未在限时内收尾"
        assert launcher.state == "FINISHED"
        assert launcher.last.result == RESULT_FINISHED
    # 隔离根内确实记录了测试执行（last_run + registry 含 F-I-RUN 身份）
    iso = cfg_mod.state_root() / "last_run.json"
    assert iso.exists() and "SRV-LEAK-002" in iso.read_text(encoding="utf-8")
    leaked = [e for e in reg_mod.list_launches(root=_reg_dir()) if e.get("task_id") == "F-I-RUN"]
    assert leaked, "隔离根 registry 应包含 F-I-RUN 条目（证明其只在隔离根执行）"
    # 真实用户 Bridge state 零变化、零测试身份
    _assert_real_state_untouched(before, "SRV-LEAK-001", "SRV-LEAK-002", "F-I-RUN")


def test_recovery_needed_label_not_failed(tmp_path, monkeypatch):
    """last_run result=RECOVERY_NEEDED + runtime 缺失 → 显式不确定文案（非执行失败）。"""
    from bridge.launcher import RunInfo
    launcher = FrameworkLauncher(registry_dir=_reg_dir())
    launcher.state = "IDLE"
    launcher.last = RunInfo(
        task_id="SRV-UNKNOWN-001", task_path="", report_path=None, exit_code=None,
        result=RESULT_RECOVERY_NEEDED,
        output_dir=str(tmp_path / "no-such-dir" / "SRV-UNKNOWN-001"), launch_id="y" * 32,
    )
    snap = sw.collect_status({}, ("OK", "正常运行"), launcher)
    assert snap.task_id == "SRV-UNKNOWN-001"
    assert snap.overall_raw == RESULT_RECOVERY_NEEDED
    assert snap.overall == "状态无法确认，需人工核查"
    assert snap.overall != "执行失败"


# ===========================================================================
# 8) 全链路：live 中 restart → 恢复 → 自然完成 → watcher 收尾 → terminal 呈现
#    （fresh-runner closure 的 pytest 级确定性替身；requirement 12/13 场景）
# ===========================================================================

def test_restart_then_natural_finish_terminal_restored(tmp_path, monkeypatch):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-closure")
    tid = "SRV-CLOSURE-001"
    task_file = task_io.save_task(_task_text(ws, tid), str(ws), tid)
    monkeypatch.setenv("AAF_RECOVER_SLEEP", "3")  # 3s 后自然提交 SUCCESS

    launcher_a = _make_launcher(RECOVER_RUNNER)
    out_dir = launcher_a.default_output_dir(str(ws), tid)
    assert launcher_a.launch(task_file, str(ws), out_dir, tid)
    lid = launcher_a._active_launch[tid]
    _wait_handshake_lid(lid, out_dir)

    # live 中 restart：实例 B 恢复同一正式任务
    launcher_b = _make_launcher(RECOVER_RUNNER)
    recovered = launcher_b.recover_launches(_reg_dir())
    assert lid in recovered and launcher_b.state == "RUNNING"
    assert launcher_b.current.task_id == tid and launcher_b.current.launch_id == lid

    # 任务自然完成 → B（watcher）收尾：registry EXITED / last_run / state=FINISHED
    assert _wait_until(lambda: launcher_b.state == "FINISHED", timeout=30), "watcher 未收尾"
    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid
    assert launcher_b.last.result == RESULT_FINISHED
    assert launcher_b.last.report_path == str(out_dir / "REPORT.md")
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg["state"] == reg_mod.REGISTRY_STATE_EXITED
    # canonical terminal 呈现（不依赖 last_run）
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid and snap.overall_raw == "SUCCESS"
    assert snap.overall == "已完成"
    assert snap.report_path == str(out_dir / "REPORT.md")
    # 收尾后并发保护释放：可正常启动新任务（无执行回归）
    launcher_b.on_finished = None
    tid2 = "SRV-CLOSURE-002"
    task_file2 = task_io.save_task(_task_text(ws, tid2), str(ws), tid2)
    assert launcher_b.launch(task_file2, str(ws), launcher_b.default_output_dir(str(ws), tid2), tid2)
    assert _wait_until(lambda: launcher_b.state == "FINISHED", timeout=30)
    assert launcher_b.last.task_id == tid2 and launcher_b.last.result == RESULT_FINISHED
    _assert_real_state_untouched(before, tid, tid2)
