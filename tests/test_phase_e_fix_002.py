"""Phase E FIX-002（AAF-v0.4-TASK-005-A-FIX-002）Recovery TOCTOU 闭合测试（req 17 A–N + req 18 E2E）。

关闭 Codex 遗留唯一 blocking：recovery finalizer 的 canonical identity /
recovery evidence 验证与 CANCELLED terminal commit 不在同一个 state.lock
临界区（TOCTOU）。

FIX-002 单一临界区协议（frozen safety rule）::

    acquire task state.lock
    → 锁内 reload canonical task.json
    → validate canonical exists + canonical task_id == 请求 task_id
    → terminal arbitration（已有终态 → 保留 canonical，不要求 evidence）
    → 无终态：锁内验证当前 cancel.request（request=soft_cancel / task_id 匹配 /
      requested_at 合法）
    → 经 _finalize_terminal_locked（共享锁内 helper，调用方已持锁，不重复 acquire）
      提交 CANCELLED + 持久化 terminal_generation
    → release lock
    → reconcile run.json / REPORT.md

测试覆盖（req 17）：
  A  identity+evidence+commit 同一临界区（静态契约 + 真实持锁对抗者）
  B  cancel.request 在 recovery 取锁前已 invalid → 拒绝（真实锁 + 真实文件）
  C  request 在 recovery 临界区内被替换 → 无 stale-evidence 窗口；commit 后替换
     不能改 terminal
  D  canonical task_id 被改写（取锁前）→ 拒绝，identity 不被覆盖
  E  identity 在验证与 commit 之间不能变化（临界区内 raw rewrite 被锁内 commit 覆盖）
  F  failed validation → generation 不变
  G  successful recovery → generation 恰 +1
  H  existing terminal（4 种终态）无 evidence 仍 preserve
  I  existing terminal reconciliation 仍可用（修复缺失派生产物）
  J  force recovery 仍拒绝（含已有终态 + force）
  K  CLI 与 library 同一原子路径（无 bypass）
  L  强制时序：runtime writer 已启动并等待锁 → terminal 先 commit → late runtime
     no-op（真实 OS 锁 + 子进程 + 握手文件；CANCELLED + SUCCESS）
  M  无 force kill（静态断言）
  N  无第三 terminal writer（静态断言）
  并发  recovery vs recovery → 恰一次 commit
  锁失败  recovery 取锁失败 → 不写、不绕过（req 4/16）

真实 E2E（req 18）：
  Scenario 1：RUNNING canonical + 合法 cancel.request → recovery CLI → 单次原子
    CANCELLED commit → run.json CANCELLED → REPORT CANCELLED
  Scenario 2：RUNNING canonical + 不匹配 cancel.request → recovery CLI 失败 →
    task.json 保持 RUNNING → 无 generation bump → 无 CANCELLED derived artifacts
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import finalize_cancelled as fc_mod
from ai_agent_framework import task_lifecycle
from ai_agent_framework.lock_utils import LockTimeout, TaskStateLock
from ai_agent_framework.task_lifecycle import (
    _finalize_terminal_locked,
    finalize_terminal,
    read_status,
    update_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

MINIMAL_TASK = """# Task ID
T-FIX-002

# Task Name
Phase E FIX-002 recovery TOCTOU closure

# Objective
验证 recovery identity + evidence + commit 属于同一 state.lock 临界区

