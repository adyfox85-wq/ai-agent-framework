"""AAF v0.5 A4 prereq — second WorkBuddy candidate qualification 聚焦测试
（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001）。

证明（Requirement 13 + 选择契约）：
1. 候选 probe-priority 选择只消费 FRESH + trustworthy economics
   （select_probe_candidate fail closed）：baseline 事实 + probe 参考时间 →
   确定性选出 hy4-preview（RANK_AUTHORITATIVE_CHEAP，rank-0 内最早 valid_until
   = 免费窗口最早关闭者优先）；STALE / UNKNOWN / 字段缺失或矛盾 永不优先；
   无任何可信 FRESH 候选 → NO_TRUSTWORTHY_SECOND_CANDIDATE（None）
2. 经济事实永不直接使候选 eligible：hy3 仍 FRESH+authoritative cheap 但
   tier=None+qualification=unknown → ineligible；hy4-preview 资格化只来自
   独立 runtime probe evidence（经济选择只决定 probe priority）
3. 成功 probe 后 hy4-preview 可通过 LOW eligibility gate（is_usable_candidate；
   selector LOW executor/validator 下两个 WorkBuddy 候选均 eligible）
4. deepseek-v4-flash WorkBuddy 条目零变化（T4 + QUALIFIED + 原证据 + 原
   observed_at，Requirement 9）
5. 其余 13 个未选 candidates 保持 tier=None + qualification=unknown
   （Requirement 10）
6. production WorkBuddy invocation 不变（CodeBuddy Auto [-p --output-format
   text -y]，无 --model/--effort，Requirement 12）
7. registry round-trip 保留第二个 qualification；key 集合不变

边界（Boundaries）：无 active WorkBuddy routing、无 multiplier routing wiring、
无 effort selection、无 fallback、无 health/quarantine、无 runtime
requalification loop、无 Hermes/Codex 路由变更、无 A5/A6。
"""
from datetime import datetime

import pytest

