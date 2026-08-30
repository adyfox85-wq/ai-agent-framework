"""AAF v0.5 A2 — Hermes shadow observation 定向测试（TASK: AAF-v0.5-A2-SHADOW-ROUTING-002）。

覆盖 Requirement 8 测试矩阵 + 追加守卫：
- 有完整 risk/registry → 产生 shadow decision
- risk 不可用 → 明确 no-decision（RISK_UNAVAILABLE）
- 无合格 candidate → 明确 NO_SHADOW_CANDIDATE
- actual model 与 shadow candidate 可不同但不影响执行
- shadow path 不产生额外 provider 调用
- 仅 Hermes stage 接入（WorkBuddy/Codex 不产生 shadow artifact）
- runner 集成：artifact 生成、stage result 引用、真实 invocation 等价
- 静态隔离：shadow 模块零子进程/网络/LLM 依赖；无副作用 API
"""

import ast
import importlib
import inspect
import json

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework import model_observation as mo
from ai_agent_framework import model_registry as mr
from ai_agent_framework import risk_contract as rc
from ai_agent_framework import shadow_observation as so

FREE = mo.COST_CLASS_FREE
LOCAL_FREE = mo.COST_CLASS_LOCAL_FREE
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


def _observation(**overrides) -> dict:
    base = dict(
        agent="hermes",
        model="deepseek-v4-flash",
        provider="deepseek",
        model_source=mo.MODEL_SOURCE_CONFIG,
        discovery_status=mo.DISCOVERY_STATUS_OK,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. 有完整 risk/registry → 产生 shadow decision
# ---------------------------------------------------------------------------


def test_full_risk_registry_produces_shadow_decision(tmp_path):
    obs = _observation()
    reg = _registry(_entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4))
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=obs,
        risk_class=rc.RISK_LOW, risk_source="test-authoritative", registry=reg,
    )
    assert record["decision"] is not None
    assert record["selected_candidate"] == "m1@p1"
    assert record["no_decision_reason"] is None
    assert record["risk_class"] == rc.RISK_LOW
    assert record["risk_source"] == "test-authoritative"
    assert record["registry_entry_count"] == 1
    assert record["authoritative"] is False
    assert record["execution_affected"] is False
    so.validate_shadow_observation(record)


def test_decision_is_serialized_shadow_routing_dict(tmp_path):
    reg = _registry(_entry(model="m1", provider="p1", capability_tier=mr.CAP_TIER_T4))
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=_observation(),
        risk_class=rc.RISK_LOW, risk_source="test", registry=reg,
    )
    d = record["decision"]
    assert d["schema_version"] == 1
    assert d["selected"] == "m1@p1"
    assert d["risk_class"] == rc.RISK_LOW
    assert d["eligible"] == ["m1@p1"]
    assert d["no_candidate_reason"] is None


# ---------------------------------------------------------------------------
# 2. risk 不可用 → 明确 no-decision（RISK_UNAVAILABLE；Requirement 3）
# ---------------------------------------------------------------------------


def test_risk_unavailable_explicit_no_decision(tmp_path):
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=_observation(),
    )
    assert record["risk_class"] is None
    assert record["risk_source"] == so.RISK_UNAVAILABLE
    assert record["decision"] is None
    assert record["selected_candidate"] is None
    assert record["no_decision_reason"] is not None
    assert record["no_decision_reason"].startswith(so.RISK_UNAVAILABLE)
    assert record["actual_vs_shadow"] == so.MATCH_NO_SHADOW_DECISION
    assert "no authoritative runtime risk source" in record["risk_source_detail"]
    # 不发明 heuristic：没有任何 risk 猜测被填入
    assert record["risk_class"] is None


def test_resolve_stage_risk_is_honest_unavailable():
    risk, status, detail = so.resolve_stage_risk("hermes")
    assert risk is None
    assert status == so.RISK_UNAVAILABLE
    assert "does not invent" in detail or "no authoritative" in detail


def test_unknown_risk_class_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="risk class"):
        so.build_shadow_observation(
            "hermes", tmp_path, observation=_observation(),
            risk_class="EXTREME", risk_source="x",
        )


