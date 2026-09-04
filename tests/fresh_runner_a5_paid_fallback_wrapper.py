"""AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001 fresh-runner wrapper.

与既有 fresh-runner wrapper 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / fallback_runtime.py /
fallback_paid_gate.py / cost_guard.py 等不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - pf_paid_only：aaa-orig（LOCAL_FREE 本地端点）+ zzz-paid（registry
     cost_class=PAID 远程 API 候选——A5 registry FREE gate 排除 → paid
     fallback 场景：无合格 FREE/LOCAL_FREE fallback + 合格 paid candidate；
     A0 Paid Guard 按真实端点事实权威解析 PAID_OR_UNKNOWN；exact
     AAF_COST_AUTH → gate AUTHORIZED → **恰一次 paid fallback invocation**；
     absent/mismatch → gate BLOCKED → 零 invocation）。
   - pf_free_intact：aaa-orig + zzz-fb（双 LOCAL_FREE——FREE fallback 优先
     于 paid escalation 的行为保持回归场景）。
   - pf_original_only：只有 aaa-orig（无其他合格候选）——exact auth 也不能
     让授权静默转成执行（无合格候选 → gate 不运行 → 零 invocation）。
   pf_* 都是 test-only controlled fixture，绝不进入 A1 baseline。
3. paid runtime audit 持久化故障注入（Requirement 18：audit closure 失败
   拒绝 paid 输出）：
   - AAF_TEST_PAID_SAVE_FAULT=runtime_error|unicode_error → patch
     fallback_runtime.save_paid_fallback_runtime 抛对应异常（paid invocation
     已真实发生后权威 paid audit 无法闭合 → attempted=true / used=false /
     输出不被接受 / audit_closure_error surface）。
4. 进程结束前（try/finally，SystemExit 后仍执行）向 stdout 打印
   AAF_ENV_PROBE|... 三行——same-process env 还原证明：paid fallback overlay /
   A3 routing 若泄漏到 runner 结束，probe 会显示泄漏值；全部还原 = -none-。

用法：
    python tests/fresh_runner_a5_paid_fallback_wrapper.py <TASK.md> \
        --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN            fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE       baseline | pf_paid_only | pf_free_intact |
                                 pf_original_only
    AAF_TEST_FAIL_MODELS         fake hermes chat 的失败模型列表 "model@provider;..."
                                 （env 覆盖 = actual invocation model；无覆盖时用
                                 fake config 的 deepseek-v4-flash@deepseek）
    AAF_TEST_PAID_SAVE_FAULT     runtime_error | unicode_error → paid runtime
                                 audit save 抛对应异常
    FAKE_HERMES_MARKER           fake hermes chat 逐次 append 的调用证据（MODEL= 行）
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
            evidence=(f"a5-paid-fallback-runtime-fresh-runner-fixture-{model}",),
            observed_at="2026-09-05T00:30:00+08:00",
        ),
        evidence=(f"a5-paid-fallback-runtime-fresh-runner-fixture-{model}",),
        notes=(
            "A5-PAID-FALLBACK-RUNTIME-001 fresh-runner controlled fixture "
            "(test-only, not baseline)",
        ),
    )
    return {entry.key(): entry}


def _registry(mode: str) -> dict:
    if mode == "pf_paid_only":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-paid", "remote-api", "PAID"))
        return reg
    if mode == "pf_free_intact":
        reg = _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
        reg.update(_controlled_entry("zzz-fb", "custom", "LOCAL_FREE"))
        return reg
    if mode == "pf_original_only":
        return _controlled_entry("aaa-orig", "custom", "LOCAL_FREE")
    raise SystemExit(f"unknown AAF_TEST_REGISTRY_MODE: {mode!r}")


_mode = os.environ.get("AAF_TEST_REGISTRY_MODE", "baseline").strip()
if _mode != "baseline":
    model_registry_mod.baseline_registry = lambda: _registry(_mode)

# ---- paid runtime audit 持久化故障注入（test-only wrapper；生产零 hook）----
_paid_save_fault = os.environ.get("AAF_TEST_PAID_SAVE_FAULT", "").strip()
if _paid_save_fault in ("runtime_error", "unicode_error"):

    def _failing_paid_save(output_dir, record):
        if _paid_save_fault == "unicode_error":
            raise UnicodeError(
                "A5 paid fallback simulated authoritative paid runtime audit "
                "persistence UnicodeError (AAF_TEST_PAID_SAVE_FAULT)"
            )
        raise RuntimeError(
            "A5 paid fallback simulated authoritative paid runtime audit "
            "persistence RuntimeError (AAF_TEST_PAID_SAVE_FAULT)"
        )

    fallback_runtime_mod.save_paid_fallback_runtime = _failing_paid_save

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    try:
        main()
    finally:
        # same-process env 还原证明：runner 结束时 paid fallback overlay / A3
        # routing 覆盖必须全部还原（probe 值 = -none-）；泄漏会在此显形。
        for var in (
            cost_guard_mod.ENV_MODEL,
            cost_guard_mod.ENV_PROVIDER,
            cost_guard_mod.ENV_BASE_URL,
        ):
            value = os.environ.get(var)
            print(f"AAF_ENV_PROBE|{var}={value if value is not None else '-none-'}")
