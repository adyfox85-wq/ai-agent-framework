"""AAF — Model Observability / Discovery Foundation 测试（AAF-v0.4-TASK-010）。

覆盖 TASK Requirements 19（A–I）+ 20（agent-specific，mock 真实 CLI 输出形态）
+ 动态元数据刷新 + schema 校验 + 单一 authority 语义。

原则：
- mock 只使用本机真实 CLI 观察到的输出形态（probe 证据），
  不发明 imaginary flags / outputs。
- 任何 discovery 失败 → 非阻塞（UNKNOWN / FAILED 记录，绝不抛出到 runner）。
- 不持久化任何 secret。
"""
import json
import os
from pathlib import Path

import pytest

from ai_agent_framework import model_observation as mo
from ai_agent_framework.context_packet import build_stage_result
from ai_agent_framework.report import build_report

# ---------------------------------------------------------------------------
# 真实 CLI 输出形态（2026-08-29 本机 probe 证据；仅作 mock 输入，非 AAF 硬编码）
# ---------------------------------------------------------------------------

HERMES_CONFIG_GET_MODEL = """\
default: deepseek-v4-flash
provider: deepseek
base_url: ''
reasoning_effort: medium
"""

# hermes config get auxiliary 真实形态（截取关键槽位；api_key 为空串）
HERMES_CONFIG_GET_AUXILIARY = """\
transient_retries: 2
free_only: false
vision:
  provider: custom
  model: qwen2.5vl:3b
  base_url: http://127.0.0.1:11434/v1
  api_key: ''
  timeout: 120
  reasoning_effort: ''
compression:
  provider: custom
  model: qwen3:4b
  base_url: http://127.0.0.1:11434/v1
  api_key: ''
  timeout: 120
  reasoning_effort: ''
web_extract:
  provider: custom
  model: qwen3:4b
  base_url: http://127.0.0.1:11434/v1
skills_hub:
  provider: auto
  model: ''
  base_url: ''
"""

CODEBUDDY_HELP_MODEL_LINE = (
    "--model <model>                                  Model for the current session. "
    "Please provide the model ID. Currently supported: (hy4-preview, hy4-preview-x, "
    "hy3, hy3-x, glm-5.3, glm-5.3-flash, glm-5.2, glm-5.1, glm-5v-turbo, "
    "minimax-m3, minimax-m2.7, kimi-k3-1, kimi-k2.7, kimi-k2.6, "
    "deepseek-v4-pro, deepseek-v4-flash)\n"
)
CODEBUDDY_HELP = CODEBUDDY_HELP_MODEL_LINE + (
    "  --effort <level>                                 Reasoning effort level "
    "(minimal, low, medium, high, xhigh, max)\n"
)

CODEX_EXEC_HELP = """\
Run Codex non-interactively

Usage: codex exec [OPTIONS] [PROMPT]

Options:
  -m, --model <MODEL>
          Model the agent should use
      --oss
          Use open-source provider
      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama).
  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy
"""


# ---------------------------------------------------------------------------
# mock helpers（只 mock discovery 层，不 mock runner 主链路）
# ---------------------------------------------------------------------------


def _fake_cli(monkeypatch, exe: str = "C:/fake/bin/cli.exe"):
    monkeypatch.setattr(mo, "_find_cli", lambda cmd: exe)
    # 每测试隔离 --help 缓存（避免不同 agent 共享同一 exe 路径的缓存污染）
    mo._HELP_CACHE.clear()


def _fake_run_readonly(monkeypatch, script: dict):
    """script: {tuple(args) -> (exit, stdout, stderr)}；未命中 → (1, '', 'not mocked')。"""
    calls = []

    def fake(args, timeout=20.0):
        calls.append(list(args))
        return script.get(tuple(args), (1, "", "not mocked"))

    monkeypatch.setattr(mo, "_run_readonly", fake)
    return calls