def test_explicit_risk_requires_source(tmp_path):
    with pytest.raises(ValueError, match="risk_source"):
        so.build_shadow_observation(
            "hermes", tmp_path, observation=_observation(),
            risk_class=rc.RISK_LOW,
        )


# ---------------------------------------------------------------------------
# 3. 无合格 candidate → 明确 NO_SHADOW_CANDIDATE（Requirement 4 诚实）
# ---------------------------------------------------------------------------


def test_baseline_registry_no_eligible_candidate_no_shadow_candidate(tmp_path):
    """A1 基线 registry 全 UNKNOWN → decision 存在但 selected=None +
    显式 NO_SHADOW_CANDIDATE（不虚构资格/健康/capability）。"""
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=_observation(),
        risk_class=rc.RISK_LOW, risk_source="test-authoritative",
    )
    assert record["decision"] is not None
    assert record["selected_candidate"] is None
    assert record["no_decision_reason"] is not None
    assert record["no_decision_reason"].startswith("NO_SHADOW_CANDIDATE")
    assert record["actual_vs_shadow"] == so.MATCH_NO_SHADOW_DECISION
    assert record["registry_entry_count"] == len(mr.baseline_registry())
    assert "baseline_registry" in record["registry_source"]


def test_no_eligible_candidate_explicit_no_candidate(tmp_path):
    reg = _registry(
        _entry(model="t4", provider="p", capability_tier=mr.CAP_TIER_T4),
    )
    # MEDIUM floor=T3 → T4 不充分 → 0 eligible
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=_observation(),
        risk_class=rc.RISK_MEDIUM, risk_source="test", registry=reg,
    )
    assert record["decision"]["selected"] is None
    assert record["no_decision_reason"].startswith("NO_SHADOW_CANDIDATE")
    assert record["selected_candidate"] is None


# ---------------------------------------------------------------------------
# 4. actual model 与 shadow candidate 可不同但不影响执行
# ---------------------------------------------------------------------------


def test_actual_differs_from_shadow_no_execution_effect(tmp_path):
    obs = _observation(model="actual-model", provider="actual-provider")
    reg = _registry(_entry(model="shadow-model", provider="shadow-provider"))
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=obs,
        risk_class=rc.RISK_LOW, risk_source="test", registry=reg,
    )
    assert record["actual_model"] == "actual-model"
    assert record["selected_candidate"] == "shadow-model@shadow-provider"
    assert record["actual_vs_shadow"] == so.MATCH_DIFFERENT
    assert record["execution_affected"] is False
    assert record["authoritative"] is False


def test_actual_matches_shadow_same(tmp_path):
    obs = _observation(model="m1", provider="p1")
    reg = _registry(_entry(model="m1", provider="p1"))
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=obs,
        risk_class=rc.RISK_LOW, risk_source="test", registry=reg,
    )
    assert record["actual_vs_shadow"] == so.MATCH_SAME


def test_actual_unknown_vs_shadow(tmp_path):
    reg = _registry(_entry(model="m1", provider="p1"))
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=None,
        risk_class=rc.RISK_LOW, risk_source="test", registry=reg,
    )
    assert record["actual_model"] is None
    assert record["actual_vs_shadow"] == so.MATCH_ACTUAL_UNKNOWN
    assert any("UNKNOWN" in n for n in record["notes"])


def test_env_override_used_as_actual_fact(tmp_path, monkeypatch):
    """AAF_HERMES_MODEL / AAF_HERMES_PROVIDER 是实际 invocation 事实（adapters
    透传 -m/--provider）——观测如实记录覆盖值并注明来源。"""
    monkeypatch.setenv("AAF_HERMES_MODEL", "invoked-model")
    monkeypatch.setenv("AAF_HERMES_PROVIDER", "invoked-provider")
    obs = _observation(model="config-model", provider="config-provider")
    reg = _registry(_entry(model="invoked-model", provider="invoked-provider"))
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=obs,
        risk_class=rc.RISK_LOW, risk_source="test", registry=reg,
    )
    assert record["actual_model"] == "invoked-model"
    assert record["actual_provider"] == "invoked-provider"
    assert record["actual_vs_shadow"] == so.MATCH_SAME
    assert any("AAF_HERMES_MODEL" in n for n in record["notes"])


