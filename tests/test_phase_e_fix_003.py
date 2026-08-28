"""Phase E FIX-003（AAF-v0.4-TASK-005-A-FIX-003）Cancel Request Lock Serialization 测试。

关闭 Codex 复审遗留两个 blocking：

1. **evidence replacement race（Blocking 1）**：cancel.request 的官方 mutation
   （write / consume）不使用 state.lock，recovery 锁内验证的 evidence 仍可在
   commit 前被另一个 Framework writer 替换 / 删除 / consume。
   → FIX-003：write_cancel_request / consume_cancel_request 与 terminal writers
   共享同一 per-task state.lock（lock_utils.task_state_lock，§6B.1）。

2. **forced-order 握手错误（Blocking 2）**：旧 t1 在 acquire 前发出，不能证明
   terminal writer 已持锁。
   → FIX-003：重写 tests/test_phase_e_fix_002.py::test_l —— T_LOCKED 只在成功
   acquire 后发出；R_STARTED 在 runtime 取锁前发出；R_DONE 缺失 + 进程存活 +
   显式超时断言证明 runtime 真正等待锁（本文件不重复，req 24 J–N 由该测试覆盖）。

本文件覆盖（req 24 A–R + req 25 真实 race E2E）：

  A  write_cancel_request 使用 state.lock（静态 + 行为）
  B  consume_cancel_request 使用 state.lock（静态 + 行为）
  C  writer 在 recovery 持锁期间阻塞（真实双进程）
  D  consumer 在 recovery 持锁期间阻塞（真实双进程）
  E  request mutation 不能在 recovery commit 前完成（真实 race E2E）
  F  commit 后的 request mutation 不能改 terminal
  G  lock timeout → 不写 / 不 consume / 不 fallback（显式 LockTimeout）
  H  consume 在锁协议下幂等
  I  无未加锁的官方 cancel.request mutation 路径（静态 + 行为）
  J–N  forced-order（T_LOCKED 在 acquire 后 / runtime 确认等待 / terminal 先
      commit / CANCELLED 保留 / SUCCESS 可选）→ tests/test_phase_e_fix_002.py::test_l
  O–P  既有 recovery TOCTOU / E2E 不回归 → 全量套件
  Q  无 force kill（静态）
  R  无第三 terminal writer（静态；cancel.py 不写 task.json）
  req 8  身份护栏：canonical task_id mismatch → 拒绝写入；无 canonical → 兼容
  req 14 invalid-before-lock → 拒绝、无 CANCELLED、generation 不变
  req 15 mutation-after-terminal → canonical 不可变
  req 25 真实 evidence-mutation race E2E（replace + consume 两变体）：
         Recovery 持锁 → 验证 evidence → 暂停；官方 mutation 进程 → 阻塞；
         放行 → Recovery commit CANCELLED → release → 后者才完成；
         最终 task.json=CANCELLED、generation 稳定、run.json/REPORT 跟随 canonical

全部使用真实 OS state.lock（msvcrt/flock）+ 真实 filesystem + 真实子进程，
不 mock 锁（req 11）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import finalize_cancelled as fc_mod
from ai_agent_framework import reconcile as rec_mod
from ai_agent_framework import runner as runner_mod
from ai_agent_framework import task_lifecycle
from ai_agent_framework.lock_utils import LockTimeout
from ai_agent_framework.task_lifecycle import read_status, update_status

REPO_ROOT = Path(__file__).resolve().parent.parent

FIX003_TASK_ID = "T-FIX-003"


def _task_id() -> str:
    return FIX003_TASK_ID


def _recovery_ready(tmp_path: Path, task_id: str | None = None, requested_at: str | None = None) -> Path:
    """recovery 前置：RUNNING canonical + 合法 cancel.request（真实 crash 现场）。"""
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


# ---------------------------------------------------------------------------
# A/B. write_cancel_request / consume_cancel_request 使用同一 per-task state.lock
#      （req 1/3/4/7 静态契约 + req 24 A/B）
# ---------------------------------------------------------------------------


def test_static_write_cancel_request_uses_state_lock():
    """req 1/3/7：write_cancel_request 公共 API 必须 acquire 同一 per-task
    state.lock → 委托锁内 helper（不复制第二套写语义）；锁内 helper 不得自行
    acquire 锁（no nested reentry）；公共 API 不捕获锁异常（显式错误，无 fallback）。"""
    src = (REPO_ROOT / "ai_agent_framework" / "cancel.py").read_text(encoding="utf-8")
    pub = src[src.index("def write_cancel_request("):src.index("def _write_cancel_request_locked(")]
    assert "task_state_lock(" in pub, "write_cancel_request 必须使用同一 per-task state.lock"
    assert "_write_cancel_request_locked(" in pub, "write_cancel_request 必须委托锁内 helper"
    assert "except Lock" not in pub, "锁失败必须显式抛出（LockTimeout/LockError），不得吞掉或 fallback"

    locked = src[src.index("def _write_cancel_request_locked("):src.index("def inspect_cancel_request(")]
    assert "task_state_lock(" not in locked, "锁内 helper 不得自行 acquire 锁（调用方已持锁）"
    assert "os.replace(tmp, path)" in locked, "原子写（tmp + os.replace）必须在锁内 helper"


def test_static_consume_cancel_request_uses_state_lock():
    """req 4/9：consume_cancel_request 同样 acquire state.lock → 委托锁内 helper；
    存在判断 + rename 同属一个锁临界区。"""
    src = (REPO_ROOT / "ai_agent_framework" / "cancel.py").read_text(encoding="utf-8")
    pub = src[src.index("def consume_cancel_request("):src.index("def _consume_cancel_request_locked(")]
    assert "task_state_lock(" in pub, "consume_cancel_request 必须使用同一 per-task state.lock"
    assert "_consume_cancel_request_locked(" in pub, "consume_cancel_request 必须委托锁内 helper"
    assert "except Lock" not in pub, "锁失败必须显式抛出，不得 fallback 无锁 rename"

    locked = src[src.index("def _consume_cancel_request_locked("):]
    assert "task_state_lock(" not in locked, "锁内 helper 不得自行 acquire 锁"
    assert "os.replace(path, done)" in locked, "rename 到 cancel.done 必须在锁内 helper"
    assert "path.exists()" in locked, "存在判断必须在同一锁临界区内（req 9）"


def test_static_no_unlocked_official_mutation_path():
    """req 5 / req 24-I：cancel.request 的官方 mutation 只存在于 cancel.py 的
    两个锁内 helper（write tmp+replace / consume rename）；无 unlink/remove/rename
    官方删除路径；其他 Framework 模块不得以文件操作直接指向 request 路径。"""
    cancel_src = (REPO_ROOT / "ai_agent_framework" / "cancel.py").read_text(encoding="utf-8")
    assert cancel_src.count("os.replace(") == 2, "cancel.py 恰两个 mutation 点（写 + consume）"
    assert "os.remove(" not in cancel_src and "os.rename(" not in cancel_src
    assert "unlink" not in cancel_src, "官方路径不得 unlink cancel.request（删除证据）"

    # 其他 Core 模块：不得直接文件操作 request 路径 / 引用 request 文件名常量
    for rel in ["runner.py", "reconcile.py", "finalize_cancelled.py", "task_lifecycle.py", "lock_utils.py"]:
        text = (REPO_ROOT / "ai_agent_framework" / rel).read_text(encoding="utf-8")
        assert "cancel_request_path(" not in text, f"{rel} 不得直接操作 cancel.request 路径"
        assert "CANCEL_REQUEST_FILENAME" not in text, f"{rel} 不得引用 request 文件名常量"
        for m in re.finditer(r"os\.(replace|remove|rename)\(([^)]*)\)", text):
            assert "request" not in m.group(2), f"{rel} 对 cancel.request 的未授权 mutation: {m.group(0)}"
        for m in re.finditer(r"\.unlink\(([^)]*)\)", text):
            assert "request" not in m.group(1), f"{rel} 对 cancel.request 的未授权删除: {m.group(0)}"


def test_behavior_no_other_core_path_mutates_request(tmp_path):
    """req 24-I 行为证明：runner 检查点与 reconciliation 对 cancel.request 只读
    （不 consume / 不删除 / 不改写）；recovery 同样保留证据。"""
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    before = (out / "cancel.request").read_bytes()
    # runner 检查点：读到有效请求 → 收敛（finalize_terminal + reconcile），但 request 保留为证据
    assert runner_mod._check_cancel(out, _task_id(), tmp_path / "TASK.md", tmp_path) is True
    assert (out / "cancel.request").read_bytes() == before
    assert (out / "cancel.request").exists()  # runner 不 consume
    assert not (out / "cancel.done").exists()
    # 已有终态 → recovery 保留证据（不 consume / 不改写）
    c = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c.status == "CANCELLED" and c.preserved is True
    assert (out / "cancel.request").read_bytes() == before
    # reconciliation 幂等重跑：request 不变
    rec_mod.reconcile_terminal_artifacts(_task_id(), str(tmp_path), out)
    assert (out / "cancel.request").read_bytes() == before


# ---------------------------------------------------------------------------
# C/D/G. writer / consumer 在锁被其他进程持有时阻塞；timeout → 不 mutation
#        （req 3/4/18 + req 24 C/D/G）
# ---------------------------------------------------------------------------

HOLD_WORKER = """\
import sys, time
from pathlib import Path
from ai_agent_framework.lock_utils import TaskStateLock

