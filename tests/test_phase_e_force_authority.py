"""Phase E / 005-B-FIX-001 — Force Recovery Authority + Successful Termination Proof.

finalizer 层 authority 矩阵（FIX-001 req 1–7 / 10 反向部分；正向真实 E2E 见
test_phase_e_force_e2e.py）：

正向：
- 全一致（canonical registry + canonical evidence + control + registry durable
  force 字段 + termination_exit_status == 0）→ CANCELLED 提交 + 派生产物跟随

反向（任一失败 → ForceEvidenceError，零 canonical 写、任务保持非终态）：
- 非 canonical evidence 路径（任意外部文件）
- fake registry（canonical 路径上是垃圾 JSON / 另一 launch 的 schema-合法记录）
- registry 缺 durable force 字段（Bridge 在 evidence 写后、registry 更新前崩溃）
- termination_exit_status != 0（1 / 128 / -1）
- registry durable 字段与 evidence 逐项不一致（requested / observed / status /
  evidence path / verification result / verification checks）
- 三方 identity 任一不一致（registry 侧：workspace / output_dir / PID /
  creation time / expected entry / expected command；control 侧：workspace /
  creation time / expected command）
- registry state PREPARED / SUPERSEDED

CLI 级（真实子进程 + AAF_BRIDGE_DIR）：canonical → exit 0 + CANCELLED；
status=1 → exit 6 + 零 canonical 写。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_agent_framework import control as control_mod
from ai_agent_framework import finalize_cancelled as fc_mod
from ai_agent_framework import force_evidence as fe_mod
from ai_agent_framework.task_lifecycle import read_status

from bridge import launch_registry as reg_mod
from bridge import ownership as own_mod

REPO_ROOT = Path(__file__).resolve().parent.parent

TID = "T-AUTH-005B"

VALID_TASK = """# Task ID
T-AUTH-005B

# Task Name
Force recovery authority

# Objective
验证 canonical authority 绑定

