"""Phase F E2E — 真实 run.py 的 dry-run 包装（真实 runner 子进程；不调用 Agent）。

Launcher argv 形状与真实 run.py 一致（[python, <script>, <task>, --workspace, WS,
--output, OUT, --launch-id, LID]），因此 expected_command_line / ownership
handshake 是真实闭环。本包装在真实 runner 上追加 dry_run=True：完整执行
Validation → Boundary → Route → Manifest → REPORT（真实文件契约），Agent 链
不调用（dry-run 为框架既有语义——不执行 Agent，终态保持 CREATED，不伪装 SUCCESS）。

用途：Bridge Phase F E2E 的「正常执行」支线——真实 launcher 子进程 + 真实
runner + 真实 artifacts，零 Agent 依赖（Phase E 同款确定性约束）。
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task", type=Path)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--launch-id", default=None)
    args = p.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    from ai_agent_framework import runner  # noqa: PLC0415

    report = runner.run(args.task, args.workspace, args.output, dry_run=True, launch_id=args.launch_id)
    print(report, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
