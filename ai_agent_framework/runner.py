from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .adapters import build_prompt, run_agent
from .report import build_report, verdict_blocked
from .router import Route, decide_route


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


def run(task_file: Path, workspace: Path, output_dir: Path, dry_run: bool = False, resume_from: Path | None = None) -> Path:
    task = task_file.read_text(encoding='utf-8')
    if resume_from is not None:
        route, results = _load_resume_state(resume_from)
        output_dir = resume_from
        status = 'RESUMED'
    else:
        route = decide_route(task)
        results = {}
        status = 'SUCCESS'

    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / 'route.json').write_text(
        json.dumps({'agents': route.agents, 'reason': route.reason}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    if dry_run:
        status = 'DRY_RUN'
    else:
        for agent in route.agents:
            if agent in results:
                continue  # resume：复用已完成结果，不重复执行
            prompt = build_prompt(agent, task, results, workspace)
            (output_dir / f'{agent}_prompt.md').write_text(prompt, encoding='utf-8')
            try:
                result = run_agent(agent, prompt, workspace)
            except Exception as exc:
                result = f'FRAMEWORK_ERROR\n{type(exc).__name__}: {exc}'
            results[agent] = result
            (output_dir / f'{agent}_result.md').write_text(result, encoding='utf-8')
            if not _result_is_valid(result):
                break  # 执行链保护：必需节点无有效结果 → 停止后续节点
        status = _aggregate_status(route.agents, results)

    # 执行链完整性保护：必需 Executor / Validator 无有效结果 → REPORT 明确标记
    # （dry-run 不执行 Agent，属预期，不生成误导性 notes）
    integrity_notes = []
    if not dry_run:
        if 'hermes' in route.agents and not _result_is_valid(results.get('hermes', '')):
            integrity_notes.append('Required executor Hermes did not run or produced no valid result')
        if 'workbuddy' in route.agents and not _result_is_valid(results.get('workbuddy', '')):
            integrity_notes.append('Required validator WorkBuddy did not run or produced no valid result')

    report = build_report(task, route.agents, results, status, integrity_notes)
    report_path = output_dir / 'REPORT.md'
    report_path.write_text(report, encoding='utf-8')
    (output_dir / 'run.json').write_text(
        json.dumps({'timestamp': datetime.now().isoformat(), 'status': status}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return report_path


def main() -> None:
    p = argparse.ArgumentParser(description='AI Agent Framework v0.2 prototype runner')
    p.add_argument('task', type=Path, help='TASK.md path')
    p.add_argument('--workspace', type=Path, required=True, help='Business project workspace')
    p.add_argument('--output', type=Path, default=Path('.aaf-run'), help='Run output directory')
    p.add_argument('--dry-run', action='store_true', help='Route only; do not invoke agents')
    p.add_argument('--resume-from', type=Path, default=None, help='Resume an existing run output dir (reuses completed agent results)')
    args = p.parse_args()
    report = run(args.task, args.workspace, args.output, args.dry_run, args.resume_from)
    print(report)


if __name__ == '__main__':
    main()