def _json_text(obs: dict) -> str:
    return json.dumps(obs, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# A. known model metadata → correctly serialized
# ---------------------------------------------------------------------------


def test_hermes_known_metadata_serialized(monkeypatch):
    _fake_cli(monkeypatch)
    calls = _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, HERMES_CONFIG_GET_MODEL, ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (0, HERMES_CONFIG_GET_AUXILIARY, ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, "usage: hermes [-h] [-m MODEL] [--provider PROVIDER] [--reasoning LEVEL]", ""),
    })
    obs = mo.discover_hermes()

    assert obs["model"] == "deepseek-v4-flash"
    assert obs["provider"] == "deepseek"
    assert obs["model_source"] == mo.MODEL_SOURCE_CONFIG
    assert obs["reasoning_effort"] == "medium"
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_OK
    # capabilities 来自 --help（版本级证据）
    assert obs["capabilities"]["explicit_model_selection"] is True
    assert obs["capabilities"]["reasoning_effort_option"] is True
    assert obs["capabilities"]["models_listable"] is False
    # JSON 往返可序列化
    assert json.loads(_json_text(obs))["model"] == "deepseek-v4-flash"
    # 只调用了只读命令形态
    assert ["C:/fake/bin/cli.exe", "config", "get", "model"] in calls
    assert all("set" not in a for a in calls)


def test_make_observation_roundtrip_schema():
    obs = mo.make_observation(
        "hermes", provider="deepseek", model="deepseek-v4-flash",
        model_source=mo.MODEL_SOURCE_CONFIG, reasoning_effort="medium",
    )
    for field in ("agent", "provider", "model", "model_source", "reasoning_effort",
                  "cost_class", "cost_metadata", "cost_multiplier", "discovered_at",
                  "discovery_status", "capabilities", "notes"):
        assert field in obs
    assert obs["cost_class"] == mo.COST_CLASS_UNKNOWN
    assert obs["cost_multiplier"] is None


def test_make_observation_rejects_invalid_schema():
    with pytest.raises(ValueError):
        mo.make_observation("hermes", model_source="made_up_source")
    with pytest.raises(ValueError):
        mo.make_observation("hermes", cost_class="FREE_FOREVER")


# ---------------------------------------------------------------------------
# B. unknown model → UNKNOWN, task execution continues
# ---------------------------------------------------------------------------


def test_codebuddy_empty_config_yields_unknown(monkeypatch):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, "", ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, CODEBUDDY_HELP, ""),
    })
    obs = mo.discover_codebuddy()
    assert obs["model"] is None
    assert obs["model_source"] == mo.MODEL_SOURCE_UNKNOWN
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_UNAVAILABLE
    # 不发明 model；notes 记录真实原因
    assert any("NOT exposed" in n for n in obs["notes"])


def test_unknown_agent_discovery_returns_empty(monkeypatch):
    obs = mo.safe_discover_agent("ghost-agent")
    assert obs["agent"] == "ghost-agent"
    assert obs["model"] is None
    assert obs["model_source"] == mo.MODEL_SOURCE_UNKNOWN


# ---------------------------------------------------------------------------
# C. discovery command unavailable / fails → non-blocking
# ---------------------------------------------------------------------------


def test_cli_missing_non_blocking(monkeypatch):
    monkeypatch.setattr(mo, "_find_cli", lambda cmd: None)  # conftest 默认
    obs = mo.safe_discover_agent("hermes")
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_UNAVAILABLE
    assert obs["model"] is None
    assert any("not found" in n for n in obs["notes"])


def test_discovery_invocation_failure_non_blocking(monkeypatch):
    _fake_cli(monkeypatch)
    monkeypatch.setattr(mo, "_run_readonly", lambda args, timeout=20.0: None)
    obs = mo.safe_discover_agent("hermes")
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_FAILED
    assert obs["model"] is None


def test_safe_discover_agent_absorbs_any_exception(monkeypatch):
    _fake_cli(monkeypatch)
    def boom(args, timeout=20.0):
        raise RuntimeError("boom")
    monkeypatch.setattr(mo, "_run_readonly", boom)
    obs = mo.safe_discover_agent("codex")
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_FAILED
    assert obs["model"] is None
    assert any("boom" in n for n in obs["notes"])