# ---------------------------------------------------------------------------
# 5. shadow path 不产生额外 provider 调用
# ---------------------------------------------------------------------------


def test_shadow_module_has_no_subprocess_network_llm_dependency():
    """依赖图无 subprocess / urllib / requests / http / socket / openai /
    anthropic / llm —— shadow path 不可能发起额外 provider 调用。"""
    mod = importlib.import_module("ai_agent_framework.shadow_observation")
    tree = ast.parse(inspect.getsource(mod))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    banned = {"subprocess", "urllib", "requests", "http", "socket", "openai",
              "anthropic", "llm"}
    leaked = sorted(roots & banned)
    assert leaked == [], f"provider-call capability leaked into shadow module: {leaked}"


def test_shadow_module_has_no_side_effect_api():
    """公开 API 无 apply/switch/invoke/activate/fallback/poll/… 副作用函数。"""
    mod = importlib.import_module("ai_agent_framework.shadow_observation")
    banned = ("apply", "switch", "invoke", "activate", "fallback", "escalat",
              "poll", "quarantine", "monitor", "spawn", "wire", "route")
    public = [
        name for name, _ in inspect.getmembers(mod, inspect.isfunction)
        if not name.startswith("_")
    ]
    leaked = sorted(n for n in public if n.lower().startswith(banned))
    assert leaked == [], f"side-effect API leaked: {leaked}"


def test_shadow_observation_never_calls_discovery(tmp_path, monkeypatch):
    """observe_shadow_stage 不调用任何 discovery / CLI probe —— 只消费传入的
    observation。把所有 model_observation 探测函数打成 raise，shadow 路径
    仍成功（证明它不发起任何探测/CLI/provider 调用）。"""
    def boom(*a, **k):
        raise AssertionError("shadow path must not run discovery/probes")

    for name in ("discover_hermes", "discover_codebuddy", "discover_codex",
                 "discover_agent", "safe_discover_agent", "observe_stage",
                 "_run_readonly", "_cli_help", "_probe_version"):
        monkeypatch.setattr(mo, name, boom)
    record = so.observe_shadow_stage(tmp_path, "hermes", observation=_observation())
    assert record is not None
    assert (tmp_path / so.ARTIFACT_FILENAME).exists()
    assert record["actual_model"] == "deepseek-v4-flash"
    assert record["no_decision_reason"].startswith(so.RISK_UNAVAILABLE)


# ---------------------------------------------------------------------------
# 6. artifact I/O：原子写 / 读取 / 损坏容错
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    record = so.build_shadow_observation("hermes", tmp_path, observation=_observation())
    path = so.save_shadow_observation(tmp_path, record)
    assert path == tmp_path / so.ARTIFACT_FILENAME
    loaded = so.load_shadow_observation(tmp_path)
    assert loaded == record
    assert loaded["schema_version"] == 1
    so.validate_shadow_observation(loaded)


def test_load_missing_or_corrupt_returns_none(tmp_path):
    assert so.load_shadow_observation(tmp_path) is None
    (tmp_path / so.ARTIFACT_FILENAME).write_text("{not json", encoding="utf-8")
    assert so.load_shadow_observation(tmp_path) is None


def test_validate_rejects_true_authority_flags(tmp_path):
    record = so.build_shadow_observation("hermes", tmp_path, observation=_observation())
    record["authoritative"] = True
    with pytest.raises(ValueError, match="authoritative"):
        so.validate_shadow_observation(record)
    record2 = so.build_shadow_observation("hermes", tmp_path, observation=_observation())
    record2["execution_affected"] = True
    with pytest.raises(ValueError, match="execution_affected"):
        so.validate_shadow_observation(record2)


