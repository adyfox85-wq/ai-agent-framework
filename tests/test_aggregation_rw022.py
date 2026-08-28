"""RW-022 Final Status Aggregation regression tests（TASK-007 Requirement 13 A–G）。

核心语义：
- Blocking（→ WAITING）：FAIL / REQUEST_CHANGE / FRAMEWORK_ERROR / required agent
  缺失 / unresolved blocking issue / 真阻断 warning
- Non-blocking（→ SUCCESS）：PASS_WITH_WARNING / informational warning /
  recommendation / APPROVE + Blocking NONE
- Structured result 优先（<agent>_result.json blocking_rework）；legacy narrative
  fallback 保持兼容且 fail-safe（无法证明无阻断时不得 SUCCESS）
"""
import json
from pathlib import Path

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework.report import agent_result_blocked, build_report

MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-RW022

# Task Name
聚合语义测试

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
    """narrative + 结构化块（Agent 答复形状）。"""
    structured = {
        "workbuddy": {"verdict": "PASS_WITH_WARNING", "blocking_rework": False,
                      "findings": [], "warnings": ["W1: 文档瑕疵"]},
        "codex": {"verdict": "APPROVE", "blocking_rework": False, "findings": [], "warnings": []},
        "hermes": {"status": "SUCCESS", "changed_files": [], "warnings": []},
    }[agent]
    return (text + "\nAAF_STRUCTURED_RESULT_BEGIN\n"
            + json.dumps(structured) + "\nAAF_STRUCTURED_RESULT_END")


# --- A: PASS_WITH_WARNING + APPROVE + no blocking → SUCCESS ---

def test_a_pass_with_warning_approve_no_blocking_success():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {
            'hermes': 'implemented ok',
            'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n'
                         '历史 FAILED 项已解决，无 blocking rework',
            'codex': '最终判定：APPROVE\nBlocking Issues: NONE\n'
                     '历史 FAILED 场景均已验证通过（非阻断）',
        },
    )
    assert status == 'SUCCESS'


def test_a_structured_blocking_false_wins_over_narrative_failed_token(tmp_path):
    # RW-022 核心：narrative 含 FAILED 字样，但结构化 blocking_rework=false
    # （Agent 显式声明无阻断）→ SUCCESS（structured first，不再用关键词猜测）
    out = tmp_path / "out"
    out.mkdir()
    for agent, body in {
        'hermes': 'implemented ok',
        'workbuddy': '**Result: PASS_WITH_WARNING**\nFAILED to reproduce a flake (non-blocking)',
        'codex': 'APPROVE\nFAILED items were historical',
    }.items():
        _write_stage_json(out, agent, blocking=False)
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'implemented ok',
         'workbuddy': '**Result: PASS_WITH_WARNING**\nFAILED to reproduce a flake (non-blocking)',
         'codex': 'APPROVE\nFAILED items were historical'},
        out,
    )
    assert status == 'SUCCESS'


def test_a_full_run_success_with_warning_report(tmp_path, monkeypatch):
    # 真实 runner 路径：agent 答复含结构化块 → REPORT Current Status = SUCCESS
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
    # warning 内容保留（Req 8：不因 warning 文本变成 WAITING，但 warning 不丢失）
    assert 'W1: 文档瑕疵' in report


# --- B: REQUEST_CHANGE → WAITING ---

def test_b_request_change_waiting():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'REQUEST_CHANGE: fix router'},
    )
    assert status == 'WAITING'


def test_b_structured_blocking_true_waiting(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'codex', blocking=True, verdict='REQUEST_CHANGE')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'REQUEST_CHANGE: fix router'},
        out,
    )
    assert status == 'WAITING'


# --- C: WorkBuddy missing → 不得 SUCCESS ---

def test_c_workbuddy_missing_not_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'hermes', blocking=False)
    # workbuddy 无 JSON（未执行）→ 空结果 → blocked
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'], {'hermes': 'ok'}, out,
    )
    assert status == 'WAITING'


# --- D: Codex required but not run → 不得 SUCCESS ---

def test_d_codex_not_run_not_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for agent in ('hermes', 'workbuddy'):
        _write_stage_json(out, agent, blocking=False)
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS'},  # codex 缺失
        out,
    )
    assert status == 'WAITING'