# ---------------------------------------------------------------------------
# D. dynamic free/cost metadata unavailable → UNKNOWN, not invented
# ---------------------------------------------------------------------------


def test_cost_unknown_not_invented_codebuddy(monkeypatch):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, "", ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, CODEBUDDY_HELP, ""),
    })
    obs = mo.discover_codebuddy()
    assert obs["cost_class"] == mo.COST_CLASS_UNKNOWN
    assert obs["cost_metadata"] is None
    assert obs["cost_multiplier"] is None
    assert any("EXTERNAL_DYNAMIC_METADATA_REQUIRED" in n for n in obs["notes"])


def test_cost_unknown_not_invented_codex(monkeypatch, tmp_path):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "exec", "--help"): (0, CODEX_EXEC_HELP, ""),
    })
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))  # 无 config.toml
    obs = mo.discover_codex()
    assert obs["cost_class"] == mo.COST_CLASS_UNKNOWN
    assert obs["cost_metadata"] is None
    assert obs["cost_multiplier"] is None


def test_hermes_api_provider_cost_unknown_not_paid(monkeypatch):
    """main model 走 DeepSeek API（base_url 空）→ 不得硬编码 PAID；如实 UNKNOWN。"""
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, HERMES_CONFIG_GET_MODEL, ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (1, "", "no"),
        ("C:/fake/bin/cli.exe", "--help"): (0, "", ""),
    })
    obs = mo.discover_hermes()
    assert obs["cost_class"] == mo.COST_CLASS_UNKNOWN
    # 绝不出现 FREE_PROMO / 固定倍率
    assert mo.COST_CLASS_FREE_PROMO not in _json_text(obs)
    assert "cost_multiplier" in obs and obs["cost_multiplier"] is None


def test_local_aux_slots_classified_local_free_from_evidence(monkeypatch):
    """local endpoint（base_url=127.0.0.1）→ LOCAL_FREE 且带证据（provider config 事实）。"""
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, HERMES_CONFIG_GET_MODEL, ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (0, HERMES_CONFIG_GET_AUXILIARY, ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, "", ""),
    })
    obs = mo.discover_hermes()
    slots = {s["slot"]: s for s in obs["auxiliary_slots"]}
    assert "vision" in slots
    vision = slots["vision"]
    assert vision["model"] == "qwen2.5vl:3b"
    assert vision["cost_class"] == mo.COST_CLASS_LOCAL_FREE
    assert "127.0.0.1" in vision["cost_metadata"]["evidence"]
    assert vision["classification"] == "model_slot"
    # skills_hub（空 model）不进入列表
    assert "skills_hub" not in slots


# ---------------------------------------------------------------------------
# E. secrets not persisted
# ---------------------------------------------------------------------------


def test_secrets_never_in_observation(monkeypatch):
    _fake_cli(monkeypatch)
    leaky_model_out = HERMES_CONFIG_GET_MODEL + "api_key: sk-SUPERSECRET12345\n"
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, leaky_model_out, ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (1, "", ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, "", ""),
    })
    obs = mo.discover_hermes()
    assert "sk-SUPERSECRET12345" not in _json_text(obs)


def test_codex_config_only_model_key_extracted(tmp_path, monkeypatch):
    cfg = tmp_path / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        'model = "gpt-5.2-codex"\napi_key = "sk-CODXSECRET999"\n[plugins.foo]\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    assert mo._codex_config_model() == "gpt-5.2-codex"
    # secret 不进入任何观测
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "exec", "--help"): (0, CODEX_EXEC_HELP, ""),
    })
    obs = mo.discover_codex()
    assert obs["model"] == "gpt-5.2-codex"
    assert "sk-CODXSECRET999" not in _json_text(obs)


# ---------------------------------------------------------------------------
# F. stage elapsed captured
# ---------------------------------------------------------------------------


