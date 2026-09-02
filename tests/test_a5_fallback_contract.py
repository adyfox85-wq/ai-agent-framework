"""AAF v0.5 A5 — fallback decision & audit contract focused tests.

TASK: AAF-v0.5-A5-FALLBACK-CONTRACT-001（Requirement 8 全矩阵）：
- 每个 failure-class 类别（含 Req 2 五类 + A5 scope minimum classes 余项）
- eligible vs non-eligible 决策
- same-model transport retry 不计为 fallback
- unknown/malformed 输入 fail closed
- audit schema required fields（Req 5）
- foundation：fallback_attempted / fallback_used 恒 False、无第二模型执行

本文件只 import 被测模块 fallback_contract（+ A1 构造 fixture 所需
RegistryEntry / RuntimeQualification）；不触碰任何 runner / 路由执行路径。
"""

import json

import pytest

from ai_agent_framework import fallback_contract as fc
from ai_agent_framework.model_registry import (
    QUAL_SCOPE_AUXILIARY,
    QUAL_SCOPE_MAIN,
    QUAL_SCOPE_UNKNOWN,
    QUAL_STATUS_NOT_QUALIFIED,
    QUAL_STATUS_QUALIFIED,
    QUAL_STATUS_UNKNOWN,
    RegistryEntry,
    RuntimeQualification,
)

# ---------------------------------------------------------------------------
# Fixtures（受控候选池；全部 generic，不依赖真实 baseline 事实）
# ---------------------------------------------------------------------------


def _entry(
    model: str,
    *,
    provider: str = "test",
    agents: tuple[str, ...] = ("hermes",),
    tier: str | None = "T4",
    qual_status: str = QUAL_STATUS_QUALIFIED,
    qual_scope: str = QUAL_SCOPE_MAIN,
) -> RegistryEntry:
    return RegistryEntry(
        model=model,
        provider=provider,
        applicable_agents=agents,
        capability_tier=tier,
        qualification=RuntimeQualification(
            status=qual_status,
            scope=qual_scope,
            evidence=("test-fixture-evidence",),
            observed_at="2026-09-02T00:00:00",
        ),
    )


@pytest.fixture
def registry_qualified():
    """两个合格（main-scope、T4、QUALIFIED）的 hermes 候选。"""
    return {
        "fb-free-1@test": _entry("fb-free-1"),
        "fb-free-2@test": _entry("fb-free-2"),
    }


@pytest.fixture
def registry_no_candidate():
    """无合格候选：capability 未知 / qualification 未知 / auxiliary-only。"""
    return {
        "no-tier@test": _entry("no-tier", tier=None),
        "not-qualified@test": _entry(
            "not-qualified", qual_status=QUAL_STATUS_UNKNOWN
        ),
        "aux-only@test": _entry(
            "aux-only", qual_status=QUAL_STATUS_QUALIFIED,
            qual_scope=QUAL_SCOPE_AUXILIARY,
        ),
        "explicitly-not-qualified@test": _entry(
            "explicitly-not-qualified", qual_status=QUAL_STATUS_NOT_QUALIFIED
        ),
    }


def _decide(
    failure_class: str = fc.FAILURE_INVOCATION,
    registry=None,
    *,
    original_model: str = "orig-1",
    original_provider: str | None = "ds",
    role: str = "executor",
    risk_class: str = "LOW",
    trigger: str = "test trigger evidence",
    transport_retry_count: int = 0,
    automatic_fallback_count_used: int = 0,
    **extra,
):
    return fc.decide_fallback(
        failure_class=failure_class,
        trigger=trigger,
        task_id="AAF-v0.5-A5-FALLBACK-CONTRACT-001",
        stage_agent="hermes",
        role=role,
        risk_class=risk_class,
        risk_source="TASK.Risk field — planner-declared explicit risk",
        original_model=original_model,
        original_provider=original_provider,
        registry=registry if registry is not None else {},
        transport_retry_count=transport_retry_count,
        automatic_fallback_count_used=automatic_fallback_count_used,
        trigger_evidence=("evidence-ref-1",),
        **extra,
    )


