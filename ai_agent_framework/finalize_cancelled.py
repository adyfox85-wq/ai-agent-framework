"""AI Agent Framework — Core-owned Recovery Finalizer foundation（Phase E §6A.12 / §6B.21）。

场景：task 被取消 / 强杀 / 崩溃后未留下终态，需要 Core 独立收敛为 CANCELLED。
本模块属于 **Lifecycle Core**（不是 UI / Launcher 逻辑）；Launcher 通过子进程 CLI
调用，避免 import Core 内部执行逻辑（§14.4 防侵入规则）。

流程（§6B.21）：:

    acquire state.lock
    → canonical reload（锁内重读 task.json）
    → terminal arbitration（已有终态 → 返回 canonical，不改写）
    → terminal commit if allowed（CANCELLED + terminal_generation）
    → reconcile run.json / REPORT.md（§6B.6–§6B.8）
    → idempotent return（重复调用返回相同 canonical result）

边界（TASK-005-A）：
- 本 TASK 只提供 Core finalizer 基础能力（soft cancel 收敛 + reconciliation）
- **不从 Launcher 调用它去 taskkill**；真实 Force Cancel 调用链（§6A.8 ownership
  verification → 进程树终止 → 调用本 finalizer）留到 TASK-005-B
- 本文件不含任何进程终止逻辑（不启动子进程、不杀进程；只有文件状态写入）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .lock_utils import LockTimeout
from .reconcile import reconcile_terminal_artifacts
from .task_lifecycle import (
    CANCEL_MODE_FORCE,
    CANCEL_MODE_SOFT,
    TERMINAL_REASON_CANCEL_REQUESTED,
    TERMINAL_REASON_FORCE_CANCELLED,
    finalize_terminal,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LOCK_TIMEOUT = 4
EXIT_RECONCILE_ERROR = 5


def finalize_cancelled_task(
    task_id: str,
    workspace: Path | str,
    output_dir: Path | str,
    *,
    reason: str = TERMINAL_REASON_CANCEL_REQUESTED,
    cancel_mode: str = CANCEL_MODE_SOFT,
    evidence: str | None = None,
    lock_timeout: float = 10.0,
):
    """Core recovery finalizer（§6B.21）。返回 canonical result dict。

    - 已有终态 → 不改写，幂等返回现有 canonical result（§6B.2-D）
    - 无终态 → 提交 CANCELLED（terminal_reason=reason；cancel_mode=cancel_mode）
    - 无论是否新提交，都执行 reconciliation（补齐 run.json / REPORT.md 跟随 canonical）
    - 幂等：重复调用返回相同 canonical result
    """
    final_reason = reason
    if evidence:
        final_reason = f"{reason}: {evidence}"
    canonical = finalize_terminal(
        Path(output_dir),
        task_id=task_id,
        status="CANCELLED",
        task_path=Path(output_dir) / "TASK.md",  # TASK.md 不一定存在；仅作 task.json 记录
        workspace=workspace,
        report_path=str(Path(output_dir) / "REPORT.md"),
        reason="CANCEL_REQUESTED",
        terminal_reason=final_reason,
        cancel_mode=cancel_mode,
        lock_timeout=lock_timeout,
    )
    reconcile_terminal_artifacts(task_id, workspace, output_dir, lock_timeout=lock_timeout)
    return canonical


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m ai_agent_framework.finalize_cancelled",
        description="Core-owned recovery finalizer（CANCELLED 收敛 + reconciliation；幂等）",
    )
    p.add_argument("--task-id", required=True, help="Task ID")
    p.add_argument("--workspace", required=True, help="Business project workspace")
    p.add_argument("--output", required=True, help="Task output dir (.aaf/<Task-ID>)")
    p.add_argument(
        "--reason",
        default=TERMINAL_REASON_CANCEL_REQUESTED,
        choices=(TERMINAL_REASON_CANCEL_REQUESTED, TERMINAL_REASON_FORCE_CANCELLED),
        help="terminal_reason（FORCE_CANCELLED 由 TASK-005-B 的 Launcher 调用链使用）",
    )
    p.add_argument(
        "--cancel-mode",
        default=CANCEL_MODE_SOFT,
        choices=(CANCEL_MODE_SOFT, CANCEL_MODE_FORCE),
        help="cancel_mode（force 属 TASK-005-B；本 TASK 默认 soft）",
    )
    p.add_argument("--evidence", default=None, help="optional evidence description")
    p.add_argument("--lock-timeout", type=float, default=10.0, help="state.lock acquire timeout (s)")
    args = p.parse_args(argv)

    try:
        canonical = finalize_cancelled_task(
            args.task_id,
            args.workspace,
            args.output,
            reason=args.reason,
            cancel_mode=args.cancel_mode,
            evidence=args.evidence,
            lock_timeout=args.lock_timeout,
        )
    except LockTimeout as exc:
        print(f"FINALIZATION_BUSY: {exc}", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    except Exception as exc:  # noqa: BLE001 —— CLI 边界：明确错误码
        print(f"RECOVERY_FINALIZE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RECONCILE_ERROR

    print(json.dumps(canonical.to_dict(), ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
