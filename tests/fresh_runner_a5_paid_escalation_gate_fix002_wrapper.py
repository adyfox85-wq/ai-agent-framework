"""AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002 fresh-runner wrapper.

与既有 fresh-runner wrapper 同一技术：在导入 runner 之前完成模块级 patch，
只影响 fresh-process 验证，生产代码零改动（runner.py / fallback_runtime.py /
fallback_paid_gate.py / cost_guard.py 等不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_REGISTRY_MODE 注入 model_registry.baseline_registry：
   - pg_paid_only：aaa-orig（LOCAL_FREE 本地端点）+ zzz-paid（registry
     cost_class=PAID 远程 API 候选——paid escalation Cost Gate 场景）。
   - pg_free_intact：aaa-orig + zzz-fb（双 LOCAL_FREE——FREE fallback 行为
     保持回归场景）。
3. AAF_TEST_GUARD_MODE（FIX-002 fresh-runner closure，Requirement 11/12——
   本任务改变 self-hosting paid authorization **scope** 语义）：
   - real（默认）：真实 A0 Paid Guard（cost_guard.evaluate，fake bin 支撑
     resolve；exact auth → ALLOWED_AUTHORIZED_PAID / absent/mismatch →
     BLOCKED——A5-003 既有授权语义保持场景）。
   - guard_wrong_task_scope：cost_guard_mod.evaluate 被 wrapper 级替换为
     返回**别的 task** 的 ALLOWED_AUTHORIZED_PAID record（decision + flags 全
     True + model/provider == zzz-paid/remote-api 但 required_scope 编码错误
     task——此前 interpret_guard 只校验 model/provider 与 required_scope
     非空 → 会错误 AUTHORIZED；FIX-002 后必须 FAIL_CLOSED「scope mismatch」+
     自洽 record + 落盘 + raw 证据在 source_guard_record 可观察）。
   - guard_wrong_stage_scope：同型，required_scope 编码错误 stage → FAIL_CLOSED。
   - guard_exact_scope：脚本化 exact canonical scope（model/provider +
     required_scope 全部 == 当前 task/stage 的 canonical expected scope）→
     AUTHORIZED（canonical exact scope 仍被授权）但零 paid invocation。
   pg_* / guard_* 都是 test-only controlled fixture，绝不进入 A1 baseline。
4. 进程结束前（try/finally，SystemExit 后仍执行）向 stdout 打印
   AAF_ENV_PROBE|... 三行——same-process env 还原证明。

用法：
    python tests/fresh_runner_a5_paid_escalation_gate_fix002_wrapper.py <TASK.md> \
        --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN            fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_REGISTRY_MODE       pg_paid_only | pg_free_intact | baseline
    AAF_TEST_GUARD_MODE          real | guard_wrong_task_scope |
                                 guard_wrong_stage_scope | guard_exact_scope
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
            evidence=(f"a5-paid-escalation-gate-fix002-fresh-fixture-{model}",),
            observed_at="2026-09-03T20:00:00+08:00",
        ),
        evidence=(f"a5-paid-escalation-gate-fix002-fresh-fixture-{model}",),
        notes=(
            "A5-PAID-ESCALATION-GATE-001-FIX-002 fresh-runner controlled "
            "fixture (test-only, not baseline)",
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


# ---- FIX-002 guard-mode patch（wrapper 级；test-only；生产代码零改动）----
_guard_mode = os.environ.get("AAF_TEST_GUARD_MODE", "real").strip()
_real_evaluate = cost_guard_mod.evaluate

# 脚本化 wrong-scope 注入用的「别的 task / 别的 stage」（必须是确定值——与 runner
# 当前 task_id / stage=hermes 必然不同 → canonical expected scope 失配）
_WRONG_TASK_ID = "AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002-WRONG-TASK"
_WRONG_STAGE = "validator"


def _scripted_scope_guard(task_id, stage, state_dir=None) -> dict:
    """只替换 **gate-time**（paid candidate env overlay = zzz-paid）的 A0
    求值，注入脚本化 wrong/exact scope record（真实进程内证明 interpret_guard
    exact required_scope 校验，Requirement 11/12）。

    runner 的 original-stage admission guard（对象 = aaa-orig / configured
    模型，env ≠ zzz-paid）必须走真实 A0（LOCAL_FREE → ALLOWED_FREE 等既有
    语义）——否则注入的 record 会在 original invocation 前就阻断 stage，无法
    到达 Cost Gate（FIX-001 fresh-runner 实测根因，同型设计保持）。"""
    model = (os.environ.get(cost_guard_mod.ENV_MODEL) or "").strip()
    if model != "zzz-paid":
        return _real_evaluate(task_id, stage, state_dir=state_dir)
    if _guard_mode == "guard_wrong_task_scope":
        scope = cost_guard_mod.scope_string(
            _WRONG_TASK_ID, stage, "zzz-paid", "remote-api"
        )
        note = "FIX-002 scripted A0: exact-scope for a DIFFERENT task"
    elif _guard_mode == "guard_wrong_stage_scope":
        scope = cost_guard_mod.scope_string(
            task_id, _WRONG_STAGE, "zzz-paid", "remote-api"
        )
        note = "FIX-002 scripted A0: exact-scope for a DIFFERENT stage"
    elif _guard_mode == "guard_exact_scope":
        scope = cost_guard_mod.scope_string(
            task_id, stage, "zzz-paid", "remote-api"
        )
        note = "FIX-002 scripted A0: canonical exact scope for this task/stage"
    else:
        raise SystemExit(f"unknown AAF_TEST_GUARD_MODE: {_guard_mode!r}")
    return {
        "decision": cost_guard_mod.DECISION_ALLOWED_AUTHORIZED_PAID,
        "model": "zzz-paid",
        "provider": "remote-api",
        "authorization_present": True,
        "authorization_matched": True,
        "authorization_consumed": True,
        "cost_class": cost_guard_mod.COST_PAID_OR_UNKNOWN,
        "required_scope": scope,
        "notes": [note],
    }


if _guard_mode != "real":
    cost_guard_mod.evaluate = _scripted_scope_guard

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
