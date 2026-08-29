"""AAF-v0.5-A0 Hermes Paid Guard 定向测试（TASK: AAF-v0.5-A0-PAID-GUARD-001）。

覆盖 Requirement 14 A–G：
A. known local/free Hermes model → allowed
B. remote paid/unknown Hermes model without authorization → BLOCKED_COST_APPROVAL
   + Hermes subprocess not started
C. exact valid task/stage/model authorization → allowed
D. authorization for another Task → blocked
E. authorization for another model → blocked
F. missing/ambiguous effective model or cost status → fail closed
G. existing unrelated runner behavior/regressions → pass

conftest hermetic：默认 resolution = 本地免费模型（零 CLI / 零网络）；guard 环境
变量默认清除。付费/授权路径由各测试自行 monkeypatch resolution / setenv。
"""

import json
import os

import pytest

from ai_agent_framework import cost_guard as cg
from ai_agent_framework import runner as runner_mod
from ai_agent_framework.task_validation import TaskValidationError

# 在 conftest autouse fixture 替换模块属性之前捕获真实实现
# （resolution 定向测试需要真实 resolve 函数 + 自行 patch _find_cli/_run_readonly）。
_REAL_RESOLVE = cg.resolve_effective_hermes

MINIMAL_VALID_TASK = """# Task ID
T-EXEC

# Task Name
执行链测试

# Objective
实现功能并验收

# Acceptance
1. 通过
"""


# ---------------------------------------------------------------------------
# 工具 helpers
# ---------------------------------------------------------------------------


def _paid_resolution(model="deepseek-v4-flash", provider="deepseek", base_url=None):
    return {
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "model_source": cg.MODEL_SOURCE_ENV,
        "notes": ["test paid resolution"],
    }


