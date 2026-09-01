"""AAF v0.5 A4 prereq — WorkBuddy model candidate discovery 聚焦测试
（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001）。

证明（Requirement 8）：
1. 具体 WorkBuddy 候选身份可发现/可表示（registry 含当前 CLI 支持的 15 个 model IDs）
2. selector 能看到 WorkBuddy 候选（candidates_considered 含全部候选）
3. 未资格化候选 capability/qualification 仍 unknown → 不 eligible
   （deepseek-v4-flash 自 AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001 起为
   唯一资格化候选：tier=T4 + qualified，LOW 下 eligible；MEDIUM/HIGH 仍
   CAPABILITY_INSUFFICIENT——专项断言见 test_a4_workbuddy_qualification.py）
4. FREE/cheap/promo 假设不被推断（cost_class=UNKNOWN、不在 FREE 集合）
5. 当前 WorkBuddy invocation 保持 CodeBuddy Auto：无 --model / --effort 覆盖

边界（Boundaries）：无 capability promotion、无 qualification、无 multiplier
排序、无 RemoteConfig 消费、无 active routing、无 effort selection、无 Hermes/
Codex 变化——本测试只验证「身份事实层」与「调用不变」。
"""
import pytest

from ai_agent_framework import adapters
from ai_agent_framework import model_observation as mo
from ai_agent_framework import model_registry as mr
from ai_agent_framework import risk_contract as rc
from ai_agent_framework import workbuddy_retry as wb_retry_mod
from ai_agent_framework.model_registry import (
    COST_CLASS_UNKNOWN,
    FREE_OF_COST_CLASSES,
    LOCALITY_UNKNOWN,
    QUAL_STATUS_QUALIFIED,
    QUAL_STATUS_UNKNOWN,
    canonical_key,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (
    EXCL_CAPABILITY_INSUFFICIENT,
    EXCL_ROLE_NOT_APPLICABLE,
    NO_SHADOW_CANDIDATE,
    economic_rank,
    select_shadow_candidate,
)

# 当前运行时证据（2026-09-02 probe，codebuddy 2.141.0）CLI --model 帮助行文档化的
# model IDs——与 .aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001/discovery/
# discovery_facts.json models_documented_by_cli 逐字一致（测试内嵌快照，hermetic）。
WORKBUDDY_CANDIDATE_IDS = (
    "hy4-preview", "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
    "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
    "deepseek-v4-flash",
)

# 与 discovery/codebuddy_help.txt:34 逐字一致的 --model 帮助行（mock 输入形态）。
CODEBUDDY_HELP_MODEL_LINE = (
    "--model <model>                                  Model for the current session. "
    "Please provide the model ID. Currently supported: (hy4-preview, hy3, hy3-x, "
    "glm-5.3, glm-5.3-flash, glm-5.2, glm-5.1, glm-5v-turbo, minimax-m3, "
    "minimax-m2.7, kimi-k3-1, kimi-k2.7, kimi-k2.6, deepseek-v4-pro, "
    "deepseek-v4-flash)"
)


def _workbuddy_candidates(reg):
    return {
        k: e for k, e in reg.items()
        if e.applicable_agents == ("workbuddy",) and e.model is not None
    }


def _excluded_reasons(decision):
    return {rec.candidate: rec.reason for rec in decision.excluded}


# 自 AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001 起，deepseek-v4-flash 是唯一
# 被资格化的 WorkBuddy 候选（tier=T4 + qualification=qualified，独立 probe 证据），
# 其余 14 个保持 identity-only（本文件只验证后者的 identity 事实；资格化候选的
# 专项断言见 tests/test_a4_workbuddy_qualification.py）。
QUALIFIED_WORKBUDDY_IDS = ("deepseek-v4-flash",)
UNQUALIFIED_WORKBUDDY_IDS = tuple(
    mid for mid in WORKBUDDY_CANDIDATE_IDS if mid not in QUALIFIED_WORKBUDDY_IDS
)


# ---------------------------------------------------------------------------
# 1. 具体候选身份可发现 / 可表示
# ---------------------------------------------------------------------------


def test_workbuddy_candidates_present_in_baseline():
    reg = mr.baseline_registry()
    cands = _workbuddy_candidates(reg)
    assert set(cands) == set(WORKBUDDY_CANDIDATE_IDS)  # key = model ID（provider 未暴露）
    # Auto 锚点仍在（当前调用身份），不被候选替代
    assert "agent:workbuddy" in reg
    assert reg["agent:workbuddy"].model is None


def test_workbuddy_candidates_identity_only_fields():
    """未资格化候选 = identity-only：model ID 已知，其余维度保守 UNKNOWN。
    （deepseek-v4-flash 自 QUALIFICATION-001 起已资格化，见专项测试文件。）"""
    reg = mr.baseline_registry()
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        e = reg[mid]
        assert e.model == mid
        assert e.provider is None  # CLI 不暴露底层 provider
        assert e.applicable_agents == ("workbuddy",)
        assert e.capability_tier is None
        assert e.qualification.status == QUAL_STATUS_UNKNOWN
        assert e.cost_class == COST_CLASS_UNKNOWN
        assert e.locality == LOCALITY_UNKNOWN
        assert is_usable_candidate(e) is False  # 发现身份 ≠ eligible
        assert any("AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001" in s for s in e.evidence)


def test_workbuddy_candidate_ids_match_cli_documented_parser():
    """registry 候选集合 == 当前 CLI --model 帮助行解析结果（同一发现语义）。"""
    parsed = mo._parse_codebuddy_model_list(CODEBUDDY_HELP_MODEL_LINE)
    assert set(parsed) == set(WORKBUDDY_CANDIDATE_IDS)
    assert len(parsed) == len(WORKBUDDY_CANDIDATE_IDS)


def test_workbuddy_auto_anchor_entry_conservative():
    """agent:workbuddy（Auto 锚点）保持 model=None / 全 UNKNOWN。"""
    e = mr.baseline_registry()["agent:workbuddy"]
    assert e.model is None and e.provider is None
    assert e.capability_tier is None
    assert e.qualification.status == QUAL_STATUS_UNKNOWN
    assert e.cost_class == COST_CLASS_UNKNOWN
    assert e.locality == LOCALITY_UNKNOWN
    assert is_usable_candidate(e) is False


# ---------------------------------------------------------------------------
# 2. FREE/cheap/promo 假设不被推断
# ---------------------------------------------------------------------------


def test_workbuddy_candidates_no_free_cheap_promo_inference():
    reg = mr.baseline_registry()
    for mid in WORKBUDDY_CANDIDATE_IDS:
        e = reg[mid]
        assert e.cost_class == COST_CLASS_UNKNOWN
        assert e.cost_class not in FREE_OF_COST_CLASSES
        assert economic_rank(e.cost_class) == 2  # UNKNOWN 成本 rank（永不因成本获胜）


# ---------------------------------------------------------------------------
# 3. selector 能看到候选，但都不 eligible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk_class", [rc.RISK_LOW, rc.RISK_MEDIUM, rc.RISK_HIGH])
def test_selector_sees_workbuddy_candidates_but_only_qualified_eligible(risk_class):
    reg = mr.baseline_registry()
    decision = select_shadow_candidate(risk_class, rc.ROLE_EXECUTOR, "workbuddy", reg)
    # 候选被看到（considered 含全部 15 + Auto 锚点）
    considered = set(decision.candidates_considered)
    assert set(WORKBUDDY_CANDIDATE_IDS) <= considered
    assert "agent:workbuddy" in considered
    reasons = _excluded_reasons(decision)
    if risk_class == rc.RISK_LOW:
        # 唯一资格化候选（deepseek-v4-flash，T4 + QUALIFIED）通过 LOW gate
        assert decision.eligible == ("deepseek-v4-flash",)
        assert decision.selected == "deepseek-v4-flash"
        assert decision.no_candidate_reason is None
        for mid in UNQUALIFIED_WORKBUDDY_IDS:
            assert reasons[mid] == EXCL_CAPABILITY_INSUFFICIENT  # tier=None fail closed
        assert reasons["agent:workbuddy"] == EXCL_CAPABILITY_INSUFFICIENT
    else:
        # MEDIUM/HIGH：T4 不足（floor T3/T2）→ 全部排除、零 eligible
        assert decision.eligible == ()
        assert decision.selected is None
        assert decision.no_candidate_reason is not None
        assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)
        for mid in WORKBUDDY_CANDIDATE_IDS:
            assert reasons[mid] == EXCL_CAPABILITY_INSUFFICIENT
        assert reasons["agent:workbuddy"] == EXCL_CAPABILITY_INSUFFICIENT


