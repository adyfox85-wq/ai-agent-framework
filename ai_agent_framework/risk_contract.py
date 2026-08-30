"""AAF v0.5 A1 — Risk Classification Contract（foundation only）。

已决定的 v0.5 风险契约：
- 风险等级：LOW / MEDIUM / HIGH / CRITICAL（四个等级，不允许其他值）。
- 初始能力下限方向（tier 表示能力，T0 最强 → T4 最轻/本地级）：
    LOW:      executor T4，validator T4（可选），reviewer 通常无
    MEDIUM:   executor T3，validator T3，reviewer 可选
    HIGH:     executor T2，validator T2，reviewer T1/T2
    CRITICAL: executor T1，validator T1，reviewer T0/T1
- 自托管权威工作（runner / router / parser / lifecycle authority /
  report authority / model routing / cost gate / Paid Guard）至少 HIGH。
- 风险分类**不得**为分类本身发起额外 LLM 调用——本模块全部为确定性纯逻辑
  （无 I/O、无网络、无子进程）。

本任务不把分类接入 live 执行；A2/A3 路由在此契约之上消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model_registry import CAPABILITY_TIERS

# ---------------------------------------------------------------------------
# 风险等级（已决定的 v0.5 设计；不得扩展）
# ---------------------------------------------------------------------------

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"
RISK_CLASSES = (RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL)
RISK_SEVERITY = {cls: i for i, cls in enumerate(RISK_CLASSES)}

ROLE_EXECUTOR = "executor"
ROLE_VALIDATOR = "validator"
ROLE_REVIEWER = "reviewer"


# ---------------------------------------------------------------------------
# 初始能力下限（已接受的 v0.5 设计）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskFloor:
    """某风险等级的能力下限 + reviewer 候选集合。

    - executor：必须的 tier 下限（不允许 None）。
    - validator：None = 该角色无下限要求（角色可选或通常不出现）；
      非 None = 该角色**若出现**必须满足的最低 tier。
    - reviewer_tiers：该等级**允许**出现的 reviewer tier 候选集合
      （确定性有序 tuple；空 = 该等级无固定 reviewer 要求，配合
      ``RISK_ROLE_OPTIONALITY`` 表达「通常无 / 可选」）。
      语义：reviewer 候选**必须**是集合内的 tier（T0 最强）；集合外的
      tier（更强或更弱）都不是该等级的合法 reviewer。
    通用语义：tier 表示能力（T0 最强）；floor 满足 = candidate 能力 >= floor
    （``model_registry.tier_satisfies``）。
    """

    executor: str
    validator: str | None = None
    reviewer_tiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.executor not in CAPABILITY_TIERS:
            raise ValueError(f"invalid executor floor tier: {self.executor!r}")
        if self.validator is not None and self.validator not in CAPABILITY_TIERS:
            raise ValueError(f"invalid validator floor tier: {self.validator!r}")
        for tier in self.reviewer_tiers:
            if tier not in CAPABILITY_TIERS:
                raise ValueError(
                    f"invalid reviewer tier: {tier!r} (allowed: {CAPABILITY_TIERS})"
                )


# 初始能力下限映射 + reviewer 候选集合（Accepted v0.5 design —— 逐项对应用户已接受的方向）
RISK_FLOORS: dict[str, RiskFloor] = {
    RISK_LOW: RiskFloor(executor="T4", validator="T4", reviewer_tiers=()),
    RISK_MEDIUM: RiskFloor(executor="T3", validator="T3", reviewer_tiers=()),
    RISK_HIGH: RiskFloor(executor="T2", validator="T2", reviewer_tiers=("T1", "T2")),
    RISK_CRITICAL: RiskFloor(executor="T1", validator="T1", reviewer_tiers=("T0", "T1")),
}

# 角色可选性（「validator T4 / optional」「reviewer 通常 none / optional」的精确表示）
RISK_ROLE_OPTIONALITY: dict[str, frozenset[str]] = {
    RISK_LOW: frozenset({ROLE_VALIDATOR, ROLE_REVIEWER}),
    RISK_MEDIUM: frozenset({ROLE_REVIEWER}),
    RISK_HIGH: frozenset(),
    RISK_CRITICAL: frozenset(),
}


def floor_for(risk_class: str) -> RiskFloor:
    """风险等级 → 能力下限（确定性）。未知风险 → ValueError（fail closed）。"""
    if risk_class not in RISK_SEVERITY:
        raise ValueError(f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})")
    return RISK_FLOORS[risk_class]


def reviewer_allowed(risk_class: str, tier: str) -> bool:
    """某风险等级的合法 reviewer tier 判定（确定性，fail closed）。

    - 未知 risk_class → ValueError（契约不承诺未知等级的 reviewer）。
    - 未知 tier → False（未验证能力不得视为 reviewer 候选；与
      ``model_registry.tier_satisfies`` 对未知 tier 的行为一致）。
    - 空候选集合 → False（该等级不要求 reviewer / reviewer 通常不出现）。
    """
    if risk_class not in RISK_SEVERITY:
        raise ValueError(f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})")
    return tier in RISK_FLOORS[risk_class].reviewer_tiers


def risk_at_least(risk_class: str, floor: str) -> bool:
    """``risk_class`` 是否 >= ``floor``（LOW < MEDIUM < HIGH < CRITICAL）。"""
    if risk_class not in RISK_SEVERITY:
        raise ValueError(f"unknown risk class: {risk_class!r}")
    if floor not in RISK_SEVERITY:
        raise ValueError(f"unknown risk floor: {floor!r}")
    return RISK_SEVERITY[risk_class] >= RISK_SEVERITY[floor]


def max_risk(risks: Iterable[str]) -> str:
    """组合风险：取输入中最高的等级（确定性）。空输入 / 未知等级 → ValueError。"""
    values = list(risks)
    if not values:
        raise ValueError("max_risk requires at least one risk class")
    unknown = [r for r in values if r not in RISK_SEVERITY]
    if unknown:
        raise ValueError(f"unknown risk class(es): {unknown}")
    return max(values, key=lambda r: RISK_SEVERITY[r])


# ---------------------------------------------------------------------------
# 自托管权威区域（至少 HIGH）
# ---------------------------------------------------------------------------

# 影响自托管权威的改动区域（已决定的设计；覆盖 runner / router / parser /
# lifecycle / report / model routing / cost gate）
SELF_HOSTING_AUTHORITY_AREAS = frozenset(
    (
        "runner",
        "router",
        "parser",
        "lifecycle_authority",
        "report_authority",
        "model_routing",
        "cost_gate",
    )
)
SELF_HOSTING_MIN_RISK = RISK_HIGH


def risk_for_authority_area(area: str) -> str:
    """自托管权威区域的确定性风险判定。

    已知区域 → 至少 ``SELF_HOSTING_MIN_RISK``（HIGH）。未知区域 → ValueError
    （fail closed：契约不承诺未知区域的风险，绝不静默降级）。
    """
    if area not in SELF_HOSTING_AUTHORITY_AREAS:
        raise ValueError(
            f"unknown authority area: {area!r} "
            f"(known: {sorted(SELF_HOSTING_AUTHORITY_AREAS)})"
        )
    return SELF_HOSTING_MIN_RISK


# ---------------------------------------------------------------------------
# 已决定的 v0.5 路由优先级（契约常量；A2/A3 消费）
# ---------------------------------------------------------------------------

# safety/correctness > quality threshold > cash/resource cost > elapsed time
ROUTING_PRIORITY = (
    "safety_correctness",
    "quality_threshold",
    "cash_resource_cost",
    "elapsed_time",
)

# 能力充分性必须先于成本优化判定（已决定的设计；本任务只登记契约，
# 不实现任何选择/优化逻辑）
CAPABILITY_SUFFICIENCY_BEFORE_COST_OPTIMIZATION = True
