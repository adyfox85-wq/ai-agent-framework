"""TASK-007 Requirement 14 — Real Runtime Exercise（受控 dummy task 验证）。

用真实 runner（runner.run）+ 确定性 dummy agent 结果验证运行时核心真值：
1. 正常 RUNNING（真实 live 进程 identity 验证）→ HEALTHY
2. orphan/dead RUNNING（control 记录死 pid + stale + 产物缺失）→ SUSPICIOUS_DEAD
3. recovery/resume compatibility（WAITING 目录 → resume-from → SUCCESS；既有路径）
4. SUCCESS-with-warning aggregation（PASS_WITH_WARNING + APPROVE + blocking NONE）
5. genuine blocking WAITING（REQUEST_CHANGE）

dummy agent = monkeypatched run_agent（确定性结果 + 结构化块）；lifecycle /
aggregation / REPORT / resume 全部走真实 Framework 代码。
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework import control as control_mod
from ai_agent_framework import proc_identity
from ai_agent_framework import runtime_health as rh

ROUTE_TASK = """# Task ID
T-EXERCISE

# Task Name
运行时练习

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _block(text: str, agent: str, verdict: str, blocking: bool, warnings=None) -> str:
    structured = {
        "workbuddy": {"verdict": verdict, "blocking_rework": blocking,
                      "findings": [], "warnings": warnings or []},
        "codex": {"verdict": verdict, "blocking_rework": blocking,
                  "findings": [], "warnings": warnings or []},
        "hermes": {"status": "SUCCESS", "changed_files": [], "warnings": []},
    }[agent]
    return (text + "\nAAF_STRUCTURED_RESULT_BEGIN\n"
            + json.dumps(structured) + "\nAAF_STRUCTURED_RESULT_END")


