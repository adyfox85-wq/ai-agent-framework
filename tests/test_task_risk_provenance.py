"""AAF v0.5 A2 — Task-Risk provenance 定向测试（TASK: AAF-v0.5-A2-SHADOW-ROUTING-003）。

覆盖 Requirement 7 测试矩阵 + 边界守卫：
- LOW / MEDIUM / HIGH / CRITICAL 合法值（parse + validate + shadow consumption）
- 缺失 Risk 的旧 TASK 向后兼容（validate 通过；shadow = RISK_UNAVAILABLE）
- 非法 Risk 被严格拒绝（大小写 / 同义词 / 非词汇一律 fail-closed，不静默降级）
- immutable snapshot / provenance 保留 Risk（TASK.snapshot.md 冻结 + manifest hash）
- 有 risk 时 shadow observation 使用该值及正确 task/planner source
- 缺 risk 时仍为 RISK_UNAVAILABLE
- 不从正文 / Task Name / Route / 路径隐式推断
- actual execution 不受影响（run_agent 调用形态不变；shadow 零额外 provider 调用）
"""
import json

import pytest

from bridge.task_io import parse_task as bridge_parse_task
from bridge.task_io import validate_task_text as bridge_validate_task_text
from ai_agent_framework import model_observation as mo
from ai_agent_framework import model_registry as mr
from ai_agent_framework import risk_contract as rc
from ai_agent_framework import runner as runner_mod
from ai_agent_framework import shadow_observation as so
from ai_agent_framework import task_validation as tv

ALL_RISK_CLASSES = (rc.RISK_LOW, rc.RISK_MEDIUM, rc.RISK_HIGH, rc.RISK_CRITICAL)


def mr_baseline():
    return mr.baseline_registry()

# ---------------------------------------------------------------------------
# 夹具：合法 TASK（无 Risk；旧格式基线）+ 注入 Risk 的 helpers
# ---------------------------------------------------------------------------

_OLD_TASK = """AAF_TASK_BEGIN
# Task ID
A2-003-OLD

# Task Name
legacy task without risk field

# Workspace
D:\\AdyAI\\ai-agent-framework

# Objective
旧格式 TASK：没有结构化 Risk 字段，必须向后兼容。

# Route
hermes

# Acceptance
1. 通过

AAF_TASK_END
"""


def _with_risk(text: str, risk_value: str) -> str:
    """在旧 TASK 上注入 `Risk: <value>`（顶层单行字段，插在 Objective 节之前）。"""
    return text.replace("# Objective\n", f"Risk: {risk_value}\n\n# Objective\n", 1)


def _structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = ('{"verdict": "PASS", "blocking_rework": false, '
                 '"blocking_provenance": "structured", "findings": [], "warnings": []}')
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END"


# ---------------------------------------------------------------------------
# 1. LOW / MEDIUM / HIGH / CRITICAL 合法值
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk", ALL_RISK_CLASSES)
def test_valid_risk_parses_and_validates(risk):
    text = _with_risk(_OLD_TASK, risk)
    fields = tv.parse_task_fields(text)
    assert fields["Risk"] == risk
    result = tv.validate_task_text(text)
    assert result.valid is True, result.errors
    # bridge 早期 UX Guard 同样放行
    ok, errors = bridge_validate_task_text(text, "D:\\AdyAI\\ai-agent-framework")
    assert ok is True, errors
    assert bridge_parse_task(text)["risk"] == risk


@pytest.mark.parametrize("risk", ALL_RISK_CLASSES)
def test_valid_risk_feeds_shadow_decision(tmp_path, risk):
    """合法显式 risk → build_shadow_observation 使用该值并调用现有 selector。"""
    record = so.build_shadow_observation(
        "hermes", tmp_path, observation=None,
        risk_class=risk, risk_source=so.TASK_RISK_SOURCE,
        registry=mr_baseline(),
    )
    assert record["risk_class"] == risk
    assert record["risk_source"] == so.TASK_RISK_SOURCE
    # selector 被调用：decision 是结构化 ShadowDecision（基线 registry 自
    # A2-004 起 deepseek T2+QUALIFIED → LOW/MEDIUM/HIGH 有真实候选；CRITICAL
    # 下限 T1 无候选 → 显式 NO_SHADOW_CANDIDATE——但绝不等于「risk 未消费」）
    assert record["decision"] is not None
    assert record["decision"]["risk_class"] == risk
    assert record["authoritative"] is False
    assert record["execution_affected"] is False


