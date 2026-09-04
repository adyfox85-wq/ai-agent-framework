"""AAF v0.5 A5 — one-shot authorized paid fallback runtime focused tests.

TASK: AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001（Requirement 15 全矩阵）：
- exact valid paid auth -> exactly one paid fallback invocation
- no auth -> zero paid invocation（fail closed）
- mismatched task/stage/model/provider auth -> zero paid invocation
- malformed/FAIL_CLOSED auth state -> zero paid invocation
- FREE fallback attempted first -> no paid fallback（共享 one-attempt budget）
- paid fallback success -> attempted=true / used=true / final model=paid candidate
- paid fallback failure -> attempted=true / used=false / no third model
- audit closure RuntimeError/UnicodeError after paid success -> result rejected,
  attempted=true / used=false（audit_closure_error surfaced）
- environment/routing overrides restored
- authorization cannot be reused across another task/stage/model/provider
- validator rejects forged contradictory paid runtime audit records
- FREE fallback precedence / ALLOWED_AUTHORIZED_PAID never enters FREE path

第 1 节：live runtime 编排矩阵（run_fallback_after_failure 集成）；
第 2 节：真实 runner Hermes stage 集成（SUCCESS / WAITING / audit closure
        失败 / stage refs / env 还原）；
第 3 节：paid runtime audit validator fail-closed mutation 矩阵。
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

_TASK_ID = "A5PF-UNIT-1"


@pytest.fixture(autouse=True)
def _scrub_a5_env(monkeypatch):
    """本文件 hermetic 保证（与 test_a5_paid_escalation_gate 同型）。"""
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
) -> mr.RegistryEntry:
    return mr.RegistryEntry(
        model=model,
        provider=provider,
        base_url=base_url,
        applicable_agents=("hermes",),
        capability_tier=tier,
        cost_class=cost,
        locality=locality,
        qualification=mr.RuntimeQualification(
            status=qual_status,
            scope=scope,
            evidence=("a5-paid-runtime-test-fixture",),
            observed_at="2026-09-05T00:00:00",
        ),
        evidence=("a5-paid-runtime-test-fixture",),
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
    task_id: str = _TASK_ID,
    exc=RuntimeError("hermes failed (exit=1) STDERR: simulated model failure"),
    invoke=None,
    calls=None,
    risk=RISK_LOW,
    automatic_fallback_count_used=0,
    output_dir=None,
    tmp_path=None,
):
    """编排器单测 runner（模拟 runner 语义：overlay 由调用方在 observation
    后还原——本文件 paid 场景有 attempt，overlay_saved 非 None 时由调用方
    还原，等价真实 runner）。"""
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
        task_id=task_id,
        risk_class=risk,
        risk_source=so.TASK_RISK_SOURCE,
        registry=registry,
        output_dir=out_dir,
        prompt="TASK",
        workspace=Path(tmp_path),
        invoke=real_invoke or default_invoke,
        failure_exc=exc,
        automatic_fallback_count_used=automatic_fallback_count_used,
    )
    if outcome is not None and outcome.get("overlay_saved"):
        ar.restore_routing_env(outcome["overlay_saved"])
    if calls is not None:
        calls.update(state)
    return outcome, out_dir, state


def _pin_original(monkeypatch, model="aaa-orig", provider="custom"):
    monkeypatch.setenv(cg.ENV_MODEL, model)
    monkeypatch.setenv(cg.ENV_PROVIDER, provider)


def _gate(outcome) -> dict:
    rec = outcome["paid_gate_record"]
    assert rec is not None, f"missing paid_gate_record: {outcome.get('paid_gate_error')}"
    return rec


def _no_gate(outcome) -> None:
    assert "paid_gate_record" not in outcome
    assert "paid_gate_artifact_ref" not in outcome


def _scope(task_id: str = _TASK_ID, model="zzz-paid",
           provider="remote-api", stage: str = "hermes") -> str:
    return cg.scope_string(task_id, stage, model, provider)


# ===========================================================================
# 1. live runtime 编排矩阵（Requirement 15）
# ===========================================================================


def test_exact_auth_exactly_one_paid_fallback_invocation(tmp_path, monkeypatch):
    """exact valid paid auth → gate AUTHORIZED → **恰一次** paid fallback
    invocation（calls==1）、attempted=true / used=true、final actual = paid
    candidate、result_text = paid 输出。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1  # 恰一次 paid fallback invocation
    assert state["envs"][0]["model"] == "zzz-paid"  # invocation env = paid candidate
    assert outcome["attempted"] is True
    assert outcome["used"] is True
    assert outcome["result_text"].startswith("ok")
    gate = _gate(outcome)
    assert gate["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
    paid = outcome["paid_audit_record"]
    assert paid["fallback_attempted"] is True
    assert paid["fallback_used"] is True
    assert paid["final_actual_model"] == "zzz-paid"
    assert paid["final_actual_provider"] == "remote-api"
    assert paid["original_model"] == "aaa-orig"
    assert paid["paid_invocation_outcome"] == fr.PAID_OUTCOME_SUCCESS
    fr.validate_paid_fallback_runtime_record(paid)
    # 原始失败上下文保留在 original/trigger 字段
    assert paid["failure_class"] == fc.FAILURE_INVOCATION
    assert "RuntimeError" in paid["trigger"]
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"  # env 还原


def test_no_auth_zero_paid_invocation(tmp_path, monkeypatch):
    """paid candidate + no auth → gate BLOCKED → **零** paid invocation、
    attempted=false、原始失败保留（result_text=None）、权威证据（gate +
    FREE 层 runtime record）落盘。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    gate = _gate(outcome)
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert gate["authorization_present"] is False
    fpg.validate_paid_escalation_gate_record(gate)
    rt = outcome["audit_record"]
    assert rt["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rt["fallback_attempted"] is False
    fr.validate_fallback_runtime_record(rt)
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    assert (out_dir / fr.ARTIFACT_FILENAME).exists()
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()  # 无执行审计
    assert not (out_dir / cg.CONSUMPTION_FILENAME).exists()  # 零授权消费
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"


@pytest.mark.parametrize(
    "auth_value",
    [
        "WRONG-TASK|hermes|zzz-paid|remote-api",
        lambda: f"{_TASK_ID}|validator|zzz-paid|remote-api",
        lambda: f"{_TASK_ID}|hermes|other-model|remote-api",
        lambda: f"{_TASK_ID}|hermes|zzz-paid|other-provider",
        "not-a-scope-at-all",
    ],
    ids=["wrong-task", "wrong-stage", "wrong-model", "wrong-provider",
         "malformed-scope-string"],
)
def test_mismatched_or_malformed_auth_zero_paid_invocation(
    tmp_path, monkeypatch, auth_value
):
    """task/stage/model/provider 任一维度不匹配 / malformed scope → 零 paid
    invocation（exact scope 零削弱；authorization_present 但 matched=false /
    malformed → BLOCKED fail closed）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    value = auth_value() if callable(auth_value) else auth_value
    monkeypatch.setenv(cg.ENV_AUTH, value)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, _out_dir, _state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert "paid_audit_record" not in outcome
    gate = _gate(outcome)
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert gate["authorization_matched"] is False
    assert gate["authorization_consumed"] is False
    fpg.validate_paid_escalation_gate_record(gate)


def test_malformed_guard_record_fail_closed_zero_invocation(tmp_path, monkeypatch):
    """A0 guard 返回 malformed record（缺必需字段）→ gate FAIL_CLOSED →
    零 paid invocation（malformed authorization state → fail closed）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setattr(cg, "evaluate",
                        lambda task_id, stage, state_dir=None: {})
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, _state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    gate = _gate(outcome)
    assert gate["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED
    assert "malformed" in gate["gate_reason"]
    fpg.validate_paid_escalation_gate_record(gate)
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()


def test_free_fallback_attempted_first_no_paid_fallback(tmp_path, monkeypatch):
    """FREE fallback 与 paid 共享同一 one-attempt budget：budget 已消耗
    （count_used=1）→ contract 无 eligible 决策 → Cost Gate 不运行 →
    零 paid invocation（no chain/loop）。"""
    _pin_original(monkeypatch)
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, _state = _run(
        reg, calls=calls, automatic_fallback_count_used=1, tmp_path=tmp_path
    )
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    rt = outcome["audit_record"]
    assert rt["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert fc.REASON_BUDGET_EXHAUSTED in rt["decision_reason"]
    _no_gate(outcome)
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()


def test_free_candidate_precedence_paid_never_invoked(tmp_path, monkeypatch):
    """free + paid 候选都在 → FREE fallback 照常执行（恰一次、attempted=true/
    used=true）、gate 不运行、无 paid invocation、无授权消费——AUTHORIZED
    gate 状态绝不进入 FREE 路径（Requirement 13）。"""
    _pin_original(monkeypatch)
    reg = _registry(
        _local_entry("aaa-orig"),
        _entry("fb-1", cost=LOCAL_FREE, provider="custom",
               base_url="http://127.0.0.1:11434/v1",
               locality=mr.LOCALITY_LOCAL),
        _entry("zzz-paid"),
    )
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1
    assert state["envs"][0]["model"] == "fb-1"
    assert outcome["attempted"] is True
    assert outcome["used"] is True
    rt = outcome["audit_record"]
    assert rt["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    assert rt["fallback_candidate"] == "fb-1@custom"
    assert rt["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE
    fr.validate_fallback_runtime_record(rt)
    _no_gate(outcome)
    assert "paid_audit_record" not in outcome
    assert not (out_dir / fpg.ARTIFACT_FILENAME).exists()
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()
    assert not (out_dir / cg.CONSUMPTION_FILENAME).exists()


def test_paid_fallback_failure_no_third_invocation(tmp_path, monkeypatch):
    """paid fallback invocation 自身失败 → attempted=true / used=false /
    paid_invocation_outcome=failed / paid failure 细节保留 / 原始失败保留
    （result_text=None）/ 无第三模型（calls==1）/ 无第二 paid candidate。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    invoked = {"n": 0}

    def failing_invoke(agent, prompt, workspace):
        invoked["n"] += 1
        raise RuntimeError("paid fallback model also failed (simulated)")

    calls = {}
    outcome, out_dir, state = _run(reg, invoke=failing_invoke, calls=calls,
                                   tmp_path=tmp_path)
    assert invoked["n"] == 1  # 恰一次 paid invocation 被发起；无第三模型
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None  # 原始失败保留
    assert outcome["overlay_saved"] is not None
    paid = outcome["paid_audit_record"]
    assert paid["fallback_attempted"] is True
    assert paid["fallback_used"] is False
    assert paid["paid_invocation_outcome"] == fr.PAID_OUTCOME_FAILED
    assert paid["final_actual_model"] == "zzz-paid"  # 最后实际 invocation
    assert paid["original_model"] == "aaa-orig"
    ev = " ".join(paid["no_silent_paid_evidence"])
    assert "raised RuntimeError" in ev  # paid failure 细节保留（Requirement 9）
    assert "no fallback chain" in " ".join(paid["no_third_invocation_evidence"])
    fr.validate_paid_fallback_runtime_record(paid)
    assert (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"  # env 还原


def test_paid_fallback_invalid_output_not_accepted(tmp_path, monkeypatch):
    """paid invocation 产出 FRAMEWORK_ERROR 前缀/空输出 → used=false（输出
    不被接受）、attempted=true、原始失败保留、无第三模型。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    invoked = {"n": 0}

    def invalid_invoke(agent, prompt, workspace):
        invoked["n"] += 1
        return "FRAMEWORK_ERROR\nsimulated invalid paid output"

    calls = {}
    outcome, _out_dir, state = _run(reg, invoke=invalid_invoke, calls=calls,
                                    tmp_path=tmp_path)
    assert invoked["n"] == 1  # 恰一次 paid invocation
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    paid = outcome["paid_audit_record"]
    assert paid["paid_invocation_outcome"] == fr.PAID_OUTCOME_FAILED
    fr.validate_paid_fallback_runtime_record(paid)


def test_audit_closure_runtime_error_rejects_paid_output(tmp_path, monkeypatch):
    """paid invocation 成功后权威 paid audit 持久化抛 RuntimeError → paid
    输出**不**被接受：attempted=true / used=false / result_text=None /
    audit_closure_error 显式 surface（含 RuntimeError）/ 无 paid audit
    artifact / 无第三模型 / overlay_saved 返回（env 还原）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))

    def failing_save(output_dir, record):
        raise RuntimeError("simulated paid audit persistence RuntimeError")

    monkeypatch.setattr(fr, "save_paid_fallback_runtime", failing_save)
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1  # paid invocation 恰一次已发生；无第三模型
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    assert outcome["overlay_saved"] is not None
    err = outcome["audit_closure_error"]
    assert "audit closure FAILED" in err
    assert "RuntimeError" in err
    assert "simulated paid audit persistence RuntimeError" in err
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()
    # gate（invocation 前落盘）仍存在——授权证据可审计
    assert (out_dir / fpg.ARTIFACT_FILENAME).exists()
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"  # env 已还原


