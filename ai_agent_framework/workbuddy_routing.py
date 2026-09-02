"""AAF v0.5 A4 — Active economic routing for the WorkBuddy validator stage
（A4 active-routing slices，TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001
[LOW] + AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 [MEDIUM]）。

目标：仅当 WorkBuddy validator stage 的 TASK 显式声明 Risk: LOW 或 MEDIUM
（002 把 active-routing risk 域从 explicit LOW 扩展到 explicit LOW + MEDIUM），
且现有 selector 选出**至少两个** eligible（capability + qualification）
WorkBuddy candidate，且经济事实层对 eligible 候选提供 **FRESH、完整、一致、
可审计**的经济事实，且经济过滤后仍**至少两个可信候选**（FIX-001：
economically_trustworthy >= 2 —— 两候选 gate 作用于 capability +
qualification + trustworthy economics 全部过滤之后）时，把该 decision 升级为
**真实** per-run ``--model`` 选择（routing_applied=true → 生产 WorkBuddy
invocation 精确追加 ``--model <selected_model_id>``，其余参数零变化）。任何
权威条件不满足 → routing_applied=false，保持 CodeBuddy Auto
（[-p --output-format text -y]）。

复用纪律（Requirement 1，不创建第二套独立 eligibility 系统）：
- 候选筛选 = 现有 ``shadow_routing.select_shadow_candidate``（A2 引擎原样调用，
  role=validator；能力充分性 → qualification 顺序原样保持，Requirement 3）。
- Risk 词汇 = ``risk_contract.RISK_CLASSES``（唯一 authority；缺失 =
  RISK_UNAVAILABLE，missing ≠ LOW）。
- Registry = ``model_registry.baseline_registry()``（A1 有证据基线）。
- 经济事实 = ``workbuddy_economics`` 事实层（A4 prerequisite 建立）：
  ``cheapness_rank`` / ``classify_freshness`` / ``EconomicFact`` 原样消费；
  本模块是经济事实层的**第一个**（也是唯一）路由消费方。

Activation gates（Requirement 2/4/5/11，全部满足才 routing_applied=true）：
- stage_agent == "workbuddy" 且 role == "validator"
- 显式 Risk ∈ {LOW, MEDIUM}（002：risk 域 = explicit LOW + MEDIUM；
  None / HIGH / CRITICAL → 不生效）
- selector eligible candidates >= 2（capability + qualification gate；
  少于两个 → INSUFFICIENT_ELIGIBLE_CANDIDATES，保持 Auto）
- 经济选择只消费 FRESH + 完整 + 一致 + 可审计的事实（Requirement 6）：
  eligible 候选中 cheapness_rank ∈ {RANK_AUTHORITATIVE_CHEAP(0),
  RANK_FRESH_DISCOUNT(1)} 的候选进入经济排序；STALE / UNKNOWN /
  字段缺失或矛盾 / 无已知便宜 rank（rank 2）→ 永不获胜（fail closed）。
- **最小候选数 gate 作用于全部过滤之后**（FIX-001，Codex Requirement 5
  blocker 收口）：capability + qualification + trustworthy economics 全部门槛
  完成后仍须 **economically_trustworthy >= 2** 才允许 economic winner
  selection；经济门槛后只剩 1 个可信候选（或 0 个）→ 不路由
  （1 个 → INSUFFICIENT_ECONOMIC_CANDIDATES；0 个 →
  NO_TRUSTWORTHY_ECONOMIC_WINNER），保持 CodeBuddy Auto。
- 存在确定性可信经济 winner（全部 rank 2 → NO_TRUSTWORTHY_ECONOMIC_WINNER
  → Auto；Requirement 11）。

Selection policy（Requirement 7，确定性，输入顺序无关）：
- 排序键 = (cheapness_rank, multiplier, model_id)：
  - 权威免费（rank 0）outranks 非免费（rank 1）；
  - rank 1 内更低 multiplier 获胜（\"lower trusted multiplier\"）；
  - 经济完全相等（同 rank、同 multiplier）→ model_id 字典序确定性 tie-break
    （与 A2 shadow engine 的 key tie-break 同一惯例；输入顺序无关）。
- 经济性**永不**使 ineligible 候选 eligible（Requirement 4/15）：经济选择
  只作用于 selector 已 eligible 的候选；hy3（FRESH 免费但 tier=None +
  qualification=unknown）绝不被选中。

No silent fallback（Requirement 12）：本模块不存在 fallback 分支；
``fallback_used`` 恒为 False（fixed semantic，validate fail-closed）。
routing_applied 后真实 invocation 失败 → runner 如实 FRAMEWORK_ERROR
（链中断 → WAITING）；transport 层既有 bounded retry（workbuddy_retry）复用
**同一次 invocation**（同一 args，含 --model），绝不换模型 / 不退回 Auto /
不升级付费层级（Requirement 10：无 retry escalation）。

范围边界（Boundaries，002）：不实现 HIGH/CRITICAL active model routing
（HIGH/CRITICAL 保持 CodeBuddy Auto）、effort routing、automatic fallback、
Cost Gate UX、health polling / quarantine、runtime requalification loop、
Hermes 路由变更（A3 原样）、Codex 路由变更、A5/A6、本 slice 之外的
multi-agent routing。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from . import model_registry as model_registry_mod
from . import workbuddy_economics as we
from .risk_contract import RISK_CLASSES, RISK_LOW, RISK_MEDIUM, ROLE_VALIDATOR
from .shadow_routing import STAGE_ROLES, select_shadow_candidate

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
# 与 A3 Hermes 的 active_routing.json 明确分开：WorkBuddy stage 与 Hermes
# stage 写同一 output_dir，filename 必须不冲突；且本 artifact 与
# shadow_observation.json（hypothetical, authoritative=false）语义明确区分。
ARTIFACT_FILENAME = "workbuddy_active_routing.json"

STAGE_AGENT_WORKBUDDY = "workbuddy"

# 权威标记：本 artifact = 真实 routing authority 的决策记录（authoritative=true）。
AUTHORITATIVE = True

DECISION_KIND = "workbuddy_active_routing"

# env 覆盖变量名：runner 在 routing_applied 时设置，adapters._workbuddy_invocation
# 读取并把 ``--model <value>`` 追加到精确 invocation（A3 用 AAF_HERMES_* 的
# 同一 override 机制；本 slice 只携带 model，绝不携带 provider/effort）。
ENV_WORKBUDDY_MODEL = "AAF_WORKBUDDY_MODEL"

# Requirement 5：active routing 至少需要两个 eligible candidates
# （capability + qualification gate；FIX-001 保持不变）。
MIN_ELIGIBLE_CANDIDATES = 2

# Requirement 5（FIX-001，Codex blocker 收口）：最小候选数 gate 必须作用于
# **全部**过滤之后（capability sufficiency + qualification/usability +
# trustworthy economics）。只有 economically_trustworthy >= 2 时才有
# 两个可比较候选，才允许 economic winner selection；否则保持 CodeBuddy Auto。
MIN_ECONOMIC_CANDIDATES = 2

AUTHORITY_STATEMENT = (
    "workbuddy_active_routing.json is the AUTHORITATIVE active-routing decision "
    "record for the WorkBuddy validator stage (A4 slices, TASK: "
    "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 [LOW] + -002 [MEDIUM]): when "
    "routing_applied=true it "
    "DIRECTLY selects the real per-run CodeBuddy --model for this execution "
    "(adapters._workbuddy_invocation appends exactly --model <routed_model>; "
    "no --effort / no provider override / no fallback model / no retry "
    "escalation). It reuses the existing A2 selector (shadow_routing) for "
    "eligibility (capability sufficiency -> qualification), the A1 "
    "Registry/Risk contracts, and the A4 economic fact layer "
    "(workbuddy_economics.cheapness_rank: FRESH + complete + consistent facts "
    "only; STALE/UNKNOWN/incomplete/contradictory fail closed) — no second "
    "independent eligibility system. Active routing additionally requires at "
    "least two candidates to survive the COMPLETE filter chain (capability + "
    "qualification + trustworthy economics, FIX-001: economically_trustworthy "
    ">= 2); fewer than two comparable candidates after any gate -> CodeBuddy "
    "Auto (INSUFFICIENT_ELIGIBLE_CANDIDATES / INSUFFICIENT_ECONOMIC_CANDIDATES "
    "/ NO_TRUSTWORTHY_ECONOMIC_WINNER). fallback_used is always false: no "
    "fallback mechanism exists. Contrast with shadow_observation.json "
    "(hypothetical, authoritative=false) and active_routing.json (A3 Hermes "
    "stage)."
)

# risk 可用性 token（与 shadow_observation 同一词汇；missing ≠ LOW）
RISK_UNAVAILABLE = "RISK_UNAVAILABLE"

_DEFAULT_REGISTRY_SOURCE = (
    "model_registry.baseline_registry() (A1 contract; evidence-backed facts; "
    "unverified dimensions are UNKNOWN — no fabricated qualification/health/capability)"
)
_DEFAULT_ECONOMIC_FACTS_SOURCE = (
    "workbuddy_economics.baseline_economic_facts() (A4 prerequisite fact layer: "
    "TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001, probe observed_at="
    "2026-09-02T02:10:30+08:00, codebuddy 2.141.0; freshness computed per "
    "reference time; refresh = re-run the read-only economic probe)"
)

# ---------------------------------------------------------------------------
# 决策 reason token（确定性；可审计）
# ---------------------------------------------------------------------------

REASON_APPLIED = "WORKBUDDY_ECONOMIC_ROUTE_APPLIED"
REASON_AGENT_NOT_WORKBUDDY = "AGENT_NOT_WORKBUDDY"
REASON_ROLE_NOT_VALIDATOR = "ROLE_NOT_VALIDATOR"
REASON_RISK_UNAVAILABLE = "RISK_UNAVAILABLE"
# 002：active-routing risk 域 = explicit LOW + MEDIUM；HIGH/CRITICAL 在
# active slice 之外（RISK_OUTSIDE_ACTIVE_SLICE，显式区别于 missing 的
# RISK_UNAVAILABLE —— missing ≠ LOW/MEDIUM，HIGH/CRITICAL ≠ in-slice）。
REASON_RISK_OUTSIDE_SLICE = "RISK_OUTSIDE_ACTIVE_SLICE"
REASON_INSUFFICIENT_ELIGIBLE = "INSUFFICIENT_ELIGIBLE_CANDIDATES"
# FIX-001（Codex Requirement 5 blocker）：capability+qualification gate 已通过、
# 经济信任度 gate 也已通过，但经济过滤后只剩 1 个可信候选 —— 没有两个
# 可比较候选，禁止 active route。显式区别于 INSUFFICIENT_ELIGIBLE_CANDIDATES
# （后者 = capability/qualification 后不足两个，绝不混用，Requirement 4）。
REASON_INSUFFICIENT_ECONOMIC = "INSUFFICIENT_ECONOMIC_CANDIDATES"
REASON_NO_TRUSTWORTHY_WINNER = "NO_TRUSTWORTHY_ECONOMIC_WINNER"

# 经济排除原因（Requirement 6：STALE / UNKNOWN / incomplete / contradictory
# 一律 fail closed，绝不进入经济排序）
ECON_STALE = "ECON_STALE"                      # 促销窗口已过期 / 尚未生效
ECON_FRESHNESS_UNKNOWN = "ECON_FRESHNESS_UNKNOWN"  # 无窗口 / 单边边界 → 无法证明当前有效
ECON_INCONSISTENT = "ECON_INCONSISTENT"        # FRESH 但字段缺失 / 自相矛盾 /
                                               # 无促销 / 全价（fact-layer 严格 gate：
                                               # 不是权威免费也不是已知新鲜折扣 → 无已知便宜 rank）
ECON_FACT_MISSING = "ECON_FACT_MISSING"        # eligible 候选无经济事实条目
ECON_EXCLUSION_REASONS = (
    ECON_STALE,
    ECON_FRESHNESS_UNKNOWN,
    ECON_INCONSISTENT,
    ECON_FACT_MISSING,
)

_REQUIRED_KEYS = (
    "schema_version",
    "decision_kind",
    "authority",
    "authoritative",
    "stage_agent",
    "role",
    "risk_class",
    "risk_source",
    "registry_source",
    "economic_facts_source",
    "freshness_reference_time",
    "candidates_considered",
    "excluded",
    "eligible",
    "selector_selected",
    "economically_trustworthy",
    "economically_excluded",
    "economic_facts",
    "selected",
    "routing_applied",
    "routed_model",
    "invocation",
    "fallback_used",
    "reason",
    "generated_at",
)

_FALLBACK_USED = False  # fixed semantic（Requirement 12）：本模块无 fallback


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _invocation_description(routed_model: str | None) -> str:
    """预期 invocation 描述（single source of truth = adapters._workbuddy_invocation）。

    routing_applied → 精确追加 ``--model <routed_model>``（恰好一个 --model，
    无 --effort / 无 provider override / 无 fallback）；否则 CodeBuddy Auto。
    """
    base = "[<codebuddy exe>, -p, --output-format, text, -y]"
    if routed_model is None:
        return (
            f"CodeBuddy Auto preserved: {base} — no --model / --effort "
            "(model chosen by CLI default/last-used)"
        )
    return (
        f"explicit per-run --model: {base[:-1]}, --model, {routed_model!r}] — "
        f"exactly one --model <{routed_model}>; no --effort / no provider "
        "override / no fallback model / no retry escalation"
    )


def _econ_fail_reason(fact: we.EconomicFact, now: datetime) -> str:
    """rank 2 经济事实的精确排除原因（fail-closed 词汇）。"""
    freshness = we.classify_freshness(fact, now)
    if freshness == we.ECON_STALE:
        return ECON_STALE
    if freshness == we.ECON_UNKNOWN:
        return ECON_FRESHNESS_UNKNOWN
    # FRESH 但 rank 2：不是权威免费、不是已知新鲜折扣（无促销 / 全价 /
    # 字段缺失或矛盾，fact-layer 严格 gate）→ incomplete/contradictory bucket
    return ECON_INCONSISTENT


def _fact_summary(fact: we.EconomicFact, now: datetime) -> dict[str, Any]:
    """eligible 候选经济事实的可审计摘要（= artifact 中「economic facts used」）。"""
    return {
        "model_id": fact.model_id,
        "multiplier": fact.multiplier,
        "multiplier_raw": fact.multiplier_raw,
        "promotion_status": fact.promotion_status,
        "promotion_factor": fact.promotion_factor,
        "valid_from": fact.valid_from,
        "valid_until": fact.valid_until,
        "observed_at": fact.observed_at,
        "freshness": we.classify_freshness(fact, now),
        "cheapness_rank": we.cheapness_rank(fact, now),
        "economic_fields_consistent": we.economic_fields_consistent(fact),
    }


def decide_workbuddy_route(
    risk_class: str | None,
    role: str,
    stage_agent: str,
    registry: dict[str, model_registry_mod.RegistryEntry],
    facts: dict[str, we.EconomicFact] | None = None,
    now: datetime | None = None,
    *,
    risk_source: str | None = None,
    registry_source: str | None = None,
    economic_facts_source: str | None = None,
) -> dict:
    """WorkBuddy validator stage 的 authoritative 经济路由决策。

    参数：
    - ``risk_class``：TASK 显式声明的 Risk（RISK_CLASSES 成员）；None =
      RISK_UNAVAILABLE（missing ≠ LOW/MEDIUM → 不生效）。active-routing
      risk 域 = explicit LOW + MEDIUM（002）；HIGH / CRITICAL 在 slice 之外
      → 不生效。
    - ``role``：stage 角色（必须 validator 才可能生效）。
    - ``stage_agent``：stage agent（必须 workbuddy 才可能生效）。
    - ``registry``：候选 registry（A1 RegistryEntry dict；建议
      ``baseline_registry()``）。
    - ``facts``：经济事实（A4 fact layer dict；缺省
      ``baseline_economic_facts()``）。
    - ``now``：freshness 参考时间（必须 tz-aware；缺省当前本地时间）。
      事实的新鲜度永远对**决策时刻**显式计算（promo 窗口过期 → fail closed），
      不信任任何已存 freshness。
    - ``risk_source``：risk_class 来源（显式 risk 时应提供）。
    - ``registry_source`` / ``economic_facts_source``：审计用来源描述。

    返回 machine-readable record（可直接 ``save_workbuddy_routing`` 落盘）。
    校验 fail closed：未知 risk_class / 非法 role / 空 agent / 非 dict
    registry / 非 dict facts / naive now → ValueError。
    """
    if not (isinstance(role, str) and role.strip()):
        raise ValueError("role must be a non-empty string")
    if not (isinstance(stage_agent, str) and stage_agent.strip()):
        raise ValueError("stage_agent must be a non-empty string")
    if role not in STAGE_ROLES:
        raise ValueError(f"unknown role: {role!r} (allowed: {STAGE_ROLES})")
    if risk_class is not None and risk_class not in RISK_CLASSES:
        raise ValueError(
            f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})"
        )
    if risk_class is not None and risk_source is None:
        raise ValueError(
            "risk_source must be provided when an explicit risk_class is supplied"
        )
    if not isinstance(registry, dict):
        raise ValueError(f"registry must be a dict, got {type(registry).__name__}")
    if facts is None:
        facts = we.baseline_economic_facts()
    if not isinstance(facts, dict):
        raise ValueError(f"facts must be a dict, got {type(facts).__name__}")
    if now is None:
        now = datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError("now must be tz-aware (freshness reference time contract)")
    if registry_source is None:
        registry_source = _DEFAULT_REGISTRY_SOURCE
    if economic_facts_source is None:
        economic_facts_source = _DEFAULT_ECONOMIC_FACTS_SOURCE

    # --- 复用现有 selector（A2 引擎；同一套 eligibility，不另起炉灶） ---
    decision_obj = None
    selector_selected: str | None = None
    considered: list[str] = []
    excluded: list[dict[str, str]] = []
    eligible: list[str] = []
    if risk_class is not None:
        decision_obj = select_shadow_candidate(
            risk_class, role, stage_agent, registry
        )
        selector_selected = decision_obj.selected
        considered = list(decision_obj.candidates_considered)
        excluded = [
            {"candidate": r.candidate, "reason": r.reason}
            for r in sorted(decision_obj.excluded, key=lambda r: (r.candidate, r.reason))
        ]
        eligible = list(decision_obj.eligible)

    # --- Activation gates（顺序确定性；第一个失败的 gate 决定 reason） ---
    routing_applied = False
    selected: str | None = None
    routed_model: str | None = None
    reason: str | None = None
    economically_trustworthy: list[str] = []
    economically_excluded: list[dict[str, str]] = []
    economic_facts_summary: dict[str, dict[str, Any]] = {}

    if stage_agent != STAGE_AGENT_WORKBUDDY:
        reason = (
            f"{REASON_AGENT_NOT_WORKBUDDY}: active economic routing applies only "
            f"to agent={STAGE_AGENT_WORKBUDDY!r}"
        )
    elif role != ROLE_VALIDATOR:
        reason = (
            f"{REASON_ROLE_NOT_VALIDATOR}: active economic routing applies only "
            f"to role={ROLE_VALIDATOR!r}"
        )
    elif risk_class is None:
        reason = (
            f"{REASON_RISK_UNAVAILABLE}: no explicit Risk declared in TASK — "
            "missing != LOW/MEDIUM (fail-safe no routing, CodeBuddy Auto preserved)"
        )
    elif risk_class not in (RISK_LOW, RISK_MEDIUM):
        reason = (
            f"{REASON_RISK_OUTSIDE_SLICE}: explicit Risk={risk_class!r} — "
            "active economic routing applies only to explicit LOW/MEDIUM "
            "(HIGH/CRITICAL keep CodeBuddy Auto)"
        )
    elif len(eligible) < MIN_ELIGIBLE_CANDIDATES:
        reason = (
            f"{REASON_INSUFFICIENT_ELIGIBLE}: {len(eligible)} eligible "
            f"WorkBuddy candidate(s) after capability+qualification gates — "
            f"active routing requires at least {MIN_ELIGIBLE_CANDIDATES} "
            "(fewer than two remain -> CodeBuddy Auto preserved)"
        )
    else:
        # --- 经济选择：只消费 FRESH + 完整 + 一致的事实（Requirement 6） ---
        ranked: list[tuple[int, float, str]] = []  # (cheapness_rank, multiplier, model_id)
        for mid in sorted(eligible):
            fact = facts.get(mid)
            if fact is None:
                economically_excluded.append(
                    {"candidate": mid, "reason": ECON_FACT_MISSING}
                )
                continue
            economic_facts_summary[mid] = _fact_summary(fact, now)
            rank = we.cheapness_rank(fact, now)
            if rank == we.RANK_UNKNOWN_OR_STALE:
                economically_excluded.append(
                    {"candidate": mid, "reason": _econ_fail_reason(fact, now)}
                )
                continue
            multiplier = fact.multiplier if fact.multiplier is not None else float("inf")
            ranked.append((rank, multiplier, mid))
        economically_trustworthy = [mid for _, _, mid in sorted(ranked)]
        if not ranked:
            reason = (
                f"{REASON_NO_TRUSTWORTHY_WINNER}: no eligible candidate has "
                "trustworthy economic facts (STALE / UNKNOWN / incomplete / "
                "contradictory / no known cheap rank all fail closed) — no "
                "deterministic trustworthy economic winner, CodeBuddy Auto preserved"
            )
        elif len(economically_trustworthy) < MIN_ECONOMIC_CANDIDATES:
            # FIX-001（Codex Requirement 5 blocker）：capability+qualification
            # gate 已通过、经济信任度 gate 也已通过，但经济过滤后只剩 1 个可信
            # 候选 —— 没有两个可比较候选，绝不 active route（保持 CodeBuddy
            # Auto）。显式区别于 INSUFFICIENT_ELIGIBLE_CANDIDATES（那是
            # capability/qualification 后不足两个，Requirement 4 不得混用）。
            reason = (
                f"{REASON_INSUFFICIENT_ECONOMIC}: {len(economically_trustworthy)} "
                f"eligible WorkBuddy candidate(s) with trustworthy economics "
                f"after capability + qualification + trustworthy-economics gates "
                f"({len(eligible)} passed capability+qualification) — active "
                f"economic routing requires at least {MIN_ECONOMIC_CANDIDATES} "
                "comparable candidates; fewer than two -> CodeBuddy Auto preserved"
            )
        else:
            # Requirement 7：rank 0（权威免费）outranks rank 1（已知折扣）；
            # rank 1 内更低 multiplier 获胜；经济完全相等 → model_id 字典序
            # 确定性 tie-break（输入顺序无关）。仅当 economically_trustworthy
            # >= 2（两个可比较候选）才允许 winner selection（FIX-001）。
            ranked.sort(key=lambda t: (t[0], t[1], t[2]))
            winner_rank, winner_multiplier, winner = ranked[0]
            routing_applied = True
            selected = winner
            routed_model = winner
            reason = (
                f"{REASON_APPLIED}: explicit Risk={risk_class} + "
                f"{len(eligible)} eligible WorkBuddy candidates (capability + "
                f"qualification gates) + {len(economically_trustworthy)} "
                f"trustworthy economic candidates (>= {MIN_ECONOMIC_CANDIDATES} "
                f"comparable) -> economic winner {winner!r} "
                f"(cheapness_rank={winner_rank}, "
                f"multiplier={winner_multiplier}) -> active route with per-run "
                f"--model {winner}"
            )

    record = {
        "schema_version": SCHEMA_VERSION,
        "decision_kind": DECISION_KIND,
        "authority": AUTHORITY_STATEMENT,
        "authoritative": AUTHORITATIVE,
        "stage_agent": stage_agent,
        "role": role,
        "risk_class": risk_class,
        "risk_source": (
            risk_source if risk_class is not None else RISK_UNAVAILABLE
        ),
        "registry_source": registry_source,
        "economic_facts_source": economic_facts_source,
        "freshness_reference_time": now.isoformat(timespec="seconds"),
        "candidates_considered": considered,
        "excluded": excluded,
        "eligible": eligible,
        "selector_selected": selector_selected,
        "economically_trustworthy": economically_trustworthy,
        "economically_excluded": economically_excluded,
        "economic_facts": economic_facts_summary,
        "selected": selected,
        "routing_applied": routing_applied,
        "routed_model": routed_model,
        "invocation": _invocation_description(routed_model),
        "fallback_used": _FALLBACK_USED,
        "reason": reason,
        "generated_at": _now_iso(),
    }
    validate_workbuddy_routing(record)
    return record


# ---------------------------------------------------------------------------
# Schema 校验（fail closed）
# ---------------------------------------------------------------------------


def validate_workbuddy_routing(record: dict) -> None:
    """Schema 契约校验（fail closed）。

    - 必需字段齐全；schema_version == SCHEMA_VERSION。
    - authoritative 必须是 True（本 artifact = authoritative routing decision）。
    - fallback_used 必须是 False（本模块无 fallback；任何 True 都是违规）。
    - routing_applied=True → selected / routed_model 必须非空且相等
      （不能声明生效却无模型；routed_model 必须 == 经济 winner）。
    - routing_applied=False → selected / routed_model 必须是 None
      （Requirement 14：Auto 保持时 artifact 不得声称任何模型路由）。
    - risk_class 显式 → risk_source 必须存在。
    """
    if not isinstance(record, dict):
        raise ValueError("workbuddy routing record must be a mapping")
    missing = [k for k in _REQUIRED_KEYS if k not in record]
    if missing:
        raise ValueError(f"workbuddy routing record missing required keys: {missing}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported workbuddy routing schema_version: "
            f"{record.get('schema_version')!r}"
        )
    if record["authoritative"] is not True:
        raise ValueError("authoritative must be True (authoritative routing decision)")
    if record["fallback_used"] is not False:
        raise ValueError(
            "fallback_used must be False (no fallback mechanism exists — "
            "requirement: no silent fallback)"
        )
    if record["routing_applied"] is True:
        routed = record.get("routed_model")
        if not (isinstance(routed, str) and routed.strip()):
            raise ValueError(
                "routing_applied=True requires a non-empty routed_model "
                "(cannot claim an applied route without an actual model)"
            )
        if record.get("selected") != routed:
            raise ValueError(
                "routing_applied=True requires selected == routed_model "
                "(the routed model must be the economic winner)"
            )
    else:
        if record.get("selected") is not None or record.get("routed_model") is not None:
            raise ValueError(
                "routing_applied=False must leave selected/routed_model as None "
                "(must not claim model routing when CodeBuddy Auto is preserved)"
            )
    if record.get("risk_class") is not None and not record.get("risk_source"):
        raise ValueError(
            "risk_source must be provided when risk_class is explicitly set"
        )


# ---------------------------------------------------------------------------
# 持久化（原子写；与 shadow_observation / active_routing 同一约定）
# ---------------------------------------------------------------------------


def save_workbuddy_routing(output_dir: Path | str, record: dict) -> Path:
    """原子写 artifact（同目录 tmp + os.replace）。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / ARTIFACT_FILENAME
    tmp = output_dir / f"{ARTIFACT_FILENAME}.tmp-{os.getpid()}"
    tmp.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def load_workbuddy_routing(output_dir: Path | str) -> dict | None:
    """读取 artifact；缺失 / 损坏 → None（不抛出；辅助审计/测试读取）。"""
    path = Path(output_dir) / ARTIFACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Env 覆盖 apply / restore（runner WorkBuddy stage 使用；A3 同一机制）
