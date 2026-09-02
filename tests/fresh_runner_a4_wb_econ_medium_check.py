"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 — fresh-process check
（Fresh Runner N4，MEDIUM risk 扩展）。

在**全新 python 进程**中证明（与真实 runtime 的 full-runner 场景互补）：
1. **MEDIUM 真实 facts + 真实 registry**：真实 WorkBuddy 候选（T4）不满足
   MEDIUM selector floor T3 → 0 eligible → routing_applied=false /
   routed_model=None / reason=INSUFFICIENT_ELIGIBLE_CANDIDATES /
   fallback_used=false / invocation 保持 CodeBuddy Auto（Req 15：真实数据
   不被人为放宽/伪造）。
2. **MEDIUM 受控两可信候选 fixture**（明确标注 evidence injection，与真实
   facts 区分）：routing_applied=true / winner 确定性（med-free rank 0 权威
   免费 outranks med-discount rank 1）；env apply 后 run_agent 的**真实
   invocation args** 恰好一个 --model med-free、无 --effort；transport retry
   复用**同一 args**（绝不退回 Auto / 不换模型 / 无 retry escalation）。
3. **LOW 回归（Req 9/16G/16H）**：LOW 真实 facts → Auto
   （INSUFFICIENT_ECONOMIC_CANDIDATES，trustworthy=1）；LOW 受控两可信 →
   routed（winner = hy4-preview）。
4. **HIGH / CRITICAL / missing Risk → Auto**（RISK_OUTSIDE_ACTIVE_SLICE /
   RISK_UNAVAILABLE；即使受控 registry 可路由也只因 risk gate 阻断）。
5. validate fail-closed（fallback_used=True 拒绝 / Auto 不声称 routed_model /
   未生效决策 apply 拒绝）；env apply/restore 精确还原。

用法：python tests/fresh_runner_a4_wb_econ_medium_check.py
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
from ai_agent_framework import model_registry as mr  # noqa: E402
from ai_agent_framework import workbuddy_economics as we  # noqa: E402
from ai_agent_framework import workbuddy_routing as wr  # noqa: E402
from ai_agent_framework.risk_contract import (  # noqa: E402
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    ROLE_VALIDATOR,
)

NOW = datetime.fromisoformat("2026-09-02T03:30:00+08:00")
MEDIUM_WINNER = "med-free"
LOW_WINNER = "hy4-preview"

failures = 0


def check(label: str, cond: bool) -> None:
    global failures
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures += 1


def _medium_controlled_registry() -> dict[str, mr.RegistryEntry]:
    reg = mr.baseline_registry()
    for mid in ("med-free", "med-discount"):
        if mid not in reg:
            reg[mid] = mr.RegistryEntry(
                model=mid,
                provider=None,
                applicable_agents=("workbuddy",),
                capability_tier=mr.CAP_TIER_T3,
                cost_class=mr.COST_CLASS_UNKNOWN,
                locality=mr.LOCALITY_UNKNOWN,
                qualification=mr.RuntimeQualification(status=mr.QUAL_STATUS_QUALIFIED),
            )
    return reg


def _medium_controlled_facts() -> dict[str, we.EconomicFact]:
    base = we.baseline_economic_facts()
    if "med-free" not in base:
        base["med-free"] = we.EconomicFact(
            model_id="med-free", multiplier=0.0, multiplier_raw="x0.00",
            promotion_status=we.PROMO_STATUS_FREE, promotion_factor=0.0,
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
            source="controlled fixture (fresh-process check; test-only, NOT real probe evidence)",
        )
    if "med-discount" not in base:
        base["med-discount"] = we.EconomicFact(
            model_id="med-discount", multiplier=0.5, multiplier_raw="x0.5",
            promotion_status=we.PROMO_STATUS_DISCOUNT, promotion_factor=0.5,
            valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
            source="controlled fixture (fresh-process check; test-only, NOT real probe evidence)",
        )
    return base


def _low_two_trustworthy_facts() -> dict[str, we.EconomicFact]:
    base = we.baseline_economic_facts()
    base["deepseek-v4-flash"] = we.EconomicFact(
        model_id="deepseek-v4-flash", multiplier=0.17, multiplier_raw="x0.17",
        promotion_status=we.PROMO_STATUS_DISCOUNT, promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00", valid_until="2026-12-31T00:00:00+08:00",
        source="controlled fixture (fresh-process check; test-only, NOT real probe evidence)",
    )
    return base


