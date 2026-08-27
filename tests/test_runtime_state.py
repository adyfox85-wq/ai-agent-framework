"""AI Agent Framework — v0.4 Phase A Runtime State Foundation 测试。"""
import json
from pathlib import Path
import pytest

from ai_agent_framework import task_lifecycle as tl
from ai_agent_framework.runtime_state import read_runtime_state


def _write(out: Path, data: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / "task.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _upd(out: Path, status: str, **kw):
    return tl.update_status(
        out,
        task_id=kw.pop("task_id", "T1"),
        status=status,
        task_path=kw.pop("task_path", "T1.md"),
        workspace=kw.pop("workspace", "D:/ws"),
        **kw,
    )


def test_update_status_writes_runtime_fields(tmp_path):
    _upd(tmp_path, "RUNNING", stage="HERMES", agent="hermes")
    data = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert data["stage"] == "HERMES"
    assert data["agent"] == "hermes"
    assert data["started_at"]  # 首次 RUNNING
    assert data["last_activity_at"]
    assert data["stage_started_at"]
    assert data["phases"]["HERMES"]["state"] == "RUNNING"
    assert data["phases"]["HERMES"]["started_at"]


def test_started_at_set_only_on_first_running(tmp_path):
    _upd(tmp_path, "CREATED")
    first = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert first.get("started_at") is None

    _upd(tmp_path, "RUNNING")
    second = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert second["started_at"]

    _upd(tmp_path, "RUNNING", stage="HERMES", agent="hermes")
    third = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert third["started_at"] == second["started_at"]  # 不重写


def test_stage_started_at_updates_on_stage_change(tmp_path):
    _upd(tmp_path, "RUNNING", stage="HERMES", agent="hermes")
    a = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    _upd(tmp_path, "RUNNING", stage="WORKBUDDY", agent="workbuddy")
    b = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert b["stage"] == "WORKBUDDY"
    assert b["stage_started_at"] >= a["stage_started_at"]
    assert b["phases"]["HERMES"]["state"] == "RUNNING"  # 历史保留
    assert b["phases"]["WORKBUDDY"]["state"] == "RUNNING"


def test_phase_state_transition(tmp_path):
    _upd(tmp_path, "RUNNING", stage="HERMES", agent="hermes")
    _upd(tmp_path, "RUNNING", stage="HERMES", agent="hermes", phase_state="SUCCESS")
    data = json.loads((tmp_path / "task.json").read_text(encoding="utf-8"))
    assert data["phases"]["HERMES"]["state"] == "SUCCESS"
    assert data["phases"]["HERMES"]["started_at"]  # started_at 保持首次


def test_invalid_stage_and_phase_state_rejected(tmp_path):
    with pytest.raises(tl.LifecycleError):
        _upd(tmp_path, "RUNNING", stage="NOT_A_STAGE")
    with pytest.raises(tl.LifecycleError):
        _upd(tmp_path, "RUNNING", stage="HERMES", phase_state="BOGUS")


def test_reader_returns_none_when_missing(tmp_path):
    assert read_runtime_state(tmp_path) is None


def test_reader_legacy_compat(tmp_path):
    # 老 task.json：无 runtime 字段 → 不崩溃
    _write(tmp_path, {"task_id": "OLD", "status": "SUCCESS", "updated_at": "2026-08-01T00:00:00"})
    rs = read_runtime_state(tmp_path)
    assert rs is not None
    assert rs.task_id == "OLD"
    assert rs.status == "SUCCESS"
    assert rs.stage is None
    assert rs.phases == {}
    assert rs.elapsed_seconds() is None  # 无 started_at → None


def test_reader_accessors(tmp_path):
    _upd(tmp_path, "RUNNING", stage="CODEX", agent="codex")
    rs = read_runtime_state(tmp_path)
    assert rs.current_stage() == "CODEX"
    assert rs.current_agent() == "codex"
    assert rs.phase_state("CODEX") == "RUNNING"
    assert rs.phase_state("HERMES") is None
    assert rs.elapsed_seconds() is not None
    assert rs.stage_elapsed_seconds() is not None
    d = rs.as_dict()
    assert d["stage"] == "CODEX" and d["phases"]["CODEX"]["state"] == "RUNNING"


def test_reader_corrupt_json_raises(tmp_path):
    out = tmp_path / "task.json"
    out.write_text("{bad json", encoding="utf-8")
    with pytest.raises(tl.LifecycleError):
        read_runtime_state(tmp_path)


def test_runner_integration_writes_stage_phases(tmp_path, monkeypatch):
    """执行链后 task.json 含 stage=COMPLETED + phases 记录（fake agents）。"""
    import subprocess
    from ai_agent_framework.runner import run

    task_file = tmp_path / "T.md"
    task_file.write_text(
        "AAF_TASK_BEGIN\n# Task ID\nT-1\n# Task Name\ntest\n"
        f"# Workspace\n{tmp_path}\n# Objective\n实现 X\n# Acceptance\n1. ok\nAAF_TASK_END",
        encoding="utf-8",
    )
    ws = tmp_path / "ws"
    out = tmp_path / "out"

    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env):
        class P:
            returncode = 0
            stdout = "PASS fake"
            stderr = ""
        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = run(task_file, ws, out)
    assert report.exists()
    data = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "SUCCESS"
    assert data["stage"] == "COMPLETED"
    assert data["phases"]["HERMES"]["state"] == "SUCCESS"
    assert data["phases"]["WORKBUDDY"]["state"] == "SUCCESS"
    assert data["phases"]["REPORT"]["state"] == "SUCCESS"
    assert data["started_at"]
    assert data["last_activity_at"]
