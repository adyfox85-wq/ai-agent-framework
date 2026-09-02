"""AAF v0.5 A4 — FIX-001 focused regression/adversarial tests
（TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001：enforce the
two-candidate economic routing gate）。

Requirement 5 blocker 收口：active routing 的最小候选数量 gate 必须作用于
**全部**过滤之后（capability sufficiency + qualification/usability +
trustworthy economics）。只有 ``len(economically_trustworthy) >= 2`` 才允许
economic winner selection；经济过滤后少于 2 个可信候选 → routing_applied=false /
routed_model=None / fallback_used=false / CodeBuddy Auto / artifact 记录显式
no-route reason（1 个 → INSUFFICIENT_ECONOMIC_CANDIDATES；0 个 →
NO_TRUSTWORTHY_ECONOMIC_WINNER）。

Req 12 矩阵：
A. 2 个 capability+qualified，但只有 1 个 trustworthy economics → Auto，无 --model
B. 2 个 capability+qualified，2 个 trustworthy economics → routing applied，
   economic winner 选中，恰好一个 --model
C. 3 个 eligible，economics 后剩 2 个 → routing allowed
D. 2 个 eligible，economics 后剩 0 个 → Auto
E. 只有 1 个 capability-qualified → Auto
F. STALE / UNKNOWN / incomplete / contradictory 经济事实不能凑满两个候选
G. input ordering 不影响结果

+ 明确区分 no-route reason（INSUFFICIENT_ECONOMIC_CANDIDATES ≠
  INSUFFICIENT_ELIGIBLE_CANDIDATES，Req 4，绝不混用）
+ 不 hard-code 任何 model id（generic 候选，Req 8）
+ active artifact 准确反映 eligible / economically_trustworthy /
  routing_applied / routed_model / no-route reason / fallback_used=false（Req 11）
+ capability/qualification gate 优先于 economics（Req 5 不变：经济不能救活
  不足两个 eligible 的场景）

边界（Boundaries，002）：无 HIGH/CRITICAL active routing、无 effort routing、无
automatic fallback、无 Cost Gate UX、无 health/quarantine、无 runtime
requalification、无 Hermes（A3）/Codex 路由变更、无 A5/A6。
"""
from datetime import datetime

import pytest

import ai_agent_framework.model_registry as mr
from ai_agent_framework import adapters
from ai_agent_framework import shadow_observation as so
from ai_agent_framework import workbuddy_economics as we
from ai_agent_framework import workbuddy_routing as wr
from ai_agent_framework.risk_contract import RISK_LOW, ROLE_VALIDATOR

# 参考时间（2026-09-02：hy4-preview 免费窗口 08-28..09-11 内 → FRESH）。
NOW = datetime.fromisoformat("2026-09-02T03:30:00+08:00")

# 生产 WorkBuddy invocation 的精确 Auto 形状（无 --model / --effort）
AUTO_ARGS_TAIL = ["-p", "--output-format", "text", "-y"]


def _entry(**overrides) -> mr.RegistryEntry:
    base = dict(
        model="m",
        provider=None,
        applicable_agents=("workbuddy",),
        capability_tier=mr.CAP_TIER_T4,
        cost_class=mr.COST_CLASS_UNKNOWN,
        locality=mr.LOCALITY_UNKNOWN,
        qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED),
    )
    base.update(overrides)
    return mr.RegistryEntry(**base)


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
        source="test-fix001",
    )
    base.update(kw)
    return we.EconomicFact(**base)


def _fresh_free_fact(model_id: str, valid_until: str = "2026-12-31T00:00:00+08:00") -> we.EconomicFact:
    """FRESH 权威免费（rank 0）：FRESH + free + multiplier 0.0 + factor 0.0。"""
    return _fact(
        model_id=model_id, multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until=valid_until,
    )


def _fresh_discount_fact(model_id: str, multiplier: float) -> we.EconomicFact:
    """FRESH 已知折扣（rank 1）：字段完整且一致。"""
    return _fact(
        model_id=model_id, multiplier=multiplier, multiplier_raw=f"x{multiplier}",
        promotion_status="discount", promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
    )


