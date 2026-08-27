"""Phase E FIX-001（AAF-v0.4-TASK-005-A-FIX-001）安全阻断修复测试（req 19 A–T）。

关闭 Codex 两个 blocking findings：

Blocker 1 — late non-terminal update 覆盖 terminal：
  - A–D：late RUNNING 不覆盖 CANCELLED / SUCCESS / WAITING / FAILED
  - E：generation 与 terminal metadata 在 late runtime update 后保持不变（req 16）
  - F：真实跨进程 runtime-vs-terminal 竞争（真实 OS state.lock + subprocess，不 mock）
  - G：真实 Runner Agent-return-after-CANCELLED race（req 6）
  - lock failure：non-terminal update 取不到锁 → 抛 LockTimeout、不写、不绕过（req 4）
  - legacy：terminal（含无 generation 的 legacy terminal）拒绝 late runtime update（req 17）

Blocker 2 — recovery finalizer 无 evidence / 无 identity 验证：
  - H–L：missing / malformed / task_id mismatch / wrong type / canonical mismatch 全部 fail safely
  - M/N：合法 soft evidence 成功；duplicate 幂等
  - O/P：existing terminal（SUCCESS/CANCELLED）无 evidence 也 preserve（req 9）
  - Q：force recovery 在 005-A 明确拒绝（FORCE_RECOVERY_NOT_AVAILABLE，req 10）
  - R：CLI 与 library 同规则，无 bypass（req 11）
  - S：无 force-kill 能力静态断言仍成立
  - T：修正 soft CANCELLED REPORT no-force 断言（advisory A 的 tautology）

真实 E2E（req 20）：真实 Runner + deterministic agent → Agent 执行期间真实
`finalize_cancelled` CLI 子进程提交 CANCELLED → Agent 返回 → Runner post-agent 恢复
→ canonical 保持 CANCELLED → 后续 agent 不启动 → run.json/REPORT = CANCELLED →
terminal_generation 稳定。
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
from ai_agent_framework.lock_utils import LockTimeout
from ai_agent_framework.task_lifecycle import (
    finalize_terminal,
    read_status,
    update_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

MINIMAL_TASK = """# Task ID
T-FIX-001

# Task Name
Phase E FIX-001 safety blockers

# Objective
验证 late runtime update 不覆盖 terminal + recovery evidence 验证

