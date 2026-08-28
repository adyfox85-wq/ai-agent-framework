"""Phase E / TASK-005-B — Process Ownership + Force Cancel + Recovery（单元/集成层）。

覆盖 TASK req 32 的 A–AN 矩阵中不依赖真实 taskkill 的部分（真实进程树 force-kill
E2E 见 test_phase_e_force_e2e.py）：

  A  launch_id unique / B control schema / C registry PREPARED / D registry RUNNING /
  E  runner handshake correct / F handshake mismatch rejected / G PID stored /
  H  creation time stored / I command line stored / J ownership verified happy path /
  K  PID mismatch refused / L creation-time mismatch refused / M command-line mismatch /
  N  workspace mismatch / O task_id mismatch / P registry/control launch_id mismatch /
  Q  superseded refused / R terminal task refused / S process missing refused /
  T  restart reauthentication success / U restart reauthentication uncertain /
  V  launcher_instance_id mismatch allowed / AG wait thread follows canonical CANCELLED /
  AI/AJ reconciliation missing run.json / REPORT（真实 Core CLI 子进程）/
  AK registry EXITED / AL last_run mirrors canonical /
  AM 无 UI Stop 按钮泄漏 / AN 无 project switching 泄漏 /
  AE/AF normal-vs-force race（真实跨进程 state.lock 仲裁）/
  AC/AD fake/stale force evidence rejected（finalizer 层）

Force kill 相关（Y/Z/W/X/AA/AB）与 restart E2E 在 test_phase_e_force_e2e.py。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import control as control_mod
from ai_agent_framework import force_evidence as fe_mod
from ai_agent_framework import runner as runner_mod
from ai_agent_framework.task_lifecycle import (
    finalize_terminal,
    read_status,
    update_status,
)

from bridge import launch_registry as reg_mod
from bridge import launcher as launcher_mod
from bridge import ownership as own_mod
from bridge.launcher import FrameworkLauncher

REPO_ROOT = Path(__file__).resolve().parent.parent

TID = "T-OWN-005B"

VALID_TASK = """# Task ID
T-OWN-005B

# Task Name
Phase E ownership

# Objective
验证 process ownership protocol