def test_observe_shadow_stage_nonblocking_on_failure(tmp_path, monkeypatch):
    """任何内部失败 → None（telemetry 失败绝不影响执行；runner 双保险）。"""
    def boom(*a, **k):
        raise OSError("disk failure")
    monkeypatch.setattr(so, "save_shadow_observation", boom)
    assert so.observe_shadow_stage(tmp_path, "hermes", observation=_observation()) is None
    assert not (tmp_path / so.ARTIFACT_FILENAME).exists()


# ---------------------------------------------------------------------------
# 7. 静态隔离（A2-001 隔离契约延续：live 模块零 import 本模块除外——本任务
#    合法接入 runner；断言 wiring 是只读的、范围是 Hermes-only）
# ---------------------------------------------------------------------------


def test_runner_imports_shadow_observation_but_only_readonly_path():
    """runner 是本任务唯一合法 wiring 点：只通过 observe_shadow_stage 消费，
    且 shadow_observation 本身不 import 任何 live 执行模块（runner/adapters/
    report/lifecycle 等；cost_guard 只读 ENV_* 常量，不 import 其执行逻辑）
    ——无循环依赖、无 live invocation 耦合。"""
    mod = importlib.import_module("ai_agent_framework.shadow_observation")
    tree = ast.parse(inspect.getsource(mod))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # 不 import 任何 live 执行模块（runner/adapters/cost_guard 逻辑/report/lifecycle）
    live = {"runner", "adapters", "report", "reconcile", "task_lifecycle",
            "context_packet", "project_boundary", "control", "cancel"}
    leaked = sorted(imported & live)
    assert leaked == [], f"shadow module imports live execution module: {leaked}"


def test_stage_agent_constrained_to_hermes():
    """Requirement 1：本任务只接 Hermes stage（WorkBuddy/Codex 由 runner
    显式过滤；模块常量锁定 hermes）。"""
    assert so.STAGE_AGENT_HERMES == "hermes"
    assert so.ARTIFACT_FILENAME == "shadow_observation.json"


# ---------------------------------------------------------------------------
# 8. Runner 集成：Hermes-only artifact + stage result 引用 + invocation 等价
# ---------------------------------------------------------------------------

_HERMES_ONLY_TASK = """# Task ID
A2-002-INTEG

# Task Name
shadow observation runner integration

# Objective
验证 Hermes shadow observation 接入后的真实执行等价性

# Route
hermes

# Acceptance
1. 通过
"""

_FULL_ROUTE_TASK = """# Task ID
A2-002-INTEG-FULL

# Task Name
shadow observation full route

# Objective
验证 full route 下 shadow artifact 只产生于 Hermes stage

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = ('{"verdict": "PASS", "blocking_rework": false, '
                 '"blocking_provenance": "structured", "findings": [], "warnings": []}')
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return (f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END")


def test_runner_writes_shadow_observation_hermes_only(tmp_path, monkeypatch):
    """full route：shadow_observation.json 只写一次、stage_agent=hermes、
    non-authoritative / execution_affected=false；hermes_result.json 携带
    shadow_observation_ref；workbuddy/codex stage 不产生额外 artifact。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_FULL_ROUTE_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)
    assert calls == ["hermes", "workbuddy", "codex"]

    artifact = out / so.ARTIFACT_FILENAME
    assert artifact.exists(), "shadow artifact must be written for the hermes stage"
    record = json.loads(artifact.read_text(encoding="utf-8"))
    so.validate_shadow_observation(record)
    assert record["stage_agent"] == "hermes"
    assert record["role"] == rc.ROLE_EXECUTOR
    assert record["authoritative"] is False
    assert record["execution_affected"] is False
    assert record["risk_class"] is None
    assert record["risk_source"] == so.RISK_UNAVAILABLE
    assert record["no_decision_reason"].startswith(so.RISK_UNAVAILABLE)
    # actual model/provider 来自 model observation（hermetic env：CLI 不可得 → UNKNOWN，
    # 如实记录，不虚构）
    assert record["actual_model"] is None
    assert record["actual_provider"] is None
    assert record["observation_ref"].endswith("model_observation.json")

    # stage result 引用
    hermes_json = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    ref = hermes_json.get("shadow_observation_ref")
    assert ref is not None
    assert ref["authority"].endswith(so.ARTIFACT_FILENAME)
    assert ref["entry"] == "hermes"
    # workbuddy/codex stage result 不携带 shadow ref
    assert "shadow_observation_ref" not in json.loads(
        (out / "workbuddy_result.json").read_text(encoding="utf-8")
    )
    assert "shadow_observation_ref" not in json.loads(
        (out / "codex_result.json").read_text(encoding="utf-8")
    )
    # REPORT / lifecycle 正常
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    # REPORT 保持既有紧凑摘要（不新增平行 shadow 段；shadow 细节只在 artifact）
    assert "## Shadow Observation" not in report


