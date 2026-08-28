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
    → terminal arbitration（已有终态 → 保留 canonical，不要求 evidence，不改写；
      force request loses——TASK-005-B req 22）
    → 无终态：锁内验证 recovery evidence
      （soft: 当前锁内仍有效的 matching cancel.request；
       force: TASK-005-B 结构化 force evidence 三方交叉验证
       ——evidence ↔ control.json ↔ Bridge launch registry）
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

TASK-005-B（AAF-v0.4-TASK-005-B，Process Ownership / Force Cancel / Recovery）：
- force recovery 不再一律拒绝（005-A 的 FORCE_RECOVERY_NOT_AVAILABLE 由
  ``ForceEvidenceError`` 取代）：force（cancel_mode=force 或
  reason=FORCE_CANCELLED）必须提供 ``force_evidence`` 结构化证据路径，
  并在 state.lock 临界区内完成三方交叉验证（evidence ↔ control.json ↔
  Bridge launch registry：launch_id / task_id / runner 身份 / ownership verified /
  非 superseded / 时间序 sane）——伪造 / 过期 / 不匹配 → 安全失败，零 canonical 写
- 已有终态 + force 请求 → 保留现有 terminal（arbitration 优先，force loses）

005-B-FIX-001（Force Recovery Authority and Successful Termination Proof Closure；
Codex 两个 blocking findings 闭合）：
- **canonical registry authority（blocker 1）**：Core 由 canonical Bridge registry
  root + launch_id 推导 registry path（``bridge.launch_registry`` 官方
  path/schema/read contract，``AAF_BRIDGE_DIR`` / ``~/.aaf-bridge`` 唯一根）；
  evidence.registry_path 只是 proof，必须严格等于 canonical path——不得把它当
  authority locator，不得手工读任意 JSON 充当 registry
- **canonical evidence location（req 2）**：force evidence 必须位于
  ``<registry_root>/<launch_id>.force-evidence.json``；任意外部 evidence 文件路径
  → 拒绝授权 CANCELLED
- **successful termination proof（blocker 2 / req 5）**：只有
  ``termination_exit_status == 0``（Windows 当前 termination contract）才授权新的
  CANCELLED；nonzero / missing / malformed → fail closed
- **durable bridge evidence（req 6）**：registry 必须独立记录 force termination
  关键事实（requested / observed / exit status / evidence path / verification
  result+checks），Core 锁内逐项核对与 evidence 一致
- **三方 identity 全量（req 3/4）**：task / launch / workspace / output / PID /
  creation time / expected entry / normalized command line / registry state
  全部一致；任一 mismatch → fail closed，不得产生新的 CANCELLED

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
from datetime import datetime
from pathlib import Path

from . import cancel as cancel_mod
from . import control as control_mod
from . import force_evidence as force_evidence_mod
from . import proc_identity
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
# FIX-001（req 1/3）：复用正式 registry path/schema/read contract（bridge-owned
# canonical root + launch_id 推导），不得再手工信任任意 JSON / 任意路径。
from bridge import launch_registry as reg_mod

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_LOCK_TIMEOUT = 4
EXIT_RECONCILE_ERROR = 5
EXIT_RECOVERY_ERROR = 6  # identity / evidence / force-evidence 校验失败（安全失败）


class RecoveryError(RuntimeError):
    """Recovery 校验失败：不得写 canonical、不得 reconciliation 变更。"""


class RecoveryEvidenceError(RecoveryError):
    """Soft recovery evidence（cancel.request）缺失 / 损坏 / 不匹配 / 非法。"""


