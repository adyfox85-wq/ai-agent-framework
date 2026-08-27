"""AI Agent Framework — Core-owned Recovery Finalizer foundation（Phase E §6A.12 / §6B.21）。

场景：task 被取消 / 强杀 / 崩溃后未留下终态，需要 Core 独立收敛为 CANCELLED。
本模块属于 **Lifecycle Core**（不是 UI / Launcher 逻辑）；Launcher 通过子进程 CLI
调用，避免 import Core 内部执行逻辑（§14.4 防侵入规则）。

流程（§6B.21 + FIX-001 evidence/identity validation + FIX-002 single-lock atomic）::

    一个不可分割的 state.lock 临界区（FIX-002：identity + evidence 验证与 commit
    之间**不 release lock**，关闭 TOCTOU）：

    acquire task state.lock
    → 锁内 reload canonical task.json
    → validate canonical exists + canonical task_id == 请求 task_id
    → terminal arbitration（已有终态 → 保留 canonical，不要求 evidence，不改写）
    → 无终态：锁内验证 recovery evidence（soft: 当前锁内仍有效的 matching
      cancel.request；force: 005-A 明确拒绝）→ 才允许新提交 CANCELLED
    → 经 _finalize_terminal_locked（同一锁临界区内共享 helper，不重复 acquire 锁）
      提交 CANCELLED + 持久化 terminal_generation
    → release lock
    → reconcile run.json / REPORT.md（§6B.6–§6B.8；锁外，不改 canonical terminal）

    idempotent return（重复调用返回相同 canonical result）

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

FIX-002 单一临界区契约（Codex 遗留 recovery TOCTOU blocker 闭合）：
- canonical identity 验证、terminal arbitration、recovery evidence 验证与
  CANCELLED commit 属于**同一个不可分割的 per-task state.lock 临界区**——
  验证与 commit 之间不 release lock（req 1/4/5）
- commit 经 ``task_lifecycle._finalize_terminal_locked``（共享锁内 helper）：
  调用方已持锁、传入锁内 canonical snapshot、不再次 acquire 锁（no nested
  reentry，req 2）；terminal commit 逻辑仍只有一套（req 3，无第三写者）

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
    _finalize_terminal_locked,
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
    """**锁内**验证 canonical identity（FIX-001 req 7 / FIX-002 req 4 lock-stable）。

    - canonical task.json exists + task_id == requested task_id
    - 失败 → RecoveryError（显式）；调用方不得继续提交 CANCELLED
    - 返回锁内读取的 canonical dict（供 terminal arbitration / commit 使用；
      FIX-002：同一临界区内 reload，identity 不可能在验证与 commit 之间变化）
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

    FIX-002：**必须由调用方在 state.lock 临界区内调用**——evidence 验证与
    CANCELLED commit 同属一个临界区（req 5：evidence 必须 lock-stable；验证后、
    commit 前不 release lock；不得在锁外验证后再提交）。

    - force → ForceRecoveryNotAvailable（005-A 无 force evidence validator；
      调用方在进入临界区前已拦截，此处为纵深防御）
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
    """Core recovery finalizer（§6B.21 + FIX-001 + FIX-002）。返回 canonical result dict。

    FIX-002 单一不可分割临界区（关闭 Codex 遗留 recovery TOCTOU blocker）::

        0. force boundary（纯参数校验，不依赖文件状态；005-A 明确拒绝 force recovery）
        1. acquire state.lock
        2. 锁内 reload canonical task.json
        3. 锁内 identity 校验（canonical exists + task_id == 请求 task_id；req 4：
           canonical identity 必须 lock-stable，mismatch → RecoveryError，零写零 bump）
        4. 锁内 terminal arbitration：已有终态 → 保留 canonical（req 9：无 evidence
           也 preserve；reconciliation 仍执行），不改写
        5. 无终态 → 锁内验证 recovery evidence（req 5/8：soft 必须存在当前锁内仍
           有效的 matching cancel.request；force 已在 0 拒绝）——验证与 commit 之间
           **不 release lock**（req 1/4）
        6. 经 ``_finalize_terminal_locked`` 提交 CANCELLED（req 2/3：共享锁内 helper，
           调用方已持锁，不重复 acquire；generation 恰一次 bump；无第三 terminal writer）
        7. release state.lock
        8. reconciliation（run.json / REPORT.md 跟随 canonical；req 10：锁外执行，
           canonical terminal 不被 reconciliation 修改；crash 后可重跑）
        9. 幂等：重复调用返回相同 canonical result

    - ``evidence``：仅 diagnostic note（req 12），不是 authority evidence；
      authority evidence = 锁内验证的 cancel.request（soft）/ TASK-005-B ownership
      + termination evidence（force，未开放）
    """
    output_dir = Path(output_dir)
    final_reason = reason
    if evidence:
        final_reason = f"{reason}: {evidence}"  # diagnostic note only（req 12）

    # 0. force boundary（req 13：005-A force recovery = NOT AVAILABLE；纯参数校验，
    #    不 acquire 锁、不依赖文件状态、不产生任何写）
    if cancel_mode == CANCEL_MODE_FORCE or reason == TERMINAL_REASON_FORCE_CANCELLED:
        raise ForceRecoveryNotAvailable(
            "FORCE_RECOVERY_NOT_AVAILABLE: force recovery 需要 TASK-005-B 的 "
            "ownership/termination evidence validator；005-A-FIX-002 不得凭任意 "
            "字符串 evidence 提交 CANCELLED（不伪造 force validation）"
        )

    # 1–7. 单一 state.lock 临界区：identity + arbitration + evidence + commit
    with task_state_lock(output_dir, task_id, timeout=lock_timeout):
        # 2/3. 锁内 reload + identity 校验（req 4：canonical identity lock-stable）
        prev = _validate_recovery_identity(output_dir, task_id)

        # 4. terminal arbitration（req 9）：已有终态 → 保留 canonical、不要求
        #    evidence、不改写（统一经共享 helper 幂等返回 preserved canonical）
        if not is_terminal_status(prev.get("status", "")):
            # 5. 锁内 evidence 验证（req 5/8：当前锁内仍有效的 matching cancel.request）
            _validate_recovery_evidence(output_dir, task_id, cancel_mode, reason)

        # 6. 同一临界区内提交（req 1/2/3：共享锁内 helper；调用方已持锁，不再次
        #    acquire；canonical identity / evidence 与 commit 之间零 gap）
        canonical = _finalize_terminal_locked(
            output_dir,
            prev,
            task_id=task_id,
            status="CANCELLED",
            task_path=Path(output_dir) / "TASK.md",  # TASK.md 不一定存在；仅作 task.json 记录
            workspace=workspace,
            report_path=str(Path(output_dir) / "REPORT.md"),
            reason="CANCEL_REQUESTED",
            terminal_reason=final_reason,
            cancel_mode=cancel_mode,
        )

    # 8. reconciliation（已有终态也必须走；§6B.21 不再“发现终态直接 return”；
    #    锁外执行：reconciliation 不得修改 canonical terminal，crash 后可重跑）
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
