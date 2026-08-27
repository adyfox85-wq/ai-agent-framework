from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .adapters import build_prompt, run_agent
from . import cancel as cancel_mod
from . import project_boundary
from . import task_lifecycle
from .report import build_report, verdict_blocked
from .reconcile import reconcile_terminal_artifacts
from .router import Route, decide_route
from .task_lifecycle import (
    TERMINAL_REASON_CANCEL_REQUESTED,
    TERMINAL_REASON_FRAMEWORK_ERROR,
    TERMINAL_REASON_NORMAL_COMPLETION,
    TERMINAL_REASON_WAITING,
    finalize_terminal,
)
from .task_validation import TaskValidationError, parse_task_fields, validate_task_text

# soft cancel 的 runner 退出码：0（REPORT 已生成；Launcher 不得仅凭 exit code 把
# CANCELLED 判 FAILED——§6A.5 exit code 只是 evidence，不是判定）
CANCEL_EXIT_CODE = 0


def _result_is_valid(body: str) -> bool:
    body = body.strip()
    return bool(body) and not body.startswith('FRAMEWORK_ERROR')


def _aggregate_status(agents: list[str], results: dict[str, str]) -> str:
    """所有必需节点通过（无缺失 / FRAMEWORK_ERROR / FAILED / FAIL / REQUEST_CHANGE）→ SUCCESS，否则 WAITING。"""
    for agent in agents:
        if verdict_blocked(agent, results.get(agent, '')):
            return 'WAITING'
    return 'SUCCESS'


def _load_resume_state(output_dir: Path) -> tuple[Route, dict[str, str]]:
    """从已有输出目录恢复：route.json + 非 FRAMEWORK_ERROR 的 agent 结果。"""
    route_data = json.loads((output_dir / 'route.json').read_text(encoding='utf-8'))
    route = Route(route_data['agents'], route_data['reason'])
    results: dict[str, str] = {}
    for agent in route.agents:
        rf = output_dir / f'{agent}_result.md'
        if rf.exists():
            body = rf.read_text(encoding='utf-8')
            if not body.strip().startswith('FRAMEWORK_ERROR'):
                results[agent] = body
    return route, results


def _check_cancel(output_dir: Path, task_id: str, task_file: Path, workspace: Path) -> bool:
    """Safe checkpoint：读取 cancel.request（§6.3 / §6A.11）。

    - 无请求 / 无效请求（warning 记录，不拒绝执行，§6A.15）→ False（继续）
    - 有效请求 → Core 收敛：task.json(CANCELLED) → run.json(CANCELLED) →
      REPORT(CANCELLED)（§6A.4 顺序；经 state.lock 锁内提交 + reconciliation）
    - 若已有其他终态（如 SUCCESS 已 canonical committed）→ 保留现有终态，
      derived artifacts 跟随 canonical（§6A.2 late cancel 被吸收）
    - 返回 True = 任务已终态化（调用方应停止后续 Agent）
    """
    req, warning = cancel_mod.inspect_cancel_request(output_dir)
    if warning:
        print(f"[cancel] {warning}", file=sys.stderr)
        return False
    if req is None:
        return False
    if req.task_id != task_id:
        print(
            f"[cancel] cancel.request task_id 不匹配（{req.task_id!r} != {task_id!r}），已忽略",
            file=sys.stderr,
        )
        return False
    finalize_terminal(
        output_dir,
        task_id=task_id,
        status='CANCELLED',
        task_path=task_file,
        workspace=workspace,
        report_path=str(output_dir / 'REPORT.md'),
        reason='CANCEL_REQUESTED',
        terminal_reason=TERMINAL_REASON_CANCEL_REQUESTED,
        cancel_mode='soft',
    )
    # derived artifacts 跟随 canonical（幂等；若为 absorbed 场景则按其终态重建）
    reconcile_terminal_artifacts(task_id, workspace, output_dir)
    return True


