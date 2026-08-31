"""AAF v0.5 A3 — Active routing (LOW-risk Hermes free routing) 定向测试
（TASK: AAF-v0.5-A3-HERMES-FREE-ROUTING-001）。

覆盖 Requirement 10 测试矩阵 + 审计/隔离守卫：
- LOW + qwen3 qualified → active route 到 qwen3（真实 model/provider 选择）
- LOW 但 free candidate 不合格 → 保持 configured model
- missing Risk → 保持 configured model
- MEDIUM/HIGH/CRITICAL → 保持 configured model
- selected local invocation 失败 → 不 fallback（如实失败 + 证据保留）
- active decision 与 shadow decision 可审计（authoritative vs hypothetical 明确区分）
- Paid Guard invariant 不被绕过（routed LOCAL_FREE 经既有 loopback 判定放行）
- 复用现有 selector / registry / risk（不创建第二套路由判断）
- env 覆盖精确 apply / restore（绝不泄漏到后续 stage / 调用方）
"""

import json
import os

import pytest

import ai_agent_framework.cost_guard as cg
import ai_agent_framework.model_registry as mr
import ai_agent_framework.runner as runner_mod
from ai_agent_framework import active_routing as ar
from ai_agent_framework import model_observation as mo
from ai_agent_framework import shadow_observation as so
from ai_agent_framework import task_validation as tv
from ai_agent_framework.risk_contract import (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    ROLE_EXECUTOR,
    ROLE_REVIEWER,
)

# conftest hermetic fixture 在测试运行时 patch cg.resolve_effective_hermes；
# 模块导入时刻捕获真实实现（用于 Paid Guard invariant 端到端测试）。
_REAL_RESOLVE = cg.resolve_effective_hermes

FREE = mo.COST_CLASS_FREE
LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
PAID = mo.COST_CLASS_PAID
QUALIFIED = mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED)


def _entry(**overrides) -> mr.RegistryEntry:
    base = dict(
        model="m1",
        provider="p1",
        applicable_agents=("hermes",),
        capability_tier=mr.CAP_TIER_T4,
        cost_class=LOCAL_FREE,
        locality=mr.LOCALITY_LOCAL,
        qualification=QUALIFIED,
    )
    base.update(overrides)
    return mr.RegistryEntry(**base)


def _registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


# ---------------------------------------------------------------------------
# 1. LOW + qualified free → active route（Requirement 3/10）
# ---------------------------------------------------------------------------


def test_low_qualified_free_routes_to_qwen3_baseline():
    """基线 registry：LOW executor + hermes → qwen3:4b@custom 被真实选中。"""
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source=so.TASK_RISK_SOURCE,
        configured_model="deepseek-v4-flash", configured_provider="deepseek",
    )
    assert rec["routing_applied"] is True
    assert rec["selected"] == "qwen3:4b@custom"
    assert rec["routed_model"] == "qwen3:4b"
    assert rec["routed_provider"] == "custom"
    assert rec["routed_base_url"] == "http://127.0.0.1:11434/v1"
    assert rec["configured_model"] == "deepseek-v4-flash"
    assert rec["configured_provider"] == "deepseek"
    assert rec["fallback_attempted"] is False
    assert rec["reason"].startswith(ar.REASON_APPLIED)
    assert rec["risk_class"] == RISK_LOW
    assert rec["risk_source"] == so.TASK_RISK_SOURCE
    # 复用现有 selector：considered/eligible/selected 与 A2 决策一致
    assert "qwen3:4b@custom" in rec["eligible"]
    assert "deepseek-v4-flash@deepseek" in rec["eligible"]
    ar.validate_active_routing(rec)


