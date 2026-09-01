"""AAF v0.5 A4 prereq FIX-001 — WorkBuddy economic fail-closed 语义收紧聚焦测试
（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001）。

关闭 Codex REQUEST_CHANGE 的两个 blocking findings：
  1. multiplier=None + FRESH discount 当前仍可能获得已知便宜 rank
     （cheapness_rank 只看 freshness+status，不看字段完整性）→ 本修复：
     RANK_FRESH_DISCOUNT 要求 economic_fields_consistent(fact)（multiplier
     已知且有效 + promotion_factor 已知且有效 + status 与二者不矛盾）；
     缺失/矛盾 → RANK_UNKNOWN_OR_STALE（绝不进入已知经济排序）。
  2. authoritative free 当前未要求 promotion_factor == 0.0 → 本修复：
     is_authoritative_cheap 四条件同立：FRESH + free + multiplier==0.0 +
     promotion_factor==0.0。

证明（Requirement 9 + 边界）：
1. FRESH discount + multiplier=None → non-authoritative，rank=UNKNOWN_OR_STALE
2. FRESH discount + promotion_factor=None → non-authoritative，rank=UNKNOWN_OR_STALE
3. FRESH free + multiplier=0.0 + promotion_factor=0.0 → authoritative free
4. FRESH free + multiplier=0.0 + promotion_factor=1.0 → non-authoritative
5. FRESH free + multiplier=0.0 + promotion_factor=0.5 → non-authoritative
6. FRESH free + multiplier>0 → non-authoritative（含 factor=0.0 与 factor>0 两态）
7. STALE/UNKNOWN（即使字段完整）永不 authoritative cheap/free
8. discount 内部矛盾（factor=0.0 / factor=1.0 / multiplier=0.0）→ fail closed
9. economic_fields_consistent 完整/一致性判定（纯 gate）
10. raw 证据无法解释 parsed multiplier → 构造即 ValueError（无法解释 → fail closed）
11. capability/qualification precedence 不回归（FRESH FREE hy3 仍
    ineligible；hy4-preview 自 SECOND-CANDIDATE-001 起由独立 probe 资格化；
    deepseek-v4-flash T4+QUALIFIED 不变；selector 零变化）
12. production WorkBuddy invocation 不变（Auto，无 --model/--effort）
13. 经济模块仍不被路由代码 import

边界（Boundaries）：无 active WorkBuddy routing、无 economic selection wiring、
无 fallback、无 Cost Gate UX、无 health/quarantine、无 runtime requalification、
无 Hermes/Codex 变更、无 A5/A6。
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
    economic_fields_consistent,
    is_authoritative_cheap,
)
from ai_agent_framework.model_registry import (
    baseline_registry,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (
    EXCL_CAPABILITY_INSUFFICIENT,
    select_shadow_candidate,
)

# 固定参考时间（确定性测试；Asia/Shanghai = UTC+8）——与父任务测试同值
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))

FRESH_WINDOW = dict(
    valid_from="2026-08-01T00:00:00+08:00",
    valid_until="2026-10-01T00:00:00+08:00",
)
STALE_WINDOW = dict(
    valid_from="2026-07-01T00:00:00+08:00",
    valid_until="2026-08-01T00:00:00+08:00",
)


def _fact(**kw):
    base = dict(model_id="m", source="EVID")
    base.update(kw)
    return EconomicFact(**base)


def _fresh_discount(**kw):
    """最小合法 FRESH discount 事实（multiplier>0, 0<factor<1, 窗口覆盖 NOW）。"""
    base = dict(
        multiplier=0.79,
        promotion_status=PROMO_STATUS_DISCOUNT,
        promotion_factor=0.5,
        **FRESH_WINDOW,
    )
    base.update(kw)
    return _fact(**base)


def _fresh_free(**kw):
    """最小合法 FRESH free 事实（multiplier 0.0, factor 0.0, 窗口覆盖 NOW）。"""
    base = dict(
        multiplier=0.0,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        **FRESH_WINDOW,
    )
    base.update(kw)
    return _fact(**base)


# ---------------------------------------------------------------------------
# 1/2. FRESH discount 字段缺失 → 不进入已知经济排序（blocking finding #1）
# ---------------------------------------------------------------------------


def test_fresh_discount_multiplier_none_not_authoritative():
    """blocking finding #1：multiplier=None + FRESH discount 不得获得已知便宜
    rank——本修复前 cheapness_rank 返回 RANK_FRESH_DISCOUNT（已知便宜）。"""
    f = _fresh_discount(multiplier=None, multiplier_raw=None)
    assert classify_freshness(f, NOW) == ECON_FRESH
    assert f.promotion_status == PROMO_STATUS_DISCOUNT
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE  # 不再是 RANK_FRESH_DISCOUNT


def test_fresh_discount_promotion_factor_none_not_authoritative():
    """promotion_factor=None + FRESH discount → 字段不完整，不进入已知排序。"""
    f = _fresh_discount(promotion_factor=None)
    assert classify_freshness(f, NOW) == ECON_FRESH
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_fresh_discount_complete_consistent_keeps_known_rank():
    """完整且一致的 FRESH discount 仍获得已知新鲜折扣 rank（不扩大策略，只
    收紧缺失/矛盾——healthy 事实行为不变）。"""
    f = _fresh_discount()
    assert economic_fields_consistent(f) is True
    assert cheapness_rank(f, NOW) == RANK_FRESH_DISCOUNT
    assert is_authoritative_cheap(f, NOW) is False  # 折扣 ≠ 免费


# ---------------------------------------------------------------------------
# 3-6. authoritative free 需要 multiplier==0.0 + promotion_factor==0.0
#      （blocking finding #2）
# ---------------------------------------------------------------------------


def test_fresh_free_zero_multiplier_zero_factor_is_authoritative():
    """唯一权威免费组合：FRESH + free + multiplier 0.0 + promotion_factor 0.0。"""
    f = _fresh_free()
    assert economic_fields_consistent(f) is True
    assert is_authoritative_cheap(f, NOW) is True
    assert cheapness_rank(f, NOW) == RANK_AUTHORITATIVE_CHEAP


def test_fresh_free_zero_multiplier_factor_1_not_authoritative():
    """blocking finding #2 直接反例：free + multiplier=0.0 但 promotion_factor=1.0
    → 本修复前 is_authoritative_cheap=True；现在必须 False。"""
    f = _fresh_free(promotion_factor=1.0)
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_fresh_free_zero_multiplier_factor_half_not_authoritative():
    """free + multiplier=0.0 但 promotion_factor=0.5（免费促销却带 50% 因子 →
    内部矛盾）→ fail closed。"""
    f = _fresh_free(promotion_factor=0.5)
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_fresh_free_nonzero_multiplier_not_authoritative():
    """free + multiplier>0（促销说免费但 credits 非 0）→ 不权威；无论 factor
    是否为 0。"""
    f = _fresh_free(multiplier=0.17)
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE

    f2 = _fresh_free(multiplier=0.17, promotion_factor=0.0)
    assert economic_fields_consistent(f2) is False
    assert is_authoritative_cheap(f2, NOW) is False


def test_fresh_free_nonzero_multiplier_and_factor_not_authoritative():
    f = _fresh_free(multiplier=0.17, promotion_factor=0.5)
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


# ---------------------------------------------------------------------------
# 7. STALE / UNKNOWN 永不 authoritative cheap/free（即使字段完整）
# ---------------------------------------------------------------------------


def test_stale_complete_fields_never_authoritative():
    """字段完整（multiplier 0.0 + factor 0.0 + free）但窗口过期 → STALE → 不权威。"""
    f = _fact(
        multiplier=0.0,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        **STALE_WINDOW,
    )
    assert classify_freshness(f, NOW) == ECON_STALE
    assert economic_fields_consistent(f) is True  # 字段本身完整一致
    assert is_authoritative_cheap(f, NOW) is False  # 但新鲜度不权威
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_unknown_complete_fields_never_authoritative():
    """字段完整但无日期窗口 → UNKNOWN → 不权威。"""
    f = _fact(
        multiplier=0.0,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        valid_from=None,
        valid_until=None,
    )
    assert classify_freshness(f, NOW) == ECON_UNKNOWN
    assert economic_fields_consistent(f) is True
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


def test_stale_discount_complete_fields_rank_unknown():
    f = _fact(
        multiplier=0.79,
        promotion_status=PROMO_STATUS_DISCOUNT,
        promotion_factor=0.5,
        **STALE_WINDOW,
    )
    assert classify_freshness(f, NOW) == ECON_STALE
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(multiplier=None),  # 乘数缺失（窗口仍在 → FRESH，但字段缺失 → fail closed）
        dict(valid_from=None, valid_until=None),  # 无窗口证据 → UNKNOWN
    ],
)
def test_incomplete_or_unknown_never_authoritative(kwargs):
    """字段缺失（即使 FRESH）或无窗口证据（UNKNOWN）→ 一律不权威、rank 2。
    （一致性 gate 与新鲜度 gate 独立：此处只断言 fail-closed 结果。）"""
    f = _fresh_free(**kwargs)
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE


# ---------------------------------------------------------------------------
# 8. discount 内部矛盾 → fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(multiplier=0.0),  # discount 促销但 credits 免费 → 矛盾
        dict(promotion_factor=0.0),  # discount 促销但 factor=免费 → 矛盾
        dict(promotion_factor=1.0),  # discount 促销但 factor=无折扣 → 矛盾
        dict(multiplier=None, promotion_factor=None),  # 双缺失
    ],
)
def test_fresh_discount_internal_contradiction_fail_closed(kwargs):
    f = _fresh_discount(**kwargs)
    assert economic_fields_consistent(f) is False
    assert is_authoritative_cheap(f, NOW) is False
    assert cheapness_rank(f, NOW) == RANK_UNKNOWN_OR_STALE  # 矛盾 → 已知排序之外


# ---------------------------------------------------------------------------
# 9. economic_fields_consistent 纯 gate
# ---------------------------------------------------------------------------


def test_consistent_gate_free_only_when_zero_zero():
    assert economic_fields_consistent(_fresh_free()) is True
    assert economic_fields_consistent(_fresh_free(promotion_factor=0.0)) is True
    assert economic_fields_consistent(_fresh_free(multiplier=0.0)) is True
    for bad in (
        _fresh_free(multiplier=0.1),
        _fresh_free(promotion_factor=0.1),
        _fresh_free(multiplier=0.1, promotion_factor=0.1),
        _fresh_free(multiplier=None),
        _fresh_free(promotion_factor=None),
        _fresh_free(multiplier=None, promotion_factor=None),
    ):
        assert economic_fields_consistent(bad) is False


def test_consistent_gate_discount_requires_positive_known_fields():
    assert economic_fields_consistent(_fresh_discount()) is True
    assert economic_fields_consistent(_fresh_discount(multiplier=0.05)) is True
    for bad in (
        _fresh_discount(multiplier=0.0),
        _fresh_discount(multiplier=None),
        _fresh_discount(promotion_factor=0.0),
        _fresh_discount(promotion_factor=1.0),
        _fresh_discount(promotion_factor=None),
    ):
        assert economic_fields_consistent(bad) is False


def test_consistent_gate_no_promotion_false():
    """无促销证据（promotion_status=None）→ 无法证明一致性 → False。"""
    f = _fact(multiplier=0.17)
    assert f.promotion_status is None
    assert economic_fields_consistent(f) is False
    f2 = _fact(multiplier=0.0, multiplier_raw="x0.00", promotion_status=None)
    assert economic_fields_consistent(f2) is False  # credits 0 无促销 ≠ 免费


# ---------------------------------------------------------------------------
# 10. raw 证据无法解释 parsed multiplier → 构造即 ValueError（fail closed）
# ---------------------------------------------------------------------------


def test_multiplier_raw_must_explain_value():
    with pytest.raises(ValueError):
        _fact(multiplier=0.5, multiplier_raw="x0.17")  # raw 与数值不一致
    with pytest.raises(ValueError):
        _fact(multiplier=0.5, multiplier_raw="garbage")  # raw 不可解析
    with pytest.raises(ValueError):
        _fact(multiplier=0.5, multiplier_raw="0x")  # 非 product config 格式
    # 一致 / 缺失 raw 合法
    _fact(multiplier=0.5, multiplier_raw="x0.5")
    _fact(multiplier=0.5, multiplier_raw=None)
    _fact(multiplier=None, multiplier_raw="x0.17")  # 无 parsed 值不校验


# ---------------------------------------------------------------------------
# 11. capability/qualification precedence 不回归（Requirement 6/7）
# ---------------------------------------------------------------------------


def test_fresh_free_candidates_still_ineligible():
    """hy3 仍 FRESH + authoritative cheap（字段完整），但 tier=None
    + qualification=unknown → is_usable_candidate 仍 False。
    （hy4-preview 自 SECOND-CANDIDATE-001 起已由独立 probe 资格化；经济事实
    只决定 probe priority，不赋予资格。）"""
    facts = baseline_economic_facts()
    assert classify_freshness(facts["hy3"], NOW) == ECON_FRESH
    assert classify_freshness(facts["hy4-preview"], NOW) == ECON_FRESH
    assert is_authoritative_cheap(facts["hy3"], NOW) is True
    assert is_authoritative_cheap(facts["hy4-preview"], NOW) is True
    reg = baseline_registry()
    e = reg["hy3"]
    assert is_usable_candidate(e) is False
    assert e.capability_tier is None
    assert e.qualification.status == "unknown"
    assert e.cost_class == "UNKNOWN"


def test_qualified_candidate_capability_qualification_unchanged():
    """deepseek-v4-flash：T4 + QUALIFIED 保持；经济事实（discount 0.5, freshness
    UNKNOWN）不改任何 registry 维度。"""
    facts = baseline_economic_facts()
    f = facts["deepseek-v4-flash"]
    assert f.multiplier == 0.17
    assert f.promotion_status == PROMO_STATUS_DISCOUNT
    assert f.promotion_factor == 0.5
    assert classify_freshness(f, NOW) == ECON_UNKNOWN
    assert is_authoritative_cheap(f, NOW) is False
    reg = baseline_registry()
    e = reg["deepseek-v4-flash"]
    assert e.capability_tier == "T4"
    assert e.qualification.status == "qualified"
    assert is_usable_candidate(e) is True
    assert e.cost_class == "UNKNOWN"


def test_selector_unchanged_economics_not_consumed():
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    assert decision.eligible == ("deepseek-v4-flash", "hy4-preview")
    assert decision.selected == "deepseek-v4-flash"
    reasons = {rec.candidate: rec.reason for rec in decision.excluded}
    assert reasons["hy3"] == EXCL_CAPABILITY_INSUFFICIENT
    assert "hy4-preview" not in reasons  # eligible 来自独立 probe 证据，非经济事实


# ---------------------------------------------------------------------------
# 12. production WorkBuddy invocation 不变（Requirement 7/8）
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
# 13. 经济模块仍不被路由代码 import（事实层无消费方）
# ---------------------------------------------------------------------------


def test_economics_module_not_imported_by_routing_code():
    import importlib
    import pathlib

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
# 附加：基线事实完整性/一致性不回归（收紧 gate 后 baseline 仍全部合法）
# ---------------------------------------------------------------------------


def test_baseline_facts_all_consistent_and_unchanged():
    facts = baseline_economic_facts()
    assert set(facts) == set(WORKBUDDY_CANDIDATE_IDS)
    for mid, f in facts.items():
        assert f.multiplier is not None
        if f.promotion_status is None:
            # 无促销 → 一致性 gate False（无证据不进入已知排序）但合法
            assert economic_fields_consistent(f) is False
        else:
            assert economic_fields_consistent(f) is True, f"{mid}: baseline inconsistent"
    # 关键候选语义不变
    assert is_authoritative_cheap(facts["hy3"], NOW) is True
    assert is_authoritative_cheap(facts["hy4-preview"], NOW) is True
    assert cheapness_rank(facts["hy3"], NOW) == RANK_AUTHORITATIVE_CHEAP
    assert cheapness_rank(facts["glm-5.2"], NOW) == RANK_UNKNOWN_OR_STALE  # daily-only
    assert cheapness_rank(facts["deepseek-v4-flash"], NOW) == RANK_UNKNOWN_OR_STALE
    # rank 顺序不变量
    assert RANK_AUTHORITATIVE_CHEAP < RANK_FRESH_DISCOUNT < RANK_UNKNOWN_OR_STALE
