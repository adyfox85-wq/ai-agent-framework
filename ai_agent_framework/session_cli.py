"""AAF Session Continuity CLI（显式 rollover；不自动触发）。

用法：
    python -m ai_agent_framework.session_cli rollover --workspace <ws> [--project ... --phase ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .session_continuity import SessionError, rollover


def main() -> int:
    p = argparse.ArgumentParser(prog="session_cli", description="AAF Session Continuity")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("rollover", help="显式生成 Session 承接材料")
    pr.add_argument("--workspace", type=Path, required=True)
    pr.add_argument("--project")
    pr.add_argument("--phase")
    pr.add_argument("--goal", dest="core_goal")
    pr.add_argument("--boundaries", dest="frozen_boundaries")
    pr.add_argument("--completed", dest="completed_work")
    pr.add_argument("--open-items", dest="open_items")
    pr.add_argument("--blocking", dest="blocking_issues")
    pr.add_argument("--decisions", dest="important_decisions")
    pr.add_argument("--task-ids", dest="relevant_task_ids")
    pr.add_argument("--next-step", dest="next_step")
    pr.add_argument("--do-not-reopen", dest="do_not_reopen")
    pr.add_argument("--project-state", dest="project_state_file", type=Path)

    args = p.parse_args()
    try:
        result = rollover(args.workspace, **{
            k: v for k, v in {
                "project": args.project,
                "phase": args.phase,
                "core_goal": args.core_goal,
                "frozen_boundaries": args.frozen_boundaries,
                "completed_work": args.completed_work,
                "open_items": args.open_items,
                "blocking_issues": args.blocking_issues,
                "important_decisions": args.important_decisions,
                "relevant_task_ids": args.relevant_task_ids,
                "next_step": args.next_step,
                "do_not_reopen": args.do_not_reopen,
                "project_state_file": args.project_state_file,
            }.items() if v is not None
        })
    except SessionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