def test_stage_timing_captured_when_provided(tmp_path):
    stage = build_stage_result(
        agent="hermes",
        result_text="done",
        output_dir=tmp_path,
        stage_started_at="2026-08-29T10:00:00",
        stage_elapsed_seconds=123.45678,
    )
    timing = stage["stage_timing"]
    assert timing["stage_started_at"] == "2026-08-29T10:00:00"
    assert timing["stage_finished_at"]  # 非空
    assert timing["stage_elapsed_seconds"] == 123.457  # 3 位小数


def test_stage_timing_absent_without_params(tmp_path):
    """未提供时序参数 → 旧行为：无 stage_timing / 无 ref 字段。"""
    stage = build_stage_result(agent="hermes", result_text="done", output_dir=tmp_path)
    assert "stage_timing" not in stage
    assert "model_observation_ref" not in stage


def test_model_observation_ref_present(tmp_path):
    stage = build_stage_result(
        agent="hermes", result_text="done", output_dir=tmp_path,
        model_observation_ref={"authority": str(tmp_path / "model_observation.json"), "entry": "hermes"},
    )
    assert stage["model_observation_ref"]["entry"] == "hermes"
    assert stage["model_observation_ref"]["authority"].endswith("model_observation.json")


# ---------------------------------------------------------------------------
# G. REPORT compact summary generated
# ---------------------------------------------------------------------------


def test_report_compact_model_section(tmp_path):
    obs = mo.make_observation(
        "hermes", provider="deepseek", model="deepseek-v4-flash",
        model_source=mo.MODEL_SOURCE_CONFIG, reasoning_effort="medium",
    )
    data = {"hermes": {"observation": obs, "stage_elapsed": 42.5}}
    report = build_report(
        "TASK", ["hermes"], {"hermes": "ok"}, "SUCCESS",
        output_dir=tmp_path, model_observations=data,
    )
    assert "## Model Observation" in report
    assert "model=deepseek-v4-flash" in report
    assert "stage=42.50s" in report
    assert "model_observation.json" in report
    # 紧凑：每 agent 一行 + 标题 + artifact 行
    section = report.split("## Model Observation")[1].split("## Planner Handoff")[0]
    lines = [l for l in section.splitlines() if l.strip()]
    assert len(lines) <= 3


def test_report_no_section_when_not_provided(tmp_path):
    report = build_report("TASK", ["hermes"], {"hermes": "ok"}, "SUCCESS", output_dir=tmp_path)
    assert "## Model Observation" not in report


def test_report_unknown_rendering(tmp_path):
    data = {"codex": {"observation": mo.empty_observation("codex"), "stage_elapsed": None}}
    report = build_report("TASK", ["codex"], {"codex": "ok"}, "SUCCESS",
                          output_dir=tmp_path, model_observations=data)
    assert "codex: model=UNKNOWN provider=UNKNOWN source=unknown" in report
    assert "stage=UNKNOWN" in report


# ---------------------------------------------------------------------------
# H. machine artifact detailed metadata available（single authority）
# ---------------------------------------------------------------------------


def test_registry_artifact_written_and_refreshed(tmp_path, monkeypatch):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, HERMES_CONFIG_GET_MODEL, ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (0, HERMES_CONFIG_GET_AUXILIARY, ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, "", ""),
    })
    registry = mo.refresh_observations(tmp_path, ["hermes"])
    artifact = tmp_path / mo.ARTIFACT_FILENAME
    assert artifact.exists()
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["schema_version"] == mo.SCHEMA_VERSION
    assert data["observations"]["hermes"]["model"] == "deepseek-v4-flash"
    assert data["refresh_policy"]["refreshable"] is True
    assert data["authority"]

    # 动态元数据：刷新后新模型替换旧条目（不把一次发现当永久事实）
    script = {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, "default: newer-model\nprovider: deepseek\nbase_url: ''\nreasoning_effort: high\n", ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (0, HERMES_CONFIG_GET_AUXILIARY, ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, "", ""),
    }
    monkeypatch.setattr(mo, "_run_readonly", lambda args, timeout=20.0: script.get(tuple(args), (1, "", "x")))
    mo.refresh_observations(tmp_path, ["hermes"])
    data2 = json.loads(artifact.read_text(encoding="utf-8"))
    assert data2["observations"]["hermes"]["model"] == "newer-model"
    assert len(data2["observations"]) == 1  # 覆盖而非累积


