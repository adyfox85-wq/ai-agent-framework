"""AAF v0.5 A3 — Hermes executor qualification fix 聚焦回归测试
（TASK: AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001）。

Prevent auxiliary-only models from Hermes active routing。

Requirement 8 回归矩阵：
- auxiliary-only / 端点级 / 非主调用 evidence 候选排除于 Hermes executor active routing
- 无合格 FREE/LOCAL_FREE Hermes executor 时 configured model/provider 保留
  （routing_applied=false）
- 无 silent fallback（fallback_attempted 恒 false）
- 真正主调用合格（scope=main）的 Hermes free executor 行为保持支持
- qualification scope 词汇契约 / 序列化 round-trip / 基线 scope 事实
- gate 顺序不弱化（capability / qualification 先于 scope / 成本）
"""

import json
import os

import pytest

import ai_agent_framework.cost_guard as cg
import ai_agent_framework.model_registry as mr
import ai_agent_framework.runner as runner_mod
from ai_agent_framework import active_routing as ar
from ai_agent_framework import model_observation as mo
from ai_agent_framework.risk_contract import (
    RISK_LOW,
    RISK_MEDIUM,
    ROLE_EXECUTOR,
    ROLE_VALIDATOR,
)
from ai_agent_framework.shadow_routing import (
    EXCL_AUXILIARY_ONLY,
    EXCL_CAPABILITY_INSUFFICIENT,
    EXCL_MAIN_INVOCATION_UNPROVEN,
    EXCL_NOT_QUALIFIED,
    NO_SHADOW_CANDIDATE,
    select_shadow_candidate,
)

LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
QUAL_MAIN = mr.QUAL_SCOPE_MAIN
QUAL_AUX = mr.QUAL_SCOPE_AUXILIARY
QUAL_UNKNOWN = mr.QUAL_SCOPE_UNKNOWN


def _qual(status: str = mr.QUAL_STATUS_QUALIFIED, scope: str | None = None) -> mr.RuntimeQualification:
    return mr.RuntimeQualification(
        status=status,
        scope=mr.QUAL_SCOPE_MAIN if scope is None and status == mr.QUAL_STATUS_QUALIFIED else (
            scope or mr.QUAL_SCOPE_UNKNOWN
        ),
    )


def _entry(**overrides) -> mr.RegistryEntry:
    base = dict(
        model="m1",
        provider="p1",
        base_url="http://127.0.0.1:11434/v1",
        applicable_agents=("hermes",),
        capability_tier=mr.CAP_TIER_T4,
        cost_class=LOCAL_FREE,
        locality=mr.LOCALITY_LOCAL,
        qualification=mr.RuntimeQualification(
            status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_MAIN
        ),
    )
    base.update(overrides)
    return mr.RegistryEntry(**base)


def _registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


def _excluded_reasons(decision) -> dict[str, str]:
    return {rec.candidate: rec.reason for rec in decision.excluded}


# ---------------------------------------------------------------------------
# A. qualification scope 词汇契约（A1）
# ---------------------------------------------------------------------------


def test_qualification_scope_vocabulary_contract():
    assert mr.QUAL_SCOPES == (QUAL_MAIN, QUAL_AUX, QUAL_UNKNOWN)
    # 默认 = unknown（未声明主调用 scope → fail closed）
    assert mr.RuntimeQualification().scope == QUAL_UNKNOWN
    # scope 与 status 独立：QUALIFIED 不隐含 main；main 不隐含 QUALIFIED
    assert mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED).scope == QUAL_UNKNOWN
    q = mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_MAIN)
    assert q.status == mr.QUAL_STATUS_QUALIFIED and q.scope == QUAL_MAIN
    # 语义可区分（dataclass equality 含 scope）
    assert mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED) != q


def test_qualification_invalid_scope_fail_closed():
    with pytest.raises(ValueError, match="scope"):
        mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED, scope="main-chat")
    with pytest.raises(ValueError, match="scope"):
        _entry(qualification=mr.RuntimeQualification(scope="bogus"))