# Acceptance
1. 通过
"""


@pytest.fixture(autouse=True)
def _bridge_root_env(tmp_path, monkeypatch):
    """canonical Bridge registry root（AAF_BRIDGE_DIR）——finalizer 的 authority 根。"""
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path / "aaf-bridge"))
    yield tmp_path / "aaf-bridge" / "launches"


def _iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).isoformat(timespec="milliseconds")


def _old_iso(seconds: float = 30.0) -> str:
    return (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    return task_file


def _make_ctx(tmp_path: Path, reg_dir: Path) -> dict:
    """构造全一致三元组：registry(RUNNING) + control(force 标记) + canonical RUNNING
    + canonical force evidence(status 0) + registry durable force 字段。"""
    ws = tmp_path / "ws"
    out = ws / ".aaf" / TID
    out.mkdir(parents=True, exist_ok=True)
    _write_task(tmp_path)
    lid = reg_mod.new_launch_id()
    ct = _iso()
    argv = [
        sys.executable, str(tmp_path / "run.py"), str(tmp_path / "TASK.md"),
        "--workspace", str(ws), "--output", str(out), "--launch-id", lid,
    ]
    reg_mod.create_prepared(
        launch_id=lid, task_id=TID, workspace=str(ws), output_dir=str(out),
        expected_runner_entry="run.py", expected_command_line=argv,
        launcher_instance_id="inst-A", root=reg_dir,
    )
    reg_mod.mark_running(lid, 424242, ct, root=reg_dir)
    control_mod.write_control(
        out, control_mod.new_control(
            task_id=TID, workspace=str(ws), launch_id=lid,
            launcher_pid=os.getpid(), launcher_instance_id="inst-A",
            expected_runner_entry="run.py", expected_command_line=argv,
        ), task_id=TID,
    )
    control_mod.update_control(
        out, {"runner_pid": 424242, "runner_creation_time": ct,
              "force_terminate_requested": True}, task_id=TID,
    )
    from ai_agent_framework.task_lifecycle import update_status

    update_status(out, task_id=TID, status="RUNNING", task_path="T.md", workspace=str(ws))

    ev = fe_mod.build_force_evidence(
        task_id=TID, launch_id=lid, runner_pid=424242,
        runner_creation_time=ct, workspace=str(ws), output_dir=str(out),
        expected_runner_entry="run.py", expected_command_line=argv,
        verification_result="VERIFIED",
        verification_checks={name: True for name in own_mod.CHECK_NAMES},
        termination_requested_at=_old_iso(), termination_observed_at=_iso(),
        termination_exit_status=fe_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS,
        termination_command=["taskkill", "/T", "/F", "/PID", "424242"],
        registry_path=str(reg_mod.registry_path(lid, reg_dir)),
        control_path=str(control_mod.control_path(out)),
    )
    ev_path = reg_mod.force_evidence_path_for(lid, reg_dir)
    fe_mod.write_force_evidence(ev_path, ev)
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
    return {"lid": lid, "out": out, "ws": ws, "ev_path": ev_path, "reg_dir": reg_dir,
            "ev": ev, "argv": argv, "ct": ct}


def _assert_no_terminal(out: Path) -> None:
    """fail closed 断言：零 canonical 写、任务保持非终态。"""
    data = read_status(out)
    assert data.get("status") in (None, "RUNNING"), f"不应产生新 terminal: {data.get('status')}"
    assert "terminal_generation" not in data, "不应产生 terminal_generation"


def _finalize(ctx: dict):
    return fc_mod.finalize_cancelled_task(
        TID, ctx["ws"], ctx["out"], cancel_mode="force", force_evidence=ctx["ev_path"],
    )


# ---------------------------------------------------------------------------
# 正向：全一致 → CANCELLED（FIX-001 req 10 正向，finalizer 层）
# ---------------------------------------------------------------------------


def test_positive_full_consistent_authorizes_cancelled(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    canonical = _finalize(ctx)
    assert canonical.status == "CANCELLED" and canonical.preserved is False
    data = read_status(ctx["out"])
    assert data["status"] == "CANCELLED" and data["cancel_mode"] == "force"
    # 派生产物跟随（reconciliation）
    run = json.loads((ctx["out"] / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1
    report = (ctx["out"] / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report


# ---------------------------------------------------------------------------
# 反向 1：canonical path binding（req 1/2）
# ---------------------------------------------------------------------------


def test_negative_noncanonical_evidence_path_rejected(tmp_path):
    """内容合法但文件位于 canonical Bridge location 之外 → 拒绝（req 2）。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    outside = tmp_path / "outside-evidence.json"
    fe_mod.write_force_evidence(outside, ctx["ev"])
    with pytest.raises(fc_mod.ForceEvidenceError, match="canonical"):
        fc_mod.finalize_cancelled_task(
            TID, ctx["ws"], ctx["out"], cancel_mode="force", force_evidence=outside,
        )
    _assert_no_terminal(ctx["out"])


def test_negative_evidence_registry_path_proof_mismatch_rejected(tmp_path):
    """evidence.registry_path 指向 canonical 之外 → 拒绝（req 1：只作 proof）。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    forged = dict(ctx["ev"])
    forged["registry_path"] = str(tmp_path / "forged-registry.json")
    fe_mod.write_force_evidence(ctx["ev_path"], forged)  # 仍在 canonical 文件位置
    with pytest.raises(fc_mod.ForceEvidenceError, match="registry_path"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_fake_registry_at_canonical_path_rejected(tmp_path):
    """canonical 路径上是垃圾 JSON → 官方 read contract schema 校验拒绝。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    (reg_mod.registry_path(ctx["lid"])).write_text("not-json", encoding="utf-8")
    with pytest.raises(fc_mod.ForceEvidenceError):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_replaced_with_other_launch_record_rejected(tmp_path):
    """canonical 路径被换成另一 launch 的 schema-合法记录（unrelated）→ 拒绝。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    other_lid = reg_mod.new_launch_id()
    reg_mod.create_prepared(
        launch_id=other_lid, task_id="OTHER-TASK", workspace=str(tmp_path / "other"),
        output_dir=str(tmp_path / "other" / ".aaf" / "OTHER-TASK"),
        expected_runner_entry="run.py", expected_command_line=[sys.executable, "run.py"],
        launcher_instance_id="inst-B", root=ctx["reg_dir"],
    )
    other_entry, _ = reg_mod.read_registry(other_lid, root=ctx["reg_dir"])
    (reg_mod.registry_path(ctx["lid"])).write_text(
        json.dumps(other_entry, ensure_ascii=False), encoding="utf-8",
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="launch_id"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_missing_durable_force_fields_rejected(tmp_path):
    """Bridge 在 evidence 写后、registry 更新前崩溃（缺 durable 字段）→ fail closed。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"],
        {
            "force_terminate_requested_at": None, "force_termination_observed_at": None,
            "force_termination_exit_status": None, "force_evidence_path": None,
            "force_termination_verification_result": None,
            "force_termination_verification_checks": None,
        },
        root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


