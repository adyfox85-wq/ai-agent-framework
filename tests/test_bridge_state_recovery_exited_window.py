"""AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001-FIX-001 — 聚焦回归测试。

覆盖（TASK req 10/11）：EXITED→last_run crash-window closure
（registry 已持久化 EXITED、但 Bridge 在 last_run.json 写入前崩溃）：

- terminal SUCCESS → mark_exited(EXITED) → 模拟崩溃（last_run 未写入）→
  restart → 正确 terminal task 恢复（FINISHED / identity / REPORT）
- terminal FAILED 同崩溃点 → FAILED 恢复
- terminal CANCELLED 同崩溃点 → CANCELLED 恢复
- EXITED 无 canonical proof → 绝不伪造 FINISHED → RECOVERY_NEEDED
- canonical 存在但 launch/task 关系不可验证 → fail closed RECOVERY_NEEDED
- 旧 EXITED 任务不覆盖更新的 live RUNNING 任务（restored 优先）
- 多个 EXITED 记录 → 只选最新 validated 终态；stale 历史不回溯
- 重建的 last_run 不被测试 F-I-RUN 身份污染；真实 ~/.aaf-bridge 零写入
- 干净收尾稳态（last_run 已呈现 newest EXITED）→ recover no-op

真实子进程全链路用 tests/fixtures/dummy_recover_runner.py（自然完成 SUCCESS
canonical 全套）；crash-window 状态 = registry EXITED + last_run 缺失/旧内容
（可观察磁盘状态与「mark_exited 后、_persist_last 前崩溃」等价）。全部 registry /
last_run / config 落在 conftest 的 AAF_BRIDGE_DIR 隔离根内；真实 ~/.aaf-bridge
只读快照对比（零写入）。
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
from ai_agent_framework.task_lifecycle import read_canonical_terminal, update_status

from bridge import config as cfg_mod
from bridge import launch_registry as reg_mod
from bridge import status_window as sw
from bridge import task_io
from bridge.launcher import (
    RESULT_CANCELLED,
    RESULT_FAILED,
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

# 与 launcher._DISPOSITION_* 对齐（测试断言用字面量；避免 import 私有常量）
DISP_EXITED_TERMINAL = "EXITED_TERMINAL_RECOVERED"
DISP_EXITED_NEEDED = "EXITED_RECOVERY_NEEDED"

DEAD_PID = 4_294_967_289  # 不存在的 runner pid（registry 只作记录，EXITED pass 不验证进程）


def _task_text(ws: Path, task_id: str) -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {task_id}
Task Name: EXITED crash-window 测试任务
Workspace: {ws}

Objective:
验证 EXITED-to-last_run crash window 恢复

Acceptance:
1. 通过
AAF_TASK_END"""