out, tid, hold, ready = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
with TaskStateLock(out, tid, timeout=10.0):
    # ready 只在成功 acquire 后发出（与 FIX-003 握手原则一致：post-lock 信号）
    Path(ready).write_text("ready", encoding="utf-8")
    time.sleep(hold)
print("RELEASED")
"""


def test_writer_blocks_while_lock_held_timeout_no_write(tmp_path):
    """req 18 / req 24 C+G：另一进程持有 state.lock 时，官方 write_cancel_request
    必须阻塞；timeout → 显式 LockTimeout，不写 request、不 fallback 无锁写。
    锁释放后正常写入。"""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    ready = tmp_path / "ready.txt"
    proc = _spawn_worker(tmp_path, HOLD_WORKER, str(out), _task_id(), "1.5", str(ready))
    try:
        _wait_file(ready)  # ready 由持锁者发出 → 锁确已持有
        with pytest.raises(LockTimeout):
            cancel_mod.write_cancel_request(out, _task_id(), lock_timeout=0.3)
        assert not (out / "cancel.request").exists(), "锁失败不得写 request"
        assert not list(out.glob("*.request.tmp")), "锁失败不得残留 tmp"
        assert not (out / "cancel.done").exists()
    finally:
        proc.communicate(timeout=20)
    # release 后正常写（不 fallback 无锁写；锁协议生效后写成功）
    p = cancel_mod.write_cancel_request(out, _task_id())
    assert p == out / "cancel.request"
    assert cancel_mod.read_cancel_request(out) is not None


def test_consumer_blocks_while_lock_held_timeout_no_consume(tmp_path):
    """req 18 / req 24 D+G：另一进程持有 state.lock 时，官方 consume_cancel_request
    必须阻塞；timeout → 显式 LockTimeout，不 consume、不 fallback 无锁 rename。
    锁释放后 consume 成功。"""
    out = _recovery_ready(tmp_path)  # RUNNING canonical + 合法 cancel.request
    ready = tmp_path / "ready.txt"
    proc = _spawn_worker(tmp_path, HOLD_WORKER, str(out), _task_id(), "1.5", str(ready))
    try:
        _wait_file(ready)
        with pytest.raises(LockTimeout):
            cancel_mod.consume_cancel_request(out, _task_id(), lock_timeout=0.3)
        assert (out / "cancel.request").exists(), "锁失败不得 consume request"
        assert not (out / "cancel.done").exists(), "锁失败不得 rename 到 cancel.done"
    finally:
        proc.communicate(timeout=20)
    assert cancel_mod.consume_cancel_request(out, _task_id()) is True
    assert not (out / "cancel.request").exists()
    assert (out / "cancel.done").exists()


def test_consume_idempotent_under_lock(tmp_path):
    """req 9 / req 24 H：consume 在锁协议下保持幂等——
    no request → False；成功 → True；重复 → False。"""
    out = tmp_path / "out"
    cancel_mod.write_cancel_request(out, _task_id())
    assert cancel_mod.consume_cancel_request(out, _task_id()) is True
    assert not (out / "cancel.request").exists()
    assert (out / "cancel.done").exists()  # 改名保留证据（§6.6）
    assert cancel_mod.consume_cancel_request(out, _task_id()) is False  # 幂等
    assert cancel_mod.consume_cancel_request(out) is False  # 无 task_id 同样幂等


# ---------------------------------------------------------------------------
# req 8. 身份护栏：canonical task_id mismatch → 拒绝写入；无 canonical → 兼容
# ---------------------------------------------------------------------------


def test_write_identity_guard_canonical_mismatch_rejected(tmp_path):
    """req 8 / req 24（req 8 专项）：canonical task.json 已存在且 task_id 不匹配 →
    write_cancel_request 拒绝（显式 CancelRequestIdentityError），不写文件；
    匹配 → 写入；无 canonical（legacy / 新目录）→ 兼容写入（不破坏既有契约）。"""
    out = tmp_path / "out"
    update_status(out, task_id="TASK-A", status="RUNNING",
                  task_path="T.md", workspace=str(tmp_path))
    with pytest.raises(cancel_mod.CancelRequestIdentityError, match="CANCEL_REQUEST_IDENTITY_ERROR"):
        cancel_mod.write_cancel_request(out, "TASK-B")
    assert not (out / "cancel.request").exists(), "mismatch 写入必须被拒绝"

    p = cancel_mod.write_cancel_request(out, "TASK-A")
    assert p.exists()
    req = cancel_mod.read_cancel_request(out)
    assert req is not None and req.task_id == "TASK-A"

    # legacy / 无 canonical：兼容写入（request 只是外部意图）
    out2 = tmp_path / "out2"
    p2 = cancel_mod.write_cancel_request(out2, "ANY-TASK")
    assert p2.exists()
    req2 = cancel_mod.read_cancel_request(out2)
    assert req2 is not None and req2.task_id == "ANY-TASK"


# ---------------------------------------------------------------------------
# req 14 / req 15 / req 24 F. invalid-before-lock 拒绝；mutation-after-terminal 不可变
# ---------------------------------------------------------------------------


def test_invalid_before_lock_rejected_no_generation_change(tmp_path):
    """req 14：request 在 recovery 获取 state.lock 前已损坏 → 锁内重新验证 →
    拒绝、无 CANCELLED、generation 不变（真实锁 + 真实文件）。"""
    out = _recovery_ready(tmp_path)
    (out / "cancel.request").write_text("{broken json", encoding="utf-8")
    with pytest.raises(fc_mod.RecoveryEvidenceError):
        fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    data = read_status(out)
    assert data["status"] == "RUNNING"
    assert "terminal_generation" not in data  # generation 不变
    assert not (out / "run.json").exists()
    assert not (out / "REPORT.md").exists()


def test_mutation_after_terminal_terminal_immutable(tmp_path):
    """req 15 / req 24 F：recovery commit CANCELLED → release → 官方 writer 替换
    （matching task_id，新时间戳）→ 官方 consumer consume → canonical 仍 CANCELLED、
    generation 不变；后续 request 变化无 terminal authority。"""
    out = _recovery_ready(tmp_path)
    c1 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c1.status == "CANCELLED" and c1.terminal_generation == 1

    # commit 后官方 writer 替换 request（matching task_id，允许写入）
    cancel_mod.write_cancel_request(out, _task_id(), requested_at="2026-08-27T23:00:00")
    # commit 后官方 consumer consume request
    assert cancel_mod.consume_cancel_request(out, _task_id()) is True

    data = read_status(out)
    assert data["status"] == "CANCELLED"  # request 后续变化不能改 terminal
    assert data["terminal_generation"] == 1
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1
    c2 = fc_mod.finalize_cancelled_task(_task_id(), str(tmp_path), out)
    assert c2.preserved is True and c2.terminal_generation == 1


# ---------------------------------------------------------------------------
# req 11/12/13/25. 真实 evidence-mutation race E2E（真实 OS 锁 + 真实子进程 + 握手）
# ---------------------------------------------------------------------------

RECOVERY_PAUSE_WORKER = """\
import sys, time
from pathlib import Path
import ai_agent_framework.finalize_cancelled as fc_mod