from ai_agent_framework import adapters
from ai_agent_framework import risk_contract as rc
from ai_agent_framework import workbuddy_economics as we
from ai_agent_framework.model_registry import (
    CAP_TIER_T0,
    CAP_TIER_T1,
    CAP_TIER_T2,
    CAP_TIER_T3,
    CAP_TIER_T4,
    COST_CLASS_UNKNOWN,
    LOCALITY_UNKNOWN,
    QUAL_STATUS_QUALIFIED,
    QUAL_STATUS_UNKNOWN,
    baseline_registry,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (
    EXCL_CAPABILITY_INSUFFICIENT,
    NO_SHADOW_CANDIDATE,
    select_shadow_candidate,
)

# 两个被资格化的 WorkBuddy 候选（key = model ID，provider 未暴露）。
QUALIFIED_WORKBUDDY_IDS = ("deepseek-v4-flash", "hy4-preview")
# 本任务选中的第二个候选（经济事实层 fail-closed probe-priority 选择）。
SELECTED_CANDIDATE = "hy4-preview"
# 其余 13 个仍保持 identity-only 的 WorkBuddy 候选。
UNQUALIFIED_WORKBUDDY_IDS = (
    "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
    "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
)
# probe 证据 artifact 的真实 observed_at（= probe 完成时刻，registry 使用同一值）。
PROBE_OBSERVED_AT = "2026-09-02T03:01:44+08:00"
# 经济事实层 probe 参考时间（= economic facts observed_at，FRESH 判定基准）。
ECON_NOW = datetime.fromisoformat("2026-09-02T02:10:30+08:00")


def _workbuddy_candidates(reg):
    return {
        k: e for k, e in reg.items()
        if e.applicable_agents == ("workbuddy",) and e.model is not None
    }


def _excluded_reasons(decision):
    return {rec.candidate: rec.reason for rec in decision.excluded}


def _fact(**kw):
    base = dict(
        model_id="m",
        multiplier=1.0,
        multiplier_raw="x1.0",
        promotion_status=None,
        promotion_factor=None,
        valid_from=None,
        valid_until=None,
        source="test",
    )
    base.update(kw)
    return we.EconomicFact(**base)


# ---------------------------------------------------------------------------
# 1. 候选 probe-priority 选择（select_probe_candidate）fail closed
# ---------------------------------------------------------------------------


def test_selection_baseline_facts_picks_hy4_preview():
    """baseline 经济事实 + probe 参考时间：只有 hy3 / hy4-preview 是
    RANK_AUTHORITATIVE_CHEAP（FRESH + 显式 free + multiplier 0.0 + factor 0.0）；
    rank-0 内最早 valid_until 确定性选择 → hy4-preview（2026-09-11 < hy3 10-01）。"""
    facts = we.baseline_economic_facts()
    sel = we.select_probe_candidate(facts, ECON_NOW, exclude_ids=("deepseek-v4-flash",))
    assert sel == SELECTED_CANDIDATE
    # 14 个未资格化候选中 rank-0 只有这两个；其余 12 个全是 rank 2（UNKNOWN）
    rank0 = [
        mid for mid in facts
        if mid != "deepseek-v4-flash"
        and we.cheapness_rank(facts[mid], ECON_NOW) == we.RANK_AUTHORITATIVE_CHEAP
    ]
    assert set(rank0) == {"hy3", "hy4-preview"}
    rank2 = [
        mid for mid in facts
        if mid != "deepseek-v4-flash"
        and we.cheapness_rank(facts[mid], ECON_NOW) == we.RANK_UNKNOWN_OR_STALE
    ]
    assert len(rank2) == 12  # 其余 12 个 freshness=UNKNOWN → 永不优先


def test_selection_rank0_earliest_valid_until_wins():
    """rank-0（FRESH + authoritative free）内：最早 valid_until（免费窗口最早
    关闭者）确定性优先；valid_until 相同 → model_id 字典序。"""
    f1 = _fact(
        model_id="free-a", multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-10-01T00:00:00+08:00",
    )
    f2 = _fact(
        model_id="free-b", multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-09-01T00:00:00+08:00",
    )
    now = datetime.fromisoformat("2026-08-01T00:00:00+08:00")
    assert we.select_probe_candidate({"free-a": f1, "free-b": f2}, now) == "free-b"
    # valid_until 相同 → model_id 字典序（确定性全序 tie-break）
    f3 = _fact(
        model_id="free-c", multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-10-01T00:00:00+08:00",
    )
    assert we.select_probe_candidate({"free-a": f1, "free-c": f3}, now) == "free-a"


def test_selection_fresh_discount_lowest_multiplier_second():
    """无 rank-0 时：FRESH + discount + economic_fields_consistent 的候选按
    最低 multiplier 优先（rank 1）。"""
    now = datetime.fromisoformat("2026-08-01T00:00:00+08:00")
    d_hi = _fact(
        model_id="disc-hi", multiplier=0.8, multiplier_raw="x0.8",
        promotion_status="discount", promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-01T00:00:00+08:00",
    )
    d_lo = _fact(
        model_id="disc-lo", multiplier=0.2, multiplier_raw="x0.2",
        promotion_status="discount", promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-01T00:00:00+08:00",
    )
    assert we.select_probe_candidate({"disc-hi": d_hi, "disc-lo": d_lo}, now) == "disc-lo"


def test_selection_unknown_stale_never_prioritized():
    """STALE / UNKNOWN / 字段缺失或矛盾 永不优先：
    - STALE free（窗口已过）不参与；UNKNOWN freshness 的极低 multiplier 不参与；
    - 存在 rank-0 时绝不选它们；只有它们时 → NO_TRUSTWORTHY_SECOND_CANDIDATE。"""
    now = datetime.fromisoformat("2026-08-01T00:00:00+08:00")
    stale_free = _fact(
        model_id="stale-free", multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-02-01T00:00:00+08:00",
    )
    unknown_cheap = _fact(
        model_id="unknown-cheap", multiplier=0.01, multiplier_raw="x0.01",
    )  # 无窗口 → freshness UNKNOWN，即使 multiplier 极低也不得优先
    fresh_free = _fact(
        model_id="fresh-free", multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-01T00:00:00+08:00",
    )
    # 有可信 FRESH 时：只能选 fresh-free
    assert we.select_probe_candidate(
        {"stale-free": stale_free, "unknown-cheap": unknown_cheap, "fresh-free": fresh_free},
        now,
    ) == "fresh-free"
    # 只有 STALE/UNKNOWN 时：NO_TRUSTWORTHY_SECOND_CANDIDATE（不发明经济值）
    assert we.select_probe_candidate(
        {"stale-free": stale_free, "unknown-cheap": unknown_cheap}, now,
    ) is we.NO_TRUSTWORTHY_SECOND_CANDIDATE
    assert we.select_probe_candidate({}, now) is we.NO_TRUSTWORTHY_SECOND_CANDIDATE


def test_selection_incomplete_or_contradictory_never_prioritized():
    """字段缺失/矛盾的经济事实（FIX-001 gate）不得进入已知经济排序：
    multiplier=None 或 promotion_factor=None 的 FRESH discount → rank 2。"""
    now = datetime.fromisoformat("2026-08-01T00:00:00+08:00")
    broken1 = _fact(
        model_id="broken-1", multiplier=None, multiplier_raw=None,
        promotion_status="discount", promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-01T00:00:00+08:00",
    )
    broken2 = _fact(
        model_id="broken-2", multiplier=0.5, multiplier_raw="x0.5",
        promotion_status="discount", promotion_factor=None,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-01T00:00:00+08:00",
    )
    assert we.economic_fields_consistent(broken1) is False
    assert we.economic_fields_consistent(broken2) is False
    assert we.cheapness_rank(broken1, now) == we.RANK_UNKNOWN_OR_STALE
    assert we.cheapness_rank(broken2, now) == we.RANK_UNKNOWN_OR_STALE
    assert we.select_probe_candidate({"broken-1": broken1, "broken-2": broken2}, now) \
        is we.NO_TRUSTWORTHY_SECOND_CANDIDATE


def test_selection_exclude_ids_and_naive_now_rejected():
    """exclude_ids 排除已资格化候选；无时区参考时间 → ValueError（显式契约）。"""
    facts = we.baseline_economic_facts()
    sel_without_exclude = we.select_probe_candidate(facts, ECON_NOW)
    # 不排除 deepseek-v4-flash 时它是 rank-2（UNKNOWN freshness discount）→ 不影响
    assert sel_without_exclude == SELECTED_CANDIDATE
    # 排除全部 rank-0/1 候选（hy4-preview/hy3/deepseek-v4-flash）后，剩余 12 个
    # 全部 freshness=UNKNOWN（rank 2）→ NO_TRUSTWORTHY_SECOND_CANDIDATE
    assert we.select_probe_candidate(
        facts, ECON_NOW, exclude_ids=("hy4-preview", "hy3", "deepseek-v4-flash"),
    ) is we.NO_TRUSTWORTHY_SECOND_CANDIDATE
    with pytest.raises(ValueError):
        we.select_probe_candidate(facts, datetime(2026, 9, 2))


# ---------------------------------------------------------------------------
# 2. 经济事实永不直接使候选 eligible
# ---------------------------------------------------------------------------


def test_economics_never_makes_candidate_eligible():
    """hy3 仍 FRESH + authoritative cheap（rank 0），但 tier=None +
    qualification=unknown → is_usable_candidate False（Requirement 11）。"""
    facts = we.baseline_economic_facts()
    assert we.is_authoritative_cheap(facts["hy3"], ECON_NOW) is True
    reg = baseline_registry()
    e = reg["hy3"]
    assert e.capability_tier is None
    assert e.qualification.status == QUAL_STATUS_UNKNOWN
    assert is_usable_candidate(e) is False


def test_hy4_preview_qualification_from_probe_evidence_only():
    """hy4-preview 资格化只来自独立 runtime probe evidence（Requirement 8）：
    qualification.evidence 引用本次 probe artifacts；observed_at = probe 真实
    时间戳；cost_class/locality/provider 保持 UNKNOWN/None。"""
    e = baseline_registry()[SELECTED_CANDIDATE]
    blob = " ".join(e.qualification.evidence)
    assert "AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001/probe" in blob
    assert "hy4_preview_qualification_probe" in blob
    assert "--model hy4-preview" in blob
    assert f"observed_at={PROBE_OBSERVED_AT}" in blob
    assert e.qualification.observed_at == PROBE_OBSERVED_AT
    assert e.cost_class == COST_CLASS_UNKNOWN
    assert e.locality == LOCALITY_UNKNOWN
    assert e.provider is None


# ---------------------------------------------------------------------------
# 3. 成功 probe 后第二候选通过 LOW eligibility gate
# ---------------------------------------------------------------------------


def test_hy4_preview_qualified_and_low_eligible():
    e = baseline_registry()[SELECTED_CANDIDATE]
    assert e.model == SELECTED_CANDIDATE
    assert e.applicable_agents == ("workbuddy",)
    assert e.capability_tier == CAP_TIER_T4
    assert e.qualification.status == QUAL_STATUS_QUALIFIED
    assert is_usable_candidate(e) is True


def test_hy4_preview_tier_not_overestimated():
    """LOW probe 成功只证明最低 T4；T3/T2/T1/T0 绝不推断。"""
    e = baseline_registry()[SELECTED_CANDIDATE]
    assert e.capability_tier == CAP_TIER_T4
    for t in (CAP_TIER_T0, CAP_TIER_T1, CAP_TIER_T2, CAP_TIER_T3):
        assert e.capability_tier != t


def test_selector_low_workbuddy_two_eligible():
    """LOW executor：两个 WorkBuddy 候选均 eligible；selected 仍为
    deepseek-v4-flash（cost/locality 同 rank，key 字典序 tie-break 不变）；
    MEDIUM/HIGH/CRITICAL 仍 CAPABILITY_INSUFFICIENT。"""
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    assert decision.eligible == ("deepseek-v4-flash", "hy4-preview")
    assert decision.selected == "deepseek-v4-flash"  # 既有选择语义不变
    assert decision.no_candidate_reason is None
    reasons = _excluded_reasons(decision)
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        assert reasons[mid] == EXCL_CAPABILITY_INSUFFICIENT
    assert reasons["agent:workbuddy"] == EXCL_CAPABILITY_INSUFFICIENT

    dec_v = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_VALIDATOR, "workbuddy", reg)
    assert set(dec_v.eligible) == set(QUALIFIED_WORKBUDDY_IDS)

    for risk in (rc.RISK_MEDIUM, rc.RISK_HIGH, rc.RISK_CRITICAL):
        d = select_shadow_candidate(risk, rc.ROLE_EXECUTOR, "workbuddy", reg)
        assert d.eligible == ()
        assert d.selected is None
        assert (d.no_candidate_reason or "").startswith(NO_SHADOW_CANDIDATE)
        r = _excluded_reasons(d)
        for mid in QUALIFIED_WORKBUDDY_IDS:
            assert r[mid] == EXCL_CAPABILITY_INSUFFICIENT