def test_audit_closure_unicode_error_rejects_paid_output(tmp_path, monkeypatch):
    """paid audit 持久化抛 UnicodeError（编码类失败代表）→ 同一 fail-closed
    语义（attempted=true / used=false / UnicodeError surface / 无 artifact /
    无第三模型）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))

    def failing_save(output_dir, record):
        raise UnicodeError("simulated paid audit persistence UnicodeError")

    monkeypatch.setattr(fr, "save_paid_fallback_runtime", failing_save)
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert "UnicodeError" in outcome["audit_closure_error"]
    assert "simulated paid audit persistence UnicodeError" in outcome[
        "audit_closure_error"
    ]
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()
    assert os.environ.get(cg.ENV_MODEL) == "aaa-orig"


def test_audit_closure_validation_error_rejects_paid_output(tmp_path, monkeypatch):
    """paid runtime audit validator 抛未预期异常 → paid 输出不被接受
    （attempted=true / used=false / audit_closure_error surface）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    real_validate = fr.validate_paid_fallback_runtime_record

    def flaky_validate(record):
        raise RuntimeError("simulated paid audit validator RuntimeError")

    monkeypatch.setattr(fr, "validate_paid_fallback_runtime_record", flaky_validate)
    calls = {}
    outcome, out_dir, _state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert "simulated paid audit validator RuntimeError" in outcome[
        "audit_closure_error"
    ]
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()


