"""AAF Project Boundary CLI（显式动作；不自动修改 Scope / Backlog）。

用法：
    python -m ai_agent_framework.project_boundary_cli show [--workspace <ws>] [--scope <file>]
    python -m ai_agent_framework.project_boundary_cli check <task.md> [--workspace <ws>] [--scope <file>]
    python -m ai_agent_framework.project_boundary_cli add-backlog <item> [--workspace <ws>] [--scope <file>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .project_boundary import (
    BOUNDARY_NOT_CONFIGURED,
    BoundaryError,
    check_task,
    load_boundary,
    write_boundary_json,
)


def _resolve_workspace(args_ws: Path | None, task: Path | None = None) -> Path:
    if args_ws is not None:
        return args_ws
    if task is not None:
        # 从 task 位置向上找 .aaf → workspace（task 在 <ws>/.aaf/tasks/active/）
        cur = task.resolve().parent
        for _ in range(6):
            if (cur / ".aaf").is_dir():
                return cur
            cur = cur.parent
    return Path.cwd()


def main() -> int:
    p = argparse.ArgumentParser(prog="project_boundary_cli", description="AAF Project Boundary Control")
    p.add_argument("--workspace", type=Path)
    p.add_argument("--scope", type=Path, dest="scope_file")
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("show", help="显示当前 PROJECT_SCOPE 结构化结果")
    ps.add_argument("--workspace", type=Path)
    ps.add_argument("--scope", type=Path, dest="scope_file")
    pc = sub.add_parser("check", help="对 TASK 执行 Boundary Check（warning-first）")
    pc.add_argument("task", type=Path)
    pc.add_argument("--workspace", type=Path)
    pc.add_argument("--scope", type=Path, dest="scope_file")
    pb = sub.add_parser("add-backlog", help="显式把一条建议加入 Backlog（必须显式调用）")
    pb.add_argument("item")
    pb.add_argument("--workspace", type=Path)
    pb.add_argument("--scope", type=Path, dest="scope_file")

    args = p.parse_args()
    ws = _resolve_workspace(args.workspace, args.task if args.command == "check" else None)
    try:
        if args.command == "show":
            boundary = load_boundary(ws, args.scope_file)
            if not boundary.configured:
                print(f"{BOUNDARY_NOT_CONFIGURED}: 未找到 PROJECT_SCOPE（{ws}）", file=sys.stderr)
                return 2
            print(json.dumps(boundary.to_dict(), ensure_ascii=False, indent=2))
            return 0

        if args.command == "check":
            boundary = load_boundary(ws, args.scope_file)
            if not boundary.configured:
                print(f"{BOUNDARY_NOT_CONFIGURED}: 未配置边界，跳过检查", file=sys.stderr)
                return 2
            task_text = args.task.read_text(encoding="utf-8")
            result = check_task(boundary, task_text)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        if args.command == "add-backlog":
            from .project_boundary import _section_items  # 复用 section 提取（显式动作）

            path = args.scope_file or (ws / "PROJECT_SCOPE.md")
            if not path.exists():
                path = ws / "docs" / "PROJECT_SCOPE.md"
            if not path.exists():
                print(f"{BOUNDARY_NOT_CONFIGURED}: 未找到 PROJECT_SCOPE 文件，无法加入 Backlog", file=sys.stderr)
                return 2
            text = path.read_text(encoding="utf-8")
            # 在 Backlog 节末尾追加（无 Backlog 节则新建）
            import re

            pat = re.compile(r"(?im)^[ \t]*#{1,4}[ \t]+(?:Backlog|Future Ideas)[ \t]*$")
            m = pat.search(text)
            if m:
                # 找到节末尾（下一标题或 EOF）
                rest = text[m.end():]
                lines = rest.splitlines()
                idx = 0
                for i, line in enumerate(lines):
                    if re.match(r"^[ \t]*#{1,4}[ \t]+\S", line):
                        idx = i
                        break
                    idx = i + 1
                new_text = text[: m.end()] + "\n- " + args.item + "\n" + "\n".join(lines[idx:])
            else:
                new_text = text.rstrip() + "\n\n## Backlog / Future Ideas\n\n- " + args.item + "\n"
            # 显式写回（原文件可读性保持；add-backlog 是唯一允许修改入口）
            path.write_text(new_text, encoding="utf-8")
            print(json.dumps({"action": "add-backlog", "item": args.item, "scope_path": str(path)}, ensure_ascii=False))
            return 0
    except (BoundaryError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
