"""RW-022 FIX-001 regression tests：Blocking Provenance + Fail-Closed Aggregation。

覆盖 TASK-007-FIX-001 Requirement 9 的 A–H 真实组合 + blocking provenance 完整性：

- A: Hermes SUCCESS narrative 含技术性 FAILED 字样 + no real blocking → 不得被错误聚合为 WAITING
- B: FRAMEWORK_ERROR + structured COMPLETE + blocking=false → 不得 SUCCESS（fail closed）
- C: empty required result + structured COMPLETE + blocking=false → 不得 SUCCESS
- D: missing required agent result → 不得 SUCCESS（即使其 structured JSON 声称无阻断）
- E: PASS_WITH_WARNING + explicit no blocking + Codex APPROVE → SUCCESS
- F: REQUEST_CHANGE → WAITING
- G: invalid structured blocking data → fail closed
- H: legacy narrative-only result → backward-compatible且不 fail-open

核心语义（Requirement 1/2/7）：
- blocking provenance 可辨识：structured（agent 显式结构化 verdict）/ framework
  （Framework 可确定的执行有效性）/ narrative（legacy fallback）
- narrative keyword 推断不得伪装成 structured authoritative fact
- 优先级：Framework hard failure > explicit blocking structured verdict >
  explicit non-blocking structured verdict > legacy fallback
- COMPLETE 标签不得覆盖 execution validity
"""
import json
from pathlib import Path

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework.context_packet import build_stage_result
from ai_agent_framework.report import (
    BLOCKING_PROVENANCE_FRAMEWORK,
    BLOCKING_PROVENANCE_NARRATIVE,
    BLOCKING_PROVENANCE_STRUCTURED,
    agent_result_blocked,
    build_report,
    read_structured_blocking,
    verdict_blocked,
)

MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-RW022-FIX

# Task Name
Blocking Provenance + Fail-Closed 聚合测试

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _write_stage_json(out: Path, agent: str, *, blocking: bool, status: str = "COMPLETE",
                      verdict: str | None = None, warnings: list | None = None,
                      provenance: str | None = None) -> None:
    """写 <agent>_result.json。provenance=None → 不写字段（模拟旧 artifact）。"""
    data = {
        "protocol": "packet/1",
        "agent": agent,
        "status": "SUCCESS" if not blocking else "FAILED",
        "verdict": verdict or ("APPROVE" if agent == "codex" else "PASS"),
        "blocking_rework": blocking,
        "commit": None,
        "commit_changed": False,
        "tests": None,
        "changed_files": [],
        "evidence_paths": [],
        "findings": [],
        "warnings": [] if warnings is None else warnings,
        "summary_complete": status == "COMPLETE",
        "structured_summary_status": status,
        "summary": "",
        "narrative_path": str(out / f"{agent}_result.md"),
    }
    if provenance is not None:
        data["blocking_provenance"] = provenance
    (out / f"{agent}_result.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _block(text: str, agent: str) -> str:
    """narrative + 结构化块（Agent 答复形状）。

    FIX-002：reviewer 结构化块显式声明 blocking_provenance=structured（新契约，
    structured authority 只来自显式字段；缺声明 = legacy narrative fallback）。
    """
    structured = {
        "workbuddy": {"verdict": "PASS_WITH_WARNING", "blocking_rework": False,
                      "blocking_provenance": "structured",
                      "findings": [], "warnings": ["W1: 文档瑕疵"]},
        "codex": {"verdict": "APPROVE", "blocking_rework": False,
                  "blocking_provenance": "structured", "findings": [], "warnings": []},
        "hermes": {"status": "SUCCESS", "changed_files": [], "warnings": []},
    }[agent]
    return (text + "\nAAF_STRUCTURED_RESULT_BEGIN\n"
            + json.dumps(structured) + "\nAAF_STRUCTURED_RESULT_END")


# ============ A: Hermes narrative 技术性 FAILED 字样不得误判 WAITING（Req 4 / Req 9-A） ============

def test_a_hermes_technical_failed_token_not_waiting():
    # Hermes SUCCESS narrative 含 FAILED / error 技术性词语，无显式失败判定 → 不得 WAITING
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {
            'hermes': 'implemented ok. The previously FAILED test now passes; '
                      'also fixed the error handling in the parser.',
            'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 建议补充文档',
            'codex': '最终判定：APPROVE\nBlocking Issues: NONE',
        },
    )
    assert status == 'SUCCESS'


