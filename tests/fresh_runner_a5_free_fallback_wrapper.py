"""AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001 fresh-runner wrapper（Run N+1）。

与既有 fresh-runner wrapper 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / fallback_runtime.py /
fallback_contract.py / active_routing.py / shadow_routing.py / model_registry.py
不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - baseline（默认）：原样返回 A1 基线 registry（真实事实）。
   - fb_success：两个 main-scope QUALIFIED LOCAL_FREE Hermes 候选
     （aaa-orig / zzz-fb——A3 初始 routing 选中 aaa-orig；其失败后 A5 fallback
     到 zzz-fb）。
   - fb_single：唯一 main-scope LOCAL_FREE 候选（aaa-orig）——A3 路由后失败，
     same-model 排除 → 无候选 → fail closed。
   - fb_paid_pool：aaa-orig（LOCAL_FREE）+ zzz-paid（PAID）+ mmm-unk（UNKNOWN）
     ——paid/unknown 候选被 A5 cost gate 排除 → 无 second invocation。
   fb_* 都是 test-only controlled fixture，绝不进入 A1 baseline。

用法：
    python tests/fresh_runner_a5_free_fallback_wrapper.py <TASK.md> --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN         fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE    baseline | fb_success | fb_single | fb_paid_pool
    AAF_TEST_FAIL_MODELS      fake hermes chat 的失败模型列表 "model@provider;..."
                              （env 覆盖 = actual invocation model；无覆盖时用 fake
                              config 的 deepseek-v4-flash@deepseek）
    FAKE_HERMES_MARKER        fake hermes chat 逐次 append 的调用证据（MODEL= 行）
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


def _controlled_entry(model: str, provider: str, cost_class: str) -> dict:
    """受控 Hermes 候选 fixture（test-only；main-scope QUALIFIED LOCAL_FREE/
    PAID/UNKNOWN 形状由调用方指定；本地候选带 loopback base_url）。"""
    locality = model_registry_mod.LOCALITY_LOCAL if cost_class == "LOCAL_FREE" else model_registry_mod.LOCALITY_REMOTE
    base_url = "http://127.0.0.1:11434/v1" if cost_class == "LOCAL_FREE" else None
    entry = model_registry_mod.RegistryEntry(
        model=model,
        provider=provider,
        base_url=base_url,
        applicable_agents=("hermes",),
        capability_tier=model_registry_mod.CAP_TIER_T4,
        cost_class=cost_class,
        locality=locality,
        qualification=model_registry_mod.RuntimeQualification(
            status=model_registry_mod.QUAL_STATUS_QUALIFIED,
            scope=model_registry_mod.QUAL_SCOPE_MAIN,
            evidence=(f"a5-free-fallback-fresh-runner-fixture-{model}",),
            observed_at="2026-09-02T00:00:00+08:00",
        ),
        evidence=(f"a5-free-fallback-fresh-runner-fixture-{model}",),
        notes=(
            "A5-FREE-FALLBACK-RUNTIME fresh-runner controlled fixture "
            "(test-only, not baseline)",
        ),
    )
    return {entry.key(): entry}


def _registry(mode: str) -> dict:
    if mode == "fb_success":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-fb", "custom", "LOCAL_FREE"))
        return reg
    if mode == "fb_single":
        return _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
    if mode == "fb_paid_pool":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-paid", "remote-api", "PAID"))
        reg.update(_controlled_entry("mmm-unk", "remote-api", "UNKNOWN"))
        return reg
    raise SystemExit(f"unknown AAF_TEST_REGISTRY_MODE: {mode!r}")


_mode = os.environ.get("AAF_TEST_REGISTRY_MODE", "baseline").strip()
if _mode != "baseline":
    model_registry_mod.baseline_registry = lambda: _registry(_mode)

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