def _stale_free_fact(model_id: str) -> we.EconomicFact:
    """免费窗口已过期 → STALE（fail closed，绝不当作可信候选）。"""
    return _fact(
        model_id=model_id, multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.0,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-08-01T00:00:00+08:00",
    )


def _unknown_fact(model_id: str) -> we.EconomicFact:
    """无日期窗口 → freshness UNKNOWN（fail closed）。"""
    return _fact(model_id=model_id, multiplier=0.17, multiplier_raw="x0.17")


def _incomplete_fact(model_id: str) -> we.EconomicFact:
    """FRESH 但字段缺失（multiplier=None / promotion_factor=None）→ rank 2。"""
    return _fact(
        model_id=model_id, multiplier=None, multiplier_raw=None,
        promotion_status="discount", promotion_factor=None,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
    )


def _contradictory_fact(model_id: str) -> we.EconomicFact:
    """free 状态但非零 factor → 内部矛盾（economic_fields_consistent=False）→ rank 2。"""
    return _fact(
        model_id=model_id, multiplier=0.0, multiplier_raw="x0.00",
        promotion_status="free", promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
    )


# ---------------------------------------------------------------------------
# A. 2 个 capability+qualified，但只有 1 个 trustworthy economics → Auto
# ---------------------------------------------------------------------------