def test_low_synthetic_qualified_free_routes():
    """合成 registry：唯一合格 free 候选 → 单选胜出（sole_eligible）。"""
    reg = _registry(
        _entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test")
    assert rec["routing_applied"] is True
    assert rec["selected"] == "m1@p1"
    assert rec["routed_model"] == "m1"
    assert rec["routed_provider"] == "p1"


# ---------------------------------------------------------------------------
# 2. LOW 但 free candidate 不合格 → 保持 configured model（Requirement 4/10）
# ---------------------------------------------------------------------------


def test_low_free_candidate_not_qualified_keeps_configured():
    """LOW + free 候选 qualification=unknown → 无合格候选 → 不路由。"""
    reg = _registry(
        _entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               qualification=mr.RuntimeQualification()),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test")
    assert rec["routing_applied"] is False
    assert rec["selected"] is None
    assert rec["reason"].startswith(ar.REASON_NO_ELIGIBLE)


def test_low_free_candidate_not_qualified_but_other_eligible_keeps_configured():
    """LOW + free 候选不合格、仅 deepseek(UNKNOWN cost) eligible →
    selector 选中 deepseek 但 cost 非 FREE → 保持 configured（不路由）。"""
    reg = _registry(
        _entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               qualification=mr.RuntimeQualification()),
        _entry(model="deepseek", provider="remote", capability_tier=mr.CAP_TIER_T2,
               cost_class=mo.COST_CLASS_UNKNOWN,
               locality=mr.LOCALITY_REMOTE),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test")
    assert rec["routing_applied"] is False
    assert rec["selected"] == "deepseek@remote"
    assert rec["reason"].startswith(ar.REASON_SELECTED_NOT_FREE)
    assert "UNKNOWN" in rec["reason"]


def test_low_selected_paid_candidate_never_routed():
    """selector 选中 PAID 候选（无 free eligible）→ 保持 configured。"""
    reg = _registry(
        _entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=PAID, locality=mr.LOCALITY_REMOTE),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test")
    assert rec["routing_applied"] is False
    assert rec["selected"] == "m1@p1"
    assert rec["reason"].startswith(ar.REASON_SELECTED_NOT_FREE)


# ---------------------------------------------------------------------------
# 3. missing Risk → 保持 configured model（Requirement 4/10）
# ---------------------------------------------------------------------------


def test_missing_risk_keeps_configured():
    rec = ar.decide_active_route(None, ROLE_EXECUTOR, "hermes",
                                 mr.baseline_registry())
    assert rec["routing_applied"] is False
    assert rec["risk_class"] is None
    assert rec["risk_source"] == ar.RISK_UNAVAILABLE
    assert rec["selected"] is None
    assert rec["routed_model"] is None
    assert rec["reason"].startswith(ar.REASON_RISK_UNAVAILABLE)


# ---------------------------------------------------------------------------
# 4. MEDIUM/HIGH/CRITICAL → 保持 configured model（Requirement 4/10）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk", [RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL])
def test_non_low_risk_keeps_configured(risk):
    """MEDIUM/HIGH/CRITICAL 即使 selector 有 eligible（deepseek）也不路由。"""
    rec = ar.decide_active_route(risk, ROLE_EXECUTOR, "hermes",
                                 mr.baseline_registry(), risk_source="TASK.Risk")
    assert rec["routing_applied"] is False
    assert rec["risk_class"] == risk
    assert rec["reason"].startswith(ar.REASON_RISK_NOT_LOW)
    assert rec["routed_model"] is None


# ---------------------------------------------------------------------------
# 5. role / agent gate（Requirement 2）
# ---------------------------------------------------------------------------


def test_non_executor_role_keeps_configured():
    rec = ar.decide_active_route(RISK_LOW, ROLE_REVIEWER, "hermes",
                                 mr.baseline_registry(), risk_source="TASK.Risk")
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(ar.REASON_ROLE_NOT_EXECUTOR)


def test_non_hermes_agent_keeps_configured():
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "codex",
                                 mr.baseline_registry(), risk_source="TASK.Risk")
    assert rec["routing_applied"] is False
    assert rec["reason"].startswith(ar.REASON_AGENT_NOT_HERMES)


def test_unknown_risk_class_fail_closed():
    with pytest.raises(ValueError, match="risk class"):
        ar.decide_active_route("EXTREME", ROLE_EXECUTOR, "hermes",
                               mr.baseline_registry(), risk_source="x")


