from ai_agent_framework.report import build_report, verdict_blocked


def test_report_contains_machine_context():
    report = build_report(
        task='TASK-002\n目标：实现首页',
        route=['hermes','workbuddy'],
        results={'hermes': 'SUCCESS: implemented', 'workbuddy': 'PASS'},
        status='SUCCESS',
    )
    assert '# REPORT' in report
    assert '## Current Status\nSUCCESS' in report
    assert '## Agent Results' in report
    assert '## Planner Handoff' in report


# --- 状态判定：结论优先，历史 FAIL/REQUEST_CHANGE 引用不阻断 ---

def test_verdict_ok_workbuddy_pass():
    assert not verdict_blocked('workbuddy', '**Result: PASS**\nall good')


def test_verdict_ok_workbuddy_pass_with_warning():
    assert not verdict_blocked('workbuddy', '## VALIDATOR REPORT\n**Result: PASS_WITH_WARNING**\nW1: browser smoke not rerun')


def test_verdict_ok_workbuddy_pass_with_historical_request_change():
    # PASS_WITH_WARNING 报告中引用历史 REQUEST_CHANGE（"all closed"）→ 不阻断
    body = '**Result: PASS_WITH_WARNING**\nThe Codex REQUEST_CHANGE items are all closed.'
    assert not verdict_blocked('workbuddy', body)


def test_verdict_ok_codex_approve_with_historical_request_change():
    # APPROVE 报告中引用"原 REQUEST_CHANGE 已关闭"→ 不阻断
    body = '最终判定：APPROVE\n原 Codex REQUEST_CHANGE 的阻断项已关闭。'
    assert not verdict_blocked('codex', body)


def test_verdict_ok_codex_approve_with_risk_warning_note():
    body = '## 独立审查结论：APPROVE\n风险说明：\n- 当前 Mock 是全局固定演示盘\n- 本轮浏览器被拒绝\n不构成阻断。'
    assert not verdict_blocked('codex', body)


def test_verdict_blocked_workbuddy_fail():
    assert verdict_blocked('workbuddy', '**Result: FAIL**\nB1 broken')


def test_verdict_blocked_codex_request_change():
    assert verdict_blocked('codex', 'REQUEST_CHANGE: fix router')


def test_verdict_blocked_hermes_failed():
    assert verdict_blocked('hermes', 'FAILED: implementation incomplete')


def test_verdict_blocked_framework_error():
    assert verdict_blocked('workbuddy', 'FRAMEWORK_ERROR\nRuntimeError: boom')


def test_verdict_ok_hermes_diff_warning_review():
    # Hermes 正常执行摘要含 diff/warning/review 但无 FAILED → 有效
    body = 'review diff\na/x.py → b/x.py\nwarning: minor\nreview summary done'
    assert not verdict_blocked('hermes', body)


# --- Unresolved Issues 只收集真正阻断项 ---

def test_unresolved_empty_for_all_pass():
    report = build_report(
        task='T',
        route=['hermes', 'workbuddy', 'codex'],
        results={
            'hermes': 'implemented\nreview diff ok',
            'workbuddy': '**Result: PASS**\nall verified',
            'codex': '最终判定：APPROVE\n风险说明：无阻断',
        },
        status='SUCCESS',
    )
    assert '## Unresolved Issues\nNone identified.' in report


def test_unresolved_excludes_pass_with_warning_report_body():
    report = build_report(
        task='T',
        route=['hermes', 'workbuddy', 'codex'],
        results={
            'hermes': 'implemented ok',
            'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: browser smoke not rerun\nW2: minor note\nThe Codex REQUEST_CHANGE items are all closed.',
            'codex': '最终判定：APPROVE',
        },
        status='SUCCESS',
    )
    assert '## Unresolved Issues\nNone identified.' in report
    assert 'W1' not in report.split('## Unresolved Issues')[1]


def test_unresolved_contains_workbuddy_fail():
    report = build_report(
        task='T',
        route=['hermes', 'workbuddy'],
        results={'hermes': 'implemented', 'workbuddy': '**Result: FAIL**\nB1 broken'},
        status='WAITING',
    )
    unresolved = report.split('## Unresolved Issues')[1]
    assert 'workbuddy' in unresolved
    assert 'FAIL' in unresolved


def test_unresolved_contains_codex_request_change():
    report = build_report(
        task='T',
        route=['hermes', 'workbuddy', 'codex'],
        results={
            'hermes': 'implemented',
            'workbuddy': 'PASS',
            'codex': 'REQUEST_CHANGE: fix router',
        },
        status='WAITING',
    )
    unresolved = report.split('## Unresolved Issues')[1]
    assert 'codex' in unresolved
    assert 'REQUEST_CHANGE' in unresolved
