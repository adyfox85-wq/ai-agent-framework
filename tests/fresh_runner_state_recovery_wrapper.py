"""AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001 fresh-runner stage wrapper.

每个 stage 在**全新 python 进程**内扮演一个 Bridge 实例（restart 场景 =
新进程读同一 AAF_BRIDGE_DIR / registry；绝不复用前一个进程的内存）：

  launch   实例 1：FrameworkLauncher 真实启动 bounded 任务
            （tests/fixtures/dummy_recover_runner.py；AAF_RECOVER_SLEEP 控制
            live 窗口）→ 等 handshake → 证据 JSON → 退出（模拟 Bridge 崩溃/
            重启前实例消失——wait thread 不复存在）
  restart  实例 2（零内存）：recover_launches → 断言 state=RUNNING / current
            identity（task_id/launch_id/runner_pid 与 registry/control 一致）→
            duplicate hotkey 尝试（同 Task ID）→ reject running 卡片、无第二
            runner、view 未被覆盖 → 等待任务自然完成（recovered watcher 收尾）
            → 证据 JSON → 退出
  reopen   实例 3（零内存）：recover_launches（registry 已 EXITED）→ last_run
            恢复 terminal 视图（resolve + collect_status）→ 再真实启动一个新
            bounded 任务（执行/报告生成无回归）→ 证据 JSON → 退出

用法（由 fresh_runner_state_recovery_validation.py 驱动）：
  python tests/fresh_runner_state_recovery_wrapper.py <stage> <evidence_dir>

退出码 0 = stage 通过；非 0 = stage 失败（driver 以退出码聚合失败场景数）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import control as control_mod  # noqa: E402
from ai_agent_framework.task_lifecycle import read_status  # noqa: E402

from bridge import config as cfg_mod  # noqa: E402
from bridge import intake  # noqa: E402
from bridge import launch_registry as reg_mod  # noqa: E402
from bridge import status_window as sw  # noqa: E402
from bridge import task_io  # noqa: E402
from bridge.launcher import RESULT_FINISHED, FrameworkLauncher  # noqa: E402

RECOVER_RUNNER = ROOT / "tests" / "fixtures" / "dummy_recover_runner.py"
TASK_ID = "SRV-FRESH-001"
TASK_ID2 = "SRV-FRESH-002"


def _fail(msg: str) -> int:
    print(f"STAGE_FAIL: {msg}")
    return 1


def _task_text(ws: Path, tid: str) -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {tid}
Task Name: Fresh Runner State Recovery
Workspace: {ws}

Objective:
fresh-process 验证 Bridge restart 状态恢复

Acceptance:
1. 通过
AAF_TASK_END"""