def test_explicit_risk_requires_source():
    with pytest.raises(ValueError, match="risk_source"):
        ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes",
                               mr.baseline_registry())


# ---------------------------------------------------------------------------
# 6. active decision 与 shadow decision 可审计区分（Requirement 6/7/10）
# ---------------------------------------------------------------------------


def test_audit_fields_present():
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source=so.TASK_RISK_SOURCE,
        configured_model="deepseek-v4-flash", configured_provider="deepseek",
    )
    # Requirement 6 字段全齐：risk+provenance / considered / eligible / selected /
    # routing_applied / actual selected model+provider / reason / fallback_attempted
    assert rec["risk_class"] == RISK_LOW
    assert rec["risk_source"] == so.TASK_RISK_SOURCE
    assert isinstance(rec["candidates_considered"], list) and rec["candidates_considered"]
    assert isinstance(rec["eligible"], list) and rec["eligible"]
    assert rec["selected"] == "qwen3:4b@custom"
    assert rec["routing_applied"] is True
    assert rec["routed_model"] == "qwen3:4b"
    assert rec["routed_provider"] == "custom"
    assert rec["configured_model"] == "deepseek-v4-flash"
    assert rec["reason"]
    assert rec["fallback_attempted"] is False
    assert rec["decision_kind"] == ar.DECISION_KIND
    ar.validate_active_routing(rec)


def test_active_vs_shadow_clearly_distinguished(tmp_path):
    """同一 LOW 场景：shadow 记录 authoritative=false（hypothetical），
    active 记录 authoritative=true（真实决策）——两者可明确区分。"""
    # A2 shadow（假设性）：绝不改变执行
    shadow = so.build_shadow_observation(
        "hermes", tmp_path, observation=None,
        risk_class=RISK_LOW, risk_source=so.TASK_RISK_SOURCE,
        registry=mr.baseline_registry(),
    )
    assert shadow["authoritative"] is False
    assert shadow["execution_affected"] is False
    # A3 active（authoritative）：真实选择
    active = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source=so.TASK_RISK_SOURCE,
    )
    assert active["authoritative"] is True
    assert active["decision_kind"] == "active_routing"
    assert active["routing_applied"] is True
    # 同一 selector 决策被两者消费（不创建第二套路由判断）
    assert shadow["decision"]["selected"] == active["selected"] == "qwen3:4b@custom"


def test_validate_fail_closed_routing_applied_requires_model():
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="test",
    )
    rec["routed_model"] = None
    with pytest.raises(ValueError, match="routed_model"):
        ar.validate_active_routing(rec)


def test_validate_fail_closed_fallback_attempted_must_be_false():
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="test",
    )
    rec["fallback_attempted"] = True
    with pytest.raises(ValueError, match="fallback_attempted"):
        ar.validate_active_routing(rec)


def test_validate_fail_closed_authoritative_must_be_true():
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="test",
    )
    rec["authoritative"] = False
    with pytest.raises(ValueError, match="authoritative"):
        ar.validate_active_routing(rec)


# ---------------------------------------------------------------------------
# 7. env 覆盖 apply / restore（Requirement 3 的透传机制）
# ---------------------------------------------------------------------------


def test_apply_restore_env_roundtrip(monkeypatch):
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL):
        monkeypatch.delenv(var, raising=False)
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="test",
    )
    assert rec["routing_applied"] is True
    saved = ar.apply_routing_env(rec)
    assert os.environ[cg.ENV_MODEL] == "qwen3:4b"
    assert os.environ[cg.ENV_PROVIDER] == "custom"
    assert os.environ[cg.ENV_BASE_URL] == "http://127.0.0.1:11434/v1"
    ar.restore_routing_env(saved)
    assert cg.ENV_MODEL not in os.environ
    assert cg.ENV_PROVIDER not in os.environ
    assert cg.ENV_BASE_URL not in os.environ


