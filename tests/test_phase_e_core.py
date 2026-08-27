"""Phase E（TASK-005-A）Core Cancel Foundation / Soft Cancel 测试（req 28 A–Z）。

覆盖：
- A/B CANCELLED 合法 / 可识别终态
- C/D state.lock 排他 + 残留文件不占锁
- F terminal immutable
- G generation 单调
- H–L reconciliation（missing / stale / conflict / idempotent / no-op）
- M–O runner cancel 检查点（Hermes 前 / 之间）
- P–R late cancel 不覆盖 SUCCESS / WAITING / FAILED
- S duplicate cancel 幂等
- T/U CANCELLED REPORT / run.json
- V legacy 无 generation
- W invalid / partial cancel.request 安全处理
- X/Y recovery finalizer 幂等 + 保留已有终态
- Z 无 force-kill 行为

真实并发（req 29）与真实 E2E（req 30）在 test_phase_e_concurrency.py /
test_phase_e_e2e.py。
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

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import finalize_cancelled as fc_mod
from ai_agent_framework import reconcile as rec_mod
from ai_agent_framework import runner as runner_mod
from ai_agent_framework import task_lifecycle
from ai_agent_framework.lock_utils import (
    LockTimeout,
    TaskStateLock,
    task_state_lock,
)
from ai_agent_framework.task_lifecycle import (
    TERMINAL_STATUSES,
    VALID_STATUSES,
    finalize_terminal,
    read_canonical_terminal,
    read_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

MINIMAL_TASK = """# Task ID
T-E-CORE

# Task Name
Phase E Core 测试

# Objective
验证 soft cancel core

# Acceptance
1. 通过
"""


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(MINIMAL_TASK, encoding="utf-8")
    return task_file


def _task_id() -> str:
    return "T-E-CORE"


# ---------------------------------------------------------------------------
# A / B. CANCELLED 合法终态
# ---------------------------------------------------------------------------


def test_a_cancelled_is_valid_terminal(tmp_path):
    assert "CANCELLED" in VALID_STATUSES
    assert "CANCELLED" in TERMINAL_STATUSES
    assert task_lifecycle.is_terminal_status("CANCELLED")
    assert not task_lifecycle.is_terminal_status("RUNNING")
    assert not task_lifecycle.is_terminal_status("CANCEL_REQUESTED")


def test_b_cancelled_recognized_terminal(tmp_path):
    out = tmp_path / "out"
    finalize_terminal(
        out, task_id=_task_id(), status="CANCELLED",
        task_path="T.md", workspace=str(tmp_path),
        cancel_mode="soft",
    )
    canonical = read_canonical_terminal(out)
    assert canonical is not None
    assert canonical.status == "CANCELLED"
    assert canonical.terminal_reason == "CANCEL_REQUESTED"
    assert canonical.cancel_mode == "soft"
    assert canonical.terminal_generation == 1


# ---------------------------------------------------------------------------
# C / D. state.lock 排他 + 残留文件不占锁
# ---------------------------------------------------------------------------


HOLD_WORKER = """\
import sys, time
from pathlib import Path
from ai_agent_framework.lock_utils import TaskStateLock

out, tid, hold, ready = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
with TaskStateLock(out, tid, timeout=10.0):
    Path(ready).write_text("ready", encoding="utf-8")
    time.sleep(hold)
