"""AAF v0.5 A5 — bounded FREE/LOCAL_FREE fallback runtime focused tests.

TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001（Requirement 10 全矩阵）：
- eligible original failure + qualified FREE candidate -> exactly one fallback attempt
- fallback success -> fallback_used=true and final actual model/provider = fallback candidate
- fallback failure -> no third invocation（attempted=true / used=false / no chain）
- no eligible free candidate -> no second invocation（fail closed，原始失败保留）
- auxiliary/unknown qualification candidate excluded
- same original model excluded
- paid/unknown-cost candidate not silently used（含 A0 guard BLOCKED 路径）
- non-fallback-eligible failure -> no fallback
- same-model transport retry does not consume fallback budget
- audit record validates for each live outcome（validate + 落盘 reload 复验）

第 1 节：runtime 模块单元（classify_failure / gate / 记录 / validator / 编排器）；
第 2 节：真实 runner Hermes stage 集成（A3 初始 routing 保持 + A5 失败后 fallback +
artifact + env 还原 + 链状态）。
"""

import json
import os
import subprocess as subprocess_mod
from pathlib import Path

import pytest

import ai_agent_framework.cost_guard as cg
import ai_agent_framework.model_registry as mr
import ai_agent_framework.runner as runner_mod
from ai_agent_framework import active_routing as ar
from ai_agent_framework import fallback_contract as fc
from ai_agent_framework import fallback_runtime as fr
from ai_agent_framework import model_observation as mo
from ai_agent_framework import shadow_observation as so
from ai_agent_framework.risk_contract import RISK_LOW, ROLE_EXECUTOR

_REAL_RESOLVE = cg.resolve_effective_hermes  # conftest hermetic patch 前的真实实现

FREE = mo.COST_CLASS_FREE
LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
PAID = mo.COST_CLASS_PAID
UNKNOWN = mo.COST_CLASS_UNKNOWN


@pytest.fixture(autouse=True)
def _scrub_a5_env(monkeypatch):
    """本文件 hermetic 保证：编排器/runner 直接写 os.environ 的 AAF_HERMES_*
    覆盖（fallback candidate overlay 在 observation 后才还原）不得跨测试泄漏；
    monkeypatch 的 cleanup 会在测试结束后把每个变量还原/删除。"""
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL, cg.ENV_AUTH):
        monkeypatch.delenv(var, raising=False)


def _entry(
    model: str,
    *,
    provider: str = "custom",
    tier: str = "T4",
    cost: str = LOCAL_FREE,
    scope: str = mr.QUAL_SCOPE_MAIN,
    qual_status: str = mr.QUAL_STATUS_QUALIFIED,
    base_url: str | None = "http://127.0.0.1:11434/v1",
    locality: str = mr.LOCALITY_LOCAL,
) -> mr.RegistryEntry:
    return mr.RegistryEntry(
        model=model,
        provider=provider,
        base_url=base_url,
        applicable_agents=("hermes",),
        capability_tier=tier,
        cost_class=cost,
        locality=locality,
        qualification=mr.RuntimeQualification(
            status=qual_status,
            scope=scope,
            evidence=("a5-runtime-test-fixture",),
            observed_at="2026-09-02T00:00:00",
        ),
        evidence=("a5-runtime-test-fixture",),
    )


def _registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


# ---------------------------------------------------------------------------
# 1a. classify_failure（最小分类器；evidence-based，fail closed）
# ---------------------------------------------------------------------------


def test_classify_runtime_error_is_invocation_failure():
    cls = fr.classify_failure(RuntimeError("hermes failed (exit=1)\nSTDERR: boom"))
    assert cls["failure_class"] == fc.FAILURE_INVOCATION
    assert "RuntimeError" in cls["trigger"]
    assert cls["trigger_evidence"]


def test_classify_missing_command_is_framework_config():
    cls = fr.classify_failure(RuntimeError("MISSING_COMMAND: hermes"))
    assert cls["failure_class"] == fc.FAILURE_FRAMEWORK_INPUT_CONFIG


def test_classify_timeout_is_transport_runtime():
    exc = subprocess_mod.TimeoutExpired("hermes", 3600)
    cls = fr.classify_failure(exc)
    assert cls["failure_class"] == fc.FAILURE_TRANSPORT_RUNTIME


@pytest.mark.parametrize(
    "exc", [OSError(13, "permission denied"), ValueError("boom"), KeyError("k")]
)
def test_classify_other_exceptions_fail_closed(exc):
    cls = fr.classify_failure(exc)
    assert cls["failure_class"] == fc.FAILURE_FRAMEWORK_INPUT_CONFIG


# ---------------------------------------------------------------------------
# 1b. 编排器核心矩阵（fail closed / one attempt / gate / audit）
# ---------------------------------------------------------------------------