def _run_full_runner(tmp_path, monkeypatch, task_text=MINIMAL_VALID_TASK):
    """完整 runner.run（真实 lifecycle / filesystem；mock run_agent 记录调用）。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)

    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding="utf-8")
    return calls, out, report


# ---------------------------------------------------------------------------
# 成本分类（Requirement 3 / 设计规则 2：UNKNOWN 不视为 FREE；不凭名称猜 FREE）
# ---------------------------------------------------------------------------


def test_classify_local_base_url_is_local_free():
    cls, meta = cg.classify_cost("qwen3:4b", "custom", "http://127.0.0.1:11434/v1")
    assert cls == cg.COST_LOCAL_FREE
    assert "127.0.0.1" in meta["evidence"]


def test_classify_ollama_without_remote_base_url_is_local_free():
    cls, meta = cg.classify_cost("qwen3:4b", "ollama", None)
    assert cls == cg.COST_LOCAL_FREE
    assert "ollama" in meta["evidence"]


def test_classify_ollama_with_remote_base_url_fails_closed():
    cls, _ = cg.classify_cost("qwen3:4b", "ollama", "https://ollama.example.com/v1")
    assert cls == cg.COST_PAID_OR_UNKNOWN


def test_classify_remote_model_without_free_metadata_is_paid_or_unknown():
    cls, _ = cg.classify_cost("deepseek-v4-flash", "deepseek", None)
    assert cls == cg.COST_PAID_OR_UNKNOWN


def test_classify_never_infers_free_from_model_name():
    # 模型名含 free 字样但无权威元数据 → 绝不因此 FREE（Requirement 3）
    cls, _ = cg.classify_cost("free-trial-llm", "some-api", None)
    assert cls == cg.COST_PAID_OR_UNKNOWN


def test_classify_explicit_free_metadata_bare_model():
    cls, _ = cg.classify_cost("free-model-a", "deepseek", None, free_entries=["free-model-a"])
    assert cls == cg.COST_FREE


def test_classify_explicit_free_metadata_model_at_provider():
    cls, _ = cg.classify_cost("free-model-a", "deepseek", None, free_entries=["free-model-a@deepseek"])
    assert cls == cg.COST_FREE
    # 同模型不同 provider → 不匹配（provider-scoped 声明）
    cls2, _ = cg.classify_cost("free-model-a", "other-provider", None, free_entries=["free-model-a@deepseek"])
    assert cls2 == cg.COST_PAID_OR_UNKNOWN


def test_classify_none_model_is_cost_unknown():
    cls, _ = cg.classify_cost(None, None, None)
    assert cls == cg.COST_UNKNOWN


# ---------------------------------------------------------------------------
# Scope / 授权匹配（Requirement 4/5：精确匹配；不泄漏）
# ---------------------------------------------------------------------------


def test_scope_string_includes_provider_when_known():
    assert cg.scope_string("T1", "hermes", "m", "p") == "T1|hermes|m|p"


def test_scope_string_omits_unknown_provider():
    assert cg.scope_string("T1", "hermes", "m", None) == "T1|hermes|m"


def test_authorization_requires_exact_whole_string():
    # 前缀/包含/缺 provider 均不得匹配（fail closed）
    assert not cg._authorization_matches("T1|hermes|m", "T1|hermes|m|p")
    assert not cg._authorization_matches("T1|hermes|m|p", "T1|hermes|m")
    assert not cg._authorization_matches("T1|hermes|m|p ", "T1|hermes|m|p")
    assert cg._authorization_matches("T1|hermes|m|p", "T1|hermes|m|p")
    assert not cg._authorization_matches(None, "T1|hermes|m|p")


# ---------------------------------------------------------------------------
# evaluate()：A / B / C / D / E / F
# ---------------------------------------------------------------------------


def test_a_local_free_model_allowed(monkeypatch):
    monkeypatch.setattr(
        cg, "resolve_effective_hermes",
        lambda: {"model": "qwen3:4b", "provider": "ollama", "base_url": None,
                 "model_source": "env_override", "notes": []},
    )
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_ALLOWED_FREE
    assert rec["cost_class"] == cg.COST_LOCAL_FREE
    assert rec["required_scope"] is None


def test_a_explicit_free_metadata_allowed(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_FREE_MODELS, "deepseek-v4-flash@deepseek")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_ALLOWED_FREE
    assert rec["cost_class"] == cg.COST_FREE


def test_b_paid_without_authorization_blocked(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert rec["required_scope"] == "T1|hermes|deepseek-v4-flash|deepseek"
    assert rec["authorization_present"] is False
    assert rec["authorization_matched"] is False


def test_c_exact_authorization_allows_paid(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert rec["authorization_matched"] is True


def test_d_authorization_for_another_task_blocked(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T-OTHER-TASK|hermes|deepseek-v4-flash|deepseek")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_matched"] is False
    # 精确 scope 仍然给出，用户可据此授权
    assert rec["required_scope"] == "T1|hermes|deepseek-v4-flash|deepseek"


def test_e_authorization_for_another_model_blocked(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|another-model|deepseek")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL


def test_f_missing_effective_model_fails_closed(monkeypatch):
    monkeypatch.setattr(
        cg, "resolve_effective_hermes",
        lambda: {"model": None, "provider": None, "base_url": None,
                 "model_source": cg.MODEL_SOURCE_UNKNOWN, "notes": ["unresolved"]},
    )
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["cost_class"] == cg.COST_UNKNOWN
    assert rec["required_scope"] is None  # 无法验证 scope → 不给可授权 scope


def test_f_ambiguous_provider_mismatch_blocked(monkeypatch):
    # provider 已知但授权串不含 provider → 不匹配（fail closed）
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL


# ---------------------------------------------------------------------------
# resolve_effective_hermes（Requirement 2 / 11：env 优先；CLI 只读 fallback；无网络）
# ---------------------------------------------------------------------------


def test_resolution_env_override_makes_no_subprocess(monkeypatch):
    """env 覆盖时零 subprocess（不触发 CLI / 网络）。"""

    def _boom(*a, **k):
        raise AssertionError("CLI must not be probed when env override is present")

    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setenv(cg.ENV_MODEL, "deepseek-v4-flash")
    monkeypatch.setenv(cg.ENV_PROVIDER, "deepseek")
    monkeypatch.setattr(cg, "_find_cli", _boom)
    monkeypatch.setattr(cg, "_run_readonly", _boom)
    eff = cg.resolve_effective_hermes()
    assert eff["model"] == "deepseek-v4-flash"
    assert eff["provider"] == "deepseek"
    assert eff["model_source"] == cg.MODEL_SOURCE_ENV


def test_resolution_hermes_config_fallback(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.delenv(cg.ENV_MODEL, raising=False)
    monkeypatch.setattr(cg, "_find_cli", lambda cmd: "C:/fake/hermes.exe")
    monkeypatch.setattr(
        cg, "_run_readonly",
        lambda *a, **k: (0, "default: deepseek-v4-flash\nprovider: deepseek\nreasoning_effort: medium\n", ""),
    )
    eff = cg.resolve_effective_hermes()
    assert eff["model"] == "deepseek-v4-flash"
    assert eff["provider"] == "deepseek"
    assert eff["model_source"] == cg.MODEL_SOURCE_CONFIG


def test_resolution_failure_is_none_fail_closed(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.delenv(cg.ENV_MODEL, raising=False)
    monkeypatch.setattr(cg, "_find_cli", lambda cmd: None)
    eff = cg.resolve_effective_hermes()
    assert eff["model"] is None
    assert eff["model_source"] == cg.MODEL_SOURCE_UNKNOWN


def test_resolution_config_error_is_none(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.delenv(cg.ENV_MODEL, raising=False)
    monkeypatch.setattr(cg, "_find_cli", lambda cmd: "C:/fake/hermes.exe")
    monkeypatch.setattr(cg, "_run_readonly", lambda *a, **k: None)  # 调用失败
    eff = cg.resolve_effective_hermes()
    assert eff["model"] is None


# ---------------------------------------------------------------------------
# blocked 文本（Requirement 6：人读信息完整）
# ---------------------------------------------------------------------------


def test_blocked_text_contains_required_human_fields(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    rec = cg.evaluate("T1", "hermes")
    text = cg.blocked_stage_text(rec)
    assert text.startswith("FRAMEWORK_ERROR\nCOST_APPROVAL_REQUIRED")
    for field in ("T1", "hermes", "deepseek-v4-flash", "deepseek",
                  cg.COST_PAID_OR_UNKNOWN, cg.ENV_AUTH):
        assert field in text
    assert 'AAF_COST_AUTH="T1|hermes|deepseek-v4-flash|deepseek"' in text
    assert "Hermes" in text  # 明确说明 Hermes 未启动


# ---------------------------------------------------------------------------
# Runner 集成（Requirement 7/8：guard 在 subprocess 前；blocked → 零 Hermes 调用）
# ---------------------------------------------------------------------------


def test_g_free_local_hermes_reaches_invocation_regression(tmp_path, monkeypatch):
    """默认 hermetic（本地免费）→ Hermes stage 照常执行（既有 runner 行为回归 G）。"""
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)
    assert calls == ["hermes", "workbuddy"]
    assert "## Current Status\nSUCCESS" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_ALLOWED_FREE


def test_b_blocked_paid_hermes_never_spawned(tmp_path, monkeypatch):
    """付费/未知 + 无授权 → Hermes stage 被 guard 阻断：run_agent 零调用
    （= Hermes subprocess 未创建），任务 WAITING，机器可读状态完整。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)

    assert calls == []  # Hermes 未被调用（subprocess 未创建）
    assert "## Current Status\nWAITING" in report
    assert "Required executor Hermes did not run" in report

    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert guard["task_id"] == "T-EXEC"
    assert guard["stage"] == "hermes"
    assert guard["model"] == "deepseek-v4-flash"
    assert guard["provider"] == "deepseek"
    assert guard["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert guard["required_scope"] == "T-EXEC|hermes|deepseek-v4-flash|deepseek"

    hermes_result = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert hermes_result.startswith("FRAMEWORK_ERROR\nCOST_APPROVAL_REQUIRED")
    assert "T-EXEC|hermes|deepseek-v4-flash|deepseek" in hermes_result
    # 未产生真实 Hermes 输出
    assert "implemented" not in hermes_result


def test_c_runner_exact_authorization_allows_paid_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T-EXEC|hermes|deepseek-v4-flash|deepseek")
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)

    assert calls == ["hermes", "workbuddy"]
    assert "## Current Status\nSUCCESS" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert guard["authorization_matched"] is True