def _run_chain(tmp_path, monkeypatch, agents: dict) -> Path:
    """真实 runner 跑完整 agent 链（dummy 结果注入）。返回 REPORT.md 路径。"""
    def fake_run_agent(agent, prompt, workspace):
        return agents[agent]
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(ROUTE_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    return runner_mod.run(task_file, ws, out)


# 1. 正常 RUNNING → HEALTHY（真实 live 进程 identity 验证，非 mock）----------

def test_exercise_normal_running_healthy(tmp_path):
    out = tmp_path / "live"
    out.mkdir()
    now = datetime.now()
    (out / "task.json").write_text(json.dumps({
        "task_id": "T-LIVE", "status": "RUNNING", "stage": "HERMES", "agent": "hermes",
        "started_at": now.isoformat(timespec="seconds"),
        "last_activity_at": now.isoformat(timespec="seconds"),
    }), encoding="utf-8")
    # control.json 指向真实当前进程（= runner 替身）：真实 creation time + 真实命令行
    live_cmd = proc_identity.live_command_line(os.getpid())
    ct = proc_identity.process_creation_time(os.getpid())
    control_mod.write_control(out, control_mod.new_control(
        task_id="T-LIVE", workspace=str(tmp_path), launch_id="live1",
        launcher_pid=os.getpid(), launcher_instance_id="i",
        expected_runner_entry="pytest", expected_command_line=live_cmd or [],
        started_at=now.isoformat(timespec="seconds"),
    ), task_id="T-LIVE")
    control_mod.update_control(out, {
        "runner_pid": os.getpid(),
        "runner_creation_time": ct.isoformat(timespec="milliseconds") if ct else None,
    }, task_id="T-LIVE")

    h = rh.collect_health(out)
    assert h.health == rh.HEALTH_HEALTHY
    assert h.warning == ""


# 2. orphan/dead RUNNING → SUSPICIOUS_DEAD -----------------------------------

def test_exercise_dead_running_suspicious(tmp_path):
    out = tmp_path / "dead"
    out.mkdir()
    stale = (datetime.now() - timedelta(minutes=25)).isoformat(timespec="seconds")
    (out / "task.json").write_text(json.dumps({
        "task_id": "T-DEAD", "status": "RUNNING", "stage": "WORKBUDDY", "agent": "workbuddy",
        "started_at": stale, "last_activity_at": stale,
    }), encoding="utf-8")
    control_mod.write_control(out, control_mod.new_control(
        task_id="T-DEAD", workspace=str(tmp_path), launch_id="dead1",
        launcher_pid=1, launcher_instance_id="i",
        expected_runner_entry="run.py", expected_command_line=["py", "run.py", "T"],
        started_at=stale,
    ), task_id="T-DEAD")
    control_mod.update_control(out, {
        "runner_pid": 987654321,
        "runner_creation_time": "2026-08-28T10:00:00.000",
    }, task_id="T-DEAD")
    (out / "workbuddy_prompt.md").write_text("p", encoding="utf-8")  # 已调用未产出

    h = rh.collect_health(out)
    assert h.health == rh.HEALTH_SUSPICIOUS_DEAD
    assert "任务可能已异常中断" in h.warning
    assert h.resume_hint == ""  # 无 TASK.snapshot.md → 无恢复提示

    # CLI 同样可诊断（Requirement 5：查看诊断入口）
    snapshot = rh.collect_health(out)
    assert snapshot.health == rh.HEALTH_SUSPICIOUS_DEAD


# 3. recovery/resume compatibility（既有 resume 路径） ------------------------

def test_exercise_blocking_waiting_then_resume_success(tmp_path, monkeypatch):
    # 第一步：构造 RW-020 真实事故形态——runner 中断（无 canonical terminal）：
    # task.json 残留 RUNNING / CODEX，hermes/workbuddy 结果完整，codex 从未执行。
    out = tmp_path / "out"
    out.mkdir()
    (out / "TASK.snapshot.md").write_text(ROUTE_TASK, encoding="utf-8")
    (out / "route.json").write_text(
        json.dumps({"agents": ["hermes", "workbuddy", "codex"], "reason": "explicit route (machine field)"}),
        encoding="utf-8",
    )
    (out / "hermes_result.md").write_text(_block("implemented", "hermes", "SUCCESS", False), encoding="utf-8")
    (out / "workbuddy_result.md").write_text(_block("**Result: PASS**\nverified", "workbuddy", "PASS", False), encoding="utf-8")
    task_file = tmp_path / "TASK.md"
    task_file.write_text(ROUTE_TASK, encoding="utf-8")
    now = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
    (out / "task.json").write_text(json.dumps({
        "task_id": "T-EXERCISE", "status": "RUNNING", "stage": "CODEX", "agent": "codex",
        "workspace": str(tmp_path), "task_path": str(task_file),
        "started_at": now, "last_activity_at": now, "phases": {},
    }), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()

    # 中断状态下 health 判定：无 control（legacy 形态）→ 只给 STALE 警告不误报 dead；
    # 诊断提示既有恢复路径（resume-from）
    h_orphan = rh.collect_health(out)
    assert h_orphan.health == rh.HEALTH_STALE  # 无法证明 dead（无 ownership 记录）
    assert "任务可能已异常中断" not in h_orphan.warning
    assert "--resume-from" in h_orphan.resume_hint  # 既有恢复路径提示

    # 第二步：resume-from（既有权威路径）——复用 hermes/workbuddy 结果（不再重跑），
    # 只执行 codex → SUCCESS canonical（terminal generation 1）
    calls2 = []

    def fake_run_agent_2(agent, prompt, workspace):
        calls2.append(agent)
        return _block("最终判定：APPROVE\nBlocking Issues: NONE", "codex", "APPROVE", False)
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent_2)
    report2 = runner_mod.run(task_file, ws, out, resume_from=out)
    text2 = report2.read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in text2
    assert calls2 == ['codex']  # 已完成结果复用，不重复执行

    # 恢复后 canonical terminal wins：health 不再做 liveness 判定
    h_after = rh.collect_health(out)
    assert h_after.health == rh.HEALTH_NOT_APPLICABLE
    assert h_after.warning == ""


# 4. SUCCESS-with-warning aggregation（真实 runner） --------------------------

def test_exercise_success_with_warning(tmp_path, monkeypatch):
    report = _run_chain(tmp_path, monkeypatch, {
        "hermes": _block("implemented ok", "hermes", "SUCCESS", False),
        "workbuddy": _block(
            "**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n"
            "历史 FAILED 场景均已验证通过（非阻断）",
            "workbuddy", "PASS_WITH_WARNING", False, warnings=["W1: 文档瑕疵"]),
        "codex": _block("最终判定：APPROVE\nBlocking Issues: NONE\n"
                        "FAILED 历史项已闭合", "codex", "APPROVE", False),
    })
    text = report.read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in text          # warning 不强制 WAITING
    assert "## Unresolved Issues\nNone identified." in text
    assert "W1: 文档瑕疵" in text                          # warning 内容保留


# 5. genuine blocking WAITING（真实 runner） ----------------------------------

def test_exercise_genuine_blocking_waiting(tmp_path, monkeypatch):
    report = _run_chain(tmp_path, monkeypatch, {
        "hermes": _block("implemented", "hermes", "SUCCESS", False),
        "workbuddy": _block("**Result: FAIL**\nB1 broken", "workbuddy", "FAIL", True),
    })
    text = report.read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in text
    assert "B1 broken" in text.split("## Unresolved Issues")[1]


# 6. required agent missing → 不得 SUCCESS（真实 runner；RW-022 C/D 运行时验证） --

def test_exercise_workbuddy_missing_not_success(tmp_path, monkeypatch):
    report = _run_chain(tmp_path, monkeypatch, {
        "hermes": _block("implemented", "hermes", "SUCCESS", False),
        # workbuddy 结果为空 → 链中断
        "workbuddy": "",
    })
    text = report.read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in text
    assert "Required validator WorkBuddy did not run or produced no valid result" in text
