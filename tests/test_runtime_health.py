"""RW-020 Runtime Health regression tests（Dead Runner / Orphaned RUNNING Detection）。

覆盖 TASK-007 Requirement 12 的 A–F 场景 + 保护性场景：
A. RUNNING + live runner + fresh activity → HEALTHY
B. RUNNING + runner missing + stale + artifact missing → SUSPICIOUS_DEAD
C. runner missing 但已有 terminal → canonical terminal wins（TERMINAL_PENDING / NOT_APPLICABLE）
D. Bridge restart + runner still alive → 不误判 dead（HEALTHY）
E. stale timestamp alone → 不足以直接判 dead（STALE / 非 SUSPICIOUS_DEAD）
F. PID reuse / ownership mismatch → fail-safe，不把 unrelated process 当 owner

另外覆盖：recovery 流程保护 / 无 ownership 记录不误报 / expected artifact 判定 /
collect_health 文件级集成 / CLI。
"""
from datetime import datetime, timedelta
from pathlib import Path

import json

import pytest

from ai_agent_framework import runtime_health as rh

NOW = datetime(2026, 8, 28, 12, 0, 0)
FRESH = (NOW - timedelta(minutes=1)).isoformat(timespec="seconds")
STALE = (NOW - timedelta(minutes=25)).isoformat(timespec="seconds")

SIGNALS_LIVE = {
    "runner_pid_recorded": True,
    "runner_process_alive": True,
    "runner_identity_ok": True,
    "last_activity_stale": False,
    "expected_artifact_missing": False,
    "recovery_in_progress": False,
    "terminal_pending": False,
}


def sig(**overrides) -> dict:
    s = dict(SIGNALS_LIVE)
    s.update(overrides)
    return s


# --- A: RUNNING + live runner + fresh activity → HEALTHY ---

def test_a_live_runner_fresh_activity_healthy():
    h = rh.assess_health("RUNNING", sig())
    assert h.health == rh.HEALTH_HEALTHY
    assert h.warning == ""


def test_a_live_runner_stale_activity_still_healthy():
    # runner 正常运行但长时间无 stdout → 不判死（Req 4 假阳性保护）
    h = rh.assess_health("RUNNING", sig(last_activity_stale=True))
    assert h.health == rh.HEALTH_HEALTHY
    assert h.warning == ""
    assert any("不判死" in d for d in h.diagnostics)


# --- B: RUNNING + runner missing + stale + artifact missing → SUSPICIOUS_DEAD ---

def test_b_runner_missing_stale_artifact_missing_suspicious_dead():
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=False, last_activity_stale=True, expected_artifact_missing=True,
    ))
    assert h.health == rh.HEALTH_SUSPICIOUS_DEAD
    assert rh.WARNING_SUSPICIOUS_DEAD in h.warning
    assert "任务可能已异常中断" in h.warning


def test_b_identity_mismatch_stale_artifact_missing_suspicious_dead():
    # PID reuse 场景：进程存活但身份不匹配 → 视为 runner 缺失 → 组合判死
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=True, runner_identity_ok=False,
        last_activity_stale=True, expected_artifact_missing=True,
    ))
    assert h.health == rh.HEALTH_SUSPICIOUS_DEAD


# --- C: runner missing 但已有 terminal → canonical wins ---

def test_c_terminal_pending_canonical_wins():
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=False, last_activity_stale=True,
        expected_artifact_missing=True, terminal_pending=True,
    ))
    assert h.health == rh.HEALTH_TERMINAL_PENDING
    assert h.warning == ""  # canonical wins——不得报 dead


def test_c_terminal_task_not_applicable():
    for status in ("SUCCESS", "WAITING", "FAILED", "CANCELLED"):
        h = rh.assess_health(status, sig())
        assert h.health == rh.HEALTH_NOT_APPLICABLE
        assert h.warning == ""


