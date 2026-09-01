"""AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001 — fresh-process eligibility check.

Run by fresh_runner_a4_wb_qualification_validation.py as a FRESH python process
(N+1 discipline): proves the registry qualification data ONLY affects candidate
eligibility and NEVER alters actual routing authority / invocation.
(自 AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001 起 hy4-preview 也成为
资格化候选；本检查的 UNQUALIFIED 集合已同步移除 hy4-preview——它由
fresh_runner_a4_wb_second_candidate_eligibility_check.py 专项覆盖。)

Checks (exit 0 = all pass):
1. baseline_registry: deepseek-v4-flash WorkBuddy candidate is QUALIFIED
   (T4 + qualified) → is_usable_candidate True; the other 13 WorkBuddy
   candidates stay ineligible.
2. select_shadow_candidate(LOW, executor, workbuddy) → deepseek-v4-flash
   eligible/selected (data visible to the eligibility gate).
3. select_shadow_candidate(MEDIUM/HIGH, executor, workbuddy) → still
   NO_SHADOW_CANDIDATE (no overestimation from the data).
4. adapters._workbuddy_invocation args EXACTLY [-p --output-format text -y]
   — the qualification data does NOT auto-add --model/--effort to the
   production WorkBuddy invocation (CodeBuddy Auto preserved).
5. agent:workbuddy Auto anchor unchanged (model=None / unknown).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import adapters  # noqa: E402
from ai_agent_framework import risk_contract as rc  # noqa: E402
from ai_agent_framework.model_registry import (  # noqa: E402
    QUAL_STATUS_QUALIFIED,
    baseline_registry,
    is_usable_candidate,
)
from ai_agent_framework.shadow_routing import (  # noqa: E402
    NO_SHADOW_CANDIDATE,
    select_shadow_candidate,
)

QUALIFIED_ID = "deepseek-v4-flash"
UNQUALIFIED_IDS = (
    "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
    "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
)


def main() -> int:
    failures: list[str] = []
    reg = baseline_registry()

    e = reg[QUALIFIED_ID]
    if e.capability_tier != "T4" or e.qualification.status != QUAL_STATUS_QUALIFIED:
        failures.append(f"{QUALIFIED_ID}: expected T4+QUALIFIED, got tier={e.capability_tier} qual={e.qualification.status}")
    if not is_usable_candidate(e):
        failures.append(f"{QUALIFIED_ID}: must pass eligibility gate (is_usable_candidate True)")
    for mid in UNQUALIFIED_IDS:
        if is_usable_candidate(reg[mid]):
            failures.append(f"{mid}: must stay ineligible")

    dec_low = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    if dec_low.selected != QUALIFIED_ID or QUALIFIED_ID not in dec_low.eligible:
        failures.append(f"LOW selector: expected selected={QUALIFIED_ID}, got {dec_low.selected}")
    for risk in (rc.RISK_MEDIUM, rc.RISK_HIGH):
        dec = select_shadow_candidate(risk, rc.ROLE_EXECUTOR, "workbuddy", reg)
        if dec.eligible or dec.selected is not None or not (dec.no_candidate_reason or "").startswith(NO_SHADOW_CANDIDATE):
            failures.append(f"{risk} selector: expected NO_SHADOW_CANDIDATE, got eligible={dec.eligible}")

    # invocation authority untouched by the qualification data
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", {})
    expected_args = ["<exe>", "-p", "--output-format", "text", "-y"]
    if len(args) != len(expected_args) or args[1:] != expected_args[1:]:
        failures.append(f"production invocation args changed: {args!r} (expected exact Auto shape)")
    if "--model" in args or "--effort" in args or "-m" in args:
        failures.append(f"qualification data auto-added a model/effort flag: {args!r}")

    anchor = reg["agent:workbuddy"]
    if anchor.model is not None or anchor.capability_tier is not None or is_usable_candidate(anchor):
        failures.append("agent:workbuddy Auto anchor changed")

    for f in failures:
        print("FAIL:", f)
    print(f"eligibility fresh-process check: {'PASS' if not failures else 'FAIL'} ({len(failures)} failure(s))")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
