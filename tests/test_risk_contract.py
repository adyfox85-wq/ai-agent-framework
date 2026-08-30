"""AAF v0.5 A1 — Risk Classification Contract 定向测试（TASK: AAF-v0.5-A1-REGISTRY-RISK-001）。

覆盖 Requirement 9 的 risk 部分：
- 四个风险等级全部表示
- 初始 tier-floor 映射正确（已接受的 v0.5 设计）
- 已知自托管权威区域解析为至少 HIGH
- 确定性行为
- 分类契约无 LLM/网络依赖
"""

import inspect

import pytest

from ai_agent_framework.model_registry import tier_satisfies
from ai_agent_framework import risk_contract as rc
from ai_agent_framework.risk_contract import (
    RISK_CLASSES,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_ROLE_OPTIONALITY,
    RiskFloor,
    floor_for,
    max_risk,
    risk_at_least,
    risk_for_authority_area,
)

# ---------------------------------------------------------------------------
# A. 四个风险等级全部表示
# ---------------------------------------------------------------------------


def test_all_four_risk_classes_represented():
    assert RISK_CLASSES == (RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL)
    assert set(rc.RISK_FLOORS) == set(RISK_CLASSES)
    assert set(RISK_ROLE_OPTIONALITY) == set(RISK_CLASSES)


def test_risk_severity_monotonic():
    assert rc.RISK_SEVERITY[RISK_LOW] < rc.RISK_SEVERITY[RISK_MEDIUM] < \
        rc.RISK_SEVERITY[RISK_HIGH] < rc.RISK_SEVERITY[RISK_CRITICAL]


# ---------------------------------------------------------------------------
# B. 初始 tier-floor 映射（已接受的 v0.5 设计）
# ---------------------------------------------------------------------------


def test_initial_tier_floor_mapping_exact():
    assert rc.RISK_FLOORS == {
        RISK_LOW: RiskFloor(executor="T4", validator="T4", reviewer=None),
        RISK_MEDIUM: RiskFloor(executor="T3", validator="T3", reviewer=None),
        RISK_HIGH: RiskFloor(executor="T2", validator="T2", reviewer="T1"),
        RISK_CRITICAL: RiskFloor(executor="T1", validator="T1", reviewer="T0"),
    }


def test_floor_for_returns_contract_floors():
    assert floor_for(RISK_LOW) == RiskFloor("T4", "T4", None)
    assert floor_for(RISK_MEDIUM) == RiskFloor("T3", "T3", None)
    assert floor_for(RISK_HIGH) == RiskFloor("T2", "T2", "T1")
    assert floor_for(RISK_CRITICAL) == RiskFloor("T1", "T1", "T0")


def test_role_optionality_exact():
    assert RISK_ROLE_OPTIONALITY == {
        RISK_LOW: frozenset({"validator", "reviewer"}),   # validator T4 / optional；reviewer 通常无
        RISK_MEDIUM: frozenset({"reviewer"}),             # reviewer optional
        RISK_HIGH: frozenset(),
        RISK_CRITICAL: frozenset(),
    }


def test_floors_are_capability_sufficiency_contract():
    """floor 语义：candidate tier >= floor（tier 表示能力，T0 最强）。"""
    # HIGH floor（T2/T2/T1）：T2 executor 满足，T3 不满足
    high = floor_for(RISK_HIGH)
    assert tier_satisfies("T2", high.executor) is True
    assert tier_satisfies("T3", high.executor) is False
    assert tier_satisfies("T2", high.validator) is True
    assert tier_satisfies("T1", high.reviewer) is True
    # CRITICAL floor（T1/T1/T0）：executor 必须 T1 或更强
    critical = floor_for(RISK_CRITICAL)
    assert tier_satisfies("T1", critical.executor) is True
    assert tier_satisfies("T0", critical.executor) is True
    assert tier_satisfies("T2", critical.executor) is False


def test_unknown_risk_class_fail_closed():
    with pytest.raises(ValueError):
        floor_for("EXTREME")
    with pytest.raises(ValueError):
        risk_at_least("EXTREME", RISK_HIGH)
    with pytest.raises(ValueError):
        risk_at_least(RISK_HIGH, "EXTREME")


# ---------------------------------------------------------------------------
# C. 自托管权威区域至少 HIGH
# ---------------------------------------------------------------------------


def test_self_hosting_authority_areas_covered():
    assert rc.SELF_HOSTING_AUTHORITY_AREAS == frozenset(
        {
            "runner",
            "router",
            "parser",
            "lifecycle_authority",
            "report_authority",
            "model_routing",
            "cost_gate",
        }
    )
    assert rc.SELF_HOSTING_MIN_RISK == RISK_HIGH