def test_registry_load_corrupt_returns_template(tmp_path):
    (tmp_path / mo.ARTIFACT_FILENAME).write_text("{not json", encoding="utf-8")
    registry = mo.load_registry(tmp_path)
    assert registry["observations"] == {}
    assert registry["schema_version"] == mo.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# I. existing Agent execution unchanged when telemetry disabled/fails
# ---------------------------------------------------------------------------


def test_observations_disabled_toggle():
    os.environ[mo.ENV_TOGGLE] = "0"
    try:
        assert mo.observations_enabled() is False
    finally:
        os.environ.pop(mo.ENV_TOGGLE, None)
    os.environ[mo.ENV_TOGGLE] = "false"
    try:
        assert mo.observations_enabled() is False
    finally:
        os.environ.pop(mo.ENV_TOGGLE, None)
    assert mo.observations_enabled() is True  # 默认启用


def test_runner_unchanged_when_telemetry_disabled(tmp_path, monkeypatch):
    """AAF_MODEL_OBSERVATION=0：无 stage_timing / 无 ref / 无 registry / REPORT 无段。"""
    import ai_agent_framework.runner as runner_mod

    def fake_run_agent(agent, prompt, workspace):
        return "ok"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setenv(mo.ENV_TOGGLE, "0")

    task_file = tmp_path / "TASK.md"
    task_file.write_text(_minimal_task(), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)

    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert "stage_timing" not in stage
    assert "model_observation_ref" not in stage
    assert not (out / mo.ARTIFACT_FILENAME).exists()
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Model Observation" not in report


def test_runner_telemetry_failure_does_not_fail_execution(tmp_path, monkeypatch):
    """discovery 层整体抛异常 → stage result 仍有效、REPORT 仍生成、状态仍 SUCCESS。"""
    import ai_agent_framework.runner as runner_mod

    def fake_run_agent(agent, prompt, workspace):
        if agent == "workbuddy":
            return ('PASS\n\nAAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"verdict": "PASS", "blocking_rework": false, '
                    '"findings": [], "warnings": []}\nAAF_STRUCTURED_RESULT_END')
        if agent == "codex":
            return ('APPROVE\n\nAAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"verdict": "APPROVE", "blocking_rework": false, '
                    '"findings": [], "warnings": []}\nAAF_STRUCTURED_RESULT_END')
        return "implemented ok"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)

    def boom(output_dir, agent):
        raise RuntimeError("telemetry exploded")

    monkeypatch.setattr(runner_mod.model_observation_mod, "observe_stage", boom)

    task_file = tmp_path / "TASK.md"
    task_file.write_text(_minimal_task(), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)

    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage["status"] == "SUCCESS"
    assert stage["stage_timing"]["stage_elapsed_seconds"] is not None


# ---------------------------------------------------------------------------
# 20. Agent-specific discovery（mock 真实 CLI 输出形态）
# ---------------------------------------------------------------------------


def test_hermes_auxiliary_and_capabilities(monkeypatch):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, HERMES_CONFIG_GET_MODEL, ""),
        ("C:/fake/bin/cli.exe", "config", "get", "auxiliary"): (0, HERMES_CONFIG_GET_AUXILIARY, ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, "usage: hermes [-h] [-m MODEL] [--provider PROVIDER] [--reasoning LEVEL]", ""),
    })
    obs = mo.discover_hermes()
    slots = {s["slot"]: s for s in obs["auxiliary_slots"]}
    assert {"vision", "compression", "web_extract"} <= set(slots)
    assert all(s["model_source"] == mo.MODEL_SOURCE_CONFIG for s in slots.values())
    assert any("ComfyUI" in n for n in obs["notes"])
    assert any("interactive-only" in n for n in obs["notes"])


