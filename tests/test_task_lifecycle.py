"""AI Agent Framework — Task Lifecycle 测试（模块单测 + runner 集成）。"""
import json
from pathlib import Path
import pytest

from ai_agent_framework import task_lifecycle
from ai_agent_framework.task_lifecycle import (
    LifecycleError,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    finalize_terminal,
    read_canonical_terminal,
    read_status,
    task_json_path,
    update_status,
)
from ai_agent_framework import runner as runner_mod
from ai_agent_framework.task_validation import TaskValidationError

VALID_TASK = """# Task ID
AAF-V03-002-LC

# Task Name
lifecycle test

# Objective
测试 lifecycle

# Acceptance
1. 通过
"""


# ---------- 模块单测 ----------

def test_valid_statuses():
    assert VALID_STATUSES == ("CREATED", "RUNNING", "WAITING", "SUCCESS", "FAILED", "CANCELLED")
    assert "ARCHIVED" not in VALID_STATUSES  # ARCHIVED 不属于 Task Status
    # Phase E（§6A.1）：CANCELLED 是合法终态；CANCEL_REQUESTED / CANCELLING 不是 task.json status
    assert TERMINAL_STATUSES == ("SUCCESS", "WAITING", "FAILED", "CANCELLED")
    assert "CANCELLED" in VALID_STATUSES
    assert "CANCEL_REQUESTED" not in VALID_STATUSES
    assert "CANCELLING" not in VALID_STATUSES


@pytest.mark.parametrize("status", ["CREATED", "RUNNING"])
def test_write_and_read_non_terminal(tmp_path, status):
    p = update_status(
        tmp_path / "out", task_id="T1", status=status,
        task_path="T.md", workspace=str(tmp_path),
    )
    assert p == tmp_path / "out" / "task.json"
    data = read_status(tmp_path / "out")
    assert data["task_id"] == "T1"
    assert data["status"] == status
    assert data["updated_at"]
    assert data["report_path"] is None


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_write_and_read_terminal_via_finalize(tmp_path, status):
    """终态必须经 finalize_terminal（锁内提交）；update_status 拒绝终态。"""
    out = tmp_path / "out"
    update_status(out, task_id="T1", status="RUNNING", task_path="T.md", workspace=str(tmp_path))
    result = finalize_terminal(
        out, task_id="T1", status=status, task_path="T.md", workspace=str(tmp_path)
    )
    data = read_status(out)
    assert data["task_id"] == "T1"
    assert data["status"] == status
    assert data["updated_at"]
    assert result.status == status
    assert result.preserved is False
    # terminal generation 持久化（§6B.4）
    assert result.terminal_generation == 1
    assert data["terminal_generation"] == 1
    assert data["terminal_at"]
    assert read_canonical_terminal(out).status == status


def test_update_status_rejects_terminal_status(tmp_path):
    """绕过锁直接 update_status 写终态必须被拒绝（§6B.1/§6B.2 不绕过锁）。"""
    with pytest.raises(LifecycleError, match="finalize_terminal"):
        update_status(tmp_path / "out", task_id="T1", status="SUCCESS",
                      task_path="T.md", workspace=str(tmp_path))
    with pytest.raises(LifecycleError, match="finalize_terminal"):
        update_status(tmp_path / "out", task_id="T1", status="CANCELLED",
                      task_path="T.md", workspace=str(tmp_path))


def test_invalid_status_rejected(tmp_path):
    with pytest.raises(LifecycleError):
        update_status(tmp_path / "out", task_id="T1", status="ARCHIVED",
                      task_path="T.md", workspace=str(tmp_path))


def test_report_path_updated_after_generation(tmp_path):
    out = tmp_path / "out"
    update_status(out, task_id="T1", status="RUNNING", task_path="T.md", workspace=str(tmp_path))
    finalize_terminal(out, task_id="T1", status="SUCCESS", task_path="T.md", workspace=str(tmp_path),
                      report_path=str(tmp_path / "REPORT.md"))
    data = read_status(out)
    assert data["report_path"] == str(tmp_path / "REPORT.md")
    assert data["status"] == "SUCCESS"


def test_report_path_preserved_when_none(tmp_path):
    """新写入 report_path=None 时保留旧值。"""
    out = tmp_path / "out"
    update_status(out, task_id="T1", status="RUNNING", task_path="T.md", workspace=str(tmp_path),
                  report_path="R.md")
    finalize_terminal(out, task_id="T1", status="SUCCESS", task_path="T.md", workspace=str(tmp_path))
    assert read_status(out)["report_path"] == "R.md"