# ---------------------------------------------------------------------------
# 2. 缺失 Risk 的旧 TASK 向后兼容
# ---------------------------------------------------------------------------


def test_missing_risk_backward_compatible_validation():
    result = tv.validate_task_text(_OLD_TASK)
    assert result.valid is True, result.errors
    assert tv.parse_task_fields(_OLD_TASK)["Risk"] == ""


def test_missing_risk_shadow_stays_risk_unavailable(tmp_path, monkeypatch):
    """旧 TASK（无 Risk）→ runner 集成：shadow risk_class=None +
    RISK_UNAVAILABLE no-decision（行为与 A2-002 完全一致）。"""

    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_OLD_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    record = so.load_shadow_observation(out)
    assert record is not None
    assert record["risk_class"] is None
    assert record["risk_source"] == so.RISK_UNAVAILABLE
    assert record["no_decision_reason"].startswith(so.RISK_UNAVAILABLE)
    assert record["decision"] is None


# ---------------------------------------------------------------------------
# 3. 非法 Risk 被严格拒绝（fail-closed，不静默降级）
# ---------------------------------------------------------------------------

_INVALID_RISKS = (
    "low",        # 大小写猜测被拒绝（非 LOW）
    "Low",        # 混合大小写被拒绝
    "EXTREME",    # 非词汇
    "HIGH risk",  # 同义词/附加文本被拒绝
    "5",          # 非词汇
    "MEDIUM ",    # 尾随空白 → strip 后合法（边界：允许）
)


@pytest.mark.parametrize("bad", [r for r in _INVALID_RISKS if r != "MEDIUM "])
def test_invalid_risk_strictly_rejected(bad):
    text = _with_risk(_OLD_TASK, bad)
    result = tv.validate_task_text(text)
    assert result.valid is False
    assert any("Risk" in e and "非法" in e for e in result.errors), result.errors
    # bridge 早期 UX Guard 同样严格拒绝
    ok, errors = bridge_validate_task_text(text, "D:\\AdyAI\\ai-agent-framework")
    assert ok is False
    assert any("Risk" in e and "非法" in e for e in errors)


def test_invalid_risk_rejected_before_execution(tmp_path, monkeypatch):
    """非法 Risk → runner 在 Validation 阶段 fail-closed（Hermes 零执行）。"""
    spawned = []

    def fake_run_agent(agent, prompt, workspace):
        spawned.append(agent)
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, "EXTREME"), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    with pytest.raises(tv.TaskValidationError):
        runner_mod.run(task_file, ws, out)
    assert spawned == []
    assert not (out / so.ARTIFACT_FILENAME).exists()


def test_trailing_whitespace_risk_is_normalized_valid():
    """`MEDIUM `（尾随空白）→ strip 后是合法词汇；空白不算非法值。"""
    text = _with_risk(_OLD_TASK, "MEDIUM ")
    result = tv.validate_task_text(text)
    assert result.valid is True, result.errors
    assert tv.parse_task_fields(text)["Risk"] == "MEDIUM"


def test_duplicate_top_level_risk_fail_closed():
    """顶层 preamble 内重复声明 Risk → 双层 fail-closed（不得 first/last wins）。"""
    text = _with_risk(_with_risk(_OLD_TASK, rc.RISK_HIGH), rc.RISK_LOW)
    result = tv.validate_task_text(text)
    assert result.valid is False
    assert any("重复声明" in e and "Risk" in e for e in result.errors), result.errors
    ok, errors = bridge_validate_task_text(text, "D:\\AdyAI\\ai-agent-framework")
    assert ok is False
    assert any("重复声明" in e and "Risk" in e for e in errors)


