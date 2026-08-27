"""AI Agent Framework — Core-owned Recovery Finalizer foundation（Phase E §6A.12 / §6B.21）。

场景：task 被取消 / 强杀 / 崩溃后未留下终态，需要 Core 独立收敛为 CANCELLED。
本模块属于 **Lifecycle Core**（不是 UI / Launcher 逻辑）；Launcher 通过子进程 CLI
调用，避免 import Core 内部执行逻辑（§14.4 防侵入规则）。

流程（§6B.21 + FIX-001 evidence/identity validation）::

    锁内 canonical identity 校验（canonical task.json exists + task_id 匹配）
    → terminal arbitration（已有终态 → 返回 canonical，不改写）
    → 无终态：先验证 recovery evidence（soft: 合法 matching cancel.request；
      force: 005-A 明确拒绝）→ 才允许新提交 CANCELLED
    → terminal commit via finalize_terminal（统一 Core terminal finalizer，§6B.2）
    → reconcile run.json / REPORT.md（§6B.6–§6B.8）
    → idempotent return（重复调用返回相同 canonical result）

FIX-001 安全契约（Codex blocking finding 2 闭合）：
- 任何新 terminal commit 前必须验证 canonical identity：task.json 存在且
  ``task.json.task_id == 请求 task_id``；mismatch → 显式错误、零 canonical 写、
  零 reconciliation 变更、零 generation bump（不得用 CLI 参数覆盖 canonical identity）
- soft recovery（cancel_mode=soft 或 reason=CANCEL_REQUESTED）必须先存在并通过验证的
  ``<output_dir>/cancel.request``：parseable + request == soft_cancel +
  task_id == canonical task_id + requested_at 合法（缺失/损坏/mismatch/wrong type →
  fail safely，不得修改 canonical task.json）
- 旧 ``evidence: str | None`` 参数只是 **diagnostic note**，不是 authority evidence
- force recovery（cancel_mode=force 或 reason=FORCE_CANCELLED）：005-A 不伪造证据验证，
  返回 ``ForceRecoveryNotAvailable``（FORCE_RECOVERY_NOT_AVAILABLE），直至 TASK-005-B
  提供正式 ownership evidence validator

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

from . import cancel as cancel_mod
from .lock_utils import LockTimeout, task_state_lock
from .reconcile import reconcile_terminal_artifacts
from .task_lifecycle import (
    CANCEL_MODE_FORCE,
    CANCEL_MODE_SOFT,
    TERMINAL_REASON_CANCEL_REQUESTED,
    TERMINAL_REASON_FORCE_CANCELLED,
    finalize_terminal,
    is_terminal_status,
    read_status,
    task_json_path,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LOCK_TIMEOUT = 4
EXIT_RECONCILE_ERROR = 5
EXIT_RECOVERY_ERROR = 6  # identity / evidence / force-boundary 校验失败（安全失败）


class RecoveryError(RuntimeError):
    """Recovery 校验失败：不得写 canonical、不得 reconciliation 变更。"""


class RecoveryEvidenceError(RecoveryError):
    """Soft recovery evidence（cancel.request）缺失 / 损坏 / 不匹配 / 非法。"""


class ForceRecoveryNotAvailable(RecoveryError):
    """force recovery 未开放（TASK-005-B 交付）；005-A 不伪造 force validation。"""


def _validate_recovery_identity(output_dir: Path, task_id: str) -> dict:
    """锁内验证 canonical identity（FIX-001 req 7）。

    - canonical task.json exists + task_id == requested task_id
    - 失败 → RecoveryError（显式）；调用方不得继续提交 CANCELLED
    - 返回锁内读取的 canonical dict（供 terminal arbitration 使用）
    """
    path = task_json_path(output_dir)
    if not path.exists():
        raise RecoveryError(
            f"RECOVERY_IDENTITY_ERROR: 无 canonical task.json（{path}）——"
            f"不得凭空收敛为 CANCELLED"
        )
    try:
        prev = read_status(output_dir)
    except Exception as exc:  # LifecycleError（损坏）
        raise RecoveryError(
            f"RECOVERY_IDENTITY_ERROR: canonical task.json 损坏/不可读（{path}）: {exc}——"
            f"不得修改 canonical"
        ) from exc
    canonical_task_id = prev.get("task_id")
    if canonical_task_id != task_id:
        raise RecoveryError(
            f"RECOVERY_IDENTITY_ERROR: canonical task_id {canonical_task_id!r} "
            f"!= 请求 task_id {task_id!r}——不得以 CLI 参数覆盖 canonical identity，"
            f"零 canonical 写 / 零 reconciliation 变更 / 零 generation bump"
        )
    return prev


def _validate_recovery_evidence(
    output_dir: Path,
    task_id: str,
    cancel_mode: str,
    reason: str,
) -> None:
    """在“准备新提交 CANCELLED”前验证 recovery evidence（FIX-001 req 8/10/12）。

    - force → ForceRecoveryNotAvailable（005-A 无 force evidence validator）
    - soft → 必须存在合法 matching cancel.request（parseable / soft_cancel /
      task_id 匹配 / requested_at 合法）；任何缺失/损坏/mismatch → RecoveryEvidenceError，
      不写 canonical
    - 旧 ``evidence`` 参数仅作 diagnostic note（由调用方拼入 terminal_reason），
      不在此充当 authority evidence
    """
    if cancel_mode == CANCEL_MODE_FORCE or reason == TERMINAL_REASON_FORCE_CANCELLED:
        raise ForceRecoveryNotAvailable(
            "FORCE_RECOVERY_NOT_AVAILABLE: force recovery 需要 TASK-005-B 的 "
            "ownership/termination evidence validator；005-A-FIX-001 不得凭任意 "
            "字符串 evidence 提交 CANCELLED（不伪造 force validation）"
        )
    # 复用 cancel.py 的 parser / validator（req 13：不得复制第二套不一致 JSON parser）
    req, warning = cancel_mod.inspect_cancel_request(output_dir)
    if warning:
        raise RecoveryEvidenceError(f"RECOVERY_EVIDENCE_ERROR: cancel.request 无效——{warning}")
    if req is None:
        raise RecoveryEvidenceError(
            "RECOVERY_EVIDENCE_ERROR: 缺少合法 cancel.request——soft recovery 要求 "
            f"<output_dir>/cancel.request 存在且通过验证（request=soft_cancel、"
            f"task_id={task_id!r}、requested_at 合法）"
        )
    if req.request != cancel_mod.CANCEL_REQUEST_TYPE_SOFT:
        raise RecoveryEvidenceError(
            f"RECOVERY_EVIDENCE_ERROR: cancel.request 请求类型 {req.request!r} 不是 "
            f"soft_cancel（wrong request type → fail safely）"
        )
    if req.task_id != task_id:
        raise RecoveryEvidenceError(
            f"RECOVERY_EVIDENCE_ERROR: cancel.request task_id {req.task_id!r} "
            f"!= canonical task_id {task_id!r}（mismatch → fail safely）"
        )
    if cancel_mod.parse_requested_at(req.requested_at) is None:
        raise RecoveryEvidenceError(
            f"RECOVERY_EVIDENCE_ERROR: cancel.request requested_at 非法 {req.requested_at!r}"
            f"（损坏 → fail safely）"
        )


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
    """Core recovery finalizer（§6B.21 + FIX-001）。返回 canonical result dict。

    顺序：
    1. 锁内 canonical identity 校验（task.json exists + task_id 匹配；req 7）
    2. terminal arbitration：已有终态 → 不改写（req 9：late/missing evidence 不得改变
       existing terminal；reconciliation 仍执行），幂等返回现有 canonical
    3. 无终态 → 先验证 recovery evidence（soft: 合法 matching cancel.request；
       force: 拒绝）→ 经 ``finalize_terminal`` 提交 CANCELLED（唯一 Core terminal
       finalizer，req 14：本模块不自行写 task.json terminal）
    4. reconciliation（补齐 run.json / REPORT.md 跟随 canonical）
    5. 幂等：重复调用返回相同 canonical result

    - ``evidence``：仅 diagnostic note（req 12），不是 authority evidence；
      authority evidence = validated cancel.request（soft）/ TASK-005-B ownership
      + termination evidence（force，未开放）
    """
    output_dir = Path(output_dir)
    final_reason = reason
    if evidence:
        final_reason = f"{reason}: {evidence}"  # diagnostic note only（req 12）

    # 1. canonical identity（锁内 reload；§6B.21 锁内 canonical reload + req 7）
    with task_state_lock(output_dir, task_id, timeout=lock_timeout):
        prev = _validate_recovery_identity(output_dir, task_id)
        existing_terminal = is_terminal_status(prev.get("status", ""))

    if existing_terminal:
        # 2. terminal arbitration（req 9）：canonical terminal wins；
        #    evidence validation 只适用于“准备新提交 CANCELLED”，不适用于“已有终态”。
        #    统一经 finalize_terminal（锁内仲裁，幂等返回 preserved=True canonical）。
        canonical = finalize_terminal(
            Path(output_dir),
            task_id=task_id,
            status="CANCELLED",
            task_path=Path(output_dir) / "TASK.md",
            workspace=workspace,
            report_path=str(Path(output_dir) / "REPORT.md"),
            reason="CANCEL_REQUESTED",
            terminal_reason=final_reason,
            cancel_mode=cancel_mode,
            lock_timeout=lock_timeout,
        )
    else:
        # 3. evidence validation BEFORE 新 terminal commit（req 8/10）
        _validate_recovery_evidence(output_dir, task_id, cancel_mode, reason)
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

    # 4. reconciliation（已有终态也必须走；§6B.21 不再“发现终态直接 return”）
    reconcile_terminal_artifacts(task_id, workspace, output_dir, lock_timeout=lock_timeout)
    return canonical


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m ai_agent_framework.finalize_cancelled",
        description=(
            "Core-owned recovery finalizer（CANCELLED 收敛 + reconciliation；幂等）。\n"
            "安全契约（FIX-001）：soft cancel 必须先存在合法 matching cancel.request\n"
            "（<output_dir>/cancel.request: request=soft_cancel、task_id 匹配、"
            "requested_at 合法）；force recovery 未开放（TASK-005-B）。"
        ),
    )
    p.add_argument("--task-id", required=True, help="Task ID（必须与 canonical task.json.task_id 一致）")
    p.add_argument("--workspace", required=True, help="Business project workspace")
    p.add_argument("--output", required=True, help="Task output dir (.aaf/<Task-ID>)")
    p.add_argument(
        "--reason",
        default=TERMINAL_REASON_CANCEL_REQUESTED,
        choices=(TERMINAL_REASON_CANCEL_REQUESTED, TERMINAL_REASON_FORCE_CANCELLED),
        help="terminal_reason（FORCE_CANCELLED 属 TASK-005-B；005-A 明确拒绝，不伪造）",
    )
    p.add_argument(
        "--cancel-mode",
        default=CANCEL_MODE_SOFT,
        choices=(CANCEL_MODE_SOFT, CANCEL_MODE_FORCE),
        help="cancel_mode（force 属 TASK-005-B；本 TASK 仅 soft，且要求合法 cancel.request）",
    )
    p.add_argument(
        "--evidence",
        default=None,
        help="diagnostic note only（NOT authority evidence；authority evidence = "
        "validated cancel.request / future TASK-005-B force evidence）",
    )
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
    except RecoveryError as exc:
        # identity / evidence / force-boundary 校验失败：安全失败，CLI 与 library 同规则
        print(f"RECOVERY_FINALIZE_ERROR: {exc}", file=sys.stderr)
        return EXIT_RECOVERY_ERROR
    except Exception as exc:  # noqa: BLE001 —— CLI 边界：明确错误码
        print(f"RECOVERY_FINALIZE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RECONCILE_ERROR

    print(json.dumps(canonical.to_dict(), ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