def test_qualification_scope_serialization_roundtrip():
    entry = _entry(qualification=mr.RuntimeQualification(
        status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX,
        evidence=("aux-probe",), observed_at="2026-09-02T00:00:00+08:00",
    ))
    data = mr.entry_to_dict(entry)
    assert data["qualification"]["scope"] == QUAL_AUX
    restored = mr.entry_from_dict(data)
    assert restored.qualification == entry.qualification
    # 旧 dict（无 scope 字段）→ 缺省 unknown（向后兼容，fail closed）
    del data["qualification"]["scope"]
    assert mr.entry_from_dict(data).qualification.scope == QUAL_UNKNOWN


def test_baseline_scope_facts():
    """当前真实证据的 scope 事实：qwen3:4b@custom = auxiliary（aux 槽位 +
    本地端点 evidence，真实 main-chat invocation HTTP 400）；deepseek-v4-flash
    （hermes）= main（真实 AAF main-chat 执行证据）；WorkBuddy 两资格化候选 =
    main（真实 CodeBuddy CLI 主 invocation probe）；qwen2.5vl = unknown。"""
    reg = mr.baseline_registry()
    qwen3 = reg[mr.canonical_key("qwen3:4b", "custom")]
    deepseek = reg[mr.canonical_key("deepseek-v4-flash", "deepseek")]
    wb_ds = reg["deepseek-v4-flash"]  # WorkBuddy 候选（provider=None）
    wb_hy4 = reg["hy4-preview"]
    vision = reg[mr.canonical_key("qwen2.5vl:3b", "custom")]
    assert qwen3.qualification.scope == QUAL_AUX
    assert qwen3.qualification.status == mr.QUAL_STATUS_QUALIFIED  # 仍 QUALIFIED
    assert qwen3.cost_class == LOCAL_FREE  # 成本/资格维度不变
    assert deepseek.qualification.scope == QUAL_MAIN
    assert wb_ds.qualification.scope == QUAL_MAIN
    assert wb_hy4.qualification.scope == QUAL_MAIN
    assert vision.qualification.scope == QUAL_UNKNOWN
    # scope 事实经 registry round-trip 保持
    rebuilt = mr.registry_from_dict(mr.registry_to_dict(reg))
    assert rebuilt[mr.canonical_key("qwen3:4b", "custom")].qualification.scope == QUAL_AUX
    assert rebuilt["deepseek-v4-flash@deepseek"].qualification.scope == QUAL_MAIN


# ---------------------------------------------------------------------------
# B. selector：executor 角色要求主调用 qualification（Requirement 3/8）
# ---------------------------------------------------------------------------


def test_auxiliary_only_candidate_excluded_from_executor():
    """auxiliary-only（scope=auxiliary）qualified free 候选：LOW Hermes executor
    排除（AUXILIARY_ONLY）——绝不当作 Hermes 主 executor。"""
    reg = _registry(
        _entry(model="aux", provider="custom",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
    )
    decision = select_shadow_candidate(RISK_LOW, ROLE_EXECUTOR, "hermes", reg)
    assert decision.selected is None
    assert decision.eligible == ()
    assert _excluded_reasons(decision)["aux@custom"] == EXCL_AUXILIARY_ONLY
    assert decision.no_candidate_reason is not None
    assert decision.no_candidate_reason.startswith(NO_SHADOW_CANDIDATE)


def test_unknown_scope_qualified_candidate_excluded_from_executor():
    """scope=unknown 的 qualified 候选：executor 角色 fail closed
    （MAIN_INVOCATION_UNPROVEN）——未证明主调用能力绝不当作 executor。"""
    reg = _registry(
        _entry(model="unk", provider="p",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_UNKNOWN)),
    )
    decision = select_shadow_candidate(RISK_LOW, ROLE_EXECUTOR, "hermes", reg)
    assert decision.selected is None
    assert _excluded_reasons(decision)["unk@p"] == EXCL_MAIN_INVOCATION_UNPROVEN


def test_aux_only_excluded_even_when_free_local_cheapest():
    """aux-only 候选绝不因 FREE/LOCAL_FREE/本地偏好进入 executor 经济排序——
    scope 闸在成本之前。"""
    reg = _registry(
        _entry(model="aux-free", provider="p",
               cost_class=LOCAL_FREE, locality=mr.LOCALITY_LOCAL,
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
        _entry(model="main-paid", provider="q",
               cost_class=mo.COST_CLASS_PAID, locality=mr.LOCALITY_REMOTE,
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_MAIN)),
    )
    decision = select_shadow_candidate(RISK_LOW, ROLE_EXECUTOR, "hermes", reg)
    reasons = _excluded_reasons(decision)
    assert reasons["aux-free@p"] == EXCL_AUXILIARY_ONLY
    assert decision.eligible == ("main-paid@q",)
    assert decision.selected == "main-paid@q"


