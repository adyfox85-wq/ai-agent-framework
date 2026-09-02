"""AAF v0.5 A4 prereq — WorkBuddy candidate qualification 聚焦测试
（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001；第二个候选 hy4-preview
由 AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001 资格化，本文件断言已同步）。

证明（Requirement 10）：
1. deepseek-v4-flash WorkBuddy candidate 成功 qualification 后可通过
   capability/qualification eligibility gate（is_usable_candidate True；
   selector LOW executor/validator 下 eligible）
2. 不高估 tier：只赋最低被证据证明的 T4（LOW probe floor = T4），
   绝不推断 T3/T2/T1/T0；MEDIUM/HIGH/CRITICAL 下仍 CAPABILITY_INSUFFICIENT
3. 其余 13 个 WorkBuddy candidates 仍 ineligible（tier=None +
   qualification=unknown）
4. cost_class=UNKNOWN 保持；UNKNOWN 成本不反向提升能力或 qualification
   （economic_rank=2；不在 FREE 集合）
5. production WorkBuddy Auto invocation 不变（无 --model / --effort；
   agent:workbuddy Auto 锚点保持 model=None / 全 UNKNOWN）
6. WorkBuddy qualification 独立于 Hermes 历史证据（Requirement 6）：
   证据只引用本任务 probe，不引用 A2-004 Hermes 证据；Hermes 侧同名模型
   （deepseek-v4-flash@deepseek）条目零变化
7. registry round-trip 保留 qualification

边界（Boundaries）：无 active WorkBuddy routing、无 economic multiplier
解析、无 RemoteConfig routing authority、无 effort selection、无 fallback、
无 Hermes/Codex 路由变更、无 A5/A6。
"""
import pytest

from ai_agent_framework import adapters
from ai_agent_framework import risk_contract as rc
from ai_agent_framework.model_registry import (
    CAP_TIER_T0,
    CAP_TIER_T1,
    CAP_TIER_T2,
    CAP_TIER_T3,
    CAP_TIER_T4,
    COST_CLASS_UNKNOWN,
    LOCALITY_UNKNOWN,
    QUAL_STATUS_QUALIFIED,
    QUAL_STATUS_UNKNOWN,
    baseline_registry,
    canonical_key,
    is_usable_candidate,
    tier_satisfies,
)
from ai_agent_framework.shadow_routing import (
    EXCL_AUXILIARY_ONLY,
    EXCL_CAPABILITY_INSUFFICIENT,
    EXCL_ROLE_NOT_APPLICABLE,
    NO_SHADOW_CANDIDATE,
    economic_rank,
    select_shadow_candidate,
)

# 两个被资格化的 WorkBuddy 候选（registry key = model ID，provider 未暴露）。
# deepseek-v4-flash = QUALIFICATION-001；hy4-preview = SECOND-CANDIDATE-001。
QUALIFIED_WORKBUDDY_IDS = ("deepseek-v4-flash", "hy4-preview")
QUALIFIED_WORKBUDDY_ID = "deepseek-v4-flash"
SECOND_QUALIFIED_WORKBUDDY_ID = "hy4-preview"
# 其余 13 个仍保持 identity-only 的 WorkBuddy 候选。
UNQUALIFIED_WORKBUDDY_IDS = (
    "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
    "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
)
# probe 证据 artifact 的真实 observed_at（= probe 完成时刻，registry 使用同一值）。
PROBE_OBSERVED_AT = "2026-09-02T01:45:31+08:00"
SECOND_PROBE_OBSERVED_AT = "2026-09-02T03:01:44+08:00"


def _workbuddy_candidates(reg):
    return {
        k: e for k, e in reg.items()
        if e.applicable_agents == ("workbuddy",) and e.model is not None
    }


def _excluded_reasons(decision):
    return {rec.candidate: rec.reason for rec in decision.excluded}


# ---------------------------------------------------------------------------
# 1. deepseek-v4-flash WorkBuddy candidate 已资格化（tier T4 + QUALIFIED）
# ---------------------------------------------------------------------------


