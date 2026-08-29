"""AAF-v0.5-A0-PAID-GUARD-001-FIX-003：一次性授权原子消费回归测试。

Codex BLOCKING（FIX-002 残留）：授权消费是 check-then-consume（TOCTOU）——并发/
重入 admission 可同时观察到“未消费”并都返回 ALLOWED_AUTHORIZED_PAID；
_CONSUMED_AUTHS 无法跨进程协调，普通 write_text 覆盖写没有 exclusive-claim 语义。

FIX-003 修复：_claim_auth 单一原子操作 —— filesystem exclusive-create
（open(..., "x")）为跨进程权威；in-process 集合退化为只拒绝的非权威快路径。

覆盖 Requirement 9 A–F：
A. 线程并发：barrier 同时起跑，同一 auth + 同一 state_dir → 恰好一个 ALLOWED
B. 进程并发：独立 python 进程同一 auth + 同一 state_dir → 恰好一个进程 claim 成功
C. 顺序 replay 仍 blocked（同进程 + marker 已存在的跨进程等价）
D. 不同 Task/model 授权仍 blocked（不消费任何状态）
E. 未匹配授权不消费有效授权（后续正确授权仍可准入）
F. 模拟 marker 创建/持久化错误 → fail closed
G. 既有 endpoint / FREE-bypass 对抗测试继续通过（与 fix002 套件共同证明）
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ai_agent_framework import cost_guard as cg

ROOT = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).resolve().parent / "_auth_claim_worker.py"

MINIMAL_VALID_TASK = """# Task ID
T-EXEC

# Task Name
执行链测试

# Objective
实现功能并验收