# --- D: Bridge restart + runner still alive → 不误判 dead ---

def test_d_bridge_restart_runner_alive_healthy():
    # registry/control 持久，live 进程 identity 验证通过（创建时间 + 命令行一致）
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=True, runner_identity_ok=True,
        last_activity_stale=True,  # Bridge 重启期间可能无活动——仍不判死
    ))
    assert h.health == rh.HEALTH_HEALTHY
    assert h.warning == ""


def test_d_alive_but_identity_unverifiable_not_dead():
    # 进程存活但缺身份记录 → 不判死（ALIVE_UNVERIFIED）
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=True, runner_identity_ok=None,
        last_activity_stale=True, expected_artifact_missing=True,
    ))
    assert h.health != rh.HEALTH_SUSPICIOUS_DEAD
    assert h.warning == ""


# --- E: stale alone → 不足以直接判 dead ---

def test_e_stale_alone_not_dead():
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=False, last_activity_stale=True, expected_artifact_missing=False,
    ))
    assert h.health == rh.HEALTH_PROCESS_MISSING  # 进程缺失事实警告
    assert h.health != rh.HEALTH_SUSPICIOUS_DEAD
    assert "任务可能已异常中断" not in h.warning


def test_e_stale_alone_no_ownership_not_dead():
    # 无 ownership 记录 + 仅 stale → STALE 警告，不判死
    h = rh.assess_health("RUNNING", sig(
        runner_pid_recorded=False, runner_process_alive=None,
        last_activity_stale=True, expected_artifact_missing=False,
    ))
    assert h.health == rh.HEALTH_STALE
    assert rh.WARNING_STALE in h.warning
    assert "任务可能已异常中断" not in h.warning


def test_e_stale_alone_live_runner_healthy():
    h = rh.assess_health("RUNNING", sig(last_activity_stale=True))
    assert h.health == rh.HEALTH_HEALTHY


# --- F: PID reuse / ownership mismatch → fail-safe ---

def test_f_pid_reuse_identity_mismatch_not_owner():
    # 存活但创建时间不匹配 → 不把 unrelated process 当 owner → 视为 runner 缺失
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=True, runner_identity_ok=False,
        last_activity_stale=False, expected_artifact_missing=False,
    ))
    assert h.health == rh.HEALTH_PROCESS_MISSING
    assert h.health != rh.HEALTH_HEALTHY  # 绝不因“进程活着”而误判 HEALTHY


def test_f_identity_mismatch_stale_only_not_dead():
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=True, runner_identity_ok=False,
        last_activity_stale=True, expected_artifact_missing=False,
    ))
    assert h.health == rh.HEALTH_PROCESS_MISSING
    assert "任务可能已异常中断" not in h.warning


def test_f_no_ownership_record_orphan_not_dead():
    # legacy orphan（无 control/registry 记录）→ 无法证明 dead → 不报“异常中断”
    h = rh.assess_health("RUNNING", sig(
        runner_pid_recorded=False, runner_process_alive=None,
        last_activity_stale=True, expected_artifact_missing=True,
    ))
    assert h.health == rh.HEALTH_AGENT_MISSING
    assert "任务可能已异常中断" not in h.warning
    assert "无法证明" in " ".join(h.diagnostics)


# --- 保护场景：recovery / force-cancel ---

def test_recovery_in_progress_no_warning():
    h = rh.assess_health("RUNNING", sig(
        runner_process_alive=False, last_activity_stale=True,
        expected_artifact_missing=True, recovery_in_progress=True,
    ))
    assert h.health == rh.HEALTH_RECOVERING
    assert h.warning == ""


def test_unknown_runtime_status_not_applicable():
    h = rh.assess_health(None, sig())
    assert h.health == rh.HEALTH_NOT_APPLICABLE


# --- expected_stage_artifact_missing ---