def test_a_two_eligible_one_trustworthy_auto():
    """Req 12A：两个 eligible（capability+qualification 通过）+ 只有 1 个可信
    经济候选 → routing_applied=false / routed_model=None / fallback_used=false /
    CodeBuddy Auto；artifact 记录显式 no-route reason
    （INSUFFICIENT_ECONOMIC_CANDIDATES，与 capability 不足 reason 明确区分）。"""
    reg = _registry(_entry(model="cand-a"), _entry(model="cand-b"))
    facts = {
        "cand-a": _fresh_free_fact("cand-a"),
        "cand-b": _unknown_fact("cand-b"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["eligible"] == ["cand-a", "cand-b"]
    assert rec["economically_trustworthy"] == ["cand-a"]
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["fallback_used"] is False
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    assert "CodeBuddy Auto" in rec["invocation"]
    assert rec["economically_excluded"] == [
        {"candidate": "cand-b", "reason": wr.ECON_FRESHNESS_UNKNOWN}
    ]
    wr.validate_workbuddy_routing(rec)


def test_a_real_baseline_facts_one_trustworthy_auto():
    """Req 12A/13：真实 baseline facts（facts=None → baseline_economic_facts()）
    下两个 eligible（deepseek-v4-flash + hy4-preview），但经济过滤后只有
    hy4-preview 一个可信 → Auto。当前真实 facts **不被人为伪造**成可路由；
    不 hard-code 任何候选（断言只依赖经济 rank 语义）。"""
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert len(rec["economically_trustworthy"]) == 1
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    # economically_trustworthy 恰好 1 个 → 不满足 >= 2 → Auto
    assert "CodeBuddy Auto" in rec["invocation"]


# ---------------------------------------------------------------------------
# B. 2 个 eligible + 2 个 trustworthy economics → routing applied + 恰好一个 --model
# ---------------------------------------------------------------------------


def test_b_two_trustworthy_routes_with_exactly_one_model(monkeypatch):
    """Req 12B：两个 eligible 且两个都有 trustworthy economics →
    routing_applied=true；economic winner 被选中（同 rank 同 multiplier →
    model_id 字典序确定性 tie-break）；真实 invocation 恰好一个 --model <winner>、
    无 --effort。"""
    reg = _registry(_entry(model="cand-b"), _entry(model="cand-a"))
    facts = {
        "cand-a": _fresh_free_fact("cand-a"),
        "cand-b": _fresh_free_fact("cand-b"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "cand-a"  # 字典序 tie-break（cand-a < cand-b）
    assert rec["routed_model"] == "cand-a"
    assert rec["economically_trustworthy"] == ["cand-a", "cand-b"]
    assert rec["fallback_used"] is False
    assert rec["reason"].startswith(wr.REASON_APPLIED)
    wr.validate_workbuddy_routing(rec)
    # 真实 argv：恰好一个 --model <winner>，无 --effort
    monkeypatch.setattr(adapters, "_require", lambda cmd: "C:/fake/codebuddy.exe")
    args, stdin_data, _ = adapters._workbuddy_invocation("P", {}, model=rec["routed_model"])
    assert args == ["C:/fake/codebuddy.exe", *AUTO_ARGS_TAIL, "--model", "cand-a"]
    assert args.count("--model") == 1
    assert "--effort" not in args
    assert stdin_data == "P"


# ---------------------------------------------------------------------------
# C. 3 个 eligible，economics 后剩 2 个 → routing allowed
# ---------------------------------------------------------------------------


def test_c_three_eligible_two_survive_economics_routed():
    """Req 12C：3 个 eligible；经济过滤后 2 个可信（1 个 rank 2 被排除）→
    满足两候选 gate → routing applied，winner 从可信候选确定性选出。"""
    reg = _registry(
        _entry(model="cand-a"), _entry(model="cand-b"), _entry(model="cand-c"),
    )
    facts = {
        "cand-a": _fresh_free_fact("cand-a"),
        "cand-b": _fresh_discount_fact("cand-b", multiplier=0.5),
        "cand-c": _fact(  # FRESH 但无促销/全价 → rank 2（无已知便宜 rank）
            model_id="cand-c", multiplier=0.9, multiplier_raw="x0.9",
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["economically_trustworthy"] == ["cand-a", "cand-b"]
    assert rec["selected"] == "cand-a"  # rank 0 权威免费 outranks rank 1 折扣
    assert rec["economically_excluded"] == [
        {"candidate": "cand-c", "reason": wr.ECON_INCONSISTENT}
    ]
    assert rec["fallback_used"] is False


# ---------------------------------------------------------------------------
# D. 2 个 eligible，economics 后剩 0 个 → Auto
# ---------------------------------------------------------------------------


def test_d_two_eligible_zero_survive_economics_auto():
    """Req 12D：2 个 eligible，但经济过滤后 0 个可信（STALE + UNKNOWN）→
    NO_TRUSTWORTHY_ECONOMIC_WINNER → Auto。"""
    reg = _registry(_entry(model="cand-a"), _entry(model="cand-b"))
    facts = {
        "cand-a": _stale_free_fact("cand-a"),
        "cand-b": _unknown_fact("cand-b"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["economically_trustworthy"] == []
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)
    assert "CodeBuddy Auto" in rec["invocation"]
    excluded = {e["candidate"]: e["reason"] for e in rec["economically_excluded"]}
    assert excluded["cand-a"] == wr.ECON_STALE
    assert excluded["cand-b"] == wr.ECON_FRESHNESS_UNKNOWN


# ---------------------------------------------------------------------------
# E. 只有 1 个 capability-qualified candidate → Auto
# ---------------------------------------------------------------------------


def test_e_one_eligible_auto():
    """Req 12E：只有 1 个 capability-qualified 候选 → INSUFFICIENT_ELIGIBLE →
    Auto。即使其经济事实 FRESH 免费，economics 也不能救活不足两个 eligible
    的场景（capability/qualification gate 先于 economics，Req 5 不变）。"""
    reg = _registry(_entry(model="solo"))
    facts = {"solo": _fresh_free_fact("solo")}
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["solo"]
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    assert "fewer than two" in rec["reason"]


# ---------------------------------------------------------------------------
# F. STALE / UNKNOWN / incomplete / contradictory 不能凑满两个候选（Req 12F）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_fact_builder, expected_reason",
    [
        (_stale_free_fact, wr.ECON_STALE),
        (_unknown_fact, wr.ECON_FRESHNESS_UNKNOWN),
        (_incomplete_fact, wr.ECON_INCONSISTENT),
        (_contradictory_fact, wr.ECON_INCONSISTENT),
    ],
    ids=["stale", "unknown", "incomplete", "contradictory"],
)
def test_f_one_bad_fact_cannot_fill_second_candidate(bad_fact_builder, expected_reason):
    """Req 12F：一个 FRESH 可信 + 一个 STALE/UNKNOWN/incomplete/contradictory →
    经济过滤后仍只有 1 个可信候选 → Auto。不可信事实绝不凑数。"""
    reg = _registry(_entry(model="good"), _entry(model="bad"))
    facts = {
        "good": _fresh_free_fact("good"),
        "bad": bad_fact_builder("bad"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["economically_trustworthy"] == ["good"]
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    assert rec["economically_excluded"] == [
        {"candidate": "bad", "reason": expected_reason}
    ]


def test_f_three_eligible_only_one_trustworthy_auto():
    """Req 12F 扩展：3 个 eligible，2 个经济事实不可信 → 只剩 1 个可信 →
    Auto（信任度 gate 是逐候选的，不可信者不参与两候选计数）。"""
    reg = _registry(
        _entry(model="good"), _entry(model="stale"), _entry(model="broken"),
    )
    facts = {
        "good": _fresh_free_fact("good"),
        "stale": _stale_free_fact("stale"),
        "broken": _contradictory_fact("broken"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["economically_trustworthy"] == ["good"]
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)


# ---------------------------------------------------------------------------
# G. input ordering 不影响结果（Req 12G）
# ---------------------------------------------------------------------------


def test_g_input_ordering_independent_routed():
    """Req 12G（routed 分支）：registry 插入顺序 + facts dict 顺序反转 →
    同一决策（routing_applied、winner 相同）。"""
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
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg_fwd, facts=facts_fwd,
        now=NOW, risk_source="t",
    )
    rec_rev = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg_rev, facts=facts_rev,
        now=NOW, risk_source="t",
    )
    assert rec_fwd["routing_applied"] is True
    assert rec_rev["routing_applied"] == rec_fwd["routing_applied"]
    assert rec_rev["selected"] == rec_fwd["selected"] == "cand-a"
    assert rec_rev["economically_trustworthy"] == rec_fwd["economically_trustworthy"]
    assert rec_rev["economically_excluded"] == rec_fwd["economically_excluded"]


def test_g_input_ordering_independent_auto():
    """Req 12G（Auto 分支）：顺序反转不影响「1 个可信 → Auto」决策。"""
    reg_fwd = _registry(_entry(model="cand-a"), _entry(model="cand-b"))
    facts_fwd = {"cand-a": _fresh_free_fact("cand-a"), "cand-b": _unknown_fact("cand-b")}
    reg_rev = _registry(_entry(model="cand-b"), _entry(model="cand-a"))
    facts_rev = {"cand-b": _unknown_fact("cand-b"), "cand-a": _fresh_free_fact("cand-a")}
    rec_fwd = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg_fwd, facts=facts_fwd,
        now=NOW, risk_source="t",
    )
    rec_rev = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg_rev, facts=facts_rev,
        now=NOW, risk_source="t",
    )
    assert rec_fwd["routing_applied"] is False
    assert rec_rev["routing_applied"] is False
    assert rec_rev["reason"] == rec_fwd["reason"]
    assert rec_rev["economically_trustworthy"] == rec_fwd["economically_trustworthy"]


# ---------------------------------------------------------------------------
# no-route reason 明确区分（Req 3/4）：INSUFFICIENT_ECONOMIC_CANDIDATES 绝不与
# INSUFFICIENT_ELIGIBLE_CANDIDATES 混用（后者 = capability/qualification 不足）
# ---------------------------------------------------------------------------


def test_reason_tokens_distinct_and_not_confused():
    assert wr.REASON_INSUFFICIENT_ECONOMIC == "INSUFFICIENT_ECONOMIC_CANDIDATES"
    assert wr.REASON_INSUFFICIENT_ELIGIBLE == "INSUFFICIENT_ELIGIBLE_CANDIDATES"
    assert wr.REASON_INSUFFICIENT_ECONOMIC != wr.REASON_INSUFFICIENT_ELIGIBLE
    # 1 个 eligible（capability 不足）→ INSUFFICIENT_ELIGIBLE
    rec_elig = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy",
        _registry(_entry(model="solo")),
        facts={"solo": _fresh_free_fact("solo")},
        now=NOW, risk_source="t",
    )
    assert rec_elig["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    # 2 个 eligible 但 1 个可信（经济不足）→ INSUFFICIENT_ECONOMIC
    rec_econ = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy",
        _registry(_entry(model="cand-a"), _entry(model="cand-b")),
        facts={"cand-a": _fresh_free_fact("cand-a"), "cand-b": _unknown_fact("cand-b")},
        now=NOW, risk_source="t",
    )
    assert rec_econ["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    # 不误导为 capability 不足：reason 不得使用 INSUFFICIENT_ELIGIBLE token，
    # 且明确说明「可信候选不足两个」（compare candidates 语义）
    assert wr.REASON_INSUFFICIENT_ELIGIBLE not in rec_econ["reason"]
    assert "fewer than two" in rec_econ["reason"]


# ---------------------------------------------------------------------------
# 不 hard-code 候选（Req 8）：决策只由 registry/facts 输入驱动
# ---------------------------------------------------------------------------


def test_no_hardcoded_models():
    """generic 候选（任意 id）同样服从 gate 语义：2 可信 → 路由；1 可信 → Auto。
    决策不引用任何具体 model id 常量。"""
    reg = _registry(_entry(model="zeta"), _entry(model="alpha"))
    facts = {
        "zeta": _fresh_free_fact("zeta"),
        "alpha": _fresh_discount_fact("alpha", multiplier=0.2),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "zeta"  # rank 0 outranks rank 1（与 id 无关）
    # 只换 facts：zeta 变不可信 → 1 可信 → Auto
    facts2 = {"zeta": _unknown_fact("zeta"), "alpha": _fresh_discount_fact("alpha", multiplier=0.2)}
    rec2 = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts2,
        now=NOW, risk_source="t",
    )
    assert rec2["routing_applied"] is False
    assert rec2["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)


# ---------------------------------------------------------------------------
# active artifact 准确性（Req 11）：Auto 场景也如实记录候选集合与 no-route reason
# ---------------------------------------------------------------------------


def test_artifact_accuracy_auto_case(tmp_path):
    """Auto（1 可信候选）artifact 必须准确反映：eligible / economically_trustworthy /
    routing_applied=false / routed_model=None / no-route reason / fallback_used=false。"""
    reg = _registry(_entry(model="cand-a"), _entry(model="cand-b"))
    facts = {"cand-a": _fresh_free_fact("cand-a"), "cand-b": _unknown_fact("cand-b")}
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["eligible"] == ["cand-a", "cand-b"]
    assert rec["economically_trustworthy"] == ["cand-a"]
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["fallback_used"] is False
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    path = wr.save_workbuddy_routing(tmp_path, rec)
    loaded = wr.load_workbuddy_routing(tmp_path)
    assert loaded is not None
    assert path.name == wr.ARTIFACT_FILENAME
    assert loaded["routing_applied"] is False
    assert loaded["routed_model"] is None
    assert loaded["economically_trustworthy"] == ["cand-a"]
    assert loaded["reason"] == rec["reason"]
    assert loaded["fallback_used"] is False
    assert loaded["authoritative"] is True


def test_capability_gate_precedes_economics_no_regression():
    """Req 5 不变：ineligible（capability/qualification 不满足）候选即使经济
    FRESH 免费也绝不进入经济选择；经济成本不能绕过 capability gate。"""
    reg = _registry(
        _entry(model="ok-a"),
        _entry(model="ok-b"),
        _entry(model="ineligible-free", capability_tier=None),
    )
    facts = {
        "ok-a": _fresh_free_fact("ok-a"),
        "ok-b": _fresh_free_fact("ok-b"),
        "ineligible-free": _fresh_free_fact("ineligible-free"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["ok-a", "ok-b"]
    assert "ineligible-free" not in rec["economic_facts"]  # 经济学根本没消费它
    assert rec["routing_applied"] is True
    assert rec["selected"] == "ok-a"
