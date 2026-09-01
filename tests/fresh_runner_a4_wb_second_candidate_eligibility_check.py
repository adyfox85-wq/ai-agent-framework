"""AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001 — fresh-process eligibility check.

Run by fresh_runner_a4_wb_second_candidate_validation.py as a FRESH python
process (N+1 discipline): proves the new second WorkBuddy qualification data
ONLY affects candidate eligibility and NEVER alters actual routing authority /
invocation.

Checks (exit 0 = all pass):
1. baseline_registry: TWO independent LOW-eligible WorkBuddy candidates —
   deepseek-v4-flash (QUALIFICATION-001) and hy4-preview (SECOND-CANDIDATE-001),
   both T4 + QUALIFIED → is_usable_candidate True; the other 13 WorkBuddy
   candidates stay ineligible (tier=None + qualification=unknown).
2. select_shadow_candidate(LOW, executor, workbuddy) → both eligible;
   selected stays deepseek-v4-flash (cost/locality tie, key order — existing
   selection semantics unchanged).
3. select_shadow_candidate(MEDIUM/HIGH/CRITICAL, executor, workbuddy) → still
   NO_SHADOW_CANDIDATE (no overestimation from the data).
4. adapters._workbuddy_invocation args EXACTLY [-p --output-format text -y]
   — the new qualification data does NOT auto-add --model/--effort to the
   production WorkBuddy invocation (CodeBuddy Auto preserved).
5. agent:workbuddy Auto anchor unchanged (model=None / unknown).
6. workbuddy_economics.select_probe_candidate on baseline facts picks
   hy4-preview first (fail-closed probe-priority) and reports
   NO_TRUSTWORTHY_SECOND_CANDIDATE when only STALE/UNKNOWN facts remain.
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
from ai_agent_framework import risk_contract as rc  # noqa: E402
from ai_agent_framework import workbuddy_economics as we  # noqa: E402
from ai_agent_framework.model_registry import (  # noqa: E402
    QUAL_STATUS_QUALIFIED,
    baseline_registry,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (  # noqa: E402
    NO_SHADOW_CANDIDATE,
    select_shadow_candidate,
)

QUALIFIED_IDS = ("deepseek-v4-flash", "hy4-preview")
SELECTED_CANDIDATE = "hy4-preview"
UNQUALIFIED_IDS = (
    "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
    "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
)


def main() -> int:
    failures: list[str] = []
    reg = baseline_registry()

    for mid in QUALIFIED_IDS:
        e = reg[mid]
        if e.capability_tier != "T4" or e.qualification.status != QUAL_STATUS_QUALIFIED:
            failures.append(f"{mid}: expected T4+QUALIFIED, got tier={e.capability_tier} qual={e.qualification.status}")
        if not is_usable_candidate(e):
            failures.append(f"{mid}: must pass eligibility gate (is_usable_candidate True)")
    for mid in UNQUALIFIED_IDS:
        if is_usable_candidate(reg[mid]):
            failures.append(f"{mid}: must stay ineligible")

    dec_low = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    if set(dec_low.eligible) != set(QUALIFIED_IDS):
        failures.append(f"LOW selector: expected eligible={set(QUALIFIED_IDS)}, got {dec_low.eligible}")
    if dec_low.selected != "deepseek-v4-flash":
        failures.append(f"LOW selector: expected selected=deepseek-v4-flash, got {dec_low.selected}")
    for risk in (rc.RISK_MEDIUM, rc.RISK_HIGH, rc.RISK_CRITICAL):
        dec = select_shadow_candidate(risk, rc.ROLE_EXECUTOR, "workbuddy", reg)
        if dec.eligible or dec.selected is not None or not (dec.no_candidate_reason or "").startswith(NO_SHADOW_CANDIDATE):
            failures.append(f"{risk} selector: expected NO_SHADOW_CANDIDATE, got eligible={dec.eligible}")

    # invocation authority untouched by the second qualification data
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", {})
    expected_args = ["<exe>", "-p", "--output-format", "text", "-y"]
    if len(args) != len(expected_args) or args[1:] != expected_args[1:]:
        failures.append(f"production invocation args changed: {args!r} (expected exact Auto shape)")
    if "--model" in args or "--effort" in args or "-m" in args:
        failures.append(f"qualification data auto-added a model/effort flag: {args!r}")

    anchor = reg["agent:workbuddy"]
    if anchor.model is not None or anchor.capability_tier is not None or is_usable_candidate(anchor):
        failures.append("agent:workbuddy Auto anchor changed")

    # fail-closed probe-priority selection (economic fact layer)
    now = datetime.fromisoformat("2026-09-02T02:10:30+08:00")
    facts = we.baseline_economic_facts()
    if we.select_probe_candidate(facts, now, exclude_ids=("deepseek-v4-flash",)) != SELECTED_CANDIDATE:
        failures.append(f"probe-priority selection: expected {SELECTED_CANDIDATE}")
    if we.select_probe_candidate(
        facts, now, exclude_ids=("deepseek-v4-flash", "hy4-preview", "hy3"),
    ) is not we.NO_TRUSTWORTHY_SECOND_CANDIDATE:
        failures.append("probe-priority selection: expected NO_TRUSTWORTHY_SECOND_CANDIDATE after exhausting FRESH ranks")

    for f in failures:
        print("FAIL:", f)
    print(f"second-candidate eligibility fresh-process check: {'PASS' if not failures else 'FAIL'} ({len(failures)} failure(s))")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
