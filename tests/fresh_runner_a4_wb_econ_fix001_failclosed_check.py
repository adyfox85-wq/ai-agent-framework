"""AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001 — fresh-process fail-closed check.

Run by fresh_runner_a4_wb_econ_fix001_validation.py as a FRESH python process
(N+1 discipline): proves the tightened economic authority semantics (FIX-001)
- malformed / incomplete / contradictory economic facts FAIL CLOSED
  (never authoritative cheap/free, never enter the known economic ordering),
- the tightened gates did not break the valid baseline facts
  (hy3/hy4-preview still FRESH + authoritative free at observed_at),
- production WorkBuddy invocation still exact CodeBuddy Auto
  ([-p --output-format text -y], no --model/--effort),
- routing authority unchanged (LOW workbuddy selector still only
  deepseek-v4-flash; economics still not imported by routing code).

Checks (exit 0 = all pass):
1. FRESH discount + multiplier=None -> NOT authoritative cheap; rank
   RANK_UNKNOWN_OR_STALE (Codex blocking finding #1 closed: no known-cheap rank).
2. FRESH discount + promotion_factor=None -> NOT authoritative; rank 2.
3. FRESH free + multiplier=0.0 + promotion_factor=0.0 -> authoritative cheap
   (rank 0) — valid baseline semantics kept.
4. FRESH free + multiplier=0.0 + promotion_factor=1.0 -> NOT authoritative
   (Codex blocking finding #2 closed: authoritative free requires factor 0.0).
5. FRESH free + multiplier>0 / free + nonzero factor / discount internal
   contradictions (factor=0.0, factor=1.0, multiplier=0.0) -> NOT authoritative;
   rank 2.
6. STALE / UNKNOWN (complete or incomplete fields) -> never authoritative.
7. multiplier_raw that cannot explain a set multiplier -> ValueError at
   construction (no invented multipliers).
8. Baseline facts: all 15 candidates present; every promoted fact consistent;
   hy3/hy4-preview authoritative cheap at observed_at; deepseek-v4-flash NOT.
9. Production invocation exact Auto; selector LOW still deepseek-v4-flash only;
   routing modules do not import workbuddy_economics.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import adapters  # noqa: E402
from ai_agent_framework import risk_contract as rc  # noqa: E402
from ai_agent_framework.model_registry import (  # noqa: E402
    baseline_registry,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (  # noqa: E402
    EXCL_CAPABILITY_INSUFFICIENT,
    select_shadow_candidate,
)
from ai_agent_framework.workbuddy_economics import (  # noqa: E402
    ECON_FRESH,
    PROMO_STATUS_DISCOUNT,
    PROMO_STATUS_FREE,
    RANK_AUTHORITATIVE_CHEAP,
    RANK_UNKNOWN_OR_STALE,
    EconomicFact,
    baseline_economic_facts,
    cheapness_rank,
    economic_fields_consistent,
    is_authoritative_cheap,
)

NOW = datetime.fromisoformat("2026-09-02T12:00:00+08:00")
FRESH_WINDOW = dict(
    valid_from="2026-08-01T00:00:00+08:00",
    valid_until="2026-10-01T00:00:00+08:00",
)
STALE_WINDOW = dict(
    valid_from="2026-07-01T00:00:00+08:00",
    valid_until="2026-08-01T00:00:00+08:00",
)


def _fact(**kw):
    base = dict(model_id="m", source="EVID")
    base.update(kw)
    return EconomicFact(**base)


def _fresh_discount(**kw):
    base = dict(
        multiplier=0.79,
        promotion_status=PROMO_STATUS_DISCOUNT,
        promotion_factor=0.5,
        **FRESH_WINDOW,
    )
    base.update(kw)
    return _fact(**base)


def _fresh_free(**kw):
    base = dict(
        multiplier=0.0,
        promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0,
        **FRESH_WINDOW,
    )
    base.update(kw)
    return _fact(**base)


def main() -> int:
    failures: list[str] = []

    # ---- 1/2. incomplete FRESH discount fails closed (blocking finding #1) ----
    f = _fresh_discount(multiplier=None, multiplier_raw=None)
    if economic_fields_consistent(f) or is_authoritative_cheap(f, NOW):
        failures.append("multiplier=None FRESH discount became authoritative cheap")
    if cheapness_rank(f, NOW) != RANK_UNKNOWN_OR_STALE:
        failures.append(
            f"multiplier=None FRESH discount got known-cheap rank {cheapness_rank(f, NOW)}"
        )
    f = _fresh_discount(promotion_factor=None)
    if economic_fields_consistent(f) or is_authoritative_cheap(f, NOW):
        failures.append("promotion_factor=None FRESH discount became authoritative")
    if cheapness_rank(f, NOW) != RANK_UNKNOWN_OR_STALE:
        failures.append("promotion_factor=None FRESH discount got known-cheap rank")

    # ---- 3. valid zero-zero free still authoritative ----
    f = _fresh_free()
    if not is_authoritative_cheap(f, NOW):
        failures.append("valid FRESH free (0.0/0.0) lost authoritative cheap status")
    if cheapness_rank(f, NOW) != RANK_AUTHORITATIVE_CHEAP:
        failures.append("valid FRESH free lost rank 0")

    # ---- 4/5. free + nonzero factor / nonzero multiplier fail closed (finding #2) ----
    for bad in (
        _fresh_free(promotion_factor=1.0),
        _fresh_free(promotion_factor=0.5),
        _fresh_free(multiplier=0.17),
        _fresh_free(multiplier=0.17, promotion_factor=0.0),
        _fresh_free(multiplier=0.17, promotion_factor=0.5),
        _fresh_free(multiplier=None),
        _fresh_free(promotion_factor=None),
    ):
        if is_authoritative_cheap(bad, NOW):
            failures.append(f"fail-open authoritative cheap: {bad!r}")
        if cheapness_rank(bad, NOW) != RANK_UNKNOWN_OR_STALE:
            failures.append(f"contradictory/incomplete free entered known ordering: {bad!r}")

    # ---- 5b. discount internal contradictions fail closed ----
    for bad in (
        _fresh_discount(multiplier=0.0),
        _fresh_discount(promotion_factor=0.0),
        _fresh_discount(promotion_factor=1.0),
    ):
        if economic_fields_consistent(bad) or is_authoritative_cheap(bad, NOW):
            failures.append(f"discount contradiction fail-open: {bad!r}")
        if cheapness_rank(bad, NOW) != RANK_UNKNOWN_OR_STALE:
            failures.append(f"discount contradiction entered known ordering: {bad!r}")

    # ---- 6. STALE / UNKNOWN never authoritative ----
    stale = _fact(
        multiplier=0.0, promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0, **STALE_WINDOW,
    )
    unknown = _fact(
        multiplier=0.0, promotion_status=PROMO_STATUS_FREE,
        promotion_factor=0.0, valid_from=None, valid_until=None,
    )
    for f in (stale, unknown):
        if is_authoritative_cheap(f, NOW):
            failures.append("STALE/UNKNOWN became authoritative cheap")
        if cheapness_rank(f, NOW) != RANK_UNKNOWN_OR_STALE:
            failures.append("STALE/UNKNOWN outranked unknown bucket")

    # ---- 7. raw must explain value ----
    for bad in (
        dict(multiplier=0.5, multiplier_raw="x0.17"),
        dict(multiplier=0.5, multiplier_raw="garbage"),
        dict(multiplier=0.5, multiplier_raw="0x"),
    ):
        try:
            _fact(**bad)
            failures.append(f"unexplained multiplier_raw accepted: {bad!r}")
        except ValueError:
            pass

    # ---- 8. baseline unchanged and still valid ----
    facts = baseline_economic_facts()
    if len(facts) != 15:
        failures.append(f"baseline fact count changed: {len(facts)}")
    for mid, fact in facts.items():
        if fact.promotion_status is not None and not economic_fields_consistent(fact):
            failures.append(f"{mid}: baseline promoted fact inconsistent")
    hy3, hy4 = facts["hy3"], facts["hy4-preview"]
    if not is_authoritative_cheap(hy3, NOW) or not is_authoritative_cheap(hy4, NOW):
        failures.append("hy3/hy4-preview lost authoritative cheap at NOW")
    if is_authoritative_cheap(facts["deepseek-v4-flash"], NOW):
        failures.append("deepseek-v4-flash became authoritative cheap")

    # ---- 9. invocation / selector / no-import unchanged ----
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", {})
    if len(args) < 1 or args[1:] != ["-p", "--output-format", "text", "-y"]:
        failures.append(f"production invocation args changed: {args!r}")
    if "--model" in args or "--effort" in args or "-m" in args:
        failures.append(f"economics auto-added a model/effort flag: {args!r}")
    reg = baseline_registry()
    dec = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    if dec.eligible != ("deepseek-v4-flash",) or dec.selected != "deepseek-v4-flash":
        failures.append(f"LOW workbuddy selector changed: {dec.eligible}")
    reasons = {rec.candidate: rec.reason for rec in dec.excluded}
    for mid in ("hy3", "hy4-preview"):
        if reasons.get(mid) != EXCL_CAPABILITY_INSUFFICIENT:
            failures.append(f"{mid}: expected CAPABILITY_INSUFFICIENT despite FRESH FREE fact")
    if is_usable_candidate(reg["agent:workbuddy"]):
        failures.append("agent:workbuddy Auto anchor became usable")
    for mod_name in (
        "ai_agent_framework.adapters",
        "ai_agent_framework.shadow_routing",
        "ai_agent_framework.model_registry",
        "ai_agent_framework.runner",
        "ai_agent_framework.active_routing",
        "ai_agent_framework.cost_guard",
    ):
        mod = importlib.import_module(mod_name)
        if "workbuddy_economics" in getattr(mod, "__dict__", {}):
            failures.append(f"{mod_name} imports workbuddy_economics (consumer appeared)")

    for msg in failures:
        print("FAIL:", msg)
    print(f"fail-closed fresh-process check: {'PASS' if not failures else 'FAIL'} ({len(failures)} failure(s))")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