print("RELEASED")
"""


def _spawn_worker(tmp_path: Path, worker: str, *args: str, hold: float = 2.0) -> subprocess.Popen:
    """在 tmp_path 写 worker 脚本并启动子进程（真实 OS 锁跨进程验证）。

    PYTHONPATH=REPO_ROOT：脚本位于 tmp_path（sys.path[0]=脚本目录），
    需显式注入仓库根才能 import ai_agent_framework。
    """
    script = tmp_path / f"worker_{abs(hash(worker))}.py"
    script.write_text(worker, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.Popen(
        [sys.executable, str(script), *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def test_c_state_lock_exclusive(tmp_path):
    out = tmp_path / "out"
    ready = tmp_path / "ready.txt"
    proc = _spawn_worker(tmp_path, HOLD_WORKER, str(out), _task_id(), "2.0", str(ready))
    try:
        # 等待子进程确认已持有锁（最多 20s）
        deadline = time.monotonic() + 20.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "子进程未在限时内取得锁"
        # 子进程持有锁期间：acquire 必须超时失败（明确错误，不绕过锁）
        with pytest.raises(LockTimeout):
            with task_state_lock(out, _task_id(), timeout=0.3, poll_interval=0.02):
                pytest.fail("不应取得已被持有的锁")
    finally:
        out_text = proc.communicate(timeout=20)[0] or ""
        assert proc.returncode == 0, f"worker 异常退出: {out_text}"
    # 子进程退出（OS 自动释放）后：可正常 acquire —— crash 后锁自动释放（§6B.20）
    with task_state_lock(out, _task_id(), timeout=3.0):
        pass


def test_d_stale_lock_file_does_not_mean_occupied(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "state.lock").write_text("residue", encoding="utf-8")  # 残留文件
    with task_state_lock(out, _task_id(), timeout=3.0):
        pass  # 文件残留不构成障碍（§6B.20）


def test_lock_release_is_explicit_and_reacquirable(tmp_path):
    out = tmp_path / "out"
    lock = TaskStateLock(out, _task_id(), timeout=3.0)
    lock.acquire()
    assert lock._acquired
    lock.release()
    assert not lock._acquired
    lock.acquire()  # release 后可重取
    lock.release()


# ---------------------------------------------------------------------------
# F. terminal immutable（late event 不覆盖；§6A.2）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("first,late", [
    ("SUCCESS", "CANCELLED"),
    ("WAITING", "CANCELLED"),
    ("FAILED", "CANCELLED"),
    ("CANCELLED", "SUCCESS"),
])
def test_f_terminal_immutable(tmp_path, first, late):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status=first, task_path="T.md", workspace=str(tmp_path))
    result = finalize_terminal(out, task_id=_task_id(), status=late, task_path="T.md", workspace=str(tmp_path))
    assert result.status == first
    assert result.preserved is True
    assert read_status(out)["status"] == first
    assert read_status(out)["terminal_generation"] == 1  # 未被 late commit 改写


# ---------------------------------------------------------------------------
# G. generation 单调（§6B.4）
# ---------------------------------------------------------------------------


def test_g_generation_monotonic_and_persisted(tmp_path):
    out = tmp_path / "out"
    r1 = finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md", workspace=str(tmp_path))
    assert r1.terminal_generation == 1
    assert read_status(out)["terminal_generation"] == 1
    # 已有终态 → 返回现有 canonical，不 bump
    r2 = finalize_terminal(out, task_id=_task_id(), status="CANCELLED", task_path="T.md", workspace=str(tmp_path))
    assert r2.preserved is True
    assert r2.terminal_generation == 1
    assert read_status(out)["terminal_generation"] == 1


def test_g_generation_increments_from_prev(tmp_path):
    out = tmp_path / "out"
    # 模拟旧代次写者留下的 generation 7（无终态）→ 新 commit 必须 8（prev or 0 + 1）
    out.mkdir(parents=True, exist_ok=True)
    (out / "task.json").write_text(
        json.dumps({"task_id": _task_id(), "status": "RUNNING", "terminal_generation": 7}),
        encoding="utf-8",
    )
    r = finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md", workspace=str(tmp_path))
    assert r.terminal_generation == 8
    assert read_status(out)["terminal_generation"] == 8


def test_g_non_terminal_update_does_not_bump_generation(tmp_path):
    out = tmp_path / "out"
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING", task_path="T.md",
                                 workspace=str(tmp_path), stage="HERMES", agent="hermes")
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING", task_path="T.md",
                                 workspace=str(tmp_path), stage="WORKBUDDY", agent="workbuddy")
    assert "terminal_generation" not in read_status(out)
    r = finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md", workspace=str(tmp_path))
    assert r.terminal_generation == 1  # 非终态更新不递增


# ---------------------------------------------------------------------------
# H–L. reconciliation（§6B.6–§6B.8）
# ---------------------------------------------------------------------------


def _cancelled_dir(tmp_path, *, with_artifacts=True) -> Path:
    out = tmp_path / "out"
    task_file = _write_task(tmp_path)
    finalize_terminal(
        out, task_id=_task_id(), status="CANCELLED", task_path=task_file,
        workspace=str(tmp_path), report_path=str(out / "REPORT.md"),
        terminal_reason="CANCEL_REQUESTED", cancel_mode="soft",
    )
    if with_artifacts:
        (out / "route.json").write_text(json.dumps({"agents": ["hermes"], "reason": "test"}),
                                        encoding="utf-8")
        (out / "hermes_result.md").write_text("implemented ok", encoding="utf-8")
    return out


def test_h_reconcile_run_json_missing(tmp_path):
    out = _cancelled_dir(tmp_path)
    result = rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert run["terminal_generation"] == 1
    assert any("run.json created" in a for a in result.actions)
    # canonical 未被修改
    assert read_status(out)["status"] == "CANCELLED"


def test_i_reconcile_report_missing(tmp_path):
    out = _cancelled_dir(tmp_path)
    rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "任务已取消" in report
    assert "## Terminal Generation\n1" in report


def test_j_reconcile_stale_derived_generation(tmp_path):
    out = _cancelled_dir(tmp_path)
    (out / "run.json").write_text(
        json.dumps({"timestamp": "x", "status": "CANCELLED", "terminal_generation": 0}),
        encoding="utf-8",
    )
    rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["terminal_generation"] == 1  # stale generation 6→1（跟随 canonical）


def test_k_reconcile_derived_status_conflict(tmp_path):
    out = _cancelled_dir(tmp_path)
    (out / "run.json").write_text(
        json.dumps({"timestamp": "x", "status": "SUCCESS", "terminal_generation": 1}),
        encoding="utf-8",
    )
    rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"  # 冲突 → 按 canonical 重建


def test_l_reconcile_idempotent_and_noop(tmp_path):
    out = _cancelled_dir(tmp_path)
    rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    run_before = (out / "run.json").read_bytes()
    report_before = (out / "REPORT.md").read_bytes()
    result = rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    assert result.actions == ["no-op (derived artifacts consistent with canonical)"]
    assert (out / "run.json").read_bytes() == run_before
    assert (out / "REPORT.md").read_bytes() == report_before
    # 重复调用返回相同 canonical result
    assert result.status == "CANCELLED"
    assert result.terminal_generation == 1


def test_reconcile_no_terminal_raises(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "TASK.md").write_text("x", encoding="utf-8")
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING", task_path="T.md",
                                 workspace=str(tmp_path))
    with pytest.raises(rec_mod.ReconciliationError, match="无 canonical terminal"):
        rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)


def test_reconcile_no_task_json_raises(tmp_path):
    with pytest.raises(rec_mod.ReconciliationError, match="无 canonical task.json"):
        rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), tmp_path / "nope")


# ---------------------------------------------------------------------------
# M–O. runner cancel 检查点（req 11–13）
# ---------------------------------------------------------------------------


def _run_with_mock_agents(tmp_path, monkeypatch, agents, results, cancel_writer=None, cancel_before=False):
    """runner.run 集成：mock run_agent；cancel_writer 在 hermes 执行期间写入 cancel.request。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if cancel_writer is not None and agent == cancel_writer["agent"]:
            cancel_writer["fn"](tmp_path)
        if agent in ("hermes",):
            time.sleep(cancel_writer["sleep"] if cancel_writer else 0.0)
        return results.get(agent, "implemented ok")

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(runner_mod, "decide_route", lambda task: runner_mod.Route(agents, "test"))
    task_file = _write_task(tmp_path)
    out = tmp_path / "out"
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    if cancel_before:
        cancel_mod.write_cancel_request(out, _task_id())
    report_path = runner_mod.run(task_file, ws, out)
    data = json.loads((out / "task.json").read_text(encoding="utf-8"))
    return calls, data, out, report_path


