"""AAF-v0.5-A0-PAID-GUARD-001-FIX-005：paid authorization 无持久化 state 权威 → fail closed。

背景（Codex FIX-003 review BLOCKING，FIX-004 被 guard 阻断未执行，FIX-005 以新
Task ID 重发同一 repair scope）：``evaluate()`` 在 ``state_dir=None`` 时仍可用
进程内 ``_CONSUMED_AUTHS`` 放行 matched paid authorization —— 两个独立进程各自
``evaluate(..., state_dir=None)`` 都能返回 ALLOWED_AUTHORIZED_PAID，违反
Requirement 3/5（持久化 filesystem exclusive-create 才是跨进程权威）。

FIX-005 修复（FIX-004 re-issue，同 scope）：
- ``_claim_auth(state_dir=None)`` → 直接失败（``_STATE_DIR_REQUIRED_ERR``）；
- ``_CONSUMED_AUTHS`` 永远只是非权威拒绝快路径（只拒绝、绝不放行）；
- paid admission 序列 = 精确匹配 → 有效持久化 state_dir → 原子 exclusive-create
  claim 成功 → ALLOWED_AUTHORIZED_PAID；任何前置失败 → BLOCKED / fail closed。

覆盖 Requirement 8 A–H：
A. matched paid auth + state_dir=None -> BLOCKED（单次 + 线程并发零 winner +
   _CONSUMED_AUTHS 预置也不能放行）
B. 多个独立进程 + state_dir=None -> 零 winner
C. 有效共享 state_dir + 并发进程 -> 恰好一个 winner
D. 有效共享 state_dir 顺序 replay -> 首次 allowed、二次 blocked
E. 无效/不可用 state_dir -> fail closed
F. LOCAL_FREE 路径保持可用（state_dir=None 也不受影响）
G. paid/unknown 无授权仍 blocked
H. FIX-002/FIX-003 endpoint/FREE/并发回归保持绿色（代表性 endpoint 对抗抽样；
   完整回归由全量套件证明）
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from ai_agent_framework import cost_guard as cg

ROOT = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).resolve().parent / "_auth_claim_worker.py"

SCOPE = "T1|hermes|deepseek-v4-flash|deepseek"

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


def _local_resolution(model="qwen3:4b", provider="ollama", base_url=None):
    return {
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "model_source": cg.MODEL_SOURCE_ENV,
        "notes": ["test local resolution"],
    }


def _spawn_workers(state_dir_arg: str, n: int, task_id: str = "T1") -> list[subprocess.CompletedProcess]:
    """独立 python 进程各执行一次准入 claim（真实 resolve + env invocation-truth）。

    state_dir_arg：worker 的第一个 argv（真实路径，或 "NONE" → state_dir=None）。
    退出码：0 = ALLOWED_AUTHORIZED_PAID；3 = BLOCKED_COST_APPROVAL。
    """
    procs = [
        subprocess.Popen(
            [sys.executable, "-u", str(WORKER), state_dir_arg, task_id],
            cwd=str(ROOT),
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                cg.ENV_MODEL: "deepseek-v4-flash",
                cg.ENV_PROVIDER: "deepseek",
                cg.ENV_AUTH: SCOPE,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(n)
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        results.append(
            {"rc": p.returncode, "stdout": out.strip(), "stderr": err.strip()[-300:]}
        )
    return results


# ---------------------------------------------------------------------------
# A. matched paid auth + state_dir=None -> BLOCKED
# ---------------------------------------------------------------------------


def test_a_state_dir_none_matched_paid_blocked(monkeypatch):
    """单次 evaluate：精确授权匹配 + state_dir=None → BLOCKED（fail closed）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    rec = cg.evaluate("T1", "hermes")  # state_dir=None
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert rec["required_scope"] == SCOPE
    assert rec["authorization_present"] is True
    assert rec["authorization_consumed"] is False  # 无持久化 → 未消费任何状态
    assert any("state_dir" in n and "REQUIRED" in n for n in rec["notes"])