# Acceptance
1. 通过
"""


def _task_id() -> str:
    return "T-FIX-002"


def _recovery_ready(tmp_path: Path, task_id: str | None = None, requested_at: str | None = None) -> Path:
    """FIX-002 recovery 前置：RUNNING canonical + 合法 cancel.request（真实 crash 现场）。"""
    tid = task_id or _task_id()
    out = tmp_path / "out"
    update_status(
        out, task_id=tid, status="RUNNING",
        task_path=str(out / "TASK.md"), workspace=str(tmp_path),
    )
    cancel_mod.write_cancel_request(out, tid, requested_at=requested_at)
    return out


def _wait_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), f"等待文件超时: {path}"


def _spawn_worker(tmp_path: Path, worker: str, *args: str) -> subprocess.Popen:
    """在 tmp_path 写 worker 脚本并启动子进程（真实 OS 锁跨进程验证，不 mock）。"""
    script = tmp_path / f"w_{abs(hash(worker + str(args)))}.py"
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
    out_text = proc.communicate(timeout=90)[0] or ""
    assert proc.returncode == 0, f"worker 异常退出: {out_text}"
    return out_text


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ai_agent_framework.finalize_cancelled", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )


def _spawn_cli(*args: str) -> subprocess.Popen:
    """非阻塞 CLI（用于“测试持锁期间启动 recovery”的时序测试）。"""
    return subprocess.Popen(
        [sys.executable, "-m", "ai_agent_framework.finalize_cancelled", *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ---------------------------------------------------------------------------
# A. identity+evidence+commit 同一临界区（req 1/4/5；静态契约 + 真实持锁对抗者）
# ---------------------------------------------------------------------------


def test_a_single_critical_section_static_contract():
    """静态契约（req 1/2/4/5）：finalize_cancelled_task 内必须只有一个锁获取点，
    identity / arbitration / evidence / commit 全部位于同一 with 块内；
    不调用 public finalize_terminal（无 nested reentry）；锁内 helper 自身不取锁。"""
    src = (REPO_ROOT / "ai_agent_framework" / "finalize_cancelled.py").read_text(encoding="utf-8")

    # 整个模块只有一个 task_state_lock 获取点（identity 与 commit 之间不可能 release）
    assert src.count("task_state_lock(") == 1, "recovery 必须恰好一次获取 state.lock"

    fn_idx = src.index("def finalize_cancelled_task(")
    with_idx = src.index("with task_state_lock(", fn_idx)
    rec_idx = src.index("reconcile_terminal_artifacts(", with_idx)
    body = src[with_idx:rec_idx]  # 单一临界区 → reconciliation 之间的全部代码

    for marker in (
        "_validate_recovery_identity(",   # identity 验证在锁内
        "is_terminal_status(",            # terminal arbitration 在锁内
        "_validate_recovery_evidence(",   # evidence 验证在锁内（同一临界区）
        "_finalize_terminal_locked(",     # commit 在锁内（同一临界区）
    ):
        assert marker in body, f"{marker} 不在单一 state.lock 临界区内"

    # 验证在 commit 之前（顺序：identity → arbitration → evidence → commit）
    assert body.index("_validate_recovery_identity(") < body.index("_finalize_terminal_locked(")
    assert body.index("_validate_recovery_evidence(") < body.index("_finalize_terminal_locked(")

    # 不调用 public finalize_terminal（共享锁内 helper，无 nested reentry）
    assert "finalize_terminal(" not in src.replace("_finalize_terminal_locked(", ""), \
        "finalize_cancelled 不得调用 public finalize_terminal（会重复 acquire 同一锁）"

    # 锁内 helper 自身不得取锁（调用方已持锁）
    tl_src = (REPO_ROOT / "ai_agent_framework" / "task_lifecycle.py").read_text(encoding="utf-8")
    helper = tl_src[tl_src.index("def _finalize_terminal_locked("):tl_src.index("def finalize_terminal(")]
    assert "task_state_lock(" not in helper, "_finalize_terminal_locked 不得自行 acquire 锁"
    # helper 是唯一 task.json 终态写点（原子提交在 helper 内）
    assert "_atomic_write(task_json_path(output_dir), data)" in helper


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


def test_a_recovery_commits_nothing_while_lock_held_by_other_writer(tmp_path):
    """req 1/4：真实 OS 锁被另一 writer 持有时，recovery（CLI 子进程）被完全阻塞——
    identity/evidence/commit 全部发生在同一次锁持有内；持锁期间零写入。"""
    out = _recovery_ready(tmp_path)
    lock = TaskStateLock(out, _task_id(), timeout=10.0)
    lock.acquire()
    try:
        proc = _spawn_cli("--task-id", _task_id(), "--workspace", str(tmp_path),
                          "--output", str(out), "--lock-timeout", "5.0")
        # 持锁期间 recovery 不能提交任何东西（若存在“锁外验证/锁外提交”路径，这里就会泄漏写）
        time.sleep(0.8)
        data = read_status(out)
        assert data["status"] == "RUNNING"
        assert "terminal_generation" not in data
        assert not (out / "run.json").exists()
        assert not (out / "REPORT.md").exists()
    finally:
        lock.release()
    out_text = proc.communicate(timeout=90)[0] or ""
    assert proc.returncode == 0, out_text
    data = read_status(out)
    assert data["status"] == "CANCELLED"  # 释放后 recovery 完整走单一临界区
    assert data["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# B. cancel.request 在 recovery 取锁前已 invalid → 拒绝（req 6 / req 19-B）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corruption", ["delete", "malformed", "wrong-task"])
def test_b_evidence_invalid_before_lock_rejected(tmp_path, corruption):
    """req 6：B 在 A 获取锁前替换/删除/损坏 cancel.request → recovery 锁内重新验证
    看到 invalid → fail safely（no CANCELLED、零写、零 reconciliation、零 bump）。

    真实时序：test 持锁 → 替换 evidence → 启动 recovery（阻塞等待锁）→ 释放 →
    recovery 获锁后**锁内重读** evidence（不使用锁外缓存）→ 拒绝。"""
    out = _recovery_ready(tmp_path)
    lock = TaskStateLock(out, _task_id(), timeout=10.0)
    lock.acquire()
    try:
        if corruption == "delete":
            (out / "cancel.request").unlink()
        elif corruption == "malformed":
            (out / "cancel.request").write_text("{broken json", encoding="utf-8")
        elif corruption == "wrong-task":
            cancel_mod.write_cancel_request(out, "OTHER-TASK")
        proc = _spawn_cli("--task-id", _task_id(), "--workspace", str(tmp_path),
                          "--output", str(out), "--lock-timeout", "5.0")
    finally:
        lock.release()
    out_text = proc.communicate(timeout=90)[0] or ""
    assert proc.returncode == fc_mod.EXIT_RECOVERY_ERROR, out_text
    assert "RECOVERY_EVIDENCE_ERROR" in out_text
    data = read_status(out)
    assert data["status"] == "RUNNING"  # canonical 未被修改
    assert "terminal_generation" not in data  # 零 bump
    assert not (out / "run.json").exists()  # 零 reconciliation 变更
    assert not (out / "REPORT.md").exists()


# ---------------------------------------------------------------------------
# C. request 在 recovery 临界区内被替换 → 无 stale-evidence 窗口（req 6 / req 19-C）
# ---------------------------------------------------------------------------

MID_SECTION_REPLACE_WORKER = """\
import json, sys
from pathlib import Path
import ai_agent_framework.finalize_cancelled as fc_mod
from ai_agent_framework import cancel as cancel_mod

