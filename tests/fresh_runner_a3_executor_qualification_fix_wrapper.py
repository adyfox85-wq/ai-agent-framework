"""AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001 fresh-runner wrapper（Run N+1）。

与 tests/fresh_runner_wrapper.py 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / active_routing.py /
shadow_routing.py / model_registry.py 不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - baseline（默认）：原样返回 A1 基线 registry。
   - aux_sole：仅含一个 aux-scope（scope=auxiliary）QUALIFIED LOCAL_FREE
     Hermes 候选（受控 fixture，模拟 qwen3:4b@custom 的资格形状——evidence
     只覆盖 auxiliary/端点级上下文，不覆盖真实 main-chat 调用路径）。
   - main_free：仅含一个 main-scope（scope=main）QUALIFIED LOCAL_FREE
     Hermes 候选（受控 fixture——「真正主调用合格的 free executor」形态）。
   aux_sole / main_free 都是 test-only fixture，绝不进入 A1 baseline。

用法：
    python tests/fresh_runner_a3_executor_qualification_fix_wrapper.py <TASK.md> --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN        fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE   baseline | aux_sole | main_free（缺省 baseline）
    FAKE_HERMES_MARKER       fake hermes chat 写入的 env 证据 marker 路径
    FAKE_HERMES_FAIL=1       fake hermes chat 模拟 invocation 失败（exit 1）
"""
from __future__ import annotations

import os

from ai_agent_framework import adapters as adapters_mod
from ai_agent_framework import cost_guard as cost_guard_mod
from ai_agent_framework import model_registry as model_registry_mod

_real_adapters_path = adapters_mod._windows_path
_real_guard_path = cost_guard_mod._windows_path


def _prepend_fake_bin(original):
    extra = os.environ.get("AAF_TEST_FAKE_BIN", "").strip()
    if not extra:
        return original
    return extra + ";" + original


adapters_mod._windows_path = lambda: _prepend_fake_bin(_real_adapters_path())
cost_guard_mod._windows_path = lambda: _prepend_fake_bin(_real_guard_path())


def _controlled_entry(model: str, scope: str) -> dict:
    """受控 Hermes 候选 fixture（test-only；qualification shape 与 qwen3:4b@custom
    相同：T4 + QUALIFIED + LOCAL_FREE + 本地端点；scope 决定 executor 资格）。"""
    entry = model_registry_mod.RegistryEntry(
        model=model,
        provider="custom",
        base_url="http://127.0.0.1:11434/v1",
        applicable_agents=("hermes",),
        capability_tier=model_registry_mod.CAP_TIER_T4,
        cost_class=model_registry_mod.COST_CLASS_LOCAL_FREE,
        locality=model_registry_mod.LOCALITY_LOCAL,
        qualification=model_registry_mod.RuntimeQualification(
            status=model_registry_mod.QUAL_STATUS_QUALIFIED,
            scope=scope,
            evidence=(f"fresh-runner-qualification-fix-fixture-scope-{scope}",),
            observed_at="2026-09-02T00:00:00+08:00",
        ),
        evidence=(f"fresh-runner-qualification-fix-fixture-scope-{scope}",),
        notes=(
            "EXECUTOR-QUALIFICATION-FIX fresh-runner controlled fixture "
            "(test-only, not baseline)",
        ),
    )
    return {entry.key(): entry}


def _aux_sole_registry() -> dict:
    """aux_sole：唯一候选 scope=auxiliary —— executor 资格不足（AUXILIARY_ONLY）。"""
    return _controlled_entry("aux-model", model_registry_mod.QUAL_SCOPE_AUXILIARY)


def _main_free_registry() -> dict:
    """main_free：唯一候选 scope=main —— executor 资格合格（LOCAL_FREE）。"""
    return _controlled_entry("main-free", model_registry_mod.QUAL_SCOPE_MAIN)


_mode = os.environ.get("AAF_TEST_REGISTRY_MODE", "baseline").strip()
if _mode == "aux_sole":
    model_registry_mod.baseline_registry = _aux_sole_registry
elif _mode == "main_free":
    model_registry_mod.baseline_registry = _main_free_registry
elif _mode != "baseline":
    raise SystemExit(f"unknown AAF_TEST_REGISTRY_MODE: {_mode!r}")

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