def test_atomic_write_no_tmp_left(tmp_path):
    out = tmp_path / "out"
    update_status(out, task_id="T1", status="RUNNING", task_path="T.md", workspace=str(tmp_path))
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_corrupted_json_raises_on_read(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "task.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(LifecycleError):
        read_status(out)


def test_corrupted_json_rebuilt_on_update(tmp_path):
    """已损坏 task.json：update 重建（不静默吞掉读失败——read 已抛错；此处验证可恢复）。"""
    out = tmp_path / "out"
    out.mkdir()
    (out / "task.json").write_text("{broken", encoding="utf-8")
    update_status(out, task_id="T2", status="RUNNING", task_path="T.md", workspace=str(tmp_path))
    data = read_status(out)
    assert data["task_id"] == "T2"
    assert data["status"] == "RUNNING"


def test_corrupted_json_terminal_rebuilt_via_finalize(tmp_path):
    """已损坏 task.json：finalize_terminal 锁内重建终态（兼容 update_status 的可恢复语义）。"""
    out = tmp_path / "out"
    out.mkdir()
    (out / "task.json").write_text("{broken", encoding="utf-8")
    finalize_terminal(out, task_id="T2", status="FAILED", task_path="T.md", workspace=str(tmp_path))
    data = read_status(out)
    assert data["task_id"] == "T2"
    assert data["status"] == "FAILED"
    assert data["terminal_generation"] == 1


def test_read_missing_returns_none(tmp_path):
    assert read_status(tmp_path / "nope") is None
    assert read_canonical_terminal(tmp_path / "nope") is None


# ---------- runner 集成 ----------

def _run_valid(tmp_path, monkeypatch, agents=None, results=None):
    """跑一次 runner.run（mock run_agent）；返回 (report_path, task.json data)。"""
    monkeypatch.setattr(runner_mod, "decide_route", lambda task: runner_mod.Route(agents or ["hermes"], "test"))
    monkeypatch.setattr(runner_mod, "run_agent", lambda agent, prompt, workspace: (results or {}).get(agent, "implemented ok"))
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    out = tmp_path / "out"
    ws = tmp_path / "ws"
    report_path = runner_mod.run(task_file, ws, out)
    return report_path, json.loads((out / "task.json").read_text(encoding="utf-8"))


def test_dry_run_created_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "decide_route", lambda task: runner_mod.Route(["hermes"], "test"))
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    out = tmp_path / "out"
    runner_mod.run(task_file, tmp_path / "ws", out, dry_run=True)
    data = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "CREATED"          # dry-run 不伪装 SUCCESS
    assert data["reason"] == "DRY_RUN"
    assert data["report_path"]                   # REPORT 已生成 → 回填


def test_success_status(tmp_path, monkeypatch):
    _, data = _run_valid(tmp_path, monkeypatch, agents=["hermes"], results={"hermes": "implemented ok"})
    assert data["status"] == "SUCCESS"
    assert data["report_path"]


def test_waiting_status(tmp_path, monkeypatch):
    _, data = _run_valid(tmp_path, monkeypatch, agents=["hermes", "workbuddy"],
                         results={"hermes": "ok", "workbuddy": "FAIL: broken"})
    assert data["status"] == "WAITING"


def test_framework_failure_failed(tmp_path, monkeypatch):
    """Framework 级异常（decide_route 抛错）→ task.json FAILED + 异常重新抛出。"""
    def boom(task):
        raise RuntimeError("route boom")
    monkeypatch.setattr(runner_mod, "decide_route", boom)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="route boom"):
        runner_mod.run(task_file, tmp_path / "ws", out)
    data = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "FAILED"
    assert "FRAMEWORK_ERROR" in data["reason"]


def test_invalid_task_does_not_enter_lifecycle(tmp_path, monkeypatch):
    """Validation 失败 → 抛 TaskValidationError + 无 task.json（无虚假状态）。"""
    invalid = VALID_TASK.replace("1. 通过", "")
    task_file = tmp_path / "BAD.md"
    task_file.write_text(invalid, encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(TaskValidationError):
        runner_mod.run(task_file, tmp_path / "ws", out)
    assert not task_json_path(out).exists()


def test_resume_waiting_to_running_to_success(tmp_path, monkeypatch):
    """WAITING 完成 → resume → RUNNING → 复用结果 → SUCCESS。"""
    # 第一轮：workbuddy FAIL → WAITING
    _, data = _run_valid(tmp_path, monkeypatch, agents=["hermes", "workbuddy"],
                         results={"hermes": "ok", "workbuddy": "FAIL: broken"})
    assert data["status"] == "WAITING"

    # resume：workbuddy 修正后通过；已完成的 hermes 结果复用（不重复调用）
    calls = []

    def fake_agent(agent, prompt, workspace):
        calls.append(agent)
        return "ok" if agent == "workbuddy" else "implemented ok"

    monkeypatch.setattr(runner_mod, "run_agent", fake_agent)
    monkeypatch.setattr(runner_mod, "_load_resume_state",
                        lambda resume_from: (runner_mod.Route(["hermes", "workbuddy"], "test"),
                                             {"hermes": "implemented ok"}))
    task_file = tmp_path / "TASK.md"
    out = tmp_path / "out"
    ws = tmp_path / "ws"
    runner_mod.run(task_file, ws, out, resume_from=out)
    final = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert final["status"] == "SUCCESS"
    assert calls == ["workbuddy"]  # hermes 结果复用，未重复执行
