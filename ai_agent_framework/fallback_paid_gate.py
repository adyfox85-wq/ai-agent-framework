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
     （model/provider scope 完整性）**+ A0 record 的 required_scope 精确等于
     canonical expected scope（``cost_guard.scope_string(task_id, stage, model,
     provider)``——FIX-002：exact task/stage/model/provider scope；任何
     scope mismatch / malformed scope 证据 → FAIL_CLOSED，绝不 AUTHORIZED）**
     → gate ``AUTHORIZED``（exact task-scoped authorization 已由 A0 在其准入
     边界按既有一次性语义 claim；本层如实转述 A0 的 authorization_present /
     matched / consumed 字段）；
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
final actual == original、explicit no-silent-paid-execution evidence、
``source_guard_record``（raw/source A0 record 保真快照——Requirement 2/6：
malformed/contradictory/unknown A0 证据完整可观察，但 raw 字段绝不覆盖
normalized authoritative 语义；FAIL_CLOSED 的 normalized flags 恒 False、
in-scope ALLOWED_AUTHORIZED_PAID token 不进入 normalized guard_decision——
audit record 永远内部自洽、validator-valid、可持久化，Requirement 3/5/7）——
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

# A0 Paid Guard decision tokens（validator whitelist + FAIL_CLOSED echo 共用；
# 未知 token 永不进入 normalized guard_decision 字段）
_A0_GUARD_DECISIONS = (
    cg.DECISION_ALLOWED_FREE,
    cg.DECISION_ALLOWED_AUTHORIZED_PAID,
    cg.DECISION_BLOCKED_COST_APPROVAL,
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
    "source_guard_record",
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


def _safe_str_list(value: object) -> list[str]:
    """只保留 str 元素。A0 notes 的畸形项（非 list / 非 str）不进入 audit
    record —— validator 的 ``notes`` 不变量要求全 str；原始内容仍完整保留在
    ``source_guard_record``，不因 echo 使 authoritative record 非法。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _echo_optional_str(value: object) -> str | None:
    """normalized echo：只接受非空 str（validator 类型不变量）。其余值
    （None / 空串 / 非 str）→ None；原始值保留在 ``source_guard_record``。"""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _fail_closed_fields(
    guard_record: dict,
    candidate_model: str,
    candidate_provider: str | None,
) -> dict:
    """parsed A0 record 的 FAIL_CLOSED normalized guard 字段（Requirement 2/4/5）。

    - authorization_* 恒 False —— raw A0 flags 绝不覆盖 normalized fail-closed
      语义（matched=True 与 FAIL_CLOSED 互斥，validator 拒绝自相矛盾的 record）；
    - ``guard_decision`` 只在 token ∈ A0 whitelist **且**不隐含「本候选已被
      授权」时 echo：in-scope 的 ``ALLOWED_AUTHORIZED_PAID`` 与 FAIL_CLOSED 互斥
      （validator 不变量：exact-scope authorized ⟹ AUTHORIZED），故 → None；
      raw token 原文完整保留在 ``source_guard_record``；
    - guard_model/provider/cost_class/required_scope 只做类型安全 echo（畸形值
      → None，原文在 source），保证组装出的 authoritative record 永远
      validator-valid、可持久化。
    """
    guard_model = guard_record["model"]
    guard_provider = guard_record["provider"]
    in_scope = (
        guard_model == candidate_model and guard_provider == candidate_provider
    )
    decision = guard_record["decision"]
    token: str | None = None
    if isinstance(decision, str) and decision in _A0_GUARD_DECISIONS:
        if not (in_scope and decision == cg.DECISION_ALLOWED_AUTHORIZED_PAID):
            token = decision
    return {
        "authorization_present": False,
        "authorization_matched": False,
        "authorization_consumed": False,
        "guard_decision": token,
        "guard_cost_class": _echo_optional_str(guard_record["cost_class"]),
        "guard_model": _echo_optional_str(guard_model),
        "guard_provider": _echo_optional_str(guard_provider),
        "required_scope": _echo_optional_str(guard_record["required_scope"]),
        "notes": [],
    }


# ---------------------------------------------------------------------------
# A0 guard record → Cost Gate 解释（纯函数；确定性；fail closed）
# ---------------------------------------------------------------------------


def fail_closed_interpretation(
    reason: str,
    source_guard_record: dict | None = None,
) -> dict:
    """guard 求值未发生/失败时的 FAIL_CLOSED 解释（guard 字段全 None）。

    ``reason`` 必须是非空显式证据（guard 抛异常 / env overlay 失败等——
    malformed/unknown authorization state → fail closed，Requirement 3）。
    ``source_guard_record``：求值失败前得到的 raw A0 record 快照（可为 None；
    非 dict 一律 None——raw 原文只在 dict 形状下保真，Requirement 6）。
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
        "source_guard_record": source_guard_record,
    }