def test_a_hermes_structured_json_narrative_provenance_not_authoritative(tmp_path):
    # hermes JSON blocking_rework 由 narrative 派生（provenance=narrative）→
    # 不得作为 structured 权威事实；narrative 技术性 FAILED → 不阻断（无 laundering）
    out = tmp_path / "out"
    out.mkdir()
    body = 'implemented ok. The previously FAILED test now passes; fixed the error handling.'
    _write_stage_json(out, 'hermes', blocking=False, status='COMPLETE', provenance='narrative')
    available, blocking, status, provenance = read_structured_blocking('hermes', out)
    assert available is True and blocking is False and status == 'COMPLETE'
    assert provenance == BLOCKING_PROVENANCE_NARRATIVE
    assert agent_result_blocked('hermes', body, out) is False
    # 聚合路径同样不误判
    assert runner_mod._aggregate_status(['hermes'], {'hermes': body}, out) == 'SUCCESS'


def test_a_hermes_narrative_provenance_blocking_true_still_fail_safe(tmp_path):
    # provenance=narrative 且派生值 blocking=True → 仍阻断（fail-safe 不 fail-open）
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'hermes', blocking=True, status='COMPLETE', provenance='narrative')
    assert agent_result_blocked('hermes', 'implemented ok', out) is True


def test_a_hermes_explicit_failed_line_still_blocks():
    # 显式失败判定形态（行首 FAILED:）→ 仍阻断（FIX-001 不弱化真阻断）
    assert verdict_blocked('hermes', 'FAILED: implementation incomplete') is True
    assert runner_mod._aggregate_status(['hermes'], {'hermes': 'FAILED: 实现不完整'}) == 'WAITING'
    assert verdict_blocked('hermes', '**Result: FAILED**\nB1 broken') is True
    assert verdict_blocked('hermes', 'REQUEST_CHANGE: fix router') is True


# ============ B: FRAMEWORK_ERROR fail closed（Req 3 / Req 9-B） ============

def test_b_framework_error_structured_complete_blocking_false_fail_closed(tmp_path):
    # COMPLETE + blocking=false 不得覆盖 FRAMEWORK_ERROR（framework hard failure 优先）
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': 'FRAMEWORK_ERROR\nRuntimeError: boom'},
        out,
    )
    assert status == 'WAITING'


def test_b_framework_error_full_runner_run_waiting(tmp_path, monkeypatch):
    # 真实 runner 路径：workbuddy FRAMEWORK_ERROR + 结构化块 blocking=false → WAITING
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return _block('implemented ok', 'hermes')
        if agent == 'workbuddy':
            return ('FRAMEWORK_ERROR\nRuntimeError: boom'
                    '\nAAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"verdict": "PASS", "blocking_rework": false, "findings": [], "warnings": []}'
                    '\nAAF_STRUCTURED_RESULT_END')
        return _block('APPROVE', 'codex')

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    report_path = runner_mod.run(task_file, ws, tmp_path / 'out')
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nWAITING' in report
    # stage JSON 记录 framework provenance（COMPLETE 标签不得覆盖 execution validity）
    stage = json.loads((report_path.parent / 'workbuddy_result.json').read_text(encoding='utf-8'))
    assert stage['status'] == 'FAILED'
    assert stage['blocking_rework'] is True
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_FRAMEWORK


# ============ C: empty required result fail closed（Req 9-C） ============

def test_c_empty_required_result_structured_complete_blocking_false_fail_closed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': ''},
        out,
    )
    assert status == 'WAITING'