class ForceEvidenceError(RecoveryEvidenceError):
    """Force recovery evidence（结构化 force evidence）缺失 / 损坏 / 不匹配 / 非法。

    TASK-005-B：force recovery 不再“一律拒绝”（005-A 的 FORCE_RECOVERY_NOT_AVAILABLE
    由本类取代）——只有在真实 launch_id / registry / control / verified ownership /
    termination evidence 全部满足时才允许 finalizer 提交 CANCELLED（req 20-22）。
    """


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
    force_evidence: Path | str | None = None,
    workspace: str | None = None,
) -> None:
    """在“准备新提交 CANCELLED”前验证 recovery evidence（FIX-001 req 8/10/12 + TASK-005-B）。

    FIX-002：**必须由调用方在 state.lock 临界区内调用**——evidence 验证与
    CANCELLED commit 同属一个临界区（req 5：evidence 必须 lock-stable；验证后、
    commit 前不 release lock；不得在锁外验证后再提交）。

    - force → ``_validate_force_evidence``（TASK-005-B：结构化 force evidence
      三方交叉验证；FIX-001：canonical authority 绑定 + 成功终止证明；
      伪造 / 非 canonical / 过期 / 不匹配 → ForceEvidenceError，零 canonical 写）
    - soft → 必须存在合法 matching cancel.request（parseable / soft_cancel /
      task_id 匹配 / requested_at 合法）；任何缺失/损坏/mismatch → RecoveryEvidenceError，
      不写 canonical
    - 旧 ``evidence`` 参数仅作 diagnostic note（由调用方拼入 terminal_reason），
      不在此充当 authority evidence
    """
    if cancel_mode == CANCEL_MODE_FORCE or reason == TERMINAL_REASON_FORCE_CANCELLED:
        if force_evidence is None:
            raise ForceEvidenceError(
                "FORCE_EVIDENCE_REQUIRED: force recovery 必须提供结构化 force evidence "
                "路径（TASK-005-B req 21）；不得凭任意字符串 evidence 提交 CANCELLED"
            )
        _validate_force_evidence(output_dir, task_id, Path(force_evidence), workspace=workspace)
        return
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


def _path_eq(a: object, b: object) -> bool:
    """规范化路径相等（非空 + 绝对化 + normcase；与 ownership 同规则）。"""
    return bool(a and b and proc_identity.canonicalize_path(str(a)) == proc_identity.canonicalize_path(str(b)))


def _cmdline_eq(a: object, b: object) -> bool:
    """expected_command_line 规范化逐位置相等（registry/control/evidence 三方同源）。"""
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return proc_identity.canonicalize_command_line(a) == proc_identity.canonicalize_command_line(b)