# ---------------------------------------------------------------------------
# 1. Taxonomy：Req 2 五类 + scope 余项全覆盖
# ---------------------------------------------------------------------------


def test_taxonomy_covers_requirement_2_classes():
    labels = set(fc.FAILURE_LABELS.values())
    required = {
        "model/provider invocation failure",
        "unavailable/unsupported model or provider",
        "capability/qualification failure at execution boundary",
        "cost/authorization blocked condition",
        "non-fallback-eligible framework/input/configuration failure",
    }
    assert required <= labels
    # taxonomy 有界：token/label 一一对应；未知 token 不在词汇内
    assert set(fc.FAILURE_LABELS) == set(fc.FAILURE_CLASSES)
    for cls in fc.FAILURE_CLASSES:
        assert fc.FAILURE_LABELS[cls]


@pytest.mark.parametrize("failure_class", fc.FAILURE_CLASSES)
def test_each_failure_class_produces_valid_record(failure_class):
    record = _decide(failure_class=failure_class, registry={})
    assert record["failure_class"] == failure_class
    assert record["failure_label"] == fc.FAILURE_LABELS[failure_class]
    fc.validate_fallback_record(record)  # 不抛 = schema 合法


# ---------------------------------------------------------------------------
# 2. 决策矩阵：eligible vs non-eligible / paid / blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure_class", fc.TRIGGER_CAPABLE_CLASSES
)
def test_trigger_capable_with_qualified_candidate_is_eligible(
    failure_class, registry_qualified
):
    record = _decide(failure_class=failure_class, registry=registry_qualified)
    assert record["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    assert record["fallback_eligible"] is True
    assert record["paid_escalation_required"] is False
    # 两个合格候选 → 候选列表完整、无选择权（fallback_candidate=None）
    assert record["fallback_candidates"] == [
        "fb-free-1@test",
        "fb-free-2@test",
    ]
    assert record["fallback_candidate"] is None
    fc.validate_fallback_record(record)


@pytest.mark.parametrize(
    "failure_class", fc.TRIGGER_CAPABLE_CLASSES
)
def test_trigger_capable_without_candidate_is_not_eligible(
    failure_class, registry_no_candidate
):
    record = _decide(failure_class=failure_class, registry=registry_no_candidate)
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert record["fallback_eligible"] is False
    assert record["fallback_candidates"] == []
    assert record["decision_reason"].startswith(
        fc.REASON_NO_QUALIFIED_CANDIDATE
    )
    fc.validate_fallback_record(record)


@pytest.mark.parametrize(
    "failure_class", fc.TRIGGER_CAPABLE_CLASSES
)
def test_trigger_capable_empty_registry_is_not_eligible(failure_class):
    record = _decide(failure_class=failure_class, registry={})
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert record["fallback_candidates"] == []


@pytest.mark.parametrize(
    "failure_class",
    (fc.FAILURE_COST_AUTHORIZATION_BLOCKED, fc.FAILURE_FRAMEWORK_INPUT_CONFIG),
)
def test_blocked_classes_fail_closed_even_with_candidates(
    failure_class, registry_qualified
):
    # 即使存在合格候选也绝不 fallback_eligible：类边界优先于候选存在性
    record = _decide(failure_class=failure_class, registry=registry_qualified)
    assert record["decision"] == fc.DECISION_BLOCKED_FAIL_CLOSED
    assert record["fallback_eligible"] is False
    assert record["paid_escalation_required"] is False
    assert record["decision_reason"]
    fc.validate_fallback_record(record)


def test_cost_authorization_blocked_owned_by_a0(registry_qualified):
    record = _decide(
        failure_class=fc.FAILURE_COST_AUTHORIZATION_BLOCKED,
        registry=registry_qualified,
    )
    assert record["decision_reason"].startswith(fc.REASON_COST_AUTHORITY_OWNS)


def test_paid_escalation_required_never_automatic(registry_qualified):
    record = _decide(
        failure_class=fc.FAILURE_PAID_ESCALATION_REQUIRED,
        registry=registry_qualified,
    )
    assert record["decision"] == fc.DECISION_PAID_ESCALATION_REQUIRED
    assert record["paid_escalation_required"] is True
    assert record["fallback_eligible"] is False
    assert record["authorization_outcome"] == fc.AUTH_OUTCOME_NONE
    assert record["decision_reason"].startswith(fc.REASON_PAID_NEVER_AUTOMATIC)
    fc.validate_fallback_record(record)


def test_sole_qualified_candidate_is_recorded(registry_no_candidate):
    registry = dict(registry_no_candidate)
    registry["sole-ok@test"] = _entry("sole-ok")
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry)
    assert record["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    assert record["fallback_candidates"] == ["sole-ok@test"]
    assert record["fallback_candidate"] == "sole-ok@test"
    fc.validate_fallback_record(record)


# ---------------------------------------------------------------------------
# 3. 候选资格复用（无平行 qualification 系统 / 无 silent fallback）
# ---------------------------------------------------------------------------


def test_only_qualified_candidates_survive_gate(registry_no_candidate):
    # tier=None / qualification=unknown / NOT_QUALIFIED / auxiliary-only
    # 全部被既有 A1/A2 gate 排除 → 不出现在 fallback candidates
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry_no_candidate)
    assert record["fallback_candidates"] == []
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE


