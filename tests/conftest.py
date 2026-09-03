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

AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001（state-root 隔离）：autouse 把
AAF_BRIDGE_DIR 指向每个测试独立临时根——launch registry 与 last_run.json
（config.state_root）在全部测试中一律落在临时根，测试执行（含真实 launcher /
dummy runner 收尾的 _persist_last）**绝不**向真实 ~/.aaf-bridge/ 写入任何
测试身份（F-I-RUN 等）。需要自定义根的测试可再次 monkeypatch.setenv
（后设置者生效）；legacy 直接 patch cfg_mod.CONFIG_DIR 的测试语义不变
（state_root 优先 env；env 已指向临时根时 CONFIG_DIR patch 不参与 last_run
解析——此类测试已改为显式设置 AAF_BRIDGE_DIR）。
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
def _bridge_state_root_isolation(tmp_path, monkeypatch):
    """Bridge state root（registry + last_run.json）→ 每个测试独立临时根。

    防止测试执行把测试任务身份写进真实用户 Bridge 状态（requirement 7/11）。
    只设置 env 指向，**不预先创建目录**——registry/last_run 的写入方
    （launcher/reg_mod）会自行 mkdir；不触碰 Bridge state 的测试保持
    tmp_path 纯净（严格 cwd/空目录断言不受影响）。
    """
    d = tmp_path / "aaf-bridge-state"
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(d))
    return d


@pytest.fixture(autouse=True)
def _hermetic_cost_guard(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: dict(_HERMETIC_RESOLUTION))
    for env in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_AUTH, cg.ENV_FREE_MODELS):
        monkeypatch.delenv(env, raising=False)
    # 一次性授权 in-process 消费状态：每个测试独立（无跨测试泄漏）
    cg._CONSUMED_AUTHS.clear()
    return cg