# Acceptance
1. 通过
"""


def _task_id() -> str:
    return "T-FIX-001"


def _write_task(tmp_path: Path) -> Path:
    task_file = tmp_path / "TASK.md"
    task_file.write_text(MINIMAL_TASK, encoding="utf-8")
    return task_file


def _recovery_ready(tmp_path: Path, task_id: str | None = None, requested_at: str | None = None) -> Path:
    """FIX-001 recovery 前置：RUNNING canonical + 合法 cancel.request（真实 crash 现场）。"""
    tid = task_id or _task_id()
    out = tmp_path / "out"
    task_lifecycle.update_status(
        out, task_id=tid, status="RUNNING",
        task_path=str(out / "TASK.md"), workspace=str(tmp_path),
    )
    cancel_mod.write_cancel_request(out, tid, requested_at=requested_at)
    return out


def _spawn_worker(tmp_path: Path, worker: str, *args: str) -> subprocess.Popen:
    """在 tmp_path 写 worker 脚本并启动子进程（真实 OS 锁跨进程验证，不 mock）。"""
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


def _run_worker(proc: subprocess.Popen) -> str:
    out_text = proc.communicate(timeout=60)[0] or ""
    assert proc.returncode == 0, f"worker 异常退出: {out_text}"
    return out_text


# ---------------------------------------------------------------------------
# A–D. late RUNNING cannot overwrite terminal（Blocker 1 闭合，§6A.2 / §6B.2-D）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal", ["CANCELLED", "SUCCESS", "WAITING", "FAILED"])
def test_abcd_late_running_cannot_overwrite_terminal(tmp_path, terminal):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status=terminal, task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    before = read_status(out)

    res = update_status(out, task_id=_task_id(), status="RUNNING", task_path="T.md",
                        workspace=str(tmp_path), stage="HERMES", agent="hermes")
    # deterministic “ignored / preserved terminal” result（req 1）
    assert res.preserved is True
    assert res.status == terminal
    assert res.terminal_generation == 1

    after = read_status(out)
    assert after["status"] == terminal  # 终态未被降回 RUNNING
    assert after["terminal_generation"] == 1  # generation 不变
    assert after["updated_at"] == before["updated_at"]  # 无任何写发生
    assert "stage" not in after or after.get("stage") != "HERMES"  # late stage 未写入


# ---------------------------------------------------------------------------
# E. generation + terminal metadata preserved after late runtime updates（req 2/16）
# ---------------------------------------------------------------------------


def test_e_generation_and_terminal_metadata_preserved_after_late_updates(tmp_path):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status="CANCELLED", task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"),
                      terminal_reason="CANCEL_REQUESTED", cancel_mode="soft")
    before = read_status(out)

    # 各类 late non-terminal update（RUNNING stage / CREATED / agent / phase / last_activity）
    for kwargs in [
        {"status": "RUNNING"},
        {"status": "RUNNING", "stage": "HERMES", "agent": "hermes", "phase_state": "RUNNING"},
        {"status": "CREATED"},
        {"status": "RUNNING", "stage": "REPORT", "agent": None, "phase_state": "SUCCESS"},
    ]:
        status = kwargs.pop("status")
        res = update_status(out, task_id=_task_id(), status=status, task_path="T.md",
                            workspace=str(tmp_path), **kwargs)
        assert res.preserved is True
        assert res.status == "CANCELLED"

    after = read_status(out)
    # generation 不消失、不回 null、不 bump（req 16）
    assert after["terminal_generation"] == before["terminal_generation"] == 1
    # terminal metadata 全部保留（req 2）
    for key in ("terminal_generation", "terminal_at", "terminal_reason", "cancel_mode",
                "report_path", "updated_at"):
        assert after[key] == before[key], f"terminal metadata {key} 丢失"
    assert after["status"] == "CANCELLED"


def test_legacy_terminal_rejects_late_runtime_update(tmp_path):
    """legacy terminal（无 terminal_generation）→ late non-terminal update 也被拒绝（req 17）。"""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "task.json").write_text(json.dumps({"task_id": "LEGACY", "status": "SUCCESS"}),
                                   encoding="utf-8")
    res = update_status(out, task_id="LEGACY", status="RUNNING", task_path="T.md",
                        workspace=str(tmp_path))
    assert res.preserved is True
    assert res.status == "SUCCESS"
    data = read_status(out)
    assert data["status"] == "SUCCESS"
    assert "terminal_generation" not in data  # 未被改写成任何非终态内容


def test_legacy_non_terminal_update_still_works(tmp_path):
    """legacy 非终态 task.json：non-terminal update 仍可正常进行（req 17）。"""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "task.json").write_text(json.dumps({"task_id": "LEGACY", "status": "RUNNING"}),
                                   encoding="utf-8")
    res = update_status(out, task_id="LEGACY", status="RUNNING", task_path="T.md",
                        workspace=str(tmp_path), stage="HERMES", agent="hermes")
    assert res.preserved is False
    data = read_status(out)
    assert data["status"] == "RUNNING"
    assert data["stage"] == "HERMES"


# ---------------------------------------------------------------------------
# lock failure semantics（req 4：获取不到锁 → 不写、不绕过、抛明确错误）
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


def test_lock_failure_non_terminal_update_does_not_write(tmp_path):
    out = _recovery_ready(tmp_path)
    ready = tmp_path / "ready.txt"
    proc = _spawn_worker(tmp_path, HOLD_WORKER, str(out), _task_id(), "2.0", str(ready))
    try:
        deadline = time.monotonic() + 20.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "子进程未在限时内取得锁"
        before = read_status(out)
        with pytest.raises(LockTimeout):
            update_status(out, task_id=_task_id(), status="RUNNING", task_path="T.md",
                          workspace=str(tmp_path), lock_timeout=0.3)
        after = read_status(out)
        assert after["updated_at"] == before["updated_at"]  # 锁失败：不写 task.json
        assert after["status"] == "RUNNING"  # canonical 未被改动
    finally:
        proc.communicate(timeout=20)


# ---------------------------------------------------------------------------
# F. real cross-process nonterminal-vs-terminal race（req 5 Case A + req 19-F）
# ---------------------------------------------------------------------------

RUNTIME_WORKER = """\
import json, sys
from pathlib import Path
from ai_agent_framework.task_lifecycle import update_status