def test_d_runner_auth_for_other_task_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "SOME-OTHER-TASK|hermes|deepseek-v4-flash|deepseek")
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)

    assert calls == []
    assert "## Current Status\nWAITING" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL


def test_e_runner_auth_for_other_model_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T-EXEC|hermes|some-other-model|deepseek")
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)

    assert calls == []
    assert "## Current Status\nWAITING" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL


def test_f_runner_unresolved_model_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cg, "resolve_effective_hermes",
        lambda: {"model": None, "provider": None, "base_url": None,
                 "model_source": cg.MODEL_SOURCE_UNKNOWN, "notes": ["unresolved"]},
    )
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)

    assert calls == []
    assert "## Current Status\nWAITING" in report
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert guard["cost_class"] == cg.COST_UNKNOWN


def test_blocked_terminal_resume_refused_without_reexecution(tmp_path, monkeypatch):
    """BLOCKED 以 FRAMEWORK_ERROR 开头 + 任务终态 WAITING（terminal）。

    v0.4 lifecycle：terminal WAITING 的目录 resume-from 不会重开执行链
    （TerminalAlreadyCommitted → 派生产物跟随 canonical），Hermes 不会被再次
    调用；恢复路径 = 设置 AAF_COST_AUTH 后重新提交任务（新 execution）。
    """
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())

    task_file = tmp_path / "TASK.md"
    task_file.write_text(MINIMAL_VALID_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"

    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)

    # Run 1：blocked（terminal WAITING）
    runner_mod.run(task_file, ws, out)
    assert calls == []
    blocked = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert blocked.startswith("FRAMEWORK_ERROR")
    assert json.loads((out / "run.json").read_text(encoding="utf-8"))["status"] == "WAITING"

    # Run 2：同一目录 resume-from（即便已设置精确授权）→ 已终态目录不重开
    monkeypatch.setenv(cg.ENV_AUTH, "T-EXEC|hermes|deepseek-v4-flash|deepseek")
    runner_mod.run(task_file, ws, out, resume_from=out)
    assert calls == []
    # blocked 结果未被当作已完成 hermes 结果复用
    assert (out / "hermes_result.md").read_text(encoding="utf-8").startswith("FRAMEWORK_ERROR")