# ---------------------------------------------------------------------------
# 4. deepseek-v4-flash WorkBuddy 条目零变化（Requirement 9）
# ---------------------------------------------------------------------------


def test_deepseek_v4_flash_entry_unchanged():
    e = baseline_registry()["deepseek-v4-flash"]
    assert e.model == "deepseek-v4-flash"
    assert e.provider is None
    assert e.applicable_agents == ("workbuddy",)
    assert e.capability_tier == CAP_TIER_T4
    assert e.qualification.status == QUAL_STATUS_QUALIFIED
    assert e.qualification.observed_at == "2026-09-02T01:45:31+08:00"  # 原时间戳
    blob = " ".join(e.qualification.evidence)
    assert "QUALIFICATION-001" in blob
    assert "SECOND-CANDIDATE" not in e.qualification.evidence  # 证据不混入
    assert e.cost_class == COST_CLASS_UNKNOWN
    assert e.locality == LOCALITY_UNKNOWN


# ---------------------------------------------------------------------------
# 5. 其余 13 个未选 candidates 保持 UNKNOWN（Requirement 10）
# ---------------------------------------------------------------------------


def test_other_13_workbuddy_candidates_still_unknown():
    reg = baseline_registry()
    cands = _workbuddy_candidates(reg)
    assert set(cands) == set(UNQUALIFIED_WORKBUDDY_IDS) | set(QUALIFIED_WORKBUDDY_IDS)
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        e = reg[mid]
        assert e.model == mid
        assert e.provider is None
        assert e.capability_tier is None, f"{mid}: tier invented"
        assert e.qualification.status == QUAL_STATUS_UNKNOWN, f"{mid}: health invented"
        assert e.cost_class == COST_CLASS_UNKNOWN
        assert e.locality == LOCALITY_UNKNOWN
        assert is_usable_candidate(e) is False, f"{mid}: must stay ineligible"
        assert any("WORKBUDDY-DISCOVERY-001" in s for s in e.evidence)


