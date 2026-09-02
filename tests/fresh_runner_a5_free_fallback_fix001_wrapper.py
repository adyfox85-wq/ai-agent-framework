"""AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner wrapper.

与既有 fresh-runner wrapper 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / fallback_runtime.py /
cost_guard.py 等不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - baseline（默认）：原样返回 A1 基线 registry（真实事实）。
   - fb_success：两个 main-scope QUALIFIED LOCAL_FREE Hermes 候选
     （aaa-orig / zzz-fb——A3 初始 routing 选中 aaa-orig；其失败后 A5 fallback
     到 zzz-fb）。
   - fb_paid_admission（FIX-001 场景）：aaa-orig（LOCAL_FREE，本地端点）+
     zzz-free（registry cost_class=FREE 远程候选——A5 registry cost gate
     放行，但 A0 Paid Guard 按真实端点事实（remote-api / 无本地 base_url）
     权威解析为 PAID_OR_UNKNOWN；配合精确 AAF_COST_AUTH →
     ALLOWED_AUTHORIZED_PAID → FIX-001 FREE-only 单元拒绝执行；auth mismatch
     → A0 BLOCKED）。
   fb_* 都是 test-only controlled fixture，绝不进入 A1 baseline。
3. AAF_TEST_AUDIT_SAVE_FAIL=1 → patch fallback_runtime.save_fallback_runtime
   抛 OSError（FIX-001 audit persistence failure 注入；只影响权威 audit
   落盘，其他 artifact 写入路径零影响）。

用法：
    python tests/fresh_runner_a5_free_fallback_fix001_wrapper.py <TASK.md> \
        --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN         fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE    baseline | fb_success | fb_paid_admission
    AAF_TEST_FAIL_MODELS      fake hermes chat 的失败模型列表 "model@provider;..."
                              （env 覆盖 = actual invocation model；无覆盖时用
                              fake config 的 deepseek-v4-flash@deepseek）
    AAF_TEST_AUDIT_SAVE_FAIL  1 → save_fallback_runtime 抛 OSError（audit 注入）
    FAKE_HERMES_MARKER        fake hermes chat 逐次 append 的调用证据（MODEL= 行）
"""
from __future__ import annotations

import os

from ai_agent_framework import adapters as adapters_mod
from ai_agent_framework import cost_guard as cost_guard_mod
from ai_agent_framework import fallback_runtime as fallback_runtime_mod
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
    """受控 Hermes 候选 fixture（test-only；main-scope QUALIFIED）。"""
    locality = (
        model_registry_mod.LOCALITY_LOCAL
        if cost_class == "LOCAL_FREE"
        else model_registry_mod.LOCALITY_REMOTE
    )
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
            evidence=(f"a5-free-fallback-fix001-fresh-runner-fixture-{model}",),
            observed_at="2026-09-03T00:00:00+08:00",
        ),
        evidence=(f"a5-free-fallback-fix001-fresh-runner-fixture-{model}",),
        notes=(
            "A5-FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner controlled "
            "fixture (test-only, not baseline)",
        ),
    )
    return {entry.key(): entry}


def _registry(mode: str) -> dict:
    if mode == "fb_success":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-fb", "custom", "LOCAL_FREE"))
        return reg
    if mode == "fb_paid_admission":
        # FIX-001：registry 标 FREE 的远程候选（A5 registry cost gate 放行），
        # A0 Paid Guard 按真实端点事实权威解析为 paid/unknown
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-free", "remote-api", "FREE"))
        return reg
    raise SystemExit(f"unknown AAF_TEST_REGISTRY_MODE: {mode!r}")


_mode = os.environ.get("AAF_TEST_REGISTRY_MODE", "baseline").strip()
if _mode != "baseline":
    model_registry_mod.baseline_registry = lambda: _registry(_mode)

# FIX-001 audit persistence failure 注入（test-only wrapper；生产代码零 hook）
if os.environ.get("AAF_TEST_AUDIT_SAVE_FAIL", "").strip() == "1":

    def _failing_save(output_dir, record):
        raise OSError(
            "FIX-001 simulated authoritative audit persistence failure "
            "(AAF_TEST_AUDIT_SAVE_FAIL)"
        )

    fallback_runtime_mod.save_fallback_runtime = _failing_save

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
