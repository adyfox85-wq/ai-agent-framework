"""AAF v0.5 A5 — paid escalation Cost Gate focused tests.

TASK: AAF-v0.5-A5-PAID-ESCALATION-GATE-001（Requirement 10 全矩阵）：
- paid candidate + no auth -> BLOCKED（零 paid invocation）
- paid candidate + mismatched task/stage/model/provider auth -> BLOCKED
- malformed/unknown authorization state -> fail closed（FAIL_CLOSED）
- exact valid auth -> AUTHORIZED but zero paid invocation
- free candidate still takes precedence over paid escalation
- unqualified/insufficient paid candidate never reaches Cost Gate
- audit required fields and no-silent-paid evidence（machine-readable + validated）
- authorization alone does not set fallback_attempted/used

第 1 节：``fallback_paid_gate`` 纯解释器（A0 guard record → gate 状态）；
第 2 节：live runtime 编排（run_fallback_after_failure 集成——free 路径零修改）；
第 3 节：gate audit validator fail-closed mutation 矩阵；
第 4 节：真实 runner Hermes stage 集成（paid gate artifact / stage ref / WAITING /
        env 还原 / free fallback 行为保持）。
"""

import json
import os
from pathlib import Path

import pytest

import ai_agent_framework.cost_guard as cg
import ai_agent_framework.model_registry as mr
import ai_agent_framework.runner as runner_mod
from ai_agent_framework import active_routing as ar
from ai_agent_framework import fallback_contract as fc
from ai_agent_framework import fallback_paid_gate as fpg
from ai_agent_framework import fallback_runtime as fr
from ai_agent_framework import model_observation as mo
from ai_agent_framework import shadow_observation as so
from ai_agent_framework.risk_contract import RISK_LOW, ROLE_EXECUTOR

_REAL_RESOLVE = cg.resolve_effective_hermes  # conftest hermetic patch 前捕获

FREE = mo.COST_CLASS_FREE
LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
PAID = mo.COST_CLASS_PAID
UNKNOWN = mo.COST_CLASS_UNKNOWN

_TASK_ID = "A5PG-UNIT-1"


@pytest.fixture(autouse=True)
def _scrub_a5_env(monkeypatch):
    """本文件 hermetic 保证（与 test_a5_fallback_runtime 同型）。"""
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL, cg.ENV_AUTH):
        monkeypatch.delenv(var, raising=False)


def _entry(
    model: str,
    *,
    provider: str = "remote-api",
    tier: str = "T4",
    cost: str = PAID,
    scope: str = mr.QUAL_SCOPE_MAIN,
    qual_status: str = mr.QUAL_STATUS_QUALIFIED,
    base_url: str | None = None,
    locality: str = mr.LOCALITY_REMOTE,
    agents: tuple[str, ...] = ("hermes",),
) -> mr.RegistryEntry:
    return mr.RegistryEntry(
        model=model,
        provider=provider,
        base_url=base_url,
        applicable_agents=agents,
        capability_tier=tier,
        cost_class=cost,
        locality=locality,
        qualification=mr.RuntimeQualification(
            status=qual_status,
            scope=scope,
            evidence=("a5-paid-gate-test-fixture",),
            observed_at="2026-09-03T00:00:00",
        ),
        evidence=("a5-paid-gate-test-fixture",),
    )


def _local_entry(model: str, *, provider: str = "custom") -> mr.RegistryEntry:
    """LOCAL_FREE original（loopback 端点；A3 路由/原始模型 fixture）。"""
    return _entry(
        model,
        provider=provider,
        cost=LOCAL_FREE,
        base_url="http://127.0.0.1:11434/v1",
        locality=mr.LOCALITY_LOCAL,
    )


def _registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


def _run(
    registry,
    *,
    exc=RuntimeError("hermes failed (exit=1) STDERR: simulated model failure"),
    invoke=None,
    calls=None,
    risk=RISK_LOW,
    transport_retry_count=0,
    automatic_fallback_count_used=0,
    monkeypatch=None,
    output_dir=None,
    tmp_path=None,
):
    """编排器单测 runner（模拟 runner 语义：overlay 由调用方在 observation 后
    还原——本文件场景 gate/free 路径均无 attempt，overlay_saved 恒 None）。"""
    out_dir = Path(output_dir) if output_dir else None
    if out_dir is None:
        out_dir = Path(tmp_path) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    state = {"calls": 0, "envs": []}
    real_invoke = invoke

    def default_invoke(agent, prompt, workspace):
        state["calls"] += 1
        state["envs"].append(
            {
                "model": os.environ.get(cg.ENV_MODEL),
                "provider": os.environ.get(cg.ENV_PROVIDER),
                "base_url": os.environ.get(cg.ENV_BASE_URL),
            }
        )
        return "ok\nAAF_STRUCTURED_RESULT_BEGIN\n{\"status\": \"SUCCESS\"}\nAAF_STRUCTURED_RESULT_END"

    outcome = fr.run_fallback_after_failure(
        task_id=_TASK_ID,
        risk_class=risk,
        risk_source=so.TASK_RISK_SOURCE,
        registry=registry,
        output_dir=out_dir,
        prompt="TASK",
        workspace=Path(tmp_path),
        invoke=real_invoke or default_invoke,
        failure_exc=exc,
        transport_retry_count=transport_retry_count,
        automatic_fallback_count_used=automatic_fallback_count_used,
    )
    if outcome is not None and outcome.get("overlay_saved"):
        ar.restore_routing_env(outcome["overlay_saved"])
    if calls is not None:
        calls.update(state)
    return outcome, out_dir, state


def _pin_original(monkeypatch, model="aaa-orig", provider="custom"):
    """env 显式钉住 original actual model（_original_invocation_identity 的
    env 分支——guard 的真实 resolve 只在 candidate overlay 下被调用，零 CLI）。"""
    monkeypatch.setenv(cg.ENV_MODEL, model)
    monkeypatch.setenv(cg.ENV_PROVIDER, provider)