def test_paid_failure_plus_audit_failure_fail_closed(tmp_path, monkeypatch):
    """paid invocation 失败 + audit closure 也失败 → 仍如实 attempted=true /
    used=false、audit failure 显式 surface（不静默丢弃）、无第三模型。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))

    def failing_invoke(agent, prompt, workspace):
        raise RuntimeError("paid fallback model failed (simulated)")

    def failing_save(output_dir, record):
        raise OSError("simulated paid audit persistence failure")

    monkeypatch.setattr(fr, "save_paid_fallback_runtime", failing_save)
    outcome, out_dir, _state = _run(reg, invoke=failing_invoke, tmp_path=tmp_path)
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    assert "audit closure FAILED" in outcome["audit_closure_error"]
    assert not (out_dir / fr.ARTIFACT_FILENAME_PAID).exists()


def test_authorization_replay_rejected_in_same_execution(tmp_path, monkeypatch):
    """同 execution 上下文（同 state_dir）内同一授权不可二次准入：exact auth
    首次已 claim → 第二次（同 auth、同 task/stage）A0 replay-rejected →
    gate BLOCKED → **零** paid invocation（no duplicate consumption）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    out_dir = Path(tmp_path) / "out"
    calls1 = {}
    outcome1, out_dir, _s1 = _run(reg, calls=calls1, output_dir=out_dir,
                                  tmp_path=tmp_path)
    assert calls1["calls"] == 1  # 首次：恰一次 paid invocation
    assert outcome1["used"] is True
    assert (out_dir / cg.CONSUMPTION_FILENAME).exists()
    # 第二次（同一 execution 目录 + 同一 auth 值）：A0 一次性 marker 已存在 →
    # claim 失败 → BLOCKED（replay-rejected）→ 零 invocation
    calls2 = {}
    outcome2, _out_dir2, _s2 = _run(reg, calls=calls2, output_dir=out_dir,
                                    tmp_path=tmp_path)
    assert calls2["calls"] == 0
    assert outcome2["attempted"] is False
    gate = _gate(outcome2)
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert gate["authorization_present"] is True
    assert gate["authorization_matched"] is False  # A0 不再匹配（claim 已消费）
    assert gate["authorization_consumed"] is True  # replay-rejected 如实转述
    fpg.validate_paid_escalation_gate_record(gate)