def test_prose_risk_line_after_objective_is_not_a_field(tmp_path, monkeypatch):
    """生产回归（本任务 snapshot 实证）：Requirements 正文里描述字段语法的
    `Risk: LOW|MEDIUM|HIGH|CRITICAL` 行是 **prose**，不是顶层字段声明——
    不得从正文推断 risk（Requirement 2/4）。校验通过 + shadow = RISK_UNAVAILABLE。"""
    text = """AAF_TASK_BEGIN
Task ID: A2-003-PROSE
Task Name: prose risk line regression
Workspace: D:\\AdyAI\\ai-agent-framework

Objective:
验证 Requirements 正文中的 Risk: 行不被当作顶层字段。

Requirements:
1. 先检查当前 TASK/intake contract 是否已有可复用的结构化 risk 字段。
   - 若没有，增加一个最小、可选的顶层字段：
     Risk: LOW|MEDIUM|HIGH|CRITICAL

Route: hermes

Acceptance:
1. 通过

AAF_TASK_END
"""
    fields = tv.parse_task_fields(text)
    assert fields["Risk"] == "", "prose 中的 Risk: 行不得被当作字段"
    result = tv.validate_task_text(text)
    assert result.valid is True, result.errors
    ok, errors = bridge_validate_task_text(text, "D:\\AdyAI\\ai-agent-framework")
    assert ok is True, errors

    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    record = so.load_shadow_observation(out)
    assert record["risk_class"] is None
    assert record["risk_source"] == so.RISK_UNAVAILABLE
    assert record["decision"] is None


# ---------------------------------------------------------------------------
# 4. immutable snapshot / provenance 保留 Risk
# ---------------------------------------------------------------------------


def test_snapshot_retains_risk_and_manifest_hashes_it(tmp_path, monkeypatch):
    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, rc.RISK_HIGH), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    snapshot = (out / "TASK.snapshot.md").read_text(encoding="utf-8")
    assert f"Risk: {rc.RISK_HIGH}" in snapshot, "immutable snapshot 必须保留 Risk 字段"
    # snapshot 是唯一 execution authority：从 snapshot 重新派生 risk 一致
    assert tv.parse_task_fields(snapshot)["Risk"] == rc.RISK_HIGH

    manifest = json.loads((out / "context_manifest.json").read_text(encoding="utf-8"))
    task_ref = manifest["task"]
    assert task_ref["path"].endswith("TASK.snapshot.md")
    assert isinstance(task_ref["hash"], str) and len(task_ref["hash"]) == 64
    # manifest hash 是对 snapshot 原文（含 Risk）的 SHA-256
    from ai_agent_framework.context_packet import sha256_file
    assert task_ref["hash"] == sha256_file(out / "TASK.snapshot.md")


# ---------------------------------------------------------------------------
# 5. 有 risk 时 shadow observation 使用该值及正确 source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk", ALL_RISK_CLASSES)
def test_runner_shadow_uses_task_risk_and_provenance(tmp_path, monkeypatch, risk):
    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, risk), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    record = so.load_shadow_observation(out)
    assert record is not None
    assert record["risk_class"] == risk
    assert record["risk_source"] == so.TASK_RISK_SOURCE
    assert "TASK.Risk field" in record["risk_source"]
    assert "TASK.snapshot.md" in record["risk_source"]
    assert record["decision"] is not None  # 选择器被调用（A2-004 起基线 registry：HIGH → deepseek 真实候选）
    assert record["authoritative"] is False
    assert record["execution_affected"] is False
    # stage result 引用 artifact（runtime metadata 链）
    hermes_json = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert hermes_json["shadow_observation_ref"]["entry"] == "hermes"


def test_runner_high_risk_shadow_selects_deepseek(tmp_path, monkeypatch):
    """A2-004 核心验收（runner 级）：HIGH TASK → 写出的 shadow artifact 中
    deepseek-v4-flash@deepseek 是 eligible 且被选中的真实 hypothetical
    candidate；actual execution 调用形态不变（run_agent 仍三位置参数、
    恰一次 hermes 调用）。"""
    received = []

    def fake_run_agent(agent, prompt, workspace):
        received.append((agent, prompt, workspace))
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, rc.RISK_HIGH), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    record = so.load_shadow_observation(out)
    assert record is not None
    assert record["risk_class"] == rc.RISK_HIGH
    assert record["selected_candidate"] == "deepseek-v4-flash@deepseek"
    assert record["decision"]["eligible"] == ["deepseek-v4-flash@deepseek"]
    assert record["decision"]["required_floor"] == "T2"
    assert record["authoritative"] is False
    assert record["execution_affected"] is False
    # actual execution authority 不变：恰一次 hermes 调用、三位置参数形态
    assert len(received) == 1
    assert received[0][0] == "hermes"


