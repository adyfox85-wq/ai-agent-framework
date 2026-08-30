"""AAF v0.5 A1 — Model Registry Contract 定向测试（TASK: AAF-v0.5-A1-REGISTRY-RISK-001）。

覆盖 Requirement 9 的 registry 部分：
- FREE 不隐含 qualified
- UNKNOWN 成本与 FREE 可区分
- 运行时 qualification 未知保持显式
- 未支持/未知元数据不静默变成可用候选
- capability tier 与 cost 分类是独立维度
- schema 能表达四种要求组合（free-not-qualified / free-qualified /
  paid-or-unknown-qualified / qualification-unknown）
- 基线事实纪律（未验证 = UNKNOWN；每条非 UNKNOWN 事实带证据引用）
- 范围边界静态断言（无选择/路由/回退/轮询/隔离 API；零网络/子进程依赖）
"""

import inspect

import pytest

from ai_agent_framework import model_observation as mo
from ai_agent_framework import model_registry as mr
from ai_agent_framework.model_registry import (
    AGENT_KEY_PREFIX,
    CAP_TIER_T2,
    CAP_TIER_T4,
    COST_CLASS_UNKNOWN,
    LOCALITY_LOCAL,
    LOCALITY_REMOTE,
    LOCALITY_UNKNOWN,
    QUAL_STATUS_NOT_QUALIFIED,
    QUAL_STATUS_QUALIFIED,
    QUAL_STATUS_UNKNOWN,
    SCHEMA_VERSION,
    RegistryEntry,
    RuntimeQualification,
    baseline_registry,
    canonical_key,
    entry_from_dict,
    entry_to_dict,
    free_of_cost,
    is_usable_candidate,
    registry_from_dict,
    registry_to_dict,
    tier_satisfies,
)

FREE = mo.COST_CLASS_FREE
LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
PAID = mo.COST_CLASS_PAID


def _entry(**overrides) -> RegistryEntry:
    """测试便捷构造：默认 = 有 tier、已 qualified、FREE 成本的"可区分"条目。"""
    base = dict(
        model="m1",
        provider="p1",
        applicable_agents=("hermes",),
        capability_tier=CAP_TIER_T2,
        cost_class=FREE,
        locality=LOCALITY_UNKNOWN,
        qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED),
    )
    base.update(overrides)
    return RegistryEntry(**base)


# ---------------------------------------------------------------------------
# A. 词汇复用与常量契约
# ---------------------------------------------------------------------------


def test_cost_vocabulary_reused_from_model_observation():
    """成本分类复用 repository 既有词汇（不另造重复词汇）。"""
    assert mr.COST_CLASSES is mo.COST_CLASSES
    assert set(mr.COST_CLASSES) == {mo.COST_CLASS_LOCAL_FREE, mo.COST_CLASS_FREE,
                                    mo.COST_CLASS_FREE_PROMO, mo.COST_CLASS_PAID,
                                    mo.COST_CLASS_UNKNOWN}


def test_capability_tiers_contract():
    assert mr.CAPABILITY_TIERS == ("T0", "T1", "T2", "T3", "T4")
    assert mr.TIER_STRENGTH_ORDER["T0"] < mr.TIER_STRENGTH_ORDER["T4"]
    # T0 最强：T2 满足 T4 下限，T4 不满足 T2 下限
    assert tier_satisfies("T2", "T4") is True
    assert tier_satisfies("T4", "T2") is False
    assert tier_satisfies("T2", "T2") is True
    assert tier_satisfies(None, "T4") is False
    assert tier_satisfies("T2", None) is False
    assert tier_satisfies("T9", "T4") is False


def test_locality_vocabulary():
    assert mr.LOCALITIES == (LOCALITY_LOCAL, LOCALITY_REMOTE, LOCALITY_UNKNOWN)


def test_qualification_vocabulary_minimal():
    assert mr.QUAL_STATUSES == (QUAL_STATUS_QUALIFIED, QUAL_STATUS_NOT_QUALIFIED,
                                QUAL_STATUS_UNKNOWN)


# ---------------------------------------------------------------------------
# B. FREE 不隐含 qualified
# ---------------------------------------------------------------------------


