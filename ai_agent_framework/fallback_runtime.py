"""AAF v0.5 A5 — Fallback Runtime Layer（bounded FREE/LOCAL_FREE automatic fallback）。

TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001
把已验收的 A5 fallback decision/audit contract（``fallback_contract.py``，CLOSED
& SYNCED）接入真实执行路径：Hermes executor stage 的原始模型 invocation 以
fallback-eligible failure 失败后，**至多一次** automatic model-level fallback
attempt，且只允许 FREE / LOCAL_FREE 合格候选。本任务**不实现 paid escalation**。

FIX-001（TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001，Codex 两个
blocking runtime-contract defects 收口）：
1. **准入 fail-closed**：本 FREE/LOCAL_FREE fallback runtime 只允许 A0 Paid
   Guard 结果 = ``ALLOWED_FREE`` 的候选进入第二模型 invocation；
   ``ALLOWED_AUTHORIZED_PAID``（权威 Cost/Paid Guard 解析为 paid /
   authorized-paid 语义）**绝不**发起 fallback invocation——即使 registry
   候选最初标为 FREE/LOCAL_FREE、即使 ``AAF_COST_AUTH`` 存在且精确匹配（A0
   在 admission 边界按既有一次性语义 claim 该授权，本层不 bypass/削弱/复刻
   A0；paid escalation = 后续 A5 任务的 scope，本单元只拒绝并 fail closed）。
2. **authoritative audit closure 是 fallback 结果被接受的前提**：fallback
   invocation 已发生后，若权威 audit record 的组装/校验/持久化失败——该
   invocation 的输出**不得**被接受为成功 stage result（fail-closed framework
   result：result_text=None 保留原始失败），语义如实记录 attempted=true /
   used=false；audit failure 显式 surface（绝不静默丢弃、绝不假装 attempt 未
   发生）；不发起第三模型、不重试另一个 fallback。

FIX-002（TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002，Codex 唯一
blocking 收口——fallback 第二模型已实际 invocation 后，audit validation /
serialization / persistence 异常的统一 fail-closed 边界）：post-invocation
authoritative audit closure 是 exception-safe 的 fail-closed 边界——
1. ``_emit`` 的 catch 从 (ValueError, TypeError, OSError) 拓宽为 Exception：
   audit 组装/校验/序列化/持久化中**任何**未预期的实现/runtime 异常
   （RuntimeError / UnicodeError / KeyError / …）都是 audit closure 失败 →
   收口为显式 fail-closed 结果（attempted=true / used=false / 绝不接受
   fallback 输出 / audit_closure_error surface），**绝不**作为裸异常逃逸；
2. 自 ALLOWED_FREE admission（第二模型 invocation 真实发生、attempted=true）
   起，整个 invocation + audit closure 段由兜底 fail-closed 边界包裹：任何
   未被内层捕获的异常（含 audit closure 之外的意外逃逸）都转换为结构化
   fail-closed 返回（attempted=true / used=false / audit_closure_error /
   overlay_saved 供调用方还原 env）——runner 绝不把这些降级为泛化
   "layer error"（那会丢失 attempt 事实与 env 还原）；pre-invocation
   编程错误（边界之外、无 attempt 发生）不在此捕获（原语义保持）。

复用纪律（Requirement 1——不创建平行判断系统）：
1. 决策 = ``fallback_contract.decide_fallback``（唯一权威 A5 decision contract；
   其内部复用 A2 selector -> A1 registry/risk 契约：role 适用性 → capability
   充分性 → qualification → executor main-scope 闸）。本模块零 eligibility
   判断：只在 contract 的 fallback candidates 之上应用 Requirement 3 的
   FREE/LOCAL_FREE cost gate（复用 A3 active_routing.ACTIVE_ROUTING_COST_CLASSES
   ——同一成本闸词汇，不另建）并做确定性选择（零现金类内按 locality → key，
   与 A2 selector 的次级 tie-break 偏好一致）。
2. 准入 = 既有 A0 Paid Guard（``cost_guard.evaluate``）在 fallback candidate 的
   env 覆盖下求值（A0 是 effective cost 的权威解析层）：**仅
   ALLOWED_FREE → 允许恰一次 invocation**；``ALLOWED_AUTHORIZED_PAID`` →
   **不发起第二模型**（FIX-001——authoritative result 解析为 paid 语义即拒绝；
   显式 notes 记录 A0 已按既有一次性语义 claim 精确 scope 授权、本 FREE-only
   单元拒绝执行 paid fallback，fail closed）；其余（BLOCKED_COST_APPROVAL /
   guard 失败）→ **不发起第二模型**（fail closed；无 silent paid fallback——
   A0 authority 持有，授权消费/一次性语义不变）。eligibility 与 admission
   之间任何失败一律视作 admission 被拒（authorization_outcome=
   BLOCKED_COST_APPROVAL + 显式 notes），不产生 attempt。
3. 初始选择 = A3 active routing 行为零修改（Requirement 9）：fallback 只发生在
   **真实原始 invocation 失败之后**（runner 在 try/except 捕获到 invocation
   异常后调用本层），绝不与 initial model selection 混淆。
4. 失败分类 = 本层最小分类器（``classify_failure``）：只基于可观测 invocation
   证据（异常类型/消息）映射到 A5 taxonomy；无证据证明是模型级失败 → 一律
   FAILURE_FRAMEWORK_INPUT_CONFIG（blocked_fail_closed，无 fallback 上下文）。
   映射纪律与 workbuddy_retry 的保守分类同型（只基于真实 evidence，不凭空造
   规则）。
5. same-model transport retry（RW-027 层）与 model-level fallback 分层分离：
   ``transport_retry_count`` 独立记录、不计入 one-fallback 预算、绝不翻转
   attempted/used（Hermes stage 无 retry 层；字段保留供审计一致）。

One-fallback / no-chain rule（Requirement 2/5/7）：
- 每个 affected stage 至多 1 次 automatic model-level fallback attempt
  （本层单次调用点、无循环；失败的 fallback 也保持一次 attempt，绝不触发
  第二次）；
- fallback_attempted=true 仅当第二个不同模型的 invocation 被实际发起；
- fallback_used=true 仅当该 fallback invocation 的输出成为被接受的 stage
  执行结果（valid、非 FRAMEWORK_ERROR）**且权威 audit record 已成功组装、
  校验并持久化**（FIX-001：authoritative audit closure 是接受前提——audit
  失败时 attempted=true / used=false，输出不被接受）；
- 失败的 fallback：used=false，stage 保留原始失败文本（不替换、不伪装）。

Audit（Requirement 6/10）：每个 live outcome 持久化 ``fallback_runtime.json``
（authoritative=true；decision_kind="fallback_runtime_audit"）并经
``validate_fallback_runtime_record`` fail-closed 校验。记录与 contract decision
record 同 schema 字段（original actual model/provider、failure class/trigger、
fallback candidates/candidate、fallback_attempted/used、paid_escalation_required、
authorization outcome、final actual model/provider、explicit no-silent-fallback
evidence），语义为**本执行单元的实际结果**。foundation contract 的 fixed
semantic（attempted/used 恒 False、final==original、validate_fallback_record
零修改）继续约束它自己的 decision record；两种 record 以 decision_kind +
authority 明确区分，互不混淆。

执行顺序纪律：A5 审计 artifact 记录的是**执行结果**（outcome evidence），
与 A3 active_routing（执行前 admission evidence）不同——本层在 outcome 确定后
持久化最终记录；eligible 但 admission 被拒（BLOCKED / authorized-paid 被本
FREE-only 单元拒绝）同样是最终状态并被完整审计。持久化失败（发生在第二模型
invocation **之前**）→ 不发起第二模型（fail closed）。FIX-001：发生在第二模型
invocation **之后**的 audit 失败（组装/校验/持久化）→ invocation 不可撤销
（attempted=true 如实记录）但其输出**绝不**被接受（used=false、result_text=None
保留原始失败），audit failure 经返回结构显式 surface——fail closed，不发起
第三模型、不重试另一个 fallback。

Executor 资格（Context：Hermes executor candidate 必须有真实 main-executor
qualification）：selector 的 executor scope=main 闸原样生效（auxiliary/unknown
scope 候选绝不进入 fallback candidates——AAF-v0.5-A3-HERMES-EXECUTOR-
QUALIFICATION-FIX-001 语义保持，测试锁定）。

范围边界：不实现 paid escalation / free→paid 授权流程（A0 authority 语义保持，
本层绝不发起付费模型调用）；A6（health/quarantine/requalification）与 A4+
（broader agent scope）显式 outside；A3 初始 routing / A0 guard / A4 经济路由
行为零修改。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import active_routing as active_routing_mod
from . import cost_guard as cost_guard_mod
from . import fallback_contract as fc
from . import model_registry as model_registry_mod
from . import shadow_routing as shadow_routing_mod
from .risk_contract import ROLE_EXECUTOR

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DECISION_KIND = "fallback_runtime_audit"
ARTIFACT_FILENAME = "fallback_runtime.json"

# 唯一权威说明（写入每个 record；与 contract decision record 的 authority 同型
# 但明确区分：本 artifact 记录**已执行 stage** 的结果；decision 语义仍由
# fallback_contract 唯一授权）
AUTHORITY = (
    "fallback_runtime.py (A5 bounded FREE/LOCAL_FREE fallback runtime layer, "
    "TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001): this artifact is the "
    "AUTHORITATIVE audit record of the live Hermes executor stage's automatic "
    "model-level fallback outcome (fallback_attempted/fallback_used/final "
    "actual model per the A5 execution semantics). Decision semantics reuse "
    "the single authoritative A5 decision contract "
    "(fallback_contract.decide_fallback -> A2 selector -> A1 registry/risk "
    "gates); the Requirement-3 cost gate reuses A3 "
    "active_routing.ACTIVE_ROUTING_COST_CLASSES (FREE/LOCAL_FREE only); "
    "admission reuses the A0 Paid Guard (cost_guard.evaluate) — no parallel "
    "routing/qualification/cost/authorization judgment system. Contrast with "
    "the contract's own decision records (decision_kind=fallback_decision, "
    "foundation semantics: attempted/used always false)."
)

# 本单元只接入 Hermes executor stage（最小 live runtime path）
STAGE_AGENT_HERMES = "hermes"

# Requirement 3 cost gate：复用 A3 的 active-routing cost gate（{FREE,
# LOCAL_FREE}）——同一词汇，绝不另建成本集合。FREE_PROMO 与 A3 authority
# 相同地被排除（本单元只允许 FREE / LOCAL_FREE）。
FALLBACK_COST_CLASSES = active_routing_mod.ACTIVE_ROUTING_COST_CLASSES

# locality tie-break 偏好（次级；与 A2 selector 次级 tie-break 同序：
# local < remote < unknown）。零现金类经济 rank 全并列 → locality → key。
_LOCALITY_RANK = {
    model_registry_mod.LOCALITY_LOCAL: 0,
    model_registry_mod.LOCALITY_REMOTE: 1,
    model_registry_mod.LOCALITY_UNKNOWN: 2,
}

# 审计 schema 必需字段（与 contract decision record 的字段集一致——同一审计
# 词汇；变更必须与 fallback_contract._REQUIRED_KEYS 协同）
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

# authorization_outcome 词汇：A0 Paid Guard decision token（ALLOWED_FREE /
# ALLOWED_AUTHORIZED_PAID / BLOCKED_COST_APPROVAL）或 "none"（本层未进入
# admission——非 eligible / paid / blocked 上下文无候选需准入）
AUTH_OUTCOME_ALLOWED_FREE = cost_guard_mod.DECISION_ALLOWED_FREE
AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID = cost_guard_mod.DECISION_ALLOWED_AUTHORIZED_PAID
AUTH_OUTCOME_BLOCKED = cost_guard_mod.DECISION_BLOCKED_COST_APPROVAL
AUTH_OUTCOME_NONE = fc.AUTH_OUTCOME_NONE

_ALLOWED_AUTH_OUTCOMES = frozenset(
    (
        AUTH_OUTCOME_NONE,
        AUTH_OUTCOME_ALLOWED_FREE,
        AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID,
        AUTH_OUTCOME_BLOCKED,
    )
)


def _output_is_valid(text: str) -> bool:
    """invocation 输出接受判定（与 runner._result_is_valid 同语义）。"""
    body = (text or "").strip()
    return bool(body) and not body.startswith("FRAMEWORK_ERROR")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _excerpt(message: str, limit: int = 400) -> str:
    message = (message or "").strip().replace("\r", " ")
    message = " ".join(message.split())
    if len(message) > limit:
        return message[:limit] + "..."
    return message


# ---------------------------------------------------------------------------
# Failure classification（最小、确定性、evidence-based；无证据 → 非 fallback 上下文）
# ---------------------------------------------------------------------------


def classify_failure(exc: BaseException) -> dict:
    """把 runner 捕获的 invocation 异常映射到 A5 taxonomy（fail closed）。

    只基于可观测证据（异常类型 + 消息）；无证据证明是模型级失败 →
    FAILURE_FRAMEWORK_INPUT_CONFIG（blocked_fail_closed——诚实 FRAMEWORK_ERROR，
    非 fallback 上下文）：
    - RuntimeError 含 "MISSING_COMMAND" → FAILURE_FRAMEWORK_INPUT_CONFIG
      （CLI 缺失 = 框架/环境配置失败，不是模型失败）
    - subprocess.TimeoutExpired → FAILURE_TRANSPORT_RUNTIME
      （transport/runtime failure；A5 scope 文档：模型级 fallback 判定仍可
      评估，one-fallback 预算同一规则适用）
    - 其他 RuntimeError → FAILURE_INVOCATION（CLI 已启动并以非零退出 / 空
      输出失败 = model/provider invocation failure；消息摘录为 trigger
      evidence）
    - 其余任何异常类型（OSError / ValueError / …）→ FAILURE_FRAMEWORK_INPUT_CONFIG
      （spawn/框架级失败无法归因于模型——unknown ≠ fallback trigger，fail closed）

    返回 {"failure_class", "trigger", "trigger_evidence"}。
    """
    if isinstance(exc, RuntimeError) and "MISSING_COMMAND" in str(exc):
        failure_class = fc.FAILURE_FRAMEWORK_INPUT_CONFIG
    elif isinstance(exc, subprocess.TimeoutExpired):
        failure_class = fc.FAILURE_TRANSPORT_RUNTIME
    elif isinstance(exc, RuntimeError):
        failure_class = fc.FAILURE_INVOCATION
    else:
        failure_class = fc.FAILURE_FRAMEWORK_INPUT_CONFIG
    trigger = f"{type(exc).__name__}: {_excerpt(str(exc))}"
    evidence = [
        f"original invocation raised {type(exc).__name__}; classified by the "
        "A5 fallback runtime classifier (classify_failure) as "
        f"{failure_class!r} ({fc.FAILURE_LABELS[failure_class]})",
    ]
    if failure_class == fc.FAILURE_FRAMEWORK_INPUT_CONFIG:
        evidence.append(
            "no evidence proves a model-level failure (missing CLI / "
            "non-invocation exception) — fail closed: non-fallback context, "
            "no automatic fallback is evaluated as eligible"
        )
    return {
        "failure_class": failure_class,
        "trigger": trigger,
        "trigger_evidence": evidence,
    }


# ---------------------------------------------------------------------------
# 原始 invocation 身份（env override = invocation truth；否则 resolver）
# ---------------------------------------------------------------------------


def _original_invocation_identity() -> dict:
    """失败时刻的原始实际 model/provider。

    env 覆盖（AAF_HERMES_MODEL / AAF_HERMES_PROVIDER / AAF_HERMES_BASE_URL）
    优先——A3/A4 路由后的 env 覆盖即实际 invocation model（既有不变量：guard
    解析的 effective model == 实际 invocation model）；无覆盖时回退
    ``cost_guard.resolve_effective_hermes``（config 只读解析）。返回
    {"model", "provider", "base_url", "source"}；无法解析 → model=None。
    """
    model = os.environ.get(cost_guard_mod.ENV_MODEL, "").strip() or None
    if model:
        return {
            "model": model,
            "provider": os.environ.get(cost_guard_mod.ENV_PROVIDER, "").strip() or None,
            "base_url": os.environ.get(cost_guard_mod.ENV_BASE_URL, "").strip() or None,
            "source": "env_override",
        }
    resolved = cost_guard_mod.resolve_effective_hermes()
    return {
        "model": resolved.get("model"),
        "provider": resolved.get("provider"),
        "base_url": resolved.get("base_url"),
        "source": resolved.get("model_source"),
    }


# ---------------------------------------------------------------------------
# Requirement-3 cost gate + 确定性选择（复用 A3 成本闸词汇 / A2 selector 偏好）
# ---------------------------------------------------------------------------


def _gated_fallback_candidates(
    candidates: list[str],
    registry: dict[str, model_registry_mod.RegistryEntry],
) -> tuple[list[str], list[str]]:
    """FREE/LOCAL_FREE gate：contract candidates → 可执行 fallback candidates。

    返回 (gated_candidates, notes)；被 gate 排除的候选以显式 note 记录
    （可审计——paid/unknown-cost 候选绝不静默出现/静默消失）。
    """
    gated: list[str] = []
    notes: list[str] = []
    for key in candidates:
        entry = registry.get(key)
        if entry is None or not isinstance(entry, model_registry_mod.RegistryEntry):
            notes.append(
                f"candidate {key!r} missing/unsupported in registry — excluded "
                "from fallback execution (fail closed)"
            )
            continue
        if entry.cost_class in FALLBACK_COST_CLASSES:
            gated.append(key)
        else:
            notes.append(
                f"candidate {key!r} cost_class={entry.cost_class!r} excluded by "
                f"the A5 FREE/LOCAL_FREE cost gate "
                f"({sorted(FALLBACK_COST_CLASSES)}; vocabulary reused from A3 "
                "active_routing.ACTIVE_ROUTING_COST_CLASSES) — a "
                "paid/unknown-cost candidate is never silently used"
            )
    return sorted(gated), notes


def _select_fallback_candidate(
    gated: list[str],
    registry: dict[str, model_registry_mod.RegistryEntry],
) -> str | None:
    """确定性选择（gated 非空时）：(economic rank, locality rank, key) 最小者。

    economic rank 复用 ``shadow_routing.economic_rank``（同一 A1 成本分类语义，
    零现金类并列 rank 0）；locality 次级 tie-break 与 A2 selector 同序
    （local < remote < unknown）；key 全序保证输入顺序无关。选择只作用于已
    通过 A1/A2 资格闸 + cost gate 的候选——不是 eligibility 判断。
    """
    if not gated:
        return None
    return min(
        gated,
        key=lambda k: (
            shadow_routing_mod.economic_rank(registry[k].cost_class),
            _LOCALITY_RANK.get(registry[k].locality, 2),
            k,
        ),
    )


# ---------------------------------------------------------------------------
# Live audit record（execution 语义；单一组装点）
# ---------------------------------------------------------------------------


def assemble_runtime_audit_record(
    *,
    decision_record: dict,
    original_identity: dict,
    task_id: str,
    stage_agent: str,
    role: str,
    risk_class: str,
    risk_source: str,
    registry: dict[str, model_registry_mod.RegistryEntry],
    automatic_fallback_count_used: int = 0,
    transport_retry_count: int = 0,
    attempted: bool = False,
    used: bool = False,
    authorization_outcome: str = AUTH_OUTCOME_NONE,
    extra_notes: list[str] | None = None,
    extra_evidence: list[str] | None = None,
) -> dict:
    """组装 live runtime audit record（contract 层叠 runtime 决策 + 执行结果）。

    本函数是**单一组装点**：先对 contract decision record 的 fallback
    candidates 应用 Requirement-3 gate 推导 runtime 决策（``_runtime_outcome``），
    再按 execution 参数填写 attempted/used/authorization_outcome/final actual，
    组装后立即经 ``validate_fallback_runtime_record`` fail-closed 校验。
    """
    outcome = _runtime_outcome(decision_record, registry, automatic_fallback_count_used)

    evidence: list[str] = []
    if attempted:
        evidence.append(
            f"fallback_attempted=true: a second distinct model invocation was "
            f"actually attempted exactly once against candidate "
            f"{outcome['fallback_candidate']!r}"
        )
    else:
        evidence.append(
            "fallback_attempted=false: no second distinct model invocation "
            "was attempted"
        )
    if used:
        evidence.append(
            "fallback_used=true: the fallback invocation's output became the "
            "accepted stage execution result"
        )
    else:
        evidence.append(
            "fallback_used=false: no fallback invocation output became the "
            "accepted stage execution result"
        )
    if outcome["fallback_eligible"]:
        evidence.append(
            "one-fallback rule: this stage's automatic model-level fallback "
            "budget is consumed by at most one attempt — no third model, no "
            "fallback chain/loop"
        )
    if attempted:
        evidence.append(
            "no silent paid fallback: the single fallback invocation passed "
            "the existing A0 Paid Guard admission with an ALLOWED_FREE "
            f"decision (authorization_outcome={authorization_outcome!r}) — "
            "this FREE/LOCAL_FREE unit never invokes a paid or unknown-cost "
            f"model (gate {sorted(FALLBACK_COST_CLASSES)}); an "
            "ALLOWED_AUTHORIZED_PAID admission is refused before invocation "
            "(FIX-001)"
        )
    else:
        evidence.append(
            "no silent paid fallback: no second model invocation occurred "
            f"(authorization_outcome={authorization_outcome!r}) — paid / "
            "unknown-cost / authorized-paid semantics never enter invocation "
            "in this FREE/LOCAL_FREE unit (FIX-001 admission fail-closed)"
        )
    if not attempted:
        evidence.append(
            "no automatic model switch occurred: final actual model/provider "
            "remain the original invocation's model/provider (the original "
            "failure is preserved as the stage result)"
        )
    elif not used:
        evidence.append(
            "the failed fallback remains ONE attempt (used=false) and must "
            "not trigger another fallback — the original failure is preserved "
            "as the stage result (no silent substitution)"
        )
    if transport_retry_count > 0:
        evidence.append(
            f"transport retries ({transport_retry_count}) are the RW-027 "
            "same-model retry layer and are never reported as model-level "
            "fallback and never consume the one-fallback budget"
        )
    if extra_evidence:
        evidence.extend(extra_evidence)

    original_model = original_identity.get("model")
    original_provider = original_identity.get("provider")
    if attempted:
        final_model, final_provider = _split_candidate(
            outcome["fallback_candidate"] or ""
        )
    else:
        final_model, final_provider = original_model, original_provider

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
        "fallback_candidates": list(outcome["candidates"]),
        "fallback_candidate": outcome["fallback_candidate"],
        "fallback_eligible": outcome["fallback_eligible"],
        "decision": outcome["decision"],
        "decision_reason": outcome["decision_reason"],
        "fallback_attempted": attempted,
        "fallback_used": used,
        "paid_escalation_required": (
            outcome["decision"] == fc.DECISION_PAID_ESCALATION_REQUIRED
        ),
        "authorization_outcome": authorization_outcome,
        "final_actual_model": final_model,
        "final_actual_provider": final_provider,
        "no_silent_fallback_evidence": evidence,
        "notes": list(outcome["notes"]) + list(extra_notes or []),
        "generated_at": _now_iso(),
    }
    validate_fallback_runtime_record(record)
    return record


def _runtime_outcome(
    decision_record: dict,
    registry: dict[str, model_registry_mod.RegistryEntry],
    automatic_fallback_count_used: int,
) -> dict:
    """runtime 决策派生：contract decision + FREE/LOCAL_FREE gate。

    返回 {"decision", "decision_reason", "fallback_eligible", "notes",
    "candidates", "fallback_candidate"}。contract decision 为 permission 层
    （fallback_eligible = 存在 A1/A2 合格其他候选且预算未耗尽）；runtime 在其上
    应用 Requirement-3 cost gate：
    - contract 非 eligible（not_eligible / paid_escalation_required /
      blocked_fail_closed）→ runtime decision = contract decision（reason 原样）；
    - contract eligible 但 gated 为空 → runtime decision = fallback_not_eligible
      （REASON_NO_QUALIFIED_CANDIDATE——本单元只允许 FREE/LOCAL_FREE 候选，
      无合格 free 候选 = fail closed，Requirement 4）；
    - contract eligible 且 gated 非空 → runtime decision = fallback_eligible，
      fallback_candidate = 确定性选中者（恰一）。
    """
    notes: list[str] = []
    contract_decision = decision_record["decision"]
    contract_candidates = list(decision_record["fallback_candidates"])
    if contract_decision != fc.DECISION_FALLBACK_ELIGIBLE:
        # 非 eligible 决策：fallback_candidate 沿用 contract 的字段约定
        # （sole qualified candidate 时填该候选，多候选 None）——表达「若
        # 决策不同，可能作为 fallback 的候选」，不代表任何执行选择。
        return {
            "decision": contract_decision,
            "decision_reason": decision_record.get("decision_reason"),
            "fallback_eligible": False,
            "notes": notes,
            "candidates": contract_candidates,
            "fallback_candidate": decision_record.get("fallback_candidate"),
        }
    gated, gate_notes = _gated_fallback_candidates(contract_candidates, registry)
    notes.extend(gate_notes)
    if automatic_fallback_count_used >= fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE:
        return {
            "decision": fc.DECISION_FALLBACK_NOT_ELIGIBLE,
            "decision_reason": (
                f"{fc.REASON_BUDGET_EXHAUSTED}: automatic model-level fallback "
                f"budget ({fc.MAX_AUTOMATIC_FALLBACKS_PER_STAGE} per affected "
                "stage) already consumed — no fallback chain/loop permitted"
            ),
            "fallback_eligible": False,
            "notes": notes,
            "candidates": contract_candidates,
            "fallback_candidate": None,
        }
    if not gated:
        notes.append(
            f"{len(contract_candidates)} contract-eligible candidate(s) "
            f"{contract_candidates} exist but none passes the A5 "
            "FREE/LOCAL_FREE cost gate — no eligible FREE/LOCAL_FREE fallback "
            "candidate (fail closed; paid/unknown-cost candidates are never "
            "silently used)"
        )
        return {
            "decision": fc.DECISION_FALLBACK_NOT_ELIGIBLE,
            "decision_reason": (
                f"{fc.REASON_NO_QUALIFIED_CANDIDATE}: no qualified "
                "FREE/LOCAL_FREE fallback candidate exists for this "
                "stage/role/risk after the A5 Requirement-3 cost gate (A1/A2 "
                "gates were passed by the contract; the FREE/LOCAL_FREE cost "
                "gate filters the remainder) — no safe fallback; fail closed "
                "with an explicit no-fallback reason"
            ),
            "fallback_eligible": False,
            "notes": notes,
            "candidates": [],
            "fallback_candidate": None,
        }
    selected = _select_fallback_candidate(gated, registry)
    if len(gated) > 1:
        notes.append(
            f"multiple FREE/LOCAL_FREE fallback candidates ({gated}) exist; "
            "deterministic selection by (economic rank, locality, key) chose "
            f"{selected!r} — exactly one candidate is attempted at most once"
        )
    return {
        "decision": fc.DECISION_FALLBACK_ELIGIBLE,
        "decision_reason": None,
        "fallback_eligible": True,
        "notes": notes,
        "candidates": gated,
        "fallback_candidate": selected,
    }


def _split_candidate(key: str) -> tuple[str | None, str | None]:
    """``model@provider`` key → (model, provider)（``canonical_key`` 逆操作）。"""
    if "@" in key:
        model, _, provider = key.partition("@")
        return model, provider or None
    return key, None


# ---------------------------------------------------------------------------
# 校验（live execution 语义；fail closed）
# ---------------------------------------------------------------------------


def validate_fallback_runtime_record(record: dict) -> None:
    """Live runtime audit record fail-closed 校验。

    与 contract validator（validate_fallback_record，foundation 语义）分层：
    本 validator 校验**已执行 stage** 的记录——attempted/used/final actual 按
    Requirement 7 语义真实反映执行结果；contract decision record 的 foundation
    不变量（attempted/used 恒 False）零修改、互不混淆。FIX-001 语义：attempted
    只允许 authorization_outcome=ALLOWED_FREE（本 FREE/LOCAL_FREE 单元绝不执行
    authorized-paid 候选）；eligible-未attempt 允许 BLOCKED（A0 拒绝）或
    ALLOWED_AUTHORIZED_PAID（A0 准入为 paid 但本 FREE-only 单元拒绝执行）。
    任一违例 → ValueError（不返回部分有效状态）。
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
            "authority must exactly match the authoritative A5 fallback "
            "runtime value emitted by this module (single authoritative "
            "source; missing/altered/unexpected authority fails closed — no "
            "second authority system)"
        )
    failure_class = record["failure_class"]
    if failure_class not in fc.FAILURE_CLASSES:
        raise ValueError(
            f"unknown failure_class: {failure_class!r} "
            f"(allowed: {fc.FAILURE_CLASSES})"
        )
    if record["failure_label"] != fc.FAILURE_LABELS[failure_class]:
        raise ValueError("failure_label does not match failure_class")
    if record["role"] not in fc.STAGE_ROLES:
        raise ValueError(f"unknown role: {record['role']!r}")
    if record["risk_class"] not in fc.RISK_CLASSES:
        raise ValueError(f"unknown risk_class: {record['risk_class']!r}")
    decision_token = record["decision"]
    if decision_token not in fc.DECISIONS:
        raise ValueError(
            f"unknown decision: {decision_token!r} (allowed: {fc.DECISIONS})"
        )
    # failure_class ↔ decision 完整双向契约（复用 contract 的分区权威）
    fc._validate_class_decision_contract(failure_class, decision_token)
    if record["authorization_outcome"] not in _ALLOWED_AUTH_OUTCOMES:
        raise ValueError(
            "authorization_outcome must be an A0 Paid Guard decision token "
            "(ALLOWED_FREE / ALLOWED_AUTHORIZED_PAID / BLOCKED_COST_APPROVAL) "
            f"or 'none', got {record['authorization_outcome']!r}"
        )

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

    # --- execution 语义不变量（Requirement 7） ---
    attempted = record["fallback_attempted"]
    used = record["fallback_used"]
    if attempted is not True and attempted is not False:
        raise ValueError("fallback_attempted must be a bool")
    if used is not True and used is not False:
        raise ValueError("fallback_used must be a bool")
    if used and not attempted:
        raise ValueError(
            "fallback_used=true requires fallback_attempted=true "
            "(an invocation must be attempted before its output can be used)"
        )
    if record["fallback_eligible"] is not (
        decision_token == fc.DECISION_FALLBACK_ELIGIBLE
    ):
        raise ValueError("fallback_eligible flag inconsistent with decision")
    if record["paid_escalation_required"] is not (
        decision_token == fc.DECISION_PAID_ESCALATION_REQUIRED
    ):
        raise ValueError(
            "paid_escalation_required flag inconsistent with decision"
        )

    candidates = record["fallback_candidates"]
    if not isinstance(candidates, list) or not all(
        isinstance(item, str) and item.strip() for item in candidates
    ):
        raise ValueError("fallback_candidates must be a list of non-empty str")
    if candidates != sorted(set(candidates)):
        raise ValueError("fallback_candidates must be unique and sorted")
    original_key = model_registry_mod.canonical_key(
        record["original_model"], record["original_provider"]
    )
    if original_key in candidates:
        raise ValueError(
            "original model must not appear in fallback_candidates "
            "(same-model recovery is the retry layer, not fallback)"
        )
    single = record["fallback_candidate"]
    if len(candidates) == 1:
        if single != candidates[0]:
            raise ValueError("fallback_candidate must be the sole gated candidate")
    elif single is not None and single not in candidates:
        raise ValueError(
            "fallback_candidate must be one of fallback_candidates (the "
            "deterministically selected executable candidate)"
        )

    if attempted:
        if decision_token != fc.DECISION_FALLBACK_ELIGIBLE:
            raise ValueError(
                "an attempted fallback requires decision=fallback_eligible "
                "(only an eligible decision may execute a second model)"
            )
        if used_count != 0:
            raise ValueError(
                "an attempted fallback requires an unexhausted budget "
                "(automatic_fallback_count_used must be 0 before the attempt)"
            )
        if not candidates or single is None:
            raise ValueError(
                "an attempted fallback requires an executable fallback_candidate"
            )
        if record["authorization_outcome"] != AUTH_OUTCOME_ALLOWED_FREE:
            raise ValueError(
                "an attempted fallback requires an A0 Paid Guard "
                "ALLOWED_FREE admission (this FREE/LOCAL_FREE fallback "
                "runtime never executes an ALLOWED_AUTHORIZED_PAID "
                "candidate — paid fallback is a later A5 unit's scope; "
                "no silent paid execution; FIX-001 admission fail-closed)"
            )
    elif decision_token == fc.DECISION_FALLBACK_ELIGIBLE:
        # eligible 但未 attempt：合法路径只有 admission 边界拒绝——A0 BLOCKED
        # （guard 拒绝 / admission 前失败）或 A0 准入为 paid 但本 FREE-only
        # 单元拒绝执行 authorized-paid fallback（FIX-001；A0 已按既有一次性
        # 语义 claim 精确 scope 授权，但本单元绝不因此执行 paid fallback）
        if record["authorization_outcome"] not in (
            AUTH_OUTCOME_BLOCKED,
            AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID,
        ):
            raise ValueError(
                "fallback_eligible with no attempt requires the admission "
                "to have been denied at the boundary: authorization_outcome "
                "must be BLOCKED_COST_APPROVAL (A0 Paid Guard denied) or "
                "ALLOWED_AUTHORIZED_PAID (A0 admitted the candidate as PAID "
                "but this FREE/LOCAL_FREE fallback runtime refuses to "
                "execute paid fallback — attempted=false, no second model) "
                "— an eligible-but-not-attempted record is otherwise "
                "contradictory"
            )

    if decision_token in (
        fc.DECISION_FALLBACK_NOT_ELIGIBLE,
        fc.DECISION_PAID_ESCALATION_REQUIRED,
        fc.DECISION_BLOCKED_FAIL_CLOSED,
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
        raise ValueError(
            "decision_reason must be null when decision is fallback_eligible"
        )

    original_model = record["original_model"]
    original_provider = record["original_provider"]
    final_model = record["final_actual_model"]
    final_provider = record["final_actual_provider"]
    if not (isinstance(original_model, str) and original_model.strip()):
        raise ValueError("original_model must be a non-empty string")
    if original_provider is not None and not (
        isinstance(original_provider, str) and original_provider.strip()
    ):
        raise ValueError("original_provider must be a non-empty string or None")
    if not (isinstance(final_model, str) and final_model.strip()):
        raise ValueError("final_actual_model must be a non-empty string")
    if final_provider is not None and not (
        isinstance(final_provider, str) and final_provider.strip()
    ):
        raise ValueError("final_actual_provider must be a non-empty string or None")
    if attempted:
        if single is None:
            raise ValueError(
                "attempted fallback requires a selected fallback_candidate"
            )
        if (final_model, final_provider) != _split_candidate(single):
            raise ValueError(
                "final_actual_model/provider must equal the attempted "
                "fallback candidate's model/provider (provenance of the last "
                "actual invocation)"
            )
    elif (final_model, final_provider) != (original_model, original_provider):
        raise ValueError(
            "final_actual_model/provider must equal original_model/provider "
            "when no fallback was attempted (no model switch occurred)"
        )

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
    if not (isinstance(record["generated_at"], str) and record["generated_at"]):
        raise ValueError("generated_at must be a non-empty string")
    tev = record["trigger_evidence"]
    if not isinstance(tev, list) or not all(isinstance(item, str) for item in tev):
        raise ValueError("trigger_evidence must be a list of str")


# ---------------------------------------------------------------------------
# 持久化（原子写；同目录 tmp + os.replace，与 A3/A4 artifact 同一约定）
# ---------------------------------------------------------------------------


def save_fallback_runtime(output_dir: Path | str, record: dict) -> Path:
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


def load_fallback_runtime(output_dir: Path | str) -> dict | None:
    path = Path(output_dir) / ARTIFACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Candidate env overlay（复用 A3 env 契约 / restore 机制；显式清除 stale 值）
# ---------------------------------------------------------------------------


def _apply_candidate_env(
    entry: model_registry_mod.RegistryEntry,
) -> dict[str, str | None]:
    """把 fallback candidate 的 model/provider/base_url 写入 invocation env 覆盖。

    与 ``active_routing.apply_routing_env`` 同一 env 契约与 restore 语义，但
    base_url=None 时**显式删除**该变量——candidate 无端点事实时，绝不能因 A3
    初始 routing overlay 残留的 loopback base_url 让 A0 Paid Guard 误判
    LOCAL_FREE（admission truth = candidate 自身事实；fail closed）。返回
    {var: 旧值或 None}，用 ``active_routing.restore_routing_env`` 还原（旧值
    None → restore 删除；本函数删除的已有变量 → 旧值被保存，restore 原样恢复）。
    """
    saved: dict[str, str | None] = {}
    values = {
        cost_guard_mod.ENV_MODEL: entry.model,
        cost_guard_mod.ENV_PROVIDER: entry.provider,
        cost_guard_mod.ENV_BASE_URL: entry.base_url,
    }
    for var, value in values.items():
        saved[var] = os.environ.get(var)
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value
    return saved


# ---------------------------------------------------------------------------
# Orchestrator（runner Hermes stage 调用点）
# ---------------------------------------------------------------------------


def run_fallback_after_failure(
    *,
    task_id: str,
    risk_class: str,
    risk_source: str,
    registry: dict[str, model_registry_mod.RegistryEntry],
    output_dir: Path | str,
    prompt: str,
    workspace: Any,
    invoke: Callable[[str, str, Any], str],
    failure_exc: BaseException,
    stage_agent: str = STAGE_AGENT_HERMES,
    role: str = ROLE_EXECUTOR,
    transport_retry_count: int = 0,
    automatic_fallback_count_used: int = 0,
) -> dict | None:
    """Hermes stage 原始 invocation 失败后的 A5 fallback 编排（至多一次 attempt）。

    前置（fail closed，返回 None——runner 保持原始失败语义、零 artifact）：
    - risk_class 必须为 RISK_CLASSES 显式成员（contract 需要；缺失无法决策）；
    - 原始实际 model 必须可解析（无法审计 original identity → 不评估）；
    - contract 决策 / 记录组装 / 持久化失败 → 不发起第二模型。

    流程：
    1. ``classify_failure`` → failure_class / trigger；
    2. 解析 original actual model/provider（env override = invocation truth）；
    3. ``fallback_contract.decide_fallback``（唯一决策 authority）+ contract
       validator 复核；
    4. Requirement-3 FREE/LOCAL_FREE gate → runtime 决策（eligible / 明确
       no-fallback reason）+ 确定性候选；
    5. runtime eligible 时：candidate env 覆盖（复用 A3 env 契约与
       ``active_routing.restore_routing_env`` 还原机制；candidate 无 base_url 时
       显式清除 stale 覆盖，admission truth = candidate 自身事实）→ A0 Paid
       Guard 求值（既有 authority；FIX-001 admission fail-closed）：
       - **仅 ALLOWED_FREE → invoke 恰一次**（本 FREE/LOCAL_FREE 单元唯一
         允许进入第二模型 invocation 的准入结果）；
       - ALLOWED_AUTHORIZED_PAID → 还原 env，**不 invocation**
         （authorization_outcome=ALLOWED_AUTHORIZED_PAID 如实记录 A0 结果 +
         显式 notes：A0 已按既有一次性语义 claim 精确 scope 授权，但本
         FREE-only 单元拒绝执行 paid fallback——paid escalation 是后续 A5
         任务 scope，fail closed）；
       - BLOCKED_COST_APPROVAL / admission 前失败 → 还原 env，不 invocation
         （authorization_outcome=BLOCKED_COST_APPROVAL + 显式 notes）；
    6. 最终 audit record 组装 + 校验 + 落盘（artifact 记录的是 outcome
       evidence；invocation **之前**的持久化失败 → 不发起第二模型，fail
       closed；FIX-001：invocation **之后**的 audit 组装/校验/持久化失败 →
       该 invocation 的输出**不**被接受为成功 stage result——返回
       attempted=true / used=false / result_text=None 的 fail-closed 结构 +
       audit_closure_error 显式 surface，不发起第三模型、不重试 fallback；
       FIX-002：audit closure 的异常捕获从 (ValueError, TypeError, OSError)
       拓宽为 Exception（RuntimeError / UnicodeError / 其他未预期实现/
       runtime 异常一律收口，绝不作为裸异常逃逸），且自 admission 起整个
       invocation + audit closure 段有兜底 fail-closed 边界——任何逃逸都
       转为同样的结构化结果，runner 绝不降级为泛化 "layer error"）。

    返回 dict（runner 消费）：
    {"result_text", "audit_record", "artifact_ref", "attempted", "used",
     "overlay_saved"}（audit closure 失败时另含 "audit_closure_error"）；
    result_text=None → runner 保留其原始 FRAMEWORK_ERROR 文本；overlay_saved
    非 None 仅当已发起 candidate invocation——调用方必须在 model/shadow
    observation **之后**、A3 routing env 还原**之前**调用
    ``active_routing.restore_routing_env(overlay_saved)`` 还原（observation 必须
    如实看到 final actual invocation model）。前置不满足 → None。
    """
    output_dir = Path(output_dir)
    if risk_class not in fc.RISK_CLASSES:
        return None

    classification = classify_failure(failure_exc)
    original_identity = _original_invocation_identity()
    original_model = original_identity.get("model")
    if not (isinstance(original_model, str) and original_model.strip()):
        return None

    try:
        decision_record = fc.decide_fallback(
            failure_class=classification["failure_class"],
            trigger=classification["trigger"],
            task_id=task_id,
            stage_agent=stage_agent,
            role=role,
            risk_class=risk_class,
            risk_source=risk_source,
            original_model=original_model,
            original_provider=original_identity.get("provider"),
            registry=registry,
            transport_retry_count=transport_retry_count,
            automatic_fallback_count_used=automatic_fallback_count_used,
            trigger_evidence=tuple(classification["trigger_evidence"]),
        )
        fc.validate_fallback_record(decision_record)  # contract 层内部复核
    except (ValueError, TypeError):
        return None  # malformed/无法决策 → fail closed：不评估、不 attempt

    # 最近一次 _emit 失败详情（FIX-001：audit closure 失败必须显式 surface，
    # 绝不静默丢弃——post-invocation 路径将其带进返回结构）
    emit_failure: list[str] = []

    def _emit(
        *,
        attempted: bool,
        used: bool,
        authorization_outcome: str,
        extra_notes: list[str] | None = None,
        extra_evidence: list[str] | None = None,
    ) -> dict | None:
        """组装 + 校验 + 落盘最终 audit record；失败 → None（fail closed）。

        失败详情记录到 ``emit_failure``（FIX-001：调用方必须显式 surface，
        绝不静默丢弃 audit failure）。
        """
        try:
            record = assemble_runtime_audit_record(
                decision_record=decision_record,
                original_identity=original_identity,
                task_id=task_id,
                stage_agent=stage_agent,
                role=role,
                risk_class=risk_class,
                risk_source=risk_source,
                registry=registry,
                automatic_fallback_count_used=automatic_fallback_count_used,
                transport_retry_count=transport_retry_count,
                attempted=attempted,
                used=used,
                authorization_outcome=authorization_outcome,
                extra_notes=extra_notes,
                extra_evidence=extra_evidence,
            )
            save_fallback_runtime(output_dir, record)
        except Exception as exc:  # noqa: BLE001 — FIX-002：audit closure
            # 边界。assemble（含 validator）/ 序列化 / 持久化的**任何**未预期
            # 实现/runtime 异常（不限于 ValueError/TypeError/OSError；含
            # RuntimeError / UnicodeError / KeyError 等）都是 audit closure
            # 失败 → 统一收口为显式 fail-closed 结果（调用方把 emit_failure
            # 带进返回结构），绝不作为裸异常逃逸到 runner 变成泛化
            # "layer error"（那会丢失 attempted=true 事实、fallback 结果
            # 接受判定与 env 还原路径）。
            emit_failure[:] = [
                f"{type(exc).__name__}: {_excerpt(str(exc))}"
            ]
            if os.environ.get("AAF_FALLBACK_DEBUG"):
                print(
                    f"[a5-fallback][debug] _emit failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            return None
        return record

    # --- 决策基记录（attempted=false 的最终形态之一；eligible 分支会在
    #     admission 后才组装最终记录——本层 artifact = outcome evidence） ---
    outcome = _runtime_outcome(decision_record, registry, automatic_fallback_count_used)
    if not outcome["fallback_eligible"] or outcome["fallback_candidate"] is None:
        record = _emit(
            attempted=False,
            used=False,
            authorization_outcome=AUTH_OUTCOME_NONE,
            extra_notes=[
                f"contract decision record validated: decision="
                f"{decision_record['decision']!r} with "
                f"{len(decision_record['fallback_candidates'])} contract-"
                "eligible candidate(s) (A1/A2 gates); runtime Requirement-3 "
                "cost gate applied afterwards",
            ],
        )
        if record is None:
            return None
        return {
            "result_text": None,
            "audit_record": record,
            "artifact_ref": {
                "authority": str(output_dir / ARTIFACT_FILENAME),
                "entry": stage_agent,
            },
            "attempted": False,
            "used": False,
            "overlay_saved": None,
        }

    # --- eligible：candidate env 覆盖 + A0 Paid Guard 求值（既有 authority） ---
    selected = outcome["fallback_candidate"]
    entry = registry.get(selected)
    if entry is None or not isinstance(entry, model_registry_mod.RegistryEntry):
        record = _emit(
            attempted=False,
            used=False,
            authorization_outcome=AUTH_OUTCOME_BLOCKED,
            extra_notes=[
                f"registry view inconsistent for selected candidate "
                f"{selected!r} (missing/unsupported entry) — admission "
                "denied, no second invocation (fail closed)"
            ],
        )
        return _no_attempt_result(output_dir, stage_agent, record)

    try:
        overlay_saved = _apply_candidate_env(entry)
    except (ValueError, OSError) as exc:
        record = _emit(
            attempted=False,
            used=False,
            authorization_outcome=AUTH_OUTCOME_BLOCKED,
            extra_notes=[
                "candidate env overlay failed "
                f"({type(exc).__name__}: {_excerpt(str(exc))}) — admission "
                "denied, no second invocation (fail closed)"
            ],
        )
        return _no_attempt_result(output_dir, stage_agent, record)

    try:
        guard_record = cost_guard_mod.evaluate(
            task_id, stage_agent, state_dir=output_dir
        )
    except Exception as exc:  # noqa: BLE001 — guard 内部失败 → fail closed
        active_routing_mod.restore_routing_env(overlay_saved)
        record = _emit(
            attempted=False,
            used=False,
            authorization_outcome=AUTH_OUTCOME_BLOCKED,
            extra_notes=[
                "A0 Paid Guard evaluation for the fallback candidate raised "
                f"{type(exc).__name__}: {_excerpt(str(exc))} — admission "
                "denied, no second invocation (fail closed; existing Paid "
                "Guard semantics remain authoritative)"
            ],
        )
        return _no_attempt_result(output_dir, stage_agent, record)

    guard_decision = guard_record.get("decision")
    if guard_decision == AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID:
        # FIX-001（Codex BLOCKING #1 收口）：A0 Paid Guard 的权威结果 =
        # authorized-paid 语义 → 本 FREE/LOCAL_FREE fallback runtime **绝不**
        # 发起该候选的 invocation——registry 候选最初标为 FREE/LOCAL_FREE 不
        # 改变该结论（A0 是 effective cost 的权威解析层）；AAF_COST_AUTH 存在
        # 且精确匹配也不能把本单元变成 paid fallback（A0 在 admission 边界按
        # 既有一次性语义 claim 该授权——本层不 bypass、不削弱、不复刻 A0，
        # 也不消耗超出 A0 既有语义的授权；paid escalation = 后续 A5 任务的
        # scope，本单元只拒绝并 fail closed）。
        active_routing_mod.restore_routing_env(overlay_saved)
        record = _emit(
            attempted=False,
            used=False,
            authorization_outcome=AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID,
            extra_notes=[
                "A0 Paid Guard admitted the fallback candidate as PAID "
                f"(decision={guard_decision!r}, cost_class="
                f"{guard_record.get('cost_class')!r}, required_scope="
                f"{guard_record.get('required_scope')!r}) — the exact "
                "task-scoped authorization was atomically claimed at the A0 "
                "admission boundary by the existing Paid Guard (one-time "
                "semantics preserved; A0 authority unmodified — this unit "
                "does not bypass, weaken or replicate it) BUT this "
                "FREE/LOCAL_FREE fallback runtime NEVER executes an "
                "authorized-paid / paid-classified fallback candidate: paid "
                "escalation is a later A5 unit's scope. No second model was "
                "invoked; no silent paid fallback (fail closed; the original "
                "stage failure is preserved)",
            ],
            extra_evidence=[
                f"authorized-paid candidate {selected!r} was NOT invoked: "
                "the authoritative A0 Paid Guard result "
                "ALLOWED_AUTHORIZED_PAID resolves paid semantics — this "
                "FREE/LOCAL_FREE fallback runtime refuses paid fallback "
                "execution; attempted=false, no second model invocation "
                "(FIX-001 admission fail-closed; AAF_COST_AUTH cannot "
                "convert this unit into paid fallback)",
            ],
        )
        return _no_attempt_result(output_dir, stage_agent, record)

    if guard_decision != AUTH_OUTCOME_ALLOWED_FREE:
        # A0 BLOCKED（缺精确 task-scoped 授权 / 成本未知 / 无法准入 / guard
        # record 异常）→ 不 invocation（unknown-paid 语义同样 fail closed）
        active_routing_mod.restore_routing_env(overlay_saved)
        blocked_notes = [
            "A0 Paid Guard denied the fallback candidate admission "
            f"(decision={guard_decision!r}, cost_class="
            f"{guard_record.get('cost_class')!r}, required_scope="
            f"{guard_record.get('required_scope')!r}) — no second model was "
            "invoked; no silent paid fallback (existing Paid Guard semantics "
            "remain authoritative)",
        ]
        if guard_record.get("authorization_present"):
            blocked_notes.append(
                "an authorization value was present but did not exactly match "
                "the fallback candidate's task/stage/model scope — fail closed"
            )
        record = _emit(
            attempted=False,
            used=False,
            authorization_outcome=AUTH_OUTCOME_BLOCKED,
            extra_notes=blocked_notes,
        )
        return _no_attempt_result(output_dir, stage_agent, record)

    # --- A0 Paid Guard ALLOWED_FREE：本 FREE/LOCAL_FREE 单元唯一允许进入
    #     第二模型 invocation 的准入结果 → invoke 恰一次 ---
    # FIX-002（Codex REQUEST_CHANGE 唯一 blocker 收口）：自此处起第二模型
    # invocation 真实发生（attempted=true 不可撤销、绝不假装未发生）——整个
    # invocation + authoritative audit closure 段是一个 exception-safe 的
    # fail-closed 边界：任何未预期的实现/runtime 异常（_emit 内部已按
    # Exception 全量收口为 audit closure 失败；此兜底再捕获边界内任何其他
    # 逃逸，如输出接受判定 / evidence 文本构造的意外异常）都被转换为显式
    # 结构化 fail-closed 结果（attempted=true / used=false /
    # audit_closure_error / overlay_saved）——绝不作为裸异常逃逸到 runner
    # 变成泛化 "layer error"（那会丢失 attempt 事实与 env 还原）；不发起
    # 第三模型、不重试另一个 fallback（单次调用点语义保持）。边界之外
    # （admission 之前、无 attempt 发生）的 pre-invocation 编程错误不在此
    # 捕获（原语义保持）。
    try:
        attempted = True
        used = False
        fb_output: str | None = None
        invocation_evidence: list[str] = []
        try:
            fb_output = invoke(stage_agent, prompt, workspace)
        except Exception as exc:  # noqa: BLE001 — invocation 失败 = fallback 失败
            invocation_evidence.append(
                f"fallback invocation of {selected!r} raised "
                f"{type(exc).__name__}: {_excerpt(str(exc))} — the failed fallback "
                "remains ONE attempt (used=false) and must not trigger another "
                "fallback (no chain/loop)"
            )
        if fb_output is not None:
            if _output_is_valid(fb_output):
                used = True
                invocation_evidence.append(
                    f"fallback invocation of {selected!r} produced an accepted "
                    "stage execution result (valid non-FRAMEWORK_ERROR output)"
                )
            else:
                invocation_evidence.append(
                    f"fallback invocation of {selected!r} produced an invalid "
                    "result (empty or FRAMEWORK_ERROR-prefixed output) — the "
                    "failed fallback remains ONE attempt (used=false) and must "
                    "not trigger another fallback (no chain/loop)"
                )

        extra_notes = [
            f"A0 Paid Guard admitted the fallback candidate as FREE "
            f"(decision={guard_decision!r}, cost_class="
            f"{guard_record.get('cost_class')!r}) — exactly one fallback "
            "invocation attempted (ALLOWED_FREE is the only admission this "
            "FREE/LOCAL_FREE unit executes; no authorization value involved)",
        ]
        record = _emit(
            attempted=attempted,
            used=used,
            authorization_outcome=AUTH_OUTCOME_ALLOWED_FREE,
            extra_notes=extra_notes,
            extra_evidence=invocation_evidence,
        )
        if record is None:
            # FIX-001（Codex BLOCKING #2 收口）+ FIX-002（异常类型全量覆盖）：
            # fallback invocation 已发生（attempted=true 不可撤销、绝不假装
            # 未发生），但权威 audit record 的组装/校验/持久化失败（现在
            # **任何**异常类型——含 RuntimeError / UnicodeError / 其他未预期
            # 实现/runtime 异常——都在 _emit 内被收口，绝不逃逸）→
            # authoritative audit closure 缺失 → 该 invocation 的输出**不得**
            # 被接受为成功 stage result（used=false；result_text=None 保留
            # 原始失败 = fail-closed framework result）；audit failure 经
            # audit_closure_error 显式 surface（绝不静默丢弃）；不发起第三
            # 模型、不重试另一个 fallback（单次调用点语义保持）。
            exc_desc = emit_failure[-1] if emit_failure else "unknown audit closure failure"
            audit_error = (
                f"authoritative fallback runtime audit closure FAILED after the "
                f"fallback invocation of {selected!r} was actually attempted "
                f"(attempted=true; {exc_desc}) — the fallback output is NOT "
                "accepted as the stage result (used=false, fail closed): no "
                "third model invocation and no further fallback retry will "
                "occur; the audit failure is surfaced here and to stderr, not "
                "silently discarded"
            )
            return {
                "result_text": None,
                "audit_record": None,
                "artifact_ref": None,
                "attempted": True,
                "used": False,
                "overlay_saved": overlay_saved,
                "audit_closure_error": audit_error,
            }
        return {
            "result_text": fb_output if used else None,
            "audit_record": record,
            "artifact_ref": {
                "authority": str(output_dir / ARTIFACT_FILENAME),
                "entry": stage_agent,
            },
            "attempted": attempted,
            "used": used,
            "overlay_saved": overlay_saved,
        }
    except Exception as exc:  # noqa: BLE001 — FIX-002 兜底 fail-closed 边界
        # post-invocation 边界内任何未被内层捕获的意外逃逸（不限于 audit
        # 组装/校验/持久化——含输出接受判定等任何后续步骤的未预期实现/runtime
        # 异常）：同样 fail closed——attempted=true / used=false（fallback
        # 输出**绝不**被接受）/ 真实异常经 audit_closure_error 显式 surface /
        # overlay_saved 返回供调用方还原 env；无第三模型、无进一步 fallback
        # retry；原始 stage 失败由 result_text=None 保留（runner 语义）。
        audit_error = (
            f"unexpected {type(exc).__name__}: {_excerpt(str(exc))} escaped "
            f"inside the post-invocation authoritative audit closure boundary "
            f"after the fallback invocation of {selected!r} was actually "
            "attempted (attempted=true) — the fallback output is NOT accepted "
            "as the stage result (used=false, fail closed): no third model "
            "invocation and no further fallback retry will occur; the failure "
            "is surfaced here and to stderr, not silently discarded; the "
            "fallback routing overlay is returned so the caller can restore "
            "the environment"
        )
        return {
            "result_text": None,
            "audit_record": None,
            "artifact_ref": None,
            "attempted": True,
            "used": False,
            "overlay_saved": overlay_saved,
            "audit_closure_error": audit_error,
        }


def _no_attempt_result(
    output_dir: Path,
    stage_agent: str,
    record: dict | None,
) -> dict:
    """未 attempt 分支的统一返回（result_text=None → runner 保留原始失败）。"""
    return {
        "result_text": None,
        "audit_record": record,
        "artifact_ref": (
            {"authority": str(output_dir / ARTIFACT_FILENAME), "entry": stage_agent}
            if record is not None
            else None
        ),
        "attempted": False,
        "used": False,
        "overlay_saved": None,
    }