def test_runner_low_risk_shadow_selects_deepseek(tmp_path, monkeypatch):
    """TASK: AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001 核心验收
    （runner 级）：LOW TASK → 写出的 shadow artifact 中 qwen3:4b@custom
    **不再**是 eligible hypothetical candidate（aux-only evidence →
    AUXILIARY_ONLY 排除）；唯一 eligible/selected = deepseek-v4-flash@deepseek
    （scope=main）；actual execution 调用形态不变（run_agent 仍三位置参数、
    恰一次 hermes 调用）；authoritative=false / execution_affected=false 保持。"""
    received = []

    def fake_run_agent(agent, prompt, workspace):
        received.append((agent, prompt, workspace))
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, rc.RISK_LOW), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    record = so.load_shadow_observation(out)
    assert record is not None
    assert record["risk_class"] == rc.RISK_LOW
    assert record["selected_candidate"] == "deepseek-v4-flash@deepseek"
    assert record["decision"]["eligible"] == ["deepseek-v4-flash@deepseek"]
    assert record["decision"]["required_floor"] == "T4"
    assert record["decision"]["selection_reason"] == "sole_eligible_candidate"
    assert record["authoritative"] is False
    assert record["execution_affected"] is False
    # aux-only 候选的显式排除记录（可审计）
    aux_excl = [
        e for e in record["decision"]["excluded"]
        if e["candidate"] == "qwen3:4b@custom"
    ]
    assert aux_excl and aux_excl[0]["reason"] == "AUXILIARY_ONLY"
    # actual execution authority 不变：恰一次 hermes 调用、三位置参数形态
    assert len(received) == 1
    assert received[0][0] == "hermes"


# ---------------------------------------------------------------------------
# 6. 缺 risk 时仍为 RISK_UNAVAILABLE
# ---------------------------------------------------------------------------


def test_runner_no_risk_field_keeps_risk_unavailable(tmp_path, monkeypatch):
    """正文大量出现 risk 词汇但无结构化字段 → 仍 RISK_UNAVAILABLE（见 7）。"""
    text = _OLD_TASK.replace(
        "# Objective\n旧格式 TASK：没有结构化 Risk 字段，必须向后兼容。",
        "# Objective\n这是一个 high risk 任务，请评估 CRITICAL 场景的 MEDIUM 风险。",
    )
    assert "Risk:" not in text

    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    record = so.load_shadow_observation(out)
    assert record["risk_class"] is None
    assert record["risk_source"] == so.RISK_UNAVAILABLE
    assert record["decision"] is None


# ---------------------------------------------------------------------------
# 7. 不从正文 / Task Name / Route / 路径隐式推断
# ---------------------------------------------------------------------------


def test_no_inference_from_prose_name_route(tmp_path, monkeypatch):
    """风险词汇只出现在 prose / Task Name / Route 中 → parse 为空 → shadow
    RISK_UNAVAILABLE（结构化字段是唯一权威来源）。"""
    text = """# Task ID
A2-003-NOINFER

# Task Name
CRITICAL HIGH-risk MEDIUM operation

# Objective
LOW 风险级别的正文描述，含 HIGH / CRITICAL 字样；但没有结构化 Risk 字段。

# Route
hermes

# Acceptance
1. 通过

AAF_TASK_END
"""
    fields = tv.parse_task_fields(text)
    assert fields["Risk"] == ""
    assert tv.validate_task_text(text).valid is True

    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    record = so.load_shadow_observation(out)
    assert record["risk_class"] is None
    assert record["risk_source"] == so.RISK_UNAVAILABLE


# ---------------------------------------------------------------------------
# 8. actual execution 不受影响
# ---------------------------------------------------------------------------


def test_risk_wiring_does_not_change_invocation(tmp_path, monkeypatch):
    """带 Risk 的 TASK：run_agent 调用形态与 A2-002 完全一致
    （agent, prompt, workspace 三位置参数；prompt 内容不变）。"""
    received = []

    def fake_run_agent(agent, prompt, workspace):
        received.append((agent, prompt, workspace))
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, rc.RISK_HIGH), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    assert len(received) == 1
    agent, prompt, workspace = received[0]
    assert agent == "hermes"
    assert isinstance(prompt, str) and "TASK" in prompt
    assert str(workspace) == str(ws)
    import inspect as _inspect
    sig = _inspect.signature(runner_mod.run_agent)
    assert list(sig.parameters)[:3] == ["agent", "prompt", "workspace"]