out, tid, ws, ev, go = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
orig = fc_mod._validate_recovery_evidence

def paused(output_dir, task_id, cancel_mode, reason, force_evidence=None, workspace=None):
    # 锁内验证当前 evidence（有效）→ commit 前暂停：信号 EV_VALIDATED 并等待 GO。
    # 全程仍持有 state.lock（验证与 commit 之间不 release —— FIX-002 单一临界区）。
    orig(output_dir, task_id, cancel_mode, reason, force_evidence=force_evidence,
         workspace=workspace)
    Path(ev).write_text("1", encoding="utf-8")
    deadline = time.monotonic() + 60.0
    while not Path(go).exists() and time.monotonic() < deadline:
        time.sleep(0.02)

fc_mod._validate_recovery_evidence = paused
c = fc_mod.finalize_cancelled_task(tid, ws, Path(out))
print("RECOVERY", c.status, c.terminal_generation, c.preserved)
"""

WRITE_BLOCKED_WORKER = """\
import sys
from pathlib import Path
from ai_agent_framework import cancel as cancel_mod

out, tid, started, done = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
Path(started).write_text("1", encoding="utf-8")
try:
    p = cancel_mod.write_cancel_request(Path(out), tid,
                                        requested_at="2026-08-27T23:59:59",
                                        lock_timeout=60.0)
    Path(done).write_text("OK " + str(p), encoding="utf-8")
    print("WRITER DONE")