out, tid, ws = sys.argv[1], sys.argv[2], sys.argv[3]
orig = fc_mod._validate_recovery_evidence

def adversarial(output_dir, task_id, cancel_mode, reason):
    # 锁内验证当前证据（有效）→ 验证后、commit 前：另一 writer（B）替换 cancel.request
    orig(output_dir, task_id, cancel_mode, reason)
    cancel_mod.write_cancel_request(Path(output_dir), "OTHER-TASK")

fc_mod._validate_recovery_evidence = adversarial
c = fc_mod.finalize_cancelled_task(tid, ws, Path(out))
print("OK", c.status, c.terminal_generation, c.preserved)
"""


def test_c_evidence_replaced_mid_section_no_stale_window(tmp_path):
    """req 6 中段竞态：request 在 recovery 临界区内（验证后、commit 前）被替换。
    commit 依据的是**锁内已验证的 snapshot**——commit 不重读文件，因此不存在
    “验证后改用失效 evidence”的 stale window；替换发生在 commit 后也无法改 terminal。"""
    out = _recovery_ready(tmp_path)
    o = _run_worker(_spawn_worker(tmp_path, MID_SECTION_REPLACE_WORKER, str(out), _task_id(), str(tmp_path)))
    assert "OK CANCELLED 1 False" in o  # 基于锁内有效证据提交（非 stale）

    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    # 磁盘上的 request 已被 B 替换为 OTHER-TASK → 后续 request 变化不能改 terminal
    req = cancel_mod.inspect_cancel_request(out)[0]
    assert req is not None and req.task_id == "OTHER-TASK"
    c2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c2.status == "CANCELLED" and c2.terminal_generation == 1 and c2.preserved is True


def test_c_evidence_replaced_after_commit_terminal_immutable(tmp_path):
    """req 6 尾部：request 在 recovery commit 后才被替换/删除 → canonical CANCELLED
    已合法提交，后续 request 变化不能改 terminal。"""
    out = _recovery_ready(tmp_path)
    c1 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c1.status == "CANCELLED" and c1.terminal_generation == 1

    (out / "cancel.request").unlink()  # 删除证据
    c2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c2.status == "CANCELLED" and c2.terminal_generation == 1 and c2.preserved is True

    cancel_mod.write_cancel_request(out, "OTHER-TASK")  # 换成别的任务的请求
    c3 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c3.status == "CANCELLED" and c3.terminal_generation == 1 and c3.preserved is True
    data = read_status(out)
    assert data["status"] == "CANCELLED" and data["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# D. canonical task_id 被改写（取锁前）→ 拒绝，identity 不被覆盖（req 4 / req 19-D）
# ---------------------------------------------------------------------------


def test_d_canonical_identity_rewritten_before_lock_rejected(tmp_path):
    """req 4/7：B 在 A 取锁前改写 non-terminal canonical identity（raw rewrite）→
    recovery 锁内重读 identity → mismatch → explicit RecoveryError、零写、零 bump、
    零 reconciliation；wrong requested task_id 不能取消任务。"""
    out = _recovery_ready(tmp_path)
    lock = TaskStateLock(out, _task_id(), timeout=10.0)
    lock.acquire()
    try:
        # B：non-terminal identity rewrite（绕过锁的 raw write，模拟 rogue writer）
        (out / "task.json").write_text(
            json.dumps({"task_id": "B-ROGUE", "status": "RUNNING", "updated_at": "t"}),
            encoding="utf-8",
        )
        proc = _spawn_cli("--task-id", _task_id(), "--workspace", str(tmp_path),
                          "--output", str(out), "--lock-timeout", "5.0")
    finally:
        lock.release()
    out_text = proc.communicate(timeout=90)[0] or ""
    assert proc.returncode == fc_mod.EXIT_RECOVERY_ERROR, out_text
    assert "RECOVERY_IDENTITY_ERROR" in out_text
    data = read_status(out)
    assert data["task_id"] == "B-ROGUE"  # canonical identity 未被请求参数覆盖
    assert data["status"] == "RUNNING"
    assert "terminal_generation" not in data  # 零 generation bump
    assert not (out / "run.json").exists()  # 零 reconciliation 变更


# ---------------------------------------------------------------------------
# E. identity 在验证与 commit 之间不能变化（req 7 / req 19-E）
# ---------------------------------------------------------------------------

IN_SECTION_IDENTITY_REWRITE_WORKER = """\
import json, sys
from pathlib import Path
import ai_agent_framework.finalize_cancelled as fc_mod

