from pathlib import Path
import re

import pytest

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

# 显式 Route 字段的极简 TASK（FIX-003：canonical machine Route）
MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-EXPLICIT

# Task Name
显式路由测试

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

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


# --- FIX-003：Explicit Route Authority 集成（Req 1/3/4/6/7/11/13） ---

def test_explicit_route_drives_runner_chain(tmp_path, monkeypatch):
    """正文无代码风险词的 compact TASK + 显式 Route → 完整执行 hermes -> workbuddy -> codex，
    route.json 记录显式来源（Anti-Bloat：不靠关键词膨胀触发 Codex）。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return {'hermes': 'implemented', 'workbuddy': '**Result: PASS**\nverified', 'codex': 'APPROVE'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    body = ("Task ID: T-EXP\nTask Name: 显式路由\n"
            "Objective: 完成资料汇总并输出清单\n"
            "Acceptance:\n1. 通过\n"
            "Route: hermes -> workbuddy -> codex\n")
    # 正文不含代码风险词（codex 中的 "code" 是子串，Router 用词边界 \b 不命中）
    assert not any(w in body for w in ('代码', '安全', '架构'))
    assert not re.search(r'\b(code|architecture)\b', body)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(body, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)

    assert calls == ['hermes', 'workbuddy', 'codex']
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nSUCCESS' in report
    assert '## Route\nhermes -> workbuddy -> codex' in report
    import json
    rj = json.loads((out / 'route.json').read_text(encoding='utf-8'))
    assert rj['agents'] == ['hermes', 'workbuddy', 'codex']
    assert rj['reason'] == 'explicit route (machine field)'


def test_required_codex_missing_no_success(tmp_path, monkeypatch):
    """required route 含 codex 但 codex 结果为空 → 不得 SUCCESS（Req 3）。"""
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return 'implemented ok'
        if agent == 'workbuddy':
            return '**Result: PASS**\nverified'
        return ''  # codex 空结果（未产生有效结果）

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')

    assert '## Current Status\nWAITING' in report
    assert 'Required reviewer Codex did not run or produced no valid result' in report
    assert 'SUCCESS' not in report.split('## Route')[0]


def test_required_codex_framework_error_no_success(tmp_path, monkeypatch):
    """required route 含 codex 但 codex FRAMEWORK_ERROR → 不得 SUCCESS（Req 3）。"""
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return 'implemented ok'
        if agent == 'workbuddy':
            return '**Result: PASS**\nverified'
        return 'FRAMEWORK_ERROR\nRuntimeError: boom'

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')

    assert '## Current Status\nWAITING' in report
    assert 'Required reviewer Codex did not run or produced no valid result' in report


def test_route_inconsistency_rejected_at_validation(tmp_path, monkeypatch):
    """Req 4：TASK 显式声明含 codex 的 Route，但 Router 计算结果缺 codex →
    Validation 阶段直接失败（Route inconsistency），不执行任何 Agent、不得误报 SUCCESS。"""
    def fake_decide_route(task):
        return runner_mod.Route(['hermes', 'workbuddy'], 'heuristic')  # 与声明冲突

    monkeypatch.setattr(runner_mod, 'decide_route', fake_decide_route)
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return 'ok'

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    with pytest.raises(runner_mod.TaskValidationError) as exc:
        runner_mod.run(task_file, ws, out)
    assert 'Route inconsistency' in str(exc.value)
    assert calls == []  # 未启动任何 Agent


def test_snapshot_hash_in_all_stage_prompts_and_manifest(tmp_path, monkeypatch):
    """Req 5/6/13：snapshot hash 贯穿所有 stage prompt（hermes/workbuddy/codex）、
    manifest（task + execution_task）、REPORT；intake_task 仅 provenance 无 hash。"""
    def fake_run_agent(agent, prompt, workspace):
        return {'hermes': 'implemented', 'workbuddy': '**Result: PASS**\nverified', 'codex': 'APPROVE'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    runner_mod.run(task_file, ws, out)

    from ai_agent_framework.context_packet import read_manifest, sha256_file
    snapshot_hash = sha256_file(out / 'TASK.snapshot.md')
    for agent in ('hermes', 'workbuddy', 'codex'):
        prompt = (out / f'{agent}_prompt.md').read_text(encoding='utf-8')
        assert snapshot_hash in prompt
        assert 'TASK.snapshot.md' in prompt

    manifest = read_manifest(out)
    assert manifest['task']['hash'] == snapshot_hash
    assert manifest['execution_task']['hash'] == snapshot_hash
    assert manifest['execution_task']['path'] == str(out / 'TASK.snapshot.md')
    assert manifest['intake_task']['path'] == str(task_file)
    assert 'hash' not in manifest['intake_task']  # 单一 hash authority

    report = (out / 'REPORT.md').read_text(encoding='utf-8')
    assert snapshot_hash in report


def test_active_task_mutation_keeps_execution_reference_stable(tmp_path, monkeypatch):
    """Req 7：active TASK 后续变化不影响本次 execution 引用（snapshot/manifest/REPORT）。"""
    def fake_run_agent(agent, prompt, workspace):
        return {'hermes': 'implemented', 'workbuddy': '**Result: PASS**\nverified', 'codex': 'APPROVE'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)

    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    runner_mod.run(task_file, ws, out)

    from ai_agent_framework.context_packet import check_references, read_manifest, sha256_file
    snapshot_hash = sha256_file(out / 'TASK.snapshot.md')
    report_before = (out / 'REPORT.md').read_text(encoding='utf-8')

    # active 文件被修改（追加新要求）→ 本次 execution 引用不得变化
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK + "Requirements:\n99. 新增要求\n", encoding='utf-8')

    report_after = (out / 'REPORT.md').read_text(encoding='utf-8')
    assert report_after == report_before
    assert check_references(read_manifest(out)) == []

    ref_section = report_after.split('## Task Reference')[1].split('## Agent Results')[0]
    assert 'TASK.snapshot.md' in ref_section          # Task Path = immutable snapshot
    assert snapshot_hash in ref_section               # Task Hash = snapshot hash
    assert 'Original Intake Path' in ref_section      # intake 仅 provenance
    assert str(task_file) in ref_section


# --- FIX-004：Byte-Stable Task Identity + Snapshot Authority + Route Fail-Closed ---

def _fake_agents_ok(agent, prompt, workspace):
    return {'hermes': 'implemented', 'workbuddy': '**Result: PASS**\nverified', 'codex': 'APPROVE'}[agent]


def test_runner_hash_is_raw_file_bytes_externally_reproducible(tmp_path, monkeypatch):
    """Req 1/2/6：CRLF snapshot（raw copy，模拟 launcher 行为）→ framework task hash
    == hashlib.sha256(snapshot.read_bytes())（外部标准工具可复算），manifest bytes
    == snapshot.stat().st_size；不再对换行归一化后的文本计算 hash。"""
    import hashlib
    from ai_agent_framework.context_packet import check_references, read_manifest, sha256_text

    monkeypatch.setattr(runner_mod, 'run_agent', _fake_agents_ok)

    body = MINIMAL_EXPLICIT_ROUTE_TASK.replace('\n', '\r\n')  # CRLF active TASK
    task_file = tmp_path / 'TASK.md'
    task_file.write_bytes(body.encode('utf-8'))
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    out.mkdir()
    # launcher 行为：snapshot = active 文件 raw copy（CRLF 保留在磁盘上）
    (out / 'TASK.snapshot.md').write_bytes(body.encode('utf-8'))

    runner_mod.run(task_file, ws, out)

    snapshot = out / 'TASK.snapshot.md'
    raw = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest = read_manifest(out)
    assert manifest['task']['hash'] == raw
    assert manifest['execution_task']['hash'] == raw
    assert manifest['task']['bytes'] == snapshot.stat().st_size
    assert manifest['execution_task']['bytes'] == snapshot.stat().st_size
    # CRLF 文件：raw bytes hash != 归一化文本 hash（证明不再走 read_text 归一化路径）
    assert raw != sha256_text(MINIMAL_EXPLICIT_ROUTE_TASK)
    assert check_references(manifest) == []
    # REPORT Task Reference hash 同样为 raw bytes hash
    report = (out / 'REPORT.md').read_text(encoding='utf-8')
    assert raw in report


def test_runner_hash_raw_bytes_for_fresh_snapshot(tmp_path, monkeypatch):
    """Req 1/2：新 execution（runner 自写 LF snapshot）→ framework hash ==
    hashlib.sha256(snapshot.read_bytes())，bytes == stat().st_size。"""
    import hashlib
    from ai_agent_framework.context_packet import read_manifest

    monkeypatch.setattr(runner_mod, 'run_agent', _fake_agents_ok)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    runner_mod.run(task_file, ws, out)

    snapshot = out / 'TASK.snapshot.md'
    manifest = read_manifest(out)
    assert manifest['task']['hash'] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert manifest['task']['bytes'] == snapshot.stat().st_size


def test_resume_uses_snapshot_before_route_and_hash(tmp_path, monkeypatch):
    """Req 3/5：首次执行生成 snapshot → 修改 active TASK（Route + Objective）→
    resume 仍使用原 snapshot semantics：route / task hash / references 不变。"""
    monkeypatch.setattr(runner_mod, 'run_agent', _fake_agents_ok)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    runner_mod.run(task_file, ws, out)

    import json
    from ai_agent_framework.context_packet import read_manifest
    route_before = json.loads((out / 'route.json').read_text(encoding='utf-8'))
    manifest_before = read_manifest(out)
    snapshot_hash = manifest_before['task']['hash']

    # 修改 active TASK：Route 换成别的链、Objective 追加要求（Task ID 不变）
    mutated = MINIMAL_EXPLICIT_ROUTE_TASK.replace(
        'hermes -> workbuddy -> codex', 'workbuddy'
    ).replace('实现功能并验收', '实现功能并验收（active 侧新增要求，不得生效）')
    task_file.write_text(mutated, encoding='utf-8')

    report_path = runner_mod.run(task_file, ws, out, resume_from=out)

    route_after = json.loads((out / 'route.json').read_text(encoding='utf-8'))
    manifest_after = read_manifest(out)
    assert route_after == route_before                       # active Route 突变被忽略
    assert manifest_after['task']['hash'] == snapshot_hash   # execution hash 不变
    assert manifest_after['execution_task']['hash'] == snapshot_hash
    assert manifest_after['intake_task']['path'] == str(task_file)  # intake 仅 provenance
    report = report_path.read_text(encoding='utf-8')
    assert snapshot_hash in report                           # REPORT 引用原 snapshot hash
    # snapshot 文件未被 active 突变改写（原 Route 链仍在 snapshot 中）
    snapshot_text = (out / 'TASK.snapshot.md').read_text(encoding='utf-8')
    assert 'hermes -> workbuddy -> codex' in snapshot_text


def test_resume_active_content_mutation_keeps_execution_identity(tmp_path, monkeypatch):
    """Req 5：active TASK 内容变为非法（删除 Objective 等）→ resume 不校验 active
    内容，仍以 snapshot 为 authority 正常完成。"""
    monkeypatch.setattr(runner_mod, 'run_agent', _fake_agents_ok)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    runner_mod.run(task_file, ws, out)

    # active 内容被破坏（Objective 清空 + 乱码）——Task ID 保持不变
    task_file.write_text(
        MINIMAL_EXPLICIT_ROUTE_TASK.replace('实现功能并验收', '').replace('# Objective', '## 乱改'),
        encoding='utf-8',
    )
    report_path = runner_mod.run(task_file, ws, out, resume_from=out)  # 不抛错
    assert '## Current Status\nSUCCESS' in report_path.read_text(encoding='utf-8')


def test_resume_task_id_conflict_refused(tmp_path, monkeypatch):
    """Req 5：active TASK Task ID 与 snapshot 严重冲突 → 显式拒绝 resume
    （不得静默采用新 active 内容，也不得静默执行旧 snapshot）。"""
    monkeypatch.setattr(runner_mod, 'run_agent', _fake_agents_ok)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    runner_mod.run(task_file, ws, out)

    task_file.write_text(
        MINIMAL_EXPLICIT_ROUTE_TASK.replace('T-EXPLICIT', 'T-OTHER-TASK'), encoding='utf-8'
    )
    with pytest.raises(runner_mod.TaskValidationError) as exc:
        runner_mod.run(task_file, ws, out, resume_from=out)
    assert 'Execution identity conflict' in str(exc.value)
    # snapshot 未被改写（原身份保留）
    assert 'T-EXPLICIT' in (out / 'TASK.snapshot.md').read_text(encoding='utf-8')


def test_invalid_explicit_route_runner_fails_validation(tmp_path, monkeypatch):
    """Req 7：非法显式 Route（未知 agent / malformed / empty）→ runner 在 Validation
    阶段失败，不执行任何 Agent、不写 route.json。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return 'ok'

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)
    ws = tmp_path / 'ws'
    ws.mkdir()
    for route_line in ('Route: hermes -> alien\n', 'Route: hermes ->\n', 'Route:\n'):
        task_file = tmp_path / 'TASK.md'
        task_file.write_text(
            MINIMAL_VALID_TASK.replace('T-EXEC', 'T-BADROUTE') + route_line, encoding='utf-8'
        )
        out = tmp_path / 'out-bad'
        with pytest.raises(runner_mod.TaskValidationError) as exc:
            runner_mod.run(task_file, ws, out)
        assert 'Route' in str(exc.value)
        assert calls == []            # 未启动任何 Agent
        assert not (out / 'route.json').exists()  # 未产生路由产物