def run(task_file: Path, workspace: Path, output_dir: Path, dry_run: bool = False, resume_from: Path | None = None) -> Path:
    task = task_file.read_text(encoding='utf-8')

    # 正式 Task Validation（权威执行边界）：失败即中止，不进 Router / 不启动 Agent / 不进 Lifecycle
    result = validate_task_text(task)
    if not result.valid:
        raise TaskValidationError(result)

    task_id = parse_task_fields(task)["Task ID"]

    try:
        # --- Lifecycle 状态编排（确定性，不调用 LLM） ---
        def _ls(status, *, report_path=None, reason=None, stage=None, agent=None, phase_state="RUNNING"):
            task_lifecycle.update_status(
                output_dir,
                task_id=task_id,
                status=status,
                task_path=task_file,
                workspace=workspace,
                report_path=report_path,
                reason=reason,
                stage=stage,
                agent=agent,
                phase_state=phase_state,
            )

        def _finalize(status, *, report_path=None, reason=None, stage=None, agent=None, phase_state=None,
                      terminal_reason=None, cancel_mode=None):
            return finalize_terminal(
                output_dir,
                task_id=task_id,
                status=status,
                task_path=task_file,
                workspace=workspace,
                report_path=report_path,
                reason=reason,
                stage=stage,
                agent=agent,
                phase_state=phase_state,
                terminal_reason=terminal_reason,
                cancel_mode=cancel_mode,
            )

        # 检查点：Validation 完成后 / Boundary 前（取消 → 不启动后续任何环节）
        if _check_cancel(output_dir, task_id, task_file, workspace):
            return output_dir / 'REPORT.md'

        if resume_from is not None:
            route, results = _load_resume_state(resume_from)
            output_dir = resume_from
            _ls('RUNNING', reason='RESUMED')  # WAITING/... → RUNNING
        else:
            # --- Boundary Check（Validation 通过后、Router 前；warning-first，fail-open）---
            # 不阻断执行；边界模块自身错误也 fail-open（外围功能不使核心链路不可用）
            try:
                boundary = project_boundary.load_boundary(workspace)
                bcheck = project_boundary.check_task(boundary, task)
                project_boundary.write_boundary_json(output_dir, task_id, bcheck, boundary.source_path)
            except project_boundary.BoundaryError as exc:
                bcheck = project_boundary.BoundaryCheckResult(
                    configured=False,
                    warnings=[f"BOUNDARY_CHECK_ERROR: {exc}"],
                    matched_boundaries=[],
                    severity="NONE",
                    checked_at=datetime.now().isoformat(timespec="seconds"),
                )
                project_boundary.write_boundary_json(output_dir, task_id, bcheck, None)
            route = decide_route(task)
            results = {}
            _ls('CREATED')  # 通过 Validation，尚未执行 Agent 链

        output_dir.mkdir(parents=True, exist_ok=True)

        (output_dir / 'route.json').write_text(
            json.dumps({'agents': route.agents, 'reason': route.reason}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        dry = bool(dry_run)
        if dry:
            status = 'DRY_RUN'  # 保留现有 dry-run 语义（route only，不执行 Agent）
            final_status = 'CREATED'  # 未正式执行 Agent 链 → 终态保持 CREATED，不伪装 SUCCESS
        else:
            # 检查点：Boundary 完成后 / Hermes 前（取消 → Hermes 不启动）
            if _check_cancel(output_dir, task_id, task_file, workspace):
                return output_dir / 'REPORT.md'
            _ls('RUNNING', reason=('RESUMED' if resume_from is not None else None))  # 真正进入执行链
            for agent in route.agents:
                if agent in results:
                    continue  # resume：复用已完成结果，不重复执行
                # 检查点：上一 Agent 完成后 / 下一 Agent 前
                # （Hermes 完成后 / WorkBuddy 前；WorkBuddy 完成后 / Codex 前）
                if _check_cancel(output_dir, task_id, task_file, workspace):
                    return output_dir / 'REPORT.md'
                stage_name = agent.upper()
                _ls('RUNNING', stage=stage_name, agent=agent, phase_state='RUNNING')
                prompt = build_prompt(agent, task, results, workspace)
                (output_dir / f'{agent}_prompt.md').write_text(prompt, encoding='utf-8')
                try:
                    result_text = run_agent(agent, prompt, workspace)
                except Exception as exc:
                    result_text = f'FRAMEWORK_ERROR\n{type(exc).__name__}: {exc}'
                results[agent] = result_text
                (output_dir / f'{agent}_result.md').write_text(result_text, encoding='utf-8')
                valid = _result_is_valid(result_text)
                _ls('RUNNING', stage=stage_name, agent=agent, phase_state=('SUCCESS' if valid else 'FAILED'))
                if not valid:
                    break  # 执行链保护：必需节点无有效结果 → 停止后续节点
            # 检查点：Codex 完成后 / Report finalization 前
            if _check_cancel(output_dir, task_id, task_file, workspace):
                return output_dir / 'REPORT.md'
            status = _aggregate_status(route.agents, results)
            final_status = 'SUCCESS' if status == 'SUCCESS' else 'WAITING'

        # 执行链完整性保护：必需 Executor / Validator 无有效结果 → REPORT 明确标记
        # （dry-run 不执行 Agent，属预期，不生成误导性 notes）
        integrity_notes = []
        if not dry:
            if 'hermes' in route.agents and not _result_is_valid(results.get('hermes', '')):
                integrity_notes.append('Required executor Hermes did not run or produced no valid result')
            if 'workbuddy' in route.agents and not _result_is_valid(results.get('workbuddy', '')):
                integrity_notes.append('Required validator WorkBuddy did not run or produced no valid result')

        report = build_report(task, route.agents, results, status, integrity_notes)
        report_path = output_dir / 'REPORT.md'

        # REPORT 阶段完成 + 终态（dry-run: CREATED + reason=DRY_RUN；REPORT 生成后回填 report_path）
        if not dry:
            # §6A.4 artifact order：Core 裁决 → task.json 终态提交（锁内）→ run.json → REPORT
            _ls('RUNNING', stage='REPORT', agent=None, phase_state='SUCCESS')
            terminal_reason = (
                TERMINAL_REASON_NORMAL_COMPLETION if final_status == 'SUCCESS' else TERMINAL_REASON_WAITING
            )
            canonical = _finalize(
                final_status,
                report_path=report_path,
                stage='COMPLETED',
                agent=None,
                phase_state=('SUCCESS' if final_status == 'SUCCESS' else 'WAITING'),
                terminal_reason=terminal_reason,
            )
            if canonical.status != final_status:
                # 另一 finalizer 先 commit（§6B.18 Case B：如 recovery 已写 CANCELLED）：
                # 保留现有 canonical，派生产物跟随 canonical（不覆盖成 SUCCESS/WAITING）
                reconcile_terminal_artifacts(task_id, workspace, output_dir)
                report_path = output_dir / 'REPORT.md'
            else:
                # 我们胜出：run.json 跟随 canonical terminal（status + generation）
                (output_dir / 'run.json').write_text(
                    json.dumps(
                        {
                            'timestamp': canonical.terminal_at or datetime.now().isoformat(timespec='seconds'),
                            'status': canonical.status,
                            'terminal_generation': canonical.terminal_generation,
                            'task_id': task_id,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding='utf-8',
                )
                # REPORT 跟随 canonical（附加 Terminal Generation provenance，§6B.4）
                report = build_report(
                    task, route.agents, results, status, integrity_notes, terminal=canonical.to_dict()
                )
                report_path.write_text(report, encoding='utf-8')
        else:
            _ls(final_status, report_path=report_path, reason=('DRY_RUN' if dry else None))
            report_path.write_text(report, encoding='utf-8')
        return report_path
    except TaskValidationError:
        raise  # Validation 失败：不进 Lifecycle（不生成虚假状态）
    except Exception as exc:
        # Framework 级失败：锁内提交 FAILED 终态后重新抛出（保持调用方行为；异常中断也有明确 lifecycle 记录）
        try:
            finalize_terminal(
                output_dir,
                task_id=task_id,
                status='FAILED',
                task_path=task_file,
                workspace=workspace,
                reason=f'FRAMEWORK_ERROR: {type(exc).__name__}: {exc}',
                terminal_reason=TERMINAL_REASON_FRAMEWORK_ERROR,
            )
        except Exception:
            pass  # FAILED 记录本身失败不能掩盖原始异常
        raise


def main() -> None:
    p = argparse.ArgumentParser(description='AI Agent Framework v0.2 prototype runner')
    p.add_argument('task', type=Path, help='TASK.md path')
    p.add_argument('--workspace', type=Path, required=True, help='Business project workspace')
    p.add_argument('--output', type=Path, default=Path('.aaf-run'), help='Run output directory')
    p.add_argument('--dry-run', action='store_true', help='Route only; do not invoke agents')
    p.add_argument('--resume-from', type=Path, default=None, help='Resume an existing run output dir (reuses completed agent results)')
    args = p.parse_args()
    try:
        report = run(args.task, args.workspace, args.output, args.dry_run, args.resume_from)
    except TaskValidationError as exc:
        # 校验失败：清晰错误 + 非零退出；不进入 Router / 不启动 Agent
        print(str(exc))
        print(f"Task: {args.task}")
        raise SystemExit(2)
    print(report)


if __name__ == '__main__':
    main()