def _validate_force_evidence(
    output_dir: Path,
    task_id: str,
    force_evidence_path: Path,
    workspace: str | None = None,
) -> None:
    """**锁内**验证 force recovery evidence（FIX-001 req 1–7；TASK-005-B req 20/22）。

    三方交叉验证（evidence ↔ control.json ↔ Bridge launch registry；§6B.13/§6B.14），
    authority 根由 **canonical Bridge registry root + launch_id** 推导（FIX-001
    blocker 1 闭合：不得把 evidence.registry_path 当作 locator）：

    1. evidence 结构合法（schema_version/kind/verification_result/字段集）
    2. evidence.task_id == 请求 task_id（canonical identity 已由调用方锁内验证）
    3. canonical path binding（FIX-001 req 1/2）：
       - evidence 文件必须位于 ``<registry_root>/<launch_id>.force-evidence.json``
         （bridge.launch_registry 官方 path contract；任意外部路径 → 拒绝）
       - evidence.registry_path proof 必须严格等于 canonical registry path
       - evidence.control_path proof 必须严格等于本任务 control.json
    4. 成功终止证明（FIX-001 req 5）：``termination_exit_status == 0``——
       nonzero / missing / malformed → fail closed，不得授权新的 CANCELLED
    5. control.json 交叉（lock-stable）：launch_id / task_id / 非 superseded /
       force_terminate_requested == true / runner_pid / runner_creation_time /
       workspace / expected_runner_entry / expected_command_line
    6. registry 交叉（官方 read contract，canonical path 推导）：
       launch_id / task_id / workspace / output_dir（== 本任务 output_dir）/
       runner_pid / runner_creation_time / expected_runner_entry /
       expected_command_line / state（PREPARED / SUPERSEDED 拒绝）
    7. durable bridge evidence（FIX-001 req 6）：registry 必须独立记录 force
       termination 关键事实并与 evidence 逐项一致——requested_at / observed_at /
       exit status / evidence path / verification result+checks
    8. 时间序 sane：termination_observed_at >= termination_requested_at

    任一失败 → ForceEvidenceError（fail safely：零 canonical 写、零 generation bump）。
    """
    ev, err = force_evidence_mod.read_force_evidence(force_evidence_path)
    if err:
        raise ForceEvidenceError(f"FORCE_EVIDENCE_ERROR: {err}")

    if ev.get("task_id") != task_id:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence task_id {ev.get('task_id')!r} "
            f"!= 请求 task_id {task_id!r}（mismatch → fail safely）"
        )
    launch_id = ev.get("launch_id")
    if not isinstance(launch_id, str) or not launch_id:
        raise ForceEvidenceError("FORCE_EVIDENCE_ERROR: evidence.launch_id 缺失/非法")

    # --- req 1/2：canonical authority path（bridge 官方 path contract 推导）---
    canonical_reg_path = reg_mod.registry_path(launch_id)
    canonical_ev_path = reg_mod.force_evidence_path_for(launch_id)

    # req 2：evidence 文件必须位于 canonical Bridge location——不得接受任意外部
    # evidence 文件授权 CANCELLED
    if not _path_eq(force_evidence_path, canonical_ev_path):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence 文件不在 canonical Bridge location: "
            f"{force_evidence_path} != {canonical_ev_path}——任意外部 evidence 不得授权 CANCELLED"
        )
    # req 1：evidence.registry_path 只作 proof，必须严格等于 canonical registry path
    if not _path_eq(ev.get("registry_path") or "", canonical_reg_path):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence.registry_path {ev.get('registry_path')!r} "
            f"!= canonical registry path {canonical_reg_path}——不得把任意路径当作 authority locator"
        )

    # --- req 5：successful termination proof（Windows contract：exit 0）---
    term_status = ev.get("termination_exit_status")
    if term_status != force_evidence_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: termination_exit_status {term_status!r} != "
            f"{force_evidence_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS}——只有 verified "
            f"successful termination 才能授权新的 CANCELLED（nonzero/missing/malformed → fail closed）"
        )

    # --- control.json 交叉（锁内读取——与 commit 同一临界区，lock-stable）---
    control, cerr = control_mod.read_control(output_dir)
    if control is None:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: 缺少可验证的 control.json（{control_mod.control_path(output_dir)}）"
            f"{'——' + cerr if cerr else ''}——force recovery 必须存在 task-owned control artifact"
        )
    if control.get("launch_id") != launch_id:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence launch_id {launch_id!r} "
            f"!= control.launch_id {control.get('launch_id')!r}（launch 不匹配）"
        )
    if control.get("task_id") != task_id:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: control.task_id {control.get('task_id')!r} "
            f"!= 请求 task_id {task_id!r}"
        )
    if control.get("superseded_by"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: control 已 superseded（superseded_by="
            f"{control.get('superseded_by')!r}）——stale evidence 拒绝"
        )
    if control.get("force_terminate_requested") is not True:
        raise ForceEvidenceError(
            "FORCE_EVIDENCE_ERROR: control.force_terminate_requested != true——"
            "Launcher 未确认该 launch 的 force termination 请求，evidence 与 control 不匹配"
        )
    if control.get("runner_pid") != ev.get("runner_pid"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence runner_pid {ev.get('runner_pid')!r} "
            f"!= control.runner_pid {control.get('runner_pid')!r}"
        )
    # req 4：creation time 三方一致（缺失/不可解析 → fail closed）
    if not proc_identity.creation_times_equal(
        control.get("runner_creation_time"), ev.get("runner_creation_time")
    ):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence runner_creation_time "
            f"{ev.get('runner_creation_time')!r} 与 control "
            f"{control.get('runner_creation_time')!r} 不一致/缺失"
        )
    # req 4：workspace 三方一致
    if not _path_eq(control.get("workspace") or "", ev.get("workspace") or ""):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence workspace {ev.get('workspace')!r} "
            f"!= control.workspace {control.get('workspace')!r}"
        )
    # req 3/4：expected runner entry / normalized command line
    if control.get("expected_runner_entry") != ev.get("expected_runner_entry"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence expected_runner_entry "
            f"{ev.get('expected_runner_entry')!r} != control "
            f"{control.get('expected_runner_entry')!r}"
        )
    if not _cmdline_eq(control.get("expected_command_line"), ev.get("expected_command_line")):
        raise ForceEvidenceError(
            "FORCE_EVIDENCE_ERROR: evidence expected_command_line 与 control 不一致"
        )
    # control_path proof 字段必须指向本任务 control.json
    if not _path_eq(ev.get("control_path") or "", control_mod.control_path(output_dir)):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence.control_path {ev.get('control_path')!r} "
            f"!= 本任务 control.json（{control_mod.control_path(output_dir)}）"
        )

    # --- Bridge launch registry 交叉（官方 read contract：schema 验证 + canonical path）---
    registry, reg_err = reg_mod.read_registry(launch_id)
    if reg_err:
        raise ForceEvidenceError(f"FORCE_EVIDENCE_ERROR: registry 不可用: {reg_err}")
    if registry is None:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: canonical registry 不存在（{canonical_reg_path}）——"
            f"不得以任意外部 JSON 充当 registry"
        )
    if registry.get("launch_id") != launch_id:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.launch_id {registry.get('launch_id')!r} "
            f"!= evidence.launch_id {launch_id!r}"
        )
    if registry.get("task_id") != task_id:
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.task_id {registry.get('task_id')!r} "
            f"!= 请求 task_id {task_id!r}"
        )
    # req 3/4：workspace / output_dir 三方一致（output_dir 还必须 == 本任务 output_dir）
    if not _path_eq(registry.get("workspace") or "", ev.get("workspace") or ""):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence workspace {ev.get('workspace')!r} "
            f"!= registry.workspace {registry.get('workspace')!r}"
        )
    if not _path_eq(registry.get("output_dir") or "", ev.get("output_dir") or ""):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence output_dir {ev.get('output_dir')!r} "
            f"!= registry.output_dir {registry.get('output_dir')!r}"
        )
    if not _path_eq(registry.get("output_dir") or "", output_dir):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.output_dir {registry.get('output_dir')!r} "
            f"!= 本任务 output_dir {output_dir}"
        )
    if workspace is not None and not _path_eq(registry.get("workspace") or "", workspace):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: 请求 workspace {workspace!r} != registry.workspace "
            f"{registry.get('workspace')!r}"
        )
    if registry.get("runner_pid") != ev.get("runner_pid"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence runner_pid {ev.get('runner_pid')!r} "
            f"!= registry.runner_pid {registry.get('runner_pid')!r}"
        )
    if not proc_identity.creation_times_equal(
        registry.get("runner_creation_time"), ev.get("runner_creation_time")
    ):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence runner_creation_time "
            f"{ev.get('runner_creation_time')!r} 与 registry "
            f"{registry.get('runner_creation_time')!r} 不一致/缺失"
        )
    if registry.get("expected_runner_entry") != ev.get("expected_runner_entry"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: evidence expected_runner_entry "
            f"{ev.get('expected_runner_entry')!r} != registry "
            f"{registry.get('expected_runner_entry')!r}"
        )
    if not _cmdline_eq(registry.get("expected_command_line"), ev.get("expected_command_line")):
        raise ForceEvidenceError(
            "FORCE_EVIDENCE_ERROR: evidence expected_command_line 与 registry 不一致"
        )
    # registry state：RUNNING / EXITED 可授权；PREPARED（runner 从未启动，不可能有
    # verified termination）/ SUPERSEDED（stale）/ 非法值 → 拒绝（req 4/7）
    reg_state = registry.get("state")
    if reg_state == reg_mod.REGISTRY_STATE_PREPARED:
        raise ForceEvidenceError(
            "FORCE_EVIDENCE_ERROR: registry 仍 PREPARED——runner 从未启动，"
            "不可能存在已验证的 force termination"
        )
    if reg_state == reg_mod.REGISTRY_STATE_SUPERSEDED:
        raise ForceEvidenceError("FORCE_EVIDENCE_ERROR: registry 已 SUPERSEDED——stale evidence 拒绝")
    if reg_state not in (reg_mod.REGISTRY_STATE_RUNNING, reg_mod.REGISTRY_STATE_EXITED):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry state 非法 {reg_state!r}"
            f"（仅 RUNNING / EXITED 可授权 CANCELLED）"
        )

    # --- durable bridge evidence（req 6：Core 独立核对 registry ↔ evidence 事实一致）---
    if registry.get("force_terminate_requested_at") != ev.get("termination_requested_at"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.force_terminate_requested_at "
            f"{registry.get('force_terminate_requested_at')!r} != evidence.termination_requested_at "
            f"{ev.get('termination_requested_at')!r}——registry 与 evidence 不一致"
        )
    if registry.get("force_termination_observed_at") != ev.get("termination_observed_at"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.force_termination_observed_at "
            f"{registry.get('force_termination_observed_at')!r} != evidence.termination_observed_at "
            f"{ev.get('termination_observed_at')!r}——registry 与 evidence 不一致"
        )
    if registry.get("force_termination_exit_status") != ev.get("termination_exit_status"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.force_termination_exit_status "
            f"{registry.get('force_termination_exit_status')!r} != evidence.termination_exit_status "
            f"{ev.get('termination_exit_status')!r}——registry 与 evidence 不一致"
        )
    if not _path_eq(registry.get("force_evidence_path") or "", canonical_ev_path):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.force_evidence_path "
            f"{registry.get('force_evidence_path')!r} != canonical evidence path "
            f"{canonical_ev_path}——registry 未指向本 evidence"
        )
    if registry.get("force_termination_verification_result") != ev.get("verification_result"):
        raise ForceEvidenceError(
            f"FORCE_EVIDENCE_ERROR: registry.force_termination_verification_result "
            f"{registry.get('force_termination_verification_result')!r} != evidence.verification_result "
            f"{ev.get('verification_result')!r}"
        )
    if registry.get("force_termination_verification_checks") != ev.get("verification_checks"):
        raise ForceEvidenceError(
            "FORCE_EVIDENCE_ERROR: registry.force_termination_verification_checks 与 "
            "evidence.verification_checks 不一致"
        )

    # 时间序 sane：observed >= requested（伪造时间序拒绝）
    try:
        req_ts = datetime.fromisoformat(ev["termination_requested_at"])
        obs_ts = datetime.fromisoformat(ev["termination_observed_at"])
    except (KeyError, TypeError, ValueError):
        raise ForceEvidenceError("FORCE_EVIDENCE_ERROR: termination 时间戳不可解析") from None
    if obs_ts < req_ts:
        raise ForceEvidenceError("FORCE_EVIDENCE_ERROR: termination_observed_at 早于 requested_at——时间序非法")


