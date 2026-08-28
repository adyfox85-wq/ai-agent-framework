from __future__ import annotations

import json
import re
from pathlib import Path

from .task_validation import parse_task_fields


def _summarize(text: str, limit: int = 6000) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + '\n...[truncated by framework]'


def verdict_ok(agent: str, body: str) -> bool:
    """该 Agent 是否有明确通过结论（WorkBuddy PASS/PASS_WITH_WARNING、Codex APPROVE）。

    有通过结论时，报告内对历史 FAIL / REQUEST_CHANGE 的引用（如"原 REQUEST_CHANGE 已关闭"）
    不视为当前阻断。Hermes 正常完成即视为通过。
    """
    if agent == 'workbuddy':
        return bool(re.search(r'\bPASS_WITH_WARNING\b|\bPASS\b', body, re.IGNORECASE))
    if agent == 'codex':
        return bool(re.search(r'\bAPPROVE\b', body, re.IGNORECASE))
    return True


def verdict_blocked(agent: str, body: str) -> bool:
    """判定该 Agent 结果是否构成阻断（缺失 / FRAMEWORK_ERROR / 明确 FAILED / FAIL / REQUEST_CHANGE）。

    只认全大写结论标记（FAILED / FAIL / REQUEST_CHANGE）；小写/首字母大写的描述性动词
    （如 "Failed to read file"）属于工具级错误描述，不构成任务失败。

    RW-022：FAILED 分支同样允许通过结论逃逸——WorkBuddy PASS_WITH_WARNING / Codex APPROVE
    正文中的历史 FAILED 引用（如"原 FAILED 项已解决"、"FAILED 场景验证通过"）不是当前阻断；
    Hermes（无 verdict 语义）与无通过结论的正文仍按 FAILED 阻断（fail-safe）。
    """
    body = body.strip()
    if not body:
        return True
    if body.startswith('FRAMEWORK_ERROR'):
        return True
    # 显式失败结论（全大写）：任何 agent 都阻断；reviewer agent 已有明确通过结论时，
    # 正文中的历史/工具级 FAILED 引用不视为当前阻断（RW-022）
    if re.search(r'\bFAILED\b', body):
        if agent in ('workbuddy', 'codex') and verdict_ok(agent, body):
            return False
        return True
    # FAIL / REQUEST_CHANGE：有通过结论（PASS/PASS_WITH_WARNING/APPROVE）时，
    # 正文中的历史引用（如"原 REQUEST_CHANGE 已关闭"）不视为阻断
    if re.search(r'\b(FAIL|REQUEST_CHANGE|FRAMEWORK_ERROR)\b', body):
        if verdict_ok(agent, body):
            return False
        return True
    return False


def read_structured_blocking(agent: str, output_dir) -> tuple[bool, bool | None, str]:
    """读取 ``<agent>_result.json`` 的 blocking 信号（RW-022 structured-first）。

    返回 (available, blocking, status)：
    - available=False：JSON 缺失 / 损坏 / 无 blocking_rework 字段 → 调用方走 narrative fallback
    - available=True：blocking = blocking_rework 字段（bool）；status =
      structured_summary_status（COMPLETE / CONSISTENCY_VIOLATION / MALFORMED /
      NOT_PROVIDED …）
    """
    if output_dir is None:
        return False, None, ''
    path = Path(output_dir) / f'{agent}_result.json'
    if not path.exists():
        return False, None, ''
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False, None, ''
    if not isinstance(data, dict) or not isinstance(data.get('blocking_rework'), bool):
        return False, None, ''
    return True, bool(data['blocking_rework']), str(data.get('structured_summary_status') or '')


