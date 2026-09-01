"""AAF v0.5 A4 prereq — WorkBuddy economic metadata fact layer 聚焦测试
（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001）。

证明（Requirement 9 + 边界）：
1. 当前经济事实可解析/存储且带 provenance（source + source_version +
   observed_at 显式）
2. 有效窗口覆盖参考时间 → FRESH
3. 已过期 / 尚未生效 → STALE
4. 时间戳/来源证据不足 → UNKNOWN
5. STALE/UNKNOWN 的 multiplier 绝不作为权威便宜/免费（fail closed）
6. capability/qualification gate 先于经济事实（FRESH FREE 的 hy3 仍
   ineligible；hy4-preview 自 SECOND-CANDIDATE-001 起由独立 probe 资格化——
   经济事实只决定 probe priority，不赋予资格；selector 零变化）
7. production WorkBuddy invocation 不变（CodeBuddy Auto，无 --model/--effort）
8. 经济模块不被任何路由代码 import（事实层无消费方）

边界（Boundaries）：无 active WorkBuddy routing、无 effort routing、无
fallback、无 CodeBuddy Auto 替换、无 Hermes/Codex 变更、无 A5/A6。
"""
import sys
from datetime import datetime, timedelta, timezone

import pytest

from ai_agent_framework import adapters
from ai_agent_framework import risk_contract as rc
from ai_agent_framework.workbuddy_economics import (
    ECON_FRESH,
    ECON_STALE,
    ECON_UNKNOWN,
    PROMO_STATUS_DISCOUNT,
    PROMO_STATUS_FREE,
    RANK_AUTHORITATIVE_CHEAP,
    RANK_FRESH_DISCOUNT,
    RANK_UNKNOWN_OR_STALE,
    WORKBUDDY_CANDIDATE_IDS,
    EconomicFact,
    baseline_economic_facts,
    cheapness_rank,
    classify_freshness,
    fact_from_dict,
    fact_to_dict,
    facts_from_dict,
    facts_to_dict,
    is_authoritative_cheap,
    parse_multiplier,
)
from ai_agent_framework.model_registry import (
    baseline_registry,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (
    EXCL_CAPABILITY_INSUFFICIENT,
    select_shadow_candidate,
)

# 固定参考时间（确定性测试；Asia/Shanghai = UTC+8）
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))

# probe 真实 observed_at（= economic_facts.json 生成时刻）
OBSERVED_AT = "2026-09-02T02:10:30+08:00"


def _fact(**kw):
    """构造合法 EconomicFact 的最小助手。"""
    base = dict(model_id="m", source="EVID")
    base.update(kw)
    return EconomicFact(**base)


# ---------------------------------------------------------------------------
# 1. 当前经济事实可解析/存储且带 provenance
# ---------------------------------------------------------------------------


def test_baseline_facts_cover_all_15_candidates():
    facts = baseline_economic_facts()
    assert set(facts) == set(WORKBUDDY_CANDIDATE_IDS)
    assert len(facts) == 15


def test_baseline_facts_evidence_backed_multiplier_and_provenance():
    facts = baseline_economic_facts()
    for mid, fact in facts.items():
        assert fact.model_id == mid
        assert fact.multiplier is not None, f"{mid}: multiplier missing"
        assert fact.multiplier >= 0
        assert ".aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/economic_probe" in fact.source
        assert fact.source_version and "acc-product-config-v3.json" in fact.source_version
        assert fact.observed_at == OBSERVED_AT  # 真实 probe 完成时刻，非构造时时间


def test_baseline_multiplier_values_match_primary_source():
    facts = baseline_economic_facts()
    expected = {
        "deepseek-v4-flash": (0.17, "x0.17"),
        "deepseek-v4-pro": (0.51, "x0.51"),
        "hy4-preview": (0.0, "x0.00"),
        "hy3": (0.0, "x0.00"),
        "hy3-x": (0.05, "x0.05"),
        "glm-5.3": (0.79, "x0.79"),
        "glm-5.3-flash": (0.06, "x0.06"),
        "glm-5.2": (0.79, "x0.79"),
        "glm-5.1": (0.79, "x0.79"),
        "glm-5v-turbo": (0.71, "x0.71"),
        "minimax-m3": (0.25, "x0.25"),
        "minimax-m2.7": (0.26, "x0.26"),
        "kimi-k3-1": (1.62, "x1.62"),
        "kimi-k2.7": (0.57, "x0.57"),
        "kimi-k2.6": (0.52, "x0.52"),
    }
    for mid, (mult, raw) in expected.items():
        assert facts[mid].multiplier == mult, mid
        assert facts[mid].multiplier_raw == raw, mid