out, tid, ws = sys.argv[1], sys.argv[2], sys.argv[3]
orig = fc_mod._validate_recovery_evidence

def adversarial(output_dir, task_id, cancel_mode, reason):
    # identity 验证完成后、commit 前：B 试图改写 canonical identity（raw write）
    orig(output_dir, task_id, cancel_mode, reason)
    Path(output_dir, "task.json").write_text(
        json.dumps({"task_id": "B-ROGUE", "status": "RUNNING"}), encoding="utf-8")

fc_mod._validate_recovery_evidence = adversarial
c = fc_mod.finalize_cancelled_task(tid, ws, Path(out))
print("OK", c.status, c.terminal_generation, c.preserved)
"""


def test_e_identity_cannot_change_between_validation_and_commit(tmp_path):
    """req 7：同一临界区内 identity 已验证（A）→ B 在 commit 前改写 canonical →
    commit 使用锁内 snapshot（task_id=A），rogue rewrite 被原子提交覆盖——
    “validated task_id=A → commit task_id=B 参数覆盖”不可能发生。"""
    out = _recovery_ready(tmp_path)
    o = _run_worker(_spawn_worker(tmp_path, IN_SECTION_IDENTITY_REWRITE_WORKER, str(out), _task_id(), str(tmp_path)))
    assert "OK CANCELLED 1 False" in o
    data = read_status(out)
    assert data["task_id"] == _task_id()  # canonical identity 保持已验证的 A
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# F. failed validation → generation 不变（req 11 / req 19-F）
# ---------------------------------------------------------------------------


def test_f_failed_validation_generation_unchanged(tmp_path):
    out = _recovery_ready(tmp_path)
    # 失败路径 1：evidence 缺失
    (out / "cancel.request").unlink()
    with pytest.raises(fc_mod.RecoveryEvidenceError):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    data = read_status(out)
    assert data["status"] == "RUNNING" and "terminal_generation" not in data

    # 失败路径 2：identity mismatch
    (out / "task.json").write_text(json.dumps({"task_id": "X", "status": "RUNNING"}), encoding="utf-8")
    cancel_mod.write_cancel_request(out, _task_id())
    with pytest.raises(fc_mod.RecoveryError, match="RECOVERY_IDENTITY_ERROR"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert "terminal_generation" not in read_status(out)

    # 失败路径 3：force
    out2 = _recovery_ready(tmp_path)
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out2, cancel_mode="force")
    assert "terminal_generation" not in read_status(out2)

    # 修好 evidence 后成功 commit → gen 恰 1；后续失败尝试不 bump
    out3 = _recovery_ready(tmp_path)
    c = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out3)
    assert c.terminal_generation == 1
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out3, cancel_mode="force")
    assert read_status(out3)["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# G. successful recovery → generation 恰 +1（req 12 / req 19-G）
# ---------------------------------------------------------------------------


def test_g_successful_recovery_generation_exactly_plus_one(tmp_path):
    out = _recovery_ready(tmp_path)
    c = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c.preserved is False
    assert c.terminal_generation == 1  # 无历史 generation → 恰一次 bump（1，不是 0/2）
    assert read_status(out)["terminal_generation"] == 1
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["terminal_generation"] == 1

    # 幂等重跑：不 bump
    c2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c2.preserved is True and c2.terminal_generation == 1
    assert read_status(out)["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# H/I. existing terminal 无 evidence 仍 preserve + reconciliation 可用（req 9 / 19-H/I）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal", ["SUCCESS", "WAITING", "FAILED", "CANCELLED"])
def test_h_existing_terminal_no_evidence_preserved(tmp_path, terminal):
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status=terminal, task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    before = read_status(out)
    # 无 cancel.request：已有终态依然 preserve（evidence 只用于“新提交 CANCELLED”）
    c = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c.status == terminal
    assert c.preserved is True
    assert c.terminal_generation == before.get("terminal_generation")
    after = read_status(out)
    assert after["status"] == terminal
    assert after["updated_at"] == before["updated_at"]  # 零写发生（未重新 commit）
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == terminal and run["terminal_generation"] == before.get("terminal_generation")


def test_i_existing_terminal_reconciliation_repairs_missing_derived(tmp_path):
    """req 9/10/14：已有终态、缺派生产物、无 evidence → recovery 不因缺 evidence
    阻断 derived repair：run.json / REPORT.md 被补齐并跟随 canonical。"""
    out = tmp_path / "out"
    finalize_terminal(out, task_id=_task_id(), status="SUCCESS", task_path="T.md",
                      workspace=str(tmp_path), report_path=str(out / "REPORT.md"))
    assert not (out / "run.json").exists()
    assert not (out / "REPORT.md").exists()
    c = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c.status == "SUCCESS" and c.preserved is True
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS" and run["terminal_generation"] == 1
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    assert "## Terminal Generation\n1" in report
    # canonical terminal 未被 reconciliation 修改（req 10）
    data = read_status(out)
    assert data["status"] == "SUCCESS" and data["terminal_generation"] == 1


# ---------------------------------------------------------------------------
# J. force recovery 仍拒绝（req 13 / req 19-J）
# ---------------------------------------------------------------------------


def test_j_force_recovery_refused_any_state(tmp_path):
    # non-terminal + 合法 evidence + force → 拒绝
    out = _recovery_ready(tmp_path)
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable, match="FORCE_RECOVERY_NOT_AVAILABLE"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out, cancel_mode="force")
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable, match="FORCE_RECOVERY_NOT_AVAILABLE"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out, reason="FORCE_CANCELLED")
    data = read_status(out)
    assert data["status"] == "RUNNING" and "terminal_generation" not in data
    assert not (out / "run.json").exists()

    # 已有终态 + force → 同样明确拒绝（不部分处理 force 请求）
    out2 = tmp_path / "out2"
    finalize_terminal(out2, task_id=_task_id(), status="CANCELLED", task_path="T.md",
                      workspace=str(tmp_path))
    with pytest.raises(fc_mod.ForceRecoveryNotAvailable, match="FORCE_RECOVERY_NOT_AVAILABLE"):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out2, cancel_mode="force")
    assert read_status(out2)["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# K. CLI 与 library 同一原子路径（req 12 / req 19-K；无 CLI bypass）
# ---------------------------------------------------------------------------


def test_k_cli_same_semantics_single_lock_path(tmp_path):
    # 有效 evidence → CLI exit 0 → CANCELLED（同一临界区路径）
    out = _recovery_ready(tmp_path)
    proc = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    data = read_status(out)
    assert data["status"] == "CANCELLED" and data["terminal_generation"] == 1

    # 已有终态 + 无 evidence → CLI exit 0（preserve + reconciliation，无 bypass 要求 evidence）
    out2 = tmp_path / "out2"
    finalize_terminal(out2, task_id=_task_id(), status="SUCCESS", task_path="T.md",
                      workspace=str(tmp_path))
    proc2 = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out2))
    assert proc2.returncode == 0, proc2.stderr
    assert read_status(out2)["status"] == "SUCCESS"
    run2 = json.loads((out2 / "run.json").read_text(encoding="utf-8"))
    assert run2["status"] == "SUCCESS"

    # 无 evidence + non-terminal → CLI exit 6（library 同规则）
    out3 = tmp_path / "out3"
    update_status(out3, task_id=_task_id(), status="RUNNING", task_path="T.md",
                  workspace=str(tmp_path))
    proc3 = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out3))
    assert proc3.returncode == fc_mod.EXIT_RECOVERY_ERROR
    assert "RECOVERY_EVIDENCE_ERROR" in proc3.stderr
    assert read_status(out3)["status"] == "RUNNING"


# ---------------------------------------------------------------------------
# L. 强制时序：runtime writer 已启动并等待锁 → terminal 先 commit → late no-op
#    （req 8 / req 19-L；真实 OS 锁 + 子进程 + 握手文件）
# ---------------------------------------------------------------------------

TERMINAL_HOLDER_WORKER = """\
import json, sys, time
from pathlib import Path
from ai_agent_framework.lock_utils import TaskStateLock
from ai_agent_framework.task_lifecycle import _finalize_terminal_locked, read_status