def test_free_does_not_imply_qualified_unknown_qual():
    entry = _entry(cost_class=FREE, qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    assert free_of_cost(entry.cost_class) is True
    assert is_usable_candidate(entry) is False


def test_free_does_not_imply_qualified_not_qualified():
    entry = _entry(cost_class=FREE, qualification=RuntimeQualification(status=QUAL_STATUS_NOT_QUALIFIED))
    assert is_usable_candidate(entry) is False


def test_free_alone_never_usable():
    """FREE + 有 tier 但 qualification 未知 → 仍不可用（FREE 不是健康证据）。"""
    entry = _entry(cost_class=FREE, capability_tier=CAP_TIER_T2,
                   qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    assert is_usable_candidate(entry) is False


def test_free_and_qualified_is_usable():
    entry = _entry(cost_class=FREE, capability_tier=CAP_TIER_T2,
                   qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    assert is_usable_candidate(entry) is True


# ---------------------------------------------------------------------------
# C. UNKNOWN 成本与 FREE 可区分
# ---------------------------------------------------------------------------


def test_unknown_cost_is_not_free():
    assert free_of_cost(COST_CLASS_UNKNOWN) is False
    assert COST_CLASS_UNKNOWN != FREE


def test_unknown_cost_entry_not_reported_as_free():
    entry = _entry(cost_class=COST_CLASS_UNKNOWN)
    assert entry.cost_class == COST_CLASS_UNKNOWN
    assert free_of_cost(entry.cost_class) is False


def test_unknown_cost_with_qualification_is_usable_but_never_free():
    """UNKNOWN 成本不影响可用性判定，但也不得被当作 FREE。"""
    entry = _entry(cost_class=COST_CLASS_UNKNOWN,
                   qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    assert is_usable_candidate(entry) is True
    assert free_of_cost(entry.cost_class) is False
    assert entry.cost_class != FREE


def test_unknown_cost_survives_serialization():
    entry = _entry(cost_class=COST_CLASS_UNKNOWN)
    restored = entry_from_dict(entry_to_dict(entry))
    assert restored.cost_class == COST_CLASS_UNKNOWN
    assert restored.cost_class != FREE


# ---------------------------------------------------------------------------
# D. 运行时 qualification 未知保持显式
# ---------------------------------------------------------------------------


def test_qualification_unknown_is_explicit_by_default():
    entry = RegistryEntry(model="x", provider="y")
    assert entry.qualification.status == QUAL_STATUS_UNKNOWN
    assert entry.qualification.observed_at is None
    assert entry.qualification.evidence == ()


def test_qualification_unknown_not_usable_even_with_tier():
    entry = _entry(capability_tier=CAP_TIER_T2,
                   qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    assert is_usable_candidate(entry) is False


def test_not_qualified_is_distinct_from_unknown():
    assert QUAL_STATUS_NOT_QUALIFIED != QUAL_STATUS_UNKNOWN
    assert RuntimeQualification(status=QUAL_STATUS_NOT_QUALIFIED) != RuntimeQualification(status=QUAL_STATUS_UNKNOWN)


# ---------------------------------------------------------------------------
# E. 未支持/未知元数据不静默变成可用候选
# ---------------------------------------------------------------------------


def test_unknown_tier_never_usable_even_when_qualified():
    entry = _entry(capability_tier=None,
                   qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    assert is_usable_candidate(entry) is False


def test_unknown_tier_and_unknown_qual_never_usable():
    entry = _entry(capability_tier=None,
                   qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    assert is_usable_candidate(entry) is False


def test_unknown_metadata_does_not_fabricate_candidacy():
    """未知 locality + 未知成本本身绝不产生可用候选（须 tier + qualified 双满足）。"""
    entry = _entry(cost_class=COST_CLASS_UNKNOWN, locality=LOCALITY_UNKNOWN,
                   qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    assert is_usable_candidate(entry) is False


def test_usability_not_gated_by_cost_or_locality():
    """可用性只由 tier + qualification 决定；成本/locality 未知不阻断、也不促成。"""
    entry = _entry(cost_class=COST_CLASS_UNKNOWN, locality=LOCALITY_UNKNOWN,
                   qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    assert is_usable_candidate(entry) is True


# ---------------------------------------------------------------------------
# F. capability tier 与 cost 分类独立
# ---------------------------------------------------------------------------


def test_tier_and_cost_are_independent_dimensions():
    a = _entry(cost_class=FREE, capability_tier=CAP_TIER_T2)
    b = _entry(cost_class=PAID, capability_tier=CAP_TIER_T2)
    c = _entry(cost_class=FREE, capability_tier=CAP_TIER_T4)
    # 成本变化不影响 tier
    assert a.capability_tier == b.capability_tier == CAP_TIER_T2
    # tier 变化不影响成本
    assert a.cost_class == c.cost_class == FREE
    # 成本与 tier 各自保持
    assert (b.cost_class, b.capability_tier) == (PAID, CAP_TIER_T2)
    assert (c.cost_class, c.capability_tier) == (FREE, CAP_TIER_T4)
    # 判定行为独立：tier_satisfies 不读 cost_class
    assert tier_satisfies(a.capability_tier, "T4") == tier_satisfies(b.capability_tier, "T4") is True


# ---------------------------------------------------------------------------
# G. schema 表达四种要求组合
# ---------------------------------------------------------------------------


def test_schema_expresses_all_required_combinations():
    free_not_qualified = _entry(cost_class=FREE, capability_tier=CAP_TIER_T2,
                                qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    free_qualified = _entry(cost_class=FREE, capability_tier=CAP_TIER_T2,
                            qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    paid_qualified = _entry(cost_class=PAID, capability_tier=CAP_TIER_T2,
                            qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    unknown_cost_qualified = _entry(cost_class=COST_CLASS_UNKNOWN, capability_tier=CAP_TIER_T2,
                                    qualification=RuntimeQualification(status=QUAL_STATUS_QUALIFIED))
    health_unknown = _entry(cost_class=COST_CLASS_UNKNOWN, capability_tier=None,
                            qualification=RuntimeQualification(status=QUAL_STATUS_UNKNOWN))
    # 四种组合全部可表达且彼此可区分
    combos = (free_not_qualified, free_qualified, paid_qualified,
              unknown_cost_qualified, health_unknown)
    assert len({e.key() for e in combos}) == 1  # 同身份（模型维度区分由字段承担）
    assert len({(e.cost_class, e.qualification.status, e.capability_tier) for e in combos}) == 5
    # 可用性语义：只有 tier + qualified 组合可用
    assert is_usable_candidate(free_qualified) is True
    assert is_usable_candidate(paid_qualified) is True
    assert is_usable_candidate(unknown_cost_qualified) is True
    assert is_usable_candidate(free_not_qualified) is False
    assert is_usable_candidate(health_unknown) is False


# ---------------------------------------------------------------------------
# H. 校验 fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        dict(capability_tier="T9"),
        dict(cost_class="GRATIS"),
        dict(locality="cloud"),
        dict(model="  "),
        dict(provider="  "),
    ],
)
def test_invalid_metadata_rejected(bad):
    with pytest.raises(ValueError):
        _entry(**bad)


def test_invalid_qualification_status_rejected():
    with pytest.raises(ValueError):
        RuntimeQualification(status="maybe")
    with pytest.raises(ValueError):
        _entry(qualification=RuntimeQualification(status="maybe"))


def test_invalid_qualification_evidence_type_rejected():
    with pytest.raises(ValueError):
        RuntimeQualification(status=QUAL_STATUS_UNKNOWN, evidence=(42,))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# I. 序列化 round-trip
# ---------------------------------------------------------------------------


def test_entry_serialization_round_trip():
    entry = _entry(cost_class=PAID, locality=LOCALITY_REMOTE,
                   qualification=RuntimeQualification(
                       status=QUAL_STATUS_QUALIFIED, evidence=("runtime probe #1",),
                       observed_at="2026-08-30T00:00:00"))
    restored = entry_from_dict(entry_to_dict(entry))
    assert restored == entry


def test_registry_serialization_round_trip():
    registry = baseline_registry()
    restored = registry_from_dict(registry_to_dict(registry))
    assert restored == registry
    assert set(restored) == set(registry)


def test_registry_from_dict_rejects_key_mismatch():
    data = registry_to_dict(baseline_registry())
    key = next(iter(data["entries"]))
    # 篡改 key 使与 entry.key() 不一致 → fail closed
    data["entries"]["tampered"] = data["entries"].pop(key)
    with pytest.raises(ValueError):
        registry_from_dict(data)


def test_registry_from_dict_rejects_invalid_enum():
    data = registry_to_dict(baseline_registry())
    key = next(iter(data["entries"]))
    data["entries"][key]["cost_class"] = "GRATIS"
    with pytest.raises(ValueError):
        registry_from_dict(data)


# ---------------------------------------------------------------------------
# I2. schema_version 校验（FIX-001：文档声明 fail closed，实现必须兑现）
# ---------------------------------------------------------------------------


def test_supported_schema_version_loads():
    """受支持的 schema_version（== SCHEMA_VERSION）正常加载。"""
    data = registry_to_dict(baseline_registry())
    assert data["schema_version"] == SCHEMA_VERSION
    restored = registry_from_dict(data)
    assert restored == baseline_registry()


def test_unsupported_schema_version_rejected():
    """不受支持的 schema_version（如 999）必须 fail closed（ValueError）。"""
    data = registry_to_dict(baseline_registry())
    data["schema_version"] = 999
    with pytest.raises(ValueError):
        registry_from_dict(data)


def test_missing_schema_version_rejected():
    """缺失 schema_version → 显式且确定性的拒绝（不承诺未声明版本的文档）。"""
    data = registry_to_dict(baseline_registry())
    del data["schema_version"]
    with pytest.raises(ValueError):
        registry_from_dict(data)


def test_malformed_schema_version_rejected():
    """malformed 版本（非受支持 int 的其它类型）→ 显式且确定性的拒绝。"""
    data = registry_to_dict(baseline_registry())
    data["schema_version"] = "1"
    with pytest.raises(ValueError):
        registry_from_dict(data)


def test_schema_version_mismatch_message_is_deterministic():
    """错误信息确定性地包含受支持版本号（可诊断、可断言）。"""
    data = registry_to_dict(baseline_registry())
    data["schema_version"] = 999
    with pytest.raises(ValueError, match="schema_version"):
        registry_from_dict(data)


def test_valid_registry_entries_still_load_unchanged():
    """既有合法 registry 条目在加入 schema 校验后仍然原样加载。"""
    baseline = baseline_registry()
    restored = registry_from_dict(registry_to_dict(baseline))
    assert set(restored) == set(baseline)
    for key, entry in baseline.items():
        assert restored[key] == entry


# ---------------------------------------------------------------------------
# I3. schema_version 严格类型校验（FIX-002：仅真实 int == SCHEMA_VERSION 被接受）
# ---------------------------------------------------------------------------


def test_strict_schema_version_accepts_exact_int_only():
    """仅真实 int 类型且值 == SCHEMA_VERSION 被接受；bool/float 不因值相等被接受。"""
    assert type(SCHEMA_VERSION) is int
    assert type(True) is not int and type(1.0) is not int  # 防止 isinstance 式实现回归
    data = registry_to_dict(baseline_registry())
    data["schema_version"] = int(SCHEMA_VERSION)
    restored = registry_from_dict(data)
    assert restored == baseline_registry()


@pytest.mark.parametrize(
    "bad_version",
    [
        True,      # bool 是 int 子类，值 == 1，必须拒绝
        False,     # 值 == 0，必须拒绝
        1.0,       # 值 == 1，float，必须拒绝
        1.5,       # 其它 float
        "1",       # 数字字符串
        None,      # 显式 None
        [1],       # 序列
        {"v": 1},  # 映射
        (1,),      # 元组
    ],
)
def test_strict_schema_version_rejects_malformed_types(bad_version):
    """值相等但类型不合规的版本必须 fail closed（ValueError），绝不静默强转。"""
    data = registry_to_dict(baseline_registry())
    data["schema_version"] = bad_version
    with pytest.raises(ValueError, match="schema_version"):
        registry_from_dict(data)


def test_strict_schema_version_rejects_unsupported_integer():
    """不受支持的真实 int（999）必须 fail closed。"""
    data = registry_to_dict(baseline_registry())
    data["schema_version"] = 999
    with pytest.raises(ValueError, match="schema_version"):
        registry_from_dict(data)


# ---------------------------------------------------------------------------
# J. 基线事实纪律（Requirement 5：未验证 = UNKNOWN）
# ---------------------------------------------------------------------------


def test_baseline_hermes_main_model_unknown_cost_remote():
    reg = baseline_registry()
    entry = reg[canonical_key("deepseek-v4-flash", "deepseek")]
    assert entry.cost_class == COST_CLASS_UNKNOWN  # 未验证，绝不写成 PAID/FREE
    assert entry.locality == LOCALITY_REMOTE
    assert entry.applicable_agents == ("hermes",)


def test_baseline_local_ollama_models_local_free():
    reg = baseline_registry()
    vision = reg[canonical_key("qwen2.5vl:3b", "custom")]
    qwen3 = reg[canonical_key("qwen3:4b", "custom")]
    assert vision.cost_class == LOCAL_FREE
    assert vision.locality == LOCALITY_LOCAL
    assert qwen3.cost_class == LOCAL_FREE
    assert qwen3.locality == LOCALITY_LOCAL


def test_baseline_workbuddy_and_codex_model_identity_unknown():
    reg = baseline_registry()
    wb = reg[AGENT_KEY_PREFIX + "workbuddy"]
    cx = reg[AGENT_KEY_PREFIX + "codex"]
    assert wb.model is None and cx.model is None
    assert wb.cost_class == COST_CLASS_UNKNOWN and cx.cost_class == COST_CLASS_UNKNOWN
    assert wb.locality == LOCALITY_UNKNOWN and cx.locality == LOCALITY_UNKNOWN


def test_baseline_no_invented_tiers_or_health():
    """基线不发明 tier / health：全部条目 capability_tier=None、qualification 默认 unknown。"""
    for key, entry in baseline_registry().items():
        assert entry.capability_tier is None, f"{key}: invented tier {entry.capability_tier}"
        assert entry.qualification.status == QUAL_STATUS_UNKNOWN, f"{key}: invented health"
        assert entry.evidence, f"{key}: non-UNKNOWN facts must carry evidence"


def test_baseline_no_invented_prices():
    """基线不发明价格：远程模型成本 = UNKNOWN；本地端点 = LOCAL_FREE（有 base_url 证据）。"""
    for key, entry in baseline_registry().items():
        assert entry.cost_class in mr.COST_CLASSES
        assert entry.cost_class != PAID, f"{key}: PAID 未经验证不得写入"


def test_baseline_keys_unique_and_stable():
    reg = baseline_registry()
    assert len(reg) == len({e.key() for e in mr.baseline_entries()})
    assert set(reg) == {"deepseek-v4-flash@deepseek", "qwen2.5vl:3b@custom",
                        "qwen3:4b@custom", "agent:workbuddy", "agent:codex"}


# ---------------------------------------------------------------------------
# K. 范围边界静态断言（A1 foundation：无选择/路由/回退/轮询/隔离）
# ---------------------------------------------------------------------------

_BANNED_PUBLIC_API_PREFIXES = (
    "select", "choose", "route", "fallback", "escalat", "poll", "quarantine",
    "monitor", "switch", "activate",
)


def _public_callables(module):
    return [
        name for name, obj in inspect.getmembers(module, inspect.isfunction)
        if not name.startswith("_")
    ]


def test_registry_exposes_no_selection_routing_fallback_api():
    banned = [n for n in _public_callables(mr) if n.lower().startswith(_BANNED_PUBLIC_API_PREFIXES)]
    assert banned == [], f"scope leak: {banned}"


def test_registry_module_has_no_network_or_subprocess_dependency():
    import ast

    import ai_agent_framework.model_registry as mod

    tree = ast.parse(inspect.getsource(mod))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    banned_roots = {"subprocess", "urllib", "requests", "http", "socket", "openai"}
    leaked = sorted(roots & banned_roots)
    assert leaked == [], f"network/subprocess dependency leaked into contract: {leaked}"
    # 依赖图：仅 stdlib + 同 package 的 model_observation（cost 词汇复用）
    assert roots <= {"__future__", "dataclasses", "typing", "model_observation"}
