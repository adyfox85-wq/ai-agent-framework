"""AI Agent Framework — Core-owned Reconciliation Protocol（Phase E §6B.6–§6B.8）。

职责：
- 基于 canonical task.json terminal record（唯一 canonical terminal truth，§6B.5）
  幂等补齐 / 修复派生产物：run.json、REPORT.md
- 不臆造终态：无 canonical terminal → 返回明确错误（ReconciliationError）
- 不得改变已提交的 terminal status / generation（canonical 不可变，§6B.8）
- 幂等：重复调用返回相同结果；完整一致 → no-op
- 属 Lifecycle Core（与 finalize_cancelled_task 同属 Core）；Launcher / UI 不自行修文件，
  只能调用本入口（§6B.6 / §6B.7-C/D）

触发时机（§6B.7）：normal finalization 提交后 / recovery finalizer 内 /
Launcher wait thread 发现派生产物不完整时 / Bridge 打开已终止任务检测到 inconsistency 时。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import cancel as cancel_mod
from .context_packet import sha256_text
from .lock_utils import LockError, LockTimeout, task_state_lock
from .report import build_report
from .task_lifecycle import (
    read_canonical_terminal,
    read_status,
    task_json_path,
)

# 默认超时与锁参数
RECONCILE_LOCK_TIMEOUT = 10.0


class ReconciliationError(RuntimeError):
    """无 canonical terminal 或派生修复失败（不得静默）。"""


@dataclass
class ReconciliationResult:
    """一次 reconciliation 的结果（供 Launcher 更新 last_run.json，§6B.6-3）。"""

    status: str
    terminal_generation: int | None
    task_id: str
    output_dir: str
    report_path: str | None
    actions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "terminal_generation": self.terminal_generation,
            "task_id": self.task_id,
            "output_dir": self.output_dir,
            "report_path": self.report_path,
            "actions": self.actions,
        }


def _run_json_path(output_dir: Path) -> Path:
    return output_dir / "run.json"


def _report_path_for(output_dir: Path) -> Path:
    return output_dir / "REPORT.md"


def _expected_run_json(canonical, task_id: str, now_iso: str) -> dict:
    expected = {
        "timestamp": canonical.terminal_at or now_iso,
        "status": canonical.status,
        "task_id": task_id,
    }
    if canonical.terminal_generation is not None:
        expected["terminal_generation"] = canonical.terminal_generation
    return expected


def _run_json_consistent(path: Path, canonical, task_id: str) -> bool:
    """run.json 是否已跟随 canonical（status + generation 一致）。"""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return (
        data.get("status") == canonical.status
        and data.get("terminal_generation") == canonical.terminal_generation
    )


def _report_consistent(path: Path, canonical) -> bool:
    """REPORT.md 是否已跟随 canonical（Current Status 行 + Terminal Generation 行一致）。

    legacy canonical（无 generation）不要求 generation 行（无法补——canonical 不可改）。
    """
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    status_ok = f"## Current Status\n{canonical.status}" in text
    gen_ok = (
        canonical.terminal_generation is None
        or f"## Terminal Generation\n{canonical.terminal_generation}" in text
    )
    return status_ok and gen_ok


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise ReconciliationError(f"派生产物写入失败: {path} ({exc})") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _atomic_write_json(path: Path, data: dict) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _build_report_from_artifacts(output_dir: Path, canonical, task_id: str) -> str:
    """根据 canonical + 磁盘已有 artifacts 重建 REPORT（§6B.8：根据 canonical terminal
    record + 已有 agent artifacts 生成）。

    - route：route.json（缺失 → 空 route）
    - agent results：<agent>_result.md（缺失 → 不加入）
    - Original Task：TASK.snapshot.md 优先（immutable execution snapshot，FIX-002
      Req 1/2）；无 snapshot（legacy 目录）→ task.json.task_path 指向的文件
    - CANCELLED：从 cancel.request（若仍存在）读取 requested_at
    """
    task_text = ""
    task_ref_path = None
    intake_task_path = None
    snapshot = output_dir / "TASK.snapshot.md"
    if snapshot.exists():
        try:
            task_text = snapshot.read_text(encoding="utf-8")
            task_ref_path = str(snapshot)
        except OSError:
            task_text = ""
    # intake path（active TASK 原始路径）只作为 provenance，不是 execution authority
    try:
        task_json = read_status(output_dir) or {}
        intake_task_path = task_json.get("task_path")
    except Exception:
        intake_task_path = None
    if not task_text:
        try:
            task_json = read_status(output_dir) or {}
            tp = task_json.get("task_path")
            if tp and Path(tp).exists():
                task_text = Path(tp).read_text(encoding="utf-8")
                task_ref_path = str(tp)
        except Exception:
            task_text = ""

    route: list[str] = []
    route_path = output_dir / "route.json"
    if route_path.exists():
        try:
            data = json.loads(route_path.read_text(encoding="utf-8"))
            agents = data.get("agents") if isinstance(data, dict) else None
            if isinstance(agents, list):
                route = [str(a) for a in agents]
        except (json.JSONDecodeError, OSError):
            route = []

    results: dict[str, str] = {}
    for agent in route:
        rf = output_dir / f"{agent}_result.md"
        if rf.exists():
            try:
                results[agent] = rf.read_text(encoding="utf-8")
            except OSError:
                pass

    terminal = canonical.to_dict()
    if canonical.status == "CANCELLED":
        req, _ = cancel_mod.inspect_cancel_request(output_dir)
        if req is not None:
            terminal["cancel_requested_at"] = req.requested_at
        terminal["task_id"] = task_id
    return build_report(
        task_text, route, results, canonical.status, integrity_notes=None, terminal=terminal,
        task_path=task_ref_path,
        task_hash=sha256_text(task_text) if task_text else None,
        output_dir=output_dir,
        intake_task_path=intake_task_path,
    )


def reconcile_terminal_artifacts(
    task_id: str,
    workspace: Path | str,
    output_dir: Path | str,
    *,
    lock_timeout: float = RECONCILE_LOCK_TIMEOUT,
) -> ReconciliationResult:
    """幂等补齐 / 修复派生产物（run.json / REPORT.md），使其跟随 canonical terminal。

    - 无 canonical terminal（task.json 缺失或尚无终态）→ ReconciliationError，不臆造终态
    - canonical 只读：本函数绝不修改 task.json 的 terminal status / generation
    - 锁内完成（与 finalizer 串行；保证 canonical 读一致）
    """
    output_dir = Path(output_dir)
    if not task_json_path(output_dir).exists():
        raise ReconciliationError(
            f"无 canonical task.json（{task_json_path(output_dir)}），无法 reconciliation"
        )

    with task_state_lock(output_dir, task_id, timeout=lock_timeout):
        canonical = read_canonical_terminal(output_dir)
        if canonical is None:
            raise ReconciliationError(
                f"无 canonical terminal（{task_json_path(output_dir)} 尚无终态），无法 reconciliation——不臆造终态"
            )

        actions: list[str] = []
        now_iso = datetime.now().isoformat(timespec="seconds")

        # --- run.json（跟随 canonical status + generation） ---
        run_path = _run_json_path(output_dir)
        if not _run_json_consistent(run_path, canonical, task_id):
            if not run_path.exists():
                actions.append("run.json created (follow canonical)")
            else:
                actions.append("run.json refreshed to canonical (stale/conflict)")
            _atomic_write_json(run_path, _expected_run_json(canonical, task_id, now_iso))

        # --- REPORT.md（跟随 canonical status + generation） ---
        report_path = _report_path_for(output_dir)
        if not _report_consistent(report_path, canonical):
            if not report_path.exists():
                actions.append("REPORT.md created (follow canonical)")
            else:
                actions.append("REPORT.md refreshed to canonical (stale/conflict)")
            _atomic_write_text(report_path, _build_report_from_artifacts(output_dir, canonical, task_id))

        if not actions:
            actions.append("no-op (derived artifacts consistent with canonical)")

    return ReconciliationResult(
        status=canonical.status,
        terminal_generation=canonical.terminal_generation,
        task_id=task_id,
        output_dir=str(output_dir),
        report_path=str(report_path) if report_path.exists() else None,
        actions=actions,
    )


def main(argv: list[str] | None = None) -> int:
    """正式 Core entry point（TASK-005-B：Launcher wait thread 经子进程调用，
    §6B.7-C / §14.4 防侵入规则——Desktop Shell 不直接 import Core 执行逻辑）。"""
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="python -m ai_agent_framework.reconcile",
        description=(
            "Core-owned reconciliation（幂等补齐 run.json / REPORT.md 跟随 canonical "
            "terminal；不改 canonical；无终态不臆造）。"
        ),
    )
    p.add_argument("--task-id", required=True, help="Task ID")
    p.add_argument("--workspace", required=True, help="Business project workspace")
    p.add_argument("--output", required=True, help="Task output dir (.aaf/<Task-ID>)")
    p.add_argument("--lock-timeout", type=float, default=10.0, help="state.lock acquire timeout (s)")
    args = p.parse_args(argv)

    try:
        result = reconcile_terminal_artifacts(
            args.task_id, args.workspace, args.output, lock_timeout=args.lock_timeout
        )
    except LockTimeout as exc:
        print(f"RECONCILE_BUSY: {exc}", file=sys.stderr)
        return 4
    except ReconciliationError as exc:
        print(f"RECONCILE_ERROR: {exc}", file=sys.stderr)
        return 5
    except Exception as exc:  # noqa: BLE001 —— CLI 边界：明确错误码
        print(f"RECONCILE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