# Acceptance
1. 通过
"""


def _paid_resolution(model="deepseek-v4-flash", provider="deepseek", base_url=None):
    return {
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "model_source": cg.MODEL_SOURCE_ENV,
        "notes": ["test paid resolution"],
    }


# ---------------------------------------------------------------------------
# A. 线程并发（同一 auth + 同一 state_dir，barrier 起跑）
# ---------------------------------------------------------------------------


def test_thread_concurrency_exactly_one_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    n = 8
    barrier = threading.Barrier(n)
    decisions: list[str] = []
    consumed_flags: list[bool] = []
    errors: list[str] = []
    guard = threading.Lock()

    def worker():
        barrier.wait()
        try:
            rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
        except Exception as exc:  # noqa: BLE001 — 线程内异常要收集而不是静默
            with guard:
                errors.append(f"{type(exc).__name__}: {exc}")
            return
        with guard:
            decisions.append(rec["decision"])
            consumed_flags.append(rec["authorization_consumed"])

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    assert len(decisions) == n
    assert decisions.count(cg.DECISION_ALLOWED_AUTHORIZED_PAID) == 1, decisions
    assert decisions.count(cg.DECISION_BLOCKED_COST_APPROVAL) == n - 1, decisions
    winner_idx = decisions.index(cg.DECISION_ALLOWED_AUTHORIZED_PAID)
    assert consumed_flags[winner_idx] is True
    for i in range(n):
        if i != winner_idx:
            assert consumed_flags[i] is True, "losers must observe consumed state"
    assert (tmp_path / cg.CONSUMPTION_FILENAME).exists()


def test_thread_concurrency_state_dir_none_zero_winners(monkeypatch):
    """FIX-005（FIX-004 re-issue）：state_dir=None + matched paid auth → 零 winner。

    原 FIX-003 语义（state_dir=None 时 in-process 集合可放行 1 个 winner）已被
    移除：没有持久化 filesystem exclusive-create 权威，任何线程/进程都不得
    ALLOWED_AUTHORIZED_PAID（fail closed）。
    """
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    n = 8
    barrier = threading.Barrier(n)
    decisions: list[str] = []
    consumed_flags: list[bool] = []
    errors: list[str] = []
    guard = threading.Lock()

    def worker():
        barrier.wait()
        try:
            rec = cg.evaluate("T1", "hermes")  # state_dir=None
        except Exception as exc:  # noqa: BLE001 — 线程内异常要收集而不是静默
            with guard:
                errors.append(f"{type(exc).__name__}: {exc}")
            return
        with guard:
            decisions.append(rec["decision"])
            consumed_flags.append(rec["authorization_consumed"])

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    assert len(decisions) == n
    assert decisions.count(cg.DECISION_ALLOWED_AUTHORIZED_PAID) == 0, decisions
    assert decisions.count(cg.DECISION_BLOCKED_COST_APPROVAL) == n, decisions
    assert not any(consumed_flags), "nothing was persisted — nothing may be consumed"


# ---------------------------------------------------------------------------
# B. 进程并发（独立 python 进程，同一 auth + 同一 state_dir）
# ---------------------------------------------------------------------------


def test_process_concurrency_exactly_one_allowed(tmp_path, monkeypatch):
    """跨进程权威：恰好一个进程赢得 exclusive-create claim，其余全部 blocked。"""
    monkeypatch.setenv(cg.ENV_MODEL, "deepseek-v4-flash")
    monkeypatch.setenv(cg.ENV_PROVIDER, "deepseek")
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    state_dir = tmp_path / "shared"
    state_dir.mkdir()

    n = 6
    procs = [
        subprocess.Popen(
            [sys.executable, "-u", str(WORKER), str(state_dir), "T1"],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(n)
    ]
    winners, losers = 0, 0
    for p in procs:
        out, err = p.communicate(timeout=180)
        assert p.returncode in (0, 3), (
            f"worker unexpected rc={p.returncode} out={out!r} err={err!r}"
        )
        if p.returncode == 0:
            winners += 1
        else:
            losers += 1

    assert winners == 1, f"expected exactly 1 winning process, got {winners}"
    assert losers == n - 1, f"expected {n - 1} blocked processes, got {losers}"

    marker = state_dir / cg.CONSUMPTION_FILENAME
    assert marker.exists()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["consumed_auth_fingerprint"] == cg._auth_fingerprint(
        "T1|hermes|deepseek-v4-flash|deepseek"
    )

    # 跨进程 replay：再起一个 fresh 进程（新内存）→ 必须 blocked（持久化权威）
    p = subprocess.run(
        [sys.executable, "-u", str(WORKER), str(state_dir), "T1"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert p.returncode == 3, f"replay process must be blocked, rc={p.returncode} {p.stdout!r}"


# ---------------------------------------------------------------------------
# C. 顺序 replay 仍 blocked
# ---------------------------------------------------------------------------


def test_sequential_replay_blocked_same_and_fresh_authority(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    r1 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r1["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    r2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert r2["authorization_consumed"] is True
    cg._CONSUMED_AUTHS.clear()  # fresh process 等价（仅剩磁盘 marker）
    r3 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r3["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert r3["authorization_consumed"] is True


def test_claim_auth_atomic_semantics_at_function_level(tmp_path):
    ok1, err1 = cg._claim_auth("T1|hermes|m|p", "T1|hermes|m|p", tmp_path)
    assert ok1 is True and err1 == ""
    ok2, err2 = cg._claim_auth("T1|hermes|m|p", "T1|hermes|m|p", tmp_path)
    assert ok2 is False
    assert "consumed" in err2
    assert (tmp_path / cg.CONSUMPTION_FILENAME).exists()


def test_consume_auth_alias_delegates_to_atomic_claim(tmp_path):
    ok, err = cg._consume_auth("auth-x", "scope-x", tmp_path)
    assert ok is True and err == ""
    ok2, err2 = cg._consume_auth("auth-x", "scope-x", tmp_path)
    assert ok2 is False and "consumed" in err2


def test_runner_replay_with_claimed_marker_never_spawns(tmp_path, monkeypatch):
    """marker 已被 claim → runner 内 Hermes stage 被阻断 → run_agent 零调用
    （loser/replay 不越过 Hermes invocation 边界）。"""
    from ai_agent_framework import runner as runner_mod

    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T-EXEC|hermes|deepseek-v4-flash|deepseek")

    task_file = tmp_path / "TASK.md"
    task_file.write_text(MINIMAL_VALID_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    # 预置已消费 marker：模拟并发中已有一个 admission 赢得了 claim
    ok, err = cg._claim_auth(
        "T-EXEC|hermes|deepseek-v4-flash|deepseek",
        "T-EXEC|hermes|deepseek-v4-flash|deepseek",
        out,
    )
    assert ok is True and err == ""

    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding="utf-8")
    assert calls == []  # Hermes subprocess 未被创建
    assert "## Current Status\nWAITING" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert guard["authorization_consumed"] is True
    assert (out / "hermes_result.md").read_text(encoding="utf-8").startswith(
        "FRAMEWORK_ERROR\nCOST_APPROVAL_REQUIRED"
    )


# ---------------------------------------------------------------------------
# D. 不同 Task/model 授权仍 blocked（不消费）
# ---------------------------------------------------------------------------


def test_different_task_or_model_auth_blocked_not_consumed(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    for bad in (
        "T2|hermes|deepseek-v4-flash|deepseek",
        "T1|hermes|other-model|deepseek",
    ):
        monkeypatch.setenv(cg.ENV_AUTH, bad)
        rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
        assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL, bad
        assert rec["authorization_matched"] is False, bad
        assert rec["authorization_consumed"] is False, bad
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()  # 未消费 → 无 marker
    # 正确授权随后仍可准入（没有误锁）
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID


# ---------------------------------------------------------------------------
# E. 未匹配授权不消费有效授权
# ---------------------------------------------------------------------------


def test_unmatched_auth_does_not_consume_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "OTHER|hermes|deepseek-v4-flash|deepseek")
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec2["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID


# ---------------------------------------------------------------------------
# F. 模拟 marker 创建/持久化错误 → fail closed
# ---------------------------------------------------------------------------


def test_marker_path_occupied_by_directory_fails_closed(monkeypatch, tmp_path):
    """marker 路径被目录占用 → claim 不可能 → fail closed（视为已消费）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    (tmp_path / cg.CONSUMPTION_FILENAME).mkdir()
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is True  # 状态不确定 → fail closed


