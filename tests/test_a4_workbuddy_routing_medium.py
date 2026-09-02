"""AAF v0.5 A4 — WorkBuddy active economic routing MEDIUM 扩展聚焦测试
（TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002：把 active-routing risk 域
从 explicit LOW 扩展到 explicit LOW + MEDIUM；A4-001 + FIX-001 已接受的
capability / qualification / trustworthy economics / >=2 economic candidates /
Auto fail-closed / artifact / no-fallback 契约全部原样复用）。

Req 16 测试矩阵（A–M）+ 附加守卫：
- A. MEDIUM + 2 capability-qualified + 2 trustworthy economics
     → routing_applied=true → 确定性经济 winner → 恰好一个 --model
- B. MEDIUM + 2 qualified 但只有 1 个 trustworthy → Auto → 无 --model
- C. MEDIUM + 0 trustworthy economics → Auto
- D. MEDIUM + 只有 1 个 capability-qualified → Auto
- E. MEDIUM capability-insufficient 候选在经济前被排除（含 T4 对 MEDIUM floor T3）
- F. MEDIUM qualification-unknown 候选在经济前被排除
- G. LOW 既有 routed 受控场景保持有效（002 不改变 LOW 行为，Req 9）
- H. LOW 真实 facts Auto（trustworthy < 2）保持有效
- I. HIGH → Auto（受控 registry 也路由不了 → 证明是 risk gate 而非候选不足）
- J. CRITICAL → Auto
- K. missing Risk → Auto
- L. 输入顺序不影响 winner（MEDIUM）
- M. 无 --effort / 无 fallback（MEDIUM routed 真实 argv 恰好一个 --model）
+ 附加：
- MEDIUM 复用既有 selector capability floor（risk_contract
  RISK_FLOORS[MEDIUM].validator = T3）——T4 候选 LOW eligible 但 MEDIUM
  ineligible（Req 5：绝不单独放宽/硬编码 MEDIUM eligibility）
- MEDIUM + 3 eligible，economics 后剩 2 → routed（FIX-001 两候选 gate 在
  MEDIUM 同样生效）
- MEDIUM artifact authority 语义（risk_class=MEDIUM + risk_source 记录、
  authoritative=true、Auto 不声称 routed_model、validate fail-closed）
- MEDIUM env apply/restore（绝不泄漏到后续 stage / 调用方）
- runner 集成：MEDIUM 受控全链 routed（registry+facts 注入，生产 runner 恒
  真实数据）+ MEDIUM 真实 registry Auto + HIGH control + env 还原

边界（Boundaries）：无 HIGH/CRITICAL active routing、无 effort routing、无
automatic fallback、无 Cost Gate UX、无 health/quarantine、无 runtime
requalification、无 Hermes（A3）/Codex 路由变更、无 A5/A6。
"""
import json
import os
from datetime import datetime

import pytest

import ai_agent_framework.cost_guard as cg
import ai_agent_framework.model_registry as mr
import ai_agent_framework.runner as runner_mod
from ai_agent_framework import adapters
from ai_agent_framework import shadow_observation as so
from ai_agent_framework import workbuddy_economics as we
from ai_agent_framework import workbuddy_routing as wr
from ai_agent_framework.risk_contract import (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    ROLE_VALIDATOR,
)

# 参考时间（2026-09-02：hy4-preview 免费窗口 08-28..09-11 内 → FRESH）。
NOW = datetime.fromisoformat("2026-09-02T03:30:00+08:00")

# MEDIUM validator floor = T3（risk_contract.RISK_FLOORS[MEDIUM].validator）。
# 本文件默认候选 tier = T3 → MEDIUM-eligible；T4 只对 LOW 合格（floor T4）。
MEDIUM_FLOOR_TIER = mr.CAP_TIER_T3

# 生产 WorkBuddy invocation 的精确 Auto 形状（无 --model / --effort）
AUTO_ARGS_TAIL = ["-p", "--output-format", "text", "-y"]

# 受控两可信 MEDIUM 场景的确定性经济 winner（rank 0 权威免费 outranks
# rank 1 已知折扣；generic 候选，不是硬编码特例）
CONTROLLED_WINNER = "med-free"


def _entry(**overrides) -> mr.RegistryEntry:
    base = dict(
        model="m",
        provider=None,
        applicable_agents=("workbuddy",),
        capability_tier=MEDIUM_FLOOR_TIER,  # T3 → MEDIUM-eligible（floor T3）
        cost_class=mr.COST_CLASS_UNKNOWN,
        locality=mr.LOCALITY_UNKNOWN,
        qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED),
    )
    base.update(overrides)
    return mr.RegistryEntry(**base)


