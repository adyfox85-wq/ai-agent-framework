"""AAF v0.5 A4 — WorkBuddy active economic routing 聚焦测试
（TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001，A4 first slice）。

覆盖 Requirement 15 测试矩阵 + 审计/隔离守卫（FIX-001 起两候选 gate 作用于
全部过滤之后）：
- explicit LOW + 两个 qualified + **两个** fresh trustworthy economics → routing
  applied，选中经济 winner（hy4-preview），真实 argv 含恰好一个 --model <winner>
- FIX-001：两个 eligible 但经济过滤后只剩 1 个 trustworthy candidate（真实
  baseline facts）→ routing_applied=false（INSUFFICIENT_ECONOMIC_CANDIDATES）
  → Auto（不伪造第二可信候选）
- selected = 经济 winner（不是 selector 默认的 deepseek-v4-flash）
- missing Risk / HIGH / CRITICAL → Auto（CodeBuddy Auto 保持）；MEDIUM 在
  explicit LOW + MEDIUM active-slice 内（002）——真实 registry 下仍 Auto
  （MEDIUM selector floor = T3，真实 WorkBuddy 候选 T4 不满足 → 0 eligible）
- 只有一个 eligible candidate → Auto
- stale / unknown / contradictory economics → Auto（fail closed）
- capability-insufficient / qualification-unknown 候选在经济选择前被排除
- 经济成本不能绕过 capability/qualification
- 无 --effort / 无 fallback / 无 retry escalation
- 确定性选择与输入顺序无关（含经济平局 tie-break）
- active artifact authority 语义正确（authoritative=true；Auto 时不声称路由）
- env 覆盖精确 apply / restore（绝不泄漏到后续 stage / 调用方）
- runner 集成：LOW 全链 workbuddy_active_routing.json routing_applied=true、
  AAF_WORKBUDDY_MODEL 在 workbuddy invocation 时可见且事后还原；HIGH → false

边界（Boundaries，002）：无 HIGH/CRITICAL active routing、无 effort routing、无
automatic fallback、无 Cost Gate UX、无 health polling/quarantine、无 runtime
requalification loop、无 Hermes（A3）/Codex 路由变更、无 A5/A6。
"""
import json
import os

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

# 参考时间（2026-09-02：hy4-preview 免费窗口 08-28..09-11 内 → FRESH；
# deepseek-v4-flash 无日期窗口 → freshness UNKNOWN）。
NOW = __import__("datetime").datetime.fromisoformat("2026-09-02T03:30:00+08:00")

QUALIFIED_WORKBUDDY_IDS = ("deepseek-v4-flash", "hy4-preview")
ECONOMIC_WINNER = "hy4-preview"  # RANK_AUTHORITATIVE_CHEAP（FRESH + 显式免费）
SELECTOR_DEFAULT = "deepseek-v4-flash"  # selector 默认（cost/locality 同 rank，key tie-break）

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
        source="test",
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