def test_state_dir_is_file_fails_closed(monkeypatch, tmp_path):
    """state_dir 本身是文件 → marker 无法建立 → 持久化失败 → fail closed。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    state_dir = tmp_path / "afile"
    state_dir.write_text("x")
    rec = cg.evaluate("T1", "hermes", state_dir=state_dir)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("persist" in n for n in rec["notes"])


# ---------------------------------------------------------------------------
# 消费记录内容（Codex 非阻塞警告收口）+ 旧格式兼容
# ---------------------------------------------------------------------------


def test_marker_payload_has_fingerprint_not_raw_auth(monkeypatch, tmp_path):
    """消费记录不落盘授权原文（仅 sha256 指纹 + scope 即可做等值判定）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    cg.evaluate("T1", "hermes", state_dir=tmp_path)
    data = json.loads(
        (tmp_path / cg.CONSUMPTION_FILENAME).read_text(encoding="utf-8")
    )
    assert "consumed_auth" not in data
    assert data["consumed_auth_fingerprint"] == cg._auth_fingerprint(
        "T1|hermes|deepseek-v4-flash|deepseek"
    )
    assert data["scope"] == "T1|hermes|deepseek-v4-flash|deepseek"
    assert data["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID


def test_legacy_marker_format_still_blocks_replay(monkeypatch, tmp_path):
    """FIX-002 旧格式 marker（含 consumed_auth 原文）→ 新代码仍拒绝 replay（fail closed）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    legacy = {
        "schema_version": 1,
        "decision": cg.DECISION_ALLOWED_AUTHORIZED_PAID,
        "scope": "T1|hermes|deepseek-v4-flash|deepseek",
        "consumed_auth_fingerprint": cg._auth_fingerprint(
            "T1|hermes|deepseek-v4-flash|deepseek"
        ),
        "consumed_auth": "T1|hermes|deepseek-v4-flash|deepseek",
        "consumed_at": "2026-08-29T00:00:00",
    }
    (tmp_path / cg.CONSUMPTION_FILENAME).write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is True