def test_a_state_dir_none_thread_contention_zero_winners(monkeypatch):
    """线程并发 + state_dir=None：8 线程 barrier 起跑 → 零 winner、全部 BLOCKED。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    n = 8
    barrier = threading.Barrier(n)
    decisions: list[str] = []
    errors: list[str] = []
    guard = threading.Lock()

    def worker():
        barrier.wait()
        try:
            rec = cg.evaluate("T1", "hermes")
        except Exception as exc:  # noqa: BLE001
            with guard:
                errors.append(f"{type(exc).__name__}: {exc}")
            return
        with guard:
            decisions.append(rec["decision"])

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    assert len(decisions) == n
    assert decisions.count(cg.DECISION_ALLOWED_AUTHORIZED_PAID) == 0, decisions
    assert decisions.count(cg.DECISION_BLOCKED_COST_APPROVAL) == n, decisions


def test_a_consumed_auths_never_an_admission_authority(monkeypatch, tmp_path):
    """_CONSUMED_AUTHS 预置也绝不放行：无 state_dir → BLOCKED；有 state_dir 时
    claim（filesystem exclusive-create）才是唯一准入权威。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)

    # 预置 in-process 集合（模拟本进程曾消费）→ 仍不得放行
    cg._CONSUMED_AUTHS.add(SCOPE)
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL

    # 预置 + 有效 state_dir：in-process 只拒绝（快路径），不可能创造放行
    rec2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL

    # 清空 in-process（fresh 进程等价）→ 同一 state_dir 上 claim 成功 → allowed
    cg._CONSUMED_AUTHS.clear()
    rec3 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec3["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID


def test_a_claim_function_level_state_dir_none_fails_closed():
    """函数级：_claim_auth / _consume_auth 在 state_dir=None 时返回 False。"""
    ok, err = cg._claim_auth(SCOPE, SCOPE, None)
    assert ok is False
    assert "state_dir" in err and "REQUIRED" in err
    ok2, err2 = cg._consume_auth(SCOPE, SCOPE, None)
    assert ok2 is False
    assert "state_dir" in err2 and "REQUIRED" in err2


# ---------------------------------------------------------------------------
# B. 多个独立进程 + state_dir=None -> 零 winner
# ---------------------------------------------------------------------------


def test_b_independent_processes_state_dir_none_zero_winners():
    """6 个独立 python 进程（各自空 _CONSUMED_AUTHS）+ state_dir=None →
    全部 BLOCKED（零 ALLOWED_AUTHORIZED_PAID）。"""
    results = _spawn_workers("NONE", n=6)
    winners = [r for r in results if r["rc"] == 0]
    losers = [r for r in results if r["rc"] == 3]
    assert winners == [], f"state_dir=None must yield zero winners: {results}"
    assert len(losers) == 6, f"all must be blocked: {results}"
    for r in losers:
        assert '"decision": "BLOCKED_COST_APPROVAL"' in r["stdout"], r
        assert '"authorization_consumed": false' in r["stdout"], r


# ---------------------------------------------------------------------------
# C. 有效共享 state_dir + 并发进程 -> 恰好一个 winner
# ---------------------------------------------------------------------------


def test_c_shared_state_dir_concurrent_processes_exactly_one_winner(tmp_path):
    """6 个独立进程 + 同一有效 state_dir → 恰好 1 个 ALLOWED，其余 BLOCKED
    （filesystem exclusive-create 为跨进程权威）。"""
    shared = tmp_path / "shared"
    shared.mkdir()
    results = _spawn_workers(str(shared), n=6)
    winners = [r for r in results if r["rc"] == 0]
    losers = [r for r in results if r["rc"] == 3]
    assert len(winners) == 1, f"exactly one winner expected: {results}"
    assert len(losers) == 5, f"five blocked expected: {results}"
    marker = shared / cg.CONSUMPTION_FILENAME
    assert marker.exists()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["consumed_auth_fingerprint"] == cg._auth_fingerprint(SCOPE)
    assert "consumed_auth" not in payload  # 不落盘授权原文


# ---------------------------------------------------------------------------
# D. 有效共享 state_dir 顺序 replay -> 首次 allowed、二次 blocked
# ---------------------------------------------------------------------------


def test_d_sequential_replay_first_allowed_second_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    r1 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r1["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert r1["authorization_consumed"] is True
    r2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert r2["authorization_consumed"] is True
    cg._CONSUMED_AUTHS.clear()  # fresh 进程等价（仅剩磁盘 marker）
    r3 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r3["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert r3["authorization_consumed"] is True


# ---------------------------------------------------------------------------
# E. 无效/不可用 state_dir -> fail closed
# ---------------------------------------------------------------------------


def test_e_state_dir_is_file_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    state_dir = tmp_path / "afile"
    state_dir.write_text("x")
    rec = cg.evaluate("T1", "hermes", state_dir=state_dir)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("persist" in n for n in rec["notes"])


def test_e_marker_path_occupied_by_directory_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    (tmp_path / cg.CONSUMPTION_FILENAME).mkdir()  # marker 路径被目录占用
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is True  # 状态不确定 → fail closed


def test_e_runner_persistence_uncertainty_never_spawns(tmp_path, monkeypatch):
    """runner 集成：persistence 不确定（marker 路径被目录占用）→ guard BLOCKED
    → Hermes 不越过 invocation 边界（run_agent 零调用）。"""
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
    out.mkdir()
    (out / cg.CONSUMPTION_FILENAME).mkdir()  # marker 路径被目录占用 → 无法 claim

    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding="utf-8")
    assert calls == []  # Hermes subprocess 未被创建
    assert "## Current Status\nWAITING" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert (out / "hermes_result.md").read_text(encoding="utf-8").startswith(
        "FRAMEWORK_ERROR\nCOST_APPROVAL_REQUIRED"
    )


# ---------------------------------------------------------------------------
# F. LOCAL_FREE 路径保持可用（state_dir=None 也不受影响）
# ---------------------------------------------------------------------------


def test_f_local_free_remains_functional_without_state_dir(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _local_resolution())
    rec = cg.evaluate("T1", "hermes")  # state_dir=None
    assert rec["decision"] == cg.DECISION_ALLOWED_FREE
    assert rec["cost_class"] == cg.COST_LOCAL_FREE
    assert rec["required_scope"] is None  # 本地免费不需要授权/claim


def test_f_local_base_url_endpoint_local_free(monkeypatch):
    monkeypatch.setattr(
        cg, "resolve_effective_hermes",
        lambda: _paid_resolution(base_url="http://127.0.0.1:11434/v1"),
    )
    rec = cg.evaluate("T1", "hermes", state_dir=None)
    assert rec["decision"] == cg.DECISION_ALLOWED_FREE


# ---------------------------------------------------------------------------
# G. paid/unknown 无授权仍 blocked
# ---------------------------------------------------------------------------


def test_g_paid_without_authorization_blocked(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    rec = cg.evaluate("T1", "hermes", state_dir=None)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_present"] is False
    assert rec["required_scope"] == SCOPE


# ---------------------------------------------------------------------------
# H. FIX-002/FIX-003 代表性回归（endpoint / FREE / 并发语义保持）
# ---------------------------------------------------------------------------


def test_h_fake_local_endpoint_regression_samples():
    """FIX-002 hostname/IP 语义抽样：伪装本地/非 loopback → PAID_OR_UNKNOWN。"""
    for url in (
        "https://localhost.evil.example/v1",
        "http://0.0.0.0:11434/v1",          # bind 通配 ≠ 权威本地证据
        "https://8.8.8.8/v1",
        "http://localhost.localdomain/v1",
        "http://127.0.0.1.example.com/v1",
        "http:///v1",                        # 无 hostname
        "http://localhost:99999/v1",         # 非法 port
        "ftp://localhost/v1",                # 非 http(s)
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_PAID_OR_UNKNOWN, url


def test_h_exact_local_endpoint_regression_samples():
    """exact localhost / loopback IP → LOCAL_FREE（FIX-002 语义保持）。"""
    for url in (
        "http://localhost:11434/v1",
        "http://127.0.0.2:11434/v1",
        "http://[::1]:11434/v1",
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_LOCAL_FREE, url


def test_h_free_env_still_ignored(monkeypatch):
    """AAF_COST_FREE_MODELS 仍非权威：声明付费模型为 free → 无授权仍 BLOCKED。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_FREE_MODELS, "deepseek-v4-flash@deepseek")
    rec = cg.evaluate("T1", "hermes", state_dir=None)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert any("IGNORED" in n for n in rec["notes"])


def test_h_shared_dir_contention_still_one_winner_thread_level(monkeypatch, tmp_path):
    """FIX-003 线程级 contention 保持：同一 auth + 同一 state_dir → 恰 1 winner。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    n = 8
    barrier = threading.Barrier(n)
    decisions: list[str] = []
    guard = threading.Lock()

    def worker():
        barrier.wait()
        rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
        with guard:
            decisions.append(rec["decision"])

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert decisions.count(cg.DECISION_ALLOWED_AUTHORIZED_PAID) == 1, decisions
    assert decisions.count(cg.DECISION_BLOCKED_COST_APPROVAL) == n - 1, decisions
