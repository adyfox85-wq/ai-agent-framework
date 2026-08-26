"""AAF Task Archive CLI（独立入口，不改变 run.py 语义）。

用法：
    python -m ai_agent_framework.task_archive archive <package_dir> --archive-root <root>
    python -m ai_agent_framework.task_archive restore <archive_path> --active-root <root>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .task_archive import ArchiveError, archive_package, restore_package


def main() -> int:
    p = argparse.ArgumentParser(prog="task_archive", description="AAF Task Artifact Archive")
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("archive", help="归档 Task Package（仅终态 SUCCESS/WAITING/FAILED）")
    pa.add_argument("package_dir", type=Path, help="Task package 目录（含 task.json）")
    pa.add_argument("--archive-root", type=Path, required=True, help="归档根目录（如 <ws>/.aaf/archive）")

    pr = sub.add_parser("restore", help="恢复 archived Task Package 到 active")
    pr.add_argument("archive_path", type=Path, help="archive package 目录")
    pr.add_argument("--active-root", type=Path, required=True, help="active 根目录（如 <ws>/.aaf）")

    args = p.parse_args()
    try:
        if args.command == "archive":
            result = archive_package(args.package_dir, args.archive_root)
        else:
            result = restore_package(args.archive_path, args.active_root)
    except ArchiveError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