def test_baseline_promotions_from_explicit_entries_only():
    facts = baseline_economic_facts()
    # 显式促销：hy3 / hy4-preview 免费（带窗口），glm-5.2 / deepseek-v4-flash /
    # deepseek-v4-pro 折扣（daily-only，无窗口）
    assert facts["hy3"].promotion_status == PROMO_STATUS_FREE
    assert facts["hy4-preview"].promotion_status == PROMO_STATUS_FREE
    assert facts["glm-5.2"].promotion_status == PROMO_STATUS_DISCOUNT
    assert facts["deepseek-v4-flash"].promotion_status == PROMO_STATUS_DISCOUNT
    assert facts["deepseek-v4-pro"].promotion_status == PROMO_STATUS_DISCOUNT
    # 其余 10 个候选：无促销证据 → None（credits x0.00 而无促销条目不推断免费）
    for mid in WORKBUDDY_CANDIDATE_IDS:
        if mid not in ("hy3", "hy4-preview", "glm-5.2",
                       "deepseek-v4-flash", "deepseek-v4-pro"):
            assert facts[mid].promotion_status is None, f"{mid}: promotion invented"
            assert facts[mid].promotion_factor is None


def test_parse_multiplier_observed_formats():
    assert parse_multiplier("x0.17") == 0.17
    assert parse_multiplier("x0.17 credits") == 0.17
    assert parse_multiplier("x0.00") == 0.0
    assert parse_multiplier("x1.62") == 1.62
    assert parse_multiplier("0x") is None  # 不是 product config 的实际格式（不发明）
    for bad in (None, "", "abc", "x", "x.17", "0.17"):
        assert parse_multiplier(bad) is None, f"{bad!r} must fail closed"


def test_fact_roundtrip_preserves_provenance():
    f = baseline_economic_facts()["hy3"]
    d = fact_to_dict(f, NOW)
    assert d["freshness"] == ECON_FRESH
    assert d["freshness_reference_time"] == NOW.isoformat()
    g = fact_from_dict(d)
    assert g == f
    # facts-level roundtrip
    doc = facts_to_dict(baseline_economic_facts(), NOW)
    rebuilt = facts_from_dict(doc)
    assert set(rebuilt) == set(baseline_economic_facts())
    assert rebuilt["hy3"] == f


def test_fact_from_dict_ignores_stored_freshness():
    """freshness 是派生字段：fact 只存证据字段；freshness 永远对参考时间重算。"""
    f = baseline_economic_facts()["hy3"]
    d = fact_to_dict(f, NOW)
    d["freshness"] = ECON_STALE  # 篡改已存 freshness 不得影响事实
    g = fact_from_dict(d)
    assert g.valid_from == f.valid_from
    assert classify_freshness(g, NOW) == ECON_FRESH


def test_fact_validation_fail_closed():
    with pytest.raises(ValueError):
        _fact(model_id="")
    with pytest.raises(ValueError):
        _fact(multiplier=-0.1)
    with pytest.raises(ValueError):
        _fact(promotion_status="bargain")
    with pytest.raises(ValueError):
        _fact(valid_from="2026-09-02")  # 无时区 → 拒绝（fail closed）
    with pytest.raises(ValueError):
        _fact(valid_until="not-a-date")
    with pytest.raises(ValueError):
        _fact(source="")


def test_facts_from_dict_unknown_schema_version_fail_closed():
    doc = facts_to_dict(baseline_economic_facts(), NOW)
    doc["schema_version"] = 999
    with pytest.raises(ValueError):
        facts_from_dict(doc)
    doc2 = facts_to_dict(baseline_economic_facts(), NOW)
    doc2["schema_version"] = True  # bool 不是 int（严格类型）
    with pytest.raises(ValueError):
        facts_from_dict(doc2)


# ---------------------------------------------------------------------------
# 2/3/4. 新鲜度：FRESH / STALE / UNKNOWN（确定性）
# ---------------------------------------------------------------------------


def test_freshness_fresh_when_window_covers_now():
    f = _fact(
        valid_from="2026-08-01T00:00:00+08:00",
        valid_until="2026-10-01T00:00:00+08:00",
    )
    assert classify_freshness(f, NOW) == ECON_FRESH


def test_freshness_stale_when_expired():
    f = _fact(
        valid_from="2026-07-01T00:00:00+08:00",
        valid_until="2026-08-01T00:00:00+08:00",  # 已过期
    )
    assert classify_freshness(f, NOW) == ECON_STALE


def test_freshness_stale_when_not_yet_valid():
    f = _fact(
        valid_from="2026-10-01T00:00:00+08:00",
        valid_until="2026-12-01T00:00:00+08:00",  # 尚未生效
    )
    assert classify_freshness(f, NOW) == ECON_STALE


