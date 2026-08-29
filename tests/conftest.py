"""Pytest 共享 fixture（tests/ 根 conftest）。

AAF-v0.4-TASK-010：测试套件 hermetic 保证——默认不调用真实 Agent CLI。

- ``_find_cli → None``：model discovery 走 UNAVAILABLE 快速路径（零 subprocess），
  现有 / 新测试都不会在测试中执行真实 hermes / codebuddy / codex。
- 清除 AAF_MODEL_OBSERVATION 环境变量：telemetry 默认开启路径确定可测
  （runner 集成测试可确定性断言 registry / stage_timing / REPORT 段）。
- 需要真实 discovery 解析的测试自行重新 patch ``_find_cli`` / ``_run_readonly``。

AAF-v0.5-A0（Paid Guard）：cost_guard hermetic 默认——resolution 固定为
本地免费模型（零 CLI / 零网络），并清除全部 guard 环境变量（AAF_HERMES_MODEL /
AAF_HERMES_PROVIDER / AAF_COST_AUTH / AAF_COST_FREE_MODELS），使既有 runner
集成测试（mock run_agent）在 guard 下保持 ALLOWED_FREE 语义；需要付费/授权
路径的测试自行 monkeypatch resolution 或设置环境变量。
"""
import pytest

from ai_agent_framework import model_observation as mo
from ai_agent_framework import cost_guard as cg

_HERMETIC_RESOLUTION = {
    "model": "qwen3:4b",
    "provider": "ollama",
    "base_url": "http://127.0.0.1:11434/v1",
    "model_source": "test_hermetic",
    "notes": ["hermetic test resolution (no real CLI)"],
}


@pytest.fixture(autouse=True)
def _hermetic_model_discovery(monkeypatch):
    monkeypatch.setattr(mo, "_find_cli", lambda cmd: None)
    monkeypatch.delenv(mo.ENV_TOGGLE, raising=False)
    return mo


@pytest.fixture(autouse=True)
def _hermetic_cost_guard(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: dict(_HERMETIC_RESOLUTION))
    for env in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_AUTH, cg.ENV_FREE_MODELS):
        monkeypatch.delenv(env, raising=False)
    return cg
