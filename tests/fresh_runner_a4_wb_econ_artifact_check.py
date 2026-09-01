"""AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001 — fresh-process artifact + authority check.

Run by fresh_runner_a4_wb_econ_validation.py as a FRESH python process
(N+1 discipline): proves the new WorkBuddy economic metadata fact layer
- does NOT alter framework lifecycle or routing authority (selector /
  invocation unchanged), and
- its observation artifact (economic_facts.json) is generated/readable as
  designed (facts_from_dict parses it; freshness per fact matches
  classify_freshness at the recorded observed_at).

Checks (exit 0 = all pass):
1. economic_facts.json exists next to the probe artifacts and parses via
   facts_from_dict (schema_version 1); all 15 CLI candidates present.
2. For every stored fact: classify_freshness(fact, observed_at) == stored
   freshness (artifact freshness is reproducible, not hand-written).
3. Baseline facts agree with artifact facts (multiplier/promotion/validity).
4. hy3/hy4-preview = FRESH + authoritative cheap at observed_at;
   deepseek-v4-flash = UNKNOWN freshness, NOT authoritative cheap.
5. Routing authority unchanged: LOW workbuddy selector still selects only
   deepseek-v4-flash (FRESH FREE hy3/hy4-preview still CAPABILITY_INSUFFICIENT);
   agent:workbuddy Auto anchor unchanged; adapters._workbuddy_invocation
   still exact Auto shape (no --model/--effort).
"""
from __future__ import annotations

import json
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
    ECON_UNKNOWN,
    WORKBUDDY_CANDIDATE_IDS,
    baseline_economic_facts,
    classify_freshness,
    facts_from_dict,
    is_authoritative_cheap,
)

ARTIFACT = (
    ROOT / ".aaf" / "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001"
    / "economic_probe" / "economic_facts.json"
)


def main() -> int:
    failures: list[str] = []

    # ---- 1/2. artifact readable as designed ----
    if not ARTIFACT.exists():
        failures.append(f"economic observation artifact missing: {ARTIFACT}")
        print("FAIL:", failures[0])
        print("artifact+authority fresh-process check: FAIL (1 failure(s))")
        return 1
    try:
        doc = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        stored = facts_from_dict(doc)
    except (OSError, ValueError) as exc:
        failures.append(f"economic_facts.json not parseable via facts_from_dict: {exc}")
        print("FAIL:", failures[0])
        return 1
    if set(stored) != set(WORKBUDDY_CANDIDATE_IDS):
        failures.append(
            f"artifact candidates {sorted(stored)} != expected 15 {sorted(WORKBUDDY_CANDIDATE_IDS)}"
        )

    # freshness reproducible at observed_at
    for mid, fact in stored.items():
        ref = datetime.fromisoformat(fact.observed_at)
        stored_fresh = doc["facts"][mid]["freshness"]
        computed = classify_freshness(fact, ref)
        if stored_fresh != computed:
            failures.append(f"{mid}: artifact freshness {stored_fresh!r} != computed {computed!r}")

    # ---- 3. baseline facts agree with artifact ----
    baseline = baseline_economic_facts()
    for mid, fact in baseline.items():
        other = stored[mid]
        if (fact.multiplier, fact.promotion_status, fact.valid_from, fact.valid_until) != (
            other.multiplier, other.promotion_status, other.valid_from, other.valid_until
        ):
            failures.append(f"{mid}: baseline fact != artifact fact")

    # ---- 4. freshness/cheapness semantics at observed_at ----
    ref = datetime.fromisoformat(baseline["hy3"].observed_at)
    if classify_freshness(baseline["hy3"], ref) != ECON_FRESH:
        failures.append("hy3 must be FRESH at observed_at (free promo window active)")
    if classify_freshness(baseline["hy4-preview"], ref) != ECON_FRESH:
        failures.append("hy4-preview must be FRESH at observed_at (free promo window active)")
    if not is_authoritative_cheap(baseline["hy3"], ref):
        failures.append("hy3 must be authoritative-cheap at observed_at (FRESH + free + 0.0)")
    if classify_freshness(baseline["deepseek-v4-flash"], ref) != ECON_UNKNOWN:
        failures.append("deepseek-v4-flash must be UNKNOWN freshness (no date window)")
    if is_authoritative_cheap(baseline["deepseek-v4-flash"], ref):
        failures.append("deepseek-v4-flash must NOT be authoritative cheap (discount, UNKNOWN)")

    # ---- 5. routing authority unchanged ----
    # （自 AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001 起 hy4-preview 也
    # 成为资格化候选——economic 事实层本身仍不进入 selector；本检查只验证
    # economics 不消费 + 候选选择顺序不受经济事实驱动。）
    reg = baseline_registry()
    dec = select_shadow_candidate(rc.RISK_LOW, rc.ROLE_EXECUTOR, "workbuddy", reg)
    if dec.selected != "deepseek-v4-flash":
        failures.append(f"LOW workbuddy selector changed: eligible={dec.eligible}")
    if not set(("deepseek-v4-flash", "hy4-preview")).issubset(set(dec.eligible)):
        failures.append(f"LOW workbuddy selector eligible set changed: {dec.eligible}")
    reasons = {rec.candidate: rec.reason for rec in dec.excluded}
    if reasons.get("hy3") != EXCL_CAPABILITY_INSUFFICIENT:
        failures.append("hy3: expected CAPABILITY_INSUFFICIENT despite FRESH FREE fact")
    if is_usable_candidate(reg["agent:workbuddy"]):
        failures.append("agent:workbuddy Auto anchor became usable")
    args, stdin_data, env_out = adapters._workbuddy_invocation("PROMPT", {})
    if len(args) < 1 or args[1:] != ["-p", "--output-format", "text", "-y"]:
        failures.append(f"production invocation args changed: {args!r}")
    if "--model" in args or "--effort" in args or "-m" in args:
        failures.append(f"economics auto-added a model/effort flag: {args!r}")

    for f in failures:
        print("FAIL:", f)
    print(f"artifact+authority fresh-process check: {'PASS' if not failures else 'FAIL'} ({len(failures)} failure(s))")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