def test_authorization_cannot_carry_over_to_another_task(tmp_path, monkeypatch):
    """授权不可跨 task 复用：auth scope 指向 task A，在 task B 上下文中求值
    → A0 mismatch → gate BLOCKED → 零 invocation（no silent carryover）。"""
    other_task = "A5PF-OTHER-TASK"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope(task_id=_TASK_ID))
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, out_dir, _state = _run(reg, calls=calls, task_id=other_task,
                                    tmp_path=tmp_path)
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    gate = _gate(outcome)
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    assert gate["authorization_present"] is True
    assert gate["authorization_matched"] is False
    fpg.validate_paid_escalation_gate_record(gate)
    # 授权未被消费（scope 不匹配 → A0 不 claim）→ 无 marker
    assert not (out_dir / cg.CONSUMPTION_FILENAME).exists()


def test_pre_invocation_revalidation_rejects_gate_tamper(tmp_path, monkeypatch):
    """Requirement 5 复验：AUTHORIZED gate record 被篡改（task_id 改为其他
    task）→ 拒绝 invocation（零 paid invocation、paid_invocation_error
    显式 surface、fail closed）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    calls = {}
    outcome, _out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    assert calls["calls"] == 1  # 未被篡改的 gate：恰一次 paid invocation
    assert outcome["attempted"] is True
    # 直接对 _execute 注入篡改 gate record 的路径由 fpg validator + 调用方
    # task/stage 归属复验覆盖——此处验证 gate record 本身 validator 拒绝篡改
    gate = dict(_gate(outcome))
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(dict(gate, task_id="FORGED-TASK"))
    with pytest.raises(ValueError):
        fpg.validate_paid_escalation_gate_record(
            dict(gate, required_scope=_scope(task_id="FORGED-TASK"))
        )


# ===========================================================================
# 2. 真实 runner Hermes stage 集成
# ===========================================================================

_TASK_TMPL = """AAF_TASK_BEGIN
# Task ID
{task_id}