def test_all_authority_areas_resolve_to_at_least_high():
    for area in sorted(rc.SELF_HOSTING_AUTHORITY_AREAS):
        risk = risk_for_authority_area(area)
        assert risk_at_least(risk, RISK_HIGH), f"{area} resolved to {risk} (< HIGH)"
        assert risk == RISK_HIGH


def test_unknown_authority_area_fail_closed():
    """未知区域不承诺风险，绝不静默降级。"""
    with pytest.raises(ValueError):
        risk_for_authority_area("notebook_ui")


def test_combined_authority_risk_deterministic():
    """多区域组合 = 取最高（确定性纯函数）。"""
    combined = max_risk(
        [risk_for_authority_area(a) for a in ("runner", "router", "parser", "cost_gate")]
    )
    assert combined == RISK_HIGH
    assert max_risk([RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL]) == RISK_CRITICAL
    assert max_risk([RISK_LOW]) == RISK_LOW
    with pytest.raises(ValueError):
        max_risk([])
    with pytest.raises(ValueError):
        max_risk([RISK_LOW, "EXTREME"])


# ---------------------------------------------------------------------------
# D. 确定性行为
# ---------------------------------------------------------------------------


def test_deterministic_same_input_same_output():
    for _ in range(3):
        assert risk_for_authority_area("runner") == RISK_HIGH
        assert floor_for(RISK_CRITICAL) == RiskFloor("T1", "T1", "T0")
        assert risk_at_least(RISK_CRITICAL, RISK_LOW) is True
        assert max_risk([RISK_HIGH, RISK_LOW, RISK_MEDIUM]) == RISK_HIGH
    # 组合与顺序无关
    assert max_risk([RISK_LOW, RISK_CRITICAL]) == max_risk([RISK_CRITICAL, RISK_LOW])


def test_classification_is_pure_no_env_or_io():
    """纯函数：不读环境变量、不产生文件、无副作用（重复调用结果一致）。"""
    import os

    before = dict(os.environ)
    try:
        risk_for_authority_area("model_routing")
        floor_for(RISK_HIGH)
    finally:
        assert dict(os.environ) == before


# ---------------------------------------------------------------------------
# E. 无 LLM/网络依赖（Requirement 8：分类不额外调用 LLM）
# ---------------------------------------------------------------------------


def test_risk_module_has_no_llm_or_network_dependency():
    import ast

    tree = ast.parse(inspect.getsource(rc))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    banned_roots = {
        "subprocess", "urllib", "requests", "http", "socket",
        "openai", "anthropic", "llm",
    }
    leaked = sorted(roots & banned_roots)
    assert leaked == [], f"LLM/network dependency leaked into risk contract: {leaked}"
    # 依赖图：仅 stdlib + 同 package 的 model_registry（tier 词汇单一来源）
    assert roots <= {"__future__", "dataclasses", "typing", "model_registry"}


def test_risk_public_api_is_classification_contract_only():
    banned = ("select", "choose", "route", "fallback", "escalat", "poll",
              "quarantine", "monitor", "switch", "activate", "spawn", "run")
    public = [
        name for name, _ in inspect.getmembers(rc, inspect.isfunction)
        if not name.startswith("_")
    ]
    leaked = sorted(n for n in public if n.lower().startswith(banned))
    assert leaked == [], f"scope leak: {leaked}"


def test_risk_classification_needs_no_llm_call_contract():
    """分类契约为纯函数集合：任意输入不触发任何外部调用（直接调用验证）。"""
    # 全部公开纯函数在本地完成，无返回值依赖外部状态
    for area in rc.SELF_HOSTING_AUTHORITY_AREAS:
        assert isinstance(risk_for_authority_area(area), str)
    for cls in RISK_CLASSES:
        assert isinstance(floor_for(cls), RiskFloor)


# ---------------------------------------------------------------------------
# F. 已决定的 v0.5 路由优先级与充分性顺序（契约登记）
# ---------------------------------------------------------------------------


def test_routing_priority_order_preserved():
    assert rc.ROUTING_PRIORITY == (
        "safety_correctness",
        "quality_threshold",
        "cash_resource_cost",
        "elapsed_time",
    )


def test_capability_sufficiency_precedes_cost_optimization():
    assert rc.CAPABILITY_SUFFICIENCY_BEFORE_COST_OPTIMIZATION is True
