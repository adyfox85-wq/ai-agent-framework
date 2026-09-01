"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 — fresh-process no-silent-fallback
check（Fresh Runner C）。

在**全新 python 进程**中证明：
1. active economic routing 决策记录 fallback_used 恒为 False（fixed semantic，
   validate fail-closed：任何 True 违规）。
2. routed invocation 的 transport retry 复用**同一 args**（含 --model）——
   绝不退回 CodeBuddy Auto / 不换模型 / 不升级付费层级（无 retry escalation）；
   run_agent 的 env 覆盖 → 真实 retry args 精确含恰好一个 --model 且无 --effort。
3. Auto 保持时 artifact 不得声称 routed_model（validate fail-closed）；未生效
   决策不得触碰 env（apply fail-closed）。
4. 不存在任何隐藏的 Auto fallback 分支：retry 层调用点（adapters.run_agent →
   run_workbuddy_with_retry）只传构建一次的 args。

用法：python tests/fresh_runner_a4_wb_economic_routing_check.py
退出码 0 = 全部通过。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import adapters  # noqa: E402
from ai_agent_framework import workbuddy_routing as wr  # noqa: E402
from ai_agent_framework.model_registry import baseline_registry  # noqa: E402
from ai_agent_framework.risk_contract import RISK_HIGH, RISK_LOW, ROLE_VALIDATOR  # noqa: E402

NOW = datetime.fromisoformat("2026-09-02T03:30:00+08:00")
WINNER = "hy4-preview"

failures = 0


def check(label: str, cond: bool) -> None:
    global failures
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures += 1


# 1. fallback_used 恒 False（fixed semantic + validate fail-closed）
rec = wr.decide_workbuddy_route(
    RISK_LOW, ROLE_VALIDATOR, "workbuddy", baseline_registry(),
    now=NOW, risk_source="task/planner provenance (fresh-process check)",
)
check("LOW record routing_applied=True selected=hy4-preview", rec["routing_applied"] is True and rec["selected"] == WINNER)
check("fallback_used fixed False (LOW)", rec["fallback_used"] is False)
bad_fallback = dict(rec)
bad_fallback["fallback_used"] = True
try:
    wr.validate_workbuddy_routing(bad_fallback)
    check("validate rejects fallback_used=True", False)
except ValueError:
    check("validate rejects fallback_used=True", True)

# 2. routed invocation args：恰好一个 --model、无 --effort；retry 复用同一 args
_require = adapters._require
_retry = adapters.run_workbuddy_with_retry
captured = {}


def _fake_require(cmd: str) -> str:
    return "C:/fake-bin/codebuddy.exe"


def _fake_retry(args, env, stdin_data, workspace):
    captured["attempts"] = captured.get("attempts", [])
    captured["attempts"].append(list(args))
    # 每次 attempt 复用同一 args（transport retry 语义：绝不换模型/退回 Auto）
    return "ok", {"attempt_count": len(captured["attempts"]), "retried": len(captured["attempts"]) > 1, "outcome": "SUCCESS"}


adapters._require = _fake_require
adapters.run_workbuddy_with_retry = _fake_retry
os.environ[wr.ENV_WORKBUDDY_MODEL] = WINNER
try:
    adapters.run_agent("workbuddy", "PROMPT", ROOT)
finally:
    adapters._require = _require
    adapters.run_workbuddy_with_retry = _retry
    os.environ.pop(wr.ENV_WORKBUDDY_MODEL, None)

attempts = captured.get("attempts", [])
check("run_agent invocation args exactly one --model", bool(attempts) and attempts[0].count("--model") == 1)
check("run_agent invocation args contain --model winner at tail",
      bool(attempts) and attempts[0][-2:] == ["--model", WINNER])
check("no --effort in invocation args", bool(attempts) and "--effort" not in attempts[0])
check("no provider override in invocation args", bool(attempts) and "--provider" not in attempts[0])
check("retry attempts reuse the SAME routed args (no Auto fallback)",
      len(attempts) >= 1 and all(a == attempts[0] for a in attempts))

# 3. Auto 保持时不得声称 routed_model；未生效决策不得触碰 env
rec_high = wr.decide_workbuddy_route(
    RISK_HIGH, ROLE_VALIDATOR, "workbuddy", baseline_registry(),
    now=NOW, risk_source="t",
)
check("HIGH routing_applied=False", rec_high["routing_applied"] is False)
check("HIGH routed_model=None (no claim)", rec_high["routed_model"] is None)
check("HIGH fallback_used=False", rec_high["fallback_used"] is False)
bad_claim = dict(rec_high)
bad_claim["routed_model"] = WINNER
try:
    wr.validate_workbuddy_routing(bad_claim)
    check("validate rejects routed_model claim when Auto", False)
except ValueError:
    check("validate rejects routed_model claim when Auto", True)
try:
    wr.apply_workbuddy_model_env(rec_high)
    check("apply rejects non-applied record", False)
except ValueError:
    check("apply rejects non-applied record", True)

# 4. 无隐藏 Auto fallback：retry 层只消费构建一次的 args（无第二套 invocation 构造）
import inspect  # noqa: E402

retry_src = inspect.getsource(adapters.run_workbuddy_with_retry)
check("retry entry takes prebuilt args (no model re-resolution)",
      "args" in inspect.signature(adapters.run_workbuddy_with_retry).parameters
      and "_workbuddy_invocation" not in retry_src)

print(f"fresh-process no-silent-fallback check: failures={failures}")
sys.exit(failures)