def _run(
    registry,
    *,
    exc=RuntimeError("hermes failed (exit=1) STDERR: simulated model failure"),
    invoke=None,
    calls=None,
    risk=RISK_LOW,
    transport_retry_count=0,
    monkeypatch=None,
    output_dir=None,
    tmp_path=None,
):
    out_dir = Path(output_dir) if output_dir else None
    if out_dir is None:
        out_dir = Path(tmp_path) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    state = {"calls": 0, "envs": []}
    real_invoke = invoke

    def default_invoke(agent, prompt, workspace):
        state["calls"] += 1
        state["envs"].append(
            {
                "model": os.environ.get(cg.ENV_MODEL),
                "provider": os.environ.get(cg.ENV_PROVIDER),
                "base_url": os.environ.get(cg.ENV_BASE_URL),
            }
        )
        return "ok\nAAF_STRUCTURED_RESULT_BEGIN\n{\"status\": \"SUCCESS\"}\nAAF_STRUCTURED_RESULT_END"

    outcome = fr.run_fallback_after_failure(
        task_id="A5R-UNIT-1",
        risk_class=risk,
        risk_source=so.TASK_RISK_SOURCE,
        registry=registry,
        output_dir=out_dir,
        prompt="TASK",
        workspace=Path(tmp_path),
        invoke=real_invoke or default_invoke,
        failure_exc=exc,
        transport_retry_count=transport_retry_count,
    )
    # 模拟 runner 语义：fallback overlay 在 observation 之后还原（测试隔离）
    if outcome is not None and outcome.get("overlay_saved"):
        ar.restore_routing_env(outcome["overlay_saved"])
    if calls is not None:
        calls.update(state)
    return outcome, out_dir, state


