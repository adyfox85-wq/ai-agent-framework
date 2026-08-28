"""Phase F（AAF-v0.4-TASK-006）— 真实 Windows E2E（TASK req 14 A–I）。

覆盖：
A. 当前 workspace TASK → 无额外确认 → 正常执行（真实 launcher + 真实 run.py
   dry-run 子进程：真实 runner / filesystem / artifacts；Agent 链不调用——
   Phase E 同款确定性约束）
B. 已知 workspace 切换 → 确认后切换并执行（config 持久化 + 目标 workspace 落盘）
C. 用户拒绝切换 → 不执行 TASK、current workspace 不变、零文件写入
D. 陌生 workspace → 明确确认前不得执行；确认后才允许加入/切换
E. invalid workspace → fail closed（不写任何文件）
F. 当前已有 RUNNING task → 拒绝项目切换 / 第二任务启动（launcher 既有并发保护）
G. duplicate RUNNING Task ID → 第二 runner 不启动（registry 无第二活跃 launch）
H. duplicate terminal Task ID → 不覆盖历史 artifacts + 用户得到清晰提示（卡片）
I. Bridge restart → current project 恢复正确 + duplicate protection 仍有效

全部经真实 config.json / launch registry / task.json / REPORT.md 验证；
running 场景用确定性 dummy runner（tests/fixtures/dummy_runner.py，sleep 模式），
绝不指向真实 Agent 会话。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ai_agent_framework import task_lifecycle

from bridge import config as cfg_mod
from bridge import duplicate as dup_mod
from bridge import intake
from bridge import launch_registry as reg_mod
from bridge import task_io
from bridge.launcher import AlreadyRunningError, FrameworkLauncher

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DRY = REPO_ROOT / "tests" / "fixtures" / "run_dry.py"
DUMMY_RUNNER = REPO_ROOT / "tests" / "fixtures" / "dummy_runner.py"


def _task_text(ws: str, task_id: str, name: str = "Phase F E2E 任务") -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {task_id}
Task Name: {name}
Workspace: {ws}

Objective:
验证 Phase F 提交流程

Acceptance:
1. 通过
AAF_TASK_END"""


def _ws(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


@pytest.fixture()
def bridge_env(tmp_path, monkeypatch):
    """AAF_BRIDGE_DIR → tmp/aaf-bridge（config + registry 隔离；子进程继承）。"""
    d = tmp_path / "aaf-bridge"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(d))
    return d


def _cfg(tmp_path: Path, ws: Path, project: str = "Current Project") -> tuple[dict, Path]:
    cfg_path = tmp_path / "cfg" / "config.json"
    cfg = cfg_mod.update_project(project, str(ws), cfg_path)
    return cfg, cfg_path


def _make_launcher(bridge_dir: Path, run_py: Path = RUN_DRY, done: threading.Event | None = None,
                   captured: dict | None = None) -> FrameworkLauncher:
    def _on_finished(last, output):
        if captured is not None:
            captured["last"] = last
            captured["output"] = output
        if done is not None:
            done.set()

    return FrameworkLauncher(
        run_py=run_py,
        registry_dir=bridge_dir / "launches",
        on_finished=_on_finished,
    )


def _wait_until(fn, timeout: float = 90.0, interval: float = 0.2) -> bool:
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
    except Exception:  # noqa: BLE001
        pass


def _execute(plan: intake.SubmissionPlan, launcher: FrameworkLauncher, cfg_path: Path) -> tuple[Path, Path, bool]:
    """确认后的执行链（与 main.py 一致：apply → launch）。"""
    target = intake.apply_submission(plan, cfg_path)
    output_dir = launcher.default_output_dir(plan.workspace, plan.task_id)
    started = launcher.launch(target, plan.workspace, output_dir, plan.task_id)
    return target, output_dir, started


def _hash_dir(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): p.read_bytes().hex() for p in sorted(d.rglob("*")) if p.is_file()}


# ========== A. 当前 workspace TASK → 无额外确认 → 正常执行 ==========

def test_e2e_a_same_workspace_executes_without_confirm(tmp_path, bridge_env):
    ws = _ws(tmp_path, "ws-a")
    cfg, cfg_path = _cfg(tmp_path, ws, "Project A")
    launcher = _make_launcher(bridge_env)
    done = threading.Event()
    launcher.on_finished = lambda last, output: done.set()

    plan = intake.plan_submission(_task_text(str(ws), "F-A-001"), cfg, launcher, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_PROCEED  # 无额外确认（req 2）
    assert not plan.switch_workspace

    target, output_dir, started = _execute(plan, launcher, cfg_path)
    assert started
    assert _wait_until(lambda: launcher.state == "FINISHED")
    assert launcher.last.result == "FINISHED"
    assert launcher.last.task_id == "F-A-001"
    # 真实 runner 产物
    assert (output_dir / "REPORT.md").exists()
    assert (output_dir / "route.json").exists()
    assert (output_dir / "context_manifest.json").exists()
    # 配置未被切换
    on_disk = cfg_mod.load_config(cfg_path)
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(ws))
    # registry 收敛 EXITED
    regs = reg_mod.list_launches(root=bridge_env / "launches")
    assert len(regs) == 1 and regs[0]["task_id"] == "F-A-001" and regs[0]["state"] == "EXITED"