except Exception as exc:
    Path(done).write_text("ERR " + type(exc).__name__, encoding="utf-8")
    print("WRITER ERR", type(exc).__name__, exc)
    raise SystemExit(1)
"""

CONSUME_BLOCKED_WORKER = """\
import sys
from pathlib import Path
from ai_agent_framework import cancel as cancel_mod

out, tid, started, done = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
Path(started).write_text("1", encoding="utf-8")
try:
    ok = cancel_mod.consume_cancel_request(Path(out), tid, lock_timeout=60.0)
    Path(done).write_text("OK " + str(ok), encoding="utf-8")
    print("CONSUMER DONE", ok)
except Exception as exc:
    Path(done).write_text("ERR " + type(exc).__name__, encoding="utf-8")
    print("CONSUMER ERR", type(exc).__name__, exc)
    raise SystemExit(1)
"""


def test_e2e_evidence_race_replacement_blocks_until_recovery_commit(tmp_path):
    """req 11/12/25（replace 变体，真实双进程）：
    Recovery A 持 state.lock → 锁内验证 evidence → commit 前暂停；
    Writer B（官方 write_cancel_request，新时间戳替换）发起 → 阻塞在锁上
    （不能完成替换 / 不能删除证据）；
    放行 A → A 用其临界区内有效的 evidence 提交 CANCELLED → release；
    B 随后才完成替换；B 的替换不能改 terminal。
    最终：task.json=CANCELLED、terminal_generation 稳定=1、
    run.json / REPORT 跟随 canonical。"""
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    ev = tmp_path / "ev_validated.txt"
    go = tmp_path / "go.txt"
    b_started = tmp_path / "b_started.txt"
    b_done = tmp_path / "b_done.txt"
    p_rec = _spawn_worker(tmp_path, RECOVERY_PAUSE_WORKER, str(out), _task_id(),
                          str(tmp_path), str(ev), str(go))
    try:
        _wait_file(ev)  # A 已持锁并验证 evidence（commit 前暂停，仍持锁）
        p_b = _spawn_worker(tmp_path, WRITE_BLOCKED_WORKER, str(out), _task_id(),
                            str(b_started), str(b_done))
        _wait_file(b_started)  # B 已发起官方 write_cancel_request
        # B 不能在 A release 前完成 mutation（真实阻塞证明）
        assert not b_done.exists(), "B 不应在 recovery release 前完成替换"
        assert p_b.poll() is None, "B 进程不应在 recovery release 前退出"
        time.sleep(0.5)  # 显式超时断言：B 持续阻塞在 state.lock
        assert not b_done.exists(), "B 必须持续阻塞在 state.lock 上（recovery 未 release）"
        # A 持锁期间：canonical 未 commit；evidence 仍是 A 验证的内容（未被替换/消费）
        data = read_status(out)
        assert data["status"] == "RUNNING"
        req, _ = cancel_mod.inspect_cancel_request(out)
        assert req is not None and req.task_id == _task_id()
        assert req.requested_at == "2026-08-27T10:00:00"

        go.write_text("go", encoding="utf-8")  # 放行 A：commit CANCELLED → release
        o_rec = _run_worker(p_rec)
        assert "RECOVERY CANCELLED 1 False" in o_rec  # A 用临界区内有效 evidence 提交
        o_b = _run_worker(p_b)  # 只有 A release 后 B 才能完成
        assert "WRITER DONE" in o_b
        assert b_done.exists()

        data = read_status(out)
        assert data["status"] == "CANCELLED"  # B 的后续替换不能改 terminal
        assert data["terminal_generation"] == 1
        req2, _ = cancel_mod.inspect_cancel_request(out)
        assert req2 is not None and req2.task_id == _task_id()
        assert req2.requested_at == "2026-08-27T23:59:59"  # B 的替换在 A release 后才落盘
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        assert "## Current Status\nCANCELLED" in report
    finally:
        for p in (p_rec,):
            if p.poll() is None:
                p.communicate(timeout=60)


def test_e2e_evidence_race_consume_blocks_until_recovery_commit(tmp_path):
    """req 11/13/25（consume 变体，真实双进程）：
    Recovery A 持锁 → 验证 evidence → 暂停；Consumer B（官方 consume）发起 →
    阻塞（不能在 A 验证/commit 期间静默移除证据）；
    放行 A → A 提交 CANCELLED（验证时 request 仍存在）→ release；
    B 随后才 consume（request → cancel.done）。
    最终：task.json=CANCELLED、generation 稳定=1、run.json / REPORT 跟随 canonical。"""
    out = _recovery_ready(tmp_path, requested_at="2026-08-27T10:00:00")
    ev = tmp_path / "ev_validated_consume.txt"
    go = tmp_path / "go_consume.txt"
    b_started = tmp_path / "b_started_consume.txt"
    b_done = tmp_path / "b_done_consume.txt"
    p_rec = _spawn_worker(tmp_path, RECOVERY_PAUSE_WORKER, str(out), _task_id(),
                          str(tmp_path), str(ev), str(go))
    try:
        _wait_file(ev)
        p_b = _spawn_worker(tmp_path, CONSUME_BLOCKED_WORKER, str(out), _task_id(),
                            str(b_started), str(b_done))
        _wait_file(b_started)
        assert not b_done.exists(), "B 不应在 recovery release 前完成 consume"
        assert p_b.poll() is None, "B 进程不应在 recovery release 前退出"
        time.sleep(0.5)  # 显式超时断言：B 持续阻塞
        assert not b_done.exists(), "B 必须持续阻塞在 state.lock 上（recovery 未 release）"
        # A 持锁期间：evidence 仍存在（B 无法 consume）——A 验证的就是当前 request
        assert (out / "cancel.request").exists()
        assert not (out / "cancel.done").exists()

        go.write_text("go", encoding="utf-8")
        o_rec = _run_worker(p_rec)
        assert "RECOVERY CANCELLED 1 False" in o_rec
        o_b = _run_worker(p_b)
        assert "CONSUMER DONE True" in o_b
        assert b_done.exists()
        # B 的 consume 在 A release 后才完成：request → cancel.done（证据保留）
        assert not (out / "cancel.request").exists()
        assert (out / "cancel.done").exists()

        data = read_status(out)
        assert data["status"] == "CANCELLED"  # consume 不能改 terminal
        assert data["terminal_generation"] == 1
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert run["status"] == "CANCELLED" and run["terminal_generation"] == 1
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        assert "## Current Status\nCANCELLED" in report
    finally:
        for p in (p_rec,):
            if p.poll() is None:
                p.communicate(timeout=60)


# ---------------------------------------------------------------------------
# Q/R. 无 force kill / 无第三 terminal writer（req 21/22/23 + req 24 Q/R）
# ---------------------------------------------------------------------------


def test_static_no_force_kill():
    """req 24-Q：FIX-003 修改的文件（cancel.py / lock_utils.py）不得具备进程控制能力。"""
    for rel in ("ai_agent_framework/cancel.py", "ai_agent_framework/lock_utils.py"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "import subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "from subprocess" not in text, f"{rel} 不应 import subprocess"
        assert "os.kill" not in text, f"{rel} 包含 os.kill"
        assert ".kill(" not in text, f"{rel} 包含 .kill("
        assert ".terminate(" not in text, f"{rel} 包含 .terminate("
        assert "Popen" not in text, f"{rel} 包含 Popen"


def test_static_no_third_terminal_writer():
    """req 24-R / req 21：cancel.py 不得写 task.json terminal / 不得 bump
    terminal_generation / 不得出现 terminal authority 字段——锁序列化 ≠ terminal authority。
    （request schema 只含 task_id/requested_at/request 的行为证明见
    tests/test_phase_e_core.py::test_w_cancel_request_is_not_terminal_authority）"""
    src = (REPO_ROOT / "ai_agent_framework" / "cancel.py").read_text(encoding="utf-8")
    assert "_atomic_write(task_json_path" not in src
    assert "task_json_path(" not in src, "cancel.py 连 task.json 写路径都不应引用"
    # 代码区（dataclass 起）不含 terminal authority 字段（顶部 docstring 说明“不得包含”
    # 属文档语义，不在断言范围）
    code = src[src.index("@dataclass"):]
    assert "terminal_generation" not in code, "request schema 不含 terminal authority 字段"
    assert "to_dict" in code and '"status"' not in code, "request 写路径不得引入 status 字段"