def test_artifact_missing_agent_prompt_without_result(tmp_path):
    (tmp_path / "workbuddy_prompt.md").write_text("p", encoding="utf-8")
    assert rh.expected_stage_artifact_missing("WORKBUDDY", "workbuddy", tmp_path) is True


def test_artifact_not_missing_agent_not_invoked(tmp_path):
    assert rh.expected_stage_artifact_missing("WORKBUDDY", "workbuddy", tmp_path) is False


def test_artifact_present_result(tmp_path):
    (tmp_path / "workbuddy_result.md").write_text("r", encoding="utf-8")
    assert rh.expected_stage_artifact_missing("WORKBUDDY", "workbuddy", tmp_path) is False


def test_artifact_report_stage(tmp_path):
    (tmp_path / "route.json").write_text(json.dumps({"agents": ["hermes", "workbuddy"]}), encoding="utf-8")
    for a in ("hermes", "workbuddy"):
        (tmp_path / f"{a}_result.md").write_text("r", encoding="utf-8")
    assert rh.expected_stage_artifact_missing("REPORT", None, tmp_path) is True
    (tmp_path / "REPORT.md").write_text("# REPORT", encoding="utf-8")
    assert rh.expected_stage_artifact_missing("REPORT", None, tmp_path) is False


def test_artifact_unknown_stage(tmp_path):
    assert rh.expected_stage_artifact_missing("VALIDATION", None, tmp_path) is None
    assert rh.expected_stage_artifact_missing(None, None, tmp_path) is None


def test_last_activity_stale_helpers():
    assert rh.last_activity_stale(STALE, NOW) is True
    assert rh.last_activity_stale(FRESH, NOW) is False
    assert rh.last_activity_stale(None, NOW) is None
    assert rh.last_activity_stale("garbage", NOW) is None
    assert rh.last_activity_age_seconds(STALE, NOW) == 25 * 60


# --- collect_health 文件级集成 ---