out, tid, ws, t1, go, done, status, cancel_mode = sys.argv[1:9]
Path(t1).write_text("1", encoding="utf-8")
with TaskStateLock(out, tid, timeout=20.0):
    # 等待测试进程确认 runtime writer 已就绪并阻塞在锁上
    deadline = time.monotonic() + 30.0
    while not Path(go).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    prev = read_status(Path(out))
    r = _finalize_terminal_locked(
        Path(out), prev,
        task_id=tid, status=status,
        task_path=str(Path(out) / "TASK.md"), workspace=ws,
        report_path=str(Path(out) / "REPORT.md"),
        terminal_reason=("CANCEL_REQUESTED" if status == "CANCELLED" else None),
        cancel_mode=(cancel_mode or None),
    )
    Path(done).write_text(json.dumps(r.to_dict()), encoding="utf-8")
print("TERMINAL", r.status, r.terminal_generation, r.preserved)
"""

RUNTIME_WAIT_WORKER = """\
import json, sys
from pathlib import Path
from ai_agent_framework.task_lifecycle import update_status

out, tid, ws, r1 = sys.argv[1:5]
Path(r1).write_text("1", encoding="utf-8")
res = update_status(
    Path(out), task_id=tid, status="RUNNING",
    task_path=str(Path(out) / "TASK.md"), workspace=ws,
    stage="HERMES", agent="hermes", lock_timeout=30.0,
)
print("RUNTIME", json.dumps(res.to_dict()))
"""


@pytest.mark.parametrize("terminal", ["CANCELLED", "SUCCESS"])
def test_l_forced_order_runtime_waits_lock_terminal_commits_first(tmp_path, terminal):
    """req 8 / req 19-L 强制时序（真实 OS state.lock + 真实子进程 + 握手文件）：

    1. terminal writer 先持锁（T1 已确认）
    2. runtime writer 启动并写 R1 → 随即阻塞在锁上（此时 terminal 仍持锁，
       故 runtime 必已进入“准备并等待锁”阶段——不是“terminal 先完成再启动 runtime”）
    3. 测试写 GO → terminal writer **持锁 commit** terminal → release
    4. runtime writer 随后获得锁 → **锁内 reload** 看到 terminal → 零写入（preserved）
    5. 最终 canonical = terminal、generation 稳定 = 1
    """
    out = _recovery_ready(tmp_path)
    t1 = tmp_path / f"t1_{terminal}.txt"
    go = tmp_path / f"go_{terminal}.txt"
    done = tmp_path / f"done_{terminal}.txt"
    r1 = tmp_path / f"r1_{terminal}.txt"
    cancel_mode = "soft" if terminal == "CANCELLED" else ""

    p_term = _spawn_worker(tmp_path, TERMINAL_HOLDER_WORKER, str(out), _task_id(),
                           str(tmp_path), str(t1), str(go), str(done), terminal, cancel_mode)
    try:
        _wait_file(t1)  # terminal writer 已持锁
        p_run = _spawn_worker(tmp_path, RUNTIME_WAIT_WORKER, str(out), _task_id(),
                              str(tmp_path), str(r1))
        _wait_file(r1)  # runtime writer 已启动（terminal 仍持锁 → runtime 必在等待锁）
        data = read_status(out)
        assert data["status"] == "RUNNING"  # terminal 尚未提交（等 GO）

        go.write_text("go", encoding="utf-8")  # 放行 terminal：持锁 commit → release
        o_term = _run_worker(p_term)
        assert f"TERMINAL {terminal} 1 False" in o_term

        o_run = _run_worker(p_run)
        res = json.loads(o_run.split("RUNTIME ", 1)[1])
        assert res["preserved"] is True  # late runtime writer 零写入
        assert res["status"] == terminal
        assert res["terminal_generation"] == 1

        data = read_status(out)
        assert data["status"] == terminal
        assert data["terminal_generation"] == 1  # 恰一次 commit，未被 runtime 覆盖
    finally:
        for p in (p_run,):
            if p.poll() is None:
                p.communicate(timeout=90)


# ---------------------------------------------------------------------------
# M/N. 无 force kill / 无第三 terminal writer（req 19-M/N）
# ---------------------------------------------------------------------------

FIX002_FILES = [
    "ai_agent_framework/task_lifecycle.py",
    "ai_agent_framework/finalize_cancelled.py",
    "ai_agent_framework/lock_utils.py",
    "ai_agent_framework/reconcile.py",
]


def test_m_no_force_kill_still_true():
    """req 19-M：FIX-002 修改的 Core 文件不得具备进程控制能力（无 force kill）。"""
    for rel in FIX002_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "from subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "os.kill" not in text, f"{rel} 包含 os.kill"
        assert ".kill(" not in text, f"{rel} 包含 .kill("
        assert ".terminate(" not in text, f"{rel} 包含 .terminate("
        assert "Popen" not in text, f"{rel} 包含 Popen"
        # 无 taskkill 调用形态（docstring 允许提及“不从 Launcher 调用它去 taskkill”，
        # 但不得出现实际调用语法）
        assert "taskkill /" not in text.lower(), f"{rel} 包含 taskkill 调用"
        assert "taskkill.exe" not in text.lower(), f"{rel} 包含 taskkill 调用"


def test_n_no_third_terminal_writer():
    """req 19-N / req 3：task.json 终态写只能出现在 task_lifecycle 的锁内 helper；
    finalize_cancelled 不直接写 task.json（只 validate → delegate → reconcile）。"""
    fc_src = (REPO_ROOT / "ai_agent_framework" / "finalize_cancelled.py").read_text(encoding="utf-8")
    assert "_atomic_write" not in fc_src
    assert "task_json_path(" in fc_src  # 只读路径（identity 校验）允许
    # 终态写点唯一性：所有模块中只有 task_lifecycle._finalize_terminal_locked 原子写 task.json
    for mod in ("cancel.py", "reconcile.py", "runner.py", "lock_utils.py"):
        src = (REPO_ROOT / "ai_agent_framework" / mod).read_text(encoding="utf-8")
        assert "_atomic_write(task_json_path" not in src, f"{mod} 直接写 task.json terminal"


# ---------------------------------------------------------------------------
# 补充并发/锁失败不变量（req 4/16/17）
# ---------------------------------------------------------------------------

RECOVERY_WORKER = """\
import json, sys
from pathlib import Path
from ai_agent_framework import finalize_cancelled
out, tid, ws = sys.argv[1], sys.argv[2], sys.argv[3]
c = finalize_cancelled.finalize_cancelled_task(tid, ws, Path(out))
print("REC", c.status, c.terminal_generation, c.preserved)
"""


def test_recovery_vs_recovery_race_single_commit(tmp_path):
    """两个 recovery finalizer 同时竞争：同一把锁串行化 → 恰一次 CANCELLED commit
    （gen=1），后到者 preserved=True；派生产物跟随 canonical。"""
    out = _recovery_ready(tmp_path)
    p1 = _spawn_worker(tmp_path, RECOVERY_WORKER, str(out), _task_id(), str(tmp_path))
    p2 = _spawn_worker(tmp_path, RECOVERY_WORKER, str(out), _task_id(), str(tmp_path))
    o1 = _run_worker(p1)
    o2 = _run_worker(p2)
    results = o1 + o2
    assert results.count("REC CANCELLED 1") == 2  # 幂等：都返回相同 canonical
    assert "REC CANCELLED 1 True" in results  # 至少一个 preserved（后到者）
    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1  # 恰一次 commit
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1


def test_recovery_lock_timeout_no_write(tmp_path):
    """req 4/16：recovery 取锁失败（超时）→ 不写、不绕过、抛明确 LockTimeout。"""
    out = _recovery_ready(tmp_path)
    ready = tmp_path / "ready.txt"
    proc = _spawn_worker(tmp_path, HOLD_WORKER, str(out), _task_id(), "1.5", str(ready))
    try:
        _wait_file(ready)
        with pytest.raises(LockTimeout):
            fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out, lock_timeout=0.3)
        data = read_status(out)
        assert data["status"] == "RUNNING"
        assert "terminal_generation" not in data
        assert not (out / "run.json").exists()
    finally:
        proc.communicate(timeout=20)


# ---------------------------------------------------------------------------
# 真实 Recovery E2E（req 18）：真实 filesystem + CLI
# ---------------------------------------------------------------------------


def test_e2e_scenario1_valid_request_cli_single_atomic_commit(tmp_path):
    """req 18 Scenario 1：RUNNING canonical + 合法 cancel.request → recovery CLI →
    单次原子 CANCELLED commit → run.json CANCELLED → REPORT CANCELLED（真实 filesystem）。"""
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    (out / "route.json").write_text(json.dumps({"agents": ["hermes"], "reason": "e2e"}), encoding="utf-8")
    (out / "hermes_result.md").write_text("partial work done", encoding="utf-8")

    proc = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out))
    assert proc.returncode == 0, f"recovery CLI 失败: {proc.stdout} {proc.stderr}"

    data = read_status(out)
    assert data["status"] == "CANCELLED"
    assert data["terminal_generation"] == 1
    assert data["cancel_mode"] == "soft"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nCANCELLED" in report
    assert "取消请求时间: 2026-08-27T10:00:00" in report
    assert (out / "hermes_result.md").exists()  # 已完成 artifacts 保留

    # 幂等：重复 CLI 收敛返回相同 canonical（generation 不 bump）
    proc2 = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out))
    assert proc2.returncode == 0
    assert read_status(out)["terminal_generation"] == 1


def test_e2e_scenario2_invalid_request_cli_fails_safely(tmp_path):
    """req 18 Scenario 2：RUNNING canonical + 不匹配 cancel.request → recovery CLI
    失败 → task.json 保持 RUNNING → 无 terminal_generation bump → 无 CANCELLED
    derived artifacts（真实 filesystem）。"""
    out = _recovery_ready(tmp_path)
    (out / "cancel.request").write_text(
        json.dumps({"task_id": "OTHER-TASK", "requested_at": "2026-08-27T10:00:00",
                    "request": "soft_cancel"}), encoding="utf-8")

    proc = _run_cli("--task-id", _task_id(), "--workspace", str(tmp_path), "--output", str(out))
    assert proc.returncode == fc_mod.EXIT_RECOVERY_ERROR
    assert "RECOVERY_EVIDENCE_ERROR" in proc.stderr

    data = read_status(out)
    assert data["status"] == "RUNNING"  # canonical 未变
    assert "terminal_generation" not in data  # 零 generation bump
    assert not (out / "run.json").exists()  # 无 CANCELLED derived artifacts
    assert not (out / "REPORT.md").exists()
