"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 — fresh-process check
（Fresh Runner C，enforce two-candidate economic routing gate）。

在**全新 python 进程**中证明：
1. **真实 baseline economic facts**（facts=None → baseline_economic_facts()）下
   LOW 决策：经济过滤后只剩 hy4-preview 一个 trustworthy candidate
   （deepseek-v4-flash freshness UNKNOWN 被排除）→ routing_applied=false /
   routed_model=None / reason = INSUFFICIENT_ECONOMIC_CANDIDATES / fallback_used
   =false（FIX-001：真实 facts 不人为伪造成可路由）。
2. **受控两可信候选 fixture**（明确标注 evidence injection，与真实 facts
   区分）：两个 eligible 都有 trustworthy economics → routing_applied=true /
   winner 确定性（hy4-preview rank 0 outranks deepseek-v4-flash rank 1）；
   apply env 后 run_agent 的**真实 invocation args** 恰好一个 --model <winner>、
   无 --effort；transport retry 复用**同一 args**（绝不退回 Auto / 不换模型 /
   无 retry escalation）。
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
from ai_agent_framework import workbuddy_economics as we  # noqa: E402
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


# ---------------------------------------------------------------------------
# 1. 真实 baseline facts：1 个可信候选 → Auto（FIX-001 核心；fresh-process 证明）
# ---------------------------------------------------------------------------
rec = wr.decide_workbuddy_route(
    RISK_LOW, ROLE_VALIDATOR, "workbuddy", baseline_registry(),
    now=NOW, risk_source="task/planner provenance (fresh-process check)",
)
check("LOW real facts routing_applied=False (only 1 trustworthy)", rec["routing_applied"] is False)
check("LOW real facts routed_model=None (Auto preserved)", rec["routed_model"] is None)
check("LOW real facts economically_trustworthy == 1 candidate", len(rec["economically_trustworthy"]) == 1)
check("LOW real facts reason = INSUFFICIENT_ECONOMIC_CANDIDATES",
      (rec["reason"] or "").startswith(wr.REASON_INSUFFICIENT_ECONOMIC))
check("LOW real facts fallback_used fixed False", rec["fallback_used"] is False)
check("LOW real facts invocation stays CodeBuddy Auto", "CodeBuddy Auto" in rec["invocation"])

# ---------------------------------------------------------------------------
# 2. 受控两可信候选 fixture（Req 14：evidence injection，与真实 N1 明确区分）：
#    routing_applied=true + winner 确定性 + 真实 invocation argv 恰好一个 --model
# ---------------------------------------------------------------------------
base_facts = we.baseline_economic_facts()
controlled_facts = dict(base_facts)
controlled_facts["deepseek-v4-flash"] = we.EconomicFact(
    model_id="deepseek-v4-flash",
    multiplier=0.17,
    multiplier_raw="x0.17",
    promotion_status=we.PROMO_STATUS_DISCOUNT,
    promotion_factor=0.5,
    valid_from="2026-01-01T00:00:00+08:00",
    valid_until="2026-12-31T00:00:00+08:00",
    source="controlled fixture (fresh-process check; test-only, NOT real probe evidence)",
)
rec_ctl = wr.decide_workbuddy_route(
    RISK_LOW, ROLE_VALIDATOR, "workbuddy", baseline_registry(),
    facts=controlled_facts,
    now=NOW, risk_source="controlled fixture (fresh-process check)",
)
check("controlled two-trustworthy routing_applied=True",
      rec_ctl["routing_applied"] is True)
check("controlled winner deterministic = hy4-preview (rank 0 free outranks rank 1 discount)",
      rec_ctl["selected"] == WINNER and rec_ctl["routed_model"] == WINNER)
check("controlled economically_trustworthy == [hy4-preview, deepseek-v4-flash]",
      rec_ctl["economically_trustworthy"] == [WINNER, "deepseek-v4-flash"])
check("controlled fallback_used fixed False", rec_ctl["fallback_used"] is False)
check("controlled reason = WORKBUDDY_ECONOMIC_ROUTE_APPLIED",
      (rec_ctl["reason"] or "").startswith(wr.REASON_APPLIED))
wr.validate_workbuddy_routing(rec_ctl)
bad_fallback = dict(rec_ctl)
bad_fallback["fallback_used"] = True
try:
    wr.validate_workbuddy_routing(bad_fallback)
    check("validate rejects fallback_used=True", False)
except ValueError:
    check("validate rejects fallback_used=True", True)

# 2b. 受控 routed invocation args：恰好一个 --model、无 --effort；retry 复用同一 args
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

# ---------------------------------------------------------------------------
# 3. Auto 保持时不得声称 routed_model；未生效决策不得触碰 env
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 4. 无隐藏 Auto fallback：retry 层只消费构建一次的 args（无第二套 invocation 构造）
# ---------------------------------------------------------------------------
import inspect  # noqa: E402

retry_src = inspect.getsource(adapters.run_workbuddy_with_retry)
check("retry entry takes prebuilt args (no model re-resolution)",
      "args" in inspect.signature(adapters.run_workbuddy_with_retry).parameters
      and "_workbuddy_invocation" not in retry_src)

print(f"fresh-process FIX-001 check (real-facts Auto + controlled routed + no-silent-fallback): failures={failures}")
sys.exit(failures)