def test_wb_candidate_deepseek_v4_flash_qualified():
    reg = baseline_registry()
    e = reg[QUALIFIED_WORKBUDDY_ID]
    assert e.model == QUALIFIED_WORKBUDDY_ID
    assert e.provider is None  # CLI 不暴露 provider（保持）
    assert e.applicable_agents == ("workbuddy",)
    assert e.capability_tier == CAP_TIER_T4
    assert e.qualification.status == QUAL_STATUS_QUALIFIED
    assert e.cost_class == COST_CLASS_UNKNOWN  # 成本维度独立，保持 UNKNOWN
    assert e.locality == LOCALITY_UNKNOWN  # runtime 不暴露执行位置，保持
    assert is_usable_candidate(e) is True  # 通过 capability/qualification gate


def test_wb_qualification_evidence_backed_and_observed_at_real():
    """QUALIFIED 必须携带具体、可审计的真实 probe 证据引用 + 真实观测时间戳。"""
    e = baseline_registry()[QUALIFIED_WORKBUDDY_ID]
    assert e.qualification.evidence, "QUALIFIED 必须携带证据引用"
    blob = " ".join(e.qualification.evidence)
    assert ".aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/probe" in blob
    assert "deepseek_v4_flash_qualification_probe" in blob
    assert "--model deepseek-v4-flash" in blob
    assert "observed_at=2026-09-02T01:45:31+08:00" in blob
    # observed_at = probe artifact 的真实完成时刻（不是构造时的当前时间）
    assert e.qualification.observed_at == PROBE_OBSERVED_AT
    # 条目级 evidence 也包含该证据引用
    assert any("QUALIFICATION-001" in s for s in e.evidence)


def test_wb_qualification_independent_of_hermes_evidence():
    """Requirement 6：WorkBuddy qualification authority = 独立 runtime probe，
    Hermes 侧同名模型的历史证据（A2-004 / 003-FIX-001）不是 authority。"""
    e = baseline_registry()[QUALIFIED_WORKBUDDY_ID]
    blob = " ".join(e.qualification.evidence)
    assert "AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001" in blob
    # Hermes 证据不得作为本条目 qualification authority（可提及为“不使用”，
    # 但不得作为证据来源引用）
    assert "003-FIX-001" not in e.qualification.evidence
    assert "A2-SHADOW-ROUTING-004" not in e.qualification.evidence


def test_wb_tier_not_overestimated():
    """LOW probe 成功只证明最低 T4；T3/T2/T1/T0 绝不推断。"""
    e = baseline_registry()[QUALIFIED_WORKBUDDY_ID]
    assert e.capability_tier == CAP_TIER_T4
    for t in (CAP_TIER_T0, CAP_TIER_T1, CAP_TIER_T2, CAP_TIER_T3):
        assert e.capability_tier != t, f"overestimated tier {t}"
    # tier_satisfies 语义：T4 满足 LOW floor（T4），不满足 MEDIUM/HIGH floor
    assert tier_satisfies(e.capability_tier, rc.RISK_FLOORS[rc.RISK_LOW].executor) is True
    assert tier_satisfies(e.capability_tier, rc.RISK_FLOORS[rc.RISK_MEDIUM].executor) is False
    assert tier_satisfies(e.capability_tier, rc.RISK_FLOORS[rc.RISK_HIGH].executor) is False


def test_wb_cost_unknown_does_not_boost_capability_or_qualification():
    """cost UNKNOWN 不会反向提升能力或 qualification（成本与资格独立维度）。"""
    e = baseline_registry()[QUALIFIED_WORKBUDDY_ID]
    assert e.cost_class == COST_CLASS_UNKNOWN
    assert economic_rank(e.cost_class) == 2  # UNKNOWN 成本 rank（永不因成本获胜）
    # 资格来自 probe 证据而非成本：把 cost 改成任何已知类也不该影响 tier/qual
    from ai_agent_framework.model_observation import COST_CLASS_PAID
    from ai_agent_framework.model_registry import RegistryEntry
    clone = RegistryEntry(
        model=e.model, provider=e.provider, applicable_agents=e.applicable_agents,
        capability_tier=e.capability_tier, cost_class=COST_CLASS_PAID,
        locality=e.locality, qualification=e.qualification, evidence=e.evidence,
        notes=e.notes,
    )
    assert is_usable_candidate(clone) is True  # cost 不影响资格判定


# ---------------------------------------------------------------------------
# 2. 其余 14 个 WorkBuddy candidates 仍 ineligible（identity-only）
# ---------------------------------------------------------------------------