out, task_id, ws = sys.argv[1], sys.argv[2], sys.argv[3]
res = update_status(
    Path(out), task_id=task_id, status="RUNNING",
    task_path=str(Path(out) / "TASK.md"), workspace=ws,
    stage="HERMES", agent="hermes",
)
print(json.dumps(res.to_dict()))
"""

TERMINAL_WORKER = """\
import sys
from pathlib import Path
from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import finalize_cancelled

out, task_id, ws = sys.argv[1], sys.argv[2], sys.argv[3]
cancel_mod.write_cancel_request(Path(out), task_id)
c = finalize_cancelled.finalize_cancelled_task(task_id, ws, Path(out))
print("OK cancel", c.status, c.terminal_generation, c.preserved)
"""


def test_f_cross_process_terminal_beats_late_runtime(tmp_path):
    """强制时序（deterministic）：CANCELLED 先 commit → runtime writer 后获得锁 →
    最终 canonical 仍 CANCELLED（真实子进程 + 真实 OS state.lock）。"""
    out = _recovery_ready(tmp_path)
    fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)  # terminal 先 commit
    assert read_status(out)["status"] == "CANCELLED"

    proc = _spawn_worker(tmp_path, RUNTIME_WORKER, str(out), _task_id(), str(tmp_path))
    res = json.loads(_run_worker(proc))
    assert res["preserved"] is True  # runtime 写者被拒绝
    assert res["status"] == "CANCELLED"
    assert res["terminal_generation"] == 1
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1


@pytest.mark.parametrize("iteration", range(3))
def test_f_cross_process_runtime_vs_terminal_race_invariant(tmp_path, iteration):
    """真正同时竞争：runtime writer vs CANCELLED finalizer（真实子进程 + 真实锁）。

    不变式（任意 winner 均成立）：canonical 终态 = CANCELLED、generation = 1、
    派生产物跟随 canonical；runtime writer 的写入（若成功）不可能把终态降级。
    """
    out = _recovery_ready(tmp_path)
    p1 = _spawn_worker(tmp_path, TERMINAL_WORKER, str(out), _task_id(), str(tmp_path))
    p2 = _spawn_worker(tmp_path, RUNTIME_WORKER, str(out), _task_id(), str(tmp_path))
    o1 = _run_worker(p1)
    o2 = _run_worker(p2)

    assert "OK cancel CANCELLED 1 False" in o1  # terminal worker 胜出（唯一 terminal writer）
    data = read_status(out)
    assert data["status"] == "CANCELLED", f"canonical 必须保持 CANCELLED（iteration={iteration}）"
    assert data["terminal_generation"] == 1, "generation 必须为 1（恰一次 terminal commit）"
    res = json.loads(o2)
    assert res["status"] in ("CANCELLED", "RUNNING")  # runtime 写者要么被拒绝要么先写后被覆盖
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# G. real Runner Agent-return-after-CANCELLED race（req 6 / req 19-G）
# ---------------------------------------------------------------------------


def test_g_runner_agent_return_after_cancelled_race(tmp_path, monkeypatch):
    """Agent running → cancel finalizer 提交 CANCELLED → Agent 返回 →
    Runner post-agent runtime/stage update 被拒绝：CANCELLED 保留、后续 agent
    不启动、artifact 保留、generation 不变（真实 runner + 真实 OS 锁）。"""
    calls = []
    out = tmp_path / "out"

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == "hermes":
            # Agent 执行期间：另一 writer（recovery finalizer）提交 CANCELLED
            def finalize_late():
                cancel_mod.write_cancel_request(out, _task_id())
                fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)

            t = threading.Thread(target=finalize_late)
            t.start()
            time.sleep(0.3)  # agent 仍在执行；finalizer 并发提交 CANCELLED
            t.join()
        return {"hermes": "implemented ok", "workbuddy": "PASS", "codex": "APPROVE"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(runner_mod, "decide_route",
                        lambda task: runner_mod.Route(["hermes", "workbuddy", "codex"], "test"))
    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING",
                                 task_path=str(task_file), workspace=str(ws))

    report_path = runner_mod.run(task_file, ws, out)

    data = read_status(out)
    assert data["status"] == "CANCELLED"  # CANCELLED preserved，未被 RUNNING 覆盖
    assert data["terminal_generation"] == 1  # generation 不变
    assert calls == ["hermes"]  # 后续 agent 不启动（workbuddy / codex 未调用）
    # existing agent artifact 保留
    assert (out / "hermes_result.md").exists()
    assert "implemented ok" in (out / "hermes_result.md").read_text(encoding="utf-8")
    # 派生产物跟随 canonical
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert run["terminal_generation"] == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert (out / "hermes_prompt.md").exists()  # 已启动 agent 的 prompt 保留
    assert not (out / "workbuddy_prompt.md").exists()  # 未启动 agent 无产物


# ---------------------------------------------------------------------------
# H–L. recovery evidence / identity validation（Blocker 2 闭合；req 19 H–L）
# ---------------------------------------------------------------------------


def test_h_recovery_missing_cancel_request_rejected(tmp_path):
    out = tmp_path / "out"
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING",
                                 task_path="T.md", workspace=str(tmp_path))
    with pytest.raises(fc_mod.RecoveryEvidenceError, match="cancel.request"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    data = read_status(out)
    assert data["status"] == "RUNNING"  # canonical 未被修改
    assert "terminal_generation" not in data
    assert not (out / "run.json").exists()  # 无 reconciliation 变更
    assert not (out / "REPORT.md").exists()


def test_i_recovery_malformed_cancel_request_rejected(tmp_path):
    out = _recovery_ready(tmp_path)
    (out / "cancel.request").write_text("{broken json", encoding="utf-8")
    with pytest.raises(fc_mod.RecoveryEvidenceError, match="cancel.request"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert read_status(out)["status"] == "RUNNING"
    assert not (out / "run.json").exists()


def test_j_recovery_task_id_mismatch_rejected(tmp_path):
    out = _recovery_ready(tmp_path)
    cancel_mod.write_cancel_request(out, "OTHER-TASK")  # request 属于别的任务
    with pytest.raises(fc_mod.RecoveryEvidenceError, match="task_id"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert read_status(out)["status"] == "RUNNING"
    assert not (out / "run.json").exists()


def test_k_recovery_wrong_request_type_rejected(tmp_path):
    out = _recovery_ready(tmp_path)
    (out / "cancel.request").write_text(
        json.dumps({"task_id": _task_id(), "requested_at": "2026-08-27T10:00:00",
                    "request": "force_cancel"}), encoding="utf-8")
    with pytest.raises(fc_mod.RecoveryEvidenceError, match="soft_cancel"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert read_status(out)["status"] == "RUNNING"
    assert not (out / "run.json").exists()


def test_k_recovery_bad_requested_at_rejected(tmp_path):
    out = _recovery_ready(tmp_path)
    (out / "cancel.request").write_text(
        json.dumps({"task_id": _task_id(), "requested_at": "not-a-timestamp",
                    "request": "soft_cancel"}), encoding="utf-8")
    with pytest.raises(fc_mod.RecoveryEvidenceError, match="requested_at"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert read_status(out)["status"] == "RUNNING"


def test_l_canonical_task_id_mismatch_rejected(tmp_path):
    out = tmp_path / "out"
    task_lifecycle.update_status(out, task_id="CANONICAL-X", status="RUNNING",
                                 task_path="T.md", workspace=str(tmp_path))
    cancel_mod.write_cancel_request(out, _task_id())  # request 匹配“请求的”task_id
    with pytest.raises(fc_mod.RecoveryError, match="RECOVERY_IDENTITY_ERROR"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    data = read_status(out)
    assert data["task_id"] == "CANONICAL-X"  # canonical identity 未被覆盖
    assert data["status"] == "RUNNING"
    assert "terminal_generation" not in data  # 零 generation bump
    assert not (out / "run.json").exists()  # 零 reconciliation 变更


# ---------------------------------------------------------------------------
# M/N. valid soft recovery succeeds + idempotent（req 19 M/N）
# ---------------------------------------------------------------------------


def test_m_valid_soft_recovery_succeeds(tmp_path):
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    canonical = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert canonical.status == "CANCELLED"
    assert canonical.terminal_generation == 1
    assert canonical.cancel_mode == "soft"
    assert canonical.preserved is False
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    assert data["cancel_mode"] == "soft"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "取消请求时间: 2026-08-27T10:00:00" in report


def test_n_duplicate_recovery_idempotent(tmp_path):
    out = _recovery_ready(tmp_path)
    r1 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    run1 = (out / "run.json").read_bytes()
    report1 = (out / "REPORT.md").read_bytes()
    r2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert r1.status == "CANCELLED" and r1.terminal_generation == 1
    assert r2.status == "CANCELLED" and r2.terminal_generation == 1
    assert r2.preserved is True
    assert (out / "run.json").read_bytes() == run1
    assert (out / "REPORT.md").read_bytes() == report1
    assert read_status(out)["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# O/P. existing terminal preserved without / despite evidence（req 9 / req 19 O/P）
# ---------------------------------------------------------------------------


def test_o_existing_success_preserved_without_evidence(tmp_path):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    (out / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    # 无 cancel.request：已有终态依然 preserve（evidence validation 只用于新提交 CANCELLED）
    canonical = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert canonical.status == "SUCCESS"
    assert canonical.preserved is True
    data = read_status(out)
    assert data["status"] == "SUCCESS"
    assert data["terminal_generation"] == 1
    # reconciliation 仍可用：run.json 跟随 canonical SUCCESS（不被 cancel 缺证据阻塞）
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report


def test_p_existing_cancelled_preserved_idempotently(tmp_path):
    out = _recovery_ready(tmp_path)
    r1 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    # 再次调用，即使 request 已被移除 → CANCELLED 依然 preserve（req 9：late/missing
    # evidence 不得改变 existing terminal）
    (out / "cancel.request").unlink()
    r2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert r1.status == "CANCELLED" and r1.terminal_generation == 1
    assert r2.status == "CANCELLED" and r2.terminal_generation == 1
    assert r2.preserved is True
    assert read_status(out)["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Q. force recovery refused（req 10 / req 19-Q）
# ---------------------------------------------------------------------------


def test_q_force_recovery_refused_in_005a(tmp_path):
    out = _recovery_ready(tmp_path)
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable, match="FORCE_RECOVERY_NOT_AVAILABLE"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out, cancel_mode="force")
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable, match="FORCE_RECOVERY_NOT_AVAILABLE"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out, reason="FORCE_CANCELLED")
    data = read_status(out)
    assert data["status"] == "RUNNING"  # 未提交任何终态
    assert "terminal_generation" not in data
    assert not (out / "run.json").exists()


def test_arbitrary_evidence_string_does_not_authorize(tmp_path):
    """req 12/16：arbitrary evidence 字符串不是 authority evidence——
    没有合法 cancel.request 时，即使传 evidence 也拒绝（不凭字符串提交 CANCELLED）。"""
    out = tmp_path / "out"
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING",
                                 task_path="T.md", workspace=str(tmp_path))
    with pytest.raises(fc_mod.RecoveryEvidenceError, match="cancel.request"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out,
                                       evidence="taskkill ok; ownership verified")
    assert read_status(out)["status"] == "RUNNING"  # 未被伪造 force evidence 覆盖


# ---------------------------------------------------------------------------
# R. CLI 与 library 同规则（req 11 / req 19-R；无 CLI bypass）
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ai_agent_framework.finalize_cancelled", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_r_cli_cannot_cancel_without_valid_evidence(tmp_path):
    out = tmp_path / "out"
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING",
                                 task_path="T.md", workspace=str(tmp_path))
    proc = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out))
    assert proc.returncode == fc_mod.EXIT_RECOVERY_ERROR
    assert "RECOVERY_EVIDENCE_ERROR" in proc.stderr
    assert read_status(out)["status"] == "RUNNING"  # CLI 无 bypass：canonical 未被修改

    # force CLI 同样拒绝（FORCE_RECOVERY_NOT_AVAILABLE）
    proc_f = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path),
                      "--output", str(out), "--cancel-mode", "force")
    assert proc_f.returncode == fc_mod.EXIT_RECOVERY_ERROR
    assert "FORCE_RECOVERY_NOT_AVAILABLE" in proc_f.stderr
    assert read_status(out)["status"] == "RUNNING"

    # canonical task_id 不匹配 → 拒绝
    proc_l = _run_cli("--task-id", "WRONG-TASK", "--workspace", str(tmp_path), "--output", str(out))
    assert proc_l.returncode == fc_mod.EXIT_RECOVERY_ERROR
    assert "RECOVERY_IDENTITY_ERROR" in proc_l.stderr
    assert read_status(out)["status"] == "RUNNING"


# ---------------------------------------------------------------------------
# S. no force kill still true（req 19-S / Do Not Do）
# ---------------------------------------------------------------------------

FIX_FILES = [
    "ai_agent_framework/task_lifecycle.py",
    "ai_agent_framework/cancel.py",
    "ai_agent_framework/finalize_cancelled.py",
    "ai_agent_framework/runner.py",
    "ai_agent_framework/lock_utils.py",
    "ai_agent_framework/reconcile.py",
]


def test_s_no_force_kill_still_true():
    """FIX-001 修改的 Core 文件不得具备进程控制能力（无 taskkill / kill / Popen）。"""
    for rel in FIX_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "from subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "os.kill" not in text, f"{rel} 包含 os.kill"
        assert ".kill(" not in text, f"{rel} 包含 .kill("
        assert ".terminate(" not in text, f"{rel} 包含 .terminate("
        assert "Popen" not in text, f"{rel} 包含 Popen"


# ---------------------------------------------------------------------------
# T. corrected soft CANCELLED REPORT no-force assertion（req 19-T / advisory A）
# ---------------------------------------------------------------------------


def test_t_corrected_soft_cancelled_report_no_force_assertion(tmp_path):
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    (out / "route.json").write_text(json.dumps({"agents": ["hermes"], "reason": "t"}),
                                    encoding="utf-8")
    (out / "hermes_result.md").write_text("implemented ok", encoding="utf-8")
    fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "任务已取消" in report
    # 严格断言（修正 advisory A 的 tautology：旧断言恒真；soft REPORT 必须严格无 FORCE）
    assert "FORCE" not in report
    assert "force" not in report.lower()
    assert "taskkill" not in report.lower()
    assert "PID" not in report
    assert "ownership" not in report.lower()


# ---------------------------------------------------------------------------
# Real E2E（req 20）：真实 Runner + deterministic agent + 真实 finalize CLI 子进程
# ---------------------------------------------------------------------------


def test_e2e_runner_late_agent_return_cancelled_via_cli_subprocess(tmp_path, monkeypatch):
    """真实 Runner / deterministic agent（mock run_agent）→ Agent 执行期间真实
    `python -m ai_agent_framework.finalize_cancelled` CLI 子进程提交 CANCELLED →
    Agent 返回 → Runner post-agent 恢复 → canonical 保持 CANCELLED → 后续 agent
    不启动 → run.json/REPORT = CANCELLED → terminal_generation 稳定（=1）。

    走真实 filesystem + Runner path + 真实 OS state.lock + 真实跨进程 finalizer。
    """
    calls = []
    out = tmp_path / "out"

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == "hermes":
            # Agent 执行期间：外部 recovery（CLI 子进程）提交 CANCELLED
            cancel_mod.write_cancel_request(out, _task_id())
            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            proc = subprocess.run(
                [sys.executable, "-m", "ai_agent_framework.finalize_cancelled",
                 "--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out)],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60, env=env,
            )
            assert proc.returncode == 0, f"finalize CLI 失败: {proc.stdout} {proc.stderr}"
        return {"hermes": "implemented ok", "workbuddy": "PASS", "codex": "APPROVE"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(runner_mod, "decide_route",
                        lambda task: runner_mod.Route(["hermes", "workbuddy", "codex"], "test"))
    task_file = _write_task(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    task_lifecycle.update_status(out, task_id=_task_id(), status="RUNNING",
                                 task_path=str(task_file), workspace=str(ws))

    report_path = runner_mod.run(task_file, ws, out)

    # canonical 保持 CANCELLED（terminal_generation 稳定 = 1，不 bump）
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    # Runner 不把状态重新写成 RUNNING；后续 agent 不启动
    assert calls == ["hermes"]
    # existing agent artifact 保留
    assert (out / "hermes_result.md").exists()
    assert (out / "hermes_prompt.md").exists()
    assert not (out / "workbuddy_prompt.md").exists()
    # run.json = CANCELLED；REPORT = CANCELLED
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED"
    assert run["terminal_generation"] == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    # 幂等：再次 CLI 收敛返回相同 canonical（generation 不变）
    canonical2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert canonical2.status == "CANCELLED"
    assert canonical2.terminal_generation == 1
    assert canonical2.preserved is True
