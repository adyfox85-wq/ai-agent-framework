"""AAF v0.5 A2 — Shadow Routing 确定性影子选择引擎定向测试（TASK: AAF-v0.5-A2-SHADOW-ROUTING-001）。

覆盖 Requirement 15 测试矩阵 + 追加守卫：
- LOW/MEDIUM/HIGH/CRITICAL 能力下限矩阵
- 能力充分性先于成本（免费但不充分不得胜出）
- FREE ≠ qualification；UNKNOWN qualification 不静默提升
- 经济排序（已知成本 < UNKNOWN；UNKNOWN 成本确定性保守规则）
- 无候选显式 NO_SHADOW_CANDIDATE
- role-inapplicable 排除
- 输入顺序不影响决策（确定性）
- reviewer 语义（HIGH T1/T2、CRITICAL T0/T1 不窄化）
- schema_version 严格性保持（bool/float/str/容器/None/不支持版本拒绝）
- 基线 registry 诚实（真实模型未验证 = UNKNOWN，不发明事实）
- 实际执行隔离（live 模块不 import 本模块）+ 范围静态断言
"""

import ast
import importlib
import inspect

import pytest

from ai_agent_framework import model_observation as mo
from ai_agent_framework import model_registry as mr
from ai_agent_framework import risk_contract as rc
from ai_agent_framework.shadow_routing import (
    EXCL_CAPABILITY_INSUFFICIENT,
    EXCL_NOT_QUALIFIED,
    EXCL_QUALIFICATION_UNKNOWN,
    EXCL_ROLE_NOT_APPLICABLE,
    EXCL_UNSUPPORTED,
    NO_SHADOW_CANDIDATE,
    REASON_COST_TIE_LOCALITY,
    REASON_COST_LOCALITY_TIE_KEY,
    REASON_LOWEST_KNOWN_COST,
    REASON_SOLE_ELIGIBLE,
    SCHEMA_VERSION,
    DECIDED_BY_COST,
    DECIDED_BY_KEY,
    DECIDED_BY_LOCALITY,
    DECIDED_SOLE_ELIGIBLE,
    ShadowDecision,
    decision_from_dict,
    decision_to_dict,
    economic_rank,
    select_shadow_candidate,
)

FREE = mo.COST_CLASS_FREE
LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
PAID = mo.COST_CLASS_PAID
UNKNOWN_COST = mr.COST_CLASS_UNKNOWN
LOCAL = mr.LOCALITY_LOCAL
REMOTE = mr.LOCALITY_REMOTE


def _entry(**overrides) -> mr.RegistryEntry:
    """测试便捷构造：默认 = 已 qualified、FREE 成本的 T3 条目（stage=hermes）。"""
    base = dict(
        model="m1",
        provider="p1",
        applicable_agents=("hermes",),
        capability_tier=mr.CAP_TIER_T3,
        cost_class=FREE,
        locality=mr.LOCALITY_UNKNOWN,
        qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED),
    )
    base.update(overrides)
    return mr.RegistryEntry(**base)


def _qualified(tier: str, model: str = "m", provider: str = "p", **kw) -> mr.RegistryEntry:
    return _entry(
        model=model, provider=provider, capability_tier=tier,
        qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED),
        **kw,
    )


def _registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


def _excluded_reasons(decision: ShadowDecision) -> dict[str, str]:
    return {rec.candidate: rec.reason for rec in decision.excluded}


# ---------------------------------------------------------------------------
# A. 能力下限矩阵（Requirement 15：1–4）
# ---------------------------------------------------------------------------


def test_low_task_qualified_t4_selected():
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T4, "t4", "p")),
    )
    assert decision.selected == "t4@p"
    assert decision.required_floor == "T4"
    assert decision.deciding_dimension == DECIDED_SOLE_ELIGIBLE
    assert decision.selection_reason == REASON_SOLE_ELIGIBLE
    assert decision.no_candidate_reason is None