def test_eligible_success_exactly_one_fallback_attempt(tmp_path):
    """eligible original failure + 合格 FREE 候选 → 恰一次 fallback attempt →
    used=true、final actual = fallback candidate、artifact 校验通过。"""
    reg = _registry(_entry("fb-1"), _entry("fb-2"))
    outcome, out_dir, state = _run(reg, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert outcome["attempted"] is True
    assert outcome["used"] is True
    assert state["calls"] == 1  # 恰一次 fallback invocation
    assert rec["fallback_attempted"] is True
    assert rec["fallback_used"] is True
    assert rec["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    assert rec["fallback_candidate"] == "fb-1@custom"  # 确定性选择（key 最小）
    assert rec["final_actual_model"] == "fb-1"
    assert rec["final_actual_provider"] == "custom"
    assert rec["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE
    assert rec["paid_escalation_required"] is False
    assert outcome["result_text"].startswith("ok")
    assert outcome["overlay_saved"] is not None
    fr.validate_fallback_runtime_record(rec)
    # artifact 落盘 + reload 复验（audit record validates for this live outcome）
    loaded = fr.load_fallback_runtime(out_dir)
    assert loaded is not None
    fr.validate_fallback_runtime_record(loaded)
    assert loaded["final_actual_model"] == "fb-1"


def test_eligible_fallback_failure_no_third_invocation(tmp_path):
    """fallback failure → 恰 2 次 invocation（original + 1 fallback）、无第三模型、
    attempted=true / used=false、原始失败保留（result_text=None）、chain 语义由
    runner 决定（WAITING）。"""
    reg = _registry(_entry("fb-1"))

    def failing_invoke(agent, prompt, workspace):
        raise RuntimeError("fallback model also failed (simulated)")

    outcome, out_dir, state = _run(reg, invoke=failing_invoke, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None  # runner 保留原始 FRAMEWORK_ERROR
    assert rec["fallback_attempted"] is True
    assert rec["fallback_used"] is False
    assert rec["final_actual_model"] == "fb-1"
    assert rec["decision"] == fc.DECISION_FALLBACK_ELIGIBLE
    # evidence 显式声明 no-chain
    assert any("ONE attempt" in e or "one attempt" in e for e in rec["no_silent_fallback_evidence"])
    fr.validate_fallback_runtime_record(rec)


def test_no_eligible_free_candidate_no_second_invocation(tmp_path):
    """无合格 free 候选（paid / unknown-cost 全被 Requirement-3 gate 排除）→
    无第二 invocation、attempted=false、decision=fallback_not_eligible、原始
    失败保留。"""
    reg = _registry(
        _entry("fb-paid", cost=PAID, base_url=None, locality=mr.LOCALITY_REMOTE),
        _entry("fb-unk", cost=UNKNOWN, base_url=None, locality=mr.LOCALITY_REMOTE),
    )
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert calls["calls"] == 0  # 无第二 invocation
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    assert outcome["overlay_saved"] is None
    assert rec["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rec["fallback_candidates"] == []
    assert rec["authorization_outcome"] == fr.AUTH_OUTCOME_NONE
    assert rec["final_actual_model"] == "orig-model" or rec["original_model"] == rec["final_actual_model"]
    assert any("never silently used" in n for n in rec["notes"])
    fr.validate_fallback_runtime_record(rec)


def test_auxiliary_scope_candidate_excluded(tmp_path):
    """auxiliary-only qualification scope 候选被既有 selector 排除（executor
    主调用资格闸）→ 无候选 → 不 attempt。"""
    reg = _registry(
        _entry("aux-1", scope=mr.QUAL_SCOPE_AUXILIARY),
        _entry("unk-scope-1", scope=mr.QUAL_SCOPE_UNKNOWN),
        _entry("no-qual-1", qual_status=mr.QUAL_STATUS_UNKNOWN),
    )
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert outcome["attempted"] is False
    assert rec["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rec["fallback_candidates"] == []
    fr.validate_fallback_runtime_record(rec)


def test_same_original_model_excluded(tmp_path, monkeypatch):
    """same original model 绝不出现在 fallback candidates（同模型恢复 = retry 层）。"""
    monkeypatch.setenv(cg.ENV_MODEL, "fb-1")
    monkeypatch.setenv(cg.ENV_PROVIDER, "custom")
    reg = _registry(_entry("fb-1"), _entry("fb-2"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert "fb-1@custom" not in rec["fallback_candidates"]
    assert rec["fallback_candidates"] == ["fb-2@custom"]
    assert outcome["attempted"] is True  # 仍可 fallback 到不同候选


def test_same_original_model_only_candidate_fail_closed(tmp_path, monkeypatch):
    """original 是唯一合格候选（且同为被 gate 允许的 free 候选）→ 排除后无候选
    → no second invocation（ONLY_SAME_MODEL 语义）。"""
    monkeypatch.setenv(cg.ENV_MODEL, "fb-1")
    monkeypatch.setenv(cg.ENV_PROVIDER, "custom")
    reg = _registry(_entry("fb-1"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert outcome["attempted"] is False
    assert rec["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert rec["fallback_candidates"] == []
    assert fc.REASON_ONLY_SAME_MODEL in rec["decision_reason"] or fc.REASON_NO_QUALIFIED_CANDIDATE in rec["decision_reason"]
    fr.validate_fallback_runtime_record(rec)


def test_non_fallback_eligible_failure_no_fallback(tmp_path):
    """非 fallback-eligible 失败（OSError → framework/input/config）→ decision
    blocked_fail_closed、无 attempt（即使 registry 有合格 free 候选——失败分类
    边界优先）。"""
    reg = _registry(_entry("fb-1"))
    outcome, out_dir, state = _run(reg, exc=OSError(13, "permission denied"), tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert outcome["attempted"] is False
    assert state["calls"] == 0
    assert rec["decision"] == fc.DECISION_BLOCKED_FAIL_CLOSED
    assert rec["failure_class"] == fc.FAILURE_FRAMEWORK_INPUT_CONFIG
    assert rec["fallback_attempted"] is False
    fr.validate_fallback_runtime_record(rec)


def test_missing_command_no_fallback(tmp_path):
    reg = _registry(_entry("fb-1"))
    outcome, _out_dir, state = _run(
        reg, exc=RuntimeError("MISSING_COMMAND: hermes"), tmp_path=tmp_path
    )
    rec = outcome["audit_record"]
    assert outcome["attempted"] is False
    assert state["calls"] == 0
    assert rec["decision"] == fc.DECISION_BLOCKED_FAIL_CLOSED
    fr.validate_fallback_runtime_record(rec)


def test_transport_timeout_is_trigger_capable(tmp_path):
    """TimeoutExpired → FAILURE_TRANSPORT_RUNTIME（trigger-capable）：合格 free
    候选存在 → 恰一次 fallback attempt。"""
    reg = _registry(_entry("fb-1"))
    exc = subprocess_mod.TimeoutExpired("hermes", 3600)
    outcome, _out_dir, state = _run(reg, exc=exc, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert rec["failure_class"] == fc.FAILURE_TRANSPORT_RUNTIME
    assert outcome["attempted"] is True
    assert state["calls"] == 1
    fr.validate_fallback_runtime_record(rec)


def test_transport_retry_does_not_consume_fallback_budget(tmp_path):
    """same-model transport retry 不计入 one-fallback 预算：transport_retry_count>0
    时 stage 仍拥有其一次 model-level fallback（attempted 只反映第二模型
    invocation），审计 evidence 显式声明 retry 分离。"""
    reg = _registry(_entry("fb-1"))
    outcome, out_dir, state = _run(
        reg, transport_retry_count=3, tmp_path=tmp_path
    )
    rec = outcome["audit_record"]
    assert rec["transport_retry_count"] == 3
    assert rec["automatic_fallback_count_used"] == 0
    assert outcome["attempted"] is True  # retry 不消耗 fallback 预算
    assert state["calls"] == 1
    assert any("transport retries" in e for e in rec["no_silent_fallback_evidence"])
    fr.validate_fallback_runtime_record(rec)
    # 纯决策层复核：retry 不影响 decision/count（contract 同语义）
    decision = fc.decide_fallback(
        failure_class=fc.FAILURE_INVOCATION,
        trigger="t",
        task_id="T",
        stage_agent="hermes",
        role="executor",
        risk_class=RISK_LOW,
        risk_source="test",
        original_model="orig-x",
        original_provider="p",
        registry=reg,
        transport_retry_count=5,
    )
    assert decision["automatic_fallback_count_used"] == 0
    assert decision["fallback_attempted"] is False
    fc.validate_fallback_record(decision)


def test_guard_blocked_candidate_no_silent_paid(tmp_path, monkeypatch):
    """eligible FREE（远程免费）候选但 A0 Paid Guard 无精确授权 → BLOCKED →
    无 attempt、authorization_outcome=BLOCKED_COST_APPROVAL（no silent paid）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.delenv(cg.ENV_AUTH, raising=False)
    # remote FREE 候选：registry 说 FREE，但 A0 无远程 FREE 权威 → 无授权则 BLOCKED
    reg = _registry(
        _entry(
            "remote-free",
            provider="remote-api",
            cost=FREE,
            base_url=None,
            locality=mr.LOCALITY_REMOTE,
        )
    )
    outcome, out_dir, state = _run(reg, tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec = outcome["audit_record"]
    assert state["calls"] == 0  # BLOCKED → 无第二 invocation
    assert outcome["attempted"] is False
    assert outcome["overlay_saved"] is None
    # env 覆盖已被还原（BLOCKED 不保留 candidate env）
    assert os.environ.get(cg.ENV_MODEL) is None or os.environ.get(cg.ENV_MODEL) != "remote-free"
    assert rec["decision"] == fc.DECISION_FALLBACK_ELIGIBLE  # contract 层 eligible
    assert rec["fallback_eligible"] is True
    assert rec["fallback_attempted"] is False
    assert rec["authorization_outcome"] == fr.AUTH_OUTCOME_BLOCKED
    assert rec["final_actual_model"] == rec["original_model"]
    assert any("no silent paid fallback" in e.lower() or "not silently" in e.lower()
               or "no second model" in e for e in rec["no_silent_fallback_evidence"])
    fr.validate_fallback_runtime_record(rec)


def test_no_risk_no_evaluation(tmp_path):
    """Risk 缺失 → 无法按 contract 决策 → 不评估（None；零 artifact）。"""
    reg = _registry(_entry("fb-1"))
    out_dir = Path(tmp_path) / "out"
    out_dir.mkdir()
    outcome = fr.run_fallback_after_failure(
        task_id="T",
        risk_class=None,
        risk_source=None,
        registry=reg,
        output_dir=out_dir,
        prompt="p",
        workspace=Path(tmp_path),
        invoke=lambda a, p, w: "ok",
        failure_exc=RuntimeError("boom"),
    )
    assert outcome is None
    assert not (out_dir / fr.ARTIFACT_FILENAME).exists()


def test_audit_validator_mutation_matrix(tmp_path):
    """audit record fail-closed：矛盾组合全部 ValueError。"""
    reg = _registry(_entry("fb-1"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = dict(outcome["audit_record"])
    fr.validate_fallback_runtime_record(rec)
    # used=true 但 attempted=false
    bad = dict(rec, fallback_attempted=False, fallback_used=True)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # attempted=true 但缺 ALLOWED admission
    bad = dict(rec, fallback_attempted=True, fallback_used=True,
               authorization_outcome=fr.AUTH_OUTCOME_NONE)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # final actual 与 candidate 不一致
    bad = dict(rec, final_actual_model="someone-else")
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # eligible 但未 attempt 且非 BLOCKED
    outcome2, out_dir2, _ = _run(_registry(_entry("fb-1")), tmp_path=tmp_path)
    rec2 = dict(outcome2["audit_record"])
    fr.validate_fallback_runtime_record(rec2)
    bad = dict(rec2, fallback_attempted=False, fallback_used=False,
               authorization_outcome=fr.AUTH_OUTCOME_NONE)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # original 出现在 candidates（用 canonical key——original 带 provider 时 key 含 @）
    orig_key = mr.canonical_key(rec["original_model"], rec["original_provider"])
    bad = dict(rec, fallback_candidates=sorted(["fb-1@custom", orig_key]))
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # 未知字段
    bad = dict(rec, extra_field=1)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # authority 被篡改
    bad = dict(rec, authority="tampered")
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # decision_kind 错
    bad = dict(rec, decision_kind="fallback_decision")
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    # count_used 超预算
    bad = dict(rec, automatic_fallback_count_used=2)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)


def test_multiple_free_candidates_single_deterministic_attempt(tmp_path):
    """多合格 free 候选 → 确定性选择恰一候选、恰一次 attempt（无 chain）。"""
    reg = _registry(
        _entry("zzz-fb", provider="custom"),
        _entry("aaa-fb", provider="custom"),
        _entry("mmm-fb", provider="other", locality=mr.LOCALITY_REMOTE, base_url=None),
    )
    # aaa-fb 本地 + key 最小 → 选中；mmm-fb remote（locality 次级）不入选
    outcome, out_dir, state = _run(reg, tmp_path=tmp_path)
    rec = outcome["audit_record"]
    assert outcome["attempted"] is True
    assert state["calls"] == 1
    assert rec["fallback_candidate"] == "aaa-fb@custom"
    assert rec["final_actual_model"] == "aaa-fb"
    assert len(rec["fallback_candidates"]) == 3
    fr.validate_fallback_runtime_record(rec)


def test_artifact_json_roundtrip_and_stage_fields(tmp_path):
    reg = _registry(_entry("fb-1"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    path = out_dir / fr.ARTIFACT_FILENAME
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["decision_kind"] == fr.DECISION_KIND
    assert data["authoritative"] is True
    fr.validate_fallback_runtime_record(data)


# ---------------------------------------------------------------------------
# 2. 真实 runner Hermes stage 集成
# ---------------------------------------------------------------------------

_TASK_TMPL = """AAF_TASK_BEGIN
# Task ID
A5R-{case}

# Task Name
a5 fallback runner integration

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


def _task(risk: str | None) -> str:
    body = _TASK_TMPL.format(case="RUN", objective="验证 A5 fallback runtime。")
    if risk is not None:
        body = body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)
    return body


def _structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = ('{"verdict": "PASS", "blocking_rework": false, '
                 '"blocking_provenance": "structured", "findings": [], "warnings": []}')
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END"


def _run_runner(tmp_path, monkeypatch, task_text, fake_run_agent=None):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    if fake_run_agent is None:
        fake_run_agent = lambda agent, prompt, workspace: _structured_ok(agent)  # noqa: E731
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    runner_mod.run(task_file, ws, out)
    return out


def test_runner_original_failure_then_exactly_one_fallback_success(tmp_path, monkeypatch):
    """全链（真实 runner + mock run_agent）：LOW risk + 受控 registry（A3 初始
    routing 到 aaa-orig）→ aaa-orig invocation 失败 → A5 fallback 恰一次到
    zzz-fb（env 覆盖可见）→ fallback 成功 → 全链 SUCCESS、audit used=true、
    final actual=zzz-fb、env 还原。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-fb"),
    ))
    seen = {"hermes_calls": 0, "envs": []}

    def fake_run_agent(agent, prompt, workspace):
        seen["envs"].append(
            {
                "model": os.environ.get(cg.ENV_MODEL),
                "provider": os.environ.get(cg.ENV_PROVIDER),
            }
        )
        if agent == "hermes":
            seen["hermes_calls"] += 1
            if seen["hermes_calls"] == 1:
                raise RuntimeError("original invocation failed (simulated)")
            # 第二次 = fallback invocation（env 覆盖应为 zzz-fb）
            return _structured_ok(agent)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    # A3 初始 routing 生效（第一次 invocation env = aaa-orig）
    assert seen["envs"][0]["model"] == "aaa-orig"
    # 恰一次 fallback：第二次 invocation env = zzz-fb（candidate）
    assert seen["hermes_calls"] == 2
    assert seen["envs"][1]["model"] == "zzz-fb"
    # audit artifact：attempted/used=true、final actual = zzz-fb
    audit = fr.load_fallback_runtime(out)
    assert audit is not None
    assert audit["fallback_attempted"] is True
    assert audit["fallback_used"] is True
    assert audit["original_model"] == "aaa-orig"
    assert audit["final_actual_model"] == "zzz-fb"
    assert audit["fallback_candidate"] == "zzz-fb@custom"
    fr.validate_fallback_runtime_record(audit)
    # stage result 携带 authority 引用
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage.get("fallback_runtime_ref", {}).get("entry") == "hermes"
    assert stage.get("active_routing_ref", {}).get("entry") == "hermes"
    # env 已还原（不泄漏到后续 stage）
    assert cg.ENV_MODEL not in os.environ
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_fallback_failure_no_chain(tmp_path, monkeypatch):
    """fallback 也失败 → 恰 2 次 invocation（original + 1 fallback）、无第三模型、
    链中断 WAITING、audit attempted=true/used=false/final=fallback model。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-fb"),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("all hermes invocations fail (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 2  # original + 恰一次 fallback；无第三模型
    audit = fr.load_fallback_runtime(out)
    assert audit["fallback_attempted"] is True
    assert audit["fallback_used"] is False
    assert audit["final_actual_model"] == "zzz-fb"
    assert audit["original_model"] == "aaa-orig"
    fr.validate_fallback_runtime_record(audit)
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")  # 原始失败保留（不伪装）
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


def test_runner_no_eligible_free_candidate_fail_closed(tmp_path, monkeypatch):
    """只有 paid/unknown-cost 其他候选 → 无第二 invocation（1 次总调用）、
    attempted=false、WAITING、无 silent paid。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-paid", cost=PAID, base_url=None, locality=mr.LOCALITY_REMOTE),
        _entry("mmm-unk", cost=UNKNOWN, base_url=None, locality=mr.LOCALITY_REMOTE,
               provider="deepseek"),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 1  # 无 fallback attempt
    audit = fr.load_fallback_runtime(out)
    assert audit["fallback_attempted"] is False
    assert audit["fallback_used"] is False
    assert audit["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
    assert audit["final_actual_model"] == audit["original_model"]
    fr.validate_fallback_runtime_record(audit)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


def test_runner_auxiliary_only_candidate_no_fallback(tmp_path, monkeypatch):
    """aux-only（scope=auxiliary）合格 LOCAL_FREE 候选 → selector 排除 →
    fallback candidates 空 → 无第二 invocation。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("aux-local", scope=mr.QUAL_SCOPE_AUXILIARY),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 1
    audit = fr.load_fallback_runtime(out)
    assert audit["fallback_attempted"] is False
    assert "aux-local@custom" not in audit["fallback_candidates"]
    fr.validate_fallback_runtime_record(audit)


def test_runner_non_fallback_eligible_failure_preserved(tmp_path, monkeypatch):
    """非 fallback-eligible 失败（MISSING_COMMAND 类）→ blocked_fail_closed、
    无 attempt、WAITING（原始失败保留）。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-fb"),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("MISSING_COMMAND: hermes")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 1
    audit = fr.load_fallback_runtime(out)
    assert audit["decision"] == fc.DECISION_BLOCKED_FAIL_CLOSED
    assert audit["failure_class"] == fc.FAILURE_FRAMEWORK_INPUT_CONFIG
    assert audit["fallback_attempted"] is False
    fr.validate_fallback_runtime_record(audit)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


def test_runner_guard_blocked_remote_free_no_silent_paid(tmp_path, monkeypatch):
    """eligible 远程 FREE 候选无授权 → A0 BLOCKED → 无第二 invocation、
    authorization_outcome=BLOCKED_COST_APPROVAL、WAITING（no silent paid）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.delenv(cg.ENV_AUTH, raising=False)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry(
            "remote-free",
            provider="remote-api",
            cost=FREE,
            base_url=None,
            locality=mr.LOCALITY_REMOTE,
        ),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 1
    audit = fr.load_fallback_runtime(out)
    assert audit["fallback_eligible"] is True
    assert audit["fallback_attempted"] is False
    assert audit["authorization_outcome"] == fr.AUTH_OUTCOME_BLOCKED
    assert audit["paid_escalation_required"] is False
    assert audit["final_actual_model"] == audit["original_model"]
    fr.validate_fallback_runtime_record(audit)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


def test_runner_missing_risk_no_a5_evaluation(tmp_path, monkeypatch):
    """Risk 缺失任务：Hermes 失败 → 无 A5 评估（无 artifact）、单次调用、
    A3 routing 不生效（既有语义保持）。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-fb"),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(None), fake_run_agent)
    assert hermes_calls["n"] == 1
    assert fr.load_fallback_runtime(out) is None  # 无 A5 artifact
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


def test_runner_a3_routing_behavior_preserved_on_success(tmp_path, monkeypatch):
    """A3 初始 routing 行为保持：成功路径零 A5 干预（无 artifact）、routing
    照常 applied、全链 SUCCESS。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-fb"),
    ))
    seen_env = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen_env["model"] = os.environ.get(cg.ENV_MODEL)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert seen_env["model"] == "aaa-orig"  # A3 routing 照常生效（初始选择）
    active = ar.load_active_routing(out)
    assert active["routing_applied"] is True
    assert active["fallback_attempted"] is False
    assert fr.load_fallback_runtime(out) is None  # 无失败 → 无 A5 评估/artifact
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_same_model_only_no_fallback(tmp_path, monkeypatch):
    """A3 路由的 original 是 registry 唯一合格候选 → same-model 排除后无候选
    → 恰一次调用、attempted=false、WAITING（A3 无 silent fallback 语义在
    A5 下有界评估后保持 fail closed）。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
    ))
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 1
    audit = fr.load_fallback_runtime(out)
    assert audit["fallback_attempted"] is False
    assert audit["fallback_candidates"] == []
    assert audit["original_model"] == "aaa-orig"
    fr.validate_fallback_runtime_record(audit)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


# ---------------------------------------------------------------------------
# 3. FIX-001（TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001）
#    admission fail-closed + authoritative audit closure 收口
# ---------------------------------------------------------------------------


def test_fix001_authorized_paid_never_invokes(tmp_path, monkeypatch):
    """FIX-001 Codex BLOCKING #1：registry 候选标 FREE（远程免费）但 A0 Paid
    Guard 权威解析 = paid + AAF_COST_AUTH 精确匹配 → ALLOWED_AUTHORIZED_PAID
    → 本 FREE-only 单元拒绝：无第二 invocation、attempted=false、
    authorization_outcome=ALLOWED_AUTHORIZED_PAID 如实记录（A0 已在 admission
    边界按既有一次性语义 claim 授权——A0 零修改）、no-silent-paid evidence、
    artifact 校验通过、env 覆盖已还原。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    reg = _registry(
        _entry(
            "remote-free",
            provider="remote-api",
            cost=FREE,
            base_url=None,
            locality=mr.LOCALITY_REMOTE,
        )
    )
    auth = cg.scope_string("A5R-UNIT-1", "hermes", "remote-free", "remote-api")
    monkeypatch.setenv(cg.ENV_AUTH, auth)
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path,
                                   monkeypatch=monkeypatch)
    rec = outcome["audit_record"]
    assert calls["calls"] == 0  # authorized-paid 绝不进入第二模型 invocation
    assert outcome["attempted"] is False
    assert outcome["used"] is False
    assert outcome["result_text"] is None  # 原始失败保留
    assert outcome["overlay_saved"] is None
    assert os.environ.get(cg.ENV_MODEL) != "remote-free"  # env 已还原
    assert rec["decision"] == fc.DECISION_FALLBACK_ELIGIBLE  # contract 层 eligible
    assert rec["fallback_eligible"] is True
    assert rec["fallback_attempted"] is False
    assert rec["fallback_used"] is False
    # A0 权威 token 如实记录（不伪装成 BLOCKED / 不伪造 guard 结果）
    assert rec["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID
    assert rec["paid_escalation_required"] is False
    assert rec["final_actual_model"] == rec["original_model"]
    # A0 在 admission 边界按既有一次性语义 claim 了精确 scope 授权（既有行为，
    # 本层不 bypass/复刻；claim ≠ 本单元执行 paid fallback）
    assert (out_dir / cg.CONSUMPTION_FILENAME).exists()
    notes_text = " ".join(rec["notes"])
    evidence_text = " ".join(rec["no_silent_fallback_evidence"])
    assert "paid escalation is a later A5 unit's scope" in notes_text
    assert "was NOT invoked" in evidence_text
    assert "no silent paid fallback" in evidence_text
    fr.validate_fallback_runtime_record(rec)
    # artifact 落盘 + reload 复验
    loaded = fr.load_fallback_runtime(out_dir)
    assert loaded is not None
    fr.validate_fallback_runtime_record(loaded)
    assert loaded["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID


def test_fix001_cost_auth_cannot_convert_free_unit_to_paid(tmp_path, monkeypatch):
    """FIX-001：AAF_COST_AUTH 存在且精确匹配 → 若候选真实免费（LOCAL_FREE
    loopback），guard 仍 ALLOWED_FREE → 恰一次 invocation、零授权消费（A0
    只在 paid 分支 claim）；auth 存在本身既不阻断免费 fallback 也不能把本
    单元变成 paid fallback。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    # 本地 LOCAL_FREE 候选（loopback 端点 → guard ALLOWED_FREE）
    reg = _registry(_entry("fb-local"))
    auth = cg.scope_string("A5R-UNIT-1", "hermes", "fb-local", "custom")
    monkeypatch.setenv(cg.ENV_AUTH, auth)
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path,
                                   monkeypatch=monkeypatch)
    rec = outcome["audit_record"]
    assert calls["calls"] == 1  # 真实免费候选仍可 fallback（auth 不阻断免费）
    assert outcome["attempted"] is True
    assert outcome["used"] is True
    assert rec["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE
    assert rec["fallback_attempted"] is True
    assert rec["fallback_used"] is True
    assert not (out_dir / cg.CONSUMPTION_FILENAME).exists()  # 零授权消费
    fr.validate_fallback_runtime_record(rec)


def test_fix001_auth_mismatch_blocked_no_invocation(tmp_path, monkeypatch):
    """FIX-001：registry FREE 远程候选 + AAF_COST_AUTH 存在但 scope 不匹配 →
    A0 BLOCKED（unknown-paid/未授权语义）→ 无第二 invocation、attempted=false、
    authorization_outcome=BLOCKED_COST_APPROVAL、notes 显式 mismatch。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    reg = _registry(
        _entry(
            "remote-free",
            provider="remote-api",
            cost=FREE,
            base_url=None,
            locality=mr.LOCALITY_REMOTE,
        )
    )
    monkeypatch.setenv(cg.ENV_AUTH, "WRONG|scope|remote-free|remote-api")
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path,
                                   monkeypatch=monkeypatch)
    rec = outcome["audit_record"]
    assert calls["calls"] == 0
    assert outcome["attempted"] is False
    assert rec["authorization_outcome"] == fr.AUTH_OUTCOME_BLOCKED
    assert rec["fallback_attempted"] is False
    assert any("did not exactly match" in n for n in rec["notes"])
    fr.validate_fallback_runtime_record(rec)


def test_fix001_validator_rejects_attempted_with_authorized_paid(tmp_path):
    """FIX-001 validator 不变量：attempted=true 只允许 ALLOWED_FREE admission；
    ALLOWED_AUTHORIZED_PAID + attempted=true（paid fallback 执行）→ ValueError；
    eligible-未attempt 且 auth=NONE（非合法拒绝形态）→ ValueError。"""
    reg = _registry(_entry("fb-1"))
    outcome, out_dir, _state = _run(reg, tmp_path=tmp_path)
    rec = dict(outcome["audit_record"])
    fr.validate_fallback_runtime_record(rec)
    bad = dict(rec, authorization_outcome=fr.AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)
    bad = dict(rec, fallback_attempted=False, fallback_used=False,
               authorization_outcome=fr.AUTH_OUTCOME_NONE)
    with pytest.raises(ValueError):
        fr.validate_fallback_runtime_record(bad)


def test_fix001_audit_validation_failure_after_fallback_success(tmp_path, monkeypatch):
    """FIX-001 Codex BLOCKING #2（audit validation failure）：fallback invocation
    成功产出有效输出，但权威 audit 校验失败 → 输出**不**被接受（attempted=true /
    used=false / result_text=None）、audit failure 显式 surface、无 artifact、
    无第三模型 invocation。"""
    reg = _registry(_entry("fb-1"))
    real_validate = fr.validate_fallback_runtime_record

    def flaky_validate(record):
        if record.get("fallback_attempted") is True:
            raise ValueError("simulated audit validation failure (FIX-001)")
        return real_validate(record)

    monkeypatch.setattr(fr, "validate_fallback_runtime_record", flaky_validate)
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path,
                                   monkeypatch=monkeypatch)
    assert calls["calls"] == 1  # fallback invocation 恰一次已发生；无第三模型
    assert outcome["attempted"] is True       # 不假装 attempt 未发生
    assert outcome["used"] is False           # 输出不被接受
    assert outcome["result_text"] is None     # 原始失败保留（fail-closed）
    assert outcome["audit_record"] is None
    assert outcome["artifact_ref"] is None
    assert "audit closure" in outcome["audit_closure_error"]
    assert "simulated audit validation failure" in outcome["audit_closure_error"]
    assert not (out_dir / fr.ARTIFACT_FILENAME).exists()  # 无权威 audit 落盘
    # overlay 由调用方还原（模拟 runner 语义）
    assert os.environ.get(cg.ENV_MODEL) != "fb-1"


def test_fix001_audit_persistence_failure_after_fallback_success(tmp_path, monkeypatch):
    """FIX-001 Codex BLOCKING #2（audit persistence failure）：fallback invocation
    成功但权威 audit 写盘失败 → 输出**不**被接受（attempted=true / used=false /
    result_text=None）、audit failure 显式 surface、无 artifact、无第三模型。"""
    reg = _registry(_entry("fb-1"))

    def failing_save(output_dir, record):
        raise OSError("simulated audit persistence failure (FIX-001)")

    monkeypatch.setattr(fr, "save_fallback_runtime", failing_save)
    calls = {}
    outcome, out_dir, state = _run(reg, calls=calls, tmp_path=tmp_path,
                                   monkeypatch=monkeypatch)
    assert calls["calls"] == 1
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    assert outcome["audit_record"] is None
    assert outcome["artifact_ref"] is None
    assert "audit closure" in outcome["audit_closure_error"]
    assert "simulated audit persistence failure" in outcome["audit_closure_error"]
    assert not (out_dir / fr.ARTIFACT_FILENAME).exists()
    assert os.environ.get(cg.ENV_MODEL) != "fb-1"


def test_fix001_audit_failure_when_fallback_invocation_also_failed(tmp_path, monkeypatch):
    """FIX-001：fallback invocation 自身失败 + audit closure 也失败 → 仍如实
    attempted=true / used=false、audit failure 显式 surface（不静默丢弃）。"""
    reg = _registry(_entry("fb-1"))

    def failing_invoke(agent, prompt, workspace):
        raise RuntimeError("fallback model also failed (simulated)")

    def failing_save(output_dir, record):
        raise OSError("simulated audit persistence failure (FIX-001)")

    monkeypatch.setattr(fr, "save_fallback_runtime", failing_save)
    outcome, out_dir, state = _run(reg, invoke=failing_invoke, tmp_path=tmp_path,
                                   monkeypatch=monkeypatch)
    assert state["calls"] == 0  # invoke 抛异常 → default_invoke 未被调用
    assert outcome["attempted"] is True
    assert outcome["used"] is False
    assert outcome["result_text"] is None
    assert "audit closure" in outcome["audit_closure_error"]


# ---- FIX-001 runner 集成 ----


def test_runner_fix001_authorized_paid_no_fallback_invocation(tmp_path, monkeypatch):
    """真实 runner：A3 路由 aaa-orig（LOCAL_FREE）失败 → A5 候选 = registry
    FREE 远程模型 + AAF_COST_AUTH 精确匹配 → guard ALLOWED_AUTHORIZED_PAID →
    本 FREE-only 单元拒绝 → 恰 1 次 invocation（无第二模型）、audit
    attempted=false / auth=ALLOWED_AUTHORIZED_PAID、run=WAITING、无 silent
    paid execution、env 不泄漏。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("remote-free", provider="remote-api", cost=FREE, base_url=None,
               locality=mr.LOCALITY_REMOTE),
    ))
    auth = cg.scope_string("A5R-RUN", "hermes", "remote-free", "remote-api")
    monkeypatch.setenv(cg.ENV_AUTH, auth)
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            raise RuntimeError("original invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert hermes_calls["n"] == 1  # 无第二模型 invocation（no silent paid）
    audit = fr.load_fallback_runtime(out)
    assert audit["fallback_attempted"] is False
    assert audit["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID
    assert audit["fallback_eligible"] is True
    assert audit["final_actual_model"] == audit["original_model"]
    assert any("was NOT invoked" in e for e in audit["no_silent_fallback_evidence"])
    fr.validate_fallback_runtime_record(audit)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    assert cg.ENV_MODEL not in os.environ  # env 不泄漏到后续 stage


def test_runner_fix001_audit_persistence_failure_output_not_accepted(tmp_path, monkeypatch):
    """真实 runner + audit 写盘失败注入：original 失败 → fallback 恰一次成功
    调用（env 覆盖 zzz-fb）→ audit 持久化失败 → fallback 输出**不**成为 stage
    result：FRAMEWORK_ERROR 保留 + audit closure failure 显式 append、无
    fallback_runtime.json、run=WAITING、无第三模型。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _registry(
        _entry("aaa-orig"),
        _entry("zzz-fb"),
    ))
    seen = {"hermes_calls": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen["hermes_calls"] += 1
            if seen["hermes_calls"] == 1:
                raise RuntimeError("original invocation failed (simulated)")
            return _structured_ok(agent)  # fallback invocation 本身成功
        return _structured_ok(agent)

    def failing_save(output_dir, record):
        raise OSError("simulated audit persistence failure (FIX-001)")

    monkeypatch.setattr(fr, "save_fallback_runtime", failing_save)
    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert seen["hermes_calls"] == 2  # original + 恰一次 fallback；无第三模型
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")  # fallback 输出未被接受
    assert "audit closure" in result  # audit failure 显式 surface（不静默丢弃）
    assert fr.load_fallback_runtime(out) is None  # 无权威 audit artifact
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"  # fail closed → 链中断
    assert cg.ENV_MODEL not in os.environ  # env 已还原