def test_c_empty_required_result_no_json_fail_closed():
    assert runner_mod._aggregate_status(['hermes'], {'hermes': '   '}) == 'WAITING'


# ============ D: missing required agent result fail closed（Req 9-D） ============

def test_d_missing_required_result_with_structured_complete_fail_closed(tmp_path):
    # workbuddy 未执行（结果缺失），但其 structured JSON 存在且 COMPLETE blocking=false
    # → framework 事实（required stage not executed）优先，不得 SUCCESS
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok'},
        out,
    )
    assert status == 'WAITING'


def test_d_missing_required_agent_with_others_ok_not_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for agent in ('hermes', 'workbuddy'):
        _write_stage_json(out, agent, blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS'},  # codex 缺失
        out,
    )
    assert status == 'WAITING'


# ============ E: PASS_WITH_WARNING + explicit no blocking + APPROVE → SUCCESS（Req 5 / Req 9-E） ============

def test_e_pass_with_warning_approve_no_blocking_success_provenance_aware(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for agent, body in {
        'hermes': 'implemented ok',
        'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n历史 FAILED 项已解决',
        'codex': '最终判定：APPROVE\nBlocking Issues: NONE',
    }.items():
        _write_stage_json(out, agent, blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'implemented ok',
         'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n历史 FAILED 项已解决',
         'codex': '最终判定：APPROVE\nBlocking Issues: NONE'},
        out,
    )
    assert status == 'SUCCESS'
    # warning 内容保留（不丢失）
    report = build_report(
        task='T', route=['hermes', 'workbuddy', 'codex'], output_dir=out,
        results={'hermes': 'implemented ok',
                 'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵',
                 'codex': 'APPROVE'},
        status='SUCCESS',
    )
    assert '## Unresolved Issues\nNone identified.' in report
    assert 'W1: 文档瑕疵' in report


def test_e_full_runner_run_success_with_warning(tmp_path, monkeypatch):
    # 真实 runner 路径：结构化块全部 blocking=false → SUCCESS，warning 保留，
    # 且 stage JSON blocking_provenance=structured（explicit structured verdict）
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return _block('implemented ok', 'hermes')
        if agent == 'workbuddy':
            return _block('**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n'
                          'FAILED 场景验证通过（非阻断）', 'workbuddy')
        return _block('最终判定：APPROVE\nBlocking Issues: NONE', 'codex')

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nSUCCESS' in report
    assert '## Unresolved Issues\nNone identified.' in report
    assert 'W1: 文档瑕疵' in report
    for agent in ('workbuddy', 'codex'):
        stage = json.loads((out / f'{agent}_result.json').read_text(encoding='utf-8'))
        assert stage['structured_summary_status'] == 'COMPLETE'
        assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_STRUCTURED


# ============ F: REQUEST_CHANGE → WAITING（Req 9-F） ============

def test_f_request_change_waiting(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'codex', blocking=True, verdict='REQUEST_CHANGE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'REQUEST_CHANGE: fix router'},
        out,
    )
    assert status == 'WAITING'


# ============ G: invalid structured blocking data → fail closed（Req 9-G） ============

def test_g_invalid_structured_blocking_data_fail_closed(tmp_path):
    # blocking_rework 存在但非 bool（如字符串 "false"）→ invalid structured data → fail closed
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text(
        json.dumps({"blocking_rework": "false", "structured_summary_status": "COMPLETE"}),
        encoding="utf-8",
    )
    available, blocking, status, _ = read_structured_blocking('workbuddy', out)
    assert available is False and status == 'INVALID'
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified'},
        out,
    )
    assert status == 'WAITING'


def test_g_invalid_structured_blocking_null_fail_closed(tmp_path):
    # blocking_rework=null 同样是非法 blocking 数据 → fail closed
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text(
        json.dumps({"blocking_rework": None, "structured_summary_status": "COMPLETE"}),
        encoding="utf-8",
    )
    assert agent_result_blocked('workbuddy', '**Result: PASS**\nverified', out) is True