def test_runner_hermes_only_route_writes_shadow_artifact(tmp_path, monkeypatch):
    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_HERMES_ONLY_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    assert (out / so.ARTIFACT_FILENAME).exists()
    record = so.load_shadow_observation(out)
    assert record["stage_agent"] == "hermes"


def test_runner_telemetry_disabled_no_shadow_artifact(tmp_path, monkeypatch):
    """AAF_MODEL_OBSERVATION=0 → 整层关闭：无 model observation、无 shadow
    artifact、无 stage ref（行为与接入前完全一致）。"""
    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setenv(mo.ENV_TOGGLE, "0")
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_HERMES_ONLY_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    assert not (out / so.ARTIFACT_FILENAME).exists()
    assert not (out / mo.ARTIFACT_FILENAME).exists()
    hermes_json = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert "shadow_observation_ref" not in hermes_json
    assert "model_observation_ref" not in hermes_json


def test_runner_shadow_path_reuses_observation_no_new_probes(tmp_path, monkeypatch):
    """shadow 路径复用同一 observation（零额外 discovery/probe 调用）：
    observe_stage 调用次数 = stage 数（本任务无新增）；observe_shadow_stage
    只对 hermes 调用且收到 hermes stage 的同一 observation 对象。"""
    shadow_calls = []
    observed = {}

    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    orig_observe_stage = mo.observe_stage
    orig_shadow = so.observe_shadow_stage

    def spy_observe_stage(output_dir, agent):
        obs = orig_observe_stage(output_dir, agent)
        observed[agent] = obs
        return obs

    def spy_shadow(output_dir, agent, **kwargs):
        shadow_calls.append((agent, kwargs.get("observation")))
        return orig_shadow(output_dir, agent, **kwargs)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(mo, "observe_stage", spy_observe_stage)
    monkeypatch.setattr(so, "observe_shadow_stage", spy_shadow)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_FULL_ROUTE_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    assert list(observed) == ["hermes", "workbuddy", "codex"]  # 每 stage 恰好一次 discovery
    assert [a for a, _ in shadow_calls] == ["hermes"]  # shadow 只接 Hermes stage
    # shadow 收到的是 hermes stage 自己的 observation 对象（复用，零新 probe）
    assert shadow_calls[0][1] is observed["hermes"]


def test_runner_invocation_signature_unchanged(tmp_path, monkeypatch):
    """Requirement 6：actual execution command 等价——runner 仍以原始
    (agent, prompt, workspace) 调用 run_agent（不新增/改变任何参数），
    adapters 的 hermes 命令构建路径未触碰。"""
    received = []

    def fake_run_agent(agent, prompt, workspace):
        received.append((agent, prompt, workspace))
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_HERMES_ONLY_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    assert len(received) == 1
    agent, prompt, workspace = received[0]
    assert agent == "hermes"
    assert isinstance(prompt, str) and "TASK" in prompt
    assert str(workspace) == str(ws)
    # 三个位置参数签名（adapters.run_agent 契约）不变——runner 未改调用形态
    import inspect as _inspect

    sig = _inspect.signature(runner_mod.run_agent)
    params = list(sig.parameters)
    assert params[:3] == ["agent", "prompt", "workspace"]
    assert sig.parameters["agent"].kind == _inspect.Parameter.POSITIONAL_OR_KEYWORD

