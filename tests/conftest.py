"""Pytest 共享 fixture（tests/ 根 conftest）。

AAF-v0.4-TASK-010：测试套件 hermetic 保证——默认不调用真实 Agent CLI。

- ``_find_cli → None``：model discovery 走 UNAVAILABLE 快速路径（零 subprocess），
  现有 / 新测试都不会在测试中执行真实 hermes / codebuddy / codex。
- 清除 AAF_MODEL_OBSERVATION 环境变量：telemetry 默认开启路径确定可测
  （runner 集成测试可确定性断言 registry / stage_timing / REPORT 段）。
- 需要真实 discovery 解析的测试自行重新 patch ``_find_cli`` / ``_run_readonly``。
"""
import pytest

from ai_agent_framework import model_observation as mo


@pytest.fixture(autouse=True)
def _hermetic_model_discovery(monkeypatch):
    monkeypatch.setattr(mo, "_find_cli", lambda cmd: None)
    monkeypatch.delenv(mo.ENV_TOGGLE, raising=False)
    return mo