def test_m_cancel_before_hermes_does_not_start_hermes(tmp_path, monkeypatch):
    calls, data, out, _ = _run_with_mock_agents(
        tmp_path, monkeypatch, ["hermes", "workbuddy", "codex"],
        {"hermes": "ok", "workbuddy": "PASS", "codex": "APPROVE"},
        cancel_before=True,
    )
    assert calls == []  # Hermes 未启动（req 12）
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert (out / "REPORT.md").exists()
    # 已完成 artifact（TASK.md 等）保留
    assert (out / "TASK.md").exists() or (tmp_path / "TASK.md").exists()


def test_n_cancel_after_hermes_before_workbuddy(tmp_path, monkeypatch):
    calls, data, out, _ = _run_with_mock_agents(
        tmp_path, monkeypatch, ["hermes", "workbuddy", "codex"],
        {"hermes": "implemented ok", "workbuddy": "PASS", "codex": "APPROVE"},
        cancel_writer={"agent": "hermes", "sleep": 0.05,
                       "fn": lambda t: cancel_mod.write_cancel_request(t / "out", _task_id())},
    )
    assert calls == ["hermes"]  # WorkBuddy 未启动（req 13）
    assert data["status"] == "CANCELLED"
    # 已完成 hermes artifacts 保留
    assert (out / "hermes_result.md").exists()
    assert (out / "hermes_prompt.md").exists()
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"