def test_executor_role_excludes_auxiliary_only_candidates():
    # A3-FIX（executor 主调用资格闸）在 fallback 候选枚举中原样生效：
    # auxiliary-only 候选绝不为 executor stage 提供 fallback。
    registry = {"aux-only@test": _entry(
        "aux-only", qual_status=QUAL_STATUS_QUALIFIED,
        qual_scope=QUAL_SCOPE_AUXILIARY)}
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry)
    assert record["fallback_candidates"] == []
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE


def test_unknown_scope_candidate_not_eligible_for_executor():
    registry = {"unknown-scope@test": _entry(
        "unknown-scope", qual_status=QUAL_STATUS_QUALIFIED,
        qual_scope=QUAL_SCOPE_UNKNOWN)}
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry)
    assert record["fallback_candidates"] == []
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE


def test_same_model_never_a_fallback_candidate():
    # original 也是 qualified 候选 → 从 fallback candidates 排除（same-model
    # 恢复 = retry 层，不是 fallback）；仍有其它候选 → eligible。
    registry = {
        "orig-1@ds": _entry("orig-1", provider="ds"),
        "fb-free-1@test": _entry("fb-free-1"),
    }
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry)
    assert record["fallback_candidates"] == ["fb-free-1@test"]
    assert record["fallback_candidate"] == "fb-free-1@test"
    assert any("same-model candidate excluded" in n for n in record["notes"])
    fc.validate_fallback_record(record)


def test_same_model_sole_candidate_is_not_fallback():
    registry = {"orig-1@ds": _entry("orig-1", provider="ds")}
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry)
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert record["fallback_candidates"] == []
    assert record["decision_reason"].startswith(fc.REASON_ONLY_SAME_MODEL)


def test_registry_non_entry_values_are_excluded_not_fatal():
    # selector 把非 RegistryEntry 值按 UNSUPPORTED 排除（不中断决策）
    registry = {
        "garbage@test": "not-an-entry",
        "fb-free-1@test": _entry("fb-free-1"),
    }
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry)
    assert record["fallback_candidates"] == ["fb-free-1@test"]
    assert record["decision"] == fc.DECISION_FALLBACK_ELIGIBLE