# Acceptance
1. 通过
"""


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    return task_file


def _iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).isoformat(timespec="milliseconds")


def _old_iso(**kwargs) -> str:
    return (datetime.now() - timedelta(**kwargs)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def _bridge_root_env(tmp_path, monkeypatch):
    """FIX-001：Core finalizer 从 canonical Bridge registry root（AAF_BRIDGE_DIR）
    推导 registry/evidence 路径——本模块所有 registry 操作必须落在同一 tmp 根，
    不得污染真实 ~/.aaf-bridge，也不得依赖 evidence.registry_path 作 locator。"""
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path / "aaf-bridge"))
    yield tmp_path / "aaf-bridge" / "launches"


# ---------------------------------------------------------------------------
# launch 上下文构造（registry + control + canonical RUNNING 一致三元组）
# ---------------------------------------------------------------------------


def _make_context(
    tmp_path: Path,
    *,
    task_id: str = TID,
    runner_pid: int = 424242,
    creation_time: str | None = None,
    registry_dir: Path | None = None,
    launcher_instance_id: str = "inst-A",
) -> tuple[str, Path, Path, dict, Path | None]:
    ws = tmp_path / "ws"
    out = ws / ".aaf" / task_id
    out.mkdir(parents=True, exist_ok=True)
    lid = reg_mod.new_launch_id()
    ct = creation_time or _iso()
    argv = [
        sys.executable, str(tmp_path / "run.py"), str(tmp_path / "TASK.md"),
        "--workspace", str(ws), "--output", str(out), "--launch-id", lid,
    ]
    reg_mod.create_prepared(
        launch_id=lid, task_id=task_id, workspace=str(ws), output_dir=str(out),
        expected_runner_entry="run.py", expected_command_line=argv,
        launcher_instance_id=launcher_instance_id, root=registry_dir,
    )
    reg_mod.mark_running(lid, runner_pid, ct, root=registry_dir)
    control_mod.write_control(
        out, control_mod.new_control(
            task_id=task_id, workspace=str(ws), launch_id=lid,
            launcher_pid=os.getpid(), launcher_instance_id=launcher_instance_id,
            expected_runner_entry="run.py", expected_command_line=argv,
        ), task_id=task_id,
    )
    control_mod.update_control(out, {"runner_pid": runner_pid, "runner_creation_time": ct}, task_id=task_id)
    update_status(out, task_id=task_id, status="RUNNING", task_path="T.md", workspace=str(ws))
    live = {"pid": runner_pid, "exists": True, "creation_time": ct, "command_line": argv}
    return lid, out, ws, live, registry_dir


def _verify(task_id, lid, live, registry_dir) -> own_mod.OwnershipVerdict:
    return own_mod.verify_runner_ownership(
        task_id=task_id, launch_id=lid, registry_dir=registry_dir,
        live_identity_override=live,
    )


# ---------------------------------------------------------------------------
# A. launch_id unique（req 32-A）
# ---------------------------------------------------------------------------


def test_a_launch_id_unique_and_format():
    ids = {reg_mod.new_launch_id() for _ in range(64)}
    assert len(ids) == 64
    for lid in ids:
        assert len(lid) == 32 and all(c in "0123456789abcdef" for c in lid)


def test_a_launcher_generates_unique_launch_id_per_launch(tmp_path, monkeypatch):
    """同一 task 两次 launch → 不同 launch_id（TASK req 2：新 launch 必须新 launch_id）。"""
    class _P:
        pid = 9999
        stdout = None
        def wait(self): return 0
    monkeypatch.setattr(launcher_mod.subprocess, "Popen", lambda *a, **k: _P())
    reg_dir = tmp_path / "reg"
    l = FrameworkLauncher(run_py=tmp_path / "run.py", registry_dir=reg_dir)
    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    out = ws / ".aaf" / TID
    assert l.launch(task_file, str(ws), out, TID) is True
    lid1 = l._active_launch[TID]
    # 等待线程很快收尾；再启动第二次
    deadline = time.monotonic() + 5
    while l.state != launcher_mod.FINISHED and time.monotonic() < deadline:
        time.sleep(0.05)
    assert l.launch(task_file, str(ws), out, TID) is True
    lid2 = l._active_launch[TID]
    assert lid1 != lid2
    assert len(lid1) == 32 and len(lid2) == 32


# ---------------------------------------------------------------------------
# B. control.json schema / 原子写（req 32-B / req 3/4）
# ---------------------------------------------------------------------------


def test_b_control_schema_and_atomic_write(tmp_path):
    out = tmp_path / "out"
    data = control_mod.new_control(
        task_id="T1", workspace=str(tmp_path), launch_id="a" * 32,
        launcher_pid=os.getpid(), launcher_instance_id="inst",
        expected_runner_entry="run.py", expected_command_line=["python", "run.py"],
    )
    path = control_mod.write_control(out, data, task_id="T1")
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()  # 无 tmp 残留
    loaded, err = control_mod.read_control(out)
    assert err is None and loaded is not None
    assert loaded["launch_id"] == "a" * 32
    assert loaded["cancel_requested"] is False
    assert loaded["force_terminate_requested"] is False
    assert loaded["superseded_by"] is None

    # schema 非法 → 拒绝写入
    bad = dict(data)
    bad["launch_id"] = ""
    with pytest.raises(control_mod.ControlError, match="launch_id"):
        control_mod.write_control(out, bad, task_id="T1")

    # 损坏文件 → read_control 返回 error（fail closed）
    (out / "control.json").write_text("{broken", encoding="utf-8")
    data2, err2 = control_mod.read_control(out)
    assert data2 is None and err2 and "损坏" in err2


def test_b_update_control_read_modify_write(tmp_path):
    out = tmp_path / "out"
    data = control_mod.new_control(
        task_id="T1", workspace=str(tmp_path), launch_id="b" * 32,
        launcher_pid=os.getpid(), launcher_instance_id="inst",
        expected_runner_entry="run.py", expected_command_line=["python", "run.py"],
    )
    control_mod.write_control(out, data, task_id="T1")
    control_mod.update_control(out, {"cancel_requested": True}, task_id="T1")
    loaded, _ = control_mod.read_control(out)
    assert loaded["cancel_requested"] is True
    assert loaded["launch_id"] == "b" * 32  # 其他字段保留
    # 不存在 → update 拒绝（必须经 write_control 全量创建）
    with pytest.raises(control_mod.ControlError, match="不存在"):
        control_mod.update_control(tmp_path / "nope", {"cancel_requested": True}, task_id="T1")


# ---------------------------------------------------------------------------
# C/D. registry PREPARED → RUNNING（req 32-C/D / req 5）
# ---------------------------------------------------------------------------


def test_cd_registry_prepared_then_running(tmp_path):
    reg_dir = tmp_path / "reg"
    lid = reg_mod.new_launch_id()
    reg_mod.create_prepared(
        launch_id=lid, task_id="T1", workspace=str(tmp_path / "ws"),
        output_dir=str(tmp_path / "ws" / ".aaf" / "T1"),
        expected_runner_entry="run.py",
        expected_command_line=["python", "run.py", "T.md"],
        launcher_instance_id="inst-A", root=reg_dir,
    )
    entry, err = reg_mod.read_registry(lid, root=reg_dir)
    assert err is None
    assert entry["state"] == reg_mod.REGISTRY_STATE_PREPARED
    assert entry["launch_id"] == lid
    assert entry["runner_pid"] is None

    reg_mod.mark_running(lid, 12345, _iso(), root=reg_dir)
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    assert entry["state"] == reg_mod.REGISTRY_STATE_RUNNING
    assert entry["runner_pid"] == 12345
    assert entry["runner_creation_time"] is not None

    reg_mod.mark_exited(lid, exit_result="FINISHED", root=reg_dir)
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    assert entry["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert entry["exit_result"] == "FINISHED"

    reg_mod.mark_superseded(lid, "c" * 32, root=reg_dir)
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    assert entry["state"] == reg_mod.REGISTRY_STATE_SUPERSEDED
    assert entry["superseded_by"] == "c" * 32


def test_cd_supersede_existing_for_task(tmp_path):
    reg_dir = tmp_path / "reg"
    lid_old = reg_mod.new_launch_id()
    lid_new = reg_mod.new_launch_id()
    reg_mod.create_prepared(
        launch_id=lid_old, task_id="T1", workspace=str(tmp_path),
        output_dir=str(tmp_path / "o1"), expected_runner_entry="run.py",
        expected_command_line=["x"], launcher_instance_id="a", root=reg_dir,
    )
    reg_mod.mark_running(lid_old, 111, _iso(), root=reg_dir)
    # 另一个 task 的活跃 launch 不受影响
    lid_other = reg_mod.new_launch_id()
    reg_mod.create_prepared(
        launch_id=lid_other, task_id="OTHER", workspace=str(tmp_path),
        output_dir=str(tmp_path / "o2"), expected_runner_entry="run.py",
        expected_command_line=["x"], launcher_instance_id="a", root=reg_dir,
    )
    superseded = reg_mod.supersede_existing_for_task("T1", lid_new, root=reg_dir)
    assert superseded == [lid_old]
    entry, _ = reg_mod.read_registry(lid_old, root=reg_dir)
    assert entry["state"] == reg_mod.REGISTRY_STATE_SUPERSEDED
    assert entry["superseded_by"] == lid_new
    other, _ = reg_mod.read_registry(lid_other, root=reg_dir)
    assert other["state"] == reg_mod.REGISTRY_STATE_PREPARED  # 不受影响


# ---------------------------------------------------------------------------
# E/F. runner handshake（req 32-E/F / req 5/8）
# ---------------------------------------------------------------------------


def test_e_handshake_correct_writes_back_identity(tmp_path):
    out = tmp_path / "out"
    data = control_mod.new_control(
        task_id=TID, workspace=str(tmp_path), launch_id="e" * 32,
        launcher_pid=os.getpid(), launcher_instance_id="inst",
        expected_runner_entry="run.py", expected_command_line=["python", "run.py", "T.md"],
    )
    control_mod.write_control(out, data, task_id=TID)
    control = runner_mod.runner_handshake(out, TID, tmp_path, expected_launch_id="e" * 32)
    assert control is not None
    loaded, _ = control_mod.read_control(out)
    assert loaded["runner_pid"] == os.getpid()  # G. PID stored
    assert loaded["runner_creation_time"] is not None  # H. creation time stored
    datetime.fromisoformat(loaded["runner_creation_time"])
    assert loaded["launch_id"] == "e" * 32


def test_e_handshake_skipped_without_control(tmp_path):
    """无 control.json（direct/legacy 调用）→ 跳过，返回 None（不获得 force ownership）。"""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    assert runner_mod.runner_handshake(out, TID, tmp_path, expected_launch_id=None) is None


@pytest.mark.parametrize(
    "mutate,expected",
    [
        ("wrong-launch-id", "launch_id mismatch"),
        ("no-launch-id", "未提供 expected launch_id"),
        ("wrong-task", "task_id mismatch"),
        ("wrong-workspace", "workspace mismatch"),
        ("superseded", "supersede"),
        ("force-requested", "force_terminate_requested"),
        ("corrupt", "损坏"),
    ],
)
def test_f_handshake_mismatch_rejected(tmp_path, mutate, expected):
    out = tmp_path / "out"
    data = control_mod.new_control(
        task_id=TID, workspace=str(tmp_path), launch_id="f" * 32,
        launcher_pid=os.getpid(), launcher_instance_id="inst",
        expected_runner_entry="run.py", expected_command_line=["python", "run.py", "T.md"],
    )
    control_mod.write_control(out, data, task_id=TID)
    expected_launch_id = "f" * 32
    task_id, ws = TID, tmp_path
    if mutate == "wrong-launch-id":
        expected_launch_id = "0" * 32
    elif mutate == "no-launch-id":
        expected_launch_id = None
    elif mutate == "wrong-task":
        task_id = "OTHER-TASK"
    elif mutate == "wrong-workspace":
        ws = tmp_path / "other-ws"
    elif mutate == "superseded":
        control_mod.update_control(out, {"superseded_by": "g" * 32}, task_id=TID)
    elif mutate == "force-requested":
        control_mod.update_control(out, {"force_terminate_requested": True}, task_id=TID)
    elif mutate == "corrupt":
        (out / "control.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(runner_mod.HandshakeError, match=expected):
        runner_mod.runner_handshake(out, task_id, ws, expected_launch_id=expected_launch_id)
    if mutate == "corrupt":
        # 损坏文件无法读取；零写语义由 HandshakeError 保证（未写 runner 身份）
        raw = (out / "control.json").read_text(encoding="utf-8")
        assert "runner_pid" not in raw
        return
    # 拒绝后零写（不写 runner 身份）
    loaded, err = control_mod.read_control(out)
    assert err is None
    assert loaded["runner_pid"] is None


# ---------------------------------------------------------------------------
# I. command line stored（req 32-I）
# ---------------------------------------------------------------------------


def test_i_command_line_stored(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    assert entry["expected_runner_entry"] == "run.py"
    assert entry["expected_command_line"][0].endswith("python.exe") or "python" in entry["expected_command_line"][0].lower()
    assert "--workspace" in entry["expected_command_line"]
    assert "--output" in entry["expected_command_line"]
    ctrl, _ = control_mod.read_control(out)
    assert ctrl["expected_command_line"] == entry["expected_command_line"]


# ---------------------------------------------------------------------------
# J–S. ownership verification 矩阵（req 32-J–S / req 11）
# ---------------------------------------------------------------------------


def test_j_ownership_verified_happy_path(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    v = _verify(TID, lid, live, reg_dir)
    assert v.result == own_mod.VERIFIED
    assert v.ok()
    assert len(v.checks) == 11 and all(v.checks.values())
    assert v.failures == []


def test_k_pid_mismatch_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    live = dict(live, pid=live["pid"] + 1)
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.checks["runner_pid_match"] is False


def test_l_creation_time_mismatch_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    live = dict(live, creation_time=_iso(datetime.now() + timedelta(days=1)))
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.result == own_mod.STALE  # PID recycle 类 → STALE
    assert v.checks["creation_time_match"] is False


def test_m_command_line_mismatch_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    live = dict(live, command_line=[sys.executable, "run.py", "OTHER.md", "--workspace", str(ws)])
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.checks["command_line_match"] is False
    assert v.result == own_mod.UNCERTAIN


def test_n_workspace_mismatch_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    reg_mod.update_registry(lid, {"workspace": str(tmp_path / "other-ws")}, root=reg_dir)
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.checks["workspace_match"] is False


def test_o_task_id_mismatch_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    reg_mod.update_registry(lid, {"task_id": "WRONG"}, root=reg_dir)
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.checks["registry_control_task_id_match"] is False
    assert v.checks["target_task_id_match"] is False


def test_p_launch_id_cross_mismatch_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    control_mod.update_control(out, {"launch_id": "0" * 32}, task_id=TID)
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.checks["registry_control_launch_id_match"] is False


def test_q_superseded_refused(tmp_path):
    # control superseded_by 非空 → STALE
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    control_mod.update_control(out, {"superseded_by": "1" * 32}, task_id=TID)
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.result == own_mod.STALE
    assert v.checks["control_not_superseded"] is False

    # registry SUPERSEDED → STALE
    lid2, out2, ws2, live2, reg_dir2 = _make_context(tmp_path)
    reg_mod.mark_superseded(lid2, "2" * 32, root=reg_dir2)
    v2 = _verify(TID, lid2, live2, reg_dir2)
    assert not v2.ok()
    assert v2.result == own_mod.STALE
    assert v2.checks["registry_state_valid"] is False


def test_r_terminal_task_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    finalize_terminal(out, task_id=TID, status="CANCELLED", task_path="T.md",
                      workspace=str(ws), report_path=str(out / "REPORT.md"))
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.result == own_mod.STALE
    assert v.checks["task_not_terminal"] is False


def test_r_terminal_task_mark_exited(tmp_path):
    """TASK req 26：canonical terminal 检测 → registry 顺带 EXITED（幂等；不改 canonical）。"""
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    finalize_terminal(out, task_id=TID, status="SUCCESS", task_path="T.md",
                      workspace=str(ws), report_path=str(out / "REPORT.md"))
    v = own_mod.verify_runner_ownership(
        task_id=TID, launch_id=lid, registry_dir=reg_dir,
        live_identity_override=live, mark_exited_on_terminal=True,
    )
    assert not v.ok()
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    assert entry["state"] == reg_mod.REGISTRY_STATE_EXITED
    assert read_status(out)["status"] == "SUCCESS"  # canonical 未变


def test_s_process_missing_refused(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    live = dict(live, exists=False)
    v = _verify(TID, lid, live, reg_dir)
    assert not v.ok()
    assert v.result == own_mod.STALE
    assert v.checks["process_exists"] is False


# ---------------------------------------------------------------------------
# T/U/V. restart reauthentication（req 32-T/U/V / req 12/35）
# ---------------------------------------------------------------------------


def test_t_restart_reauthentication_success(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path, launcher_instance_id="inst-A")
    v = own_mod.reauthenticate_launch(task_id=TID, launch_id=lid, registry_dir=reg_dir,
                                      live_identity_override=live)
    assert v.result == own_mod.REAUTHENTICATED
    assert v.ok()


def test_u_restart_reauthentication_uncertain(tmp_path):
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    live = dict(live, creation_time=_iso(datetime.now() + timedelta(hours=2)))
    v = own_mod.reauthenticate_launch(task_id=TID, launch_id=lid, registry_dir=reg_dir,
                                      live_identity_override=live)
    assert not v.ok()  # 三方验证失败 → 拒绝 force kill（§6B.13）
    assert v.checks["creation_time_match"] is False
    # 创建时间不一致属 stale 类（§6A.10）；STALE / UNCERTAIN 都拒绝 force
    assert v.result in (own_mod.UNCERTAIN, own_mod.STALE)


def test_v_launcher_instance_id_mismatch_allowed(tmp_path):
    """§6B.16 / req 32-V：restart 后 launcher_instance_id 不同**不**是恢复前提。"""
    lid, out, ws, live, reg_dir = _make_context(tmp_path, launcher_instance_id="inst-A")
    v = own_mod.reauthenticate_launch(task_id=TID, launch_id=lid, registry_dir=reg_dir,
                                      live_identity_override=live)
    assert v.result == own_mod.REAUTHENTICATED
    assert v.checks["registry_control_launch_id_match"] is True
    # 显式：registry 与当前 launcher 的 instance id 不同仍通过
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    assert entry["launcher_instance_id"] == "inst-A"


# ---------------------------------------------------------------------------
# AE/AF. normal vs force race（req 32-AE/AF / req 23；真实跨进程 state.lock）
# ---------------------------------------------------------------------------


def _spawn_worker(tmp_path: Path, worker: str, *args: str) -> subprocess.Popen:
    script = tmp_path / f"w_{abs(hash(worker + str(args)))}.py"
    script.write_text(worker, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.Popen(
        [sys.executable, str(script), *args], cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )


def _run_worker(proc: subprocess.Popen) -> str:
    out_text = proc.communicate(timeout=90)[0] or ""
    assert proc.returncode == 0, f"worker 异常退出: {out_text}"
    return out_text


SUCCESS_HOLDER = """\
import sys, time
from pathlib import Path
from ai_agent_framework.task_lifecycle import finalize_terminal