def test_o_cancel_after_workbuddy_before_codex(tmp_path, monkeypatch):
    calls, data, out, _ = _run_with_mock_agents(
        tmp_path, monkeypatch, ["hermes", "workbuddy", "codex"],
        {"hermes": "implemented ok", "workbuddy": "PASS", "codex": "APPROVE"},
        cancel_writer={"agent": "workbuddy", "sleep": 0.05,
                       "fn": lambda t: cancel_mod.write_cancel_request(t / "out", _task_id())},
    )
    assert calls == ["hermes", "workbuddy"]  # Codex 未启动（req 13）
    assert data["status"] == "CANCELLED"
    assert (out / "hermes_result.md").exists()
    assert (out / "workbuddy_result.md").exists()
    assert not (out / "codex_prompt.md").exists()


# ---------------------------------------------------------------------------
# P–R. late cancel 不覆盖已提交终态（req 14 / req 16）
# ---------------------------------------------------------------------------


def _finalize_and_late_cancel(tmp_path, status):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status=status, task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    (out / "REPORT.md").write_text(f"# REPORT\n\n## Current Status\n{status}\n", encoding="utf-8")
    (out / "run.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    cancel_mod.write_cancel_request(out, _task_id())  # late cancel.request
    canonical = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    return out, canonical


@pytest.mark.parametrize("status", ["SUCCESS", "WAITING", "FAILED"])
def test_pqr_late_cancel_preserves_terminal(tmp_path, status):
    out, canonical = _finalize_and_late_cancel(tmp_path, status)
    assert canonical.status == status
    assert canonical.preserved is True
    assert read_status(out)["status"] == status  # 未被覆盖成 CANCELLED
    assert read_status(out)["terminal_generation"] == 1
    # cancel.request 存在 + task 已 terminal → request 被忽略/吸收（req 16），
    # 派生产物跟随 canonical（不写成 CANCELLED）
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == status
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert f"## Current Status\n{status}" in report


# ---------------------------------------------------------------------------
# S. duplicate cancel 幂等（req 15 / §6A.14）
# ---------------------------------------------------------------------------


def _recovery_ready(tmp_path: Path, out_name: str = "out", requested_at: str | None = None) -> Path:
    """FIX-001 recovery 前置：建立 RUNNING canonical task.json + 合法 cancel.request。

    （req 7：recovery 要求 canonical task.json 存在且 task_id 匹配——
    真实场景是 runner crash 后残留的 RUNNING canonical。）
    """
    out = tmp_path / out_name
    task_lifecycle.update_status(
        out, task_id=_task_id(), status="RUNNING",
        task_path=str(out / "TASK.md"), workspace=str(tmp_path),
    )
    cancel_mod.write_cancel_request(out, _task_id(), requested_at=requested_at)
    return out


def test_s_duplicate_cancel_idempotent(tmp_path):
    out = _recovery_ready(tmp_path)
    r1 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    run1 = (out / "run.json").read_bytes()
    report1 = (out / "REPORT.md").read_bytes()
    r2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert r1.status == "CANCELLED"
    assert r1.terminal_generation == 1
    assert r2.status == "CANCELLED"
    assert r2.terminal_generation == 1  # 不重复 bump generation
    assert (out / "run.json").read_bytes() == run1
    assert (out / "REPORT.md").read_bytes() == report1
    assert read_status(out)["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# T / U. CANCELLED REPORT / run.json（req 17 / 18）
# ---------------------------------------------------------------------------


def test_t_cancelled_report_content(tmp_path):
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    (out / "route.json").write_text(json.dumps({"agents": ["hermes", "workbuddy"], "reason": "t"}),
                                    encoding="utf-8")
    (out / "hermes_result.md").write_text("implemented ok", encoding="utf-8")
    fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "任务已取消（CANCELLED）" in report
    assert _task_id() in report  # Task ID
    assert "取消请求时间: 2026-08-27T10:00:00" in report  # cancellation time
    assert "已完成阶段与 Agent 结果已保留" in report
    assert "后续阶段未执行" in report
    # 不得伪造 Force Cancel / PID kill / ownership verified（FIX-001 修正原 tautology：
    # 旧断言 "FORCE" not in upper() or "FORCE" not in report 恒真；soft CANCELLED REPORT
    # 必须严格不含 FORCE）
    assert "FORCE" not in report
    assert "force" not in report.lower()
    assert "taskkill" not in report.lower()
    assert "PID" not in report
    assert "ownership" not in report.lower()


def test_u_cancelled_run_json_follows_generation(tmp_path):
    out = _recovery_ready(tmp_path)  # FIX-001：RUNNING canonical + 合法 cancel.request
    fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert run["terminal_generation"] == 1
    canonical = read_canonical_terminal(out)
    assert run["terminal_generation"] == canonical.terminal_generation


# ---------------------------------------------------------------------------
# V. legacy task 无 generation（req 6 兼容；不崩溃）
# ---------------------------------------------------------------------------


def test_v_legacy_task_without_generation(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "task.json").write_text(
        json.dumps({"task_id": _task_id(), "status": "RUNNING",
                    "task_path": "T.md", "workspace": str(tmp_path)}),
        encoding="utf-8",
    )
    r = finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md",
                          workspace=str(tmp_path))
    assert r.terminal_generation == 1
    # legacy terminal（无 generation 字段）→ reconcile 不崩溃、幂等
    legacy = tmp_path / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "task.json").write_text(
        json.dumps({"task_id": "LEGACY", "status": "SUCCESS", "report_path": str(legacy / "REPORT.md")}),
        encoding="utf-8",
    )
    (legacy / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    r1 = rec_mod.reconcile_terminal_artifacts("LEGACY", str(tmp_path), legacy)
    assert r1.status == "SUCCESS"
    assert r1.terminal_generation is None
    r2 = rec_mod.reconcile_terminal_artifacts("LEGACY", str(tmp_path), legacy)
    assert r2.actions == ["no-op (derived artifacts consistent with canonical)"]


# ---------------------------------------------------------------------------
# W. invalid / partial cancel.request 安全处理（req 16 / §6A.15）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content", [
    "{broken json",
    json.dumps({"task_id": _task_id()}),  # 缺 requested_at / request
    json.dumps({"task_id": _task_id(), "requested_at": "x", "request": "force_cancel"}),
    json.dumps({"requested_at": "x", "request": "soft_cancel"}),  # 缺 task_id
    "just text",
])
def test_w_invalid_cancel_request_ignored_safely(tmp_path, monkeypatch, content):
    calls, data, out, _ = _run_with_mock_agents(
        tmp_path, monkeypatch, ["hermes"],
        {"hermes": "implemented ok"},
    )
    # 覆盖：无请求时正常完成
    req, warning = cancel_mod.inspect_cancel_request(out)
    assert req is None
    assert warning is None
    # 写入无效请求 → inspect 返回 warning 而非崩溃；Core 按“无请求”继续
    out2 = tmp_path / "out2"
    out2.mkdir(parents=True, exist_ok=True)
    (out2 / "cancel.request").write_text(content, encoding="utf-8")
    req2, warning2 = cancel_mod.inspect_cancel_request(out2)
    assert req2 is None
    assert warning2 is not None  # 明确 warning，不拒绝执行