# ---------------------------------------------------------------------------
# 反向 2：成功终止证明（req 5）——nonzero / missing / malformed → fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_status", [1, 128, -1, 999])
def test_negative_nonzero_termination_status_rejected(tmp_path, bad_status):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    ev_bad = dict(ctx["ev"])
    ev_bad["termination_exit_status"] = bad_status
    fe_mod.write_force_evidence(ctx["ev_path"], ev_bad)
    reg_mod.update_registry(
        ctx["lid"], {"force_termination_exit_status": bad_status}, root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="termination_exit_status"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_missing_termination_status_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    ev_bad = dict(ctx["ev"])
    del ev_bad["termination_exit_status"]  # 手工删字段（绕过 build 的必填）
    (ctx["ev_path"]).write_text(json.dumps(ev_bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(fc_mod.ForceEvidenceError, match="termination_exit_status|缺少必需字段"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


# ---------------------------------------------------------------------------
# 反向 3：registry durable force 字段与 evidence 逐项不一致（req 6/7）
# ---------------------------------------------------------------------------


def test_negative_registry_requested_at_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"], {"force_terminate_requested_at": _old_iso(seconds=3600)}, root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="force_terminate_requested_at"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_observed_at_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"], {"force_termination_observed_at": _iso(datetime.now() + timedelta(days=1))},
        root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="force_termination_observed_at"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_exit_status_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(ctx["lid"], {"force_termination_exit_status": 1}, root=ctx["reg_dir"])
    with pytest.raises(fc_mod.ForceEvidenceError, match="force_termination_exit_status"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_evidence_path_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"], {"force_evidence_path": str(tmp_path / "elsewhere.json")}, root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="force_evidence_path"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_verification_result_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"], {"force_termination_verification_result": "UNCERTAIN"}, root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="verification_result"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_verification_checks_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"], {"force_termination_verification_checks": {"process_exists": True}},
        root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="verification_checks"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


# ---------------------------------------------------------------------------
# 反向 4：三方 identity 任一不一致（req 3/4/7）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, new_value, match",
    [
        ("workspace", "D:/nowhere/other-ws", "workspace"),
        ("output_dir", "D:/nowhere/other-ws/.aaf/OTHER", "output_dir"),
        ("runner_pid", 999999, "runner_pid"),
        ("runner_creation_time", "2020-01-01T00:00:00.000", "runner_creation_time"),
        ("expected_runner_entry", "other.py", "expected_runner_entry"),
    ],
)
def test_negative_registry_identity_mismatch_rejected(tmp_path, field, new_value, match):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(ctx["lid"], {field: new_value}, root=ctx["reg_dir"])
    with pytest.raises(fc_mod.ForceEvidenceError, match=match):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_command_line_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(
        ctx["lid"], {"expected_command_line": [sys.executable, "run.py", "OTHER.md"]},
        root=ctx["reg_dir"],
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="expected_command_line"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


@pytest.mark.parametrize(
    "field, new_value, match",
    [
        ("workspace", "D:/nowhere/other-ws", "workspace"),
        ("runner_creation_time", "2020-01-01T00:00:00.000", "runner_creation_time"),
    ],
)
def test_negative_control_identity_mismatch_rejected(tmp_path, field, new_value, match):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    control_mod.update_control(ctx["out"], {field: new_value}, task_id=TID)
    with pytest.raises(fc_mod.ForceEvidenceError, match=match):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_control_command_line_mismatch_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    control_mod.update_control(
        ctx["out"], {"expected_command_line": [sys.executable, "run.py", "OTHER.md"]}, task_id=TID,
    )
    with pytest.raises(fc_mod.ForceEvidenceError, match="expected_command_line"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_workspace_arg_mismatch_rejected(tmp_path):
    """CLI/library 传入的 workspace 与 authority 记录不一致 → 拒绝。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    with pytest.raises(fc_mod.ForceEvidenceError, match="workspace"):
        fc_mod.finalize_cancelled_task(
            TID, tmp_path / "wrong-ws", ctx["out"], cancel_mode="force",
            force_evidence=ctx["ev_path"],
        )
    _assert_no_terminal(ctx["out"])


# ---------------------------------------------------------------------------
# 反向 5：registry state（req 4/7）
# ---------------------------------------------------------------------------


def test_negative_registry_prepared_state_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.update_registry(ctx["lid"], {"state": reg_mod.REGISTRY_STATE_PREPARED}, root=ctx["reg_dir"])
    with pytest.raises(fc_mod.ForceEvidenceError, match="PREPARED"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


def test_negative_registry_superseded_state_rejected(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    reg_mod.mark_superseded(ctx["lid"], "0" * 32, root=ctx["reg_dir"])
    with pytest.raises(fc_mod.ForceEvidenceError, match="SUPERSEDED"):
        _finalize(ctx)
    _assert_no_terminal(ctx["out"])


# ---------------------------------------------------------------------------
# 反向 6：已有终态 precedence 不受 force authority 影响（req 8）
# ---------------------------------------------------------------------------


def test_terminal_precedence_preserved_even_with_valid_evidence(tmp_path):
    """已有终态 + 全一致 force evidence → arbitration 优先 preserve（req 8/22）。"""
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    from ai_agent_framework.task_lifecycle import finalize_terminal

    finalize_terminal(
        ctx["out"], task_id=TID, status="FAILED", task_path=str(tmp_path / "T.md"),
        workspace=str(ctx["ws"]), report_path=str(ctx["out"] / "REPORT.md"),
    )
    canonical = _finalize(ctx)
    assert canonical.status == "FAILED" and canonical.preserved is True
    assert read_status(ctx["out"])["status"] == "FAILED"


# ---------------------------------------------------------------------------
# CLI 级（真实子进程；FIX-001 与 library 同一规则）
# ---------------------------------------------------------------------------


def _run_finalizer_cli(ctx: dict, ev_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["AAF_BRIDGE_DIR"] = str(ctx["reg_dir"].parent)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run(
        [sys.executable, "-m", "ai_agent_framework.finalize_cancelled",
         "--task-id", TID, "--workspace", str(ctx["ws"]), "--output", str(ctx["out"]),
         "--reason", "FORCE_CANCELLED", "--cancel-mode", "force",
         "--force-evidence", str(ev_path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=90, env=env,
    )


def test_cli_positive_canonical_evidence_commits_cancelled(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    proc = _run_finalizer_cli(ctx, ctx["ev_path"])
    assert proc.returncode == 0, f"CLI 应成功: {proc.stdout}\n{proc.stderr}"
    assert '"status": "CANCELLED"' in proc.stdout
    assert read_status(ctx["out"])["status"] == "CANCELLED"


def test_cli_negative_nonzero_status_fails_closed(tmp_path):
    ctx = _make_ctx(tmp_path, tmp_path / "aaf-bridge" / "launches")
    ev_bad = dict(ctx["ev"])
    ev_bad["termination_exit_status"] = 1
    fe_mod.write_force_evidence(ctx["ev_path"], ev_bad)
    reg_mod.update_registry(ctx["lid"], {"force_termination_exit_status": 1}, root=ctx["reg_dir"])
    proc = _run_finalizer_cli(ctx, ctx["ev_path"])
    assert proc.returncode == fc_mod.EXIT_RECOVERY_ERROR, f"CLI 应安全失败: {proc.stdout}\n{proc.stderr}"
    assert "FORCE_EVIDENCE_ERROR" in proc.stderr
    _assert_no_terminal(ctx["out"])