def test_medium_task_rejects_insufficient_t4():
    """MEDIUM executor floor=T3：T4 能力不足 → 排除 + 显式无候选。"""
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T4, "t4", "p")),
    )
    assert decision.selected is None
    assert decision.eligible == ()
    assert _excluded_reasons(decision)["t4@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.no_candidate_reason is not None
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)
    assert decision.selection_reason is None and decision.deciding_dimension is None


def test_high_task_accepts_sufficient_qualified_t2():
    decision = select_shadow_candidate(
        rc.RISK_HIGH, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T2, "t2", "p")),
    )
    assert decision.selected == "t2@p"
    assert decision.required_floor == "T2"
    assert decision.selection_reason == REASON_SOLE_ELIGIBLE


def test_critical_task_enforces_capability_floor():
    """CRITICAL executor floor=T1：T2 排除；T1 通过。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T2, "t2", "p"),
        _qualified(mr.CAP_TIER_T1, "t1", "p"),
    )
    decision = select_shadow_candidate(
        rc.RISK_CRITICAL, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert _excluded_reasons(decision)["t2@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.selected == "t1@p"
    assert decision.required_floor == "T1"


def test_medium_qualified_t3_selected():
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T3, "t3", "p")),
    )
    assert decision.selected == "t3@p"


def test_validator_floor_applied():
    """MEDIUM validator floor=T3：T4 排除、T3 通过。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T4, "t4", "p"),
        _qualified(mr.CAP_TIER_T3, "t3", "p"),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_VALIDATOR, "hermes", reg,
    )
    assert _excluded_reasons(decision)["t4@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.selected == "t3@p"
    assert decision.required_floor == "T3"


def test_low_validator_t4_floor():
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_VALIDATOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T4, "t4", "p")),
    )
    assert decision.selected == "t4@p"
    assert decision.required_floor == "T4"


# ---------------------------------------------------------------------------
# B. FREE ≠ qualification；UNKNOWN qualification 不静默提升（Requirement 15: 5/6）
# ---------------------------------------------------------------------------


def test_free_but_unqualified_candidate_does_not_win():
    """FREE + not_qualified：即使有 tier 也排除；qualified 付费候选胜出。"""
    reg = _registry(
        _entry(model="free", provider="x", capability_tier=mr.CAP_TIER_T3,
               cost_class=FREE,
               qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_NOT_QUALIFIED)),
        _qualified(mr.CAP_TIER_T3, "paid", "y", cost_class=PAID),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert _excluded_reasons(decision)["free@x"] == EXCL_NOT_QUALIFIED
    assert decision.selected == "paid@y"


def test_free_with_unknown_qualification_not_silently_qualified():
    """FREE + qualification UNKNOWN：不得静默变成 qualified。"""
    reg = _registry(
        _entry(model="free", provider="x", capability_tier=mr.CAP_TIER_T3,
               cost_class=FREE,
               qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_UNKNOWN)),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected is None
    assert _excluded_reasons(decision)["free@x"] == EXCL_QUALIFICATION_UNKNOWN
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)


def test_free_unknown_qual_never_beats_qualified_paid():
    """Requirement 8：FREE 且 qualification UNKNOWN 不得自动胜过 qualified 付费候选。"""
    reg = _registry(
        _entry(model="free", provider="x", capability_tier=mr.CAP_TIER_T3,
               cost_class=FREE,
               qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_UNKNOWN)),
        _qualified(mr.CAP_TIER_T3, "paid", "y", cost_class=PAID),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "paid@y"
    assert _excluded_reasons(decision)["free@x"] == EXCL_QUALIFICATION_UNKNOWN