def _ws(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _bridge_root() -> Path:
    return Path(os.environ["AAF_BRIDGE_DIR"])


def _reg_dir() -> Path:
    return _bridge_root() / "launches"


def _real_snapshot() -> tuple[bytes | None, int]:
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


def _wait_until(fn, timeout: float = 30.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _seed_terminal_launch(
    *,
    ws: Path,
    tid: str,
    status: str,
    created_at: str,
    exited_at: str,
    exit_result: str,
    with_report: bool = True,
    control_launch_id: str | None = None,
    canonical: bool = True,
) -> tuple[str, Path]:
    """构造 crash-window 状态的 launch（registry EXITED + 任务 artifacts + control）。

    - canonical=True：finalize_terminal 提交 status 终态（+ run.json / REPORT.md）
    - canonical=False：task.json 保持 RUNNING（无 terminal proof）
    - control_launch_id 可注入不一致 launch_id（关系验证失败场景）
    返回 (launch_id, out_dir)。
    """
    out_dir = ws / ".aaf" / tid
    out_dir.mkdir(parents=True, exist_ok=True)
    task_file = out_dir / "TASK.md"
    task_file.write_text(_task_text(ws, tid), encoding="utf-8")
    if with_report:
        (out_dir / "REPORT.md").write_text(
            f"# REPORT\n\n## Current Status\n{status}\n", encoding="utf-8")

    lid = reg_mod.new_launch_id()
    if canonical:
        kwargs = {
            "report_path": str(out_dir / "REPORT.md") if with_report else None,
        }
        if status == "CANCELLED":
            kwargs["cancel_mode"] = "soft"
            kwargs["terminal_reason"] = "CANCEL_REQUESTED"
        task_lifecycle.finalize_terminal(
            out_dir, task_id=tid, status=status,
            task_path=task_file, workspace=ws, **kwargs,
        )
        gen = read_canonical_terminal(out_dir)
        (out_dir / "run.json").write_text(
            json.dumps({"status": status, "task_id": tid,
                        "terminal_generation": getattr(gen, "terminal_generation", 1)}),
            encoding="utf-8")
    else:
        update_status(out_dir, task_id=tid, status="RUNNING",
                      task_path=task_file, workspace=ws)

    argv = [sys.executable, "dummy_recover_runner.py", str(task_file),
            "--workspace", str(ws), "--output", str(out_dir), "--launch-id", lid]
    reg_mod.create_prepared(
        launch_id=lid, task_id=tid, workspace=str(ws), output_dir=str(out_dir),
        expected_runner_entry="dummy_recover_runner.py", expected_command_line=argv,
        launcher_instance_id="cw-instance", root=_reg_dir(),
    )
    # created_at 权威排序由调用方显式控制（真实流程 created_at=launch 时间）
    reg_mod.update_registry(lid, {"created_at": created_at}, root=_reg_dir())
    reg_mod.mark_running(lid, DEAD_PID, "2026-09-01T00:00:00.000", root=_reg_dir())
    reg_mod.mark_exited(lid, exit_result=exit_result, exited_at=exited_at, root=_reg_dir())

    ctrl_lid = control_launch_id if control_launch_id is not None else lid
    ctrl_tid = tid if control_launch_id is None else f"{tid}-OTHER"
    control_mod.write_control(
        out_dir, control_mod.new_control(
            task_id=ctrl_tid, workspace=str(ws), launch_id=ctrl_lid,
            launcher_pid=os.getpid(), launcher_instance_id="cw-instance",
            expected_runner_entry="dummy_recover_runner.py", expected_command_line=argv,
        ), task_id=ctrl_tid,
    )
    control_mod.update_control(out_dir, {"runner_pid": DEAD_PID,
                                         "runner_creation_time": "2026-09-01T00:00:00.000"},
                               task_id=ctrl_tid)
    return lid, out_dir


def _poison_last_run(task_id: str = "F-I-RUN", result: str = "FAILED") -> Path:
    """写入无关/泄漏身份 last_run（模拟崩溃前存在的旧呈现 / 测试污染检查）。"""
    p = cfg_mod.state_root() / "last_run.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"task_id": task_id, "result": result,
                    "output_dir": str(_bridge_root().parent / "gone")}),
        encoding="utf-8")
    return p


# ===========================================================================
# 1) terminal SUCCESS 崩溃点 → restart → 正确 terminal task 恢复
# ===========================================================================