def _two_trustworthy_facts() -> dict[str, we.EconomicFact]:
    """FIX-001 受控 fixture：两个 eligible 候选**都有** trustworthy economics。

    - deepseek-v4-flash → FRESH discount（rank 1，multiplier 0.17，
      economic_fields_consistent=True）；
    - hy4-preview → FRESH free（rank 0，权威免费）。
    经济 winner = hy4-preview（rank 0 outranks rank 1）。只用于受控场景，
    与真实 baseline facts（deepseek-v4-flash freshness UNKNOWN）明确区分。
    """
    return {
        "deepseek-v4-flash": _fresh_discount_fact("deepseek-v4-flash", multiplier=0.17),
        "hy4-preview": _fresh_free_fact("hy4-preview", valid_until="2026-09-11T00:00:00+08:00"),
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
# 1. FIX-001：两候选 gate 作用于全部过滤之后（capability + qualification +
#    trustworthy economics）。真实 baseline facts 只有 1 个可信候选 → Auto。
# ---------------------------------------------------------------------------


def test_low_two_eligible_one_trustworthy_economics_auto():
    """baseline registry + baseline facts：LOW validator/workbuddy → 两个 eligible
    （deepseek-v4-flash + hy4-preview）；但经济过滤后只剩 hy4-preview 一个
    trustworthy candidate（deepseek-v4-flash freshness UNKNOWN 被经济排除）→
    routing_applied=false（INSUFFICIENT_ECONOMIC_CANDIDATES），CodeBuddy Auto
    保持（Requirement 5 FIX-001：当前真实 facts 不被人为伪造成可路由）。"""
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["eligible"] == list(QUALIFIED_WORKBUDDY_IDS)
    assert rec["economically_trustworthy"] == [ECONOMIC_WINNER]
    assert rec["economically_excluded"] == [
        {"candidate": "deepseek-v4-flash", "reason": wr.ECON_FRESHNESS_UNKNOWN}
    ]
    assert rec["fallback_used"] is False
    assert rec["risk_class"] == RISK_LOW
    assert rec["risk_source"] == so.TASK_RISK_SOURCE
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ECONOMIC)
    assert "CodeBuddy Auto" in rec["invocation"]
    # 经济事实已记录（auditable：facts used）
    assert "hy4-preview" in rec["economic_facts"]
    assert rec["economic_facts"]["hy4-preview"]["cheapness_rank"] == we.RANK_AUTHORITATIVE_CHEAP
    assert rec["economic_facts"]["hy4-preview"]["freshness"] == we.ECON_FRESH
    wr.validate_workbuddy_routing(rec)


def test_selected_is_economic_winner_not_selector_default():
    """selector 默认选中 deepseek-v4-flash（key tie-break）；受控两可信候选
    （FIX-001 fixture）下 active routing 的 selected 必须是经济 winner
    （hy4-preview，rank 0 权威免费 outranks rank 1 折扣）——经济选择只作用于
    eligible 候选，是确定性且非 selector 默认的（Requirement 7/8）。"""
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    assert rec["selector_selected"] == SELECTOR_DEFAULT
    assert rec["selected"] == ECONOMIC_WINNER
    assert rec["routed_model"] == ECONOMIC_WINNER
    assert rec["economically_trustworthy"] == [ECONOMIC_WINNER, "deepseek-v4-flash"]
    assert rec["selected"] != rec["selector_selected"]