def test_capability_floor_respected_for_risk():
    # MEDIUM executor floor = T3 → T4 候选不足 → 不 eligible（能力先于一切）
    registry = {"fb-free-1@test": _entry("fb-free-1")}
    record = _decide(
        failure_class=fc.FAILURE_INVOCATION,
        registry=registry,
        risk_class="MEDIUM",
    )
    assert record["fallback_candidates"] == []
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE


# ---------------------------------------------------------------------------
# 4. same-model transport retry != model-level fallback
# ---------------------------------------------------------------------------


def test_transport_retry_not_counted_as_fallback(registry_qualified):
    base = _decide(failure_class=fc.FAILURE_TRANSPORT_RUNTIME, registry=registry_qualified)
    retried = _decide(
        failure_class=fc.FAILURE_TRANSPORT_RUNTIME,
        registry=registry_qualified,
        transport_retry_count=5,
    )
    # retry 不影响 fallback 预算/执行事实：count_used=0、attempted/used=False
    assert retried["transport_retry_count"] == 5
    assert retried["automatic_fallback_count_used"] == 0
    assert retried["fallback_attempted"] is False
    assert retried["fallback_used"] is False
    assert retried["decision"] == base["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    assert any("NOT counted as model-level fallback" in n for n in retried["notes"])
    assert any("never reported as model-level fallback" in e
               for e in retried["no_silent_fallback_evidence"])
    fc.validate_fallback_record(retried)


def test_transport_retry_on_no_candidate_still_not_fallback():
    record = _decide(
        failure_class=fc.FAILURE_TRANSPORT_RUNTIME,
        registry={},
        transport_retry_count=3,
    )
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert record["automatic_fallback_count_used"] == 0
    assert record["fallback_attempted"] is False
    assert record["fallback_used"] is False


# ---------------------------------------------------------------------------
# 5. one-fallback rule：no chain / no loop
# ---------------------------------------------------------------------------


def test_exhausted_budget_blocks_further_fallback(registry_qualified):
    # stage 已消耗 1 次 model-level fallback → 即使存在合格候选也拒绝再回退
    record = _decide(
        failure_class=fc.FAILURE_INVOCATION,
        registry=registry_qualified,
        automatic_fallback_count_used=1,
    )
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert record["decision_reason"].startswith(fc.REASON_BUDGET_EXHAUSTED)
    assert record["fallback_attempted"] is False
    fc.validate_fallback_record(record)


@pytest.mark.parametrize("bad_count", (2, 3, -1, "1", 1.5, True))
def test_count_beyond_one_fallback_budget_fails_closed(
    bad_count, registry_qualified
):
    with pytest.raises(ValueError):
        _decide(
            failure_class=fc.FAILURE_INVOCATION,
            registry=registry_qualified,
            automatic_fallback_count_used=bad_count,
        )


def test_budget_constant_is_one():
    assert fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE == 1


# ---------------------------------------------------------------------------
# 6. unknown / malformed 输入 fail closed（Req 7）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutator",
    [
        lambda kw: kw.update(failure_class="unknown-class"),
        lambda kw: kw.update(trigger="   "),
        lambda kw: kw.update(task_id=""),
        lambda kw: kw.update(stage_agent=""),
        lambda kw: kw.update(role="executioner"),
        lambda kw: kw.update(risk_class="EXTREME"),
        lambda kw: kw.update(risk_source=""),
        lambda kw: kw.update(original_model=""),
        lambda kw: kw.update(original_provider="  "),
        lambda kw: kw.update(registry="not-a-dict"),
        lambda kw: kw.update(registry=None),
        lambda kw: kw.update(transport_retry_count=-1),
        lambda kw: kw.update(transport_retry_count="3"),
        lambda kw: kw.update(automatic_fallback_count_used=9),
        lambda kw: kw.update(trigger_evidence=("ok", 42)),
        lambda kw: kw.update(trigger_evidence="not-a-tuple"),
    ],
)
def test_malformed_inputs_raise_value_error(mutator, registry_qualified):
    kwargs = dict(
        failure_class=fc.FAILURE_INVOCATION,
        trigger="test trigger",
        task_id="T-1",
        stage_agent="hermes",
        role="executor",
        risk_class="LOW",
        risk_source="provenance",
        original_model="orig-1",
        original_provider="ds",
        registry=registry_qualified,
    )
    mutator(kwargs)
    with pytest.raises(ValueError):
        fc.decide_fallback(**kwargs)