def _make_task_running(out: Path, last_activity: str | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    (out / "task.json").write_text(json.dumps({
        "task_id": "T-RH", "status": "RUNNING", "stage": "WORKBUDDY", "agent": "workbuddy",
        "started_at": (now - timedelta(minutes=30)).isoformat(timespec="seconds"),
        "last_activity_at": last_activity or (now - timedelta(minutes=1)).isoformat(timespec="seconds"),
    }), encoding="utf-8")


def test_collect_health_live_runner_healthy(tmp_path):
    out = tmp_path / "out"
    _make_task_running(out)
    (out / "control.json").write_text(json.dumps({
        "schema_version": 1, "task_id": "T-RH", "workspace": str(tmp_path),
        "launch_id": "l1", "launcher_pid": 1, "launcher_instance_id": "i1",
        "started_at": NOW.isoformat(timespec="seconds"),
        "expected_runner_entry": "run.py", "expected_command_line": ["py", "run.py", "T"],
        "runner_pid": 12345, "runner_creation_time": "2026-08-28T10:00:00.000",
        "cancel_requested": False, "force_terminate_requested": False, "superseded_by": None,
    }), encoding="utf-8")
    live = {"pid": 12345, "exists": True,
            "creation_time": "2026-08-28T10:00:00.000",
            "command_line": ["py", "run.py", "T"]}
    h = rh.collect_health(out, live_identity_override=live)
    assert h.health == rh.HEALTH_HEALTHY
    assert h.warning == ""


def test_collect_health_dead_runner_suspicious(tmp_path):
    out = tmp_path / "out"
    _make_task_running(out, last_activity=STALE)
    (out / "control.json").write_text(json.dumps({
        "schema_version": 1, "task_id": "T-RH", "workspace": str(tmp_path),
        "launch_id": "l2", "launcher_pid": 1, "launcher_instance_id": "i1",
        "started_at": NOW.isoformat(timespec="seconds"),
        "expected_runner_entry": "run.py", "expected_command_line": ["py", "run.py", "T"],
        "runner_pid": 99999, "runner_creation_time": "2026-08-28T10:00:00.000",
        "cancel_requested": False, "force_terminate_requested": False, "superseded_by": None,
    }), encoding="utf-8")
    (out / "workbuddy_prompt.md").write_text("p", encoding="utf-8")  # agent 已调用未产出
    live = {"pid": 99999, "exists": False, "creation_time": None, "command_line": None}
    h = rh.collect_health(out, live_identity_override=live)
    assert h.health == rh.HEALTH_SUSPICIOUS_DEAD
    assert "任务可能已异常中断" in h.warning
    assert h.resume_hint == ""  # 无 workspace 快照 → 无恢复提示


def test_collect_health_terminal_pending_canonical_wins(tmp_path):
    out = tmp_path / "out"
    _make_task_running(out, last_activity=STALE)
    (out / "run.json").write_text(json.dumps({"status": "SUCCESS", "task_id": "T-RH"}),
                                  encoding="utf-8")
    h = rh.collect_health(out)
    assert h.health == rh.HEALTH_TERMINAL_PENDING
    assert h.warning == ""


def test_collect_health_force_recovery_no_warning(tmp_path):
    out = tmp_path / "out"
    _make_task_running(out, last_activity=STALE)
    (out / "control.json").write_text(json.dumps({
        "schema_version": 1, "task_id": "T-RH", "workspace": str(tmp_path),
        "launch_id": "l3", "launcher_pid": 1, "launcher_instance_id": "i1",
        "started_at": NOW.isoformat(timespec="seconds"),
        "expected_runner_entry": "run.py", "expected_command_line": [],
        "runner_pid": 88888, "runner_creation_time": "2026-08-28T10:00:00.000",
        "cancel_requested": False, "force_terminate_requested": True, "superseded_by": None,
    }), encoding="utf-8")
    live = {"pid": 88888, "exists": False, "creation_time": None, "command_line": None}
    h = rh.collect_health(out, live_identity_override=live)
    assert h.health == rh.HEALTH_RECOVERING
    assert h.warning == ""


def test_collect_health_no_task_not_applicable(tmp_path):
    h = rh.collect_health(tmp_path / "missing")
    assert h.health == rh.HEALTH_NOT_APPLICABLE


def test_collect_health_resume_hint_present(tmp_path):
    out = tmp_path / "out"
    _make_task_running(out, last_activity=STALE)
    (out / "TASK.snapshot.md").write_text("# Task ID\nT-RH\n", encoding="utf-8")
    (out / "control.json").write_text(json.dumps({
        "schema_version": 1, "task_id": "T-RH", "workspace": str(tmp_path),
        "launch_id": "l4", "launcher_pid": 1, "launcher_instance_id": "i1",
        "started_at": NOW.isoformat(timespec="seconds"),
        "expected_runner_entry": "run.py", "expected_command_line": [],
        "runner_pid": None, "runner_creation_time": None,
        "cancel_requested": False, "force_terminate_requested": False, "superseded_by": None,
    }), encoding="utf-8")
    h = rh.collect_health(out)
    assert h.health in (rh.HEALTH_STALE, rh.HEALTH_AGENT_MISSING)
    assert "--resume-from" in h.resume_hint
    assert str(out / "TASK.snapshot.md") in h.resume_hint


# --- CLI 冒烟 ---

def test_cli_json_output(tmp_path, capsys):
    out = tmp_path / "out"
    _make_task_running(out)
    rc = rh.main(["--output", str(out), "--json"])
    assert rc == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["health"] == rh.HEALTH_UNKNOWN  # 无 ownership 记录 → 无死判
    assert data["warning"] == ""


def test_cli_text_output(tmp_path, capsys):
    out = tmp_path / "out"
    _make_task_running(out)
    rc = rh.main(["--output", str(out)])
    assert rc == 0
    assert "Runtime Health:" in capsys.readouterr().out