def test_main_scope_qualified_free_still_selected():
    """真正主调用合格的 Hermes free executor 行为保持支持（Requirement 8）：
    scope=main + QUALIFIED + LOCAL_FREE → eligible 且被选中。"""
    reg = _registry(_entry(model="main-free", provider="p"))
    decision = select_shadow_candidate(RISK_LOW, ROLE_EXECUTOR, "hermes", reg)
    assert decision.eligible == ("main-free@p",)
    assert decision.selected == "main-free@p"
    assert decision.no_candidate_reason is None


def test_capability_gate_precedes_scope_gate():
    """gate 顺序不弱化：能力不足（T4 vs MEDIUM floor T3）先于 scope 排除——
    aux-scope 候选在 MEDIUM 上仍报 CAPABILITY_INSUFFICIENT（不是
    AUXILIARY_ONLY）。"""
    reg = _registry(
        _entry(model="aux-t4", provider="p", capability_tier=mr.CAP_TIER_T4,
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
    )
    decision = select_shadow_candidate(RISK_MEDIUM, ROLE_EXECUTOR, "hermes", reg)
    assert _excluded_reasons(decision)["aux-t4@p"] == EXCL_CAPABILITY_INSUFFICIENT
    assert decision.selected is None


def test_qualification_status_gate_precedes_scope_gate():
    """qualification status 闸先于 scope：not_qualified + aux-scope →
    NOT_QUALIFIED（scope 词汇不混淆 status 语义）。"""
    reg = _registry(
        _entry(model="nq", provider="p",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_NOT_QUALIFIED, scope=QUAL_AUX)),
    )
    decision = select_shadow_candidate(RISK_LOW, ROLE_EXECUTOR, "hermes", reg)
    assert _excluded_reasons(decision)["nq@p"] == EXCL_NOT_QUALIFIED


def test_executor_scope_rule_does_not_affect_validator_hypothetical():
    """scope 规则只作用于 executor（唯一会被 active routing 真实选择/改变执行
    的角色）：validator 的 hypothetical 选择不受影响（aux-scope qualified
    候选仍可 hypothetical-eligible）——规则不扩散、不改变 validator 语义。"""
    reg = _registry(
        _entry(model="aux", provider="p",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
    )
    decision = select_shadow_candidate(RISK_LOW, ROLE_VALIDATOR, "hermes", reg)
    assert decision.eligible == ("aux@p",)
    assert decision.selected == "aux@p"
    assert decision.no_candidate_reason is None


# ---------------------------------------------------------------------------
# C. A3 active routing 决策层（Requirement 4/5/8）
# ---------------------------------------------------------------------------


def test_active_routing_baseline_no_route_keeps_configured():
    """当前真实证据：LOW Hermes executor → qwen3:4b@custom 不再被选中
    （excluded=AUXILIARY_ONLY）；唯一 eligible=deepseek（cost UNKNOWN）→
    cost gate 拒绝 → routing_applied=false、configured DeepSeek 保留、
    fallback_attempted=false（Acceptance 1/2 + no silent fallback）。"""
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="TASK.Risk",
        configured_model="deepseek-v4-flash", configured_provider="deepseek",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] == "deepseek-v4-flash@deepseek"
    assert rec["routed_model"] is None
    assert rec["configured_model"] == "deepseek-v4-flash"
    assert rec["configured_provider"] == "deepseek"
    assert rec["reason"].startswith(ar.REASON_SELECTED_NOT_FREE)
    assert rec["fallback_attempted"] is False
    aux_excl = [e for e in rec["excluded"] if e["candidate"] == "qwen3:4b@custom"]
    assert aux_excl and aux_excl[0]["reason"] == EXCL_AUXILIARY_ONLY
    ar.validate_active_routing(rec)


