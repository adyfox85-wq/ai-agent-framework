"""AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001 fresh-runner wrapper（Run N+1）。

与 tests/fresh_runner_wrapper.py 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / active_routing.py /
model_registry.py 不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - baseline（默认）：原样返回 A1 基线 registry（N1：LOW → qwen3:4b@custom
     真实 active route 回归）。
   - promo_sole：仅含一个 FREE_PROMO + QUALIFIED + T4 的 Hermes 候选（N2
     control——A2 selector 会选中它（A1 FREE_OF_COST_CLASSES 通用语义不变），
     A3 active-routing cost gate（严格 FREE/LOCAL_FREE）必须拒绝 →
     routing_applied=false、configured model/provider 保留、零 fallback）。

用法：
    python tests/fresh_runner_a3_fix001_wrapper.py <TASK.md> --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN        fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE   baseline | promo_sole（缺省 baseline）
    FAKE_HERMES_MARKER       fake hermes chat 写入的 env 证据 marker 路径
"""
from __future__ import annotations

import os

from ai_agent_framework import adapters as adapters_mod
from ai_agent_framework import cost_guard as cost_guard_mod
from ai_agent_framework import model_registry as model_registry_mod
from ai_agent_framework.model_observation import COST_CLASS_FREE_PROMO

_real_adapters_path = adapters_mod._windows_path
_real_guard_path = cost_guard_mod._windows_path


def _prepend_fake_bin(original):
    extra = os.environ.get("AAF_TEST_FAKE_BIN", "").strip()
    if not extra:
        return original
    return extra + ";" + original


adapters_mod._windows_path = lambda: _prepend_fake_bin(_real_adapters_path())
cost_guard_mod._windows_path = lambda: _prepend_fake_bin(_real_guard_path())


def _promo_sole_registry() -> dict:
    """FIX-001 N2 control registry：唯一 eligible 候选 = FREE_PROMO + QUALIFIED + T4。

    selector（A2 引擎，消费 A1 FREE_OF_COST_CLASSES）把 FREE_PROMO 视为 0 现金
    类别 → 选中它（sole eligible）；A3 active-routing cost gate 必须拒绝。
    test-only fixture——绝不进入 A1 baseline（baseline 语义零改动）。
    """
    entry = model_registry_mod.RegistryEntry(
        model="promo-model",
        provider="custom",
        base_url="https://promo.example/v1",
        applicable_agents=("hermes",),
        capability_tier=model_registry_mod.CAP_TIER_T4,
        cost_class=COST_CLASS_FREE_PROMO,
        locality=model_registry_mod.LOCALITY_REMOTE,
        qualification=model_registry_mod.RuntimeQualification(
            status=model_registry_mod.QUAL_STATUS_QUALIFIED,
            # scope=main（TASK: AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001）：
            # 该 fixture 要测的是 A3 cost gate（FREE_PROMO 拒绝），不是 scope 闸
            # ——候选必须是 eligible executor 才会到达 cost gate。
            scope=model_registry_mod.QUAL_SCOPE_MAIN,
            evidence=("fresh-runner-fix001-promo-fixture",),
            observed_at="2026-09-01T00:00:00+08:00",
        ),
        evidence=("fresh-runner-fix001-promo-fixture",),
        notes=(
            "FIX-001 fresh-runner FREE_PROMO fixture (test-only, not baseline)",
        ),
    )
    return {entry.key(): entry}


_mode = os.environ.get("AAF_TEST_REGISTRY_MODE", "baseline").strip()
if _mode == "promo_sole":
    model_registry_mod.baseline_registry = _promo_sole_registry
elif _mode != "baseline":
    raise SystemExit(f"unknown AAF_TEST_REGISTRY_MODE: {_mode!r}")

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