def test_authoritative_free_outranks_discount():
    """rank 0（权威免费）outranks rank 1（FRESH discount），即使 discount 的
    multiplier 更低（Requirement 7：authoritative free outranks non-free）。"""
    reg = _registry(
        _entry(model="free-model"), _entry(model="disc-model"),
    )
    facts = {
        "free-model": _fresh_free_fact("free-model"),
        "disc-model": _fresh_discount_fact("disc-model", multiplier=0.01),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "free-model"


def test_fresh_discount_lower_multiplier_wins():
    """rank 1（FRESH discount）内：更低 trusted multiplier 获胜（Requirement 7）。"""
    reg = _registry(
        _entry(model="disc-hi"), _entry(model="disc-lo"),
    )
    facts = {
        "disc-hi": _fresh_discount_fact("disc-hi", multiplier=0.8),
        "disc-lo": _fresh_discount_fact("disc-lo", multiplier=0.2),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "disc-lo"


def test_economic_tie_deterministic_model_id_tiebreak():
    """经济完全相等（同 rank、同 multiplier）→ model_id 字典序确定性 tie-break；
    且与候选输入顺序无关（Requirement 7/15）。"""
    reg = _registry(
        _entry(model="free-b"), _entry(model="free-a"),
    )
    facts = {
        "free-a": _fresh_free_fact("free-a", valid_until="2026-12-01T00:00:00+08:00"),
        "free-b": _fresh_free_fact("free-b", valid_until="2026-12-01T00:00:00+08:00"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "free-a"  # 字典序 tie-break（输入顺序无关）
    # 反转 registry 插入顺序 → 同一决策
    reg_rev = _registry(
        _entry(model="free-a"), _entry(model="free-b"),
    )
    rec_rev = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg_rev, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec_rev["selected"] == rec["selected"]
    assert rec_rev["routing_applied"] == rec["routing_applied"]


# ---------------------------------------------------------------------------
# 2. 真实 argv：恰好一个 --model <winner>（Requirement 9/10/15）
# ---------------------------------------------------------------------------


def test_invocation_args_contain_exactly_one_model_for_winner(monkeypatch):
    fake_exe = "C:/fake-bin/codebuddy.exe"
    monkeypatch.setattr(adapters, "_require", lambda cmd: fake_exe)
    args, stdin_data, env_out = adapters._workbuddy_invocation(
        "PROMPT", {}, model=ECONOMIC_WINNER
    )
    assert args == [fake_exe, *AUTO_ARGS_TAIL, "--model", ECONOMIC_WINNER]
    assert args.count("--model") == 1
    assert "--effort" not in args
    assert "-m" not in args
    assert stdin_data == "PROMPT"


def test_invocation_without_model_stays_auto(monkeypatch):
    fake_exe = "C:/fake-bin/codebuddy.exe"
    monkeypatch.setattr(adapters, "_require", lambda cmd: fake_exe)
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", {})
    assert args == [fake_exe, *AUTO_ARGS_TAIL]
    assert "--model" not in args
    assert "--effort" not in args


def test_run_agent_workbuddy_reads_env_model_override(monkeypatch, tmp_path):
    """A4 env 覆盖 → run_agent 把 --model <value> 追加到真实 invocation。"""
    captured = {}

    def fake_retry(args, env, stdin_data, workspace):
        captured["args"] = list(args)
        captured["stdin"] = stdin_data
        return "ok", {"attempt_count": 1, "retried": False, "outcome": "SUCCESS"}

    monkeypatch.setattr(adapters, "_require", lambda cmd: "C:/fake/codebuddy.exe")
    monkeypatch.setattr(adapters, "run_workbuddy_with_retry", fake_retry)
    monkeypatch.setenv(wr.ENV_WORKBUDDY_MODEL, ECONOMIC_WINNER)
    adapters.run_agent("workbuddy", "PROMPT", tmp_path)
    assert captured["args"] == ["C:/fake/codebuddy.exe", *AUTO_ARGS_TAIL, "--model", ECONOMIC_WINNER]
    assert captured["args"].count("--model") == 1
    assert "--effort" not in captured["args"]
    assert captured["stdin"] == "PROMPT"


def test_run_agent_workbuddy_no_env_no_model(monkeypatch, tmp_path):
    """无 AAF_WORKBUDDY_MODEL 覆盖 → invocation 保持 CodeBuddy Auto。"""
    captured = {}

    def fake_retry(args, env, stdin_data, workspace):
        captured["args"] = list(args)
        return "ok", {"attempt_count": 1, "retried": False, "outcome": "SUCCESS"}

    monkeypatch.setattr(adapters, "_require", lambda cmd: "C:/fake/codebuddy.exe")
    monkeypatch.setattr(adapters, "run_workbuddy_with_retry", fake_retry)
    monkeypatch.delenv(wr.ENV_WORKBUDDY_MODEL, raising=False)
    adapters.run_agent("workbuddy", "PROMPT", tmp_path)
    assert captured["args"] == ["C:/fake/codebuddy.exe", *AUTO_ARGS_TAIL]
    assert "--model" not in captured["args"]


# ---------------------------------------------------------------------------
# 3. missing / HIGH / CRITICAL → Auto（Requirement 11/15；002：risk 域 =
#    explicit LOW + MEDIUM，HIGH/CRITICAL 在 active slice 之外）
# ---------------------------------------------------------------------------


def test_missing_risk_auto():
    rec = wr.decide_workbuddy_route(
        None, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(), now=NOW
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["risk_source"] == wr.RISK_UNAVAILABLE
    assert rec["reason"].startswith(wr.REASON_RISK_UNAVAILABLE)
    assert "CodeBuddy Auto" in rec["invocation"]
    wr.validate_workbuddy_routing(rec)


@pytest.mark.parametrize("risk", [RISK_HIGH, RISK_CRITICAL])
def test_outside_slice_risk_auto(risk):
    """HIGH / CRITICAL 在 active slice（LOW+MEDIUM）之外 → Auto。"""
    rec = wr.decide_workbuddy_route(
        risk, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_RISK_OUTSIDE_SLICE)


def test_medium_real_registry_auto_via_capability_floor():
    """MEDIUM 在 active slice 内，但真实 registry 下仍 Auto：MEDIUM 复用既有
    selector capability floor（risk_contract RISK_FLOORS[MEDIUM].validator =
    T3），真实 WorkBuddy 候选（deepseek-v4-flash / hy4-preview）capability_tier
    = T4 不满足 T3 floor → 0 eligible → INSUFFICIENT_ELIGIBLE_CANDIDATES →
    Auto。**当前真实数据不被人为放宽/伪造**（Requirement 5/15：不硬编码候选
    eligibility、不为凑 MEDIUM 路由而放宽能力下限）。"""
    rec = wr.decide_workbuddy_route(
        RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["eligible"] == []
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    assert "CodeBuddy Auto" in rec["invocation"]
    wr.validate_workbuddy_routing(rec)


# ---------------------------------------------------------------------------
# 4. 一个 eligible candidate only → Auto（Requirement 5/15）
# ---------------------------------------------------------------------------


def test_one_eligible_candidate_auto():
    reg = _registry(
        _entry(model="solo"),
    )
    facts = {"solo": _fresh_free_fact("solo")}
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    assert rec["eligible"] == ["solo"]
    assert "fewer than two" in rec["reason"]


# ---------------------------------------------------------------------------
# 5. stale / unknown / contradictory economics → Auto（Requirement 6/11/15）
# ---------------------------------------------------------------------------


def test_stale_economics_auto():
    """hy4-preview 免费窗口已过期（STALE）+ deepseek-v4-flash freshness UNKNOWN →
    无可信经济事实 → NO_TRUSTWORTHY_ECONOMIC_WINNER → Auto。"""
    stale_now = __import__("datetime").datetime.fromisoformat("2026-12-01T00:00:00+08:00")
    facts = {
        "hy4-preview": _fresh_free_fact(
            "hy4-preview", valid_until="2026-09-11T00:00:00+08:00"
        ),
        "deepseek-v4-flash": _unknown_fact("deepseek-v4-flash"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=facts, now=stale_now, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)
    excluded = {e["candidate"]: e["reason"] for e in rec["economically_excluded"]}
    assert excluded["hy4-preview"] == wr.ECON_STALE
    assert excluded["deepseek-v4-flash"] == wr.ECON_FRESHNESS_UNKNOWN


def test_unknown_economics_auto():
    """全部 eligible 候选 freshness UNKNOWN → 无可信经济事实 → Auto。"""
    facts = {
        "hy4-preview": _unknown_fact("hy4-preview"),
        "deepseek-v4-flash": _unknown_fact("deepseek-v4-flash"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=facts, now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)
    assert {e["candidate"] for e in rec["economically_excluded"]} == set(QUALIFIED_WORKBUDDY_IDS)


def test_contradictory_economics_never_enters_ordering():
    """免费促销带非零 factor（内部矛盾，economic_fields_consistent=False）→
    rank 2 → fail closed，绝不进入经济排序（FIX-001 gate 原样消费）。受控场景：
    另有两个可信候选（free-ok rank 0 + disc-ok rank 1）→ 满足两候选 gate，
    winner 必须是完整一致的 free-ok，矛盾候选被排除且永不获胜。"""
    reg = _registry(
        _entry(model="free-ok"), _entry(model="free-broken"), _entry(model="disc-ok"),
    )
    facts = {
        "free-ok": _fresh_free_fact("free-ok"),
        # free 状态但 factor 0.5 → 与 free 矛盾（免费促销带非零 factor）
        "free-broken": _fact(
            model_id="free-broken", multiplier=0.0, multiplier_raw="x0.00",
            promotion_status="free", promotion_factor=0.5,
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
        "disc-ok": _fresh_discount_fact("disc-ok", multiplier=0.5),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "free-ok"  # 只有完整一致的事实进入经济排序
    assert rec["economically_trustworthy"] == ["free-ok", "disc-ok"]
    excluded = {e["candidate"]: e["reason"] for e in rec["economically_excluded"]}
    assert excluded["free-broken"] == wr.ECON_INCONSISTENT


def test_all_contradictory_economics_auto():
    """全部 eligible 候选经济事实矛盾 → 无可信 winner → Auto。"""
    reg = _registry(
        _entry(model="broken-a"), _entry(model="broken-b"),
    )
    facts = {
        "broken-a": _fact(
            model_id="broken-a", multiplier=0.0, multiplier_raw="x0.00",
            promotion_status="free", promotion_factor=0.5,
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
        "broken-b": _fact(
            model_id="broken-b", multiplier=0.5, multiplier_raw="x0.5",
            promotion_status="discount", promotion_factor=0.0,  # factor 0 = free，与 discount 矛盾
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)


def test_eligible_candidate_missing_fact_auto():
    """eligible 候选无经济事实条目 → ECON_FACT_MISSING → 不参与经济排序；
    全部缺失 → Auto。"""
    reg = _registry(
        _entry(model="no-fact-a"), _entry(model="no-fact-b"),
    )
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts={},
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)
    assert {e["candidate"] for e in rec["economically_excluded"]} == {"no-fact-a", "no-fact-b"}
    assert {e["reason"] for e in rec["economically_excluded"]} == {wr.ECON_FACT_MISSING}


# ---------------------------------------------------------------------------
# 6. capability / qualification 先于经济学（Requirement 3/4/15）
# ---------------------------------------------------------------------------


def test_capability_insufficient_excluded_before_economics():
    """FRESH 免费但 capability 不足的候选（如 hy3：tier=None）绝不进入经济选择，
    即使经济 rank 0（Requirement 4：economic cost cannot bypass capability）。"""
    reg = _registry(
        _entry(model="hy3", capability_tier=None),
        _entry(model="ok-model"),
    )
    facts = {
        "hy3": _fresh_free_fact("hy3"),  # rank 0，但 ineligible
        "ok-model": _fresh_discount_fact("ok-model", multiplier=0.5),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["ok-model"]
    assert rec["routing_applied"] is False  # 只剩 1 个 eligible → 不足两个
    assert rec["reason"].startswith(wr.REASON_INSUFFICIENT_ELIGIBLE)
    excluded = {e["candidate"]: e["reason"] for e in rec["excluded"]}
    assert excluded["hy3"] == "CAPABILITY_INSUFFICIENT"
    assert "hy3" not in rec["economic_facts"]  # 经济学根本没消费它


def test_qualification_unknown_excluded_before_economics():
    """qualification=unknown 的候选即使 FRESH 免费也不 eligible；经济事实绝不
    赋予资格（Requirement 4/15）。"""
    reg = _registry(
        _entry(model="unknown-qual", qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_UNKNOWN)),
        _entry(model="ok-model"),
    )
    facts = {
        "unknown-qual": _fresh_free_fact("unknown-qual"),
        "ok-model": _fresh_discount_fact("ok-model", multiplier=0.5),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["ok-model"]
    assert rec["routing_applied"] is False
    excluded = {e["candidate"]: e["reason"] for e in rec["excluded"]}
    assert excluded["unknown-qual"] == "QUALIFICATION_UNKNOWN"


def test_economic_cost_cannot_bypass_capability_qualification():
    """经济成本不能使 ineligible 候选获胜：两个 eligible 候选经济 rank 2（全价），
    ineligible 候选 FRESH 免费 → 绝不选 ineligible；eligible 无可信经济 → Auto。"""
    reg = _registry(
        _entry(model="eligible-paid-a"),
        _entry(model="eligible-paid-b"),
        _entry(model="ineligible-free", capability_tier=None),
    )
    facts = {
        "eligible-paid-a": _fact(  # FRESH 全价（无促销）→ rank 2（无已知便宜 rank）
            model_id="eligible-paid-a", multiplier=0.9, multiplier_raw="x0.9",
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
        "eligible-paid-b": _fact(
            model_id="eligible-paid-b", multiplier=0.5, multiplier_raw="x0.5",
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        ),
        "ineligible-free": _fresh_free_fact("ineligible-free"),
    }
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", reg, facts=facts,
        now=NOW, risk_source="t",
    )
    assert rec["eligible"] == ["eligible-paid-a", "eligible-paid-b"]
    assert rec["routing_applied"] is False
    assert rec["selected"] is None  # 绝不选 ineligible-free
    assert rec["reason"].startswith(wr.REASON_NO_TRUSTWORTHY_WINNER)
    assert rec["economically_excluded"] == [
        {"candidate": "eligible-paid-a", "reason": wr.ECON_INCONSISTENT},
        {"candidate": "eligible-paid-b", "reason": wr.ECON_INCONSISTENT},
    ]
    excluded = {e["candidate"]: e["reason"] for e in rec["excluded"]}
    assert excluded["ineligible-free"] == "CAPABILITY_INSUFFICIENT"
    assert "ineligible-free" not in rec["economic_facts"]  # 经济学根本没消费它


# ---------------------------------------------------------------------------
# 7. 无 --effort / 无 fallback / 无 retry escalation（Requirement 10/12/15）
# ---------------------------------------------------------------------------


def test_no_effort_anywhere(monkeypatch):
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    assert "no --effort" in rec["invocation"]
    fake_exe = "C:/fake-bin/codebuddy.exe"
    monkeypatch.setattr(adapters, "_require", lambda cmd: fake_exe)
    args, _, _ = adapters._workbuddy_invocation("P", {}, model=rec["routed_model"])
    assert "--effort" not in args
    assert args.count("--model") == 1


def test_no_fallback_semantics():
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    assert rec["fallback_used"] is False
    # validate fail closed：任何 fallback_used=True 都是违规
    bad = dict(rec)
    bad["fallback_used"] = True
    with pytest.raises(ValueError):
        wr.validate_workbuddy_routing(bad)
    # routing_applied=True 但 routed_model 空 → 违规（不得声明生效却无模型）
    bad2 = dict(rec)
    bad2["routed_model"] = None
    with pytest.raises(ValueError):
        wr.validate_workbuddy_routing(bad2)
    # routing_applied=True 但 selected != routed_model → 违规
    bad3 = dict(rec)
    bad3["selected"] = "deepseek-v4-flash"
    with pytest.raises(ValueError):
        wr.validate_workbuddy_routing(bad3)


# ---------------------------------------------------------------------------
# 8. active artifact authority 语义（Requirement 13/14/15）
# ---------------------------------------------------------------------------


def test_artifact_authority_semantics(tmp_path):
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["authoritative"] is True
    assert rec["decision_kind"] == wr.DECISION_KIND
    assert rec["stage_agent"] == "workbuddy"
    assert rec["role"] == ROLE_VALIDATOR
    # artifact 必含审计字段（Requirement 13）
    for key in (
        "stage_agent", "role", "risk_class", "risk_source", "candidates_considered",
        "eligible", "economic_facts", "selected", "routing_applied", "routed_model",
        "fallback_used", "reason", "invocation", "freshness_reference_time",
    ):
        assert key in rec
    path = wr.save_workbuddy_routing(tmp_path, rec)
    assert path.name == wr.ARTIFACT_FILENAME
    loaded = wr.load_workbuddy_routing(tmp_path)
    assert loaded is not None
    assert loaded["routing_applied"] is True
    assert loaded["selected"] == ECONOMIC_WINNER
    assert loaded["authoritative"] is True
    assert loaded["fallback_used"] is False


def test_artifact_does_not_claim_routing_when_auto(tmp_path):
    """Requirement 14：Auto 保持时 artifact 不得声称模型路由（routed_model 必须
    None）；validate fail closed 拒绝「未路由却填了 routed_model」的记录。"""
    rec = wr.decide_workbuddy_route(
        RISK_HIGH, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert "CodeBuddy Auto" in rec["invocation"]
    wr.validate_workbuddy_routing(rec)
    bad = dict(rec)
    bad["routed_model"] = "hy4-preview"
    with pytest.raises(ValueError):
        wr.validate_workbuddy_routing(bad)
    bad2 = dict(rec)
    bad2["authoritative"] = False
    with pytest.raises(ValueError):
        wr.validate_workbuddy_routing(bad2)


def test_artifact_freshness_reference_time_recorded():
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["freshness_reference_time"] == NOW.isoformat(timespec="seconds")
    assert "economic_facts_source" in rec
    assert "WORKBUDDY-ECONOMICS-001" in rec["economic_facts_source"]


# ---------------------------------------------------------------------------
# 9. env 覆盖精确 apply / restore
# ---------------------------------------------------------------------------


def test_env_apply_restore(monkeypatch):
    monkeypatch.delenv(wr.ENV_WORKBUDDY_MODEL, raising=False)
    rec = wr.decide_workbuddy_route(
        RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        facts=_two_trustworthy_facts(),
        now=NOW, risk_source=so.TASK_RISK_SOURCE,
    )
    assert rec["routing_applied"] is True
    saved = wr.apply_workbuddy_model_env(rec)
    assert os.environ.get(wr.ENV_WORKBUDDY_MODEL) == ECONOMIC_WINNER
    assert wr.ENV_WORKBUDDY_MODEL in saved
    assert saved[wr.ENV_WORKBUDDY_MODEL] is None  # 调用前不存在
    wr.restore_workbuddy_model_env(saved)
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ  # 已还原删除

    # 旧值存在 → restore 还原旧值
    monkeypatch.setenv(wr.ENV_WORKBUDDY_MODEL, "old-value")
    saved2 = wr.apply_workbuddy_model_env(rec)
    assert os.environ.get(wr.ENV_WORKBUDDY_MODEL) == ECONOMIC_WINNER
    wr.restore_workbuddy_model_env(saved2)
    assert os.environ.get(wr.ENV_WORKBUDDY_MODEL) == "old-value"


def test_env_apply_requires_applied_record():
    rec = wr.decide_workbuddy_route(
        RISK_HIGH, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
        now=NOW, risk_source="t",
    )
    assert rec["routing_applied"] is False
    with pytest.raises(ValueError):
        wr.apply_workbuddy_model_env(rec)  # 未生效的决策不得触碰 env


def test_naive_now_rejected():
    from datetime import datetime

    with pytest.raises(ValueError):
        wr.decide_workbuddy_route(
            RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
            now=datetime(2026, 9, 2), risk_source="t",
        )


def test_unknown_role_rejected():
    with pytest.raises(ValueError):
        wr.decide_workbuddy_route(
            RISK_LOW, "bogus", "workbuddy", mr.baseline_registry(),
            now=NOW, risk_source="t",
        )


# ---------------------------------------------------------------------------
# 10. runner 集成（真实 runner + fake run_agent；fixed now 保证时间稳定）
# ---------------------------------------------------------------------------


def _task_text(risk):
    body = """AAF_TASK_BEGIN
# Task ID
AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-TEST

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


def _run_runner(tmp_path, monkeypatch, task_text, fake_run_agent=None, facts=None):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    if fake_run_agent is None:
        fake_run_agent = lambda agent, prompt, workspace: _structured_ok(agent)  # noqa: E731
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    # 固定 freshness 参考时间（runner 默认用真实 wall clock；测试用固定时间保证
    # 决策在 hy4-preview 免费窗口内稳定——真实 wall-clock 行为由 fresh-runner 证明）
    real_decide = wr.decide_workbuddy_route

    def fixed_decide(risk_class, role, stage_agent, registry, **kw):
        kw.pop("now", None)  # runner 传真实 wall clock；测试固定参考时间
        if facts is not None:
            # FIX-001 受控 fixture 注入（仅测试；生产 runner 始终 facts=None =
            # baseline_economic_facts()，本 wrapper 只在 LOW 场景注入）
            kw["facts"] = facts
        return real_decide(risk_class, role, stage_agent, registry, now=NOW, **kw)

    monkeypatch.setattr(runner_mod.workbuddy_routing_mod, "decide_workbuddy_route", fixed_decide)
    runner_mod.run(task_file, ws, out)
    return out


def test_runner_low_writes_workbuddy_routing_artifact_and_env(tmp_path, monkeypatch):
    """LOW 全链（受控两可信候选 fixture）：workbuddy_active_routing.json
    routing_applied=true（hy4-preview）；AAF_WORKBUDDY_MODEL 在 workbuddy
    invocation 时可见；执行后已还原；stage result 携带
    workbuddy_active_routing_ref；全链 SUCCESS。"""
    seen = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "workbuddy":
            seen["wb_model"] = os.environ.get(wr.ENV_WORKBUDDY_MODEL)
        return _structured_ok(agent)

    out = _run_runner(
        tmp_path, monkeypatch, _task_text(RISK_LOW),
        fake_run_agent, facts=_two_trustworthy_facts(),
    )
    # invocation 时 env 覆盖可见
    assert seen["wb_model"] == ECONOMIC_WINNER
    # 执行完成后 env 已还原（不泄漏）
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ
    # authoritative artifact
    rec = wr.load_workbuddy_routing(out)
    assert rec is not None
    assert rec["routing_applied"] is True
    assert rec["authoritative"] is True
    assert rec["selected"] == ECONOMIC_WINNER
    assert rec["routed_model"] == ECONOMIC_WINNER
    assert rec["fallback_used"] is False
    # stage result 引用
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage.get("workbuddy_active_routing_ref", {}).get("entry") == "workbuddy"
    # 全链 SUCCESS
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    # A3 Hermes artifact 仍独立存在（互不覆盖）
    assert (out / "active_routing.json").exists()


def test_runner_high_preserves_auto(tmp_path, monkeypatch):
    """HIGH 全链：workbuddy_active_routing.json routing_applied=false、routed_model
    None（不得声称路由）；env 从未被触碰；全链 SUCCESS。"""
    seen = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "workbuddy":
            seen["wb_model"] = os.environ.get(wr.ENV_WORKBUDDY_MODEL)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task_text(RISK_HIGH), fake_run_agent)
    assert seen["wb_model"] is None
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ
    rec = wr.load_workbuddy_routing(out)
    assert rec is not None
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(wr.REASON_RISK_OUTSIDE_SLICE)
    assert "CodeBuddy Auto" in rec["invocation"]
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_missing_risk_auto(tmp_path, monkeypatch):
    out = _run_runner(tmp_path, monkeypatch, _task_text(None))
    rec = wr.load_workbuddy_routing(out)
    assert rec is not None
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(wr.REASON_RISK_UNAVAILABLE)
    assert wr.ENV_WORKBUDDY_MODEL not in os.environ
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