def test_selector_workbuddy_candidates_not_visible_to_hermes_stage():
    """候选只属 workbuddy stage；hermes stage 不受影响（既有选择零变化）。"""
    reg = mr.baseline_registry()
    decision = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "hermes", reg)
    reasons = _excluded_reasons(decision)
    for mid in WORKBUDDY_CANDIDATE_IDS:
        assert reasons[mid] == EXCL_ROLE_NOT_APPLICABLE
    # Hermes 既有 eligible/selected 语义不变（qwen3:4b@custom 仍被选中）
    assert "qwen3:4b@custom" in decision.eligible
    assert decision.selected == "qwen3:4b@custom"


def test_workbuddy_candidates_do_not_leak_into_codex_stage():
    reg = mr.baseline_registry()
    decision = select_shadow_candidate(rc.RISK_HIGH, rc.ROLE_REVIEWER, "codex", reg)
    reasons = _excluded_reasons(decision)
    for mid in WORKBUDDY_CANDIDATE_IDS:
        assert reasons[mid] == EXCL_ROLE_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# 4. registry 序列化 round-trip 保留候选
# ---------------------------------------------------------------------------


def test_registry_roundtrip_preserves_workbuddy_candidates():
    reg = mr.baseline_registry()
    rebuilt = mr.registry_from_dict(mr.registry_to_dict(reg))
    assert set(rebuilt) == set(reg)
    for mid in UNQUALIFIED_WORKBUDDY_IDS:
        assert rebuilt[mid].model == mid
        assert rebuilt[mid].cost_class == COST_CLASS_UNKNOWN
        assert is_usable_candidate(rebuilt[mid]) is False
    # 唯一资格化候选的 qualification 也随 round-trip 保留
    assert is_usable_candidate(rebuilt["deepseek-v4-flash"]) is True
    assert rebuilt["deepseek-v4-flash"].qualification.status == QUAL_STATUS_QUALIFIED
    assert "agent:workbuddy" in rebuilt