def finalize_cancelled_task(
    task_id: str,
    workspace: Path | str,
    output_dir: Path | str,
    *,
    reason: str = TERMINAL_REASON_CANCEL_REQUESTED,
    cancel_mode: str = CANCEL_MODE_SOFT,
    evidence: str | None = None,
    force_evidence: Path | str | None = None,
    lock_timeout: float = 10.0,
):
    """Core recovery finalizer（§6B.21 + FIX-001 + FIX-002 + TASK-005-B force path）。
    返回 canonical result dict。

    FIX-002 单一不可分割临界区（关闭 Codex 遗留 recovery TOCTOU blocker）::

        1. acquire state.lock
        2. 锁内 reload canonical task.json
        3. 锁内 identity 校验（canonical exists + task_id == 请求 task_id；req 4：
           canonical identity 必须 lock-stable，mismatch → RecoveryError，零写零 bump）
        4. 锁内 terminal arbitration：已有终态 → 保留 canonical（req 9：无 evidence
           也 preserve；reconciliation 仍执行；force request loses——req 22），不改写
        5. 无终态 → 锁内验证 recovery evidence（req 5/8：soft 必须存在当前锁内仍
           有效的 matching cancel.request；force 必须提供结构化 force evidence 路径
           并通过 ``_validate_force_evidence`` 三方交叉验证——TASK-005-B req 20/21/22）
           ——验证与 commit 之间 **不 release lock**（req 1/4）
        6. 经 ``_finalize_terminal_locked`` 提交 CANCELLED（req 2/3：共享锁内 helper，
           调用方已持锁，不重复 acquire；generation 恰一次 bump；无第三 terminal writer）
        7. release state.lock
        8. reconciliation（run.json / REPORT.md 跟随 canonical；req 10：锁外执行，
           canonical terminal 不被 reconciliation 修改；crash 后可重跑）
        9. 幂等：重复调用返回相同 canonical result

    - ``evidence``：仅 diagnostic note（req 12），不是 authority evidence；
      authority evidence = 锁内验证的 cancel.request（soft）/ TASK-005-B 结构化
      force evidence 路径（force，req 20-22）
    """
    output_dir = Path(output_dir)
    final_reason = reason
    if evidence:
        final_reason = f"{reason}: {evidence}"  # diagnostic note only（req 12）
    is_force = cancel_mode == CANCEL_MODE_FORCE or reason == TERMINAL_REASON_FORCE_CANCELLED

    # 1–7. 单一 state.lock 临界区：identity + arbitration + evidence + commit
    #       （force evidence 必需性检查在锁内 arbitration **之后**——已有终态时
    #         force request 无条件 loses，不因缺 evidence 报错，req 22）
    with task_state_lock(output_dir, task_id, timeout=lock_timeout):
        # 2/3. 锁内 reload + identity 校验（req 4：canonical identity lock-stable）
        prev = _validate_recovery_identity(output_dir, task_id)

        # 4. terminal arbitration（req 9/22）：已有终态 → 保留 canonical、不要求
        #    evidence、不改写（force request loses；统一经共享 helper 幂等返回）
        if not is_terminal_status(prev.get("status", "")):
            # 5. 锁内 evidence 验证（req 5/8/20-22：soft = 当前锁内仍有效的 matching
            #    cancel.request；force = canonical authority 绑定 + 三方交叉验证 +
            #    成功终止证明（FIX-001）的结构化 force evidence）
            _validate_recovery_evidence(
                output_dir, task_id, cancel_mode, reason,
                force_evidence=force_evidence, workspace=str(workspace),
            )

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
            reason=TERMINAL_REASON_FORCE_CANCELLED if is_force else "CANCEL_REQUESTED",
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
            "（<output_dir>/cancel.request: request=soft_cancel、task_id 匹配、\n"
            "requested_at 合法）。\n"
            "TASK-005-B：force cancel 必须先存在通过 ownership 三方验证的结构化\n"
            "force evidence（--force-evidence <path>；伪造/过期/不匹配 → 安全失败）。"
        ),
    )
    p.add_argument("--task-id", required=True, help="Task ID（必须与 canonical task.json.task_id 一致）")
    p.add_argument("--workspace", required=True, help="Business project workspace")
    p.add_argument("--output", required=True, help="Task output dir (.aaf/<Task-ID>)")
    p.add_argument(
        "--reason",
        default=TERMINAL_REASON_CANCEL_REQUESTED,
        choices=(TERMINAL_REASON_CANCEL_REQUESTED, TERMINAL_REASON_FORCE_CANCELLED),
        help="terminal_reason（FORCE_CANCELLED 要求 --force-evidence，TASK-005-B）",
    )
    p.add_argument(
        "--cancel-mode",
        default=CANCEL_MODE_SOFT,
        choices=(CANCEL_MODE_SOFT, CANCEL_MODE_FORCE),
        help="cancel_mode（force 要求 --force-evidence）",
    )
    p.add_argument(
        "--evidence",
        default=None,
        help="diagnostic note only（NOT authority evidence；authority evidence = "
        "validated cancel.request / TASK-005-B force evidence）",
    )
    p.add_argument(
        "--force-evidence",
        default=None,
        help="结构化 force evidence JSON 路径（force recovery 必需；TASK-005-B req 21）。"
        "finalizer 在 state.lock 临界区内交叉验证 evidence ↔ control.json ↔ "
        "Bridge launch registry",
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
            force_evidence=args.force_evidence,
            lock_timeout=args.lock_timeout,
        )
    except LockTimeout as exc:
        print(f"FINALIZATION_BUSY: {exc}", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    except RecoveryError as exc:
        # identity / evidence / force-evidence 校验失败：安全失败，CLI 与 library 同规则
        print(f"RECOVERY_FINALIZE_ERROR: {exc}", file=sys.stderr)
        return EXIT_RECOVERY_ERROR
    except Exception as exc:  # noqa: BLE001 —— CLI 边界：明确错误码
        print(f"RECOVERY_FINALIZE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RECONCILE_ERROR

    print(json.dumps(canonical.to_dict(), ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
