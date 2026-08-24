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


def build_report(task: str, route: list[str], results: dict[str, str], status: str, integrity_notes: list[str] | None = None) -> str:
    agent_sections = []
    for name in route:
        body = _summarize(results.get(name, '(not run)'))
        agent_sections.append(f'### {name}\n{body}')
    results_text = '\n\n'.join(agent_sections)
    unresolved = _extract_unresolved(results)
    if integrity_notes:
        unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])
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
Use this report as the authoritative context for the next planning turn. Resolve any FAIL / REQUEST_CHANGE / unresolved warnings before creating the next TASK. If all required checks passed, plan the next smallest task without reopening completed scope.
'''