def test_qualified_paid_t3_beats_free_t4_on_medium():
    """Requirement 8 例：MEDIUM 下 qualified PAID T3 胜过 FREE T4（T4 低于下限）。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T4, "free", "x", cost_class=FREE),
        _qualified(mr.CAP_TIER_T3, "paid", "y", cost_class=PAID),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert _excluded_reasons(decision)["free@x"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.selected == "paid@y"


def test_free_alone_never_produces_qualification():
    """FREE 只是成本属性：tier 未知 + FREE 绝不产生候选（与 A1 一致）。"""
    reg = _registry(
        _entry(model="free", provider="x", capability_tier=None, cost_class=FREE),
    )
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected is None
    assert _excluded_reasons(decision)["free@x"] == EXCL_CAPABILITY_INSUFFICIENT


# ---------------------------------------------------------------------------
# C. 经济排序（Requirement 7/15: 7/8/9；Requirement 8 局部优先 subordinate）
# ---------------------------------------------------------------------------


def test_cheaper_qualified_wins_over_expensive_equivalent():
    """等价充分且合格的候选：较低已知成本（FREE < PAID）胜出；key 顺序不干扰。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "z_free", "x", cost_class=FREE),  # key 更大
        _qualified(mr.CAP_TIER_T3, "a_paid", "y", cost_class=PAID),  # key 更小
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "z_free@x"
    assert decision.deciding_dimension == DECIDED_BY_COST
    assert decision.selection_reason == REASON_LOWEST_KNOWN_COST


def test_cheaper_but_insufficient_loses():
    """更便宜但能力不足（FREE T4 on MEDIUM）不得因便宜而胜出。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T4, "free", "x", cost_class=FREE),
        _qualified(mr.CAP_TIER_T3, "paid", "y", cost_class=PAID),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "paid@y"
    assert decision.deciding_dimension == DECIDED_SOLE_ELIGIBLE


def test_unknown_cost_loses_to_known_free():
    """保守规则：已知成本（FREE）胜过 UNKNOWN 成本。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "free", "x", cost_class=FREE),
        _qualified(mr.CAP_TIER_T3, "unk", "y", cost_class=UNKNOWN_COST),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "free@x"
    assert decision.deciding_dimension == DECIDED_BY_COST


def test_unknown_cost_loses_to_known_paid():
    """保守规则：UNKNOWN 成本永不因成本获胜（unknown ≠ free，不假设更便宜）。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "paid", "x", cost_class=PAID),
        _qualified(mr.CAP_TIER_T3, "unk", "y", cost_class=UNKNOWN_COST),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "paid@x"
    assert decision.deciding_dimension == DECIDED_BY_COST


def test_all_unknown_cost_tie_uses_key_tiebreak():
    """全部 UNKNOWN 成本：成本无可比较 → locality/key 确定性 tie-break 决定。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "b", "x", cost_class=UNKNOWN_COST),
        _qualified(mr.CAP_TIER_T3, "a", "y", cost_class=UNKNOWN_COST),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "a@y"  # key 字典序最小
    assert decision.deciding_dimension == DECIDED_BY_KEY
    assert decision.selection_reason == REASON_COST_LOCALITY_TIE_KEY
    # 重复调用结果一致（确定性）
    again = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision_to_dict(again) == decision_to_dict(decision)


def test_economic_rank_function_contract():
    assert economic_rank(LOCAL_FREE) == 0
    assert economic_rank(FREE) == 0
    assert economic_rank(mo.COST_CLASS_FREE_PROMO) == 0
    assert economic_rank(PAID) == 1
    assert economic_rank(UNKNOWN_COST) == 2
    with pytest.raises(ValueError):
        economic_rank("GRATIS")