def test_freshness_stale_with_only_valid_until_past():
    f = _fact(valid_until="2026-08-01T00:00:00+08:00")
    assert classify_freshness(f, NOW) == ECON_STALE


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # 无任何时间戳
        {"valid_from": "2026-08-01T00:00:00+08:00"},  # 只有下界（过去）→ 无上界证据
        {"valid_until": "2026-10-01T00:00:00+08:00"},  # 只有上界（未来）→ 无下界证据
    ],
)
def test_freshness_unknown_on_insufficient_evidence(kwargs):
    assert classify_freshness(_fact(**kwargs), NOW) == ECON_UNKNOWN


def test_freshness_requires_tz_aware_now():
    f = _fact(valid_from="2026-08-01T00:00:00+08:00",
              valid_until="2026-10-01T00:00:00+08:00")
    with pytest.raises(ValueError):
        classify_freshness(f, datetime(2026, 9, 2, 12, 0, 0))  # naive now


# ---------------------------------------------------------------------------
# 5. STALE/UNKNOWN 绝不作为权威便宜/免费（Requirement 5）
# ---------------------------------------------------------------------------


def test_stale_free_promo_is_not_authoritative_cheap():
    f = _fact(
        multiplier=0.0,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        valid_from="2026-07-01T00:00:00+08:00",
        valid_until="2026-08-01T00:00:00+08:00",  # 过期 → STALE
    )
    assert classify_freshness(f, NOW) == ECON_STALE
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_unknown_multiplier_not_authoritative_cheap():
    f = _fact(multiplier=None)  # 无乘数证据
    assert classify_freshness(f, NOW) == ECON_UNKNOWN
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_zero_multiplier_without_promo_is_not_cheap():
    """credits x0.00 而无显式促销条目 → 不推断免费（conservative）。"""
    f = _fact(multiplier=0.0, multiplier_raw="x0.00", promotion_status=None)
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_fresh_discount_is_not_free():
    f = _fact(
        multiplier=0.79,
        promotion_status=PROMO_STATUS_DISCOUNT,
        promotion_factor=0.5,
        valid_from="2026-08-01T00:00:00+08:00",
        valid_until="2026-10-01T00:00:00+08:00",
    )
    assert classify_freshness(f, NOW) == ECON_FRESH
    assert is_authoritative_cheap(f, NOW) is False  # 折扣 ≠ 免费
    assert cheapness_rank(f, NOW) == RANK_FRESH_DISCOUNT


def test_fresh_free_with_zero_multiplier_is_authoritative_cheap():
    """唯一被认定为权威免费的组合：FRESH + 显式 free 促销 + multiplier 0.0。"""
    f = _fact(
        multiplier=0.0,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        valid_from="2026-08-01T00:00:00+08:00",
        valid_until="2026-10-01T00:00:00+08:00",
    )
    assert is_authoritative_cheap(f, NOW) is True
    assert cheapness_rank(f, NOW) == RANK_AUTHORITATIVE_CHEAP


def test_fresh_free_but_multiplier_inconsistent_is_not_cheap():
    """促销说 free 但 credits 非 0（数据不一致）→ fail closed，不视为免费。"""
    f = _fact(
        multiplier=0.17,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        valid_from="2026-08-01T00:00:00+08:00",
        valid_until="2026-10-01T00:00:00+08:00",
    )
    assert is_authoritative_cheap(f, NOW) is False


def test_unknown_stale_never_outranks_fresh():
    stale_free = _fact(
        multiplier=0.0, promotion_status=PROMO_STATUS_FREE, promotion_factor=0.0,
        valid_from="2026-07-01T00:00:00+08:00",
        valid_until="2026-08-01T00:00:00+08:00",
    )
    unknown = _fact(multiplier=None)
    fresh_discount = _fact(
        multiplier=0.79, promotion_status=PROMO_STATUS_DISCOUNT, promotion_factor=0.5,
        valid_from="2026-08-01T00:00:00+08:00",
        valid_until="2026-10-01T00:00:00+08:00",
    )
    fresh_free = _fact(
        multiplier=0.0, promotion_status=PROMO_STATUS_FREE, promotion_factor=0.0,
        valid_from="2026-08-01T00:00:00+08:00",
        valid_until="2026-10-01T00:00:00+08:00",
    )
    # STALE/UNKNOWN 的 rank 恒为 2：绝不 < 已知 FRESH 事实的 rank
    assert cheapness_rank(stale_free, NOW) == RANK_UNKNOWN_OR_STALE
    assert cheapness_rank(unknown, NOW) == RANK_UNKNOWN_OR_STALE
    assert cheapness_rank(fresh_discount, NOW) == RANK_FRESH_DISCOUNT
    assert cheapness_rank(fresh_free, NOW) == RANK_AUTHORITATIVE_CHEAP
    assert RANK_AUTHORITATIVE_CHEAP < RANK_FRESH_DISCOUNT < RANK_UNKNOWN_OR_STALE


# ---------------------------------------------------------------------------
# 6. capability/qualification gate 先于经济事实（Requirement 6/7）
# ---------------------------------------------------------------------------


