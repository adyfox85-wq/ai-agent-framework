"""Phase E（TASK-005-A）真实最小 soft-cancel E2E（req 30）。

Scenario 1：启动真实 Framework task → 在 Hermes 前写 cancel.request → Hermes 未启动
           → CANCELLED terminal → run.json CANCELLED → REPORT CANCELLED
Scenario 2：让 Hermes 完成 → WorkBuddy 前发 cancel → Hermes result 保留
           → WorkBuddy 未启动 → CANCELLED
Scenario 3：真实 CLI 级 E2E —— `python run.py` 子进程（cancel.request 预写）→ CANCELLED；
           `python -m ai_agent_framework.finalize_cancelled` CLI 幂等收敛 + reconciliation

约束（req 30）：真实 Agent timing 太短 → 使用 deterministic adapter / fixture
（mock run_agent），但必须仍经过真实 runner / filesystem / lifecycle——本文件全部
通过真实 runner.run() / run.py 子进程 + 真实 task.json / run.json / REPORT.md /
state.lock / cancel.request 验证，不只测纯函数。本文件不测 taskkill（Do Not Do）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import runner as runner_mod
from ai_agent_framework.task_lifecycle import read_status

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_TASK = """# Task ID
T-E-E2E

# Task Name
Phase E E2E 软取消

# Objective
验证真实 runner 软取消

# Acceptance
1. 通过
"""


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    return task_file


def test_e2e_scenario1_cancel_before_hermes(tmp_path, monkeypatch):
    """Scenario 1：Hermes 前 cancel → Hermes 不启动 → CANCELLED 全套产物。"""
    record = {"calls": []}

    def fake(agent, prompt, workspace):
        record["calls"].append(agent)
        return "ok"  # 不应被调用

    monkeypatch.setattr(runner_mod, "run_agent", fake)
    monkeypatch.setattr(runner_mod, "decide_route",
                        lambda task: runner_mod.Route(["hermes", "workbuddy", "codex"], "test"))

    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    out = ws / ".aaf" / "T-E-E2E"
    cancel_mod.write_cancel_request(out, "T-E-E2E")  # Hermes 启动前写 cancel.request

    report_path = runner_mod.run(task_file, ws, out)

    assert record["calls"] == []  # Hermes 未启动
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert run["terminal_generation"] == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "任务已取消" in report
    assert (out / "cancel.request").exists()  # 请求保留为证据（§6.6）


def test_e2e_scenario2_cancel_between_hermes_and_workbuddy(tmp_path, monkeypatch):
    """Scenario 2：Hermes 完成（真实时序窗口内写入 cancel）→ WorkBuddy 不启动；
    Hermes result 保留 → CANCELLED。"""
    record = {"calls": []}

    def fake(agent, prompt, workspace):
        record["calls"].append(agent)
        if agent == "hermes":
            time.sleep(0.4)  # 给主线程写 cancel.request 的时间窗
        return {"hermes": "implemented ok", "workbuddy": "PASS", "codex": "APPROVE"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake)
    monkeypatch.setattr(runner_mod, "decide_route",
                        lambda task: runner_mod.Route(["hermes", "workbuddy", "codex"], "test"))

    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    out = ws / ".aaf" / "T-E-E2E"

    # Hermes 执行期间（真实时序）写入 cancel.request
    timer = threading.Timer(0.1, cancel_mod.write_cancel_request, args=(out, "T-E-E2E"))
    timer.start()
    try:
        report_path = runner_mod.run(task_file, ws, out)
    finally:
        timer.join(timeout=2)

    assert record["calls"] == ["hermes"]  # WorkBuddy 未启动
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    # Hermes 已完成 artifact 保留（req 14）
    assert (out / "hermes_prompt.md").exists()
    assert (out / "hermes_result.md").exists()
    assert "implemented ok" in (out / "hermes_result.md").read_text(encoding="utf-8")
    # 未启动 agent 无 prompt
    assert not (out / "workbuddy_prompt.md").exists()
    assert not (out / "codex_prompt.md").exists()
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "implemented ok" in report  # 已完成 hermes 结果反映在 REPORT（agent 名小写）


def test_e2e_scenario3_real_cli_run_py_cancel_before_agents(tmp_path):
    """Scenario 3（CLI 级）：真实 `python run.py` 子进程 + 预写 cancel.request →
    Hermes 不启动、exit 0、CANCELLED 全套产物（真实 runner / filesystem / lifecycle）。

    注意：TASK.md 的 Task ID 必须与 cancel.request 的 task_id 一致
    （不一致会被 runner 正确忽略——见 test_w_mismatched_task_id_cancel_request_ignored）。
    """
    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    out = ws / ".aaf" / "T-E-E2E"
    cancel_mod.write_cancel_request(out, "T-E-E2E")  # 与 TASK.md Task ID 一致

    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "run.py"), str(task_file),
         "--workspace", str(ws), "--output", str(out)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out_text, _ = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_text, _ = proc.communicate(timeout=10)
        data_now = read_status(out)
        raise AssertionError(
            f"run.py 子进程超时（cancel 未生效）\nSTDOUT:\n{out_text}\n"
            f"task.json status={data_now.get('status') if data_now else None}\n"
            f"OUT DIR: {sorted(p.name for p in out.iterdir()) if out.exists() else 'MISSING'}"
        )
    assert proc.returncode == 0, f"run.py 退出码异常: {out_text}"
    data = read_status(out)
    assert data["status"] == "CANCELLED", (
        f"CLI cancel 未生效（status={data['status']}）\n"
        f"STDOUT:\n{out_text}\n"
        f"OUT DIR: {sorted(p.name for p in out.iterdir()) if out.exists() else 'MISSING'}"
    )
    assert data["terminal_generation"] == 1
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert not (out / "hermes_prompt.md").exists()  # Hermes 未启动


def test_e2e_scenario3_real_cli_finalize_cancelled_idempotent(tmp_path):
    """Scenario 3（CLI 级）：`python -m ai_agent_framework.finalize_cancelled` CLI
    幂等收敛（两次调用 → 相同 canonical；run.json / REPORT 跟随 CANCELLED）。"""
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    out = ws / ".aaf" / "T-E-CLI"
    out.mkdir(parents=True, exist_ok=True)
    (out / "TASK.md").write_text(VALID_TASK, encoding="utf-8")
    cancel_mod.write_cancel_request(out, "T-E-CLI", requested_at="2026-08-27T12:00:00")

    def run_cli() -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "ai_agent_framework.finalize_cancelled",
             "--task-id", "T-E-CLI", "--workspace", str(ws), "--output", str(out)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        assert proc.returncode == 0, f"finalize_cancelled CLI 失败: {proc.stdout} {proc.stderr}"
        return proc.stdout

    first = json.loads(run_cli())
    assert first["status"] == "CANCELLED"
    assert first["terminal_generation"] == 1
    assert first["preserved"] is False
    second = json.loads(run_cli())
    assert second["status"] == "CANCELLED"
    assert second["terminal_generation"] == 1
    assert second["preserved"] is True  # 幂等

    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert run["terminal_generation"] == 1
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "任务已取消" in report
    assert "取消请求时间: 2026-08-27T12:00:00" in report