def test_other_14_workbuddy_candidates_still_unknown():
    """其余 13 个 WorkBuddy candidates 仍 ineligible（identity-only）；
    hy4-preview 自 SECOND-CANDIDATE-001 起已资格化（专项断言见
    tests/test_a4_workbuddy_second_candidate.py）。"""
    reg = baseline_registry()
    cands = _workbuddy_candidates(reg)
    assert set(cands) == set(UNQUALIFIED_WORKBUDDY_IDS) | set(QUALIFIED_WORKBUDDY_IDS)
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        e = reg[mid]
        assert e.model == mid
        assert e.provider is None
        assert e.capability_tier is None, f"{mid}: tier invented"
        assert e.qualification.status == QUAL_STATUS_UNKNOWN, f"{mid}: health invented"
        assert e.cost_class == COST_CLASS_UNKNOWN
        assert e.locality == LOCALITY_UNKNOWN
        assert is_usable_candidate(e) is False, f"{mid}: must stay ineligible"
        assert any("WORKBUDDY-DISCOVERY-001" in s for s in e.evidence)


def test_workbuddy_auto_anchor_unchanged():
    """agent:workbuddy（Auto 锚点）保持 model=None / 全 UNKNOWN——qualification
    只落在具体候选条目上，不触碰当前 Auto 调用身份。"""
    e = baseline_registry()["agent:workbuddy"]
    assert e.model is None and e.provider is None
    assert e.capability_tier is None
    assert e.qualification.status == QUAL_STATUS_UNKNOWN
    assert e.cost_class == COST_CLASS_UNKNOWN
    assert e.locality == LOCALITY_UNKNOWN
    assert is_usable_candidate(e) is False


# ---------------------------------------------------------------------------
# 3. eligibility gate：LOW 可过、MEDIUM/HIGH/CRITICAL 不可过
# ---------------------------------------------------------------------------


def test_selector_low_workbuddy_executor_eligible():
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    # 两个资格化候选均 eligible（cost/locality 同 rank，selected 仍为 key 字典序
    # 第一的 deepseek-v4-flash——既有选择语义不变）。
    assert decision.eligible == ("deepseek-v4-flash", "hy4-preview")
    assert decision.selected == QUALIFIED_WORKBUDDY_ID
    assert decision.no_candidate_reason is None
    reasons = _excluded_reasons(decision)
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        assert reasons[mid] == EXCL_CAPABILITY_INSUFFICIENT
    assert reasons["agent:workbuddy"] == EXCL_CAPABILITY_INSUFFICIENT


def test_selector_low_workbuddy_validator_eligible():
    """LOW validator floor = T4：validator 角色同样通过（两个候选均 eligible）。"""
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_VALIDATOR, "workbuddy", reg)
    assert set(decision.eligible) == set(QUALIFIED_WORKBUDDY_IDS)
    assert decision.selected == QUALIFIED_WORKBUDDY_ID


@pytest.mark.parametrize(
    "risk_class",
    [rc.RISK_MEDIUM, rc.RISK_HIGH, rc.RISK_CRITICAL],
)
def test_selector_medium_high_critical_workbuddy_still_insufficient(risk_class):
    """T4 只证明 LOW 能力：MEDIUM（T3 floor）/HIGH（T2）/CRITICAL（T1）仍
    CAPABILITY_INSUFFICIENT——单次 LOW probe 不推断更高 tier。"""
    reg = baseline_registry()
    decision = select_shadow_candidate(risk_class, rc.ROLE_EXECUTOR, "workbuddy", reg)
    assert decision.eligible == ()
    assert decision.selected is None
    assert decision.no_candidate_reason is not None
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)
    reasons = _excluded_reasons(decision)
    for mid in QUALIFIED_WORKBUDDY_IDS:
        assert reasons[mid] == EXCL_CAPABILITY_INSUFFICIENT
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        assert reasons[mid] == EXCL_CAPABILITY_INSUFFICIENT


def test_selector_high_reviewer_workbuddy_not_allowed():
    """HIGH reviewer 允许集合 = {T1, T2}；T4 不在集合内 → 排除。"""
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_HIGH, rc.ROLE_REVIEWER, "workbuddy", reg)
    assert decision.eligible == ()
    assert decision.selected is None
    reasons = _excluded_reasons(decision)
    assert reasons[QUALIFIED_WORKBUDDY_ID] == EXCL_CAPABILITY_INSUFFICIENT