def test_guard_decision_timing_recorded(monkeypatch):
    """Requirement 11：决策耗时记录在 cost_guard.json（decision_ms）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    rec = cg.evaluate("T1", "hermes")
    assert isinstance(rec["decision_ms"], (int, float))
    assert rec["decision_ms"] >= 0


# ---------------------------------------------------------------------------
# adapters 透传（guard 解析的 effective model == 实际 invocation 参数；
# Requirement 2 invocation-truth；无覆盖时 args 与旧版完全一致）
# ---------------------------------------------------------------------------


def _capture_run(monkeypatch, captured: dict):
    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env, **kwargs):
        captured.update(
            args=args, cwd=cwd, input=input, text=text, encoding=encoding,
            errors=errors, capture_output=capture_output, timeout=timeout,
            env=env, kwargs=kwargs,
        )

        class FakeProc:
            returncode = 0
            stdout = 'implemented ok'
            stderr = ''
        return FakeProc()

    import subprocess as subprocess_mod
    monkeypatch.setattr(subprocess_mod, "run", fake_run)


def test_hermes_override_passed_to_invocation(monkeypatch, tmp_path):
    """AAF_HERMES_MODEL / AAF_HERMES_PROVIDER 设置时 → hermes args 含 -m/--provider
    （guard 解析的 effective model == 实际调用模型）。"""
    from ai_agent_framework.adapters import run_agent

    captured: dict = {}
    _capture_run(monkeypatch, captured)
    monkeypatch.setenv(cg.ENV_MODEL, "deepseek-v4-flash")
    monkeypatch.setenv(cg.ENV_PROVIDER, "deepseek")

    run_agent("hermes", "TASK", tmp_path)

    assert os.path.basename(captured["args"][0]).lower() in ("hermes", "hermes.exe", "hermes.bat")
    assert "-m" in captured["args"]
    assert captured["args"][captured["args"].index("-m") + 1] == "deepseek-v4-flash"
    assert "--provider" in captured["args"]
    assert captured["args"][captured["args"].index("--provider") + 1] == "deepseek"


def test_hermes_invocation_unchanged_without_override(monkeypatch, tmp_path):
    """无 env 覆盖 → args 与 v0.4 完全一致（无 -m/--provider；行为保持）。"""
    from ai_agent_framework.adapters import run_agent

    captured: dict = {}
    _capture_run(monkeypatch, captured)

    run_agent("hermes", "TASK", tmp_path)

    assert os.path.basename(captured["args"][0]).lower() in ("hermes", "hermes.exe", "hermes.bat")
    assert captured["args"][1] == "chat"
    assert "-m" not in captured["args"]
    assert "--provider" not in captured["args"]
    assert captured["input"] is None