def test_exited_success_crash_window_restores_terminal_task(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-s")
    tid = "CWX-SUCCESS-001"
    lid, out_dir = _seed_terminal_launch(
        ws=ws, tid=tid, status="SUCCESS",
        created_at="2026-09-02T10:00:00", exited_at="2026-09-02T10:05:00",
        exit_result=RESULT_FINISHED)
    # 模拟崩溃：last_run 从未写入（或只含更旧记录）
    assert not (cfg_mod.state_root() / "last_run.json").exists()

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    # 正确 terminal task identity / FINISHED 呈现（requirement 3）
    assert launcher_b.state == "IDLE" and launcher_b.current is None  # 绝不恢复 RUNNING
    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid
    assert launcher_b.last.launch_id == lid
    assert launcher_b.last.result == RESULT_FINISHED
    assert launcher_b.last.report_path == str(out_dir / "REPORT.md")
    gen = read_canonical_terminal(out_dir)
    assert launcher_b.last.terminal_generation == gen.terminal_generation
    assert launcher_b.recovered_disposition.get(lid) == DISP_EXITED_TERMINAL

    # last_run 落盘重建（同一隔离根）
    persisted = json.loads((cfg_mod.state_root() / "last_run.json").read_text(encoding="utf-8"))
    assert persisted["task_id"] == tid and persisted["launch_id"] == lid
    assert persisted["result"] == RESULT_FINISHED

    # 不 rerun / 不创建 runner / canonical 不动（requirement 3）
    active = [e for e in reg_mod.list_launches(root=_reg_dir())
              if e.get("state") in reg_mod.ACTIVE_STATES]
    assert active == []
    assert read_canonical_terminal(out_dir).status == "SUCCESS"
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert reg.get("exit_result") == RESULT_FINISHED  # canonical proof 有效 → evidence 保留

    # 状态窗口绑定正式任务并呈现 canonical terminal
    ref = sw.resolve_current_task(launcher_b)
    assert ref is not None and ref.task_id == tid
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid and snap.overall_raw == "SUCCESS"
    assert snap.overall == "已完成"
    assert snap.report_path == str(out_dir / "REPORT.md")
    _assert_real_state_untouched(before, tid, "F-I-RUN")


# ===========================================================================
# 2) terminal FAILED 同崩溃点 → FAILED 恢复（canonical 跟随，非伪造）
# ===========================================================================

def test_exited_failed_crash_window_restores_failed(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-f")
    tid = "CWX-FAILED-001"
    lid, out_dir = _seed_terminal_launch(
        ws=ws, tid=tid, status="FAILED",
        created_at="2026-09-02T11:00:00", exited_at="2026-09-02T11:02:00",
        exit_result=RESULT_FAILED, with_report=False)

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid and launcher_b.last.launch_id == lid
    assert launcher_b.last.result == RESULT_FAILED
    assert launcher_b.recovered_disposition.get(lid) == DISP_EXITED_TERMINAL
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg.get("exit_result") == RESULT_FAILED  # canonical FAILED → evidence 保留
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid and snap.overall_raw == "FAILED"
    assert snap.overall == "执行失败"  # canonical FAILED 的合法呈现（非 registry 推断）
    _assert_real_state_untouched(before, tid)


# ===========================================================================
# 3) terminal CANCELLED 同崩溃点 → CANCELLED 恢复（cancellation 语义保留）
# ===========================================================================

def test_exited_cancelled_crash_window_restores_cancelled(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-c")
    tid = "CWX-CANCELLED-001"
    lid, out_dir = _seed_terminal_launch(
        ws=ws, tid=tid, status="CANCELLED",
        created_at="2026-09-02T12:00:00", exited_at="2026-09-02T12:01:00",
        exit_result=RESULT_CANCELLED)

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid and launcher_b.last.launch_id == lid
    assert launcher_b.last.result == RESULT_CANCELLED
    assert launcher_b.last.report_path == str(out_dir / "REPORT.md")
    assert launcher_b.recovered_disposition.get(lid) == DISP_EXITED_TERMINAL
    canon = read_canonical_terminal(out_dir)
    assert canon is not None and canon.status == "CANCELLED" and canon.cancel_mode == "soft"
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.task_id == tid and snap.overall_raw == "CANCELLED"
    assert snap.overall == "已取消"
    _assert_real_state_untouched(before, tid)


# ===========================================================================
# 4) EXITED 无 canonical proof → 绝不伪造 FINISHED → RECOVERY_NEEDED
# ===========================================================================

def test_exited_without_terminal_proof_not_falsely_finished(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-np")
    tid = "CWX-NOPROOF-001"
    lid, out_dir = _seed_terminal_launch(
        ws=ws, tid=tid, status="RUNNING", canonical=False,
        created_at="2026-09-02T13:00:00", exited_at="2026-09-02T13:01:00",
        exit_result=RESULT_FINISHED)  # registry 声称 FINISHED（误导）——不足为凭

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid and launcher_b.last.launch_id == lid
    assert launcher_b.last.result == RESULT_RECOVERY_NEEDED
    assert launcher_b.last.result != RESULT_FINISHED  # requirement 5
    assert launcher_b.last.result != "FAILED"
    assert launcher_b.recovered_disposition.get(lid) == DISP_EXITED_NEEDED
    # registry 误导性 exit_result 收敛为显式不确定（evidence 字段保留）
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert reg.get("exit_result") == RESULT_RECOVERY_NEEDED
    # UI 呈现显式不确定（非执行失败 / 非已完成）
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_b)
    assert snap.overall_raw != "执行失败" and snap.overall != "执行失败"

    # 幂等：再次 restart（新实例）→ newest EXITED 已呈现 → no-op（registry 不再变化）
    launcher_c = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_c.recover_launches(_reg_dir())
    reg2, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg2.get("exit_result") == RESULT_RECOVERY_NEEDED
    assert launcher_c.recovered_disposition.get(lid) is None  # 未重复处置
    _assert_real_state_untouched(before, tid)


# ===========================================================================
# 5) canonical 存在但 launch/task 关系不可验证 → fail closed（RECOVERY_NEEDED）
# ===========================================================================

def test_exited_canonical_with_unverifiable_relationship_fails_closed(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-rel")
    tid = "CWX-RELATION-001"
    lid, _out_dir = _seed_terminal_launch(
        ws=ws, tid=tid, status="SUCCESS",
        created_at="2026-09-02T14:00:00", exited_at="2026-09-02T14:03:00",
        exit_result=RESULT_FINISHED,
        control_launch_id="f" * 32)  # control 指向另一个 launch（relaunch 覆盖场景）

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    # canonical SUCCESS 存在，但 registry↔control 关系对不上 → 不信任 → 显式不确定
    assert launcher_b.last is not None
    assert launcher_b.last.launch_id == lid
    assert launcher_b.last.result == RESULT_RECOVERY_NEEDED
    assert launcher_b.recovered_disposition.get(lid) == DISP_EXITED_NEEDED
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg.get("exit_result") == RESULT_RECOVERY_NEEDED
    _assert_real_state_untouched(before, tid)


# ===========================================================================
# 6) 旧 EXITED 任务不覆盖更新的 live RUNNING 任务（recovered RUNNING 优先）
# ===========================================================================

def test_old_exited_does_not_override_newer_live_running(tmp_path, monkeypatch):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-prio")
    tid_live = "CWX-LIVE-001"
    tid_old = "CWX-OLD-001"
    # 旧 EXITED terminal（SUCCESS proof）
    lid_old, _ = _seed_terminal_launch(
        ws=ws, tid=tid_old, status="SUCCESS",
        created_at="2026-09-02T08:00:00", exited_at="2026-09-02T08:30:00",
        exit_result=RESULT_FINISHED)
    # last_run 放入泄漏身份（F-I-RUN）——live 恢复必须不被旧 EXITED / 泄漏覆盖
    _poison_last_run()

    # live 正式任务真实运行（重启恢复场景）
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "60")
    task_file = task_io.save_task(_task_text(ws, tid_live), str(ws), tid_live)
    launcher_a = FrameworkLauncher(run_py=DUMMY_RUNNER, registry_dir=_reg_dir())
    out_live = launcher_a.default_output_dir(str(ws), tid_live)
    assert launcher_a.launch(task_file, str(ws), out_live, tid_live)
    lid_live = launcher_a._active_launch[tid_live]

    launcher_b = FrameworkLauncher(run_py=DUMMY_RUNNER, registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    # live RUNNING 恢复优先；旧 EXITED 不得改写 last_run / view（requirement 6/8）
    assert launcher_b.state == "RUNNING"
    assert launcher_b.current is not None and launcher_b.current.launch_id == lid_live
    last_bytes = (cfg_mod.state_root() / "last_run.json").read_bytes()
    assert b"F-I-RUN" in last_bytes, "last_run 不得被旧 EXITED 镜像覆盖"
    assert tid_old.encode() not in last_bytes
    assert launcher_b.recovered_disposition.get(lid_old) is None
    reg_old, _ = reg_mod.read_registry(lid_old, root=_reg_dir())
    assert reg_old["state"] == reg_mod.REGISTRY_STATE_EXITED  # 历史条目未被触碰
    assert reg_old.get("exit_result") == RESULT_FINISHED
    ref = sw.resolve_current_task(launcher_b)
    assert ref is not None and ref.task_id == tid_live
    # 无第二 runner
    active = [e for e in reg_mod.list_launches(root=_reg_dir())
              if e.get("state") in reg_mod.ACTIVE_STATES]
    assert [e["launch_id"] for e in active] == [lid_live]

    # 清理 live dummy
    reg = reg_mod.read_registry(lid_live, root=_reg_dir())[0]
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID",
                        str(reg.get("launch_root_pid") or reg.get("runner_pid"))],
                       capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001 —— 清理失败不掩盖断言结果
        pass
    assert _wait_until(lambda: launcher_b.state != "RUNNING", timeout=30)
    _assert_real_state_untouched(before, tid_live, tid_old, "F-I-RUN")


# ===========================================================================
# 7) 多个 EXITED 记录 → 只选最新 validated 终态（stale 历史不回溯/不覆盖）
# ===========================================================================

def test_multiple_exited_chooses_latest_validated_terminal(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-multi")
    # 旧 EXITED：SUCCESS proof（更早）
    tid_old = "CWX-MULTI-OLD"
    lid_old, _ = _seed_terminal_launch(
        ws=ws, tid=tid_old, status="SUCCESS",
        created_at="2026-09-02T09:00:00", exited_at="2026-09-02T09:10:00",
        exit_result=RESULT_FINISHED)
    # 新 EXITED：FAILED proof（更晚）——crash-window 受害者
    tid_new = "CWX-MULTI-NEW"
    lid_new, _ = _seed_terminal_launch(
        ws=ws, tid=tid_new, status="FAILED",
        created_at="2026-09-02T10:00:00", exited_at="2026-09-02T10:02:00",
        exit_result=RESULT_FAILED, with_report=False)
    # 无 last_run（崩溃窗口签名）

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    # 最新 validated 终态（FAILED）胜出；旧 SUCCESS 历史不回溯
    assert launcher_b.last is not None
    assert launcher_b.last.launch_id == lid_new and launcher_b.last.task_id == tid_new
    assert launcher_b.last.result == RESULT_FAILED
    assert launcher_b.recovered_disposition.get(lid_new) == DISP_EXITED_TERMINAL
    assert launcher_b.recovered_disposition.get(lid_old) is None
    reg_old, _ = reg_mod.read_registry(lid_old, root=_reg_dir())
    assert reg_old["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert reg_old.get("exit_result") == RESULT_FINISHED  # 旧条目原样保留
    persisted = json.loads((cfg_mod.state_root() / "last_run.json").read_text(encoding="utf-8"))
    assert persisted["launch_id"] == lid_new
    _assert_real_state_untouched(before, tid_old, tid_new)


def test_multiple_exited_newest_without_proof_wins_over_older_proof(tmp_path):
    """最新 EXITED 无 proof → 显式不确定；绝不回退呈现旧 EXITED 的 FINISHED。"""
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-multi2")
    tid_old = "CWX-MULTI2-OLD"
    _seed_terminal_launch(
        ws=ws, tid=tid_old, status="SUCCESS",
        created_at="2026-09-02T09:00:00", exited_at="2026-09-02T09:10:00",
        exit_result=RESULT_FINISHED)
    tid_new = "CWX-MULTI2-NEW"
    lid_new, _ = _seed_terminal_launch(
        ws=ws, tid=tid_new, status="RUNNING", canonical=False,
        created_at="2026-09-02T10:00:00", exited_at="2026-09-02T10:02:00",
        exit_result=RESULT_FINISHED)  # 最新 launch registry 误导性声称 FINISHED

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    assert launcher_b.last is not None
    assert launcher_b.last.launch_id == lid_new
    assert launcher_b.last.result == RESULT_RECOVERY_NEEDED
    assert launcher_b.last.task_id == tid_new  # 不呈现旧任务
    assert launcher_b.recovered_disposition.get(lid_new) == DISP_EXITED_NEEDED
    _assert_real_state_untouched(before, tid_old, tid_new)


# ===========================================================================
# 8) 干净收尾稳态 no-op + last_run 重建不被 F-I-RUN 污染
# ===========================================================================

def test_clean_steady_state_recovery_is_noop_and_pollution_replaced(tmp_path):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-clean")
    tid = "CWX-CLEAN-001"
    lid, out_dir = _seed_terminal_launch(
        ws=ws, tid=tid, status="SUCCESS",
        created_at="2026-09-02T15:00:00", exited_at="2026-09-02T15:05:00",
        exit_result=RESULT_FINISHED)
    # 干净收尾：last_run 已呈现该 launch（launch_id 相同；与 _persist_last 的
    # RunInfo.to_dict() 全字段形状一致，load_last 可解析）
    last_run_file = cfg_mod.state_root() / "last_run.json"
    last_run_file.parent.mkdir(parents=True, exist_ok=True)
    clean_bytes = json.dumps({
        "task_id": tid, "task_path": "", "report_path": str(out_dir / "REPORT.md"),
        "exit_code": None, "result": RESULT_FINISHED,
        "output_dir": str(out_dir), "launch_id": lid, "terminal_generation": 1,
    }, ensure_ascii=False, indent=2).encode("utf-8")
    last_run_file.write_bytes(clean_bytes)

    launcher_b = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    # 稳态：newest EXITED 已呈现 → no-op（last_run 字节级不变；launcher.last 未改）
    assert launcher_b.last is None
    assert launcher_b.recovered_disposition == {}
    assert last_run_file.read_bytes() == clean_bytes
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg.get("exit_result") == RESULT_FINISHED  # registry 未被触碰

    # F-I-RUN 污染 last_run + 真实 crash-window victim → 重建覆盖泄漏身份
    lid2, out2 = _seed_terminal_launch(
        ws=ws, tid="CWX-CLEAN-002", status="SUCCESS",
        created_at="2026-09-02T16:00:00", exited_at="2026-09-02T16:04:00",
        exit_result=RESULT_FINISHED)
    _poison_last_run()
    launcher_c = FrameworkLauncher(registry_dir=_reg_dir())
    launcher_c.recover_launches(_reg_dir())
    assert launcher_c.last is not None
    assert launcher_c.last.launch_id == lid2 and launcher_c.last.result == RESULT_FINISHED
    text = last_run_file.read_text(encoding="utf-8")
    assert "CWX-CLEAN-002" in text and "F-I-RUN" not in text  # requirement 10 末条
    assert "CWX-CLEAN-001" not in text  # 旧 EXITED 不覆盖更新 victim
    _assert_real_state_untouched(before, tid, "CWX-CLEAN-002", "F-I-RUN")


# ===========================================================================
# 9) 全链路（真实子进程）：bounded 任务自然完成 → EXITED → 模拟崩溃 → restart
#    镜像从权威 artifacts 恢复 → 无 rerun / 无重复 runner → 可再启动新任务
# ===========================================================================

def test_real_launch_exited_crash_window_full_loop(tmp_path, monkeypatch):
    before = _real_snapshot()
    ws = _ws(tmp_path, "ws-cwx-real")
    tid = "CWX-REAL-001"
    task_file = task_io.save_task(_task_text(ws, tid), str(ws), tid)
    monkeypatch.setenv("AAF_RECOVER_SLEEP", "2")

    launcher_a = FrameworkLauncher(run_py=RECOVER_RUNNER, registry_dir=_reg_dir())
    done_a = threading.Event()
    launcher_a.on_finished = lambda last, output: done_a.set()
    out_dir = launcher_a.default_output_dir(str(ws), tid)
    assert launcher_a.launch(task_file, str(ws), out_dir, tid)
    lid = launcher_a._active_launch[tid]
    # bounded 任务自然完成：wait thread 已 mark_exited(registry=EXITED)
    assert done_a.wait(30.0), "任务未在限时内收尾"
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir())
    assert reg["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert read_canonical_terminal(out_dir).status == "SUCCESS"
    gen_before = read_canonical_terminal(out_dir).terminal_generation

    # 模拟崩溃发生在 _persist_last 之前：last_run 回退为旧/泄漏呈现
    _poison_last_run()
    assert b"F-I-RUN" in (cfg_mod.state_root() / "last_run.json").read_bytes()

    # restart（新实例零内存）：EXITED crash-window 从权威 artifacts 恢复
    launcher_b = FrameworkLauncher(run_py=RECOVER_RUNNER, registry_dir=_reg_dir())
    launcher_b.recover_launches(_reg_dir())

    assert launcher_b.state == "IDLE" and launcher_b.current is None  # 不伪造 RUNNING
    assert launcher_b.last is not None
    assert launcher_b.last.task_id == tid
    assert launcher_b.last.launch_id == lid  # 同一 launch identity
    assert launcher_b.last.result == RESULT_FINISHED
    assert launcher_b.last.report_path == str(out_dir / "REPORT.md")
    assert launcher_b.recovered_disposition.get(lid) == DISP_EXITED_TERMINAL
    persisted = json.loads((cfg_mod.state_root() / "last_run.json").read_text(encoding="utf-8"))
    assert persisted["launch_id"] == lid and "F-I-RUN" not in persisted["task_id"]
    # 无 rerun / 无重复 runner：canonical generation 未变、无 ACTIVE launch
    canon_after = read_canonical_terminal(out_dir)
    assert canon_after.terminal_generation == gen_before
    assert [e for e in reg_mod.list_launches(root=_reg_dir())
            if e.get("state") in reg_mod.ACTIVE_STATES] == []
    assert len(reg_mod.list_launches(root=_reg_dir())) == 1  # 未新建 launch
    # 执行/报告无回归：可正常启动并完成新任务
    tid2 = "CWX-REAL-002"
    task_file2 = task_io.save_task(_task_text(ws, tid2), str(ws), tid2)
    assert launcher_b.launch(task_file2, str(ws),
                             launcher_b.default_output_dir(str(ws), tid2), tid2)
    assert _wait_until(lambda: launcher_b.state == "FINISHED", timeout=30)
    assert launcher_b.last.task_id == tid2 and launcher_b.last.result == RESULT_FINISHED
    _assert_real_state_untouched(before, tid, tid2, "F-I-RUN")