def _parsed_fail_closed(
    reason: str,
    guard_record: dict,
    candidate_model: str,
    candidate_provider: str | None,
    source_guard_record: dict,
) -> dict:
    """parsed（必需字段齐全）但语义矛盾/未知的 A0 record → FAIL_CLOSED
    normalized 解释（Requirement 3/5）：gate_decision=FAIL_CLOSED、授权 flags
    恒 False、guard 字段经 ``_fail_closed_fields`` 类型安全 echo、raw A0
    证据完整保留于 ``source_guard_record``（Requirement 2/4/6 —— raw
    矛盾证据可观察，但绝不覆盖 normalized 字段）。"""
    fields = _fail_closed_fields(
        guard_record, candidate_model, candidate_provider
    )
    return {
        "gate_decision": GATE_DECISION_FAIL_CLOSED,
        "gate_reason": reason,
        **fields,
        "notes": [reason] + _safe_str_list(guard_record.get("notes")),
        "source_guard_record": source_guard_record,
    }


def interpret_guard(
    guard_record: dict | None,
    model: str,
    provider: str | None,
    *,
    task_id: str,
    stage: str,
) -> dict:
    """把 A0 Paid Guard record 解释为 Cost Gate 状态（确定性、fail closed）。

    ``task_id`` / ``stage`` 是本 Cost Gate 的 expected 授权 scope 上下文
    （= 当前 Hermes executor stage 的 task/stage——与 A0 ``cost_guard.evaluate``
    求值所用参数同源；runtime 层以同一 task_id/stage_agent 调用本函数）。
    ``model`` / ``provider`` 是 proposed paid candidate。canonical expected
    scope = ``cost_guard.scope_string(task_id, stage, model, provider)``
    （既有 A0 Paid Guard scope 权威——FIX-002 复用同一 scope 格式与 authority，
    不创建第二套 scope/授权机制）。

    返回 dict：{gate_decision, gate_reason, authorization_present,
    authorization_matched, authorization_consumed, guard_decision,
    guard_cost_class, guard_model, guard_provider, required_scope, notes,
    source_guard_record}。**normalized 字段与 raw/source 证据分层**：AUTHORIZED /
    BLOCKED / FAIL_CLOSED 字段是自洽的 authoritative 语义；原始 A0 record 的
    保真快照（含可自相矛盾的 raw flags / token / scope）独立存放在
    ``source_guard_record``，任何 FAIL_CLOSED 路径都绝不把 raw 授权 flags /
    in-scope 的 ALLOWED_AUTHORIZED_PAID token 回写到 normalized 字段
    （否则组装出的 authoritative audit record 自相矛盾、validator 拒绝、
    无法持久化——Requirement 2/3/4/7）。

    映射（Requirement 3/4/5）：
    - guard record 缺失 / malformed（缺必需字段 / 非 dict）→ FAIL_CLOSED；
    - guard 解析的 effective model/provider != candidate model/provider →
      FAIL_CLOSED（scope integrity：A0 求值的不是本 candidate，授权状态无法
      归属——绝不凭错误 scope 的 record 放行/记录，Requirement 4 零削弱）；
    - ``ALLOWED_AUTHORIZED_PAID``（且 A0 三个 authorization flags 全 True）→
      **必须**同时满足 required_scope 精确等于 canonical expected scope
      ``scope_string(task_id, stage, model, provider)`` 才 → AUTHORIZED
      （exact task/stage/model/provider-scoped authorization；A0 已在其准入
      边界按既有一次性语义 claim——本层如实转述 consumed 状态）；flags 不齐 /
      required_scope 畸形（None / 非 str / 空）/ required_scope ≠ canonical
      expected scope（wrong task / wrong stage / wrong model / wrong provider
      任一维度的 scope mismatch——FIX-002 Codex blocker）→ FAIL_CLOSED
      （绝不被授权：scope mismatch 或 malformed evidence 永不映射 AUTHORIZED）；
    - ``BLOCKED_COST_APPROVAL`` → BLOCKED（absent / mismatch /
      replay-rejected；flags + guard notes 给出原因）；matched=True 的 BLOCKED
      record = malformed → FAIL_CLOSED；
    - ``ALLOWED_FREE`` → FAIL_CLOSED（registry 视为 paid 的候选被 A0 权威
      解析为 FREE = 冲突成本视图——不授 paid 资格、不静默放行）；
    - 其他未知 decision token → FAIL_CLOSED。
    """
    # ---- raw/source A0 evidence（Requirement 2/6：保真快照，允许自相矛盾；
    #      永不覆盖下方 normalized 字段）----
    source_guard_record = (
        guard_record if isinstance(guard_record, dict) else None
    )

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
        return fail_closed_interpretation(
            reason, source_guard_record=source_guard_record
        )

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
        return _parsed_fail_closed(
            reason, guard_record, model, provider, source_guard_record
        )

    present = guard_record["authorization_present"]
    matched = guard_record["authorization_matched"]
    consumed = guard_record["authorization_consumed"]
    if not all(isinstance(v, bool) for v in (present, matched, consumed)):
        reason = (
            "malformed A0 Paid Guard record: authorization_present/matched/"
            "consumed must be bools — fail closed (unknown authorization "
            "state; no paid model invoked)"
        )
        return fail_closed_interpretation(
            reason, source_guard_record=source_guard_record
        )

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
            return _parsed_fail_closed(
                reason, guard_record, model, provider, source_guard_record
            )
        scope = guard_record["required_scope"]
        if not (isinstance(scope, str) and scope.strip()):
            reason = (
                "malformed A0 Paid Guard record: decision "
                "ALLOWED_AUTHORIZED_PAID with authorization_present/matched/"
                "consumed all true requires a non-empty string required_scope "
                f"(exact task/stage/model/provider scope evidence), got "
                f"{scope!r} — exact-scope authorization cannot be recorded; "
                "fail closed (no paid model invoked)"
            )
            return _parsed_fail_closed(
                reason, guard_record, model, provider, source_guard_record
            )
        # FIX-002（Codex 唯一 blocker）：required_scope 必须**精确等于**
        # canonical expected scope（既有 A0 scope authority：
        # cost_guard.scope_string(task_id, stage, model, provider)——单一 scope
        # 格式，不建第二套）。wrong task / wrong stage / wrong model / wrong
        # provider 任一维度的 scope mismatch 都是 contradictory evidence →
        # FAIL_CLOSED，绝不映射 AUTHORIZED（Requirement 4/5）。
        expected_scope = cg.scope_string(task_id, stage, model, provider)
        if scope != expected_scope:
            reason = (
                "scope mismatch: A0 Paid Guard record required_scope "
                f"{scope!r} does not exactly equal the canonical expected "
                f"scope {expected_scope!r} for the current task/stage/model/"
                f"provider ({task_id!r}/{stage!r}/{model!r}/{provider!r}) — "
                "an ALLOWED_AUTHORIZED_PAID result claimed for a different "
                "task/stage/model/provider scope cannot authorize this paid "
                "escalation; fail closed (exact task/stage/model/provider "
                "scope matching unmodified; no paid escalation state "
                "assigned, no paid model invoked)"
            )
            return _parsed_fail_closed(
                reason, guard_record, model, provider, source_guard_record
            )
        return {
            "gate_decision": GATE_DECISION_AUTHORIZED,
            "gate_reason": (
                "exact task-scoped AAF_COST_AUTH authorization present and "
                "atomically claimed at the A0 Paid Guard admission boundary "
                f"(decision={decision!r}, required_scope={scope!r} exactly "
                f"equals the canonical expected scope "
                f"{expected_scope!r}) — gate decision AUTHORIZED records "
                "ready-for-paid-invocation ELIGIBILITY for a future paid "
                "invocation task only; NO paid model was or will be invoked "
                "by this Cost Gate (fallback_attempted/used stay false)"
            ),
            "authorization_present": present,
            "authorization_matched": matched,
            "authorization_consumed": consumed,
            "guard_decision": decision,
            "guard_cost_class": _echo_optional_str(guard_record["cost_class"]),
            "guard_model": guard_model,
            "guard_provider": guard_provider,
            "required_scope": scope,
            "notes": _safe_str_list(guard_record.get("notes")),
            "source_guard_record": source_guard_record,
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
            return _parsed_fail_closed(
                reason, guard_record, model, provider, source_guard_record
            )
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
                f"{_echo_optional_str(guard_record['required_scope'])!r}) — "
                "BLOCKED (fail closed; no paid model invoked; no weakening "
                "of exact scope matching)"
            )
        return {
            "gate_decision": GATE_DECISION_BLOCKED,
            "gate_reason": block_reason,
            "authorization_present": present,
            "authorization_matched": matched,
            "authorization_consumed": consumed,
            "guard_decision": decision,
            "guard_cost_class": _echo_optional_str(guard_record["cost_class"]),
            "guard_model": guard_model,
            "guard_provider": guard_provider,
            "required_scope": _echo_optional_str(
                guard_record["required_scope"]
            ),
            "notes": _safe_str_list(guard_record.get("notes")),
            "source_guard_record": source_guard_record,
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
        return _parsed_fail_closed(
            reason, guard_record, model, provider, source_guard_record
        )
    reason = (
        f"unknown A0 Paid Guard decision token {decision!r} — malformed/"
        "unknown authorization state; fail closed (no paid model invoked)"
    )
    return _parsed_fail_closed(
        reason, guard_record, model, provider, source_guard_record
    )


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
    （A0 record 的权威解释）；normalized audit 字段自洽地转述 A0 语义
    （AUTHORIZED / BLOCKED 如实转述 authorization flags 与 guard decision；
    FAIL_CLOSED 恒为 fail-closed normalized 语义——raw 矛盾 flags/token 不进
    normalized 字段），raw A0 record 原文完整存入 ``source_guard_record``
    （Requirement 2/4/6：raw 证据可观察且永不使 authoritative record 矛盾）。
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
        "source_guard_record": interpretation["source_guard_record"],
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
      ALLOWED_AUTHORIZED_PAID + exact task/stage/model/provider candidate
      scope（guard model/provider == candidate）**+ required_scope 精确等于
      canonical expected scope（cost_guard.scope_string(task_id, stage_agent,
      paid_candidate_model, paid_candidate_provider)——FIX-002）** + 三 flags
      True；matched=True ⟹ AUTHORIZED；BLOCKED ⟹ A0 BLOCKED_COST_APPROVAL）；
    - candidates 一致性（paid ⊆ contract；paid_candidate ∈ paid；
      model/provider == key 拆分）；
    - ``source_guard_record``（raw/source A0 record 保真快照）必须为
      dict/None 且 JSON 可序列化——raw 证据允许与 normalized 语义矛盾
      （那正是 FAIL_CLOSED 的可审计证据），但绝不允许因 raw 形状而使
      authoritative audit 无法持久化。
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
    if (
        guard_decision is not None
        and guard_decision not in _A0_GUARD_DECISIONS
    ):
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

    # --- raw/source A0 evidence（Requirement 2/4/6：raw 快照独立于 normalized
    #      字段——允许与 normalized 语义矛盾（那正是 FAIL_CLOSED 的可审计证据），
    #      但必须 dict/None 且 JSON 可序列化：authoritative record 绝不能因
    #      source 证据形状而无法持久化，Requirement 3/7）---
    source = record["source_guard_record"]
    if source is not None and not isinstance(source, dict):
        raise ValueError(
            "source_guard_record must be a dict or null (raw/source A0 "
            f"evidence snapshot), got {type(source).__name__}"
        )
    if source is not None:
        try:
            json.dumps(source, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "source_guard_record must be JSON-serializable so the "
                "authoritative audit always persists even when the raw A0 "
                f"evidence is contradictory: {exc}"
            ) from exc

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
    # FIX-002（Codex 唯一 blocker）：canonical expected scope 由 authoritative
    # record 自身的 task_id / stage_agent / paid_candidate_model / provider 重建
    # （既有 A0 scope authority = cost_guard.scope_string——单一 scope 格式，
    # 不建第二套）。required_scope 必须精确等于它——手造 AUTHORIZED record（或
    # required_scope 指向其他 task/stage/model/provider 的 record）被 validator
    # 独立拒绝（Requirement 8），不改写 interpret 层已 FAIL_CLOSED 的语义。
    _tid = record["task_id"]
    _stag = record["stage_agent"]
    if all(
        isinstance(v, str)
        for v in (_tid, _stag, paid_candidate_model, paid_candidate_provider)
    ):
        expected_scope = cg.scope_string(
            _tid, _stag, paid_candidate_model, paid_candidate_provider
        )
    else:
        expected_scope = None  # 非 str scope 组件 → 无法重建 canonical → 不满足
    if gate_decision == GATE_DECISION_AUTHORIZED:
        if not (
            guard_scope_ok
            and present is True
            and matched is True
            and consumed is True
            and record["guard_model"] is not None
            and record["required_scope"]
            and expected_scope is not None
            and record["required_scope"] == expected_scope
        ):
            raise ValueError(
                "gate_decision=AUTHORIZED requires an exact A0 Paid Guard "
                "ALLOWED_AUTHORIZED_PAID result for the proposed paid "
                "candidate's exact task/stage/model/provider scope with "
                "required_scope exactly equal to the canonical expected "
                f"scope {expected_scope!r} and "
                "authorization_present/matched/consumed all true — "
                "contradictory or out-of-scope record fails closed"
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