# ========== B. 已知 workspace 切换 → 确认后切换并执行 ==========

def test_e2e_b_known_workspace_switch_and_execute(tmp_path, bridge_env):
    cur = _ws(tmp_path, "cur")
    other = _ws(tmp_path, "known-proj")
    cfg, cfg_path = _cfg(tmp_path, cur, "Current Project")
    # 构造「已知但非当前」：先切到 other 再切回 cur
    cfg_mod.update_project("Known Project", str(other), cfg_path)
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    cfg = cfg_mod.load_config(cfg_path)

    launcher = _make_launcher(bridge_env)
    done = threading.Event()
    launcher.on_finished = lambda last, output: done.set()

    plan = intake.plan_submission(_task_text(str(other), "F-B-001"), cfg, launcher, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_CONFIRM_SWITCH  # 明确显示当前/目标（req 3）
    assert plan.target_project == "Known Project"
    assert plan.current_workspace == str(cur)

    target, output_dir, started = _execute(plan, launcher, cfg_path)
    assert started
    assert _wait_until(lambda: launcher.state == "FINISHED")
    assert launcher.last.result == "FINISHED"
    # config 已持久化切换（req 6）
    on_disk = cfg_mod.load_config(cfg_path)
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(other))
    assert on_disk["current_project"] == "Known Project"
    assert on_disk["recent_projects"][0]["workspace"] == str(other)
    # TASK.md 与执行产物落在目标 workspace（req 12：不改写 Workspace）
    assert target.parent == other / ".aaf" / "tasks" / "active"
    assert (output_dir / "REPORT.md").exists()


# ========== C. 用户拒绝切换 → 不执行、current 不变、零写入 ==========