# ---------------------------------------------------------------------------


def apply_workbuddy_model_env(record: dict) -> dict[str, str | None]:
    """把已 applied 的 routed model 写入 env 覆盖（AAF_WORKBUDDY_MODEL）。

    返回 {var: 旧值或 None} 供 ``restore_workbuddy_model_env`` 精确还原
    （old None = 调用前不存在 → restore 时删除）。

    调用前提：``record['routing_applied'] is True``（调用方负责；违反 →
    ValueError，fail closed —— 未生效的决策不得触碰 env）。
    """
    if not record.get("routing_applied"):
        raise ValueError(
            "apply_workbuddy_model_env requires a routing_applied=True record "
            "(never touch invocation env for a non-applied decision)"
        )
    model = record.get("routed_model")
    if not (isinstance(model, str) and model.strip()):
        raise ValueError(
            "apply_workbuddy_model_env requires a non-empty routed_model"
        )
    saved: dict[str, str | None] = {}
    saved[ENV_WORKBUDDY_MODEL] = os.environ.get(ENV_WORKBUDDY_MODEL)
    os.environ[ENV_WORKBUDDY_MODEL] = model
    return saved


def restore_workbuddy_model_env(saved: dict[str, str | None]) -> None:
    """还原 apply_workbuddy_model_env 之前的 env 状态（旧值 None → 删除该变量）。"""
    for var, old in saved.items():
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old
