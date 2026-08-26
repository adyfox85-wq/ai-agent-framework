from pathlib import Path
import ai_agent_framework.runner as runner_mod

# 合法极简 TASK（满足 Formal Task Validation：Task ID / Task Name / Objective / Acceptance）
MINIMAL_VALID_TASK = """# Task ID
T-EXEC

# Task Name
执行链测试

# Objective
实现功能并验收

# Acceptance
1. 通过
"""


# --- Bug2 回归：最终状态聚合 ---

def test_workbuddy_fail_yields_waiting():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'implemented ok', 'workbuddy': 'FAIL: B1 broken'},
    )
    assert status == 'WAITING'


def test_codex_request_change_yields_waiting():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'REQUEST_CHANGE: fix router'},
    )
    assert status == 'WAITING'


def test_hermes_framework_error_yields_waiting():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'FRAMEWORK_ERROR\nRuntimeError: boom', 'workbuddy': 'PASS'},
    )
    assert status == 'WAITING'


def test_missing_required_result_yields_waiting():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok'},  # workbuddy 缺失
    )
    assert status == 'WAITING'


def test_all_pass_yields_success():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'implemented', 'workbuddy': 'PASS'},
    )
    assert status == 'SUCCESS'


# --- 执行链完整性保护 ---

def test_missing_executor_stops_chain_and_waiting(tmp_path, monkeypatch):
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == 'hermes':
            raise RuntimeError('boom')
        return 'should not run'

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_VALID_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')

    assert calls == ['hermes']  # Hermes 失败后 workbuddy/codex 不得继续
    assert '## Current Status\nWAITING' in report
    assert 'Required executor Hermes did not run or produced no valid result' in report


def test_missing_validator_stops_codex(tmp_path, monkeypatch):
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == 'workbuddy':
            return 'FRAMEWORK_ERROR\nboom'
        return 'ok'

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_VALID_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')

    assert calls == ['hermes', 'workbuddy']  # codex 未执行
    assert '## Current Status\nWAITING' in report
    assert 'Required validator WorkBuddy did not run or produced no valid result' in report


def test_workbuddy_fail_never_reports_success(tmp_path, monkeypatch):
    def fake_run_agent(agent, prompt, workspace):
        return {'hermes': 'implemented', 'workbuddy': 'FAIL: broken'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_VALID_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')

    assert '## Current Status\nWAITING' in report
    assert 'SUCCESS' not in report.split('## Route')[0]


# --- 旧 output / route.json 不复用回归 ---

def test_stale_route_json_is_overwritten_on_normal_run(tmp_path, monkeypatch):
    """非 resume 正式运行必须重新路由并覆盖旧 route.json，不能复用旧 Route。"""
    def fake_run_agent(agent, prompt, workspace):
        return {'hermes': 'implemented', 'workbuddy': 'PASS'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_VALID_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()

    # 预置一个错误旧 route.json（模拟上一轮 dry-run 的旧结果）
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'route.json').write_text(
        '{"agents": ["workbuddy", "codex"], "reason": "review/validation task"}',
        encoding='utf-8',
    )

    runner_mod.run(task_file, ws, out)

    import json
    fresh_route = json.loads((out / 'route.json').read_text(encoding='utf-8'))
    assert fresh_route['agents'] == ['hermes', 'workbuddy']  # 旧值被正确覆盖
    assert 'hermes' in fresh_route['agents']


def test_real_task_dry_run_then_real_run_keeps_correct_route(tmp_path, monkeypatch):
    """真实 TASK-005-FIX-001：先 dry-run 得到正确 Route，再正式运行（mock Agent），Route 不得变回旧值。"""
    from pathlib import Path as _P
    real = _P(__file__).resolve().parent / 'fixtures' / 'TASK-005-FIX-001.md'
    if not real.exists():
        import pytest
        pytest.skip('real TASK-005-FIX-001 file not present')
    task = real.read_text(encoding='utf-8')

    def fake_run_agent(agent, prompt, workspace):
        return {'hermes': 'implemented', 'workbuddy': 'PASS', 'codex': 'APPROVE'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(task, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'

    # 第一步：dry-run（写正确 route.json）
    runner_mod.run(task_file, ws, out, dry_run=True)
    import json
    dry_route = json.loads((out / 'route.json').read_text(encoding='utf-8'))
    assert dry_route['agents'] == ['hermes', 'workbuddy', 'codex']

    # 第二步：正式运行（mock Agent，无 --resume-from）——必须重新路由并保持正确
    runner_mod.run(task_file, ws, out)
    fresh_route = json.loads((out / 'route.json').read_text(encoding='utf-8'))
    assert fresh_route['agents'] == ['hermes', 'workbuddy', 'codex']


# --- 结论优先聚合（Test A-F） ---

def test_status_success_pass_and_approve():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'implemented ok', 'workbuddy': 'PASS', 'codex': 'APPROVE'},
    )
    assert status == 'SUCCESS'


def test_status_success_pass_with_warning_and_approve():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {
            'hermes': 'implemented ok',
            'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: browser smoke not rerun\nThe Codex REQUEST_CHANGE items are all closed.',
            'codex': '最终判定：APPROVE\n原 Codex REQUEST_CHANGE 的阻断项已关闭。',
        },
    )
    assert status == 'SUCCESS'


def test_status_waiting_workbuddy_fail():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'implemented', 'workbuddy': 'FAIL: B1 broken'},
    )
    assert status == 'WAITING'


def test_status_waiting_codex_request_change():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'implemented', 'workbuddy': 'PASS', 'codex': 'REQUEST_CHANGE: fix router'},
    )
    assert status == 'WAITING'


def test_status_success_codex_approve_with_risk_warning_note():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {
            'hermes': 'implemented',
            'workbuddy': 'PASS',
            'codex': 'APPROVE\n风险说明：\n- mock 固定演示盘\n- 浏览器被拒绝\n不构成阻断。',
        },
    )
    assert status == 'SUCCESS'


def test_status_success_hermes_diff_warning_review():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'review diff\na/x.ts → b/x.ts\nwarning: minor', 'workbuddy': 'PASS'},
    )
    assert status == 'SUCCESS'