def test_apply_restore_preserves_preexisting_values(monkeypatch):
    monkeypatch.setenv(cg.ENV_MODEL, "old-model")
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="test",
    )
    saved = ar.apply_routing_env(rec)
    assert os.environ[cg.ENV_MODEL] == "qwen3:4b"
    ar.restore_routing_env(saved)
    assert os.environ[cg.ENV_MODEL] == "old-model"


def test_apply_env_requires_applied_record():
    rec = ar.decide_active_route(None, ROLE_EXECUTOR, "hermes",
                                 mr.baseline_registry())
    assert rec["routing_applied"] is False
    with pytest.raises(ValueError, match="routing_applied"):
        ar.apply_routing_env(rec)


def test_routed_env_reaches_invocation_args(monkeypatch, tmp_path):
    """A3 env 覆盖 → adapters.run_agent 透传 -m qwen3:4b --provider custom
    （guard 解析的 effective model == 实际 invocation model 的 argv 端证明）。"""
    import subprocess as subprocess_mod

    captured: dict = {}

    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env, **kwargs):
        captured["args"] = args
        captured["env_model"] = env.get(cg.ENV_MODEL)
        captured["env_provider"] = env.get(cg.ENV_PROVIDER)

        class FakeProc:
            returncode = 0
            stdout = "implemented ok"
            stderr = ""

        return FakeProc()

    monkeypatch.setattr(subprocess_mod, "run", fake_run)
    from ai_agent_framework.adapters import run_agent

    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", mr.baseline_registry(),
        risk_source="test",
    )
    saved = ar.apply_routing_env(rec)
    try:
        run_agent("hermes", "TASK", tmp_path)
    finally:
        ar.restore_routing_env(saved)
    args = captured["args"]
    assert "-m" in args
    assert args[args.index("-m") + 1] == "qwen3:4b"
    assert "--provider" in args
    assert args[args.index("--provider") + 1] == "custom"
    # 子进程 env 也携带覆盖（fresh-runner N+1 的 marker 证据同源）
    assert captured["env_model"] == "qwen3:4b"
    assert captured["env_provider"] == "custom"


# ---------------------------------------------------------------------------
# 8. Paid Guard invariant（Requirement 8/10）：routed LOCAL_FREE 经既有
#    classify_cost loopback 判定放行，无需授权；非免费路径仍走 A0。
# ---------------------------------------------------------------------------