def test_locality_tiebreak_after_cost():
    """成本并列（同为 FREE）→ locality 偏好（local < remote）决定。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "remote", "x", cost_class=FREE, locality=REMOTE),
        _qualified(mr.CAP_TIER_T3, "local", "y", cost_class=FREE, locality=LOCAL),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "local@y"
    assert decision.deciding_dimension == DECIDED_BY_LOCALITY
    assert decision.selection_reason == REASON_COST_TIE_LOCALITY


def test_locality_subordinate_to_cost():
    """局部偏好严格次于成本：remote FREE 胜过 local PAID（成本先于 locality）。"""
    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "local", "x", cost_class=PAID, locality=LOCAL),
        _qualified(mr.CAP_TIER_T3, "remote", "y", cost_class=FREE, locality=REMOTE),
    )
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected == "remote@y"
    assert decision.deciding_dimension == DECIDED_BY_COST


# ---------------------------------------------------------------------------
# D. No-candidate / 排除语义（Requirement 9/11/14/15: 10/11）
# ---------------------------------------------------------------------------


def test_no_valid_candidate_returns_explicit_no_candidate():
    """无任何合格候选 → 显式 NO_SHADOW_CANDIDATE，无 silent fallback。"""
    reg = _registry(
        _entry(model="weak", provider="x", capability_tier=mr.CAP_TIER_T4),
        _entry(model="unqual", provider="y", capability_tier=mr.CAP_TIER_T2,
               qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_NOT_QUALIFIED)),
        _entry(model="unknown", provider="z", capability_tier=mr.CAP_TIER_T2,
               qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_UNKNOWN)),
    )
    decision = select_shadow_candidate(
        rc.RISK_HIGH, rc.ROLE_EXECUTOR, "hermes", reg,
    )
    assert decision.selected is None
    assert decision.eligible == ()
    assert decision.selection_reason is None
    assert decision.deciding_dimension is None
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)
    assert "3 candidate(s) considered, 0 eligible" in decision.no_candidate_reason
    assert _excluded_reasons(decision)["weak@x"] == EXCL_CAPABILITY_INSUFFICIENT
    assert _excluded_reasons(decision)["unqual@y"] == EXCL_NOT_QUALIFIED
    assert _excluded_reasons(decision)["unknown@z"] == EXCL_QUALIFICATION_UNKNOWN


def test_empty_registry_no_candidate():
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes", {},
    )
    assert decision.selected is None
    assert decision.candidates_considered == ()
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)
    assert "registry empty" in decision.no_candidate_reason


def test_role_inapplicable_candidate_excluded():
    """stage=codex 时 hermes-only 候选 → ROLE_NOT_APPLICABLE。"""
    reg = _registry(_qualified(mr.CAP_TIER_T3, "hermes_only", "x"))
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "codex", reg,
    )
    assert decision.selected is None
    assert _excluded_reasons(decision)["hermes_only@x"] == EXCL_ROLE_NOT_APPLICABLE


def test_empty_applicable_agents_is_general():
    """applicable_agents 空 = 未知/通用 → 任意 stage 适用。"""
    entry = _entry(applicable_agents=())
    decision = select_shadow_candidate(
        rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "codex", _registry(entry),
    )
    assert decision.selected == entry.key()


def test_unsupported_invalid_registry_data_excluded():
    """registry 值不是 RegistryEntry → UNSUPPORTED 排除（不中断整体决策）。"""
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes", {"bad": "not-an-entry"},
    )
    assert decision.selected is None
    assert _excluded_reasons(decision)["bad"] == EXCL_UNSUPPORTED
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)


# ---------------------------------------------------------------------------
# E. reviewer 语义保持（Requirement 16：HIGH T1/T2、CRITICAL T0/T1 不窄化）
# ---------------------------------------------------------------------------


def test_high_reviewer_allows_t1_and_t2_rejects_others():
    reg = _registry(
        _qualified(mr.CAP_TIER_T1, "t1", "p"),
        _qualified(mr.CAP_TIER_T2, "t2", "p"),
        _qualified(mr.CAP_TIER_T0, "t0", "p"),  # 更强但不在集合内 → 拒绝
        _qualified(mr.CAP_TIER_T3, "t3", "p"),
    )
    decision = select_shadow_candidate(
        rc.RISK_HIGH, rc.ROLE_REVIEWER, "hermes", reg,
    )
    assert decision.selected == "t1@p"  # 成本/局部并列 → key 最小
    assert decision.required_floor is None
    assert decision.allowed_tiers == ("T1", "T2")
    reasons = _excluded_reasons(decision)
    assert reasons["t0@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert reasons["t3@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.eligible == ("t1@p", "t2@p")


def test_critical_reviewer_allows_t0_and_t1_rejects_t2():
    reg = _registry(
        _qualified(mr.CAP_TIER_T0, "t0", "p"),
        _qualified(mr.CAP_TIER_T1, "t1", "p"),
        _qualified(mr.CAP_TIER_T2, "t2", "p"),  # 更弱 → 拒绝
    )
    decision = select_shadow_candidate(
        rc.RISK_CRITICAL, rc.ROLE_REVIEWER, "hermes", reg,
    )
    assert decision.selected == "t0@p"
    assert decision.allowed_tiers == ("T0", "T1")
    assert _excluded_reasons(decision)["t2@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.eligible == ("t0@p", "t1@p")


# ---------------------------------------------------------------------------
# F. 确定性（Requirement 15: 12；输入顺序无关）
# ---------------------------------------------------------------------------


def test_input_order_does_not_alter_decision():
    entries = (
        _qualified(mr.CAP_TIER_T4, "a", "x", cost_class=PAID),
        _qualified(mr.CAP_TIER_T3, "b", "y", cost_class=FREE),
        _qualified(mr.CAP_TIER_T3, "c", "z", cost_class=FREE, locality=LOCAL),
    )
    forward = _registry(*entries)
    reversed_ = _registry(*reversed(entries))
    assert list(forward) != list(reversed_)  # 前提：插入顺序确实不同
    d1 = select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", forward)
    d2 = select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reversed_)
    assert decision_to_dict(d1) == decision_to_dict(d2)
    assert d1.selected == d2.selected == "c@z"  # 成本并列 → locality 决定


def test_selection_is_pure_no_env_or_side_effects():
    """纯函数：不读/改环境、无文件副作用；重复调用结果一致。"""
    import os

    reg = _registry(
        _qualified(mr.CAP_TIER_T3, "b", "x"),
        _qualified(mr.CAP_TIER_T3, "a", "y"),
    )
    before = dict(os.environ)
    d1 = select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg)
    d2 = select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", reg)
    assert dict(os.environ) == before
    assert decision_to_dict(d1) == decision_to_dict(d2)


# ---------------------------------------------------------------------------
# G. schema 严格性保持（Requirement 17）
# ---------------------------------------------------------------------------


def test_decision_serialization_round_trip():
    decision = select_shadow_candidate(
        rc.RISK_CRITICAL, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T1, "t1", "p")),
    )
    restored = decision_from_dict(decision_to_dict(decision))
    assert restored == decision


@pytest.mark.parametrize(
    "bad_version",
    [
        True,      # bool（int 子类，值 == 1）必须拒绝
        False,     # 值 == 0
        1.0,       # float，值 == 1
        1.5,       # 其它 float
        "1",       # 数字字符串
        None,      # 显式 None / 缺失语义
        [1],       # 序列
        {"v": 1},  # 映射
        (1,),      # 元组
        999,       # 不支持的真实 int
    ],
)
def test_decision_schema_version_strictness(bad_version):
    """仅真实 int == SCHEMA_VERSION 被接受；其余 fail closed（ValueError）。"""
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T4, "t4", "p")),
    )
    data = decision_to_dict(decision)
    data["schema_version"] = bad_version
    with pytest.raises(ValueError, match="schema_version"):
        decision_from_dict(data)


def test_missing_schema_version_rejected():
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes",
        _registry(_qualified(mr.CAP_TIER_T4, "t4", "p")),
    )
    data = decision_to_dict(decision)
    del data["schema_version"]
    with pytest.raises(ValueError, match="schema_version"):
        decision_from_dict(data)


def test_a1_registry_schema_strictness_preserved():
    """A1 registry_from_dict 严格性无回归（bool/float/str/None/999 全部拒绝）。"""
    data = mr.registry_to_dict(mr.baseline_registry())
    for bad in (True, 1.0, "1", None, 999):
        data["schema_version"] = bad
        with pytest.raises(ValueError, match="schema_version"):
            mr.registry_from_dict(data)
    data["schema_version"] = mr.SCHEMA_VERSION
    assert mr.registry_from_dict(data) == mr.baseline_registry()


# ---------------------------------------------------------------------------
# H. 基线诚实（Requirement 12/13：真实模型未验证 = UNKNOWN，不发明事实）
# ---------------------------------------------------------------------------


def test_baseline_registry_all_unknown_no_shadow_candidate():
    """A1 基线 registry：全部候选 tier/qualification UNKNOWN →
    诚实返回 NO_SHADOW_CANDIDATE，绝不把 FREE/本地条目提升为候选。"""
    decision = select_shadow_candidate(
        rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
    )
    assert decision.selected is None
    assert decision.eligible == ()
    reasons = _excluded_reasons(decision)
    # hermes 主模型 / 本地 Ollama 模型：tier 未验证 → CAPABILITY_INSUFFICIENT
    assert reasons["deepseek-v4-flash@deepseek"] == EXCL_CAPABILITY_INSUFFICIENT
    assert reasons["qwen2.5vl:3b@custom"] == EXCL_CAPABILITY_INSUFFICIENT
    assert reasons["qwen3:4b@custom"] == EXCL_CAPABILITY_INSUFFICIENT
    # workbuddy/codex 模型身份未知 → 不适用于 hermes stage
    assert reasons["agent:workbuddy"] == EXCL_ROLE_NOT_APPLICABLE
    assert reasons["agent:codex"] == EXCL_ROLE_NOT_APPLICABLE
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)


# ---------------------------------------------------------------------------
# I. 输入校验 fail closed
# ---------------------------------------------------------------------------


def test_unknown_risk_role_stage_inputs_fail_closed():
    reg = _registry(_qualified(mr.CAP_TIER_T3, "a", "p"))
    with pytest.raises(ValueError):
        select_shadow_candidate("EXTREME", rc.ROLE_EXECUTOR, "hermes", reg)
    with pytest.raises(ValueError):
        select_shadow_candidate(rc.RISK_MEDIUM, "driver", "hermes", reg)
    with pytest.raises(ValueError):
        select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "", reg)
    with pytest.raises(ValueError):
        select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "  ", reg)
    with pytest.raises(ValueError):
        select_shadow_candidate(rc.RISK_MEDIUM, rc.ROLE_EXECUTOR, "hermes", [])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# J. 范围 / 隔离静态断言（Requirement 10/18/19/20）
# ---------------------------------------------------------------------------


def test_shadow_module_has_no_io_or_llm_dependency():
    """依赖图 = stdlib(dataclasses/typing) + model_registry + risk_contract；零 I/O。"""
    import ai_agent_framework.shadow_routing as mod

    tree = ast.parse(inspect.getsource(mod))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    banned_roots = {
        "subprocess", "urllib", "requests", "http", "socket", "openai",
        "anthropic", "llm", "os", "json", "time", "datetime", "pathlib",
    }
    leaked = sorted(roots & banned_roots)
    assert leaked == [], f"I/O or LLM dependency leaked into selector: {leaked}"
    assert roots <= {"__future__", "dataclasses", "typing", "model_observation",
                     "model_registry", "risk_contract"}


def test_live_execution_modules_do_not_import_shadow_routing():
    """实际执行隔离：live 模块零 import 本 selector（影子决策零执行影响）。"""
    import warnings

    live_modules = (
        "runner", "router", "adapters", "cost_guard", "report",
        "project_boundary", "task_lifecycle", "context_packet",
        "reconcile", "finalize_cancelled", "task_validation",
    )
    for name in live_modules:
        module = importlib.import_module(f"ai_agent_framework.{name}")
        with warnings.catch_warnings():
            # 既有 live 模块源码中的历史无效转义警告与本断言无关
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            leaked = [i for i in imported if "shadow_routing" in i]
            assert not leaked, f"{name} imports shadow_routing: {leaked}"


def test_no_side_effect_api_in_shadow_module():
    """公开 API 无 apply/switch/invoke/activate/run/fallback/poll/… 副作用函数。"""
    import ai_agent_framework.shadow_routing as mod

    banned = ("apply", "switch", "invoke", "activate", "run", "fallback",
              "escalat", "poll", "quarantine", "monitor", "spawn", "wire")
    public = [
        name for name, _ in inspect.getmembers(mod, inspect.isfunction)
        if not name.startswith("_")
    ]
    leaked = sorted(n for n in public if n.lower().startswith(banned))
    assert leaked == [], f"side-effect API leaked: {leaked}"
    # 契约入口：仅选择 + 序列化
    assert {"select_shadow_candidate", "decision_to_dict", "decision_from_dict",
            "economic_rank"} <= set(public)