def test_workbuddy_auto_anchor_unchanged():
    e = baseline_registry()["agent:workbuddy"]
    assert e.model is None and e.provider is None
    assert e.capability_tier is None
    assert e.qualification.status == QUAL_STATUS_UNKNOWN
    assert is_usable_candidate(e) is False


# ---------------------------------------------------------------------------
# 6. production WorkBuddy invocation 不变（Requirement 12）
# ---------------------------------------------------------------------------


def test_production_invocation_unchanged(monkeypatch):
    fake_exe = "C:/fake-bin/codebuddy.exe"
    monkeypatch.setattr(adapters, "_require", lambda cmd: fake_exe)
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", {})
    assert args == [fake_exe, "-p", "--output-format", "text", "-y"]
    assert "--model" not in args
    assert "--effort" not in args
    assert "-m" not in args
    assert stdin_data == "PROMPT"


# ---------------------------------------------------------------------------
# 7. registry round-trip 保留第二个 qualification
# ---------------------------------------------------------------------------


def test_registry_roundtrip_preserves_second_qualification():
    from ai_agent_framework.model_registry import registry_from_dict, registry_to_dict
    reg = baseline_registry()
    rebuilt = registry_from_dict(registry_to_dict(reg))
    assert set(rebuilt) == set(reg)
    e = rebuilt[SELECTED_CANDIDATE]
    assert e.capability_tier == CAP_TIER_T4
    assert e.qualification.status == QUAL_STATUS_QUALIFIED
    assert e.qualification.observed_at == PROBE_OBSERVED_AT
    assert is_usable_candidate(e) is True
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        assert is_usable_candidate(rebuilt[mid]) is False


def test_baseline_key_set_unchanged():
    reg = baseline_registry()
    assert set(reg) == {
        "deepseek-v4-flash@deepseek", "qwen2.5vl:3b@custom",
        "qwen3:4b@custom", "agent:workbuddy", "agent:codex",
        "hy4-preview", "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
        "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
        "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
        "deepseek-v4-flash",
    }