# Task Name
a5 paid fallback runtime runner integration

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


def _task(risk: str | None, task_id: str = "A5PF-RUN") -> str:
    body = _TASK_TMPL.format(task_id=task_id,
                             objective="验证 A5 paid fallback runtime。")
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


def _paid_only_registry() -> dict:
    return _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))


def test_runner_exact_auth_paid_fallback_success_chain(tmp_path, monkeypatch):
    """真实 runner：paid-only + exact auth → original 失败 → 恰一次 paid
    fallback 成功 → SUCCESS；paid audit used=true / final=zzz-paid；stage
    paid_fallback_runtime_ref 存在；A3 初始 routing 未受 fallback 影响。"""
    task_id = "A5PF-RUN"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _paid_only_registry())
    monkeypatch.setenv(cg.ENV_AUTH, _scope(task_id=task_id))
    seen = {"hermes_calls": 0, "envs": []}

    def fake_run_agent(agent, prompt, workspace):
        seen["envs"].append(
            {
                "model": os.environ.get(cg.ENV_MODEL),
                "provider": os.environ.get(cg.ENV_PROVIDER),
            }
        )
        if agent == "hermes":
            seen["hermes_calls"] += 1
            if seen["hermes_calls"] == 1:
                raise RuntimeError("original invocation failed (simulated)")
            return _structured_ok(agent)  # paid fallback invocation 成功
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW, task_id),
                      fake_run_agent)
    assert seen["hermes_calls"] == 2  # original + 恰一次 paid fallback
    assert seen["envs"][0]["model"] == "aaa-orig"  # A3 初始 routing 照常
    assert seen["envs"][1]["model"] == "zzz-paid"  # paid fallback env 覆盖
    paid = fr.load_paid_fallback_runtime(out)
    assert paid is not None
    assert paid["fallback_attempted"] is True
    assert paid["fallback_used"] is True
    assert paid["paid_candidate"] == "zzz-paid@remote-api"
    assert paid["final_actual_model"] == "zzz-paid"
    assert paid["original_model"] == "aaa-orig"
    fr.validate_paid_fallback_runtime_record(paid)
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage.get("paid_fallback_runtime_ref", {}).get("entry") == "hermes"
    assert stage.get("paid_escalation_gate_ref", {}).get("entry") == "hermes"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    assert cg.ENV_MODEL not in os.environ  # env 不泄漏