def _low_entry(**overrides) -> mr.RegistryEntry:
    """T4 候选：LOW（floor T4）合格；MEDIUM（floor T3）不合格。"""
    return _entry(capability_tier=mr.CAP_TIER_T4, **overrides)


def _registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


def _fact(**kw) -> we.EconomicFact:
    base = dict(
        model_id="m",
        multiplier=1.0,
        multiplier_raw="x1.0",
        promotion_status=None,
        promotion_factor=None,
        valid_from=None,
        valid_until=None,
        source="test-medium",
    )
    base.update(kw)
    return we.EconomicFact(**base)


def _fresh_free_fact(model_id: str, valid_until: str = "2026-12-31T00:00:00+08:00") -> we.EconomicFact:
    return _fact(
        model_id=model_id, multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until=valid_until,
    )


def _fresh_discount_fact(model_id: str, multiplier: float) -> we.EconomicFact:
    return _fact(
        model_id=model_id, multiplier=multiplier, multiplier_raw=f"x{multiplier}",
        promotion_status="discount", promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
    )


def _unknown_fact(model_id: str) -> we.EconomicFact:
    """无日期窗口 → freshness UNKNOWN（fail closed）。"""
    return _fact(model_id=model_id, multiplier=0.17, multiplier_raw="x0.17")


def _stale_free_fact(model_id: str) -> we.EconomicFact:
    return _fact(
        model_id=model_id, multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-08-01T00:00:00+08:00",
    )


def _medium_two_trustworthy_registry() -> dict[str, mr.RegistryEntry]:
    """两个 MEDIUM-eligible（T3 + QUALIFIED）候选。"""
    return _registry(_entry(model="med-free"), _entry(model="med-discount"))


def _medium_two_trustworthy_facts() -> dict[str, we.EconomicFact]:
    """两个候选都有 trustworthy economics：med-free rank 0 权威免费 outranks
    med-discount rank 1 已知折扣 → winner = med-free。"""
    return {
        "med-free": _fresh_free_fact("med-free"),
        "med-discount": _fresh_discount_fact("med-discount", multiplier=0.5),
    }


def _structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = '{"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}'
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END"


# ---------------------------------------------------------------------------
# A. MEDIUM + 2 capability-qualified + 2 trustworthy economics → routed
# ---------------------------------------------------------------------------


def test_a_medium_two_qualified_two_trustworthy_routes(monkeypatch):
    """Req 16A：MEDIUM + 2 个 T3-qualified + 2 个 trustworthy economics →
    routing_applied=true；经济 winner（rank 0 免费）被选中；真实 invocation
    恰好一个 --model <winner>、无 --effort。"""
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy",
        _medium_two_trustworthy_registry(), facts=_medium_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == CONTROLLED_WINNER
    assert rec["routed_model"] == CONTROLLED_WINNER
    assert rec["risk_class"] == RISK_MEDIUM
    assert rec["risk_source"] == so.TASK_RISK_SOURCE
    assert rec["eligible"] == ["med-discount", "med-free"]
    assert rec["economically_trustworthy"] == ["med-free", "med-discount"]
    assert rec["fallback_used"] is False
    assert rec["reason"].startswith(wr.REASON_APPLIED)
    assert f"explicit Risk={RISK_MEDIUM}" in rec["reason"]
    wr.validate_workbuddy_routing(rec)
    # 真实 argv：恰好一个 --model <winner>，无 --effort
    monkeypatch.setattr(adapters, "_require", lambda cmd: "C:/fake/codebuddy.exe")
    args, stdin_data, _ = adapters._workbuddy_invocation("P", {}, model=rec["routed_model"])
    assert args == ["C:/fake/codebuddy.exe", *AUTO_ARGS_TAIL, "--model", CONTROLLED_WINNER]
    assert args.count("--model") == 1
    assert "--effort" not in args
    assert stdin_data == "P"


def test_a_medium_economic_tie_deterministic_winner():
    """MEDIUM 经济完全相等（同 rank 同 multiplier）→ model_id 字典序确定性
    tie-break（输入顺序无关）。"""
    reg = _registry(_entry(model="zz-model"), _entry(model="aa-model"))
    facts = {"zz-model": _fresh_free_fact("zz-model"), "aa-model": _fresh_free_fact("aa-model")}
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "aa-model"  # 字典序
    assert rec["routed_model"] == "aa-model"