# ---------------------------------------------------------------------------
# 1. MEDIUM 真实 facts + 真实 registry → Auto（capability floor T3）
# ---------------------------------------------------------------------------
rec = wr.decide_workbuddy_route(
    RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
    now=NOW, risk_source="task/planner provenance (fresh-process check)",
)
check("MEDIUM real routing_applied=False (0 eligible: T4 < MEDIUM floor T3)",
      rec["routing_applied"] is False)
check("MEDIUM real eligible empty", rec["eligible"] == [])
check("MEDIUM real routed_model=None (Auto preserved)", rec["routed_model"] is None)
check("MEDIUM real reason = INSUFFICIENT_ELIGIBLE_CANDIDATES",
      (rec["reason"] or "").startswith(wr.REASON_INSUFFICIENT_ELIGIBLE))
check("MEDIUM real fallback_used fixed False", rec["fallback_used"] is False)
check("MEDIUM real invocation stays CodeBuddy Auto", "CodeBuddy Auto" in rec["invocation"])
wr.validate_workbuddy_routing(rec)

# ---------------------------------------------------------------------------
# 2. MEDIUM 受控两可信候选 fixture → routed + 真实 argv 恰好一个 --model
# ---------------------------------------------------------------------------
rec_ctl = wr.decide_workbuddy_route(
    RISK_MEDIUM, ROLE_VALIDATOR, "workbuddy",
    _medium_controlled_registry(), facts=_medium_controlled_facts(),
    now=NOW, risk_source="controlled fixture (fresh-process check)",
)
check("MEDIUM controlled routing_applied=True", rec_ctl["routing_applied"] is True)
check("MEDIUM controlled winner deterministic = med-free (rank 0 free outranks rank 1)",
      rec_ctl["selected"] == MEDIUM_WINNER and rec_ctl["routed_model"] == MEDIUM_WINNER)
check("MEDIUM controlled economically_trustworthy == [med-free, med-discount]",
      rec_ctl["economically_trustworthy"] == ["med-free", "med-discount"])
check("MEDIUM controlled risk_class recorded as MEDIUM", rec_ctl["risk_class"] == RISK_MEDIUM)
check("MEDIUM controlled fallback_used fixed False", rec_ctl["fallback_used"] is False)
check("MEDIUM controlled reason = WORKBUDDY_ECONOMIC_ROUTE_APPLIED",
      (rec_ctl["reason"] or "").startswith(wr.REASON_APPLIED))
wr.validate_workbuddy_routing(rec_ctl)

# 2b. 受控 routed invocation args：恰好一个 --model、无 --effort；retry 复用同一 args
_real_require = adapters._require
_real_retry = adapters.run_workbuddy_with_retry
captured = {}


def _fake_require(cmd: str) -> str:
    return "C:/fake-bin/codebuddy.exe"


def _fake_retry(args, env, stdin_data, workspace):
    captured["attempts"] = captured.get("attempts", [])
    captured["attempts"].append(list(args))
    return "ok", {"attempt_count": 1, "retried": False, "outcome": "SUCCESS"}


adapters._require = _fake_require
adapters.run_workbuddy_with_retry = _fake_retry
saved_env = wr.apply_workbuddy_model_env(rec_ctl)
try:
    adapters.run_agent("workbuddy", "P", ROOT)
finally:
    wr.restore_workbuddy_model_env(saved_env)
adapters._require = _real_require
adapters.run_workbuddy_with_retry = _real_retry
args = captured["attempts"][0]
check("controlled invocation args == [-p --output-format text -y --model med-free]",
      args == ["C:/fake-bin/codebuddy.exe", "-p", "--output-format", "text", "-y",
               "--model", MEDIUM_WINNER])
check("exactly one --model in real args", args.count("--model") == 1)
check("no --effort in real args", "--effort" not in args)
check("retry reuses the SAME routed args (single attempt, no Auto/second model)",
      len(captured["attempts"]) == 1 and captured["attempts"][0] == args)
