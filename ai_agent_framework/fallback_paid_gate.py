"""AAF v0.5 A5 — Paid Escalation Cost Gate（authorization-evaluation-only foundation）。

TASK: AAF-v0.5-A5-PAID-ESCALATION-GATE-001
在 A5 正式 scope（bounded, auditable fallback / escalation / Cost Gate
foundation）内交付 paid escalation / Cost Gate 的 **runtime foundation**：
当 Hermes executor stage 的原始 invocation 以 fallback-eligible failure 失败、
无合格 FREE/LOCAL_FREE fallback 可用、但存在**合格 paid candidate**（已通过
A1/A2 资格闸、与失败 original 不同）时，使用**既有 A0 Paid Guard / Cost Guard
authority**（``cost_guard.evaluate``——唯一付费授权 authority）对该 candidate
做显式、可审计的授权判断。**本任务/本模块绝不执行 paid fallback model
invocation**：Cost Gate 只记录 AUTHORIZED / ready-for-paid-invocation 资格
状态；paid invocation 是后续 A5 任务的 scope。

设计纪律（与既有权威的关系——**不创建第二套授权系统**，Requirement 4）：
1. candidate 资格判定**复用** A2 selector（``shadow_routing.select_shadow_candidate``
   ——A1 registry/risk 契约：capability → qualification → executor main-scope
   闸）与既有 fallback decision contract（``fallback_contract.decide_fallback``）。
   本模块零 eligibility 判断；paid candidate pool = contract fallback candidates
   中未通过 FREE/LOCAL_FREE cost gate 的成员（registry cost_class 不在 A3
   ``ACTIVE_ROUTING_COST_CLASSES``——由 runtime 层传入同一 cost-gate 词汇）。
2. authorization 判断**复用** A0 Paid Guard（``cost_guard.evaluate``）在
   candidate 的 env 覆盖下求值——A0 是 effective cost / 授权的权威解析层：
   - A0 ``ALLOWED_AUTHORIZED_PAID`` + A0 解析的 model/provider == candidate
     （scope 完整性）→ gate ``AUTHORIZED``（exact task-scoped authorization
     已由 A0 在其准入边界按既有一次性语义 claim；本层如实转述 A0 的
     authorization_present / matched / consumed 字段）；
   - A0 ``BLOCKED_COST_APPROVAL`` → gate ``BLOCKED``（absent / mismatched /
     replay-rejected——A0 notes + flags 给出原因）；
   - A0 ``ALLOWED_FREE``（registry 说 paid、A0 权威解析为 free——成本视图
     冲突）/ guard record malformed / guard 解析的 model/provider != candidate /
     guard evaluation 失败 / 未知 guard decision → gate ``FAIL_CLOSED``
     （malformed/unknown authorization state → fail closed）。
   **没有**第二 auth token、**没有** implicit authorization、**没有** broad/
   global authorization、stage/model/provider 精确匹配零削弱（Requirement 3/4）。
3. 本单元零执行权威：fallback_attempted / fallback_used 恒 False（fixed
   semantic + validate fail-closed）；authorization 只建立未来 paid invocation
   任务的资格状态，绝不自行执行（Requirement 6/8）。gate record 的
   final_actual_model/provider 恒等于 original（无任何模型切换）。
4. 纯审计语义模块：无 I/O 到 env / 无 subprocess / 无网络 / 无 LLM；env 覆盖、
   A0 求值与编排由 fallback_runtime（live runtime layer）执行——本模块只负责
   「A0 record → gate 解释 → authoritative audit record 组装/校验/持久化」。
   持久化 = 原子写（同目录 tmp + os.replace，与 A3/A4/A5 既有 artifact 同约定）。

Cost Gate 考虑前置（Requirement 2；live runtime 层 enforcement）：
- original execution 产生 fallback-eligible failure（failure_class ∈
  TRIGGER_CAPABLE_CLASSES）；
- 无合格 FREE/LOCAL_FREE fallback 可用（runtime FREE gate 结果为空）且
  automatic fallback budget 未耗尽（count_used == 0——paid escalation 是
  eligible 时免费路径的替代，绝不发生在已消耗一次 model-level fallback 之后：
  no chain/loop 保持）；
- candidate 已通过 role/risk/capability/qualification 检查（contract/selector
  层）且 distinct from original（contract 已排除）。

Audit record（machine-readable；validate fail-closed）：task/stage/role/risk、
original model/provider、failure class/trigger、为什么 FREE fallback 不可用、
proposed paid candidate model/provider、paid_escalation_required、
authorization_present / matched / consumed、guard decision（A0 token）、
gate decision（AUTHORIZED / BLOCKED / FAIL_CLOSED）、attempted/used 恒 False、
final actual == original、explicit no-silent-paid-execution evidence——
字段与语义见 _REQUIRED_KEYS 与 ``validate_paid_escalation_gate_record``。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import cost_guard as cg
from . import fallback_contract as fc

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DECISION_KIND = "paid_escalation_gate_audit"
ARTIFACT_FILENAME = "paid_escalation_gate.json"

# 唯一权威说明（写入每个 record；指明本 artifact 的权威来源与复用纪律——
# A0 Paid Guard = 唯一付费授权 authority；本层零执行、零第二授权系统）
AUTHORITY = (
    "fallback_paid_gate.py (A5 paid escalation Cost Gate, TASK: "
    "AAF-v0.5-A5-PAID-ESCALATION-GATE-001): this artifact is the "
    "AUTHORITATIVE audit record of the paid escalation authorization "
    "evaluation for a Hermes executor stage whose fallback-eligible failure "
    "had no usable FREE/LOCAL_FREE fallback but had qualified paid "
    "candidate(s). Candidate qualification reuses the single authoritative "
    "A5 decision contract (fallback_contract.decide_fallback -> A2 selector "
    "-> A1 registry/risk gates); authorization reuses the A0 Paid Guard "
    "(cost_guard.evaluate) as the ONLY payment authorization authority — no "
    "second auth token, no implicit/broad/global authorization, exact "
    "task/stage/model/provider scope matching unmodified. This unit performs "
    "authorization evaluation ONLY: fallback_attempted/fallback_used are "
    "always false and no paid model was or can be invoked by this unit "
    "(gate decision AUTHORIZED records ready-for-paid-invocation eligibility "
    "for a FUTURE paid invocation task only)."
)

# Cost Gate decision tokens（Requirement 3：三种状态至少可区分）
GATE_DECISION_AUTHORIZED = "AUTHORIZED"
GATE_DECISION_BLOCKED = "BLOCKED"
GATE_DECISION_FAIL_CLOSED = "FAIL_CLOSED"

GATE_DECISIONS = (
    GATE_DECISION_AUTHORIZED,
    GATE_DECISION_BLOCKED,
    GATE_DECISION_FAIL_CLOSED,
)

# A0 guard record 中本层需要读取的字段（missing → malformed → FAIL_CLOSED）
_GUARD_REQUIRED_KEYS = (
    "decision",
    "model",
    "provider",
    "authorization_present",
    "authorization_matched",
    "authorization_consumed",
    "cost_class",
    "required_scope",
)

# ---------------------------------------------------------------------------
# Audit schema（Requirement 5 全部字段；validate fail-closed）
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = (
    "schema_version",
    "decision_kind",
    "authority",
    "authoritative",
    "task_id",
    "stage_agent",
    "role",
    "risk_class",
    "risk_source",
    "failure_class",
    "failure_label",
    "trigger",
    "trigger_evidence",
    "original_model",
    "original_provider",
    "transport_retry_count",
    "automatic_fallback_count_used",
    "automatic_fallback_count_budget",
    "free_fallback_unavailable_reason",
    "contract_candidates",
    "paid_candidates",
    "paid_candidate",
    "paid_candidate_model",
    "paid_candidate_provider",
    "paid_escalation_required",
    "authorization_present",
    "authorization_matched",
    "authorization_consumed",
    "guard_decision",
    "guard_cost_class",
    "guard_model",
    "guard_provider",
    "required_scope",
    "gate_decision",
    "gate_reason",
    "fallback_attempted",
    "fallback_used",
    "final_actual_model",
    "final_actual_provider",
    "no_silent_paid_evidence",
    "notes",
    "generated_at",
)

# 本单元 fixed semantic：无执行权威（Cost Gate 永不 invocation）
_FALLBACK_ATTEMPTED = False
_FALLBACK_USED = False


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _split_key(key: str) -> tuple[str, str | None]:
    """``model@provider`` key → (model, provider)（canonical_key 逆操作）。"""
    if "@" in key:
        model, _, provider = key.partition("@")
        return model, provider or None
    return key, None


# ---------------------------------------------------------------------------
# A0 guard record → Cost Gate 解释（纯函数；确定性；fail closed）
# ---------------------------------------------------------------------------


def fail_closed_interpretation(reason: str) -> dict:
    """guard 求值未发生/失败时的 FAIL_CLOSED 解释（guard 字段全 None）。

    ``reason`` 必须是非空显式证据（guard 抛异常 / env overlay 失败等——
    malformed/unknown authorization state → fail closed，Requirement 3）。
    """
    return {
        "gate_decision": GATE_DECISION_FAIL_CLOSED,
        "gate_reason": reason,
        "authorization_present": False,
        "authorization_matched": False,
        "authorization_consumed": False,
        "guard_decision": None,
        "guard_cost_class": None,
        "guard_model": None,
        "guard_provider": None,
        "required_scope": None,
        "notes": [reason],
    }


def interpret_guard(
    guard_record: dict | None,
    model: str,
    provider: str | None,
) -> dict:
    """把 A0 Paid Guard record 解释为 Cost Gate 状态（确定性、fail closed）。

    返回 dict：{gate_decision, gate_reason, authorization_present,
    authorization_matched, authorization_consumed, guard_decision,
    guard_cost_class, guard_model, guard_provider, required_scope, notes}。

    映射（Requirement 3）：
    - guard record 缺失 / malformed（缺必需字段 / 非 dict）→ FAIL_CLOSED；
    - guard 解析的 effective model/provider != candidate model/provider →
      FAIL_CLOSED（scope integrity：A0 求值的不是本 candidate，授权状态无法
      归属——绝不凭错误 scope 的 record 放行/记录，Requirement 4 零削弱）；
    - ``ALLOWED_AUTHORIZED_PAID``（且 A0 三个 authorization flags 全 True）→
      AUTHORIZED（exact task-scoped authorization；A0 已在其准入边界按既有
      一次性语义 claim——本层如实转述 consumed 状态）；
    - ``BLOCKED_COST_APPROVAL`` → BLOCKED（absent / mismatch /
      replay-rejected；flags + guard notes 给出原因）；matched=True 的 BLOCKED
      record = malformed → FAIL_CLOSED；
    - ``ALLOWED_FREE`` → FAIL_CLOSED（registry 视为 paid 的候选被 A0 权威
      解析为 FREE = 冲突成本视图——不授 paid 资格、不静默放行）；
    - 其他未知 decision token → FAIL_CLOSED。
    """
    missing = (
        []
        if isinstance(guard_record, dict)
        else ["record is not a dict"]
    )
    if isinstance(guard_record, dict):
        missing = [k for k in _GUARD_REQUIRED_KEYS if k not in guard_record]
    if missing:
        reason = (
            "malformed/unknown A0 Paid Guard record (missing required "
            f"field(s): {sorted(missing)}) — authorization state cannot be "
            "determined; fail closed (no paid escalation state assigned, no "
            "paid model invoked)"
        )
        interp = fail_closed_interpretation(reason)
        return interp

    guard_model = guard_record["model"]
    guard_provider = guard_record["provider"]
    if guard_model != model or guard_provider != provider:
        reason = (
            "scope integrity failure: A0 Paid Guard evaluated effective "
            f"model/provider {guard_model!r}/{guard_provider!r} but the "
            f"proposed paid candidate is {model!r}/{provider!r} — the A0 "
            "record cannot be attributed to this candidate's exact "
            "task/stage/model scope; fail closed (no weakening of "
            "stage/model/provider matching; no paid escalation state "
            "assigned, no paid model invoked)"
        )
        interp = fail_closed_interpretation(reason)
        interp["guard_decision"] = guard_record["decision"]
        interp["guard_cost_class"] = guard_record["cost_class"]
        interp["guard_model"] = guard_model
        interp["guard_provider"] = guard_provider
        # 授权 flags 不转述为 True：A0 求值对象不是本 candidate —— 任何授权
        # 状态都无法归属到本候选（fail closed；validate 不变量
        # matched=true ⟹ AUTHORIZED 保持自洽）
        interp["required_scope"] = guard_record["required_scope"]
        return interp

    present = guard_record["authorization_present"]
    matched = guard_record["authorization_matched"]
    consumed = guard_record["authorization_consumed"]
    if not all(isinstance(v, bool) for v in (present, matched, consumed)):
        reason = (
            "malformed A0 Paid Guard record: authorization_present/matched/"
            "consumed must be bools — fail closed (unknown authorization "
            "state; no paid model invoked)"
        )
        return fail_closed_interpretation(reason)

    base = {
        "authorization_present": present,
        "authorization_matched": matched,
        "authorization_consumed": consumed,
        "guard_decision": guard_record["decision"],
        "guard_cost_class": guard_record["cost_class"],
        "guard_model": guard_model,
        "guard_provider": guard_provider,
        "required_scope": guard_record["required_scope"],
        "notes": list(guard_record.get("notes") or []),
    }

    decision = guard_record["decision"]
    if decision == cg.DECISION_ALLOWED_AUTHORIZED_PAID:
        if not (present and matched and consumed):
            reason = (
                "contradictory A0 Paid Guard record: decision "
                "ALLOWED_AUTHORIZED_PAID requires authorization_present/"
                "matched/consumed all true, got "
                f"present={present}/matched={matched}/consumed={consumed} — "
                "malformed authorization state; fail closed (no paid model "
                "invoked)"
            )
            interp = fail_closed_interpretation(reason)
            interp.update(base)
            return interp
        return {
            **base,
            "gate_decision": GATE_DECISION_AUTHORIZED,
            "gate_reason": (
                "exact task-scoped AAF_COST_AUTH authorization present and "
                "atomically claimed at the A0 Paid Guard admission boundary "
                f"(decision={decision!r}, required_scope="
                f"{guard_record['required_scope']!r}) — gate decision "
                "AUTHORIZED records ready-for-paid-invocation ELIGIBILITY "
                "for a future paid invocation task only; NO paid model was "
                "or will be invoked by this Cost Gate (fallback_attempted/"
                "used stay false)"
            ),
        }
    if decision == cg.DECISION_BLOCKED_COST_APPROVAL:
        if matched is True:
            reason = (
                "contradictory A0 Paid Guard record: BLOCKED_COST_APPROVAL "
                "with authorization_matched=true cannot occur (a matched "
                "one-time authorization is claimed at the A0 admission "
                "boundary and yields ALLOWED_AUTHORIZED_PAID) — malformed "
                "authorization state; fail closed (no paid model invoked)"
            )
            interp = fail_closed_interpretation(reason)
            interp.update(base)
            return interp
        if consumed is True:
            block_reason = (
                "paid escalation required but the exact task-scoped "
                "one-time authorization is ALREADY CONSUMED in this "
                "execution context (A0 claim failed: replay rejected — "
                "same auth cannot admit twice; fail closed; no paid model "
                "invoked; a future paid invocation task must re-submit with "
                "a fresh execution context per the existing A0 one-time "
                "semantics)"
            )
        elif present is False:
            block_reason = (
                "paid escalation required but no AAF_COST_AUTH "
                "authorization value is present for the proposed paid "
                "candidate's exact task/stage/model scope — BLOCKED (fail "
                "closed; no paid model invoked; the original stage failure "
                "is preserved)"
            )
        else:
            block_reason = (
                "paid escalation required but the present AAF_COST_AUTH "
                "authorization does not exactly match the proposed paid "
                "candidate's task/stage/model scope (required_scope="
                f"{guard_record['required_scope']!r}) — BLOCKED (fail "
                "closed; no paid model invoked; no weakening of exact "
                "scope matching)"
            )
        return {
            **base,
            "gate_decision": GATE_DECISION_BLOCKED,
            "gate_reason": block_reason,
        }
    if decision == cg.DECISION_ALLOWED_FREE:
        reason = (
            "unexpected A0 Paid Guard decision ALLOWED_FREE for a proposed "
            "PAID candidate: the A5 FREE/LOCAL_FREE cost gate (registry "
            f"cost_class {guard_record['cost_class']!r}) had excluded this "
            "candidate, yet A0's authoritative cost resolution classified "
            "it FREE — conflicting cost views cannot authorize paid "
            "escalation; fail closed (no paid escalation state assigned, "
            "no paid model invoked)"
        )
        interp = fail_closed_interpretation(reason)
        interp.update(base)
        return interp
    reason = (
        f"unknown A0 Paid Guard decision token {decision!r} — malformed/"
        "unknown authorization state; fail closed (no paid model invoked)"
    )
    interp = fail_closed_interpretation(reason)
    interp.update(base)
    return interp


# ---------------------------------------------------------------------------
# Authoritative audit record（单一组装点；组装后立即 fail-closed 校验）
# ---------------------------------------------------------------------------


def assemble_paid_gate_record(
    *,
    decision_record: dict,
    original_model: str,
    original_provider: str | None,
    task_id: str,
    stage_agent: str,
    role: str,
    risk_class: str,
    risk_source: str,
    transport_retry_count: int,
    automatic_fallback_count_used: int,
    free_fallback_unavailable_reason: str,
    free_fallback_notes: list[str],
    contract_candidates: list[str],
    paid_pool: list[str],
    paid_candidate: str,
    interpretation: dict,
    extra_notes: list[str] | None = None,
) -> dict:
    """组装 authoritative paid escalation Cost Gate audit record（Req 5 全字段）。

    组装后立即经 ``validate_paid_escalation_gate_record`` fail-closed 校验。
    ``interpretation`` 来自 ``interpret_guard`` / ``fail_closed_interpretation``
    （A0 record 的权威解释）；audit 字段如实转述 A0 的 authorization flags 与
    guard decision，不加工、不伪装。
    """
    paid_candidate_model, paid_candidate_provider = _split_key(paid_candidate)
    paid_escalation_required = True  # 本 artifact 只产生于 paid-escalation 上下文

    evidence = [
        "no silent paid execution: the paid escalation Cost Gate performs "
        "authorization evaluation ONLY — NO paid model invocation was "
        "attempted and none is authorized to be performed by this task "
        f"(fallback_attempted={_FALLBACK_ATTEMPTED} / fallback_used="
        f"{_FALLBACK_USED}; zero second-model invocation occurred)",
        f"gate decision {interpretation['gate_decision']!r}: the exact "
        "task-scoped AAF_COST_AUTH / Paid Guard contract (A0) is the only "
        "payment authorization authority consumed; no second auth token, "
        "no implicit/broad/global authorization, exact task/stage/model/"
        "provider scope matching unmodified",
    ]
    if interpretation["gate_decision"] == GATE_DECISION_AUTHORIZED:
        evidence.append(
            "AUTHORIZED = ready-for-paid-invocation ELIGIBILITY recorded "
            "for a FUTURE paid invocation task; this task still did NOT "
            "invoke the paid model — the original stage failure is "
            "preserved and authorization alone does not set "
            "fallback_attempted/fallback_used"
        )
    elif interpretation["gate_decision"] == GATE_DECISION_BLOCKED:
        evidence.append(
            "BLOCKED: paid escalation required but authorization absent/"
            "mismatched — fail closed, no paid model invoked, original "
            "stage failure preserved"
        )
    else:
        evidence.append(
            "FAIL_CLOSED: malformed/unknown authorization state — fail "
            "closed, no paid model invoked, original stage failure preserved"
        )
    evidence.append(
        "one-fallback/no-chain: the Cost Gate performs no model invocation "
        "and consumes none of the affected stage's automatic fallback "
        "budget — this stage has no fallback chain/loop; the automatic "
        "fallback decision (fallback_not_eligible with explicit reason) is "
        "recorded separately in the authoritative fallback_runtime.json"
    )
    if automatic_fallback_count_used == 0:
        evidence.append(
            "automatic_fallback_count_used=0: no automatic model-level "
            "fallback attempt occurred in this affected stage before the "
            "gate — paid escalation is only considered while the one-"
            "fallback budget is unspent (no chain/loop)"
        )

    notes = list(free_fallback_notes)
    notes.extend(interpretation["notes"])
    if extra_notes:
        notes.extend(extra_notes)

    record = {
        "schema_version": SCHEMA_VERSION,
        "decision_kind": DECISION_KIND,
        "authority": AUTHORITY,
        "authoritative": True,
        "task_id": task_id,
        "stage_agent": stage_agent,
        "role": role,
        "risk_class": risk_class,
        "risk_source": risk_source,
        "failure_class": decision_record["failure_class"],
        "failure_label": decision_record["failure_label"],
        "trigger": decision_record["trigger"],
        "trigger_evidence": list(decision_record["trigger_evidence"]),
        "original_model": original_model,
        "original_provider": original_provider,
        "transport_retry_count": transport_retry_count,
        "automatic_fallback_count_used": automatic_fallback_count_used,
        "automatic_fallback_count_budget": fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE,
        "free_fallback_unavailable_reason": free_fallback_unavailable_reason,
        "contract_candidates": sorted(contract_candidates),
        "paid_candidates": sorted(paid_pool),
        "paid_candidate": paid_candidate,
        "paid_candidate_model": paid_candidate_model,
        "paid_candidate_provider": paid_candidate_provider,
        "paid_escalation_required": paid_escalation_required,
        "authorization_present": interpretation["authorization_present"],
        "authorization_matched": interpretation["authorization_matched"],
        "authorization_consumed": interpretation["authorization_consumed"],
        "guard_decision": interpretation["guard_decision"],
        "guard_cost_class": interpretation["guard_cost_class"],
        "guard_model": interpretation["guard_model"],
        "guard_provider": interpretation["guard_provider"],
        "required_scope": interpretation["required_scope"],
        "gate_decision": interpretation["gate_decision"],
        "gate_reason": interpretation["gate_reason"],
        "fallback_attempted": _FALLBACK_ATTEMPTED,
        "fallback_used": _FALLBACK_USED,
        "final_actual_model": original_model,
        "final_actual_provider": original_provider,
        "no_silent_paid_evidence": evidence,
        "notes": notes,
        "generated_at": _now_iso(),
    }
    validate_paid_escalation_gate_record(record)
    return record


# ---------------------------------------------------------------------------
# 校验（authorization-evaluation 语义；fail closed）
# ---------------------------------------------------------------------------


def validate_paid_escalation_gate_record(record: dict) -> None:
    """Cost Gate audit record fail-closed 校验。

    任一违例 → ValueError（不返回部分有效状态）。不变量：
    - schema / authority 精确匹配（single authoritative source——authority
      被篡改/缺失 → fail closed，不创建第二套 authority 系统）；
    - failure_class ∈ TRIGGER_CAPABLE_CLASSES（paid escalation 只在
      fallback-eligible failure 之后考虑，Requirement 2）；
    - fallback_attempted/fallback_used 必须 False（本单元零执行权威）；
    - paid_escalation_required 必须 True（本 artifact 只产生于 paid 上下文）；
    - final_actual == original（无任何模型切换）；
    - gate_decision ∈ {AUTHORIZED, BLOCKED, FAIL_CLOSED} 且与
      guard_decision / authorization flags 互洽（AUTHORIZED ⟺ A0
      ALLOWED_AUTHORIZED_PAID + exact candidate scope + 三 flags True；
      matched=True ⟹ AUTHORIZED；BLOCKED ⟹ A0 BLOCKED_COST_APPROVAL）；
    - candidates 一致性（paid ⊆ contract；paid_candidate ∈ paid；
      model/provider == key 拆分）。
    """
    if not isinstance(record, dict):
        raise ValueError(f"record must be a dict, got {type(record).__name__}")
    for key in _REQUIRED_KEYS:
        if key not in record:
            raise ValueError(f"audit record missing required field: {key!r}")
    unknown = [k for k in record if k not in _REQUIRED_KEYS]
    if unknown:
        raise ValueError(f"audit record has unknown fields: {sorted(unknown)}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {record['schema_version']!r}"
        )
    if record["decision_kind"] != DECISION_KIND:
        raise ValueError(
            f"decision_kind must be {DECISION_KIND!r}, "
            f"got {record['decision_kind']!r}"
        )
    if record["authoritative"] is not True:
        raise ValueError("authoritative must be true")
    if record["authority"] != AUTHORITY:
        raise ValueError(
            "authority must exactly match the authoritative A5 paid "
            "escalation Cost Gate value emitted by this module (single "
            "authoritative source; missing/altered/unexpected authority "
            "fails closed — no second authority system)"
        )

    failure_class = record["failure_class"]
    if failure_class not in fc.TRIGGER_CAPABLE_CLASSES:
        raise ValueError(
            "paid escalation may only be considered after a "
            "fallback-eligible failure (failure_class must be in "
            f"TRIGGER_CAPABLE_CLASSES), got {failure_class!r}"
        )
    if record["failure_label"] != fc.FAILURE_LABELS[failure_class]:
        raise ValueError("failure_label does not match failure_class")
    if record["role"] not in fc.STAGE_ROLES:
        raise ValueError(f"unknown role: {record['role']!r}")
    if record["risk_class"] not in fc.RISK_CLASSES:
        raise ValueError(f"unknown risk_class: {record['risk_class']!r}")

    gate_decision = record["gate_decision"]
    if gate_decision not in GATE_DECISIONS:
        raise ValueError(
            f"unknown gate_decision: {gate_decision!r} "
            f"(allowed: {GATE_DECISIONS})"
        )
    if not (
        isinstance(record["gate_reason"], str) and record["gate_reason"].strip()
    ):
        raise ValueError("gate_reason must be a non-empty string")
    if not (
        isinstance(record["free_fallback_unavailable_reason"], str)
        and record["free_fallback_unavailable_reason"].strip()
    ):
        raise ValueError(
            "free_fallback_unavailable_reason (why FREE/LOCAL_FREE fallback "
            "was unavailable/exhausted) must be a non-empty string"
        )

    for flag in (
        "authorization_present",
        "authorization_matched",
        "authorization_consumed",
    ):
        if record[flag] is not True and record[flag] is not False:
            raise ValueError(f"{flag} must be a bool")

    guard_decision = record["guard_decision"]
    a0_tokens = (
        cg.DECISION_ALLOWED_FREE,
        cg.DECISION_ALLOWED_AUTHORIZED_PAID,
        cg.DECISION_BLOCKED_COST_APPROVAL,
    )
    if guard_decision is not None and guard_decision not in a0_tokens:
        raise ValueError(
            f"guard_decision must be an A0 Paid Guard token or None, "
            f"got {guard_decision!r}"
        )
    for key in ("guard_model", "guard_provider", "required_scope"):
        value = record[key]
        if value is not None and not (isinstance(value, str) and value.strip()):
            raise ValueError(f"{key} must be a non-empty string or None")
    guard_cost_class = record["guard_cost_class"]
    if guard_cost_class is not None and not (
        isinstance(guard_cost_class, str) and guard_cost_class.strip()
    ):
        raise ValueError("guard_cost_class must be a non-empty string or None")

    # --- 零执行不变量（Requirement 6/8） ---
    if record["fallback_attempted"] is not False:
        raise ValueError(
            "fallback_attempted must be False (this Cost Gate unit has no "
            "execution authority — authorization alone never sets "
            "fallback_attempted; no paid model may be invoked)"
        )
    if record["fallback_used"] is not False:
        raise ValueError(
            "fallback_used must be False (this Cost Gate unit never uses a "
            "paid fallback model)"
        )
    if record["paid_escalation_required"] is not True:
        raise ValueError(
            "paid_escalation_required must be true (this artifact is only "
            "produced in a paid-escalation context)"
        )
    if (
        record["final_actual_model"] != record["original_model"]
        or record["final_actual_provider"] != record["original_provider"]
    ):
        raise ValueError(
            "final_actual_model/provider must equal original_model/provider "
            "(no model switch occurred; the gate performs no invocation)"
        )

    # --- gate_decision ↔ guard 互洽 ---
    present = record["authorization_present"]
    matched = record["authorization_matched"]
    consumed = record["authorization_consumed"]
    paid_candidate_model = record["paid_candidate_model"]
    paid_candidate_provider = record["paid_candidate_provider"]
    guard_scope_ok = (
        guard_decision == cg.DECISION_ALLOWED_AUTHORIZED_PAID
        and guard_decision is not None
        and record["guard_model"] == paid_candidate_model
        and record["guard_provider"] == paid_candidate_provider
    )
    if gate_decision == GATE_DECISION_AUTHORIZED:
        if not (
            guard_scope_ok
            and present is True
            and matched is True
            and consumed is True
            and record["guard_model"] is not None
            and record["required_scope"]
        ):
            raise ValueError(
                "gate_decision=AUTHORIZED requires an exact A0 Paid Guard "
                "ALLOWED_AUTHORIZED_PAID result for the proposed paid "
                "candidate's exact model/provider scope with "
                "authorization_present/matched/consumed all true and a "
                "non-empty required_scope — contradictory record fails "
                "closed"
            )
    elif guard_decision == cg.DECISION_ALLOWED_AUTHORIZED_PAID and guard_scope_ok:
        raise ValueError(
            "an exact A0 ALLOWED_AUTHORIZED_PAID result (with exact "
            "candidate scope) must map to gate_decision=AUTHORIZED — "
            "contradictory record fails closed"
        )
    if matched is True and gate_decision != GATE_DECISION_AUTHORIZED:
        raise ValueError(
            "authorization_matched=true requires gate_decision=AUTHORIZED "
            "(a matched exact one-time authorization can only yield "
            "AUTHORIZED at the gate)"
        )
    if gate_decision == GATE_DECISION_BLOCKED:
        if guard_decision != cg.DECISION_BLOCKED_COST_APPROVAL:
            raise ValueError(
                "gate_decision=BLOCKED requires guard_decision="
                "BLOCKED_COST_APPROVAL (the A0 Paid Guard's authoritative "
                "denial), got "
                f"{guard_decision!r}"
            )
        if matched is True:
            raise ValueError(
                "gate_decision=BLOCKED with authorization_matched=true is "
                "contradictory (see above)"
            )
    if consumed is True and gate_decision in (GATE_DECISION_AUTHORIZED,) and not (
        present is True and matched is True
    ):
        raise ValueError(
            "authorization_consumed=true with AUTHORIZED requires "
            "present/matched true as well"
        )

    # --- 计数 / budget ---
    budget = record["automatic_fallback_count_budget"]
    used_count = record["automatic_fallback_count_used"]
    if budget != fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
        raise ValueError(
            "automatic_fallback_count_budget must be "
            f"{fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE} (one-fallback rule), "
            f"got {budget!r}"
        )
    if isinstance(used_count, bool) or not isinstance(used_count, int):
        raise ValueError("automatic_fallback_count_used must be an int")
    if not 0 <= used_count <= fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
        raise ValueError(
            f"automatic_fallback_count_used out of range: {used_count!r}"
        )
    retry = record["transport_retry_count"]
    if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
        raise ValueError(
            f"transport_retry_count must be a non-negative int, got {retry!r}"
        )

    # --- candidates 一致性 ---
    contract_candidates = record["contract_candidates"]
    paid_candidates = record["paid_candidates"]
    if not isinstance(contract_candidates, list) or not all(
        isinstance(item, str) and item.strip()
        for item in contract_candidates
    ):
        raise ValueError("contract_candidates must be a list of non-empty str")
    if contract_candidates != sorted(set(contract_candidates)):
        raise ValueError("contract_candidates must be unique and sorted")
    if not isinstance(paid_candidates, list) or not paid_candidates or not all(
        isinstance(item, str) and item.strip() for item in paid_candidates
    ):
        raise ValueError(
            "paid_candidates must be a non-empty list of non-empty str"
        )
    if paid_candidates != sorted(set(paid_candidates)):
        raise ValueError("paid_candidates must be unique and sorted")
    if not set(paid_candidates).issubset(set(contract_candidates)):
        raise ValueError(
            "paid_candidates must be a subset of contract_candidates "
            "(only already-qualified candidates may reach the Cost Gate)"
        )
    paid_candidate = record["paid_candidate"]
    if paid_candidate not in paid_candidates:
        raise ValueError(
            "paid_candidate must be one of paid_candidates (the "
            "deterministically selected proposed paid candidate)"
        )
    if (
        paid_candidate_model,
        paid_candidate_provider,
    ) != _split_key(paid_candidate):
        raise ValueError(
            "paid_candidate_model/provider must equal the paid_candidate "
            "key split (model@provider)"
        )
    if (
        record["original_model"],
        record["original_provider"],
    ) == (paid_candidate_model, paid_candidate_provider):
        raise ValueError(
            "paid candidate must be distinct from the failed original "
            "model/provider (same-model recovery is the retry layer, not "
            "paid escalation)"
        )

    # --- 字符串 / 列表字段 ---
    original_model = record["original_model"]
    final_model = record["final_actual_model"]
    if not (isinstance(original_model, str) and original_model.strip()):
        raise ValueError("original_model must be a non-empty string")
    if not (isinstance(final_model, str) and final_model.strip()):
        raise ValueError("final_actual_model must be a non-empty string")
    for key in ("original_provider", "final_actual_provider"):
        value = record[key]
        if value is not None and not (isinstance(value, str) and value.strip()):
            raise ValueError(f"{key} must be a non-empty string or None")
    evidence = record["no_silent_paid_evidence"]
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(item, str) and item.strip() for item in evidence
    ):
        raise ValueError(
            "no_silent_paid_evidence must be a non-empty list of str"
        )
    notes = record["notes"]
    if not isinstance(notes, list) or not all(
        isinstance(item, str) for item in notes
    ):
        raise ValueError("notes must be a list of str")
    for key in ("task_id", "stage_agent", "trigger", "risk_source"):
        if not (isinstance(record[key], str) and record[key].strip()):
            raise ValueError(f"{key} must be a non-empty string")
    if not (isinstance(record["generated_at"], str) and record["generated_at"]):
        raise ValueError("generated_at must be a non-empty string")
    tev = record["trigger_evidence"]
    if not isinstance(tev, list) or not all(isinstance(item, str) for item in tev):
        raise ValueError("trigger_evidence must be a list of str")


# ---------------------------------------------------------------------------
# 持久化（原子写；同目录 tmp + os.replace，与 A3/A4/A5 既有 artifact 同约定）
# ---------------------------------------------------------------------------


def save_paid_gate(output_dir: Path | str, record: dict) -> Path:
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


def load_paid_gate(output_dir: Path | str) -> dict | None:
    path = Path(output_dir) / ARTIFACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None