# ---------------------------------------------------------------------------
# B. MEDIUM + 2 qualified 但只有 1 个 trustworthy → Auto
# ---------------------------------------------------------------------------


def test_b_medium_one_trustworthy_auto():
    """Req 16B：MEDIUM + 2 个 T3-qualified，经济过滤后只有 1 个可信 →
    INSUFFICIENT_ECONOMIC_CANDIDATES → Auto，无 --model。"""
    reg = _medium_two_trustworthy_registry()
    facts = {
        "med-free": _fresh_free_fact("med-free"),
        "med-discount": _unknown_fact("med-discount"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["med-discount", "med-free"]
    assert rec["economically_trustworthy"] == ["med-free"]
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["fallback_used"] is False
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    assert "CodeBuddy Auto" in rec["invocation"]
    wr.validate_workbuddy_routing(rec)


# ---------------------------------------------------------------------------
# C. MEDIUM + 0 trustworthy economics → Auto
# ---------------------------------------------------------------------------


def test_c_medium_zero_trustworthy_auto():
    """Req 16C：MEDIUM + 2 个 T3-qualified，经济过滤后 0 个可信（STALE +
    UNKNOWN）→ NO_TRUSTWORTHY_ECONOMIC_WINNER → Auto。"""
    reg = _medium_two_trustworthy_registry()
    facts = {
        "med-free": _stale_free_fact("med-free"),
        "med-discount": _unknown_fact("med-discount"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["economically_trustworthy"] == []
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)
    assert "CodeBuddy Auto" in rec["invocation"]


# ---------------------------------------------------------------------------
# D. MEDIUM + 只有 1 个 capability-qualified → Auto
# ---------------------------------------------------------------------------


def test_d_medium_one_eligible_auto():
    """Req 16D：MEDIUM + 只有 1 个 T3-qualified 候选 → INSUFFICIENT_ELIGIBLE
    → Auto（economics 不能救活不足两个 eligible 的场景）。"""
    reg = _registry(_entry(model="solo"))
    facts = {"solo": _fresh_free_fact("solo")}
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["solo"]
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    assert "fewer than two" in rec["reason"]


# ---------------------------------------------------------------------------
# E. MEDIUM capability-insufficient 候选在经济前被排除（含 floor 语义）
# ---------------------------------------------------------------------------


def test_e_medium_capability_insufficient_excluded_before_economics():
    """Req 16E + Req 5：MEDIUM 复用既有 selector capability floor（T3）。
    T4 候选（LOW eligible）对 MEDIUM CAPABILITY_INSUFFICIENT —— 绝不单独放宽
    eligibility；FRESH 免费事实也不救活它；经济层根本不消费它。"""
    reg = _registry(
        _entry(model="t3-ok"),                       # T3 → MEDIUM eligible
        _low_entry(model="t4-only"),                 # T4 → MEDIUM ineligible
    )
    facts = {
        "t3-ok": _fresh_discount_fact("t3-ok", multiplier=0.5),
        "t4-only": _fresh_free_fact("t4-only"),      # rank 0 但 ineligible
    }
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["t3-ok"]
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    excluded = {e["candidate"]: e["reason"] for e in rec["excluded"]}
    assert excluded["t4-only"] == "CAPABILITY_INSUFFICIENT"
    assert "t4-only" not in rec["economic_facts"]  # 经济学根本没消费它
    # 同一 T4 候选对 LOW 是 eligible 的（floor T4）——证明差异来自 selector
    # floor，不是候选本身
    rec_low = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert "t4-only" in rec_low["eligible"]


# ---------------------------------------------------------------------------
# F. MEDIUM qualification-unknown 候选在经济前被排除
# ---------------------------------------------------------------------------


def test_f_medium_qualification_unknown_excluded_before_economics():
    """Req 16F：MEDIUM + qualification=unknown 候选即使 FRESH 免费也不
    eligible；经济事实绝不赋予资格。"""
    reg = _registry(
        _entry(model="ok-model"),
        _entry(model="unknown-qual", qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_UNKNOWN)),
    )
    facts = {
        "ok-model": _fresh_discount_fact("ok-model", multiplier=0.5),
        "unknown-qual": _fresh_free_fact("unknown-qual"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["ok-model"]
    assert rec["routing_applied"] is False
    excluded = {e["candidate"]: e["reason"] for e in rec["excluded"]}
    assert excluded["unknown-qual"] == "QUALIFICATION_UNKNOWN"
    assert "unknown-qual" not in rec["economic_facts"]


# ---------------------------------------------------------------------------
# G. LOW 既有 routed 受控场景保持有效（002 不改变 LOW 行为）
# ---------------------------------------------------------------------------


def test_g_low_controlled_two_trustworthy_routed_unchanged():
    """Req 16G：LOW + 两个 T4-qualified + 两个 trustworthy economics →
    仍 routing_applied=true（winner = rank 0 免费）。"""
    reg = _registry(_low_entry(model="low-free"), _low_entry(model="low-discount"))
    facts = {
        "low-free": _fresh_free_fact("low-free"),
        "low-discount": _fresh_discount_fact("low-discount", multiplier=0.5),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "low-free"
    assert rec["routed_model"] == "low-free"
    assert rec["reason"].startswith(wr.REASON_APPLIED)
    assert f"explicit Risk={RISK_LOW}" in rec["reason"]


# ---------------------------------------------------------------------------
# H. LOW 真实 facts Auto（trustworthy < 2）保持有效
# ---------------------------------------------------------------------------


def test_h_low_real_facts_auto_unchanged():
    """Req 16H：LOW + 真实 baseline facts（facts=None → baseline）→ 经济过滤
    后只有 1 个可信候选 → Auto（INSUFFICIENT_ECONOMIC_CANDIDATES）。当前真实
    数据不被人为伪造成可路由。"""
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert len(rec["economically_trustworthy"]) == 1
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    assert "CodeBuddy Auto" in rec["invocation"]


# ---------------------------------------------------------------------------
# I / J / K. HIGH / CRITICAL / missing Risk → Auto（即使受控 registry 可路由）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk", [RISK_HIGH, RISK_CRITICAL])
def test_ij_outside_slice_risk_auto_even_with_routeable_candidates(risk):
    """Req 16I/J：HIGH/CRITICAL 在 active slice 之外 —— 即使提供两个
    MEDIUM-eligible + 两个 trustworthy economics（唯一不路由原因 = risk gate），
    也必须 Auto。"""
    rec = wr.decide_workbuddy_route(
        risk, ROLE_VALIDATOR, "workbuddy",
        _medium_two_trustworthy_registry(), facts=_medium_two_trustworthy_facts(),
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_RISK_OUTSIDE_SLICE)
    assert "CodeBuddy Auto" in rec["invocation"]


def test_k_missing_risk_auto_even_with_routeable_candidates():
    """Req 16K：missing Risk → RISK_UNAVAILABLE → Auto（missing ≠ LOW/MEDIUM）。"""
    rec = wr.decide_workbuddy_route(
        None, ROLE_VALIDATOR, "workbuddy",
        _medium_two_trustworthy_registry(), facts=_medium_two_trustworthy_facts(),
        now=NOW,
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["risk_source"] == wr.RISK_UNAVAILABLE
    assert rec["reason"].startswith(wr.REASON_RISK_UNAVAILABLE)
    assert "CodeBuddy Auto" in rec["invocation"]


# ---------------------------------------------------------------------------
# L. 输入顺序不影响 winner（MEDIUM）
# ---------------------------------------------------------------------------


def test_l_medium_input_ordering_independent():
    """Req 16L：registry 插入顺序 + facts dict 顺序反转 → 同一决策、同一 winner。"""
    reg_fwd = _registry(_entry(model="cand-a"), _entry(model="cand-b"))
    facts_fwd = {
        "cand-a": _fresh_free_fact("cand-a"),
        "cand-b": _fresh_discount_fact("cand-b", multiplier=0.5),
    }
    reg_rev = _registry(_entry(model="cand-b"), _entry(model="cand-a"))
    facts_rev = {
        "cand-b": _fresh_discount_fact("cand-b", multiplier=0.5),
        "cand-a": _fresh_free_fact("cand-a"),
    }
    rec_fwd = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg_fwd, facts=facts_fwd,
        now=NOW, risk_source="t",
    )
    rec_rev = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg_rev, facts=facts_rev,
        now=NOW, risk_source="t",
    )
    assert rec_fwd["routing_applied"] is True
    assert rec_rev["routing_applied"] is True
    assert rec_rev["selected"] == rec_fwd["selected"] == "cand-a"
    assert rec_rev["economically_trustworthy"] == rec_fwd["economically_trustworthy"]
    assert rec_rev["economically_excluded"] == rec_fwd["economically_excluded"]


# ---------------------------------------------------------------------------
# M. 无 --effort / 无 fallback（MEDIUM routed）
# ---------------------------------------------------------------------------


def test_m_medium_no_effort_no_fallback():
    """Req 16M：MEDIUM routed 记录 fallback_used=false；validate 拒绝
    fallback_used=True（fixed semantic，无 fallback 机制）。"""
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy",
        _medium_two_trustworthy_registry(), facts=_medium_two_trustworthy_facts(),
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["fallback_used"] is False
    assert "no fallback" in rec["invocation"].lower() or "fallback" in rec["invocation"].lower()
    bad = dict(rec)
    bad["fallback_used"] = True
    with pytest.raises(ValueError):
        wr.validate_workbuddy_routing(bad)


# ---------------------------------------------------------------------------
# 附加：MEDIUM + 3 eligible，economics 后剩 2 → routed（FIX-001 gate 同效）
# ---------------------------------------------------------------------------


def test_medium_three_eligible_two_survive_economics_routed():
    reg = _registry(
        _entry(model="cand-a"), _entry(model="cand-b"), _entry(model="cand-c"),
    )
    facts = {
        "cand-a": _fresh_free_fact("cand-a"),
        "cand-b": _fresh_discount_fact("cand-b", multiplier=0.5),
        "cand-c": _fact(  # FRESH 但无促销/全价 → rank 2
            model_id="cand-c", multiplier=0.9, multiplier_raw="x0.9",
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
    }
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["economically_trustworthy"] == ["cand-a", "cand-b"]
    assert rec["selected"] == "cand-a"
    assert rec["economically_excluded"] == [
        {"candidate": "cand-c", "reason": wr.ECON_INCONSISTENT}
    ]


# ---------------------------------------------------------------------------
# 附加：MEDIUM artifact authority 语义
# ---------------------------------------------------------------------------


def test_medium_artifact_authority_routed(tmp_path):
    """MEDIUM routed artifact：risk_class=MEDIUM + risk_source 记录、
    authoritative=true、selected == routed_model、roundtrip 一致。"""
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy",
        _medium_two_trustworthy_registry(), facts=_medium_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    path = wr.save_workbuddy_routing(tmp_path, rec)
    loaded = wr.load_workbuddy_routing(tmp_path)
    assert loaded is not None
    assert path.name == wr.ARTIFACT_FILENAME
    assert loaded["risk_class"] == RISK_MEDIUM
    assert loaded["risk_source"] == so.TASK_RISK_SOURCE
    assert loaded["authoritative"] is True
    assert loaded["routing_applied"] is True
    assert loaded["selected"] == loaded["routed_model"] == CONTROLLED_WINNER
    assert loaded["fallback_used"] is False


def test_medium_artifact_authority_auto(tmp_path):
    """MEDIUM Auto artifact：不得声称任何模型路由（selected/routed_model
    None）；no-route reason 保留；save/load roundtrip 一致。"""
    reg = _medium_two_trustworthy_registry()
    facts = {"med-free": _fresh_free_fact("med-free"), "med-discount": _unknown_fact("med-discount")}
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    path = wr.save_workbuddy_routing(tmp_path, rec)
    loaded = wr.load_workbuddy_routing(tmp_path)
    assert loaded is not None
    assert loaded["risk_class"] == RISK_MEDIUM
    assert loaded["routing_applied"] is False
    assert loaded["selected"] is None
    assert loaded["routed_model"] is None
    assert loaded["reason"] == rec["reason"]
    assert loaded["fallback_used"] is False
    assert loaded["authoritative"] is True


# ---------------------------------------------------------------------------
# 附加：MEDIUM env apply/restore
# ---------------------------------------------------------------------------


def test_medium_env_apply_restore(monkeypatch):
    monkeypatch.delenv(wr.ENV_WORKBUDDY_MODEL, raising=False)
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy",
        _medium_two_trustworthy_registry(), facts=_medium_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    saved = wr.apply_workbuddy_model_env(rec)
    assert os.environ.get(wr.ENV_WORKBUDDY_MODEL) == CONTROLLED_WINNER
    wr.restore_workbuddy_model_env(saved)
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ
    # 旧值存在 → restore 还原
    monkeypatch.setenv(wr.ENV_WORKBUDDY_MODEL, "old-value")
    saved2 = wr.apply_workbuddy_model_env(rec)
    assert os.environ.get(wr.ENV_WORKBUDDY_MODEL) == CONTROLLED_WINNER
    wr.restore_workbuddy_model_env(saved2)
    assert os.environ.get(wr.ENV_WORKBUDDY_MODEL) == "old-value"


# ---------------------------------------------------------------------------
# 附加：runner 集成（真实 runner + fake run_agent；固定 now 保证时间稳定）
# ---------------------------------------------------------------------------


def _task_text(risk):
    body = """AAF_TASK_BEGIN
# Task ID
AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-TEST

# Task Name
test

# Workspace
D:\\AdyAI\\ai-agent-framework

# Objective
test objective

# Route
hermes -> workbuddy -> codex

# Acceptance
1. ok

AAF_TASK_END
"""
    if risk is None:
        return body
    return body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)


def _run_runner(tmp_path, monkeypatch, task_text, fake_run_agent=None, registry=None, facts=None):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    if fake_run_agent is None:
        fake_run_agent = lambda agent, prompt, workspace: _structured_ok(agent)  # noqa: E731
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    real_decide = wr.decide_workbuddy_route

    def fixed_decide(risk_class, role, stage_agent, reg, **kw):
        kw.pop("now", None)  # runner 传真实 wall clock；测试固定参考时间
        if registry is not None:
            reg = registry  # 受控 registry 注入（仅测试；生产 runner 恒 baseline）
        if facts is not None:
            kw["facts"] = facts
        return real_decide(risk_class, role, stage_agent, reg, now=NOW, **kw)

    monkeypatch.setattr(runner_mod.workbuddy_routing_mod, "decide_workbuddy_route", fixed_decide)
    runner_mod.run(task_file, ws, out)
    return out


def test_runner_medium_controlled_routes_with_exact_model(tmp_path, monkeypatch):
    """MEDIUM 全链（受控两可信候选）：workbuddy_active_routing.json
    routing_applied=true / routed_model=med-free / risk_class=MEDIUM；
    AAF_WORKBUDDY_MODEL 在 workbuddy invocation 时可见；执行后已还原；
    stage result 携带 workbuddy_active_routing_ref；全链 SUCCESS。"""
    seen = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "workbuddy":
            seen["wb_model"] = os.environ.get(wr.ENV_WORKBUDDY_MODEL)
        return _structured_ok(agent)

    out = _run_runner(
        tmp_path, monkeypatch, _task_text(RISK_MEDIUM),
        fake_run_agent, registry=_medium_two_trustworthy_registry(),
        facts=_medium_two_trustworthy_facts(),
    )
    assert seen["wb_model"] == CONTROLLED_WINNER
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ  # 已还原（不泄漏）
    rec = wr.load_workbuddy_routing(out)
    assert rec is not None
    assert rec["risk_class"] == RISK_MEDIUM
    assert rec["risk_source"] == so.TASK_RISK_SOURCE
    assert rec["routing_applied"] is True
    assert rec["selected"] == rec["routed_model"] == CONTROLLED_WINNER
    assert rec["fallback_used"] is False
    assert rec["authoritative"] is True
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage.get("workbuddy_active_routing_ref", {}).get("entry") == "workbuddy"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_medium_real_registry_auto(tmp_path, monkeypatch):
    """MEDIUM 全链（真实 registry，零注入）：真实 WorkBuddy 候选 T4 < MEDIUM
    floor T3 → 0 eligible → Auto；env 从未被触碰；全链 SUCCESS。当前真实数据
    不被人为放宽（Req 15）。"""
    seen = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "workbuddy":
            seen["wb_model"] = os.environ.get(wr.ENV_WORKBUDDY_MODEL)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task_text(RISK_MEDIUM), fake_run_agent)
    assert seen["wb_model"] is None
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ
    rec = wr.load_workbuddy_routing(out)
    assert rec is not None
    assert rec["risk_class"] == RISK_MEDIUM
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    assert "CodeBuddy Auto" in rec["invocation"]
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_high_control_auto_with_routeable_candidates(tmp_path, monkeypatch):
    """HIGH 全链（即使注入受控两可信候选）：routing_applied=false /
    routed_model=None；env 从未被触碰；全链 SUCCESS（risk gate 才是阻断）。"""
    seen = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "workbuddy":
            seen["wb_model"] = os.environ.get(wr.ENV_WORKBUDDY_MODEL)
        return _structured_ok(agent)

    out = _run_runner(
        tmp_path, monkeypatch, _task_text(RISK_HIGH),
        fake_run_agent, registry=_medium_two_trustworthy_registry(),
        facts=_medium_two_trustworthy_facts(),
    )
    assert seen["wb_model"] is None
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ
    rec = wr.load_workbuddy_routing(out)
    assert rec is not None
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_RISK_OUTSIDE_SLICE)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