def test_e2e_c_decline_switch_writes_nothing(tmp_path, bridge_env):
    cur = _ws(tmp_path, "cur")
    other = _ws(tmp_path, "known-proj")
    cfg, cfg_path = _cfg(tmp_path, cur, "Current Project")
    cfg_mod.update_project("Known Project", str(other), cfg_path)
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    cfg = cfg_mod.load_config(cfg_path)

    config_before = cfg_mod.load_config(cfg_path)
    plan = intake.plan_submission(_task_text(str(other), "F-C-001"), cfg, None, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_CONFIRM_SWITCH

    # 模拟用户点 [取消]：不调用 apply_submission（main.py 对应 return）
    # → 断言：零文件写入、config 不变
    assert not task_io.task_target_path(str(other), "F-C-001").exists()
    assert not task_io.task_target_path(str(cur), "F-C-001").exists()
    assert not (other / ".aaf").exists()
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_workspace"] == config_before["current_workspace"]
    assert on_disk["current_project"] == config_before["current_project"]
    assert on_disk["recent_projects"] == config_before["recent_projects"]


# ========== D. 陌生 workspace → 确认前不得执行 ==========

def test_e2e_d_unknown_workspace_not_executed_before_confirm(tmp_path, bridge_env):
    cur = _ws(tmp_path, "cur")
    stranger = _ws(tmp_path, "stranger-path")
    cfg, cfg_path = _cfg(tmp_path, cur, "Current Project")

    plan = intake.plan_submission(_task_text(str(stranger), "F-D-001"), cfg, None, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_CONFIRM_UNKNOWN  # fail-safe 暂停（req 4）
    assert not plan.is_known
    # 确认前：不得执行 / 不得写入
    assert not task_io.task_target_path(str(stranger), "F-D-001").exists()
    assert not (stranger / ".aaf").exists()
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_workspace"] == str(cur)

    # 确认后：允许加入/切换并执行
    launcher = _make_launcher(bridge_env)
    done = threading.Event()
    launcher.on_finished = lambda last, output: done.set()
    target, output_dir, started = _execute(plan, launcher, cfg_path)
    assert started
    assert _wait_until(lambda: launcher.state == "FINISHED")
    on_disk = cfg_mod.load_config(cfg_path)
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(stranger))
    assert on_disk["recent_projects"][0]["workspace"] == str(stranger)
    assert (output_dir / "REPORT.md").exists()


# ========== E. invalid workspace → fail closed ==========

def test_e2e_e_invalid_workspace_fail_closed(tmp_path, bridge_env):
    cur = _ws(tmp_path, "cur")
    cfg, cfg_path = _cfg(tmp_path, cur, "Current Project")
    launcher = _make_launcher(bridge_env)

    plan = intake.plan_submission(_task_text(str(tmp_path / "missing-dir"), "F-E-001"), cfg, launcher, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_REJECT
    assert any("不存在" in r for r in plan.reasons)
    # 不写任何文件（req 5：fail closed，不自动修复成其它路径）
    assert not (tmp_path / "missing-dir").exists()
    assert launcher.state == "IDLE"
    regs = reg_mod.list_launches(root=bridge_env / "launches")
    assert regs == []
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_workspace"] == str(cur)


# ========== F. 当前已有 RUNNING task → 拒绝项目切换 / 第二任务启动 ==========

def test_e2e_f_running_task_blocks_switch_and_second_launch(tmp_path, bridge_env, monkeypatch):
    cur = _ws(tmp_path, "cur")
    other = _ws(tmp_path, "other")
    cfg, cfg_path = _cfg(tmp_path, cur, "Current Project")

    # 真实 RUNNING 任务：dummy runner sleep（registry RUNNING）
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "30")
    task_file = task_io.save_task(_task_text(str(cur), "F-F-RUN"), str(cur), "F-F-RUN")
    launcher = _make_launcher(bridge_env, run_py=DUMMY_RUNNER)
    out_f = launcher.default_output_dir(str(cur), "F-F-RUN")
    assert launcher.launch(task_file, str(cur), out_f, "F-F-RUN")
    assert launcher.state == "RUNNING"
    lid = launcher._active_launch["F-F-RUN"]

    # 1) 拒绝项目切换（req 7）
    plan = intake.plan_submission(_task_text(str(other), "F-F-SW"), cfg, launcher, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_REJECT
    assert plan.running_blocked
    assert any("不能切换项目" in r for r in plan.reasons)
    assert not task_io.task_target_path(str(other), "F-F-SW").exists()

    # 2) 同 workspace 第二任务：决策放行，但 launcher 既有并发保护拒绝第二 runner
    plan2 = intake.plan_submission(_task_text(str(cur), "F-F-SEC"), cfg, launcher, cfg_path=cfg_path)
    assert plan2.action == intake.ACTION_PROCEED
    target2 = intake.apply_submission(plan2, cfg_path)  # 新任务已保留（既有 contract）
    with pytest.raises(AlreadyRunningError):
        launcher.launch(target2, str(cur), launcher.default_output_dir(str(cur), "F-F-SEC"), "F-F-SEC")
    # 无第二 runner：registry 仍只有第一个活跃 launch
    regs = [e for e in reg_mod.list_launches(root=bridge_env / "launches") if e.get("state") in reg_mod.ACTIVE_STATES]
    assert [e["launch_id"] for e in regs] == [lid]

    # 清理：kill dummy 进程树，等 launcher 收敛
    reg = reg_mod.read_registry(lid, root=bridge_env / "launches")[0]
    _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
    assert _wait_until(lambda: launcher.state != "RUNNING", timeout=30)


# ========== G. duplicate RUNNING → 第二 runner 不启动 ==========

def test_e2e_g_duplicate_running_no_second_runner(tmp_path, bridge_env, monkeypatch):
    ws = _ws(tmp_path, "ws-g")
    cfg, cfg_path = _cfg(tmp_path, ws, "Project G")
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "30")

    # canonical 落盘（与真实 Bridge 提交流程一致：TASK.md 在 ws/.aaf/tasks/active/）
    task_file = task_io.save_task(_task_text(str(ws), "F-G-001"), str(ws), "F-G-001")
    launcher = _make_launcher(bridge_env, run_py=DUMMY_RUNNER)
    out_g = launcher.default_output_dir(str(ws), "F-G-001")
    assert launcher.launch(task_file, str(ws), out_g, "F-G-001")
    assert launcher.state == "RUNNING"
    lid = launcher._active_launch["F-G-001"]

    # 同 Task ID 重新提交 → reject + 卡片（running），不启动第二 runner（req 9）
    plan = intake.plan_submission(_task_text(str(ws), "F-G-001"), cfg, launcher, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None
    assert plan.duplicate.kind == dup_mod.KIND_RUNNING
    assert any("第二份 runner" in r for r in plan.reasons)
    regs = reg_mod.list_launches(root=bridge_env / "launches")
    assert len(regs) == 1 and regs[0]["launch_id"] == lid  # 无新 registry 条目

    # 清理
    reg = reg_mod.read_registry(lid, root=bridge_env / "launches")[0]
    _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
    assert _wait_until(lambda: launcher.state != "RUNNING", timeout=30)


# ========== H. duplicate terminal → 不覆盖 artifacts + 清晰提示 ==========

def test_e2e_h_duplicate_terminal_no_overwrite(tmp_path, bridge_env):
    ws = _ws(tmp_path, "ws-h")
    cfg, cfg_path = _cfg(tmp_path, ws, "Project H")
    launcher = _make_launcher(bridge_env)

    # 构造真实已完成任务（canonical SUCCESS + REPORT + run.json 完整产物）
    task_dir = ws / ".aaf" / "F-H-DONE"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    (task_dir / "run.json").write_text(json.dumps({"status": "SUCCESS", "task_id": "F-H-DONE"}), encoding="utf-8")
    task_lifecycle.finalize_terminal(
        task_dir, task_id="F-H-DONE", status="SUCCESS",
        task_path=str(ws / ".aaf" / "tasks" / "active" / "F-H-DONE.md"),
        workspace=str(ws), report_path=str(task_dir / "REPORT.md"),
        stage="COMPLETED", phase_state="SUCCESS",
    )
    active = task_io.task_target_path(str(ws), "F-H-DONE")
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(_task_text(str(ws), "F-H-DONE"), encoding="utf-8")
    before = _hash_dir(task_dir)
    before_active = active.read_bytes()

    plan = intake.plan_submission(_task_text(str(ws), "F-H-DONE"), cfg, launcher, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None
    assert plan.duplicate.kind == dup_mod.KIND_COMPLETED
    assert plan.duplicate.report_path == str(task_dir / "REPORT.md")
    assert any("需新 Task ID" in r for r in plan.reasons)  # 清晰提示（req 10）

    # 历史 artifacts 未被覆盖（req 10）；无新执行
    assert _hash_dir(task_dir) == before
    assert active.read_bytes() == before_active
    assert launcher.state == "IDLE"
    assert reg_mod.list_launches(root=bridge_env / "launches") == []


# ========== I. Bridge restart → current project + duplicate protection 恢复 ==========

def test_e2e_i_restart_recovers_project_and_duplicate_protection(tmp_path, bridge_env, monkeypatch):
    cur = _ws(tmp_path, "cur")
    other = _ws(tmp_path, "other")
    cfg, cfg_path = _cfg(tmp_path, cur, "Current Project")

    # 实例 A：切换并启动一个真实 RUNNING 任务（dummy sleep）在 other
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "30")
    task_file = task_io.save_task(_task_text(str(other), "F-I-RUN"), str(other), "F-I-RUN")
    launcher_a = _make_launcher(bridge_env, run_py=DUMMY_RUNNER)
    out_i = launcher_a.default_output_dir(str(other), "F-I-RUN")
    assert launcher_a.launch(task_file, str(other), out_i, "F-I-RUN")
    assert launcher_a.state == "RUNNING"
    lid = launcher_a._active_launch["F-I-RUN"]
    # 切换持久化
    cfg_mod.update_project("Other Project", str(other), cfg_path)
    assert cfg_mod.same_workspace(cfg_mod.load_config(cfg_path)["current_workspace"], str(other))

    # 实例 B = Bridge restart（零内存；同一 registry/config 根）
    launcher_b = _make_launcher(bridge_env, run_py=DUMMY_RUNNER)
    recovered = launcher_b.recover_launches(bridge_env / "launches")
    assert lid in recovered  # RUNNING launch 被重新认证

    # 1) current project 恢复正确（req 13/6：不因重启忘记已确认项目）
    cfg_b = cfg_mod.load_config(cfg_path)
    assert cfg_mod.same_workspace(cfg_b["current_workspace"], str(other))
    assert cfg_b["current_project"] == "Other Project"
    assert cfg_b["recent_projects"][0]["workspace"] == str(other)

    # 2) duplicate protection 仍有效：同 Task ID 重新提交 → running reject（registry 活跃）
    plan = intake.plan_submission(_task_text(str(other), "F-I-RUN"), cfg_b, launcher_b, cfg_path=cfg_path)
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None and plan.duplicate.kind == dup_mod.KIND_RUNNING

    # 3) 新 Task ID 在 other（= current）→ 正常 proceed（切换后的项目被记住）
    plan2 = intake.plan_submission(_task_text(str(other), "F-I-NEW"), cfg_b, launcher_b, cfg_path=cfg_path)
    assert plan2.action == intake.ACTION_PROCEED

    # 清理
    reg = reg_mod.read_registry(lid, root=bridge_env / "launches")[0]
    _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
    assert _wait_until(lambda: launcher_b.state != "RUNNING", timeout=30)