def test_active_routing_aux_only_pool_keeps_configured():
    """无任何 main-scope 合格 free executor（全 aux-only 池）→ NO_ELIGIBLE →
    routing_applied=false、configured 保留、零 fallback（Requirement 5）。"""
    reg = _registry(
        _entry(model="aux1", provider="custom",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
        _entry(model="aux2", provider="custom",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
    )
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
        risk_source="test",
        configured_model="deepseek-v4-flash", configured_provider="deepseek",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["configured_model"] == "deepseek-v4-flash"
    assert rec["reason"].startswith(ar.REASON_NO_ELIGIBLE)
    assert rec["fallback_attempted"] is False
    ar.validate_active_routing(rec)


def test_active_routing_valid_main_free_still_routes():
    """valid qualified Hermes executor behavior remains supported：main-scope +
    QUALIFIED + LOCAL_FREE → 仍真实 active route（FIX 只排除 aux-only）。"""
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes",
        _registry(_entry(model="main-free", provider="p")),
        risk_source="test",
        configured_model="deepseek-v4-flash", configured_provider="deepseek",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "main-free@p"
    assert rec["routed_model"] == "main-free"
    assert rec["routed_provider"] == "p"
    assert rec["reason"].startswith(ar.REASON_APPLIED)
    assert rec["fallback_attempted"] is False
    ar.validate_active_routing(rec)


# ---------------------------------------------------------------------------
# D. runner 全链（Requirement 8 + no silent fallback）
# ---------------------------------------------------------------------------

_TASK_TMPL = """AAF_TASK_BEGIN
# Task ID
A3QF-{case}

# Task Name
executor qualification fix runner integration

# Workspace
D:\\AdyAI\\ai-agent-framework

# Objective
{objective}

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过

AAF_TASK_END
"""


def _task(risk: str) -> str:
    body = _TASK_TMPL.format(case="RUN", objective="验证 executor qualification。")
    return body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)


def _structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = ('{"verdict": "PASS", "blocking_rework": false, '
                 '"blocking_provenance": "structured", "findings": [], "warnings": []}')
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END"


def _run_runner(tmp_path, monkeypatch, task_text, registry, fake_run_agent):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(mr, "baseline_registry", lambda: registry)
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    runner_mod.run(task_file, ws, out)
    return out


def test_runner_aux_only_pool_keeps_configured_no_fallback(tmp_path, monkeypatch):
    """runner 全链：LOW + 全 aux-only 池 → 零 env 覆盖（configured 保留）、
    routing_applied=false、excluded=AUXILIARY_ONLY、fallback_attempted=false、
    全链 SUCCESS（无 silent fallback、Paid Guard 语义零变化——hermetic
    resolution LOCAL_FREE → ALLOWED_FREE）。"""
    seen_env = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen_env["model"] = os.environ.get(cg.ENV_MODEL)
        return _structured_ok(agent)

    aux_reg = _registry(
        _entry(model="aux1", provider="custom",
               qualification=mr.RuntimeQualification(
                   status=mr.QUAL_STATUS_QUALIFIED, scope=QUAL_AUX)),
    )
    out = _run_runner(tmp_path, monkeypatch, _task("LOW"), aux_reg, fake_run_agent)
    assert seen_env["model"] is None  # 未路由 → 无 env 覆盖
    active = ar.load_active_routing(out)
    assert active is not None
    assert active["routing_applied"] is False
    assert active["fallback_attempted"] is False
    assert active["selected"] is None
    assert active["reason"].startswith(ar.REASON_NO_ELIGIBLE)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_main_free_no_fallback_on_failure(tmp_path, monkeypatch):
    """runner 全链：main-scope free 被路由后 invocation 失败 → 如实
    FRAMEWORK_ERROR（恰一次 hermes 调用）、routing_applied=true 证据保留、
    fallback_attempted=false（绝不静默回退 configured/其他模型）→ WAITING。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == "hermes":
            raise RuntimeError("routed main-free invocation failed (simulated)")
        return _structured_ok(agent)

    main_free_reg = _registry(_entry(model="main-free", provider="p"))
    out = _run_runner(tmp_path, monkeypatch, _task("LOW"), main_free_reg, fake_run_agent)
    assert calls.count("hermes") == 1
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")
    active = ar.load_active_routing(out)
    assert active["routing_applied"] is True
    assert active["fallback_attempted"] is False
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    assert cg.ENV_MODEL not in os.environ  # env 已还原（无泄漏）