def test_unknown_failure_class_fails_closed():
    with pytest.raises(ValueError):
        _decide(failure_class="model_switch_quiet")


def test_risk_required_for_decision():
    with pytest.raises(ValueError):
        _decide(risk_class=None)


# ---------------------------------------------------------------------------
# 7. Audit schema（Req 5）：required fields + validate fail-closed
# ---------------------------------------------------------------------------


REQUIREMENT5_FIELDS = {
    "task_id",  # task/stage/role/risk（stage/role/risk 也分别在场）
    "stage_agent",
    "role",
    "risk_class",
    "original_model",  # original model/provider
    "original_provider",
    "failure_class",  # failure class / trigger
    "trigger",
    "fallback_eligible",  # fallback eligibility
    "fallback_candidates",  # fallback candidate if any
    "fallback_attempted",
    "fallback_used",
    "paid_escalation_required",
    "authorization_outcome",
    "final_actual_model",  # final actual model/provider
    "final_actual_provider",
    "no_silent_fallback_evidence",  # explicit no-silent-fallback evidence
}


def test_audit_record_contains_all_requirement_5_fields(registry_qualified):
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry_qualified)
    assert REQUIREMENT5_FIELDS <= set(record)
    # machine-readable：JSON 可序列化
    json.dumps(record)
    fc.validate_fallback_record(record)


@pytest.mark.parametrize(
    "required_key", sorted(REQUIREMENT5_FIELDS)
)
def test_validate_rejects_missing_required_field(required_key, registry_qualified):
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry_qualified)
    del record[required_key]
    with pytest.raises(ValueError):
        fc.validate_fallback_record(record)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda r: r.update(fallback_attempted=True),
        lambda r: r.update(fallback_used=True),
        lambda r: r.update(automatic_fallback_count_budget=2),
        lambda r: r.update(automatic_fallback_count_used=2),
        lambda r: r.update(final_actual_model="fb-free-1"),
        lambda r: r.update(final_actual_provider="test"),
        lambda r: r.update(fallback_eligible=False),  # 与 decision 矛盾
        lambda r: r.update(paid_escalation_required=True),  # 与 decision 矛盾
        lambda r: r.update(decision="silent_switch"),
        lambda r: r.update(failure_class="not-a-class"),
        lambda r: r.update(failure_label="wrong label"),
        lambda r: r.update(authorization_outcome="authorized"),  # foundation 无授权流
        lambda r: r.update(role="typo"),
        lambda r: r.update(risk_class="MAYBE"),
        lambda r: r.update(no_silent_fallback_evidence=[]),
        lambda r: r.update(fallback_candidates=["fb-free-1@test", "fb-free-1@test"]),
        lambda r: r.update(fallback_candidates=["not-sorted@test", "a@test"]),
        lambda r: r.setdefault("extra_key", "x"),
        lambda r: r.update(generated_at=""),
    ],
)
def test_validate_rejects_invariant_violations(mutator, registry_qualified):
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry_qualified)
    mutator(record)
    with pytest.raises(ValueError):
        fc.validate_fallback_record(record)