def test_g_missing_blocking_field_legacy_fallback_compatible(tmp_path):
    # 旧 artifact 缺少新 blocking 字段（backward compat）→ legacy narrative fallback，
    # 不是 invalid-data fail-closed（Req 6）
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text(
        json.dumps({"structured_summary_status": "COMPLETE", "warnings": []}),
        encoding="utf-8",
    )
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified'},
        out,
    )
    assert status == 'SUCCESS'


# ============ H: legacy narrative-only → backward compatible 且不 fail-open（Req 6 / Req 9-H） ============

def test_h_legacy_narrative_only_pass_approve_success():
    # 无任何 JSON（legacy 目录）→ narrative 判定兼容
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified', 'codex': 'APPROVE'},
    ) == 'SUCCESS'


def test_h_legacy_narrative_only_fail_not_fail_open():
    # narrative-only + 真阻断 → WAITING（不 fail-open）
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: FAIL**\nB1 broken'},
    ) == 'WAITING'


def test_h_legacy_corrupt_json_falls_back_to_narrative(tmp_path):
    # 损坏 JSON（不可解析）→ legacy narrative fallback（兼容），narrative 阻断仍生效
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text('{"broken": true', encoding='utf-8')
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified'}, out,
    ) == 'SUCCESS'
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': 'FAIL: broken'}, out,
    ) == 'WAITING'