def test_guard_recognizes_routed_local_free_without_auth(monkeypatch):
    """真实 resolve_effective_hermes + 真实 classify_cost：
    设置 A3 产生的三个 env 覆盖 → LOCAL_FREE → ALLOWED_FREE（零授权）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setenv(cg.ENV_MODEL, "qwen3:4b")
    monkeypatch.setenv(cg.ENV_PROVIDER, "custom")
    monkeypatch.setenv(cg.ENV_BASE_URL, "http://127.0.0.1:11434/v1")
    monkeypatch.delenv(cg.ENV_AUTH, raising=False)
    record = cg.evaluate("T-A3-1", "hermes", state_dir="C:\\__a3_nonexistent__")
    # 不依赖 state_dir（ALLOWED_FREE 不消费授权）——但 evaluate 对 LOCAL_FREE
    # 根本不进入 claim 路径，state_dir 不影响结果。
    assert record["decision"] == cg.DECISION_ALLOWED_FREE
    assert record["cost_class"] == cg.COST_LOCAL_FREE
    assert record["model"] == "qwen3:4b"
    assert record["provider"] == "custom"
    assert record["authorization_present"] is False


def test_guard_rejects_fake_local_like_url(monkeypatch):
    """AAF_HERMES_BASE_URL 不是 FREE 后门：非 loopback 端点依旧 PAID_OR_UNKNOWN。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setenv(cg.ENV_MODEL, "qwen3:4b")
    monkeypatch.setenv(cg.ENV_PROVIDER, "custom")
    monkeypatch.setenv(cg.ENV_BASE_URL, "https://localhost.evil.example/v1")
    monkeypatch.delenv(cg.ENV_AUTH, raising=False)
    record = cg.evaluate("T-A3-2", "hermes", state_dir=None)
    assert record["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert record["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL


# ---------------------------------------------------------------------------
# 9. runner 集成（Requirement 10：真实执行路径）
# ---------------------------------------------------------------------------

_TASK_TMPL = """AAF_TASK_BEGIN
# Task ID
A3-{case}

# Task Name
active routing runner integration

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
    body = _TASK_TMPL.format(case="RUN", objective="验证 A3 active routing。")
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


def test_runner_low_routes_env_and_writes_artifacts(tmp_path, monkeypatch):
    """LOW task 全链：routing applied → env 覆盖在 invocation 时可见 →
    active_routing.json 落盘（authoritative=true）→ env 已还原 →
    shadow artifact 仍为 hypothetical（authoritative=false）。"""
    seen_env = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen_env["model"] = os.environ.get(cg.ENV_MODEL)
            seen_env["provider"] = os.environ.get(cg.ENV_PROVIDER)
            seen_env["base_url"] = os.environ.get(cg.ENV_BASE_URL)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    # invocation 时 env 覆盖可见（adapters.run_agent 将透传 -m/--provider）
    assert seen_env["model"] == "qwen3:4b"
    assert seen_env["provider"] == "custom"
    assert seen_env["base_url"] == "http://127.0.0.1:11434/v1"
    # 执行完成后 env 已还原（不泄漏到后续 stage/调用方）
    assert cg.ENV_MODEL not in os.environ
    # active_routing.json：authoritative 决策
    active = ar.load_active_routing(out)
    assert active is not None
    assert active["routing_applied"] is True
    assert active["authoritative"] is True
    assert active["selected"] == "qwen3:4b@custom"
    assert active["fallback_attempted"] is False
    # shadow artifact：hypothetical 语义保持
    shadow = so.load_shadow_observation(out)
    assert shadow is not None
    assert shadow["authoritative"] is False
    assert shadow["execution_affected"] is False
    assert shadow["risk_class"] == RISK_LOW
    assert shadow["actual_vs_shadow"] == so.MATCH_SAME  # 路由后 actual == selected
    # stage result 引用并存
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage.get("active_routing_ref", {}).get("entry") == "hermes"
    assert stage.get("shadow_observation_ref", {}).get("entry") == "hermes"
    # guard 记录存在。注：单元测试环境里 conftest 把 guard 的 effective-model
    # resolution 固定为 hermetic dict（qwen3:4b/ollama）；「routed env 覆盖 →
    # guard 真实解析 → LOCAL_FREE → ALLOWED_FREE」的端到端证明由
    # test_guard_recognizes_routed_local_free_without_auth（真实 resolve）与
    # fresh-runner N+1（真实进程）覆盖——A3 不变量 = guard 解析的 effective
    # model == 实际 invocation model（env 覆盖在 guard 求值前已生效）。
    guard = json.loads((out / cg.ARTIFACT_FILENAME).read_text(encoding="utf-8"))
    assert guard["model"] == "qwen3:4b"
    # 全链 SUCCESS
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_low_invocation_failure_no_fallback(tmp_path, monkeypatch):
    """routing 后 local invocation 失败 → 如实 FRAMEWORK_ERROR、零 fallback
    （run_agent 只被调用一次；不切回 deepseek/其他模型；证据保留）。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == "hermes":
            raise RuntimeError("local qwen3 invocation failed (simulated)")
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert calls.count("hermes") == 1  # 绝不重试/切换模型
    result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result.startswith("FRAMEWORK_ERROR")
    assert "RuntimeError" in result
    active = ar.load_active_routing(out)
    assert active["routing_applied"] is True
    assert active["fallback_attempted"] is False
    # 链中断 → WAITING（不伪装 SUCCESS）
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    # env 已还原
    assert cg.ENV_MODEL not in os.environ


def test_runner_missing_risk_no_routing(tmp_path, monkeypatch):
    out = _run_runner(tmp_path, monkeypatch, _task(None))
    active = ar.load_active_routing(out)
    assert active is not None
    assert active["routing_applied"] is False
    assert active["reason"].startswith(ar.REASON_RISK_UNAVAILABLE)
    assert active["authoritative"] is True  # 决策本身仍是权威记录
    # 未路由 → env 从未被触碰
    assert cg.ENV_MODEL not in os.environ
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


@pytest.mark.parametrize("risk", [RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL])
def test_runner_non_low_risk_no_routing(tmp_path, monkeypatch, risk):
    out = _run_runner(tmp_path, monkeypatch, _task(risk))
    active = ar.load_active_routing(out)
    assert active is not None
    assert active["routing_applied"] is False
    assert active["reason"].startswith(ar.REASON_RISK_NOT_LOW)
    assert cg.ENV_MODEL not in os.environ
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"


def test_runner_routing_works_with_model_observation_disabled(tmp_path, monkeypatch):
    """AAF_MODEL_OBSERVATION=0 时 telemetry 关闭但 active routing（执行权威）仍生效。"""
    monkeypatch.setenv(mo.ENV_TOGGLE, "0")
    seen_env = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen_env["model"] = os.environ.get(cg.ENV_MODEL)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    assert seen_env["model"] == "qwen3:4b"
    active = ar.load_active_routing(out)
    assert active["routing_applied"] is True
    # telemetry 关闭 → 无 shadow artifact（既有语义保持）
    assert so.load_shadow_observation(out) is None
    assert cg.ENV_MODEL not in os.environ


# ---------------------------------------------------------------------------
# 10. FIX-001: active-routing cost gate 严格 FREE/LOCAL_FREE（FREE_PROMO 排除）
#     （TASK: AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001）
# ---------------------------------------------------------------------------

FREE_PROMO = mo.COST_CLASS_FREE_PROMO


def test_low_qualified_local_free_routes_explicit():
    """Requirement 4：LOW + QUALIFIED + LOCAL_FREE → 可 active route（显式回归）。"""
    reg = _registry(
        _entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=LOCAL_FREE, locality=mr.LOCALITY_LOCAL),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test",
                                 configured_model="deepseek-v4-flash",
                                 configured_provider="deepseek")
    assert rec["routing_applied"] is True
    assert rec["selected"] == "m1@p1"
    assert rec["routed_model"] == "m1"
    assert rec["routed_provider"] == "p1"
    assert rec["fallback_attempted"] is False
    assert rec["reason"].startswith(ar.REASON_APPLIED)