def test_not_eligible_requires_explicit_decision_reason():
    # not-eligible 决策必须给显式 no-fallback reason（不得静默无理由）
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry={})
    assert record["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    record["decision_reason"] = None
    with pytest.raises(ValueError):
        fc.validate_fallback_record(record)


def test_validate_rejects_attempted_without_candidate_excuse():
    # 任何 attempted=True 的 record 都非法——foundation 无执行权威，
    # 不存在「尝试过但没用」的合法中间态
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry={})
    record["fallback_attempted"] = True
    with pytest.raises(ValueError):
        fc.validate_fallback_record(record)


def test_eligible_decision_requires_candidates():
    record = _decide(failure_class=fc.FAILURE_INVOCATION, registry={})
    record["decision"] = fc.DECISION_FALLBACK_ELIGIBLE
    record["fallback_eligible"] = True
    with pytest.raises(ValueError):
        fc.validate_fallback_record(record)


def test_decision_reason_required_for_blocked_and_paid(registry_qualified):
    for cls, token in (
        (fc.FAILURE_PAID_ESCALATION_REQUIRED, fc.DECISION_PAID_ESCALATION_REQUIRED),
        (fc.FAILURE_FRAMEWORK_INPUT_CONFIG, fc.DECISION_BLOCKED_FAIL_CLOSED),
    ):
        record = _decide(failure_class=cls, registry=registry_qualified)
        assert record["decision"] == token
        record["decision_reason"] = None
        with pytest.raises(ValueError):
            fc.validate_fallback_record(record)


def test_budget_exhausted_record_valid_but_never_executes(registry_qualified):
    # count_used=1（stage 已消耗）是合法 stage 状态（attempted/used 仍指
    # 本决策自身的执行事实 = False）；decision = 拒绝再次回退。
    record = _decide(
        failure_class=fc.FAILURE_INVOCATION,
        registry=registry_qualified,
        automatic_fallback_count_used=1,
    )
    fc.validate_fallback_record(record)
    assert record["fallback_attempted"] is False
    assert record["fallback_used"] is False


# ---------------------------------------------------------------------------
# 8. foundation：attempted/used 恒 False（Req 6）——跨全场景矩阵
# ---------------------------------------------------------------------------

_ALL_CLASSES_AND_REGISTRIES = [
    (cls, reg)
    for cls in fc.FAILURE_CLASSES
    for reg in ("qualified", "none", "empty")
]


@pytest.mark.parametrize(
    "failure_class,registry_kind", _ALL_CLASSES_AND_REGISTRIES
)
def test_attempted_and_used_always_false(failure_class, registry_kind):
    registry = (
        {
            "fb-free-1@test": _entry("fb-free-1"),
            "fb-free-2@test": _entry("fb-free-2"),
        }
        if registry_kind == "qualified"
        else (
            {
                "no-tier@test": _entry("no-tier", tier=None),
                "aux-only@test": _entry(
                    "aux-only",
                    qual_status=QUAL_STATUS_QUALIFIED,
                    qual_scope=QUAL_SCOPE_AUXILIARY,
                ),
            }
            if registry_kind == "none"
            else {}
        )
    )
    record = _decide(failure_class=failure_class, registry=registry)
    assert record["fallback_attempted"] is False
    assert record["fallback_used"] is False
    assert record["final_actual_model"] == record["original_model"]
    assert record["final_actual_provider"] == record["original_provider"]
    assert record["authorization_outcome"] == fc.AUTH_OUTCOME_NONE
    fc.validate_fallback_record(record)


def test_decision_record_is_order_independent(registry_qualified):
    # 候选枚举确定性：与 registry 输入顺序无关
    swapped = {
        "fb-free-2@test": registry_qualified["fb-free-2@test"],
        "fb-free-1@test": registry_qualified["fb-free-1@test"],
    }
    a = _decide(failure_class=fc.FAILURE_INVOCATION, registry=registry_qualified)
    b = _decide(failure_class=fc.FAILURE_INVOCATION, registry=swapped)
    assert a["fallback_candidates"] == b["fallback_candidates"]
    assert a["decision"] == b["decision"]