def agent_result_blocked(agent: str, body: str, output_dir=None) -> bool:
    """聚合用阻断判定：structured result 优先，legacy narrative 为 fail-safe fallback（RW-022）。

    - structured JSON 存在且 blocking_rework 合法：
      * summary COMPLETE（经 schema validation + narrative 一致性 guard）→ 直接采用
        blocking_rework（Agent 显式声明的事实；不再用 narrative 关键词猜测）
      * 非 COMPLETE（MALFORMED / CONSISTENCY_VIOLATION / 其他）→ 结构化信号与
        narrative 任一判定阻断即阻断（fail-safe：无法证明无阻断时不得 SUCCESS）
    - 无 structured JSON（legacy 目录 / 未写入）→ 原 narrative keyword 判定（向后兼容；
      空结果 / FRAMEWORK_ERROR / 明确 FAILED / FAIL / REQUEST_CHANGE 仍阻断——不 fail-open）
    """
    available, blocking, summary_status = read_structured_blocking(agent, output_dir)
    if not available:
        return verdict_blocked(agent, body)
    if summary_status == 'COMPLETE':
        return blocking
    # 非 COMPLETE：fail-safe 交叉验证（任一信号阻断 → 阻断）
    return blocking or verdict_blocked(agent, body)


def _extract_unresolved(results: dict[str, str], output_dir=None) -> str:
    """只收集真正未解决的阻断项；正常执行摘要 / diff / PASS / PASS_WITH_WARNING / APPROVE / 非阻断 warning 不进入。"""
    issues = []
    for name, body in results.items():
        if agent_result_blocked(name, body, output_dir):
            head = ' | '.join(body.strip().splitlines()[:3])[:600]
            issues.append(f'- {name}: {head}')
    return '\n'.join(issues) if issues else 'None identified.'


def _cancellation_section(terminal: dict) -> str:
    """CANCELLED REPORT 的取消说明（§6.6 / TASK req 17）。

    记录合理事实：Task ID / 取消时间 / 已完成阶段与 Agent 结果保留 / 后续阶段未执行。
    不伪造 Force Cancel / PID kill / ownership verified（本 TASK 只有 soft cancel）。
    """
    cancel_mode = terminal.get("cancel_mode")
    mode_text = {
        "soft": "cooperative（soft cancel）",
        "force": "force cancel（TASK-005-B 交付，本 TASK 未使用）",
    }.get(cancel_mode, str(cancel_mode))
    requested_at = terminal.get("cancel_requested_at")
    lines = [
        '## Cancellation',
        '任务已取消（CANCELLED）',
        f'- Task ID: {terminal.get("task_id", "")}',
    ]
    if requested_at:
        lines.append(f'- 取消请求时间: {requested_at}')
    if terminal.get("terminal_at"):
        lines.append(f'- 取消收敛时间: {terminal["terminal_at"]}')
    lines.append(f'- 取消方式: {mode_text}')
    lines.append('- 已完成阶段与 Agent 结果已保留')
    lines.append('- 后续阶段未执行')
    return '\n'.join(lines)