# --- E: FRAMEWORK_ERROR → 不得 SUCCESS ---

def test_e_framework_error_not_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'hermes', blocking=False)
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': 'FRAMEWORK_ERROR\nRuntimeError: boom'},
        out,
    )
    assert status == 'WAITING'


# --- F: informational warning only → 不强制 WAITING ---

def test_f_informational_warning_only_not_waiting():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'implemented', 'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 建议补充文档'},
    )
    assert status == 'SUCCESS'


def test_f_structured_warning_blocking_false_not_waiting(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, warnings=["W1: 建议补充文档"])
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'implemented', 'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 建议补充文档'},
        out,
    )
    assert status == 'SUCCESS'


# --- G: legacy narrative fallback → 保持兼容且不 fail-open ---

def test_g_legacy_fallback_compatible_no_json(tmp_path):
    # 无 <agent>_result.json（legacy 目录）→ narrative keyword 判定（原行为）
    out = tmp_path / "out"
    out.mkdir()
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'APPROVE'}, out,
    ) == 'SUCCESS'


def test_g_legacy_fallback_fail_safe_empty_result():
    # 空结果 → blocked（不 fail-open）
    assert runner_mod._aggregate_status(['hermes'], {'hermes': ''}) == 'WAITING'
    assert runner_mod._aggregate_status(['hermes', 'workbuddy'], {'hermes': 'ok'}) == 'WAITING'


def test_g_legacy_fallback_fail_safe_framework_error():
    assert runner_mod._aggregate_status(
        ['hermes'], {'hermes': 'FRAMEWORK_ERROR\nboom'}) == 'WAITING'


def test_g_legacy_fallback_not_fail_open_hermes_failed():
    # Hermes FAILED（无 verdict 语义）→ 阻断
    assert runner_mod._aggregate_status(['hermes'], {'hermes': 'FAILED: 实现不完整'}) == 'WAITING'


def test_g_legacy_fallback_reviewer_failed_without_pass():
    # 无通过结论的 FAILED → 阻断
    assert runner_mod._aggregate_status(
        ['workbuddy'], {'workbuddy': '**Result: FAILED**\nB1 broken'}) == 'WAITING'


# --- structured 非 COMPLETE（MALFORMED / CONSISTENCY_VIOLATION）fail-safe ---

def test_structured_violation_cross_check_fail_safe(tmp_path):
    # JSON blocking=false 但 status=CONSISTENCY_VIOLATION + narrative 有 FAIL → 阻断
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='CONSISTENCY_VIOLATION')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': 'FAIL: 真阻断'}, out,
    )
    assert status == 'WAITING'


def test_structured_malformed_falls_back_to_narrative(tmp_path):
    # JSON blocking_rework 缺失（损坏）→ narrative fallback（PASS → 不阻断）
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text('{"broken": true', encoding='utf-8')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified'}, out,
    )
    assert status == 'SUCCESS'


def test_structured_malformed_narrative_fail_blocks(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text('{"broken": true', encoding='utf-8')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': 'FAIL: broken'}, out,
    )
    assert status == 'WAITING'


# --- agent_result_blocked / unresolved 结构化一致性 ---

def test_agent_result_blocked_structured_first(tmp_path):
    # FIX-002：structured authority 需显式 provenance=structured（legacy 无 provenance
    # 已不推断 structured）；此测试保持"structured verdict 优先于 narrative"优先级
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, provenance='structured')
    assert agent_result_blocked('workbuddy', '**Result: FAIL**\nold text', out) is False
    _write_stage_json(out, 'workbuddy', blocking=True, verdict='REQUEST_CHANGE', provenance='structured')
    assert agent_result_blocked('workbuddy', 'PASS', out) is True


def test_unresolved_structured_first(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, provenance='structured')
    report = build_report(
        task='T', route=['hermes', 'workbuddy'], output_dir=out,
        results={'hermes': 'ok', 'workbuddy': '**Result: FAIL**\n历史文本'}, status='SUCCESS',
    )
    assert '## Unresolved Issues\nNone identified.' in report