def test_fresh_free_candidates_still_ineligible():
    """hy3 有 FRESH 免费促销，但 tier=None + qualification=unknown
    → is_usable_candidate 仍 False；经济事实绝不绕过 capability gate。
    （hy4-preview 自 SECOND-CANDIDATE-001 起已由独立 probe 资格化——经济事实
    只决定 probe priority，不赋予资格；其专项断言见
    tests/test_a4_workbuddy_second_candidate.py。）"""
    facts = baseline_economic_facts()
    assert classify_freshness(facts["hy3"], NOW) == ECON_FRESH
    assert classify_freshness(facts["hy4-preview"], NOW) == ECON_FRESH
    assert is_authoritative_cheap(facts["hy3"], NOW) is True
    reg = baseline_registry()
    e = reg["hy3"]
    assert is_usable_candidate(e) is False
    assert e.capability_tier is None
    assert e.qualification.status == "unknown"
    assert e.cost_class == "UNKNOWN"  # registry 成本维度未改动
    # hy4-preview 资格化后经济字段不变（multiplier 0.0 / free / factor 0.0）
    assert facts["hy4-preview"].multiplier == 0.0
    assert facts["hy4-preview"].promotion_status == PROMO_STATUS_FREE
    assert is_authoritative_cheap(facts["hy4-preview"], NOW) is True


def test_qualified_candidate_capability_qualification_unchanged():
    """deepseek-v4-flash WorkBuddy 候选：T4 + QUALIFIED 保持；经济事实（discount
    0.5, freshness UNKNOWN）不改任何 registry 维度。"""
    facts = baseline_economic_facts()
    assert facts["deepseek-v4-flash"].multiplier == 0.17
    assert facts["deepseek-v4-flash"].promotion_status == PROMO_STATUS_DISCOUNT
    assert classify_freshness(facts["deepseek-v4-flash"], NOW) == ECON_UNKNOWN
    assert is_authoritative_cheap(facts["deepseek-v4-flash"], NOW) is False
    reg = baseline_registry()
    e = reg["deepseek-v4-flash"]
    assert e.capability_tier == "T4"
    assert e.qualification.status == "qualified"
    assert is_usable_candidate(e) is True
    assert e.cost_class == "UNKNOWN"


def test_selector_unchanged_economics_not_consumed():
    """selector 不消费经济事实：LOW workbuddy 下两个资格化候选
    （deepseek-v4-flash + hy4-preview）eligible；FRESH FREE 的 hy3 仍
    CAPABILITY_INSUFFICIENT（经济事实不赋予资格）。"""
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    assert decision.eligible == ("deepseek-v4-flash", "hy4-preview")
    assert decision.selected == "deepseek-v4-flash"
    reasons = {rec.candidate: rec.reason for rec in decision.excluded}
    assert reasons["hy3"] == EXCL_CAPABILITY_INSUFFICIENT
    # hy4-preview 现在 eligible 是因为独立 probe 证据，不是经济事实
    assert "hy4-preview" not in reasons


def test_economics_module_not_imported_by_routing_code():
    """事实层无消费方（source-level contract）：adapters / shadow_routing /
    model_registry 的源码不 import workbuddy_economics（经济事实不进入任何
    路由权威）。用 importlib 验证依赖图 + 源码级断言双保险。"""
    import importlib

    for mod_name in (
        "ai_agent_framework.adapters",
        "ai_agent_framework.shadow_routing",
        "ai_agent_framework.model_registry",
        "ai_agent_framework.runner",
        "ai_agent_framework.active_routing",
        "ai_agent_framework.cost_guard",
    ):
        mod = importlib.import_module(mod_name)
        assert "workbuddy_economics" not in getattr(mod, "__dict__", {}), mod_name
    # 源码级断言：routing 源文件不得出现 workbuddy_economics 引用
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in (
        "ai_agent_framework/adapters.py",
        "ai_agent_framework/shadow_routing.py",
        "ai_agent_framework/model_registry.py",
        "ai_agent_framework/runner.py",
        "ai_agent_framework/active_routing.py",
        "ai_agent_framework/cost_guard.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "workbuddy_economics" not in text, f"{rel} must not import economics"


# ---------------------------------------------------------------------------
# 7. production WorkBuddy invocation 不变（Requirement 8）
# ---------------------------------------------------------------------------


def test_production_invocation_unchanged(monkeypatch):
    fake_exe = "C:/fake-bin/codebuddy.exe"
    monkeypatch.setattr(adapters, "_require", lambda cmd: fake_exe)
    env = {}
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", env)
    assert args == [fake_exe, "-p", "--output-format", "text", "-y"]
    assert "--model" not in args
    assert "--effort" not in args
    assert "-m" not in args
    assert stdin_data == "PROMPT"
