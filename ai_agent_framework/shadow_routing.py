"""AAF v0.5 A2 — Shadow Routing: deterministic shadow-selection engine（observation only）。

本模块回答一个**假设性**问题：

    "If AAF were allowed to choose a model for this stage, which qualified
    candidate would it select?"

Shadow selection 语义边界（与 TASK: AAF-v0.5-A2-SHADOW-ROUTING-001 一致）：
- **hypothetical**：计算结果只回答「影子决策」，不产生任何执行动作。
- **non-authoritative**：本模块不是 runner / router / lifecycle / report 的
  执行权威；没有任何 live 路径 import 或消费它（由隔离测试锁定）。
- **zero effect on actual execution**：本模块不修改 Hermes `-m`、provider
  override、WorkBuddy --model、Codex model、runner 执行命令、active Route、
  Paid Guard 授权或任何 live provider invocation。
- 本模块**纯**：无 I/O、无网络、无子进程、无 LLM 调用、无环境变量读取；
  相同输入 → 完全相同输出（确定性）。

消费的 A1 契约（复用，不复制）：
- ``model_registry``：``RegistryEntry`` / ``RuntimeQualification`` /
  ``tier_satisfies`` / ``is_usable_candidate`` / ``FREE_OF_COST_CLASSES`` /
  locality 词汇 / cost 词汇（``model_observation.COST_CLASSES``）。
- ``risk_contract``：``RISK_CLASSES`` / ``RiskFloor`` / ``RISK_FLOORS`` /
  ``floor_for`` / ``reviewer_allowed`` / role 词汇。

本任务不实现（显式 anti-pullback）：
- Hermes free automatic routing / 实际模型切换 / WorkBuddy 经济路由 /
  自动 fallback / Cost Gate UX / 观测-校准循环 / 动态 registry 健康管理 /
  健康轮询 / 后台监控 / provider probe / 自动隔离 / 动态降级 / 基准循环。

经济排序规则（确定性；不发明价格；Requirement 7）：
- 只使用 registry 的 cost_class 分类（LOCAL_FREE / FREE / FREE_PROMO /
  PAID / UNKNOWN），不发明数值价格。
- 已知经济成本排名：零现金类 {LOCAL_FREE, FREE, FREE_PROMO}（= A1
  ``FREE_OF_COST_CLASSES``，同为 0 现金 → **并列 rank 0**）< PAID（rank 1）。
- **UNKNOWN 成本的保守规则**：任何已知 cost_class 都排在 UNKNOWN 之前；
  UNKNOWN **永远不因成本获胜**。理由：``unknown ≠ free``（A1/RW-030
  纪律）——把 UNKNOWN 当作「可能更便宜」就是假设它可能是免费，属于伪造
  排序；A0 Paid Guard 同样把未知成本按 PAID_OR_UNKNOWN fail-closed 处理。
  当剩余候选全部 UNKNOWN（成本无可比较）时，成本维度不产生结论，
  由 locality / key 确定性 tie-break 决定，决策记录如实说明。
- 本地偏好（locality：local < remote < unknown）只是**次级 tie-break**，
  严格排在能力充分性与 qualification 之后（Requirement 8：local/free
  preference subordinate to sufficiency and qualification）。

排除原因词汇（Requirement 14）：
- ROLE_NOT_APPLICABLE：候选的 applicable_agents 不适用于本 stage agent
  （applicable_agents 非空且不含 stage_agent）。
- CAPABILITY_INSUFFICIENT：tier 未知（None）或已知但低于所需下限 /
  不在 reviewer 允许集合内（fail closed：未验证能力 ≠ 充分）。
- NOT_QUALIFIED：qualification.status == not_qualified。
- QUALIFICATION_UNKNOWN：qualification.status == unknown（**绝不静默
  变成 qualified**）。
- AUXILIARY_ONLY（executor 角色；TASK: AAF-v0.5-A3-HERMES-EXECUTOR-
  QUALIFICATION-FIX-001）：候选 usable（capability + QUALIFIED）但
  qualification.scope == auxiliary——evidence 只覆盖 auxiliary /
  端点级上下文（vision/compression/title/web_extract/summarization 槽位、
  本地 OpenAI-compatible 端点直连等），**绝不构成主 executor 资格**
  （真实 Hermes main-chat invocation `hermes ... -m qwen3:4b
  --provider custom` = HTTP 400 实证）。
- MAIN_INVOCATION_UNPROVEN（executor 角色）：候选 usable 但
  qualification.scope == unknown——evidence 未声明 / 未覆盖真实主调用路径；
  fail closed：未证明主调用能力的候选绝不当作 executor 可执行。
- UNSUPPORTED：registry 数据契约在消费时不成立（值不是 RegistryEntry）。

Executor 主调用资格规则（Requirement：executor qualification 必须由覆盖该
agent 真实主调用路径的 evidence 支持）：executor 角色的候选除通过
capability + qualification 双闸（is_usable_candidate）外，还必须
qualification.scope == main（A1 词汇；默认 unknown fail closed）。本规则
只作用于 executor 角色——它是唯一会被 active routing 真实选择/改变执行的
角色；validator / reviewer 的 hypothetical 选择不受影响。复用同一 A1
qualification 契约，不创建第二套资格系统。

FREE 只可能是成本属性；**FREE 绝不产生 qualification**（Requirement 13）：
候选必须 qualification.status == QUALIFIED 才可进入经济选择
（经 ``is_usable_candidate`` 判定，A1 契约原样消费）。

No-candidate 语义（Requirement 9）：没有候选满足契约时，
``selected=None``、``selection_reason=None``、
``no_candidate_reason="NO_SHADOW_CANDIDATE: ..."``——无 silent fallback、
无 forced choice。

Schema 版本（Requirement 17 保持 A1 严格性）：``decision_from_dict`` 只接受
真实 ``int`` 且值 == ``SCHEMA_VERSION``；bool / float / str / 容器 / 缺失 /
None / 不支持版本一律 ValueError（fail closed，绝不静默强转）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_observation import COST_CLASS_PAID, COST_CLASS_UNKNOWN
from .model_registry import (
    FREE_OF_COST_CLASSES,
    LOCALITY_LOCAL,
    LOCALITY_REMOTE,
    LOCALITY_UNKNOWN,
    QUAL_SCOPE_AUXILIARY,
    QUAL_SCOPE_MAIN,
    QUAL_STATUS_NOT_QUALIFIED,
    RegistryEntry,
    is_usable_candidate,
    tier_satisfies,
)
from .risk_contract import (
    RISK_CLASSES,
    ROLE_EXECUTOR,
    ROLE_REVIEWER,
    ROLE_VALIDATOR,
    floor_for,
    reviewer_allowed,
)

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

# 支持的 stage 角色（复用 risk_contract 词汇，不另造）
STAGE_ROLES = (ROLE_EXECUTOR, ROLE_VALIDATOR, ROLE_REVIEWER)

# ---------------------------------------------------------------------------
# 排除原因词汇（Requirement 14）
# ---------------------------------------------------------------------------

EXCL_ROLE_NOT_APPLICABLE = "ROLE_NOT_APPLICABLE"
EXCL_CAPABILITY_INSUFFICIENT = "CAPABILITY_INSUFFICIENT"
EXCL_NOT_QUALIFIED = "NOT_QUALIFIED"
EXCL_QUALIFICATION_UNKNOWN = "QUALIFICATION_UNKNOWN"
EXCL_AUXILIARY_ONLY = "AUXILIARY_ONLY"
EXCL_MAIN_INVOCATION_UNPROVEN = "MAIN_INVOCATION_UNPROVEN"
EXCL_UNSUPPORTED = "UNSUPPORTED"
EXCLUSION_REASONS = (
    EXCL_ROLE_NOT_APPLICABLE,
    EXCL_CAPABILITY_INSUFFICIENT,
    EXCL_NOT_QUALIFIED,
    EXCL_QUALIFICATION_UNKNOWN,
    EXCL_AUXILIARY_ONLY,
    EXCL_MAIN_INVOCATION_UNPROVEN,
    EXCL_UNSUPPORTED,
)

# ---------------------------------------------------------------------------
# No-candidate 语义（Requirement 9）
# ---------------------------------------------------------------------------

NO_SHADOW_CANDIDATE = "NO_SHADOW_CANDIDATE"

# 选择原因 / 决定维度（确定性 token；供审计）
REASON_SOLE_ELIGIBLE = "sole_eligible_candidate"
REASON_LOWEST_KNOWN_COST = "lowest_known_economic_cost"
REASON_COST_TIE_LOCALITY = "cost_tie_locality_preference"
REASON_COST_LOCALITY_TIE_KEY = "cost_locality_tie_key_tiebreak"

DECIDED_SOLE_ELIGIBLE = "sole_eligible"
DECIDED_BY_COST = "cost"
DECIDED_BY_LOCALITY = "locality"
DECIDED_BY_KEY = "key"

# ---------------------------------------------------------------------------
# 确定性排序维度（rank 越小越优先；全部为分类 rank，不发明数值价格）
# ---------------------------------------------------------------------------

# 经济 rank：零现金类并列 0（LOCAL_FREE / FREE / FREE_PROMO 同为 0 现金，
# 依据 A1 FREE_OF_COST_CLASSES）；PAID = 1；UNKNOWN = 2。
# 保守规则：已知成本 > UNKNOWN（unknown ≠ free；UNKNOWN 永不因成本获胜）。
_COST_ECONOMIC_RANK = {
    cost_class: 0 for cost_class in sorted(FREE_OF_COST_CLASSES)
}
_COST_ECONOMIC_RANK[COST_CLASS_PAID] = 1
_COST_ECONOMIC_RANK[COST_CLASS_UNKNOWN] = 2

# locality 偏好（次级 tie-break；strictly subordinate to sufficiency/qualification）
_LOCALITY_RANK = {
    LOCALITY_LOCAL: 0,
    LOCALITY_REMOTE: 1,
    LOCALITY_UNKNOWN: 2,
}


def economic_rank(cost_class: str) -> int:
    """已知 cost_class → 经济 rank（确定性；越小越优先）。"""
    rank = _COST_ECONOMIC_RANK.get(cost_class)
    if rank is None:
        # RegistryEntry 构造已保证 cost_class ∈ COST_CLASSES；
        # 防御性 fail closed：未知成本分类不得参与排序。
        raise ValueError(f"invalid cost_class: {cost_class!r}")
    return rank


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExclusionRecord:
    """单个候选的排除记录（可审计）。"""

    candidate: str  # registry key（model@provider 或 agent:<agent>）
    reason: str  # EXCLUSION_REASONS 成员


@dataclass(frozen=True)
class ShadowDecision:
    """结构化影子决策（Requirement 3：含足够审计信息）。"""

    schema_version: int
    risk_class: str
    role: str
    stage_agent: str
    required_floor: str | None  # executor/validator 的下限 tier；reviewer → None
    allowed_tiers: tuple[str, ...]  # reviewer 允许集合；executor/validator → ()
    candidates_considered: tuple[str, ...]  # 排序后的 registry keys
    excluded: tuple[ExclusionRecord, ...]  # 排序后的排除记录
    eligible: tuple[str, ...]  # 排序后的合格候选 keys
    selected: str | None  # 影子选中 key；无合格候选 → None
    selection_reason: str | None  # REASON_* token；无候选 → None
    deciding_dimension: str | None  # DECIDED_* token；无候选 → None
    no_candidate_reason: str | None  # 无候选时 = "NO_SHADOW_CANDIDATE: ..."


# ---------------------------------------------------------------------------
# 过滤管线（Requirement 6：A 适用性 → B 能力充分性 → C qualification →
# C2 executor 主调用 scope（executor 角色）→ D 经济偏好 → E 确定性 tie-break）
# ---------------------------------------------------------------------------


def _capability_sufficient(
    entry: RegistryEntry,
    role: str,
    risk_class: str,
    required_floor: str | None,
) -> bool:
    """能力充分性（B）：executor/validator 用 tier_satisfies（下限）；
    reviewer 用 reviewer_allowed（集合成员，T0 最强；集合外更强也更弱都拒绝）。

    tier=None 一律 False（fail closed：未验证能力 ≠ 充分），由 A1 纯函数
    tier_satisfies / reviewer_allowed 对未知 tier 的既有行为保证。
    """
    if role == ROLE_REVIEWER:
        return reviewer_allowed(risk_class, entry.capability_tier)
    if required_floor is None:
        # 契约未来可能出现的「无下限」角色：只要求 tier 已知。
        return entry.capability_tier is not None
    return tier_satisfies(entry.capability_tier, required_floor)


def _exclude_reason_for_unqualified(entry: RegistryEntry) -> str:
    """is_usable_candidate == False 时，区分 NOT_QUALIFIED /
    QUALIFICATION_UNKNOWN（qualified 不可能到达这里：tier 已知 + qualified
    即 is_usable_candidate True）。"""
    status = entry.qualification.status
    if status == QUAL_STATUS_NOT_QUALIFIED:
        return EXCL_NOT_QUALIFIED
    return EXCL_QUALIFICATION_UNKNOWN


def select_shadow_candidate(
    risk_class: str,
    role: str,
    stage_agent: str,
    registry: dict[str, RegistryEntry],
) -> ShadowDecision:
    """确定性影子选择（纯函数；无 I/O / 网络 / LLM / 副作用）。

    输入：
    - ``risk_class``：RISK_CLASSES 成员（LOW / MEDIUM / HIGH / CRITICAL）。
    - ``role``：STAGE_ROLES 成员（executor / validator / reviewer）。
    - ``stage_agent``：stage 的 agent 身份（如 "hermes"；非空 str）。
    - ``registry``：registry key → RegistryEntry（A1 契约；key 即
      ``entry.key()``，与 ``registry_from_dict`` 的键一致约束对齐）。

    未知 risk / role / 空 stage_agent / 非 dict registry → ValueError
    （fail closed：契约不承诺未知输入的决策）。registry 内**值**不是
    RegistryEntry → 该候选以 UNSUPPORTED 排除（可审计，不中断整体决策）。

    结果与候选输入顺序无关：全部列表排序、排序键含 key 全序 tie-break。
    """
    if risk_class not in RISK_CLASSES:
        raise ValueError(
            f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})"
        )
    if role not in STAGE_ROLES:
        raise ValueError(f"unknown role: {role!r} (allowed: {STAGE_ROLES})")
    if not (isinstance(stage_agent, str) and stage_agent.strip()):
        raise ValueError("stage_agent must be a non-empty string")
    if not isinstance(registry, dict):
        raise ValueError(f"registry must be a dict, got {type(registry).__name__}")

    floor = floor_for(risk_class)
    if role == ROLE_EXECUTOR:
        required_floor: str | None = floor.executor
        allowed_tiers: tuple[str, ...] = ()
    elif role == ROLE_VALIDATOR:
        required_floor = floor.validator
        allowed_tiers = ()
    else:  # reviewer
        required_floor = None
        allowed_tiers = floor.reviewer_tiers

    considered: list[str] = []
    excluded: list[ExclusionRecord] = []
    eligible: list[str] = []

    # 确定性迭代：候选按 key 排序处理（与输入插入顺序无关）
    for key, entry in sorted(registry.items()):
        considered.append(key)
        if not isinstance(entry, RegistryEntry):
            excluded.append(ExclusionRecord(key, EXCL_UNSUPPORTED))
            continue
        # A. stage/role 适用性（applicable_agents 空 = 未知/通用 → 适用）
        if entry.applicable_agents and stage_agent not in entry.applicable_agents:
            excluded.append(ExclusionRecord(key, EXCL_ROLE_NOT_APPLICABLE))
            continue
        # B. 能力充分性（先于成本；tier 未知 → fail closed）
        if not _capability_sufficient(entry, role, risk_class, required_floor):
            excluded.append(ExclusionRecord(key, EXCL_CAPABILITY_INSUFFICIENT))
            continue
        # C. qualification（A1 is_usable_candidate 原样消费：tier 已知 +
        #    qualified 双满足；FREE 不参与）
        if not is_usable_candidate(entry):
            excluded.append(
                ExclusionRecord(key, _exclude_reason_for_unqualified(entry))
            )
            continue
        # C2. executor 主调用资格（TASK: AAF-v0.5-A3-HERMES-EXECUTOR-
        #     QUALIFICATION-FIX-001）：executor 角色（唯一会被 active routing
        #     真实选择/改变执行的角色）除 capability + qualification 双闸外，
        #     还必须 qualification.scope == main——evidence 必须覆盖该 agent 的
        #     真实主调用路径（Hermes = main-chat invocation）。auxiliary-only /
        #     端点级 / 未声明主调用 scope 的 evidence 绝不构成主 executor 资格
        #     （fail closed：unknown ≠ main；绝不静默提升）。validator /
        #     reviewer 角色（hypothetical only）不经此闸。
        if role == ROLE_EXECUTOR:
            scope = entry.qualification.scope
            if scope == QUAL_SCOPE_AUXILIARY:
                excluded.append(ExclusionRecord(key, EXCL_AUXILIARY_ONLY))
                continue
            if scope != QUAL_SCOPE_MAIN:
                excluded.append(ExclusionRecord(key, EXCL_MAIN_INVOCATION_UNPROVEN))
                continue
        eligible.append(key)

    if not eligible:
        detail = (
            f"registry empty — no candidates considered"
            if not considered
            else f"{len(considered)} candidate(s) considered, 0 eligible "
            f"(all excluded by role/capability/qualification contract)"
        )
        return ShadowDecision(
            schema_version=SCHEMA_VERSION,
            risk_class=risk_class,
            role=role,
            stage_agent=stage_agent,
            required_floor=required_floor,
            allowed_tiers=allowed_tiers,
            candidates_considered=tuple(sorted(considered)),
            excluded=tuple(sorted(excluded, key=lambda r: (r.candidate, r.reason))),
            eligible=(),
            selected=None,
            selection_reason=None,
            deciding_dimension=None,
            no_candidate_reason=f"{NO_SHADOW_CANDIDATE}: {detail}",
        )

    # D. 经济偏好 + E. 确定性 tie-break（排序键 = (经济 rank, locality rank, key)，
    #    key 全序保证输入顺序无关）
    ranked = sorted(
        eligible,
        key=lambda k: (
            economic_rank(registry[k].cost_class),
            _LOCALITY_RANK[registry[k].locality],
            k,
        ),
    )
    winner = ranked[0]
    if len(ranked) == 1:
        reason = REASON_SOLE_ELIGIBLE
        dimension = DECIDED_SOLE_ELIGIBLE
    else:
        runner_up = ranked[1]
        winner_rank = economic_rank(registry[winner].cost_class)
        runner_rank = economic_rank(registry[runner_up].cost_class)
        if winner_rank != runner_rank:
            reason = REASON_LOWEST_KNOWN_COST
            dimension = DECIDED_BY_COST
        elif _LOCALITY_RANK[registry[winner].locality] != _LOCALITY_RANK[
            registry[runner_up].locality
        ]:
            reason = REASON_COST_TIE_LOCALITY
            dimension = DECIDED_BY_LOCALITY
        else:
            reason = REASON_COST_LOCALITY_TIE_KEY
            dimension = DECIDED_BY_KEY

    return ShadowDecision(
        schema_version=SCHEMA_VERSION,
        risk_class=risk_class,
        role=role,
        stage_agent=stage_agent,
        required_floor=required_floor,
        allowed_tiers=allowed_tiers,
        candidates_considered=tuple(sorted(considered)),
        excluded=tuple(sorted(excluded, key=lambda r: (r.candidate, r.reason))),
        eligible=tuple(sorted(eligible)),
        selected=winner,
        selection_reason=reason,
        deciding_dimension=dimension,
        no_candidate_reason=None,
    )


# ---------------------------------------------------------------------------
# 序列化（纯；未知枚举 → ValueError，fail closed；schema 版本保持 A1 严格性）
# ---------------------------------------------------------------------------


def decision_to_dict(decision: ShadowDecision) -> dict[str, Any]:
    return {
        "schema_version": decision.schema_version,
        "risk_class": decision.risk_class,
        "role": decision.role,
        "stage_agent": decision.stage_agent,
        "required_floor": decision.required_floor,
        "allowed_tiers": list(decision.allowed_tiers),
        "candidates_considered": list(decision.candidates_considered),
        "excluded": [
            {"candidate": r.candidate, "reason": r.reason} for r in decision.excluded
        ],
        "eligible": list(decision.eligible),
        "selected": decision.selected,
        "selection_reason": decision.selection_reason,
        "deciding_dimension": decision.deciding_dimension,
        "no_candidate_reason": decision.no_candidate_reason,
    }


def decision_from_dict(data: dict[str, Any]) -> ShadowDecision:
    """从 dict 重建决策（schema 版本 fail closed，与 A1 registry_from_dict
    同一严格性：仅真实 int == SCHEMA_VERSION 被接受）。"""
    if not isinstance(data, dict):
        raise ValueError("decision dict must be a mapping")
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported decision schema_version: {schema_version!r} "
            f"(supported: {SCHEMA_VERSION})"
        )
    risk_class = data.get("risk_class")
    if risk_class not in RISK_CLASSES:
        raise ValueError(f"unknown risk class: {risk_class!r}")
    role = data.get("role")
    if role not in STAGE_ROLES:
        raise ValueError(f"unknown role: {role!r}")
    excluded = tuple(
        ExclusionRecord(
            candidate=item["candidate"],
            reason=item["reason"],
        )
        for item in data.get("excluded", [])
    )
    for rec in excluded:
        if rec.reason not in EXCLUSION_REASONS:
            raise ValueError(f"unknown exclusion reason: {rec.reason!r}")
    return ShadowDecision(
        schema_version=schema_version,
        risk_class=risk_class,
        role=role,
        stage_agent=data.get("stage_agent"),
        required_floor=data.get("required_floor"),
        allowed_tiers=tuple(data.get("allowed_tiers", [])),
        candidates_considered=tuple(data.get("candidates_considered", [])),
        excluded=excluded,
        eligible=tuple(data.get("eligible", [])),
        selected=data.get("selected"),
        selection_reason=data.get("selection_reason"),
        deciding_dimension=data.get("deciding_dimension"),
        no_candidate_reason=data.get("no_candidate_reason"),
    )