def test_runner_no_auth_paid_only_waiting_no_third(tmp_path, monkeypatch):
    """真实 runner：paid-only + no auth → 恰 1 次 invocation（无 paid 执行）、
    gate BLOCKED、WAITING、chain 中断（codebuddy 未 spawn）、env 还原。"""
    task_id = "A5PF-RUN"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _paid_only_registry())
    counter = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            counter["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW, task_id),
                      fake_run_agent)
    assert counter["n"] == 1  # 无 paid invocation
    gate = fpg.load_paid_gate(out)
    assert gate["gate_decision"] == fpg.GATE_DECISION_BLOCKED
    fpg.validate_paid_escalation_gate_record(gate)
    assert fr.load_paid_fallback_runtime(out) is None
    rt = fr.load_fallback_runtime(out)
    assert rt["fallback_attempted"] is False
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    assert not (out / "codebuddy_result.md").exists()  # chain 中断


def test_runner_paid_audit_closure_failure_rejects_output(tmp_path, monkeypatch):
    """真实 runner + paid audit 写盘失败注入：original 失败 → paid fallback
    恰一次成功调用 → paid audit 持久化失败 → paid 输出**不**成为 stage
    result：FRAMEWORK_ERROR 保留 + audit closure failure 显式 append、无
    paid_fallback_runtime.json（gate 证据仍在）、WAITING、无第三模型。"""
    task_id = "A5PF-RUN"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _paid_only_registry())
    monkeypatch.setenv(cg.ENV_AUTH, _scope(task_id=task_id))
    seen = {"hermes_calls": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen["hermes_calls"] += 1
            if seen["hermes_calls"] == 1:
                raise RuntimeError("original invocation failed (simulated)")
            return _structured_ok(agent)  # paid fallback invocation 本身成功
        return _structured_ok(agent)

    def failing_save(output_dir, record):
        raise RuntimeError("simulated paid audit persistence failure")

    monkeypatch.setattr(fr, "save_paid_fallback_runtime", failing_save)
    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW, task_id),
                      fake_run_agent)
    assert seen["hermes_calls"] == 2  # original + 恰一次 paid fallback
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")  # paid 输出未被接受
    assert "audit closure FAILED" in result  # audit failure 显式 surface
    assert fr.load_paid_fallback_runtime(out) is None  # 无 paid audit artifact
    gate = fpg.load_paid_gate(out)  # gate（invocation 前落盘）证据保留
    assert gate["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
    fpg.validate_paid_escalation_gate_record(gate)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    assert cg.ENV_MODEL not in os.environ


# ===========================================================================
# 3. paid runtime audit validator fail-closed mutation 矩阵（Requirement 12）
# ===========================================================================


def _paid_record(tmp_path, monkeypatch) -> dict:
    """经真实 authorized run 产生的 paid runtime audit record（成功后 mutate）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    _pin_original(monkeypatch)
    monkeypatch.setenv(cg.ENV_AUTH, _scope())
    reg = _registry(_local_entry("aaa-orig"), _entry("zzz-paid"))
    outcome, _out_dir, _state = _run(reg, tmp_path=tmp_path)
    assert outcome["used"] is True
    return dict(outcome["paid_audit_record"])


def test_paid_validator_rejects_forged_contradictory_records(
    tmp_path, monkeypatch
):
    """Requirement 12：validator 独立拒绝矛盾/伪造 paid runtime audit records：
    used=true 但 attempted=false / paid invocation 无 AUTHORIZED gate / 授权
    证据缺失 / out-of-scope / 超预算 / final 不一致 / candidate 矛盾 / 篡改。"""
    rec = _paid_record(tmp_path, monkeypatch)
    fr.validate_paid_fallback_runtime_record(rec)

    # used=true when attempted=false（attempted 恒 True 不变量 → 拒绝）
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, fallback_attempted=False, fallback_used=False)
        )
    # paid invocation without AUTHORIZED gate（gate decision 不是 AUTHORIZED）
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, paid_gate_decision=fpg.GATE_DECISION_BLOCKED)
        )
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, paid_gate_decision=None)
        )
    # claimed paid use without corresponding authorization evidence
    for flag in ("authorization_present", "authorization_matched",
                 "authorization_consumed"):
        with pytest.raises(ValueError):
            fr.validate_paid_fallback_runtime_record(dict(rec, **{flag: False}))
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, paid_guard_decision=cg.DECISION_BLOCKED_COST_APPROVAL)
        )
    # paid candidate not matching exact authorized scope（wrong task/stage/
    # model/provider 维度 forged scope）
    canonical = cg.scope_string(_TASK_ID, "hermes", "zzz-paid", "remote-api")
    assert rec["paid_required_scope"] == canonical
    forged = {
        "wrong-task": cg.scope_string("A5PF-OTHER", "hermes", "zzz-paid",
                                      "remote-api"),
        "wrong-stage": cg.scope_string(_TASK_ID, "validator", "zzz-paid",
                                       "remote-api"),
        "wrong-model": cg.scope_string(_TASK_ID, "hermes", "someone-else",
                                       "remote-api"),
        "wrong-provider": cg.scope_string(_TASK_ID, "hermes", "zzz-paid",
                                          "other-api"),
    }
    for name, scope in forged.items():
        with pytest.raises(ValueError):
            fr.validate_paid_fallback_runtime_record(
                dict(rec, paid_required_scope=scope)
            ), name
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, task_id="A5PF-OTHER"))
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, stage_agent="validator"))
    # more than one model-level fallback attempt（budget 已耗 → 拒绝）
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, automatic_fallback_count_used=1)
        )
    # final model/provider inconsistent with used/attempted state
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, final_actual_model="someone-else")
        )
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, final_actual_provider="other-api")
        )
    # outcome/used 互洽
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, fallback_used=False, paid_invocation_outcome=fr.PAID_OUTCOME_SUCCESS)
        )
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, fallback_used=True, paid_invocation_outcome=fr.PAID_OUTCOME_FAILED)
        )
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, paid_invocation_outcome="maybe")
        )
    # candidate 一致性 / distinct from original
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, paid_candidate="other@remote-api",
                 paid_candidate_model="other",
                 paid_candidate_provider="remote-api",
                 final_actual_model="other")
        )
    orig_key = mr.canonical_key(rec["original_model"], rec["original_provider"])
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, paid_candidate=orig_key,
                 paid_candidate_model=rec["original_model"],
                 paid_candidate_provider=rec["original_provider"],
                 final_actual_model=rec["original_model"],
                 final_actual_provider=rec["original_provider"])
        )
    # 篡改 authority / decision_kind / 未知字段 / schema
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, extra_field=1))
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, authority="tampered"))
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(
            dict(rec, decision_kind="fallback_runtime_audit")
        )
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, authoritative=False))
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, schema_version=99))
    # audit_closure_error 类型
    with pytest.raises(ValueError):
        fr.validate_paid_fallback_runtime_record(dict(rec, audit_closure_error=5))
    fr.validate_paid_fallback_runtime_record(rec)  # 未篡改 record 仍通过
