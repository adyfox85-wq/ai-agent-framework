"""AAF-v0.5-A5-PAID-ESCALATION-GATE-001 fresh-runner wrapper.

与既有 fresh-runner wrapper 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / fallback_runtime.py /
fallback_paid_gate.py / cost_guard.py 等不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - pg_paid_only：aaa-orig（LOCAL_FREE 本地端点）+ zzz-paid（registry
     cost_class=PAID 远程 API 候选——A5 registry FREE gate 排除 → paid
     escalation Cost Gate 场景：无合格 FREE fallback、存在合格 paid candidate；
     A0 Paid Guard 按真实端点事实权威解析 PAID_OR_UNKNOWN，exact AAF_COST_AUTH
     匹配 → gate AUTHORIZED；absent/mismatch → gate BLOCKED）。
   - pg_free_intact：aaa-orig + zzz-fb（双 LOCAL_FREE——A5-002 FREE fallback
     行为保持回归场景）。
   pg_* 都是 test-only controlled fixture，绝不进入 A1 baseline。
3. 进程结束前（try/finally，SystemExit 后仍执行）向 stdout 打印
   AAF_ENV_PROBE|... 三行——same-process env 还原证明。

用法：
    python tests/fresh_runner_a5_paid_escalation_gate_wrapper.py <TASK.md> \
        --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN            fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE       pg_paid_only | pg_free_intact | baseline
    AAF_TEST_FAIL_MODELS         fake hermes chat 的失败模型列表 "model@provider;..."
    FAKE_HERMES_MARKER           fake hermes chat 逐次 append 的调用证据（MODEL= 行）
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
            evidence=(f"a5-paid-escalation-gate-fresh-runner-fixture-{model}",),
            observed_at="2026-09-03T01:00:00+08:00",
        ),
        evidence=(f"a5-paid-escalation-gate-fresh-runner-fixture-{model}",),
        notes=(
            "A5-PAID-ESCALATION-GATE-001 fresh-runner controlled fixture "
            "(test-only, not baseline)",
        ),
    )
    return {entry.key(): entry}


def _registry(mode: str) -> dict:
    if mode == "pg_paid_only":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-paid", "remote-api", "PAID"))
        return reg
    if mode == "pg_free_intact":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-fb", "custom", "LOCAL_FREE"))
        return reg
    raise SystemExit(f"unknown AAF_TEST_REGISTRY_MODE: {mode!r}")


_mode = os.environ.get("AAF_TEST_REGISTRY_MODE", "baseline").strip()
if _mode != "baseline":
    model_registry_mod.baseline_registry = lambda: _registry(_mode)

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    try:
        main()
    finally:
        # same-process env 还原证明：runner 结束时 fallback overlay / A3
        # routing 覆盖必须全部还原（probe 值 = -none-）；泄漏会在此显形。
        for var in (
            cost_guard_mod.ENV_MODEL,
            cost_guard_mod.ENV_PROVIDER,
            cost_guard_mod.ENV_BASE_URL,
        ):
            value = os.environ.get(var)
            print(f"AAF_ENV_PROBE|{var}={value if value is not None else '-none-'}")