def test_w_mismatched_task_id_cancel_request_ignored(tmp_path, monkeypatch):
    """cancel.request task_id 不匹配 → runner 忽略并继续（§6A.15 不拒绝执行）。"""
    calls, data, out, _ = _run_with_mock_agents(
        tmp_path, monkeypatch, ["hermes", "workbuddy"],
        {"hermes": "ok", "workbuddy": "PASS"},
    )
    out2 = tmp_path / "out3"
    cancel_mod.write_cancel_request(out2, "OTHER-TASK")
    req, warning = cancel_mod.inspect_cancel_request(out2)
    assert req is not None and req.task_id == "OTHER-TASK"
    # runner 检查点路径：task_id 不匹配 → 忽略
    assert not runner_mod._check_cancel(out2, _task_id(), tmp_path / "TASK.md", tmp_path)


def test_w_cancel_request_is_not_terminal_authority(tmp_path):
    """cancel.request 只含请求字段，不含任何 terminal authority 字段。"""
    out = tmp_path / "out"
    cancel_mod.write_cancel_request(out, _task_id())
    data = json.loads((out / "cancel.request").read_text(encoding="utf-8"))
    assert set(data.keys()) == {"task_id", "requested_at", "request"}
    assert data["request"] == "soft_cancel"
    assert "status" not in data
    assert "terminal_generation" not in data
    # 有 request 但无 task.json → 无终态（request 不是 truth）
    assert read_canonical_terminal(out) is None