# ---------------------------------------------------------------------------
# 5. 当前 WorkBuddy invocation 保持 CodeBuddy Auto（无 --model / --effort）
# ---------------------------------------------------------------------------


def test_workbuddy_invocation_remains_auto_no_model_override(monkeypatch):
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
    assert env_out.get("CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS") == "1"


def test_workbuddy_run_agent_args_have_no_model_override(tmp_path, monkeypatch):
    """run_agent('workbuddy', ...) 的 Popen args 不含 --model/--effort（Auto 保留）。"""
    captured = {}

    class FakeProc:
        pid = 1
        returncode = 0

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            return "PASS fake", ""

        def poll(self):
            return 0

    def fake_popen(args, stdin, stdout, stderr, encoding, env, **kwargs):
        captured["args"] = args
        captured["env"] = env
        return FakeProc()

    monkeypatch.setattr(adapters, "_require", lambda cmd: "C:/fake-bin/codebuddy.exe")
    monkeypatch.setattr(wb_retry_mod, "_Popen", fake_popen)
    monkeypatch.setenv("AAF_WORKBUDDY_RETRY", "0")  # 单次 attempt
    out = adapters.run_agent("workbuddy", "TASK", tmp_path)
    assert out == "PASS fake"
    args = captured["args"]
    assert args[0] == "C:/fake-bin/codebuddy.exe"
    assert "-p" in args and "--output-format" in args and "text" in args and "-y" in args
    assert "--model" not in args and "--effort" not in args and "-m" not in args
    # provider 不变（无 --provider / 无 env 覆盖）
    assert "--provider" not in args
    assert not any(k.startswith("AAF_HERMES_") for k in captured["env"])
