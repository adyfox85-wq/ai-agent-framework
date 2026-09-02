"""AAF v0.5 A5 — Fallback Decision & Audit Contract（foundation only）。

TASK: AAF-v0.5-A5-FALLBACK-CONTRACT-001
在 A5 正式 scope（bounded, auditable fallback / escalation / Cost Gate
foundation，见 PROJECT_STATE.md v0.5「A5 Scope Formalization」块与
AAF-v0.5-A5-SCOPE-FORMALIZATION-001-REPORT.md）内交付**唯一权威的
fallback decision contract**：让框架能够统一、可审计地描述「是否出现可触发
model-level fallback 的失败」以及该失败对应的 fallback 决策——**本任务不执行
第二模型、不实现 paid escalation、不接入任何 runtime 执行路径**。

设计纪律（与既有权威的关系——**不创建平行系统**）：
1. 候选资格判定**复用** A2 selector（``shadow_routing.select_shadow_candidate``，
   其内部消费 A1 registry/risk 契约：capability → qualification →
   executor main-scope 闸），本模块只在其 ``eligible`` 结果之上做 fallback
   层判定；不复制任何 routing / cost / qualification 判断。
2. cost / authorization 维度**不做本层判断**：涉及 free→paid / paid 恢复的
   场景必须由调用方（未来 runtime 单元，按既有 A0 Paid Guard / Cost Guard
   事实）分类为 FAILURE_PAID_ESCALATION_REQUIRED 或
   FAILURE_COST_AUTHORIZATION_BLOCKED——这两类**永不**产出 fallback_eligible
   （free→paid 不得静默；不建第二套付费授权系统）。
3. 本 foundation 单元**零执行权威**：fallback_attempted / fallback_used
   恒 False（fixed semantic + validate fail-closed，与 active_routing 的
   fallback_attempted 恒 False 纪律同型）；任何声称已尝试/已使用 fallback
   的 record 都是非法 record。
4. transport retry（RW-027 层，同模型同 args）与 model-level fallback
   分层分离：``transport_retry_count`` 独立记录、**不计入** one-fallback
   预算、绝不翻转 attempted/used。
5. 纯逻辑模块：无 I/O、无网络、无 LLM、无 subprocess；决策确定性、可测试。

One-fallback / no-chain rule（REQUIRED_BEFORE_A5_CLOSE #2/#3）：
- 每 affected stage 的 automatic model-level fallback 上限 =
  ``MAX_AUTOMATIC_FALLBACKS_PER_STAGE``（= 1）；
- ``automatic_fallback_count_used`` = 该 stage 在本决策**之前**已消耗的
  model-level fallback 数（0 或 1）；== 1 → 任何新决策都是
  fallback_not_eligible（无 A→B→C chain、无 loop）；> 1 → malformed →
  ValueError（fail closed）。
- same-model 恢复 = transport retry 层（RW-027），不是 fallback：候选
  枚举排除 original model key。

Taxonomy（bounded failure classes——Req 2 五类 + A5 scope 文档 minimum
classes 的其余两类，全部显式归类）：
- FAILURE_INVOCATION（model/provider invocation failure）
- FAILURE_UNAVAILABLE（unavailable/unsupported model or provider）
- FAILURE_CAPABILITY_QUALIFICATION（capability/qualification failure
  discovered at execution boundary）
- FAILURE_QUALITY_VALIDATION（quality/validation failure）
- FAILURE_TRANSPORT_RUNTIME（transport/runtime failure——RW-027 层分类；
  retry 层先处理；模型级 fallback 判定仍可评估但同一预算规则适用）
- FAILURE_COST_AUTHORIZATION_BLOCKED（cost/authorization blocked
  condition——A0 Paid Guard 前置阻断，非模型执行失败 → 非 fallback 上下文）
- FAILURE_PAID_ESCALATION_REQUIRED（paid escalation required——恢复只能
  经既有 Paid Guard / Cost Guard authority，绝不自动）
- FAILURE_FRAMEWORK_INPUT_CONFIG（non-fallback-eligible framework/input/
  configuration failure——诚实 FRAMEWORK_ERROR，非 fallback 上下文）

Decision matrix（decision token 推导，确定性）：
- trigger-capable 类（INVOCATION / UNAVAILABLE / CAPABILITY_QUALIFICATION /
  QUALITY_VALIDATION / TRANSPORT_RUNTIME）：
  * 预算已耗尽（count_used == 1）→ fallback_not_eligible
    （AUTOMATIC_FALLBACK_BUDGET_EXHAUSTED——no chain/loop）
  * 无合格其他候选 → fallback_not_eligible（NO_QUALIFIED_FALLBACK_CANDIDATE）
  * 存在合格其他候选 → **fallback_eligible**（有界、可审计；本 foundation
    不执行——attempted/used 恒 False）
- FAILURE_PAID_ESCALATION_REQUIRED → **paid_escalation_required**
  （fallback_eligible=False；authorization_outcome=none——foundation 不
  运行任何授权流程；未来 paid 路径必须消费 A0 authority，fail closed）
- FAILURE_COST_AUTHORIZATION_BLOCKED → **blocked_fail_closed**
  （A0 前置阻断 authority 持有；非模型执行失败 → 无 fallback 上下文）
- FAILURE_FRAMEWORK_INPUT_CONFIG → **blocked_fail_closed**
  （诚实框架错误；非 fallback 上下文）

Audit record（machine-readable；validate fail-closed）：stage/role/risk、
original model/provider、failure class/trigger、fallback eligibility、
fallback candidate(s)、fallback_attempted、fallback_used、
paid_escalation_required、authorization outcome、final actual model/provider、
explicit no-silent-fallback evidence——字段与语义见 _REQUIRED_KEYS 与
``validate_fallback_record``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .model_registry import RegistryEntry, canonical_key
from .risk_contract import RISK_CLASSES
from .shadow_routing import STAGE_ROLES, select_shadow_candidate

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DECISION_KIND = "fallback_decision"

# 唯一权威说明（写入每个 record；与 A3 active_routing / A4 workbuddy_routing
# 的 authority 声明同型——指明本 artifact 的权威来源与复用纪律）
_AUTHORITY = (
    "fallback_contract.py (A5 fallback decision contract, TASK: "
    "AAF-v0.5-A5-FALLBACK-CONTRACT-001): one authoritative A5 fallback "
    "decision/audit contract; candidate eligibility reuses the A2 selector "
    "(shadow_routing.select_shadow_candidate -> A1 model_registry/risk_contract "
    "gates) — no parallel routing/cost/qualification judgment system; this "
    "foundation unit has no execution authority (fallback_attempted/used "
    "always false); transport retries (RW-027 layer) are never counted as "
    "model-level fallback"
)

# ---------------------------------------------------------------------------
# Bounded failure taxonomy（Req 2 五类 + A5 scope 文档 minimum classes 余项）
# ---------------------------------------------------------------------------

# model/provider invocation failure（Req 2 类 1）
FAILURE_INVOCATION = "invocation_failure"
# unavailable/unsupported model or provider（Req 2 类 2）
FAILURE_UNAVAILABLE = "unavailable_unsupported_model_provider"
# capability/qualification failure discovered at execution boundary（Req 2 类 3）
FAILURE_CAPABILITY_QUALIFICATION = "capability_qualification_failure"
# quality/validation failure（A5 scope minimum classes）
FAILURE_QUALITY_VALIDATION = "quality_validation_failure"
# transport/runtime failure（A5 scope minimum classes；RW-027 retry 层先处理）
FAILURE_TRANSPORT_RUNTIME = "transport_runtime_failure"
# cost/authorization blocked condition（Req 2 类 4；A0 Paid Guard 前置阻断）
FAILURE_COST_AUTHORIZATION_BLOCKED = "cost_authorization_blocked"
# paid escalation required（A5 scope minimum classes；恢复必经 A0 authority）
FAILURE_PAID_ESCALATION_REQUIRED = "paid_escalation_required"
# non-fallback-eligible framework/input/configuration failure（Req 2 类 5）
FAILURE_FRAMEWORK_INPUT_CONFIG = "framework_input_config_failure"

FAILURE_CLASSES = (
    FAILURE_INVOCATION,
    FAILURE_UNAVAILABLE,
    FAILURE_CAPABILITY_QUALIFICATION,
    FAILURE_QUALITY_VALIDATION,
    FAILURE_TRANSPORT_RUNTIME,
    FAILURE_COST_AUTHORIZATION_BLOCKED,
    FAILURE_PAID_ESCALATION_REQUIRED,
    FAILURE_FRAMEWORK_INPUT_CONFIG,
)

# 规范 label（机器可读 token 的人类可读规范名；与 requirement 文本对齐）
FAILURE_LABELS: dict[str, str] = {
    FAILURE_INVOCATION: "model/provider invocation failure",
    FAILURE_UNAVAILABLE: "unavailable/unsupported model or provider",
    FAILURE_CAPABILITY_QUALIFICATION: (
        "capability/qualification failure at execution boundary"
    ),
    FAILURE_QUALITY_VALIDATION: "quality/validation failure",
    FAILURE_TRANSPORT_RUNTIME: "transport/runtime failure",
    FAILURE_COST_AUTHORIZATION_BLOCKED: "cost/authorization blocked condition",
    FAILURE_PAID_ESCALATION_REQUIRED: "paid escalation required",
    FAILURE_FRAMEWORK_INPUT_CONFIG: (
        "non-fallback-eligible framework/input/configuration failure"
    ),
}

# 模型级失败类（可评估 fallback 的类；其余 = 非 fallback 上下文 / 必经
# A0 authority 的类）
TRIGGER_CAPABLE_CLASSES = frozenset(
    (
        FAILURE_INVOCATION,
        FAILURE_UNAVAILABLE,
        FAILURE_CAPABILITY_QUALIFICATION,
        FAILURE_QUALITY_VALIDATION,
        FAILURE_TRANSPORT_RUNTIME,
    )
)

# 非 fallback 上下文 → decision = blocked_fail_closed
BLOCKED_CLASSES = frozenset(
    (
        FAILURE_COST_AUTHORIZATION_BLOCKED,
        FAILURE_FRAMEWORK_INPUT_CONFIG,
    )
)

# paid 恢复类 → decision = paid_escalation_required（never automatic）
PAID_ESCALATION_CLASSES = frozenset((FAILURE_PAID_ESCALATION_REQUIRED,))

# ---------------------------------------------------------------------------
# Decision tokens（Req 3：四种输出至少可区分）
# ---------------------------------------------------------------------------

DECISION_FALLBACK_ELIGIBLE = "fallback_eligible"
DECISION_FALLBACK_NOT_ELIGIBLE = "fallback_not_eligible"
DECISION_PAID_ESCALATION_REQUIRED = "paid_escalation_required"
DECISION_BLOCKED_FAIL_CLOSED = "blocked_fail_closed"

DECISIONS = (
    DECISION_FALLBACK_ELIGIBLE,
    DECISION_FALLBACK_NOT_ELIGIBLE,
    DECISION_PAID_ESCALATION_REQUIRED,
    DECISION_BLOCKED_FAIL_CLOSED,
)

# ---------------------------------------------------------------------------
# One-fallback rule（REQUIRED_BEFORE_A5_CLOSE #2/#3）
# ---------------------------------------------------------------------------

# 每 affected stage 最多 1 次 automatic model-level fallback（契约常量；
# record 校验强制 budget == 本常量）
MAX_AUTOMATIC_FALLBACKS_PER_STAGE = 1

# ---------------------------------------------------------------------------
# Decision reason tokens（显式、可审计；no-fallback 时必须如实给出）
# ---------------------------------------------------------------------------

REASON_NO_QUALIFIED_CANDIDATE = "NO_QUALIFIED_FALLBACK_CANDIDATE"
REASON_BUDGET_EXHAUSTED = "AUTOMATIC_FALLBACK_BUDGET_EXHAUSTED"
REASON_ONLY_SAME_MODEL = "ONLY_SAME_MODEL_RECOVERY_IS_RETRY_NOT_FALLBACK"
REASON_PAID_NEVER_AUTOMATIC = "PAID_ESCALATION_NEVER_AUTOMATIC"
REASON_NON_FALLBACK_CONTEXT = "NON_FALLBACK_CONTEXT_FRAMEWORK_ERROR"
REASON_COST_AUTHORITY_OWNS = "COST_AUTHORIZATION_BLOCKED_A0_OWNS"

# ---------------------------------------------------------------------------
# Authorization outcome（audit 字段词汇）
# ---------------------------------------------------------------------------

# foundation 单元不运行任何授权流程；任何 future paid escalation 必须消费
# 既有 task-scoped Paid Guard / Cost Guard（A0）authority——本层绝不产生
# authorized/denied/consumed 值（fail closed）。
AUTH_OUTCOME_NONE = "none"

# ---------------------------------------------------------------------------
# Audit schema（Req 5 全部字段；validate fail-closed）
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
    "fallback_candidates",
    "fallback_candidate",
    "fallback_eligible",
    "decision",
    "decision_reason",
    "fallback_attempted",
    "fallback_used",
    "paid_escalation_required",
    "authorization_outcome",
    "final_actual_model",
    "final_actual_provider",
    "no_silent_fallback_evidence",
    "notes",
    "generated_at",
)

# foundation fixed semantic：本单元无执行权威（与 active_routing 同型纪律）
_FALLBACK_ATTEMPTED = False
_FALLBACK_USED = False


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_inputs(
    *,
    failure_class: str,
    trigger: str,
    task_id: str,
    stage_agent: str,
    role: str,
    risk_class: str,
    risk_source: str,
    original_model: str,
    original_provider: str | None,
    registry: Any,
    transport_retry_count: int,
    automatic_fallback_count_used: int,
    trigger_evidence: Any,
) -> None:
    """决策输入 fail-closed 校验（Req 7：unknown/malformed → ValueError）。"""
    if failure_class not in FAILURE_CLASSES:
        raise ValueError(
            f"unknown failure class: {failure_class!r} "
            f"(allowed: {FAILURE_CLASSES})"
        )
    for name, value in (
        ("trigger", trigger),
        ("task_id", task_id),
        ("stage_agent", stage_agent),
        ("risk_source", risk_source),
    ):
        if not (isinstance(value, str) and value.strip()):
            raise ValueError(f"{name} must be a non-empty string")
    if role not in STAGE_ROLES:
        raise ValueError(f"unknown role: {role!r} (allowed: {STAGE_ROLES})")
    if risk_class not in RISK_CLASSES:
        raise ValueError(
            f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})"
        )
    if not (isinstance(original_model, str) and original_model.strip()):
        raise ValueError("original_model must be a non-empty string")
    if original_provider is not None and not (
        isinstance(original_provider, str) and original_provider.strip()
    ):
        raise ValueError("original_provider must be a non-empty string or None")
    if not isinstance(registry, dict):
        raise ValueError(
            f"registry must be a dict of RegistryEntry, got {type(registry).__name__}"
        )
    for name, value in (
        ("transport_retry_count", transport_retry_count),
        ("automatic_fallback_count_used", automatic_fallback_count_used),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    if transport_retry_count < 0:
        raise ValueError(
            f"transport_retry_count must be >= 0, got {transport_retry_count!r}"
        )
    if not 0 <= automatic_fallback_count_used <= MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
        raise ValueError(
            "automatic_fallback_count_used must be within "
            f"[0, {MAX_AUTOMATIC_FALLBACKS_PER_STAGE}] (one-fallback rule; "
            f"no chain/loop), got {automatic_fallback_count_used!r}"
        )
    if trigger_evidence is not None:
        if not isinstance(trigger_evidence, (tuple, list)) or not all(
            isinstance(item, str) for item in trigger_evidence
        ):
            raise ValueError("trigger_evidence must be a tuple/list of str")
    # 其它字段类型在 record 组装前即时检查（fail closed）。


def decide_fallback(
    *,
    failure_class: str,
    trigger: str,
    task_id: str,
    stage_agent: str,
    role: str,
    risk_class: str,
    risk_source: str,
    original_model: str,
    original_provider: str | None = None,
    registry: dict[str, RegistryEntry],
    transport_retry_count: int = 0,
    automatic_fallback_count_used: int = 0,
    trigger_evidence: tuple[str, ...] = (),
) -> dict:
    """A5 fallback decision（foundation：只决策、不执行）。

    参数（全部必填/显式，fail closed）：
    - ``failure_class``：本模块 taxonomy 成员（模型级失败才可评估 fallback；
      paid/cost/框架类按决策矩阵归类）。
    - ``trigger``：非空、evidence-backed 的失败触发摘要。
    - ``task_id`` / ``stage_agent`` / ``role`` / ``risk_class`` /
      ``risk_source``：审计上下文（role ∈ STAGE_ROLES；risk_class ∈
      RISK_CLASSES——缺失/未知一律 ValueError）。
    - ``original_model`` / ``original_provider``：发生失败的模型身份（失败
      必然关联一个实际尝试的模型）。
    - ``registry``：A1 RegistryEntry dict（与 A2/A3 决策同源；候选资格由
      ``shadow_routing.select_shadow_candidate`` 复用判定——本模块不另建
      资格系统）。
    - ``transport_retry_count``：RW-027 层同模型 transport retry 次数
      （>= 0；**不计入** one-fallback 预算、不影响 attempted/used）。
    - ``automatic_fallback_count_used``：该 affected stage 在本决策前已
      消耗的 automatic model-level fallback 数（0 或 1；> 1 = malformed）。
    - ``trigger_evidence``：支撑 trigger 的证据引用（可选）。

    返回 machine-readable audit record（Req 5 全字段；可直接 JSON 落盘并
    经 ``validate_fallback_record`` 复核）。foundation 语义：decision 只
    描述「允许/不允许什么」，attempted/used 恒 False、无第二模型执行。
    """
    _validate_inputs(
        failure_class=failure_class,
        trigger=trigger,
        task_id=task_id,
        stage_agent=stage_agent,
        role=role,
        risk_class=risk_class,
        risk_source=risk_source,
        original_model=original_model,
        original_provider=original_provider,
        registry=registry,
        transport_retry_count=transport_retry_count,
        automatic_fallback_count_used=automatic_fallback_count_used,
        trigger_evidence=trigger_evidence,
    )
    trigger_evidence_t = tuple(trigger_evidence) if trigger_evidence else ()

    # 候选枚举：**复用** A2 selector（A1 capability/qualification/scope 闸），
    # 排除 original（same-model 恢复 = transport retry 层，不是 fallback）。
    decision = select_shadow_candidate(
        risk_class=risk_class,
        role=role,
        stage_agent=stage_agent,
        registry=registry,
    )
    original_key = canonical_key(original_model, original_provider)
    eligible = [key for key in decision.eligible if key != original_key]

    notes: list[str] = []
    if original_key in decision.eligible:
        notes.append(
            "same-model candidate excluded from fallback candidates: "
            "same-model recovery is the RW-027 transport-retry layer "
            "(same model, same args), never a model-level fallback"
        )
    if transport_retry_count > 0:
        notes.append(
            f"transport retry separation: {transport_retry_count} same-model "
            "transport retry(ies) at the RW-027 layer are NOT counted as "
            "model-level fallback and do not consume the one-fallback budget"
        )

    # --- 决策矩阵（确定性；见模块 docstring） ---
    fallback_eligible = False
    paid_escalation_required = False
    decision_reason: str | None = None

    if failure_class in PAID_ESCALATION_CLASSES:
        # paid 恢复：绝不自动；未来 paid 路径必须消费既有 A0 authority。
        decision_token = DECISION_PAID_ESCALATION_REQUIRED
        paid_escalation_required = True
        decision_reason = (
            f"{REASON_PAID_NEVER_AUTOMATIC}: failure classified as paid "
            "escalation required — recovery via a paid model is never "
            "automatic; any paid step must consume the existing task-scoped "
            "Paid Guard / Cost Guard (A0) authority (fail closed; no second "
            "paid-authorization system). No paid step was executed by this "
            "foundation unit."
        )
    elif failure_class in BLOCKED_CLASSES:
        decision_token = DECISION_BLOCKED_FAIL_CLOSED
        if failure_class == FAILURE_COST_AUTHORIZATION_BLOCKED:
            decision_reason = (
                f"{REASON_COST_AUTHORITY_OWNS}: cost/authorization blocked "
                "condition is owned by the A0 Paid Guard authority "
                "(pre-invocation fail-closed state, e.g. WAITING/"
                "COST_APPROVAL_REQUIRED) — no model-level execution failed, "
                "so there is no fallback context; no second paid-authorization "
                "system and no fallback-from-cost-block behavior is introduced"
            )
        else:
            decision_reason = (
                f"{REASON_NON_FALLBACK_CONTEXT}: non-fallback-eligible "
                "framework/input/configuration failure — honest "
                "FRAMEWORK_ERROR; never a model-level fallback trigger"
            )
    elif failure_class in TRIGGER_CAPABLE_CLASSES:
        if automatic_fallback_count_used >= MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
            decision_token = DECISION_FALLBACK_NOT_ELIGIBLE
            decision_reason = (
                f"{REASON_BUDGET_EXHAUSTED}: automatic model-level fallback "
                f"budget ({MAX_AUTOMATIC_FALLBACKS_PER_STAGE} per affected "
                "stage) already consumed — no fallback chain/loop permitted"
            )
        elif not eligible:
            if decision.eligible:
                decision_reason = (
                    f"{REASON_ONLY_SAME_MODEL}: the only qualified candidate "
                    "for this stage is the original model — same-model "
                    "recovery is the RW-027 transport-retry layer, not a "
                    "model-level fallback; fail closed with an explicit "
                    "no-fallback reason"
                )
            else:
                decision_reason = (
                    f"{REASON_NO_QUALIFIED_CANDIDATE}: no qualified candidate "
                    "exists for this stage/role/risk (A1/A2 gates: "
                    "capability/qualification/main-scope) — no safe fallback; "
                    "fail closed with an explicit no-fallback reason"
                )
            decision_token = DECISION_FALLBACK_NOT_ELIGIBLE
        else:
            decision_token = DECISION_FALLBACK_ELIGIBLE
            fallback_eligible = True
            decision_reason = None
            if len(eligible) > 1:
                notes.append(
                    "multiple qualified fallback candidates exist; candidate "
                    "selection among them is a future runtime unit's "
                    "responsibility (this foundation unit has no selection/"
                    "execution authority) — fallback_candidate records None"
                )
    else:  # pragma: no cover - 防御：taxonomy 已分区完备
        raise ValueError(
            f"failure class not partitioned in decision matrix: {failure_class!r}"
        )

    if len(eligible) == 1:
        fallback_candidate = eligible[0]
    else:
        fallback_candidate = None

    evidence = [
        "fallback_attempted=false: this foundation unit has no execution "
        "authority — no second model was or can be invoked by this contract",
        "fallback_used=false: no fallback model became the final actual model",
        f"final_actual_model == original_model == {original_model!r} and "
        "final_actual_provider == original_provider: no model/provider switch "
        "occurred",
        f"automatic_fallback_count_used={automatic_fallback_count_used} <= "
        f"budget {MAX_AUTOMATIC_FALLBACKS_PER_STAGE}: one-fallback rule "
        "bounded; no chain/loop possible (any later decision on an exhausted "
        "budget is fallback_not_eligible)",
    ]
    if transport_retry_count > 0:
        evidence.append(
            f"transport retries ({transport_retry_count}) are the RW-027 "
            "same-model retry layer and are never reported as model-level "
            "fallback (separate layer / separate audit field)"
        )
    if decision_token != DECISION_FALLBACK_ELIGIBLE:
        evidence.append(
            "decision is not fallback_eligible: no automatic fallback and no "
            "silent model switch is possible from this record"
        )
    else:
        evidence.append(
            "decision is fallback_eligible but nothing was executed: "
            "eligibility is a contract-level permission only, bounded by the "
            "one-fallback rule and audited via fallback_attempted/used=false"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "decision_kind": DECISION_KIND,
        "authority": _AUTHORITY,
        "authoritative": True,
        "task_id": task_id,
        "stage_agent": stage_agent,
        "role": role,
        "risk_class": risk_class,
        "risk_source": risk_source,
        "failure_class": failure_class,
        "failure_label": FAILURE_LABELS[failure_class],
        "trigger": trigger,
        "trigger_evidence": list(trigger_evidence_t),
        "original_model": original_model,
        "original_provider": original_provider,
        "transport_retry_count": transport_retry_count,
        "automatic_fallback_count_used": automatic_fallback_count_used,
        "automatic_fallback_count_budget": MAX_AUTOMATIC_FALLBACKS_PER_STAGE,
        "fallback_candidates": list(eligible),
        "fallback_candidate": fallback_candidate,
        "fallback_eligible": fallback_eligible,
        "decision": decision_token,
        "decision_reason": decision_reason,
        "fallback_attempted": _FALLBACK_ATTEMPTED,
        "fallback_used": _FALLBACK_USED,
        "paid_escalation_required": paid_escalation_required,
        "authorization_outcome": AUTH_OUTCOME_NONE,
        "final_actual_model": original_model,
        "final_actual_provider": original_provider,
        "no_silent_fallback_evidence": evidence,
        "notes": notes,
        "generated_at": _now_iso(),
    }


def validate_fallback_record(record: dict) -> None:
    """Audit record fail-closed 校验（Req 5/7：schema + 不变量）。

    任一违例 → ValueError（不返回部分有效状态）。foundation 不变量：
    attempted/used 必须 False（本单元无执行权威——任何 True 都是违规）；
    budget 必须 == MAX_AUTOMATIC_FALLBACKS_PER_STAGE；final actual ==
    original；decision 与 flags/candidates/failure_class 互洽。
    """
    if not isinstance(record, dict):
        raise ValueError(
            f"record must be a dict, got {type(record).__name__}"
        )
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

    failure_class = record["failure_class"]
    if failure_class not in FAILURE_CLASSES:
        raise ValueError(
            f"unknown failure_class: {failure_class!r} (allowed: {FAILURE_CLASSES})"
        )
    if record["failure_label"] != FAILURE_LABELS[failure_class]:
        raise ValueError("failure_label does not match failure_class")
    if record["role"] not in STAGE_ROLES:
        raise ValueError(f"unknown role: {record['role']!r}")
    if record["risk_class"] not in RISK_CLASSES:
        raise ValueError(f"unknown risk_class: {record['risk_class']!r}")
    decision_token = record["decision"]
    if decision_token not in DECISIONS:
        raise ValueError(
            f"unknown decision: {decision_token!r} (allowed: {DECISIONS})"
        )
    if record["authorization_outcome"] != AUTH_OUTCOME_NONE:
        raise ValueError(
            "authorization_outcome must be 'none' in this foundation unit — "
            "no authorization flow is executed here; any paid escalation must "
            "consume the existing Paid Guard / Cost Guard (A0) authority"
        )

    # foundation no-execution invariants（Req 6：attempted/used 恒 False）
    if record["fallback_attempted"] is not False:
        raise ValueError(
            "fallback_attempted must be False (this foundation unit has no "
            "execution authority — no second model may be invoked)"
        )
    if record["fallback_used"] is not False:
        raise ValueError(
            "fallback_used must be False (this foundation unit has no "
            "execution authority — no fallback model was used)"
        )

    budget = record["automatic_fallback_count_budget"]
    used = record["automatic_fallback_count_used"]
    if budget != MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
        raise ValueError(
            f"automatic_fallback_count_budget must be "
            f"{MAX_AUTOMATIC_FALLBACKS_PER_STAGE} (one-fallback rule), "
            f"got {budget!r}"
        )
    if isinstance(used, bool) or not isinstance(used, int):
        raise ValueError(
            "automatic_fallback_count_used must be an int, "
            f"got {type(used).__name__}"
        )
    if not 0 <= used <= MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
        raise ValueError(
            f"automatic_fallback_count_used out of range: {used!r}"
        )
    retry = record["transport_retry_count"]
    if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
        raise ValueError(
            f"transport_retry_count must be a non-negative int, got {retry!r}"
        )

    # final actual == original（foundation：无任何执行切换）
    if (
        record["final_actual_model"] != record["original_model"]
        or record["final_actual_provider"] != record["original_provider"]
    ):
        raise ValueError(
            "final_actual_model/provider must equal original_model/provider "
            "in this foundation unit (no model switch occurred)"
        )

    # decision ↔ flags / class 一致性
    if record["fallback_eligible"] is not (
        decision_token == DECISION_FALLBACK_ELIGIBLE
    ):
        raise ValueError("fallback_eligible flag inconsistent with decision")
    if record["paid_escalation_required"] is not (
        decision_token == DECISION_PAID_ESCALATION_REQUIRED
    ):
        raise ValueError(
            "paid_escalation_required flag inconsistent with decision"
        )
    if decision_token == DECISION_PAID_ESCALATION_REQUIRED:
        if failure_class not in PAID_ESCALATION_CLASSES:
            raise ValueError(
                "paid_escalation_required decision requires failure_class "
                "in PAID_ESCALATION_CLASSES"
            )
    if decision_token == DECISION_BLOCKED_FAIL_CLOSED:
        if failure_class not in BLOCKED_CLASSES:
            raise ValueError(
                "blocked_fail_closed decision requires failure_class in "
                "BLOCKED_CLASSES"
            )
    if decision_token == DECISION_FALLBACK_ELIGIBLE:
        if failure_class not in TRIGGER_CAPABLE_CLASSES:
            raise ValueError(
                "fallback_eligible decision requires a trigger-capable "
                "failure class"
            )
        if used != 0:
            raise ValueError(
                "fallback_eligible decision impossible with an exhausted "
                "one-fallback budget"
            )
    if decision_token in (
        DECISION_FALLBACK_NOT_ELIGIBLE,
        DECISION_PAID_ESCALATION_REQUIRED,
        DECISION_BLOCKED_FAIL_CLOSED,
    ):
        if not (
            isinstance(record["decision_reason"], str)
            and record["decision_reason"].strip()
        ):
            raise ValueError(
                "decision_reason (explicit no-fallback/blocked reason) is "
                "required when decision is not fallback_eligible"
            )
    elif record["decision_reason"] is not None:
        raise ValueError("decision_reason must be null when decision is fallback_eligible")

    # candidates 一致性：全 str、排序、不含 original key；sole candidate 规则
    candidates = record["fallback_candidates"]
    if not isinstance(candidates, list) or not all(
        isinstance(item, str) and item.strip() for item in candidates
    ):
        raise ValueError("fallback_candidates must be a list of non-empty str")
    if candidates != sorted(set(candidates)):
        raise ValueError("fallback_candidates must be unique and sorted")
    original_key = canonical_key(
        record["original_model"], record["original_provider"]
    )
    if original_key in candidates:
        raise ValueError(
            "original model must not appear in fallback_candidates "
            "(same-model recovery is the retry layer, not fallback)"
        )
    if decision_token == DECISION_FALLBACK_ELIGIBLE and not candidates:
        raise ValueError(
            "fallback_eligible decision requires at least one qualified "
            "fallback candidate"
        )
    single = record["fallback_candidate"]
    if len(candidates) == 1:
        if single != candidates[0]:
            raise ValueError(
                "fallback_candidate must be the sole qualified candidate"
            )
    elif single is not None:
        raise ValueError(
            "fallback_candidate must be None unless exactly one qualified "
            "candidate exists (no selection authority in this foundation unit)"
        )

    # no-silent-fallback evidence：非空显式证据
    evidence = record["no_silent_fallback_evidence"]
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(item, str) and item.strip() for item in evidence
    ):
        raise ValueError(
            "no_silent_fallback_evidence must be a non-empty list of str"
        )
    notes = record["notes"]
    if not isinstance(notes, list) or not all(
        isinstance(item, str) for item in notes
    ):
        raise ValueError("notes must be a list of str")
    for key in ("task_id", "stage_agent", "trigger", "risk_source"):
        if not (isinstance(record[key], str) and record[key].strip()):
            raise ValueError(f"{key} must be a non-empty string")
    for key in ("original_model", "final_actual_model"):
        if not (isinstance(record[key], str) and record[key].strip()):
            raise ValueError(f"{key} must be a non-empty string")
    for key in ("original_provider", "final_actual_provider"):
        value = record[key]
        if value is not None and not (isinstance(value, str) and value.strip()):
            raise ValueError(f"{key} must be a non-empty string or None")
    if not (isinstance(record["generated_at"], str) and record["generated_at"]):
        raise ValueError("generated_at must be a non-empty string")
    tev = record["trigger_evidence"]
    if not isinstance(tev, list) or not all(isinstance(item, str) for item in tev):
        raise ValueError("trigger_evidence must be a list of str")
