from __future__ import annotations

import re


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
    """
    body = body.strip()
    if not body:
        return True
    if body.startswith('FRAMEWORK_ERROR'):
        return True
    # 显式失败结论（全大写）：任何 agent 都阻断
    if re.search(r'\bFAILED\b', body):
        return True
    # FAIL / REQUEST_CHANGE：有通过结论（PASS/PASS_WITH_WARNING/APPROVE）时，
    # 正文中的历史引用（如"原 REQUEST_CHANGE 已关闭"）不视为阻断
    if re.search(r'\b(FAIL|REQUEST_CHANGE|FRAMEWORK_ERROR)\b', body):
        if verdict_ok(agent, body):
            return False
        return True
    return False


def _extract_unresolved(results: dict[str, str]) -> str:
    """只收集真正未解决的阻断项；正常执行摘要 / diff / PASS / PASS_WITH_WARNING / APPROVE / 非阻断 warning 不进入。"""
    issues = []
    for name, body in results.items():
        if verdict_blocked(name, body):
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
) -> str:
    """生成 REPORT.md 文本。

    - ``terminal``：canonical terminal metadata（TerminalResult.to_dict() 或等价 dict），
      提供时附加 ``## Terminal Generation``（派生产物 provenance，§6B.4）
    - status == CANCELLED：追加 ``## Cancellation`` 中文说明（§6.6 / req 17）；
      未执行 agent 的缺失结果不列入 Unresolved Issues（取消是预期中断，不是缺陷）
    """
    agent_sections = []
    for name in route:
        body = _summarize(results.get(name, '(not run)'))
        agent_sections.append(f'### {name}\n{body}')
    results_text = '\n\n'.join(agent_sections)

    if status == 'CANCELLED':
        unresolved = 'None identified.'  # 取消任务不把未执行 agent 当 unresolved
        if integrity_notes:
            unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])
    else:
        unresolved = _extract_unresolved(results)
        if integrity_notes:
            unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])

    extra = ''
    if status == 'CANCELLED' and terminal:
        extra = '\n\n' + _cancellation_section(terminal)
    if terminal and terminal.get('terminal_generation') is not None:
        extra += f'\n\n## Terminal Generation\n{terminal["terminal_generation"]}'

    return f'''# REPORT

## Current Status
{status}

## Route
{' -> '.join(route)}

## Original Task
{_summarize(task, 8000)}

## Agent Results
{results_text}

## Unresolved Issues
{unresolved}

## Planner Handoff
Use this report as the authoritative context for the next planning turn. Resolve any FAIL / REQUEST_CHANGE / unresolved warnings before creating the next TASK. If all required checks passed, plan the next smallest task without reopening completed scope.{extra}
'''