out, tid, ws, ready, release = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
c = finalize_terminal(out, task_id=tid, status="SUCCESS", task_path=Path(out, "T.md"),
                      workspace=ws, report_path=str(Path(out, "REPORT.md")))
Path(ready).write_text(f"COMMITTED {{c.status}} gen={{c.terminal_generation}}", encoding="utf-8")
time.sleep(float(release))
print("DONE", c.status, c.terminal_generation, c.preserved)
"""


def _force_evidence_bundle(tmp_path: Path, lid: str, out: Path, ws: Path, runner_pid: int,
                           reg_dir: Path) -> Path:
    """构造与 registry/control 一致的合法 force evidence（finalizer 层测试用）。

    FIX-001：evidence 位于 canonical Bridge location（registry root + launch_id
    推导）、termination_exit_status == 0，且 registry 独立记录 durable force
    termination 事实（req 6）并与 evidence 逐项一致——模拟 Launcher step 7。
    """
    ctrl, _ = control_mod.read_control(out)
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    ev = fe_mod.build_force_evidence(
        task_id=TID, launch_id=lid, runner_pid=runner_pid,
        runner_creation_time=entry["runner_creation_time"],
        workspace=str(ws), output_dir=str(out),
        expected_runner_entry=entry["expected_runner_entry"],
        expected_command_line=entry["expected_command_line"],
        verification_result="VERIFIED",
        verification_checks={name: True for name in own_mod.CHECK_NAMES},
        termination_requested_at=_old_iso(seconds=30),
        termination_observed_at=_iso(),
        termination_exit_status=fe_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS,
        termination_command=["taskkill", "/T", "/F", "/PID", str(runner_pid)],
        registry_path=str(reg_mod.registry_path(lid, reg_dir)),
        control_path=str(control_mod.control_path(out)),
    )
    ev_path = reg_mod.force_evidence_path_for(lid, reg_dir)
    fe_mod.write_force_evidence(ev_path, ev)
    # durable bridge evidence（FIX-001 req 6）：registry 独立记录 termination 事实
    reg_mod.update_registry(
        lid,
        {
            "force_terminate_requested_at": ev["termination_requested_at"],
            "force_termination_observed_at": ev["termination_observed_at"],
            "force_termination_exit_status": ev["termination_exit_status"],
            "force_evidence_path": str(ev_path),
            "force_termination_verification_result": ev["verification_result"],
            "force_termination_verification_checks": ev["verification_checks"],
        },
        root=reg_dir,
    )
    return ev_path


def test_ae_race_case_a_runner_success_first_preserved(tmp_path):
    """Case A（§6B.18）：Runner 先持锁 commit SUCCESS（持有期间 force finalizer 阻塞）
    → finalizer 后获锁看到 SUCCESS → preserve（force loses）。"""
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    # 标记 force 请求（finalizer 前置条件）
    control_mod.update_control(out, {"force_terminate_requested": True}, task_id=TID)
    ev_path = _force_evidence_bundle(tmp_path, lid, out, ws, live["pid"], reg_dir)

    ready = tmp_path / "ready.txt"
    proc_success = _spawn_worker(tmp_path, SUCCESS_HOLDER, str(out), TID, str(ws), str(ready), "1.2")
    # 等 SUCCESS 已提交且锁仍被持有
    deadline = time.monotonic() + 30
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists(), "SUCCESS 提交信号超时"

    from ai_agent_framework import finalize_cancelled as fc_mod

    canonical = fc_mod.finalize_cancelled_task(
        TID, ws, out, cancel_mode="force", force_evidence=ev_path
    )
    proc_success.communicate(timeout=60)
    assert proc_success.returncode == 0
    assert canonical.status == "SUCCESS" and canonical.preserved is True
    assert read_status(out)["status"] == "SUCCESS"  # SUCCESS wins（先 commit 者）


def test_af_race_case_b_force_cancelled_first_preserved(tmp_path):
    """Case B（§6B.18）：force finalizer 先 commit CANCELLED → Runner 后尝试 SUCCESS
    → 锁内 reload 看到 CANCELLED → preserved（CANCELLED wins）。"""
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    control_mod.update_control(out, {"force_terminate_requested": True}, task_id=TID)
    ev_path = _force_evidence_bundle(tmp_path, lid, out, ws, live["pid"], reg_dir)

    from ai_agent_framework import finalize_cancelled as fc_mod

    canonical = fc_mod.finalize_cancelled_task(
        TID, ws, out, cancel_mode="force", force_evidence=ev_path
    )
    assert canonical.status == "CANCELLED" and canonical.preserved is False
    # Runner 后到：SUCCESS 尝试被仲裁保留为 CANCELLED
    c2 = finalize_terminal(out, task_id=TID, status="SUCCESS", task_path=Path(out, "T.md"),
                           workspace=ws, report_path=str(Path(out, "REPORT.md")))
    assert c2.status == "CANCELLED" and c2.preserved is True
    assert read_status(out)["status"] == "CANCELLED"
    assert read_status(out)["terminal_generation"] == canonical.terminal_generation


# ---------------------------------------------------------------------------
# AC/AD. fake / stale force evidence rejected（req 32-AC/AD / req 20/22）
# ---------------------------------------------------------------------------


def test_ac_fake_force_evidence_rejected(tmp_path):
    from ai_agent_framework import finalize_cancelled as fc_mod

    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    ev_path = tmp_path / "fake.json"
    # 任意字符串 → 拒绝
    ev_path.write_text("process killed", encoding="utf-8")
    with pytest.raises(fc_mod.ForceEvidenceError):
        fc_mod.finalize_cancelled_task(TID, ws, out, cancel_mode="force", force_evidence=ev_path)
    # 结构合法但 verification_checks 含 False → 拒绝（ownership 未全部通过）
    entry, _ = reg_mod.read_registry(lid, root=reg_dir)
    bad = fe_mod.build_force_evidence(
        task_id=TID, launch_id=lid, runner_pid=live["pid"],
        runner_creation_time=entry["runner_creation_time"], workspace=str(ws),
        output_dir=str(out), expected_runner_entry="run.py",
        expected_command_line=entry["expected_command_line"],
        verification_result="VERIFIED",
        verification_checks={"process_exists": False},
        termination_requested_at=_old_iso(seconds=30), termination_observed_at=_iso(),
        termination_exit_status=fe_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS,
        termination_command=["taskkill"],
        registry_path=str(reg_mod.registry_path(lid, reg_dir)),
        control_path=str(control_mod.control_path(out)),
    )
    with pytest.raises(fe_mod.ForceEvidenceError, match="verification_checks"):
        fe_mod.write_force_evidence(tmp_path / "bad2.json", bad)
    # task_id mismatch → 拒绝（不写 canonical）
    wrong = fe_mod.build_force_evidence(
        task_id="WRONG", launch_id=lid, runner_pid=live["pid"],
        runner_creation_time=entry["runner_creation_time"], workspace=str(ws),
        output_dir=str(out), expected_runner_entry="run.py",
        expected_command_line=entry["expected_command_line"],
        verification_result="VERIFIED",
        verification_checks={name: True for name in own_mod.CHECK_NAMES},
        termination_requested_at=_old_iso(seconds=30), termination_observed_at=_iso(),
        termination_exit_status=fe_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS,
        termination_command=["taskkill"],
        registry_path=str(reg_mod.registry_path(lid, reg_dir)),
        control_path=str(control_mod.control_path(out)),
    )
    ev2 = tmp_path / "wrong-task.json"
    fe_mod.write_force_evidence(ev2, wrong)
    with pytest.raises(fc_mod.ForceEvidenceError, match="task_id"):
        fc_mod.finalize_cancelled_task(TID, ws, out, cancel_mode="force", force_evidence=ev2)
    assert "terminal_generation" not in read_status(out)


def test_ad_stale_force_evidence_rejected(tmp_path):
    from ai_agent_framework import finalize_cancelled as fc_mod

    # control 已 superseded → stale evidence 拒绝
    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    control_mod.update_control(out, {"superseded_by": "9" * 32, "force_terminate_requested": True}, task_id=TID)
    ev_path = _force_evidence_bundle(tmp_path, lid, out, ws, live["pid"], reg_dir)
    with pytest.raises(fc_mod.ForceEvidenceError, match="superseded"):
        fc_mod.finalize_cancelled_task(TID, ws, out, cancel_mode="force", force_evidence=ev_path)
    assert "terminal_generation" not in read_status(out)

    # registry SUPERSEDED → stale evidence 拒绝
    lid2, out2, ws2, live2, reg_dir2 = _make_context(tmp_path)
    control_mod.update_control(out2, {"force_terminate_requested": True}, task_id=TID)
    reg_mod.mark_superseded(lid2, "8" * 32, root=reg_dir2)
    ev2 = _force_evidence_bundle(tmp_path, lid2, out2, ws2, live2["pid"], reg_dir2)
    with pytest.raises(fc_mod.ForceEvidenceError, match="SUPERSEDED"):
        fc_mod.finalize_cancelled_task(TID, ws2, out2, cancel_mode="force", force_evidence=ev2)
    assert "terminal_generation" not in read_status(out2)


def test_ad_control_force_mark_missing_rejected(tmp_path):
    """evidence 合法但 control.force_terminate_requested != true → 拒绝
    （Launcher 未确认 force 请求；evidence 与 control 不匹配）。"""
    from ai_agent_framework import finalize_cancelled as fc_mod

    lid, out, ws, live, reg_dir = _make_context(tmp_path)
    ev_path = _force_evidence_bundle(tmp_path, lid, out, ws, live["pid"], reg_dir)
    with pytest.raises(fc_mod.ForceEvidenceError, match="force_terminate_requested"):
        fc_mod.finalize_cancelled_task(TID, ws, out, cancel_mode="force", force_evidence=ev_path)
    assert "terminal_generation" not in read_status(out)


# ---------------------------------------------------------------------------
# AG. wait thread follows canonical CANCELLED（req 32-AG / req 24/25）
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, exit_code: int = 0, stdout_text: str = ""):
        import io

        self._exit = exit_code
        self.stdout = io.StringIO(stdout_text)
        self.returncode = None
        self.pid = 777777

    def wait(self) -> int:
        self.returncode = self._exit
        return self._exit


def test_ag_wait_thread_follows_canonical_cancelled(tmp_path, monkeypatch):
    """exit=1（force-kill 后非零退出）+ canonical CANCELLED + 派生产物一致
    → RESULT_CANCELLED（不得映射 FAILED；req 25/AH）。"""
    from bridge import launcher as launcher_mod

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    finalize_terminal(out, task_id=TID, status="CANCELLED", task_path=task_file,
                      workspace=str(ws), report_path=str(out / "REPORT.md"))
    (out / "run.json").write_text(json.dumps({"status": "CANCELLED", "terminal_generation": 1, "task_id": TID}),
                                  encoding="utf-8")
    (out / "REPORT.md").write_text(
        "# REPORT\n\n## Current Status\nCANCELLED\n## Terminal Generation\n1\n", encoding="utf-8")
    monkeypatch.setattr(launcher_mod.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(exit_code=1, stdout_text=""))

    done = threading.Event()
    captured = {}
    l = launcher_mod.FrameworkLauncher(run_py=tmp_path / "run.py",
                                       registry_dir=tmp_path / "reg",
                                       on_finished=lambda last, output: (captured.__setitem__("last", last), done.set()))
    assert l.launch(task_file, str(ws), out, TID) is True
    assert done.wait(8.0)
    assert l.last.result == launcher_mod.RESULT_CANCELLED
    assert l.last.exit_code == 1  # exit code 保留为 evidence，不参与判定
    assert l.last.terminal_generation == 1
    # registry → EXITED（AK）
    lid = l._active_launch.get(TID)  # pop 已发生 → 从 registry 找
    entries = reg_mod.list_launches(state=reg_mod.REGISTRY_STATE_EXITED, root=tmp_path / "reg")
    assert entries and entries[0]["exit_result"] == launcher_mod.RESULT_CANCELLED


# ---------------------------------------------------------------------------
# AL. last_run mirrors canonical（req 32-AL / req 25）
# ---------------------------------------------------------------------------


def test_al_last_run_mirrors_canonical_cancelled(tmp_path, monkeypatch):
    """wait thread 完成后 last_run.result 跟随 canonical CANCELLED（不因 exit code）。"""
    from bridge import launcher as launcher_mod

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    finalize_terminal(out, task_id=TID, status="CANCELLED", task_path=task_file,
                      workspace=str(ws), report_path=str(out / "REPORT.md"))
    (out / "run.json").write_text(json.dumps({"status": "CANCELLED", "terminal_generation": 1, "task_id": TID}),
                                  encoding="utf-8")
    (out / "REPORT.md").write_text(
        "# REPORT\n\n## Current Status\nCANCELLED\n## Terminal Generation\n1\n", encoding="utf-8")
    monkeypatch.setattr(launcher_mod.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(exit_code=0, stdout_text=""))
    l = launcher_mod.FrameworkLauncher(run_py=tmp_path / "run.py",
                                       registry_dir=tmp_path / "reg",
                                       on_finished=lambda last, output: None)
    assert l.launch(task_file, str(ws), out, TID) is True
    deadline = time.monotonic() + 8
    while l.state != launcher_mod.FINISHED and time.monotonic() < deadline:
        time.sleep(0.05)
    assert l.state == launcher_mod.FINISHED
    assert l.last.result == launcher_mod.RESULT_CANCELLED
    assert l.last.launch_id is not None


# ---------------------------------------------------------------------------
# AM/AN. 无 UI Stop 按钮泄漏 / 无 project switching 泄漏（req 32-AM/AN / req 30）
# ---------------------------------------------------------------------------


def test_am_no_ui_stop_button_leakage():
    """005-B 不交付最终 Stop UX（005-C 范围）：status_window / tray / main 无
    「停止当前任务」按钮、无 force-cancel UI 调用（TASK req 30/31）。

    注意：status_window.py 的 docstring 明确声明「停止当前任务 属 TASK-005-C，
    本窗口不实现」——这是边界声明，不是泄漏；断言只针对实际按钮与 UI 调用。"""
    for rel in ("bridge/status_window.py", "bridge/tray.py", "bridge/main.py"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert 'text="停止当前任务"' not in text, f"{rel} 出现 Stop 按钮"
        assert "request_force_cancel(" not in text, f"{rel} 直接调用 force cancel API（005-C 接入）"
        assert "force_eligible(" not in text, f"{rel} 直接使用 force-eligible 状态（005-C 接入）"
        assert ".request_force_cancel" not in text and "force_cancel" not in text.replace("force_cancel_soft_timeout", ""), \
            f"{rel} 出现 force-cancel UI 接入"


def test_an_no_project_switching_leakage():
    """Phase F（project switching / duplicate UX）不得泄漏进 005-B 改动（req 30/AN）。"""
    for rel in ("bridge/launcher.py", "bridge/ownership.py", "bridge/launch_registry.py",
                "bridge/main.py"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "update_project" not in text, f"{rel} 泄漏 Phase F update_project"
        assert "recent_projects" not in text, f"{rel} 泄漏 Phase F recent_projects"


def test_static_core_files_no_process_control():
    """Core 侧新增文件不得具备进程控制能力（与 fix_001/002 静态断言同规则）。"""
    core_files = [
        "ai_agent_framework/proc_identity.py",
        "ai_agent_framework/control.py",
        "ai_agent_framework/force_evidence.py",
        "ai_agent_framework/runner.py",
        "ai_agent_framework/finalize_cancelled.py",
        "ai_agent_framework/reconcile.py",
        "ai_agent_framework/task_lifecycle.py",
        "ai_agent_framework/lock_utils.py",
        "ai_agent_framework/cancel.py",
    ]
    for rel in core_files:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "from subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "os.kill" not in text, f"{rel} 包含 os.kill"
        assert ".kill(" not in text, f"{rel} 包含 .kill("
        assert ".terminate(" not in text, f"{rel} 包含 .terminate("
        assert "Popen" not in text, f"{rel} 包含 Popen"