def _gate(outcome) -> dict:
    rec = outcome["paid_gate_record"]
    assert rec is not None, f"missing paid_gate_record: {outcome.get('paid_gate_error')}"
    return rec


def _no_gate(outcome) -> None:
    assert "paid_gate_record" not in outcome
    assert "paid_gate_artifact_ref" not in outcome


# ===========================================================================
# 1. 纯解释器（interpret_guard：A0 guard record → gate 状态）
# ===========================================================================


def _guard_record(
    decision=cg.DECISION_ALLOWED_AUTHORIZED_PAID,
    model="zzz-paid",
    provider="remote-api",
    present=True,
    matched=True,
    consumed=True,
    cost_class=cg.COST_PAID_OR_UNKNOWN,
    required_scope=None,
):
    if required_scope is None:
        required_scope = cg.scope_string(_TASK_ID, "hermes", model, provider)
    return {
        "decision": decision,
        "model": model,
        "provider": provider,
        "authorization_present": present,
        "authorization_matched": matched,
        "authorization_consumed": consumed,
        "cost_class": cost_class,
        "required_scope": required_scope,
        "notes": [],
    }


def test_interpret_exact_authorized():
    interp = fpg.interpret_guard(_guard_record(), "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
    assert interp["authorization_present"] is True
    assert interp["authorization_matched"] is True
    assert interp["authorization_consumed"] is True
    assert interp["guard_decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID


def test_interpret_no_auth_blocked():
    rec = _guard_record(decision=cg.DECISION_BLOCKED_COST_APPROVAL,
                        present=False, matched=False, consumed=False)
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert interp["authorization_present"] is False
    assert "no AAF_COST_AUTH" in interp["gate_reason"]


def test_interpret_mismatched_auth_blocked():
    rec = _guard_record(decision=cg.DECISION_BLOCKED_COST_APPROVAL,
                        present=True, matched=False, consumed=False)
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert "does not exactly match" in interp["gate_reason"]


def test_interpret_replay_rejected_blocked():
    rec = _guard_record(decision=cg.DECISION_BLOCKED_COST_APPROVAL,
                        present=True, matched=False, consumed=True)
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert "ALREADY CONSUMED" in interp["gate_reason"] or "replay" in interp["gate_reason"]


def test_interpret_allow_free_conflict_fail_closed():
    rec = _guard_record(decision=cg.DECISION_ALLOWED_FREE,
                        present=False, matched=False, consumed=False)
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "ALLOWED_FREE" in interp["gate_reason"]


def test_interpret_malformed_guard_fail_closed():
    for bad in (None, {}, {"decision": cg.DECISION_ALLOWED_AUTHORIZED_PAID}):
        interp = fpg.interpret_guard(bad, "zzz-paid", "remote-api")
        assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
        assert "malformed" in interp["gate_reason"]


def test_interpret_scope_mismatch_fail_closed():
    """guard 解析的 effective model/provider != candidate → FAIL_CLOSED
    （授权状态无法归属——绝不凭错误 scope 放行/记录；Requirement 4 零削弱）。"""
    rec = _guard_record(model="someone-else", provider="other-api")
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "scope integrity" in interp["gate_reason"]


def test_interpret_unknown_guard_decision_fail_closed():
    rec = _guard_record(decision="SOMETHING_ELSE")
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED


def test_interpret_contradictory_flags_fail_closed():
    """ALLOWED_AUTHORIZED_PAID 但 flags 不齐 / BLOCKED 但 matched=True =
    malformed → FAIL_CLOSED。"""
    rec = _guard_record(decision=cg.DECISION_ALLOWED_AUTHORIZED_PAID,
                        present=True, matched=False, consumed=True)
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    rec = _guard_record(decision=cg.DECISION_BLOCKED_COST_APPROVAL,
                        present=True, matched=True, consumed=False)
    interp = fpg.interpret_guard(rec, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED


def test_interpret_contradictory_paid_flags_normalized_fail_closed():
    """FIX-001（Codex blocker 形状 1）：ALLOWED_AUTHORIZED_PAID + flags 不齐
    （含 matched=True）→ FAIL_CLOSED。normalized flags 恒 False——matched=True
    绝不进入 FAIL_CLOSED record；in-scope 的 ALLOWED_AUTHORIZED_PAID token 不
    进 normalized guard_decision（与 FAIL_CLOSED 互斥）；raw 矛盾证据完整保留
    于 source_guard_record（Requirement 2/4/5/6）。"""
    raw = _guard_record(decision=cg.DECISION_ALLOWED_AUTHORIZED_PAID,
                        present=True, matched=True, consumed=False)
    interp = fpg.interpret_guard(raw, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "contradictory" in interp["gate_reason"]
    assert interp["authorization_present"] is False
    assert interp["authorization_matched"] is False
    assert interp["authorization_consumed"] is False
    assert interp["guard_decision"] is None  # in-scope authorized token → 不 echo
    assert interp["guard_model"] == "zzz-paid"  # scope echo 保留（type-safe）
    assert interp["source_guard_record"] == raw
    # raw 矛盾可观察：source 中 decision token 与 matched=True 原样保留
    assert (
        interp["source_guard_record"]["decision"]
        == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    )
    assert interp["source_guard_record"]["authorization_matched"] is True


def test_interpret_blocked_matched_normalized_fail_closed():
    """FIX-001（Codex blocker 形状 2）：BLOCKED_COST_APPROVAL + matched=True →
    FAIL_CLOSED；normalized matched/present/consumed 恒 False；guard token
    BLOCKED 保留（非 authorized token，不隐含本候选已授权）；raw 矛盾保留于
    source（Requirement 3/4/5/6）。"""
    raw = _guard_record(decision=cg.DECISION_BLOCKED_COST_APPROVAL,
                        present=True, matched=True, consumed=False)
    interp = fpg.interpret_guard(raw, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert interp["authorization_present"] is False
    assert interp["authorization_matched"] is False
    assert interp["authorization_consumed"] is False
    assert interp["guard_decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert interp["source_guard_record"] == raw
    assert interp["source_guard_record"]["authorization_matched"] is True


def test_interpret_unknown_token_normalized_guard_none_source_preserved():
    """FIX-001：未知 decision token → FAIL_CLOSED；normalized guard_decision
    None（未知 token 不进 whitelist 字段——validator 拒绝非 A0 token）；raw
    token 完整保留于 source_guard_record。"""
    raw = _guard_record(decision="SOMETHING_ELSE")
    interp = fpg.interpret_guard(raw, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "SOMETHING_ELSE" in interp["gate_reason"]
    assert interp["authorization_matched"] is False
    assert interp["guard_decision"] is None
    assert interp["source_guard_record"] == raw
    assert interp["source_guard_record"]["decision"] == "SOMETHING_ELSE"


def test_interpret_authorized_invalid_scope_evidence_fail_closed():
    """FIX-001：ALLOWED_AUTHORIZED_PAID + flags 全 True 但 required_scope 畸形
    （None / 非 str）→ FAIL_CLOSED（exact-scope 授权证据无法记录——绝不凭残缺
    scope 授权；Requirement 3/5/6）。normalized required_scope=None（畸形值不进
    record），raw 值保留于 source。"""
    for bad_scope in (None, 42):
        raw = _guard_record()
        raw["required_scope"] = bad_scope
        interp = fpg.interpret_guard(raw, "zzz-paid", "remote-api")
        assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
        assert "required_scope" in interp["gate_reason"]
        assert interp["authorization_matched"] is False
        assert interp["guard_decision"] is None
        assert interp["required_scope"] is None
        assert interp["source_guard_record"] == raw
        assert interp["source_guard_record"]["required_scope"] == bad_scope


def test_interpret_scope_mismatch_keeps_token_and_source():
    """FIX-001：scope integrity FAIL_CLOSED 保持既有行为——out-of-scope 的
    ALLOWED_AUTHORIZED_PAID token 仍 echo（不隐含本候选授权，validator 接受），
    同时 raw 证据进入 source_guard_record。"""
    raw = _guard_record(model="someone-else", provider="other-api")
    interp = fpg.interpret_guard(raw, "zzz-paid", "remote-api")
    assert interp["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "scope integrity" in interp["gate_reason"]
    assert interp["authorization_matched"] is False
    assert interp["guard_decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert interp["guard_model"] == "someone-else"
    assert interp["source_guard_record"] == raw
    assert interp["source_guard_record"]["authorization_matched"] is True


# ===========================================================================
# 2. live runtime 编排矩阵（Requirement 10）
# ===========================================================================


def test_paid_candidate_no_auth_blocked_no_invocation(tmp_path, monkeypatch):
    """paid candidate + no auth → gate BLOCKED；零 paid invocation；
    attempted/used 恒 False（runtime + gate 双 record）；原始失败保留。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0  # 零 paid invocation
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert outcome["result_text"] is None  # 原始失败保留
    assert outcome["overlay_saved"] is None
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert rec["paid_escalation_required"] is True
    assert rec["authorization_present"] is False
    assert rec["authorization_matched"] is False
    assert rec["authorization_consumed"] is False
    assert rec["guard_decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["paid_candidate"] == "zzz-paid@remote-api"
    assert rec["paid_candidate_model"] == "zzz-paid"
    assert rec["paid_candidate_provider"] == "remote-api"
    assert rec["final_actual_model"] == rec["original_model"] == "aaa-orig"
    assert rec["fallback_attempted"] is False
    assert rec["fallback_used"] is False
    fpg.validate_paid_escalation_gate_record(rec)
    # runtime record（A5-002 语义零修改）
    rt = outcome["audit_record"]
    assert rt["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rt["fallback_attempted"] is False
    assert rt["authorization_outcome"] == fr.AUTH_OUTCOME_NONE
    fr.validate_fallback_runtime_record(rt)
    # 权威 gate artifact 落盘 + reload 复验
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded is not None
    fpg.validate_paid_escalation_gate_record(loaded)
    assert loaded["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    # no-silent-paid-execution evidence（Requirement 5）
    ev = " ".join(rec["no_silent_paid_evidence"])
    assert "no silent paid execution" in ev
    assert "NO paid model invocation" in ev or "no paid model invocation" in ev
    # env 不泄漏
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"  # 还原到调用前状态
    assert os.environ.get(cg.ENV_AUTH) is None


@pytest.mark.parametrize(
    "auth_factory",
    [
        lambda tid: f"WRONG-TASK|hermes|zzz-paid|remote-api",
        lambda tid: f"{tid}|validator|zzz-paid|remote-api",
        lambda tid: f"{tid}|hermes|other-model|remote-api",
        lambda tid: f"{tid}|hermes|zzz-paid|other-provider",
    ],
    ids=["wrong-task", "wrong-stage", "wrong-model", "wrong-provider"],
)
def test_paid_candidate_mismatched_auth_blocked(tmp_path, monkeypatch, auth_factory):
    """paid candidate + 任务/stage/model/provider 任一维度不匹配的 auth →
    BLOCKED（exact scope 零削弱），零 invocation。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, auth_factory(_TASK_ID))
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, _out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert rec["authorization_present"] is True
    assert rec["authorization_matched"] is False
    assert rec["authorization_consumed"] is False
    assert "does not exactly match" in rec["gate_reason"]
    fpg.validate_paid_escalation_gate_record(rec)


def test_exact_auth_authorized_zero_paid_invocation(tmp_path, monkeypatch):
    """exact valid auth → gate AUTHORIZED（ready-for-paid-invocation 资格）
    但仍零 paid invocation；attempted/used 恒 False（authorization 本身不设
    attempted/used——Requirement 6/8/10）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    auth = cg.scope_string(_TASK_ID, "hermes", "zzz-paid", "remote-api")
    monkeypatch.setenv(cg.ENV_AUTH, auth)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0  # 授权 ≠ 执行：零 paid invocation
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert outcome["result_text"] is None  # 原始失败保留（不自动继续）
    assert outcome["overlay_saved"] is None
    gate_rec = _gate(outcome)
    assert gate_rec["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
    assert gate_rec["paid_escalation_required"] is True
    assert gate_rec["authorization_present"] is True
    assert gate_rec["authorization_matched"] is True
    assert gate_rec["authorization_consumed"] is True  # A0 准入边界一次性 claim
    assert gate_rec["guard_decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert gate_rec["guard_model"] == "zzz-paid"
    assert gate_rec["required_scope"] == auth
    assert gate_rec["fallback_attempted"] is False  # authorization 不设 attempted
    assert gate_rec["fallback_used"] is False
    assert gate_rec["final_actual_model"] == "aaa-orig"
    # A0 一次性消费记录（既有 A0 语义；gate 只转述）
    assert (out_dir / cg.CONSUMPTION_FILENAME).exists()
    ev = " ".join(gate_rec["no_silent_paid_evidence"])
    assert "NOT invoke" in ev or "not invoke" in ev or "no paid model invocation" in ev
    fpg.validate_paid_escalation_gate_record(gate_rec)
    # runtime record：仍不 attempt、A5-002 语义零修改
    rt = outcome["audit_record"]
    assert rt["fallback_attempted"] is False
    assert rt["fallback_used"] is False
    assert rt["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    fr.validate_fallback_runtime_record(rt)
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"  # env 还原


def test_guard_evaluation_failure_fail_closed(tmp_path, monkeypatch):
    """A0 guard 求值抛异常（unknown authorization state）→ gate FAIL_CLOSED；
    编排器不崩溃、runtime record 正常、零 invocation。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)

    def broken_evaluate(task_id, stage, state_dir=None):
        raise RuntimeError("simulated A0 guard failure")

    monkeypatch.setattr(cg, "evaluate", broken_evaluate)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert rec["authorization_present"] is False
    assert rec["guard_decision"] is None
    assert "raised" in rec["gate_reason"] or "unknown" in rec["gate_reason"]
    fpg.validate_paid_escalation_gate_record(rec)
    # FIX-001：求值失败无 raw record → source=None；artifact 仍落盘 + 复验
    assert rec["source_guard_record"] is None
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded is not None
    assert loaded["source_guard_record"] is None
    fpg.validate_paid_escalation_gate_record(loaded)


def test_malformed_guard_record_fail_closed(tmp_path, monkeypatch):
    """A0 guard 返回 malformed record（缺必需字段）→ FAIL_CLOSED。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setattr(cg, "evaluate",
                        lambda task_id, stage, state_dir=None: {})
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "malformed" in rec["gate_reason"]
    fpg.validate_paid_escalation_gate_record(rec)
    # FIX-001：malformed source 证据保真（{} 原样保留）+ 权威 artifact 落盘
    assert rec["source_guard_record"] == {}
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded is not None
    assert loaded["source_guard_record"] == {}
    fpg.validate_paid_escalation_gate_record(loaded)


def _contradictory_guard(
    decision: str,
    *,
    present=False,
    matched=False,
    consumed=False,
    required_scope: str | None = "SCOPE_DEFAULT",
) -> dict:
    """FIX-001 fixture：对 zzz-paid@remote-api 候选 in-scope 的矛盾/malformed
    A0 guard record（raw 证据可自相矛盾——interpret_guard 必须 fail closed 且
    组装出 validator-valid、可持久化的 authoritative audit）。"""
    if required_scope == "SCOPE_DEFAULT":
        required_scope = cg.scope_string(
            _TASK_ID, "hermes", "zzz-paid", "remote-api"
        )
    return {
        "decision": decision,
        "model": "zzz-paid",
        "provider": "remote-api",
        "authorization_present": present,
        "authorization_matched": matched,
        "authorization_consumed": consumed,
        "cost_class": cg.COST_PAID_OR_UNKNOWN,
        "required_scope": required_scope,
        "notes": ["raw contradictory A0 evidence (FIX-001 fixture)"],
    }


@pytest.mark.parametrize(
    "guard_record",
    [
        _contradictory_guard(cg.DECISION_ALLOWED_AUTHORIZED_PAID,
                             present=True, matched=False, consumed=False),
        _contradictory_guard(cg.DECISION_ALLOWED_AUTHORIZED_PAID,
                             present=True, matched=True, consumed=False),
        _contradictory_guard(cg.DECISION_BLOCKED_COST_APPROVAL,
                             present=True, matched=True, consumed=False),
        _contradictory_guard("SOMETHING_ELSE"),
        _contradictory_guard(cg.DECISION_ALLOWED_AUTHORIZED_PAID,
                             present=True, matched=True, consumed=True,
                             required_scope=None),
        {},
    ],
    ids=[
        "allowed-authorized-incomplete-flags",
        "allowed-authorized-matched-true-not-consumed",
        "blocked-cost-approval-matched-true",
        "unknown-decision-token",
        "authorized-invalid-required-scope",
        "missing-required-keys",
    ],
)
def test_contradictory_a0_record_fail_closed_audit_persisted(
    tmp_path, monkeypatch, guard_record
):
    """FIX-001（Requirement 8 全矩阵，Codex blocker 收口）：malformed /
    contradictory / unknown A0 authorization record 经真实 runtime 编排 →
    gate FAIL_CLOSED + authoritative audit validator-valid + artifact 落盘 +
    raw 矛盾证据在 source_guard_record 可观察 + fallback_attempted/used 恒
    False + 零 paid invocation（此前这些形状组装出的 record 自相矛盾、
    validator 拒绝、paid_escalation_gate.json 不落盘——runtime 只 surface
    paid_gate_error，Requirement 7 违例）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setattr(cg, "evaluate",
                        lambda task_id, stage, state_dir=None: guard_record)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0  # 零 paid invocation
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    rec = _gate(outcome)  # 无 paid_gate_error——组装成功
    assert rec["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    # normalized flags 与 FAIL_CLOSED 自洽（Requirement 5）：raw 矛盾 flags 不进入
    assert rec["authorization_present"] is False
    assert rec["authorization_matched"] is False
    assert rec["authorization_consumed"] is False
    # normalized guard_decision 只可能是 A0 token 或 None（绝不携带未知/矛盾 token）
    assert rec["guard_decision"] in (
        None,
        cg.DECISION_ALLOWED_FREE,
        cg.DECISION_ALLOWED_AUTHORIZED_PAID,
        cg.DECISION_BLOCKED_COST_APPROVAL,
    )
    assert rec["fallback_attempted"] is False
    assert rec["fallback_used"] is False
    assert rec["paid_escalation_required"] is True
    fpg.validate_paid_escalation_gate_record(rec)
    # authoritative artifact 已持久化 + reload 复验（Requirement 3/7）
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded is not None
    fpg.validate_paid_escalation_gate_record(loaded)
    assert loaded["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    # raw 矛盾证据可观察（Requirement 4/6）：source 快照 = A0 原样（含矛盾 flags）
    assert loaded["source_guard_record"] == guard_record
    # no-silent-paid-execution evidence
    ev = " ".join(loaded["no_silent_paid_evidence"])
    assert "no silent paid execution" in ev


def test_contradictory_scope_evidence_unknown_token_fail_closed_persisted(
    tmp_path, monkeypatch
):
    """FIX-001（Requirement 8「contradictory model/provider 或 scope evidence」）：
    guard record 声称对**其他 model/provider** 的授权且 decision token 未知 →
    FAIL_CLOSED + validator-valid + 落盘 + raw 证据可观察（未知 token 只存在于
    source；normalized guard_decision 保持 None）+ 零 invocation。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    wrong_scope = cg.scope_string(
        _TASK_ID, "hermes", "someone-else", "other-api"
    )
    guard_record = {
        "decision": "SOMETHING_ELSE",
        "model": "someone-else",
        "provider": "other-api",
        "authorization_present": True,
        "authorization_matched": True,
        "authorization_consumed": True,
        "cost_class": cg.COST_PAID_OR_UNKNOWN,
        "required_scope": wrong_scope,
        "notes": ["claims authorization for someone-else@other-api"],
    }
    monkeypatch.setattr(cg, "evaluate",
                        lambda task_id, stage, state_dir=None: guard_record)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "scope integrity" in rec["gate_reason"]
    assert rec["authorization_matched"] is False
    assert rec["guard_decision"] is None
    assert rec["guard_model"] == "someone-else"  # type-safe scope echo
    assert rec["fallback_attempted"] is False
    assert rec["fallback_used"] is False
    fpg.validate_paid_escalation_gate_record(rec)
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded is not None
    fpg.validate_paid_escalation_gate_record(loaded)
    assert loaded["source_guard_record"] == guard_record
    assert loaded["source_guard_record"]["decision"] == "SOMETHING_ELSE"
    assert loaded["source_guard_record"]["authorization_matched"] is True


def test_guard_resolved_other_model_fail_closed(tmp_path, monkeypatch):
    """guard 解析的 effective model != candidate（hermetic resolve 场景的
    生产语义 = A0 record 不可归属）→ FAIL_CLOSED（绝不凭错误 scope 记录授权
    状态）。conftest hermetic resolve 固定 qwen3:4b/ollama——不做 _REAL_RESOLVE
    patch，即模拟 A0 求值对象不是 candidate 的 unknown 状态。"""
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, _out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "scope integrity" in rec["gate_reason"]
    fpg.validate_paid_escalation_gate_record(rec)


def test_unknown_cost_candidate_blocked_via_a0(tmp_path, monkeypatch):
    """registry cost=UNKNOWN 的合格候选 = paid 路径（A0 权威解析
    PAID_OR_UNKNOWN + 无授权 → BLOCKED；UNKNOWN 成本绝不静默放行）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"),
                    _entry("zzz-unk", cost=UNKNOWN, provider="deepseek"))
    calls = {}
    outcome, _out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert rec["paid_candidate"] == "zzz-unk@deepseek"
    assert rec["authorization_present"] is False
    fpg.validate_paid_escalation_gate_record(rec)


def test_free_candidate_takes_precedence_over_paid(tmp_path, monkeypatch):
    """free candidate 存在 → FREE fallback 照常执行（attempted=true），paid
    escalation Cost Gate 完全不运行（无 gate artifact）——Requirement 10。"""
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("fb-1", cost=LOCAL_FREE,
                                                     provider="custom",
                                                     base_url="http://127.0.0.1:11434/v1",
                                                     locality=mr.LOCALITY_LOCAL),
                    _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1  # free fallback 恰一次 invocation
    assert outcome["attempted"] is True
    assert outcome["used"] is True
    assert outcome["audit_record"]["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    assert outcome["audit_record"]["fallback_candidate"] == "fb-1@custom"
    _no_gate(outcome)
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()
    assert not (out_dir / cg.CONSUMPTION_FILENAME).exists()  # 零授权消费


def test_unqualified_paid_candidate_never_reaches_gate(tmp_path, monkeypatch):
    """资格闸排除的 paid 候选（aux scope / qualification unknown）→ contract
    candidates 空 → Cost Gate 完全不运行（Requirement 2/10）。"""
    _pin_original(monkeypatch)
    reg = _registry(
        _local_entry("aaa-orig"),
        _entry("aux-paid", scope=mr.QUAL_SCOPE_AUXILIARY),
        _entry("unk-qual-paid", qual_status=mr.QUAL_STATUS_UNKNOWN),
    )
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rec = outcome["audit_record"]
    assert rec["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rec["fallback_candidates"] == []
    _no_gate(outcome)
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()


def test_original_only_candidate_no_gate(tmp_path, monkeypatch):
    """唯一合格候选 = original → same-model 排除后无候选 → Cost Gate 不运行
    （paid escalation 只考虑 distinct candidate，Requirement 2）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch, model="aaa-orig", provider="custom")
    reg = _registry(_local_entry("aaa-orig"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    assert outcome["attempted"] is False
    assert outcome["audit_record"]["fallback_candidates"] == []
    _no_gate(outcome)
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()


def test_exhausted_budget_no_gate(tmp_path, monkeypatch):
    """automatic fallback budget 已消耗（count_used=1，free 路径已用其一次
    attempt）→ contract 无 eligible 决策 → Cost Gate 不运行（no chain/loop
    保持——paid escalation 绝不在已消耗一次 model-level fallback 后考虑）。"""
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, out_dir, _state = _run(
        reg, automatic_fallback_count_used=1, tmp_path=tmp_path
    )
    assert outcome["attempted"] is False
    rt = outcome["audit_record"]
    assert rt["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert fc.REASON_BUDGET_EXHAUSTED in rt["decision_reason"]
    _no_gate(outcome)
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()


def test_non_fallback_eligible_failure_no_gate(tmp_path, monkeypatch):
    """非 fallback-eligible failure（framework/input/config）→ blocked_fail_
    closed → Cost Gate 不运行（Requirement 2 前置 1）。"""
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, out_dir, _state = _run(
        reg, exc=OSError(13, "permission denied"), tmp_path=tmp_path
    )
    assert outcome["attempted"] is False
    assert outcome["audit_record"]["decision"] == fc.DECISION_BLOCKED_FAIL_CLOSED
    _no_gate(outcome)
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()


def test_gate_audit_required_fields_and_no_silent_evidence(tmp_path, monkeypatch):
    """gate audit record 含 Requirement 5 全字段；machine-readable + 校验 +
    落盘 reload 复验；no_silent_paid_evidence 非空显式。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = _gate(outcome)
    expected = {
        "schema_version", "decision_kind", "authority", "authoritative",
        "task_id", "stage_agent", "role", "risk_class", "risk_source",
        "failure_class", "failure_label", "trigger", "trigger_evidence",
        "original_model", "original_provider",
        "free_fallback_unavailable_reason",
        "paid_candidate", "paid_candidate_model", "paid_candidate_provider",
        "paid_escalation_required",
        "authorization_present", "authorization_matched",
        "authorization_consumed",
        "gate_decision", "no_silent_paid_evidence",
    }
    assert expected.issubset(set(rec.keys()))
    assert rec["decision_kind"] == fpg.DECISION_KIND
    assert rec["authoritative"] is True
    assert rec["failure_class"] == fc.FAILURE_INVOCATION
    assert rec["free_fallback_unavailable_reason"]
    assert rec["no_silent_paid_evidence"]
    assert all(isinstance(e, str) and e.strip()
               for e in rec["no_silent_paid_evidence"])
    assert all(isinstance(n, str) for n in rec["notes"])
    fpg.validate_paid_escalation_gate_record(rec)
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded == rec
    fpg.validate_paid_escalation_gate_record(loaded)
    # task/stage/role/risk 审计字段
    assert loaded["task_id"] == _TASK_ID
    assert loaded["stage_agent"] == "hermes"
    assert loaded["role"] == ROLE_EXECUTOR
    assert loaded["risk_class"] == RISK_LOW


def test_authorization_alone_never_sets_attempted_used(tmp_path, monkeypatch):
    """exact auth → AUTHORIZED：authorization 单独绝不设 fallback_attempted/
    used（Requirement 6/10——gate 与 runtime 双 record 均为 false）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(
        cg.ENV_AUTH, cg.scope_string(_TASK_ID, "hermes", "zzz-paid", "remote-api")
    )
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, _out_dir, _state = _run(reg, tmp_path=tmp_path)
    gate_rec = _gate(outcome)
    assert gate_rec["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
    assert gate_rec["fallback_attempted"] is False
    assert gate_rec["fallback_used"] is False
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert outcome["audit_record"]["fallback_attempted"] is False
    assert outcome["audit_record"]["fallback_used"] is False


def test_gate_consideration_audits_free_unavailable_reason(tmp_path, monkeypatch):
    """gate record 显式记录「为什么 FREE fallback 不可用」（Requirement 5）——
    runtime decision_reason + cost-gate 排除 notes 进入 record。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, _out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = _gate(outcome)
    assert fc.REASON_NO_QUALIFIED_CANDIDATE in rec["free_fallback_unavailable_reason"]
    assert any("never silently used" in n or "cost gate" in n.lower()
               for n in rec["notes"])


def test_guard_authorized_for_other_model_fail_closed_record(tmp_path, monkeypatch):
    """A0 返回对**其他 model** 的 ALLOWED_AUTHORIZED_PAID（record 不可归属）→
    gate FAIL_CLOSED artifact 正常组装/校验/落盘（绝不被当作本候选的授权；
    也不因 flags 转述而 validator 崩溃）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    wrong_scope = cg.scope_string(_TASK_ID, "hermes", "someone-else", "other-api")

    def authorized_for_other(task_id, stage, state_dir=None):
        return {
            "decision": cg.DECISION_ALLOWED_AUTHORIZED_PAID,
            "model": "someone-else",
            "provider": "other-api",
            "authorization_present": True,
            "authorization_matched": True,
            "authorization_consumed": True,
            "cost_class": cg.COST_PAID_OR_UNKNOWN,
            "required_scope": wrong_scope,
            "notes": ["exact match for someone-else (not the candidate)"],
        }

    monkeypatch.setattr(cg, "evaluate", authorized_for_other)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rec = _gate(outcome)
    assert rec["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "scope integrity" in rec["gate_reason"]
    assert rec["authorization_matched"] is False  # 不归属给本候选
    assert rec["guard_decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert rec["guard_model"] == "someone-else"
    fpg.validate_paid_escalation_gate_record(rec)
    # FIX-001：raw 证据（含 matched=True）只存在于 source_guard_record——
    # normalized matched 恒 False，record 自洽 + 持久化
    assert (
        rec["source_guard_record"]["decision"]
        == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    )
    assert rec["source_guard_record"]["authorization_matched"] is True
    loaded = fpg.load_paid_gate(out_dir)
    assert loaded is not None
    fpg.validate_paid_escalation_gate_record(loaded)


# ===========================================================================
# 3. gate audit validator fail-closed mutation 矩阵
# ===========================================================================


def _authorized_record(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(
        cg.ENV_AUTH, cg.scope_string(_TASK_ID, "hermes", "zzz-paid", "remote-api")
    )
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, _out_dir, _state = _run(reg, tmp_path=tmp_path)
    return dict(_gate(outcome))


def _blocked_record(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, _out_dir, _state = _run(reg, tmp_path=tmp_path)
    return dict(_gate(outcome))


def test_gate_validator_rejects_attempted_or_used(tmp_path, monkeypatch):
    rec = _authorized_record(tmp_path, monkeypatch)
    fpg.validate_paid_escalation_gate_record(rec)
    for field in ("fallback_attempted", "fallback_used"):
        with pytest.raises(ValueError):
            fpg.validate_paid_escalation_gate_record(dict(rec, **{field: True}))


def test_gate_validator_rejects_paid_escalation_false(tmp_path, monkeypatch):
    rec = _blocked_record(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, paid_escalation_required=False)
        )


def test_gate_validator_rejects_unknown_gate_decision(tmp_path, monkeypatch):
    rec = _blocked_record(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, gate_decision="MAYBE")
        )


def test_gate_validator_authorized_consistency(tmp_path, monkeypatch):
    """AUTHORIZED ↔ A0 ALLOWED_AUTHORIZED_PAID + exact scope + flags True。"""
    rec = _authorized_record(tmp_path, monkeypatch)
    fpg.validate_paid_escalation_gate_record(rec)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, authorization_matched=False)
        )
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, guard_decision=cg.DECISION_BLOCKED_COST_APPROVAL)
        )
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, gate_decision=fpg.GATE_DECISION_BLOCKED)
        )
    # matched=True 但非 AUTHORIZED → ValueError（gate BLOCKED 时 matched 必须 False）
    bad = _blocked_record(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(bad, authorization_matched=True)
        )
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(bad, gate_decision=fpg.GATE_DECISION_AUTHORIZED)
        )


def test_gate_validator_rejects_final_switch_and_tamper(tmp_path, monkeypatch):
    rec = _blocked_record(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, final_actual_model="someone-else")
        )
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(dict(rec, extra_field=1))
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(dict(rec, authority="tampered"))
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, decision_kind="fallback_runtime_audit")
        )
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, failure_class=fc.FAILURE_FRAMEWORK_INPUT_CONFIG)
        )


def test_gate_validator_rejects_source_guard_record_invariants(
    tmp_path, monkeypatch
):
    """FIX-001：source_guard_record 必须 dict/None 且 JSON 可序列化（raw 证据
    形状绝不允许使 authoritative audit 无法持久化，Requirement 3/6/7）。"""
    rec = _blocked_record(tmp_path, monkeypatch)
    assert isinstance(rec["source_guard_record"], dict)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, source_guard_record=[])
        )
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, source_guard_record={"bad": {1, 2}})
        )
    # 移除 source 字段 = missing required field → 拒
    stripped = dict(rec)
    stripped.pop("source_guard_record")
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(stripped)


def test_gate_validator_still_rejects_contradictory_fail_closed_shapes(
    tmp_path, monkeypatch
):
    """FIX-001 防御纵深：即使有人手造内部矛盾的 FAIL_CLOSED record（Codex
    blocker 形状——FAIL_CLOSED + matched=True / FAIL_CLOSED + in-scope
    ALLOWED_AUTHORIZED_PAID），validator 仍拒绝——normalized 自洽性不变量
    （Requirement 5）保持。interpret_guard 修复后这些形状不再被产出；validator
    依然把它们挡在持久化之前。"""
    # FAIL_CLOSED + matched=True（BLOCKED record 基础上翻转）
    rec = _blocked_record(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, gate_decision=fpg.GATE_DECISION_FAIL_CLOSED,
                 authorization_matched=True)
        )
    # FAIL_CLOSED + in-scope ALLOWED_AUTHORIZED_PAID token（exact-scope
    # authorized 必须映射 AUTHORIZED——除非 flags/scope 真，否则拒）
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, gate_decision=fpg.GATE_DECISION_FAIL_CLOSED,
                 guard_decision=cg.DECISION_ALLOWED_AUTHORIZED_PAID)
        )
    # FAIL_CLOSED + 未知 guard token
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, gate_decision=fpg.GATE_DECISION_FAIL_CLOSED,
                 guard_decision="SOMETHING_ELSE")
        )


def test_gate_validator_rejects_candidate_consistency(tmp_path, monkeypatch):
    rec = _blocked_record(tmp_path, monkeypatch)
    fpg.validate_paid_escalation_gate_record(rec)
    # paid_candidate 不在 paid_candidates
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, paid_candidate="other@remote-api")
        )
    # paid_candidates 超集 contract_candidates
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, paid_candidates=["zzz-paid@remote-api", "other@remote-api"])
        )
    # paid candidate == original
    orig_key = mr.canonical_key(rec["original_model"], rec["original_provider"])
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(rec, paid_candidate=orig_key,
                 paid_candidate_model=rec["original_model"],
                 paid_candidate_provider=rec["original_provider"])
        )


# ===========================================================================
# 4. 真实 runner Hermes stage 集成
# ===========================================================================

_TASK_TMPL = """AAF_TASK_BEGIN
# Task ID
{task_id}

# Task Name
a5 paid escalation gate runner integration

# Workspace
D:\\AdyAI\\ai-agent-framework

# Objective
{objective}

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过

AAF_TASK_END
"""


def _task(risk: str | None, task_id: str = "A5PG-RUN") -> str:
    body = _TASK_TMPL.format(task_id=task_id,
                             objective="验证 A5 paid escalation Cost Gate。")
    if risk is not None:
        body = body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)
    return body


def _structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = ('{"verdict": "PASS", "blocking_rework": false, '
                 '"blocking_provenance": "structured", "findings": [], "warnings": []}')
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END"


def _run_runner(tmp_path, monkeypatch, task_text, fake_run_agent=None):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    if fake_run_agent is None:
        fake_run_agent = lambda agent, prompt, workspace: _structured_ok(agent)  # noqa: E731
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    runner_mod.run(task_file, ws, out)
    return out


def _failing_hermes_first(counter):
    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            counter["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)
    return fake_run_agent


def _pg_registry(extra_free: bool = False) -> dict:
    entries = [_local_entry("aaa-orig"), _entry("zzz-paid")]
    if extra_free:
        entries.append(_entry("fb-1", cost=LOCAL_FREE, provider="custom",
                              base_url="http://127.0.0.1:11434/v1",
                              locality=mr.LOCALITY_LOCAL))
    return _registry(*entries)


def test_runner_paid_only_no_auth_blocked_waiting(tmp_path, monkeypatch):
    """真实 runner：paid-only 候选 + 无 auth → 恰 1 次 hermes invocation（无
    paid 执行）、gate BLOCKED artifact + stage ref、runtime audit not-eligible、
    WAITING、env 还原。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _pg_registry())
    counter = {"n": 0}
    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW),
                      _failing_hermes_first(counter))
    assert counter["n"] == 1  # 无第二模型 invocation（no silent paid）
    gate = fpg.load_paid_gate(out)
    assert gate is not None
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert gate["authorization_present"] is False
    fpg.validate_paid_escalation_gate_record(gate)
    rt = fr.load_fallback_runtime(out)
    assert rt["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rt["fallback_attempted"] is False
    fr.validate_fallback_runtime_record(rt)
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage.get("paid_escalation_gate_ref", {}).get("entry") == "hermes"
    assert "paid_escalation_gate" in stage["paid_escalation_gate_ref"]["authority"]
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")  # 原始失败保留
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    assert cg.ENV_MODEL not in os.environ  # env 不泄漏


def test_runner_exact_auth_authorized_no_paid_invocation(tmp_path, monkeypatch):
    """真实 runner：paid-only 候选 + exact auth → gate AUTHORIZED（仍 WAITING
    ——授权只建立未来 paid invocation 资格，本任务绝不执行）；恰 1 次 invocation
    （无 paid 执行）；A0 一次性消费 marker 存在；stage ref 存在；env 还原。"""
    task_id = "A5PG-RUN"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _pg_registry())
    auth = cg.scope_string(task_id, "hermes", "zzz-paid", "remote-api")
    monkeypatch.setenv(cg.ENV_AUTH, auth)
    counter = {"n": 0}
    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW, task_id),
                      _failing_hermes_first(counter))
    assert counter["n"] == 1  # 授权 ≠ 执行：无 paid invocation
    gate = fpg.load_paid_gate(out)
    assert gate is not None
    assert gate["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
    assert gate["authorization_matched"] is True
    assert gate["authorization_consumed"] is True
    assert gate["fallback_attempted"] is False
    fpg.validate_paid_escalation_gate_record(gate)
    assert (out / cg.CONSUMPTION_FILENAME).exists()  # A0 一次性 claim（既有语义）
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage.get("paid_escalation_gate_ref", {}).get("entry") == "hermes"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"  # 无自动继续/无 paid 执行
    assert cg.ENV_MODEL not in os.environ


def test_runner_paid_only_mismatched_auth_blocked(tmp_path, monkeypatch):
    """真实 runner：mismatched auth → gate BLOCKED、WAITING、无 paid 执行。"""
    task_id = "A5PG-RUN"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _pg_registry())
    monkeypatch.setenv(cg.ENV_AUTH, f"{task_id}|validator|zzz-paid|remote-api")
    counter = {"n": 0}
    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW, task_id),
                      _failing_hermes_first(counter))
    assert counter["n"] == 1
    gate = fpg.load_paid_gate(out)
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert gate["authorization_present"] is True
    assert gate["authorization_matched"] is False
    fpg.validate_paid_escalation_gate_record(gate)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    assert cg.ENV_MODEL not in os.environ


def test_runner_free_candidate_precedence_free_fallback_success(tmp_path, monkeypatch):
    """真实 runner：free + paid 候选都在 → FREE fallback 照常执行并成功
    （2 次 invocation = original + free fallback、SUCCESS），paid escalation
    gate 完全不运行（无 artifact、无 gate ref）——FREE 行为保持 + free 优先。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _pg_registry(extra_free=True))
    seen = {"hermes_calls": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen["hermes_calls"] += 1
            if seen["hermes_calls"] == 1:
                raise RuntimeError("original invocation failed (simulated)")
            return _structured_ok(agent)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert seen["hermes_calls"] == 2  # original + 恰一次 free fallback
    rt = fr.load_fallback_runtime(out)
    assert rt["fallback_attempted"] is True
    assert rt["fallback_used"] is True
    assert rt["fallback_candidate"] == "fb-1@custom"
    assert rt["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE
    fr.validate_fallback_runtime_record(rt)
    assert fpg.load_paid_gate(out) is None  # gate 未运行（free 优先）
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert "paid_escalation_gate_ref" not in stage
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    assert cg.ENV_MODEL not in os.environ