def test_low_qualified_free_routes_explicit():
    """Requirement 4：LOW + QUALIFIED + FREE（非本地免费层）→ 可 active route。"""
    reg = _registry(
        _entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=FREE, locality=mr.LOCALITY_REMOTE),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test",
                                 configured_model="deepseek-v4-flash",
                                 configured_provider="deepseek")
    assert rec["routing_applied"] is True
    assert rec["selected"] == "m1@p1"
    assert rec["routed_model"] == "m1"
    assert rec["routed_provider"] == "p1"
    assert rec["fallback_attempted"] is False


def test_low_qualified_free_promo_not_routed():
    """Requirement 4：LOW + QUALIFIED + FREE_PROMO → 不 active route。

    selector（A2 引擎，消费 A1 FREE_OF_COST_CLASSES）仍把 FREE_PROMO 视为
    eligible 并选中（0 现金的 A1 通用语义不变）；A3 authority 的 cost gate
    严格 FREE/LOCAL_FREE → 拒绝。configured model/provider 保留，零 fallback。
    """
    reg = _registry(
        _entry(model="promo1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=FREE_PROMO, locality=mr.LOCALITY_REMOTE),
    )
    rec = ar.decide_active_route(
        RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
        risk_source="test",
        configured_model="deepseek-v4-flash", configured_provider="deepseek",
    )
    assert rec["routing_applied"] is False
    assert rec["selected"] == "promo1@p1"  # selector 语义未变（A1 未动）
    assert rec["routed_model"] is None
    assert rec["routed_provider"] is None
    assert rec["routed_base_url"] is None
    assert rec["configured_model"] == "deepseek-v4-flash"
    assert rec["configured_provider"] == "deepseek"
    assert rec["reason"].startswith(ar.REASON_SELECTED_NOT_FREE)
    assert "FREE_PROMO" in rec["reason"]
    assert rec["fallback_attempted"] is False
    ar.validate_active_routing(rec)


def test_free_promo_selected_but_gate_blocks_in_mixed_pool():
    """FREE_PROMO 与 LOCAL_FREE 同池且确定性 tie-break 选中 FREE_PROMO →
    仍不路由（gate 作用于 selected，FREE_PROMO 无法进入 active routing）。"""
    reg = _registry(
        _entry(model="z9-local", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=LOCAL_FREE, locality=mr.LOCALITY_LOCAL),
        _entry(model="promo1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=FREE_PROMO, locality=mr.LOCALITY_LOCAL),
    )
    rec = ar.decide_active_route(RISK_LOW, ROLE_EXECUTOR, "hermes", reg,
                                 risk_source="test",
                                 configured_model="deepseek-v4-flash",
                                 configured_provider="deepseek")
    assert rec["selected"] == "promo1@p1"  # 并列 rank 0 → key tie-break 选中 promo
    assert rec["routing_applied"] is False
    assert rec["routed_model"] is None
    assert rec["configured_model"] == "deepseek-v4-flash"
    assert rec["configured_provider"] == "deepseek"
    assert rec["fallback_attempted"] is False


def test_fix001_gate_is_strict_subset_of_global_free_classes():
    """Requirement 3：A1 全局 FREE_OF_COST_CLASSES 语义不变（仍含 FREE_PROMO）；
    A3 authority 的 cost gate 是严格子集 {FREE, LOCAL_FREE}。"""
    assert mr.FREE_OF_COST_CLASSES == frozenset({FREE, LOCAL_FREE, FREE_PROMO})
    assert ar.ACTIVE_ROUTING_COST_CLASSES == frozenset({FREE, LOCAL_FREE})
    assert ar.ACTIVE_ROUTING_COST_CLASSES < mr.FREE_OF_COST_CLASSES
    assert FREE_PROMO not in ar.ACTIVE_ROUTING_COST_CLASSES


def test_runner_free_promo_registry_keeps_configured(tmp_path, monkeypatch):
    """FIX-001 全链：FREE_PROMO 唯一合格候选（registry 注入）→ routing_applied=false、
    env 零触碰、configured model 保留、全链 SUCCESS。"""
    promo_registry = _registry(
        _entry(model="promo1", provider="p1", capability_tier=mr.CAP_TIER_T4,
               cost_class=FREE_PROMO, locality=mr.LOCALITY_REMOTE),
    )
    monkeypatch.setattr(mr, "baseline_registry", lambda: promo_registry)
    seen_env = {}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen_env["model"] = os.environ.get(cg.ENV_MODEL)
            seen_env["provider"] = os.environ.get(cg.ENV_PROVIDER)
            seen_env["base_url"] = os.environ.get(cg.ENV_BASE_URL)
        return _structured_ok(agent)

    out = _run_runner(tmp_path, monkeypatch, _task(RISK_LOW), fake_run_agent)
    active = ar.load_active_routing(out)
    assert active is not None
    assert active["routing_applied"] is False
    assert active["selected"] == "promo1@p1"
    assert active["routed_model"] is None
    assert active["reason"].startswith(ar.REASON_SELECTED_NOT_FREE)
    assert "FREE_PROMO" in active["reason"]
    assert active["fallback_attempted"] is False
    # invocation 时零 env 覆盖（routing 未应用 → env 从未被触碰）
    assert seen_env["model"] is None
    assert seen_env["provider"] is None
    assert seen_env["base_url"] is None
    assert cg.ENV_MODEL not in os.environ
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