check("AAF_WORKBUDDY_MODEL restored after run", wr.ENV_WORKBUDDY_MODEL not in os.environ)

# ---------------------------------------------------------------------------
# 3. LOW 回归（Req 9 / 16G / 16H）
# ---------------------------------------------------------------------------
rec_low_real = wr.decide_workbuddy_route(
    RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
    now=NOW, risk_source="task/planner provenance (fresh-process check)",
)
check("LOW real facts routing_applied=False (only 1 trustworthy)",
      rec_low_real["routing_applied"] is False)
check("LOW real facts routed_model=None (Auto preserved)",
      rec_low_real["routed_model"] is None)
check("LOW real facts economically_trustworthy == 1 candidate",
      len(rec_low_real["economically_trustworthy"]) == 1)
check("LOW real facts reason = INSUFFICIENT_ECONOMIC_CANDIDATES",
      (rec_low_real["reason"] or "").startswith(wr.REASON_INSUFFICIENT_ECONOMIC))

rec_low_ctl = wr.decide_workbuddy_route(
    RISK_LOW, ROLE_VALIDATOR, "workbuddy", mr.baseline_registry(),
    facts=_low_two_trustworthy_facts(),
    now=NOW, risk_source="controlled fixture (fresh-process check)",
)
check("LOW controlled two-trustworthy routing_applied=True (unchanged)",
      rec_low_ctl["routing_applied"] is True)
check("LOW controlled winner deterministic = hy4-preview (unchanged)",
      rec_low_ctl["selected"] == LOW_WINNER and rec_low_ctl["routed_model"] == LOW_WINNER)
check("LOW controlled reason mentions explicit Risk=LOW (unchanged)",
      (rec_low_ctl["reason"] or "").startswith(wr.REASON_APPLIED)
      and "explicit Risk=LOW" in rec_low_ctl["reason"])

# ---------------------------------------------------------------------------
# 4. HIGH / CRITICAL / missing Risk → Auto（即使受控 registry 可路由）
# ---------------------------------------------------------------------------
for risk, token in ((RISK_HIGH, wr.REASON_RISK_OUTSIDE_SLICE),
                    (RISK_CRITICAL, wr.REASON_RISK_OUTSIDE_SLICE)):
    rec_out = wr.decide_workbuddy_route(
        risk, ROLE_VALIDATOR, "workbuddy",
        _medium_controlled_registry(), facts=_medium_controlled_facts(),
        now=NOW, risk_source="t",
    )
    check(f"{risk} -> Auto (RISK_OUTSIDE_ACTIVE_SLICE) even with routeable candidates",
          rec_out["routing_applied"] is False
          and rec_out["routed_model"] is None
          and (rec_out["reason"] or "").startswith(token))

rec_missing = wr.decide_workbuddy_route(
    None, ROLE_VALIDATOR, "workbuddy",
    _medium_controlled_registry(), facts=_medium_controlled_facts(),
    now=NOW,
)
check("missing Risk -> Auto (RISK_UNAVAILABLE) even with routeable candidates",
      rec_missing["routing_applied"] is False
      and rec_missing["routed_model"] is None
      and (rec_missing["reason"] or "").startswith(wr.REASON_RISK_UNAVAILABLE))

# ---------------------------------------------------------------------------
# 5. validate / env fail-closed 语义
# ---------------------------------------------------------------------------
bad_fallback = dict(rec_ctl)
bad_fallback["fallback_used"] = True
try:
    wr.validate_workbuddy_routing(bad_fallback)
    check("validate rejects fallback_used=True", False)
except ValueError:
    check("validate rejects fallback_used=True", True)

bad_auto = dict(rec)
bad_auto["routed_model"] = "made-up-model"
try:
    wr.validate_workbuddy_routing(bad_auto)
    check("validate rejects Auto record with routed_model claim", False)
except ValueError:
    check("validate rejects Auto record with routed_model claim", True)

try:
    wr.apply_workbuddy_model_env(rec)  # 未生效决策不得触碰 env
    check("apply on non-applied record rejected", False)
except ValueError:
    check("apply on non-applied record rejected", True)

print(f"fresh-process MEDIUM routing check: failures={failures}")
sys.exit(0 if failures == 0 else 1)