def test_shadow_risk_path_zero_extra_provider_calls(tmp_path, monkeypatch):
    """风险透传只是 runner 内同步读取 + 参数传递：observe_stage 调用次数不变
    （每 stage 一次），shadow 收到 hermes 自己的 observation 对象（零新 probe）。"""
    shadow_calls = []
    observed = {}

    def fake_run_agent(agent, prompt, workspace):
        return _structured_ok(agent)

    orig_observe_stage = runner_mod.model_observation_mod.observe_stage
    orig_shadow = so.observe_shadow_stage

    def spy_observe_stage(output_dir, agent):
        obs = orig_observe_stage(output_dir, agent)
        observed[agent] = obs
        return obs

    def spy_shadow(output_dir, agent, **kwargs):
        shadow_calls.append((agent, kwargs))
        return orig_shadow(output_dir, agent, **kwargs)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(runner_mod.model_observation_mod, "observe_stage", spy_observe_stage)
    monkeypatch.setattr(so, "observe_shadow_stage", spy_shadow)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, rc.RISK_HIGH), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    assert list(observed) == ["hermes"]
    assert [a for a, _ in shadow_calls] == ["hermes"]
    agent, kwargs = shadow_calls[0]
    assert kwargs["observation"] is observed["hermes"]  # 复用同一 observation，零新 probe
    assert kwargs["risk_class"] == rc.RISK_HIGH
    assert kwargs["risk_source"] == so.TASK_RISK_SOURCE


# ---------------------------------------------------------------------------
# 9. 显式声明但值为空 / 纯空白 → fail-closed（FIX-001 唯一 blocker）
#    「已声明」≠「缺失」：只有字段完全缺失才允许向后兼容（RISK_UNAVAILABLE）。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty_value", ["", "   ", "\t"])
def test_declared_empty_risk_fail_closed(empty_value):
    """`Risk:` / `Risk:   `（纯空白）→ 声明一次但值为空 → framework + bridge
    双层严格拒绝；绝不降级为「字段缺失」（不得变成 RISK_UNAVAILABLE）。"""
    text = _with_risk(_OLD_TASK, empty_value)
    assert tv.parse_task_fields(text)["Risk"] == "", "空声明解析后必须为空值"
    result = tv.validate_task_text(text)
    assert result.valid is False
    assert any("Risk" in e and "为空" in e for e in result.errors), result.errors
    # bridge 早期 UX Guard 语义一致（同一 fail-closed 契约）
    ok, errors = bridge_validate_task_text(text, "D:\\AdyAI\\ai-agent-framework")
    assert ok is False
    assert any("Risk" in e and "为空" in e for e in errors)


def test_declared_empty_risk_heading_form_fail_closed():
    """标题式声明但无值（`# Risk` + 后无值行）→ 同样视为「已声明但为空」→ 拒绝
    （与同行式 `Risk:` 同一 fail-closed 契约；缺失才允许向后兼容）。"""
    text = _OLD_TASK.replace("# Objective\n", "# Risk\n\n# Objective\n", 1)
    assert tv.parse_task_fields(text)["Risk"] == ""
    result = tv.validate_task_text(text)
    assert result.valid is False
    assert any("Risk" in e and "为空" in e for e in result.errors), result.errors
    ok, errors = bridge_validate_task_text(text, "D:\\AdyAI\\ai-agent-framework")
    assert ok is False
    assert any("Risk" in e and "为空" in e for e in errors)


def test_declared_empty_risk_rejected_before_execution(tmp_path, monkeypatch):
    """空值 Risk → runner 在 Validation 阶段 fail-closed：Hermes 零执行、
    无 shadow artifact、无降级成 RISK_UNAVAILABLE 的机会（Req 4）。"""
    spawned = []

    def fake_run_agent(agent, prompt, workspace):
        spawned.append(agent)
        return _structured_ok(agent)

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_with_risk(_OLD_TASK, ""), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    with pytest.raises(tv.TaskValidationError):
        runner_mod.run(task_file, ws, out)
    assert spawned == []
    assert not (out / so.ARTIFACT_FILENAME).exists()


def test_missing_risk_still_backward_compatible_after_fix():
    """FIX-001 回归守卫：字段完全缺失 ≠ 空声明——缺失仍通过（向后兼容），
    与空声明拒绝形成显式对照（同一失败契约的两个方向）。"""
    result = tv.validate_task_text(_OLD_TASK)
    assert result.valid is True, result.errors
    assert tv.parse_task_fields(_OLD_TASK)["Risk"] == ""
    ok, errors = bridge_validate_task_text(_OLD_TASK, "D:\\AdyAI\\ai-agent-framework")
    assert ok is True, errors