def test_codebuddy_models_documented_by_cli(monkeypatch):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, "", ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, CODEBUDDY_HELP, ""),
    })
    obs = mo.discover_codebuddy()
    caps = obs["capabilities"]
    assert caps["explicit_model_selection"] is True
    assert caps["reasoning_effort_option"] is True
    docs = caps["models_documented_by_cli"]
    assert "glm-5.3" in docs
    assert "deepseek-v4-flash" in docs
    assert "hy4-preview" in docs
    # 静态 help 元数据带刷新语义说明，不是 AAF 硬编码
    assert any("not hardcoded" in n or "static" in n for n in obs["notes"])


def test_codex_capabilities_truthful(monkeypatch, tmp_path):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "exec", "--help"): (0, CODEX_EXEC_HELP, ""),
    })
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    obs = mo.discover_codex()
    caps = obs["capabilities"]
    assert caps["explicit_model_selection"] is True   # -m/--model
    assert caps["reasoning_effort_option"] is False   # 本版本无专用 flag
    assert caps["models_listable"] is False           # server-side catalog 不可枚举
    assert caps["local_provider_option"] is True      # --local-provider
    assert any("server-side" in n for n in obs["notes"])
    assert any("reasoning-effort" in n for n in obs["notes"])
    assert obs["discovery_status"] == mo.DISCOVERY_STATUS_UNAVAILABLE


def test_dispatch_workbuddy_uses_codebuddy(monkeypatch):
    _fake_cli(monkeypatch)
    _fake_run_readonly(monkeypatch, {
        ("C:/fake/bin/cli.exe", "config", "get", "model"): (0, "", ""),
        ("C:/fake/bin/cli.exe", "--help"): (0, CODEBUDDY_HELP, ""),
    })
    obs = mo.discover_agent("workbuddy")
    assert obs["agent"] == "workbuddy"  # route agent 名保留
    assert obs["model"] is None


# ---------------------------------------------------------------------------
# Runner 集成：telemetry 开启 → registry / stage_timing / REPORT 段齐全
# ---------------------------------------------------------------------------


def test_runner_full_telemetry_flow(tmp_path, monkeypatch):
    import ai_agent_framework.runner as runner_mod

    def fake_run_agent(agent, prompt, workspace):
        return "ok"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    # conftest 已把 _find_cli 置 None → discovery 走 UNAVAILABLE 快速路径（零 subprocess）
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_minimal_task(), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)

    # machine artifact authority 存在
    artifact = out / mo.ARTIFACT_FILENAME
    assert artifact.exists()
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["observations"]["hermes"]["model"] is None  # CLI 不可用 → UNKNOWN
    assert data["observations"]["hermes"]["discovery_status"] == mo.DISCOVERY_STATUS_UNAVAILABLE

    # stage result：stage_timing + ref（引用 authority，无重复数据）
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage["stage_timing"]["stage_started_at"]
    assert stage["stage_timing"]["stage_elapsed_seconds"] >= 0
    assert stage["model_observation_ref"]["entry"] == "hermes"
    assert stage["model_observation_ref"]["authority"].endswith(mo.ARTIFACT_FILENAME)

    # REPORT 紧凑段
    report = report_path.read_text(encoding="utf-8")
    assert "## Model Observation" in report
    assert "hermes: model=UNKNOWN provider=UNKNOWN source=unknown" in report
    assert "model_observation.json" in report


def _minimal_task() -> str:
    return (
        "# Task ID\nT-OBS\n\n"
        "# Task Name\nmodel observation test\n\n"
        "# Objective\nimplement telemetry verification\n\n"
        "# Route\nhermes -> workbuddy -> codex\n\n"
        "# Acceptance\n1. pass\n"
    )