def build_report(
    task: str,
    route: list[str],
    results: dict[str, str],
    status: str,
    integrity_notes: list[str] | None = None,
    terminal: dict | None = None,
    *,
    task_path=None,
    task_hash: str | None = None,
    output_dir=None,
    sync_state: dict | None = None,
    intake_task_path=None,
) -> str:
    """生成 REPORT.md 文本（REPORT De-duplication，Requirement 7）。

    - 提供 ``task_path`` / ``task_hash``（Runner / Reconcile 新协议路径）→
      ``## Original Task`` 不再复制全文，改为 ``## Task Reference``（Task ID / Path / Hash）；
      未提供（legacy 外部调用方）→ 保留旧 ``## Original Task`` 全文嵌入（Backward Compat）。
      FIX-002 Req 1/2：Runner 传入的 task_path 是 immutable execution snapshot
      （TASK.snapshot.md），task_hash 只从 snapshot 计算一次并在整个 lifecycle 复用。
      FIX-003 Req 8：``intake_task_path``（active TASK 原始路径）只作为
      ``Original Intake Path`` provenance 记录，不是 execution authority。
    - Agent Results：摘要 + 完整结果 artifact 路径（output_dir 提供时）；不复制上游 narrative 全文。
    - ``sync_state``：``context_packet.remote_sync_state()`` 的 dict（FIX-002 Req 4/5）——
      提供时附加 ``## Remote Sync`` 段（Commit Sync / Tracked Working Tree /
      Task Remote Sync）；缺省（legacy 调用方）不输出该段，不虚构。
    - ``terminal``：canonical terminal metadata（TerminalResult.to_dict() 或等价 dict），
      提供时附加 ``## Terminal Generation``（派生产物 provenance，§6B.4）
    - status == CANCELLED：追加 ``## Cancellation`` 中文说明（§6.6 / req 17）；
      未执行 agent 的缺失结果不列入 Unresolved Issues（取消是预期中断，不是缺陷）
    """
    agent_sections = []
    for name in route:
        body = _summarize(results.get(name, '(not run)'), 1200)
        section = f'### {name}\n{body}'
        if output_dir is not None:
            md = Path(output_dir) / f'{name}_result.md'
            section += f'\n- Full result: {md}'
        agent_sections.append(section)
    results_text = '\n\n'.join(agent_sections)

    if status == 'CANCELLED':
        unresolved = 'None identified.'  # 取消任务不把未执行 agent 当 unresolved
        if integrity_notes:
            unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])
    else:
        # RW-022：unresolved 同样 structured-first（<agent>_result.json blocking_rework），
        # legacy narrative 为 fail-safe fallback
        unresolved = _extract_unresolved(results, output_dir)
        if integrity_notes:
            unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])

    extra = ''
    if status == 'CANCELLED' and terminal:
        extra = '\n\n' + _cancellation_section(terminal)
    if terminal and terminal.get('terminal_generation') is not None:
        extra += f'\n\n## Terminal Generation\n{terminal["terminal_generation"]}'

    if task_path or task_hash:
        # Requirement 7：REPORT 不再全文复制 Original Task，改为可追溯引用
        task_id = parse_task_fields(task).get('Task ID') or '(unknown)'
        ref_lines = [
            '## Task Reference',
            f'- Task ID: {task_id}',
        ]
        if task_path:
            ref_lines.append(f'- Task Path: {task_path}')
        if task_hash:
            ref_lines.append(f'- Task Hash: {task_hash}')
        if intake_task_path:
            ref_lines.append(
                f'- Original Intake Path: {intake_task_path}'
                '（provenance；execution authority 为上方 immutable snapshot）'
            )
        if output_dir is not None:
            ref_lines.append(f'- Artifacts: {output_dir}')
        task_section = '\n'.join(ref_lines)
    else:
        # Legacy 调用方（未提供引用信息）：保留全文嵌入，确保自包含
        task_section = f'## Original Task\n{_summarize(task, 8000)}'

    sync_section = ''
    if sync_state and isinstance(sync_state, dict) and sync_state.get('is_git_repo') is not False:
        # FIX-002 Req 4/5：区分 commit graph sync 与 tracked working tree；
        # Task Remote Sync 仅当两者都满足（commit+push 且 tracked CLEAN）才为 SYNCED
        dirty = sync_state.get('tracked_dirty_entries') or []
        sync_lines = [
            '## Remote Sync',
            f"- Commit Sync: {sync_state.get('commit_sync', 'UNKNOWN')}",
            f"- Tracked Working Tree: {sync_state.get('tracked_working_tree', 'UNKNOWN')}",
            f"- Task Remote Sync: {sync_state.get('task_remote_sync', 'UNKNOWN')}",
        ]
        if sync_state.get('ahead') is not None or sync_state.get('behind') is not None:
            sync_lines.append(
                f"- Ahead/Behind: {sync_state.get('ahead', 0)}/{sync_state.get('behind', 0)}"
            )
        if dirty:
            sync_lines.append('- Tracked 未提交条目:')
            sync_lines.extend(f'  - {d}' for d in dirty[:20])
        sync_section = '\n\n' + '\n'.join(sync_lines)

    return f'''# REPORT

## Current Status
{status}

## Route
{' -> '.join(route)}

{task_section}

## Agent Results
{results_text}

## Unresolved Issues
{unresolved}
{sync_section}

## Planner Handoff
Use this report as the authoritative context for the next planning turn. Resolve any FAIL / REQUEST_CHANGE / unresolved warnings before creating the next TASK. If all required checks passed, plan the next smallest task without reopening completed scope.{extra}
'''