# ---------------------------------------------------------------------------
# X / Y. recovery finalizer（§6A.12 / §6B.21）
# ---------------------------------------------------------------------------


def test_x_recovery_finalizer_idempotent(tmp_path):
    out = _recovery_ready(tmp_path)  # FIX-001：RUNNING canonical + 合法 cancel.request
    r1 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    r2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert r1.status == "CANCELLED" and r1.terminal_generation == 1
    assert r2.status == "CANCELLED" and r2.terminal_generation == 1
    assert r2.preserved is True


def test_y_recovery_finalizer_preserves_existing_terminal(tmp_path):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    (out / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    canonical = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert canonical.status == "SUCCESS"
    assert canonical.preserved is True
    assert read_status(out)["status"] == "SUCCESS"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# Z. 无 force-kill 行为（req 21 / Do Not Do）
# ---------------------------------------------------------------------------

PHASE_E_FILES = [
    "ai_agent_framework/lock_utils.py",
    "ai_agent_framework/reconcile.py",
    "ai_agent_framework/finalize_cancelled.py",
    "ai_agent_framework/cancel.py",
    "ai_agent_framework/task_lifecycle.py",
    "ai_agent_framework/runner.py",
]


def test_z_no_force_kill_invocation():
    """Phase E Core 源码不得具备任何进程终止能力（req 21 / Do Not Do）。

    检查可执行能力（import subprocess / os.kill / .kill( / .terminate( / Popen），
    而非文档字符串中的“taskkill”字样（finalize_cancelled.py 文档明确声明不实现）。
    """
    for rel in PHASE_E_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import subprocess" not in text, f"{rel} 不应 import subprocess（无进程控制能力）"
        assert "from subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "os.kill" not in text, f"{rel} 包含 os.kill"
        assert ".kill(" not in text, f"{rel} 包含 .kill("
        assert ".terminate(" not in text, f"{rel} 包含 .terminate("
        assert "Popen" not in text, f"{rel} 包含 Popen"


# ---------------------------------------------------------------------------
# 补充：cancel.request 契约原子写 / consume
# ---------------------------------------------------------------------------


def test_cancel_request_atomic_write_and_consume(tmp_path):
    out = tmp_path / "out"
    p = cancel_mod.write_cancel_request(out, _task_id())
    assert p == out / "cancel.request"
    assert not list(out.glob("*.tmp"))
    req = cancel_mod.read_cancel_request(out)
    assert req.task_id == _task_id()
    assert req.request == "soft_cancel"
    assert cancel_mod.consume_cancel_request(out) is True
    assert not (out / "cancel.request").exists()
    assert (out / "cancel.done").exists()  # 改名保留证据（§6.6）
    assert cancel_mod.consume_cancel_request(out) is False  # 幂等


def test_runner_cancel_exit_semantics():
    """soft cancel 的 runner 语义：CANCEL_EXIT_CODE = 0（exit code 不参与判定，§6A.5）。"""
    assert runner_mod.CANCEL_EXIT_CODE == 0


# ---------------------------------------------------------------------------
# 补充：launcher canonical-aware 兼容读取（req 19；完整 wait-thread 归 005-B）
# ---------------------------------------------------------------------------


class _FakeProc:
    """与 tests/test_bridge_launcher.py 的 FakeProc 等价的最小假进程。"""

    def __init__(self, exit_code: int = 0, stdout_text: str = ""):
        import io

        self._exit = exit_code
        self.stdout = io.StringIO(stdout_text)
        self.returncode = None

    def wait(self) -> int:
        self.returncode = self._exit
        return self._exit


def test_launcher_follows_cancelled_canonical_not_exit_code(tmp_path, monkeypatch):
    from bridge import launcher as launcher_mod

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    task_file = _write_task(tmp_path)
    finalize_terminal(out, task_id=_task_id(), status="CANCELLED", task_path=task_file,
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    (out / "REPORT.md").write_text("# REPORT\n\n## Current Status\nCANCELLED\n", encoding="utf-8")
    monkeypatch.setattr(launcher_mod.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(exit_code=1, stdout_text=""))  # 非零退出

    done = threading.Event()
    captured = {}

    def on_finished(last, output):
        captured["last"] = last
        done.set()

    l = launcher_mod.FrameworkLauncher(run_py=tmp_path / "run.py", on_finished=on_finished,
                                       registry_dir=tmp_path / "aaf-bridge" / "launches")
    assert l.launch(task_file, str(tmp_path), out, _task_id()) is True
    assert done.wait(5.0)
    assert l.last.result == launcher_mod.RESULT_CANCELLED  # 不因 exit 1 被判 FAILED
    assert l.last.report_path == str(out / "REPORT.md")


def test_launcher_legacy_path_unchanged_without_canonical(tmp_path, monkeypatch):
    """无 canonical terminal 时保留 legacy 分类（exit!=0 → FAILED），不回归。"""
    from bridge import launcher as launcher_mod

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(launcher_mod.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(exit_code=2, stdout_text=""))
    done = threading.Event()
    l = launcher_mod.FrameworkLauncher(run_py=tmp_path / "run.py",
                                       registry_dir=tmp_path / "aaf-bridge" / "launches",
                                       on_finished=lambda last, output: done.set())
    assert l.launch(tmp_path / "T.md", str(tmp_path), out, "AAF-X") is True
    assert done.wait(5.0)
    assert l.last.result == launcher_mod.RESULT_FAILED


# ---------------------------------------------------------------------------
# 补充：CANCELLED 进度收敛（req 24；设计 §4.1.5）
# ---------------------------------------------------------------------------


def test_progress_cancelled_freezes_not_100():
    from bridge import progress as prog

    strip = {"VALIDATION": "SUCCESS", "BOUNDARY": "SUCCESS", "HERMES": "SUCCESS",
             "WORKBUDDY": "PENDING", "CODEX": "PENDING", "REPORT": "PENDING"}
    est = prog.estimate_progress(strip, "CANCELLED")
    assert est.percent == 55  # 停在已完成阶段权重和（5+5+45），不显示 100%
    est100 = prog.estimate_progress(strip, "SUCCESS")
    assert est100.percent == 100  # SUCCESS 才 100
    text = prog.progress_text(est.percent, status="CANCELLED")
    assert "100%" not in text
    assert prog.DONE_TEXT not in text


# ---------------------------------------------------------------------------
# 补充：archive 支持 CANCELLED（§6.6 可归档终态）
# ---------------------------------------------------------------------------


def test_archive_cancelled_terminal(tmp_path):
    from ai_agent_framework import task_archive

    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status="CANCELLED", task_path="T.md",
                      workspace=str(tmp_path))
    (out / "REPORT.md").write_text("# R", encoding="utf-8")
    result = task_archive.archive_package(out, tmp_path / "archive")
    assert result.status == "CANCELLED"
    assert (tmp_path / "archive" / _task_id() / "task.json").exists()