def test_build_stage_result_hermes_structured_block_provenance_narrative(tmp_path):
    # hermes 结构化块无 blocking_rework 字段（schema 无该字段）→ blocking_rework
    # 仍是 narrative 派生值，provenance=narrative（不得伪装成 structured authority）
    stage = build_stage_result(
        agent='hermes',
        result_text='implemented ok. The previously FAILED test now passes.',
        output_dir=tmp_path,
        structured={'status': 'SUCCESS', 'changed_files': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['structured_summary_status'] == 'COMPLETE'
    assert stage['blocking_rework'] is False
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE


def test_a_full_runner_hermes_technical_failed_success(tmp_path, monkeypatch):
    # 真实 runner 路径：hermes SUCCESS narrative 含技术性 FAILED + 结构化块
    # （无 blocking 字段）→ SUCCESS；hermes_result.json provenance=narrative
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return ('implemented ok. The previously FAILED test now passes; fixed the error.'
                    '\nAAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"status": "SUCCESS", "changed_files": [], "warnings": []}'
                    '\nAAF_STRUCTURED_RESULT_END')
        if agent == 'workbuddy':
            return _block('**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵', 'workbuddy')
        return _block('最终判定：APPROVE\nBlocking Issues: NONE', 'codex')

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nSUCCESS' in report
    stage = json.loads((out / 'hermes_result.json').read_text(encoding='utf-8'))
    assert stage['structured_summary_status'] == 'COMPLETE'
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE


# ============ Provenance 完整性（Req 1/2/7） ============

def test_build_stage_result_provenance_structured(tmp_path):
    # agent 显式结构化块显式声明 blocking_provenance=structured → provenance=structured
    # （FIX-002：structured authority 只来自显式字段，不是 blocking_rework key 存在性）
    stage = build_stage_result(
        agent='workbuddy',
        result_text='**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵',
        output_dir=tmp_path,
        structured={'verdict': 'PASS_WITH_WARNING', 'blocking_rework': False,
                    'blocking_provenance': 'structured',
                    'findings': [], 'warnings': ['W1: 文档瑕疵']},
        structured_status='OK',
    )
    assert stage['blocking_rework'] is False
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_STRUCTURED
    assert stage['structured_summary_status'] == 'COMPLETE'


def test_build_stage_result_blocking_rework_key_without_provenance_is_narrative(tmp_path):
    # FIX-002 Req 3：结构化块有 blocking_rework 但**无** blocking_provenance 字段
    # （legacy 形状）→ provenance=narrative，绝不按 key 存在性推断 structured
    stage = build_stage_result(
        agent='workbuddy',
        result_text='**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵',
        output_dir=tmp_path,
        structured={'verdict': 'PASS_WITH_WARNING', 'blocking_rework': False,
                    'findings': [], 'warnings': ['W1: 文档瑕疵']},
        structured_status='OK',
    )
    assert stage['blocking_rework'] is False  # 决策值仍 backward compatible
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE
    assert stage['structured_summary_status'] == 'COMPLETE'


def test_build_stage_result_provenance_framework_overrides_structured(tmp_path):
    # FRAMEWORK_ERROR + 结构化块 blocking=false → framework hard failure 优先
    stage = build_stage_result(
        agent='workbuddy',
        result_text='FRAMEWORK_ERROR\nRuntimeError: boom',
        output_dir=tmp_path,
        structured={'verdict': 'PASS', 'blocking_rework': False,
                    'findings': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['status'] == 'FAILED'
    assert stage['blocking_rework'] is True
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_FRAMEWORK


def test_build_stage_result_provenance_narrative_when_no_structured_block(tmp_path):
    # 无结构化块 → blocking_rework 由 narrative 派生，provenance=narrative（不是 structured）
    stage = build_stage_result(
        agent='hermes',
        result_text='implemented ok. The previously FAILED test now passes.',
        output_dir=tmp_path,
        structured=None,
        structured_status='NOT_PROVIDED',
    )
    assert stage['blocking_rework'] is False
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE
    assert stage['structured_summary_status'] == 'NOT_PROVIDED'


def test_build_stage_result_hermes_narrative_laundering_prevented(tmp_path):
    # Hermes SUCCESS narrative 含技术性 FAILED + 无结构化块 → blocking_rework=False
    # 且 provenance=narrative——下游不得把该值当 structured authority
    stage = build_stage_result(
        agent='hermes',
        result_text='implemented ok. The previously FAILED test now passes; fixed the error.',
        output_dir=tmp_path,
        structured=None,
        structured_status='NOT_PROVIDED',
    )
    assert stage['blocking_rework'] is False
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE
    # 聚合端：narrative provenance 永不进入 authoritative 分支
    out = tmp_path / "out"
    out.mkdir()
    (out / 'hermes_result.json').write_text(json.dumps(stage, ensure_ascii=False), encoding='utf-8')
    assert agent_result_blocked('hermes', stage['summary'], out) is False


def test_read_structured_blocking_legacy_no_provenance_narrative(tmp_path):
    # FIX-002 Req 3/4：旧 artifact 无 blocking_provenance 字段 → 一律 narrative
    # （legacy fallback）。旧框架"reviewer COMPLETE → structured"的推断语义已移除——
    # blocking_rework key 存在 / COMPLETE 标签都不得升级为 structured authority。
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE')  # 无 provenance
    _write_stage_json(out, 'hermes', blocking=False, status='COMPLETE')     # 无 provenance
    _, _, _, prov_wb = read_structured_blocking('workbuddy', out)
    _, _, _, prov_h = read_structured_blocking('hermes', out)
    assert prov_wb == BLOCKING_PROVENANCE_NARRATIVE
    assert prov_h == BLOCKING_PROVENANCE_NARRATIVE


def test_aggregation_precedence_framework_over_structured_verdict(tmp_path):
    # 优先级：framework hard failure > structured verdict（任一 agent 触发即 WAITING）
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': '', 'workbuddy': '**Result: PASS**\nverified'},  # hermes 空结果
        out,
    )
    assert status == 'WAITING'


def test_aggregation_precedence_structured_blocking_over_narrative(tmp_path):
    # explicit blocking structured verdict（codex REQUEST_CHANGE）> narrative no-blocking
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'codex', blocking=True, verdict='REQUEST_CHANGE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'APPROVE'},  # narrative 说通过
        out,
    )
    assert status == 'WAITING'