# ---------------------------------------------------------------------------
# 4. Hermes / Codex stage 零变化；同名 Hermes 条目零变化
# ---------------------------------------------------------------------------


def test_wb_qualified_candidate_not_visible_to_hermes_stage():
    """WorkBuddy 候选（含已资格化的）对 hermes stage 仍 ROLE_NOT_APPLICABLE；
    Hermes 选择语义按 TASK: AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001
    收紧：qwen3:4b@custom（aux-only evidence）不再是 eligible Hermes executor
    候选 → AUXILIARY_ONLY 排除；唯一 eligible/selected = deepseek-v4-flash@deepseek。"""
    reg = baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes", reg)
    reasons = _excluded_reasons(decision)
    assert reasons[QUALIFIED_WORKBUDDY_ID] == EXCL_ROLE_NOT_APPLICABLE
    assert "qwen3:4b@custom" not in decision.eligible
    assert reasons["qwen3:4b@custom"] == EXCL_AUXILIARY_ONLY
    assert decision.eligible == ("deepseek-v4-flash@deepseek",)
    assert decision.selected == "deepseek-v4-flash@deepseek"


def test_hermes_same_name_entry_unchanged():
    """Hermes 侧 deepseek-v4-flash@deepseek 条目零变化（T2 + A2-004 证据 +
    cost UNKNOWN）——WorkBuddy qualification 不扩散、不覆盖。"""
    reg = baseline_registry()
    h = reg[canonical_key("deepseek-v4-flash", "deepseek")]
    assert h.capability_tier == CAP_TIER_T2
    assert h.qualification.status == QUAL_STATUS_QUALIFIED
    assert any("003-FIX-001" in s for s in h.qualification.evidence)
    assert h.cost_class == COST_CLASS_UNKNOWN
    assert h.applicable_agents == ("hermes",)
    # 两个条目 key 不同、互不影响
    assert canonical_key("deepseek-v4-flash", None) == QUALIFIED_WORKBUDDY_ID
    assert QUALIFIED_WORKBUDDY_ID != canonical_key("deepseek-v4-flash", "deepseek")


# ---------------------------------------------------------------------------
# 5. production WorkBuddy invocation 不变（Requirement 7）
# ---------------------------------------------------------------------------


def test_wb_qualification_does_not_change_production_invocation(monkeypatch):
    """adapters 调用不变：args 精确 = [-p --output-format text -y]，零 --model/--effort。"""
    fake_exe = "C:/fake-bin/codebuddy.exe"
    monkeypatch.setattr(adapters, "_require", lambda cmd: fake_exe)
    env = {}
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", env)
    assert args == [fake_exe, "-p", "--output-format", "text", "-y"]
    assert "--model" not in args
    assert "--effort" not in args
    assert "-m" not in args
    assert stdin_data == "PROMPT"


# ---------------------------------------------------------------------------
# 6. registry round-trip 保留 qualification
# ---------------------------------------------------------------------------


def test_registry_roundtrip_preserves_qualification():
    from ai_agent_framework.model_registry import registry_from_dict, registry_to_dict
    reg = baseline_registry()
    rebuilt = registry_from_dict(registry_to_dict(reg))
    assert set(rebuilt) == set(reg)
    e = rebuilt[QUALIFIED_WORKBUDDY_ID]
    assert e.capability_tier == CAP_TIER_T4
    assert e.qualification.status == QUAL_STATUS_QUALIFIED
    assert e.qualification.observed_at == PROBE_OBSERVED_AT
    assert is_usable_candidate(e) is True
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        assert is_usable_candidate(rebuilt[mid]) is False


def test_baseline_key_set_unchanged_after_qualification():
    """qualification 不改 key 集合（deepseek-v4-flash 仍是同一 key；
    provider 未暴露 → 无 @provider 后缀）。"""
    reg = baseline_registry()
    assert set(reg) == {
        "deepseek-v4-flash@deepseek", "qwen2.5vl:3b@custom",
        "qwen3:4b@custom", "agent:workbuddy", "agent:codex",
        "hy4-preview", "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
        "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
        "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
        "deepseek-v4-flash",
    }