def _wait_until(fn, timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _reg_dir(ev: Path) -> Path:
    return ev / "aaf-bridge" / "launches"


def _make_launcher(ev: Path) -> FrameworkLauncher:
    """fresh-runner launcher：**必须**显式注入 dummy fixture runner。

    绝不使用 FrameworkLauncher 默认 run_py（= 真实仓库 run.py——真实执行链
    + 真实 cost gate；本验证只允许 deterministic dummy runner）。
    """
    return FrameworkLauncher(run_py=RECOVER_RUNNER, registry_dir=_reg_dir(ev))


def _evidence(ev: Path, stage: str, data: dict) -> None:
    (ev / f"stage-{stage}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _wait_stable_control(out_dir: Path, timeout: float = 30.0) -> int | None:
    """control.runner_pid 连续两次读数稳定 → 返回最终 runner pid（handshake 完成）。"""
    def _stable():
        prev = None
        for _ in range(2):
            ctrl, _ = control_mod.read_control(out_dir)
            cur = (ctrl or {}).get("runner_pid")
            if cur is None or cur != prev:
                prev = cur
                time.sleep(0.3)
                continue
            return int(cur)
        return None
    _wait_until(lambda: _stable() is not None, timeout=timeout)
    ctrl, _ = control_mod.read_control(out_dir)
    pid = (ctrl or {}).get("runner_pid")
    return int(pid) if pid is not None else None


def stage_launch(ev: Path) -> int:
    ws = ev / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    os.environ["AAF_RECOVER_SLEEP"] = os.environ.get("FR_SLEEP", "6")  # live 窗口
    task_file = task_io.save_task(_task_text(ws, TASK_ID), str(ws), TASK_ID)
    launcher = _make_launcher(ev)
    out_dir = launcher.default_output_dir(str(ws), TASK_ID)
    if not launcher.launch(task_file, str(ws), out_dir, TASK_ID):
        return _fail("launch 失败")
    lid = launcher._active_launch[TASK_ID]
    # handshake 稳定回写（uv venv 重定向壳：launcher 先写 Popen pid，runner 随后
    # 覆盖自报 pid——连续两次读数一致才视为最终身份；§6A.6-4/§6B.12-G）
    runner_pid = _wait_stable_control(out_dir)
    if runner_pid is None:
        return _fail("handshake 超时（control runner_pid 未稳定回写）")
    # canonical RUNNING 落盘 + registry RUNNING
    _wait_until(lambda: (read_status(out_dir) or {}).get("status") == "RUNNING", timeout=30.0)
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir(ev))
    data = {
        "stage": "launch",
        "task_id": TASK_ID,
        "launch_id": lid,
        "runner_pid": runner_pid,
        "runner_creation_time": (control_mod.read_control(out_dir)[0] or {}).get("runner_creation_time"),
        "registry_state": reg.get("state"),
        "output_dir": str(out_dir),
    }
    _evidence(ev, "launch", data)
    print(json.dumps(data, ensure_ascii=False))
    # 实例退出 = 重启前实例消失（wait thread 不复存在；runner 进程继续存活）
    return 0


def stage_restart(ev: Path) -> int:
    launch = json.loads((ev / "stage-launch.json").read_text(encoding="utf-8"))
    tid = launch["task_id"]
    lid = launch["launch_id"]
    runner_pid = launch["runner_pid"]
    ws = ev / "ws"
    cfg = cfg_mod.default_config()
    cfg["current_workspace"] = str(ws)

    launcher_b = _make_launcher(ev)
    recovered = launcher_b.recover_launches(_reg_dir(ev))
    if lid not in recovered or recovered[lid].result != "REAUTHENTICATED":
        return _fail(f"recover 未 REAUTHENTICATED: {recovered.get(lid)}")
    reg_after, _ = reg_mod.read_registry(lid, root=_reg_dir(ev))
    ctrl_after, _ = control_mod.read_control(Path(launch["output_dir"]))
    checks = {
        "state_running": launcher_b.state == "RUNNING",
        "current_task_id": (launcher_b.current.task_id if launcher_b.current else None) == tid,
        "current_launch_id": (launcher_b.current.launch_id if launcher_b.current else None) == lid,
        # runner 身份保持：registry 与 control 一致，且 = launch stage handshake 最终 pid
        "registry_matches_control": (reg_after or {}).get("runner_pid") == (ctrl_after or {}).get("runner_pid"),
        "runner_pid_preserved": (reg_after or {}).get("runner_pid") == runner_pid,
    }
    if not all(checks.values()):
        return _fail(f"恢复身份校验失败: {checks}")

    # duplicate hotkey（同 Task ID）→ running reject；无第二 runner / 无 view 覆盖
    text = _task_text(ws, tid)
    plan = intake.plan_submission(text, cfg, launcher_b)
    dup_ok = (
        plan.action == intake.ACTION_REJECT
        and plan.duplicate is not None
        and plan.duplicate.kind == "running"
    )
    active_after = [e for e in reg_mod.list_launches(root=_reg_dir(ev))
                    if e.get("state") in reg_mod.ACTIVE_STATES]
    no_second_runner = len(active_after) == 1 and active_after[0]["launch_id"] == lid
    view_intact = (
        launcher_b.current is not None
        and launcher_b.current.task_id == tid
        and sw.resolve_current_task(launcher_b).task_id == tid
    )
    if not (dup_ok and no_second_runner and view_intact):
        return _fail(f"duplicate hotkey 防护校验失败: dup={dup_ok} no2nd={no_second_runner} view={view_intact}")

    # 任务自然完成 → recovered watcher 收尾（canonical SUCCESS 于 ~6s 提交）
    if not _wait_until(lambda: launcher_b.state == "FINISHED", timeout=60.0):
        return _fail(f"watcher 未在限时内收尾 (state={launcher_b.state})")
    if launcher_b.last is None or launcher_b.last.result != RESULT_FINISHED:
        return _fail(f"last result 异常: {getattr(launcher_b.last, 'result', None)}")
    reg, _ = reg_mod.read_registry(lid, root=_reg_dir(ev))
    if reg is None or reg.get("state") != reg_mod.REGISTRY_STATE_EXITED:
        return _fail(f"registry 未收敛 EXITED: {reg}")
    status = read_status(Path(launch["output_dir"]))
    if (status or {}).get("status") != "SUCCESS":
        return _fail(f"canonical 未 SUCCESS: {status}")
    data = {
        "stage": "restart",
        "task_id": tid,
        "launch_id": lid,
        "checks": checks,
        "dup_reject": dup_ok,
        "no_second_runner": no_second_runner,
        "view_intact": view_intact,
        "state_after": launcher_b.state,
        "last_result": launcher_b.last.result,
        "last_report": launcher_b.last.report_path,
        "registry_exited": True,
        "canonical_success": True,
        "last_run_task": cfg_mod.state_root().joinpath("last_run.json").exists(),
    }
    _evidence(ev, "restart", data)
    print(json.dumps(data, ensure_ascii=False))
    return 0


def stage_reopen(ev: Path) -> int:
    launch = json.loads((ev / "stage-launch.json").read_text(encoding="utf-8"))
    tid = launch["task_id"]
    ws = ev / "ws"
    out_dir = Path(launch["output_dir"])

    # 实例 3 = 再重启：registry 已 EXITED；terminal 视图经 last_run 镜像恢复
    launcher_c = _make_launcher(ev)
    launcher_c.recover_launches(_reg_dir(ev))
    ref = sw.resolve_current_task(launcher_c)
    if ref is None or ref.task_id != tid:
        return _fail(f"reopen 未解析到正式任务: {ref}")
    snap = sw.collect_status({"current_workspace": str(ws)}, ("OK", "正常运行"), launcher_c)
    terminal_view_ok = snap.overall_raw == "SUCCESS" and snap.overall == "已完成"
    report_ok = snap.report_path == str(out_dir / "REPORT.md")
    if not (terminal_view_ok and report_ok):
        return _fail(f"terminal 视图错误: overall={snap.overall_raw!r} report={snap.report_path!r}")

    # 执行/报告生成无回归：真实启动第二个 bounded 任务并完成
    os.environ["AAF_RECOVER_SLEEP"] = "1"
    task_file2 = task_io.save_task(_task_text(ws, TASK_ID2), str(ws), TASK_ID2)
    out_dir2 = launcher_c.default_output_dir(str(ws), TASK_ID2)
    if not launcher_c.launch(task_file2, str(ws), out_dir2, TASK_ID2):
        return _fail("第二个任务 launch 失败（执行回归）")
    if not _wait_until(lambda: launcher_c.state == "FINISHED", timeout=60.0):
        return _fail("第二个任务未收尾（执行回归）")
    if launcher_c.last is None or launcher_c.last.task_id != TASK_ID2 or launcher_c.last.result != RESULT_FINISHED:
        return _fail(f"第二个任务结果异常: {launcher_c.last}")
    if not (out_dir2 / "REPORT.md").exists() or not (out_dir2 / "run.json").exists():
        return _fail("第二个任务 REPORT/run.json 缺失（报告生成回归）")
    data = {
        "stage": "reopen",
        "task_id": tid,
        "terminal_view_ok": terminal_view_ok,
        "terminal_overall": snap.overall_raw,
        "report_ok": report_ok,
        "second_task_id": TASK_ID2,
        "second_result": launcher_c.last.result,
        "second_report_exists": (out_dir2 / "REPORT.md").exists(),
        "second_registry_exited": all(
            e.get("state") == reg_mod.REGISTRY_STATE_EXITED
            for e in reg_mod.list_launches(root=_reg_dir(ev))
        ),
    }
    _evidence(ev, "reopen", data)
    print(json.dumps(data, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python fresh_runner_state_recovery_wrapper.py <launch|restart|reopen> <evidence_dir>")
        return 2
    stage = argv[1]
    ev = Path(argv[2]).resolve()
    ev.mkdir(parents=True, exist_ok=True)
    # 与 conftest 同构：Bridge state root（registry + last_run）落在隔离证据根
    os.environ["AAF_BRIDGE_DIR"] = str(ev / "aaf-bridge")
    if stage == "launch":
        return stage_launch(ev)
    if stage == "restart":
        return stage_restart(ev)
    if stage == "reopen":
        return stage_reopen(ev)
    print(f"unknown stage: {stage}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
