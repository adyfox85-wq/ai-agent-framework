"""RW-022 FIX-003 regression tests：FAILED Verdict Consistency（TASK-007-FIX-003 Req 1–6）。

覆盖 Requirement 6 的 A–I：
- A: "Result: FAILED - implementation incomplete." + structured PASS / blocking=false → fail closed
- B: "Verdict: FAILED" → blocking
- C: WorkBuddy FAIL → blocking
- D: Codex REQUEST_CHANGE → blocking
- E: PASS_WITH_WARNING + blocking=false → non-blocking
- F: APPROVE + blocking=false → non-blocking
- G: 技术描述含 FAILED 字样但明确 overall result SUCCESS → 不误判
- H: legacy narrative-only FAILED → blocking
- I: invalid/mismatched structured result → fail closed

核心语义（Req 1/2/5）：
- consistency guard / _derive_verdict 必须识别 FAILED（词形归一化为 FAIL）——
  不得因 \\bFAIL\\b 词边界漏掉 FAILED，造成 structured PASS 覆盖真实失败语义
  （RW-022 fail-open 缺口）。
- 显式通过结论（PASS / PASS_WITH_WARNING / APPROVE / SUCCESS）存在时，
  narrative 中历史 / 技术性 FAILED 引用不视为当前阻断（无 false positive）。
- 三个组件语义一致：context_packet.py / report.py / structured consistency guard
  ——report.verdict_ok 同步识别 SUCCESS，保证聚合 fail-safe 路径不产生规则漂移。
"""
import json
from pathlib import Path

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework.context_packet import (
    STRUCTURED_RESULT_BEGIN,
    STRUCTURED_RESULT_END,
    _derive_verdict,
    build_stage_result,
    check_narrative_json_consistency,
    extract_and_validate_structured,
    write_stage_result,
)
from ai_agent_framework.report import (
    BLOCKING_PROVENANCE_NARRATIVE,
    agent_result_blocked,
    verdict_blocked,
)

MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-RW022-FIX003

# Task Name
FAILED Verdict Consistency 测试

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _tail(agent: str, verdict: str, blocking: bool, warnings=None) -> str:
    """Agent 答复形状的机器可读结构化块。"""
    structured = {
        "workbuddy": {"verdict": verdict, "blocking_rework": blocking,
                      "findings": [], "warnings": warnings or []},
        "codex": {"verdict": verdict, "blocking_rework": blocking,
                  "findings": [], "warnings": warnings or []},
        "hermes": {"status": "SUCCESS", "changed_files": [], "warnings": []},
    }[agent]
    return (STRUCTURED_RESULT_BEGIN + "\n" + json.dumps(structured)
            + "\n" + STRUCTURED_RESULT_END)


def _run_chain(tmp_path, monkeypatch, agents: dict) -> Path:
    """真实 runner 跑完整 agent 链（dummy 结果注入）。返回 output_dir。"""
    def fake_run_agent(agent, prompt, workspace):
        return agents[agent]
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    runner_mod.run(task_file, ws, out)
    return out


# ============ A: "Result: FAILED" + structured PASS / blocking=false → fail closed ============

def test_a_failed_narrative_with_structured_pass_fail_closed(tmp_path):
    # 一致性 guard：narrative 明确 FAILED（无通过结论）+ structured PASS/blocking=false
    # → 不得接受为 authoritative COMPLETE non-blocking（标记 inconsistency）
    body = ("Result: FAILED - implementation incomplete.\n" + _tail("workbuddy", "PASS", False))
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False
    assert stage["verdict"] == "FAIL"  # FAILED 归一化为 FAIL，不得派生成 PASS
    # 聚合 fail-safe：structured 非权威 → narrative FAILED → 阻断
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("workbuddy", "Result: FAILED - implementation incomplete.", out) is True
    assert runner_mod._aggregate_status(
        ["workbuddy"], {"workbuddy": "Result: FAILED - implementation incomplete."}, out,
    ) == "WAITING"


def test_a_full_runner_failed_narrative_structured_pass_waiting(tmp_path, monkeypatch):
    # 真实 runner 路径：workbuddy narrative FAILED + 结构化块 PASS/blocking=false
    # → REPORT WAITING；stage JSON 明确 CONSISTENCY_VIOLATION（不是 COMPLETE）
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("Result: FAILED - implementation incomplete.\n"
                      + _tail("workbuddy", "PASS", False)),
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False
    assert stage["verdict"] == "FAIL"


# ============ B: "Verdict: FAILED" → blocking ============

def test_b_verdict_failed_blocking():
    assert verdict_blocked("hermes", "Verdict: FAILED") is True
    assert verdict_blocked("workbuddy", "Verdict: FAILED") is True
    assert runner_mod._aggregate_status(
        ["workbuddy"], {"workbuddy": "Verdict: FAILED"}) == "WAITING"
    stage = build_stage_result(agent="workbuddy", result_text="Verdict: FAILED", output_dir=".")
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE


# ============ C: WorkBuddy FAIL → blocking ============

def test_c_workbuddy_fail_blocking():
    assert verdict_blocked("workbuddy", "**Result: FAIL**\nB1 broken") is True
    assert runner_mod._aggregate_status(
        ["workbuddy"], {"workbuddy": "**Result: FAIL**\nB1 broken"}) == "WAITING"
    # guard：narrative FAIL（无通过结论）+ structured PASS → 违规
    assert check_narrative_json_consistency(
        "workbuddy", "**Result: FAIL**\nB1 broken",
        {"verdict": "PASS", "blocking_rework": False, "findings": [], "warnings": []},
    )


# ============ D: Codex REQUEST_CHANGE → blocking ============

def test_d_codex_request_change_blocking():
    assert verdict_blocked("codex", "REQUEST_CHANGE: fix router") is True
    assert runner_mod._aggregate_status(
        ["codex"], {"codex": "REQUEST_CHANGE: fix router"}) == "WAITING"
    # guard：narrative REQUEST_CHANGE + structured APPROVE → 违规
    assert check_narrative_json_consistency(
        "codex", "REQUEST_CHANGE: fix router",
        {"verdict": "APPROVE", "blocking_rework": False, "findings": [], "warnings": []},
    )


# ============ E: PASS_WITH_WARNING + blocking=false → non-blocking ============

def test_e_pass_with_warning_blocking_false_non_blocking(tmp_path, monkeypatch):
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n"
                      + _tail("workbuddy", "PASS_WITH_WARNING", False, warnings=["W1: 文档瑕疵"])),
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report


# ============ F: APPROVE + blocking=false → non-blocking ============

def test_f_approve_blocking_false_non_blocking(tmp_path, monkeypatch):
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": "**Result: PASS**\nverified\n" + _tail("workbuddy", "PASS", False),
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report


# ============ G: 技术性 FAILED 字样 + 明确 overall result SUCCESS → 不误判 ============

TECHNICAL_FAILED_NARRATIVE = (
    "implemented and verified. The previously FAILED test is now covered; "
    "the failure handling path works as expected. Overall result: SUCCESS."
)


def test_g_technical_failed_with_overall_success_no_false_positive(tmp_path):
    # guard：FAILED 引用 + 明确 SUCCESS 整体结论 → 不判违规（previous false-positive protection 保持）
    violations = check_narrative_json_consistency(
        "workbuddy", TECHNICAL_FAILED_NARRATIVE,
        {"verdict": "PASS", "blocking_rework": False, "findings": [], "warnings": []},
    )
    assert violations == []
    # report.py 同步语义：verdict_ok 识别 SUCCESS → FAILED 引用不阻断（无规则漂移）
    assert verdict_blocked("workbuddy", TECHNICAL_FAILED_NARRATIVE) is False
    stage = build_stage_result(
        agent="workbuddy", result_text=TECHNICAL_FAILED_NARRATIVE, output_dir=tmp_path,
        structured={"verdict": "PASS", "blocking_rework": False,
                    "findings": [], "warnings": []},
        structured_status="OK",
    )
    assert stage["structured_summary_status"] == "COMPLETE"
    assert stage["summary_complete"] is True
    assert stage["blocking_rework"] is False


def test_g_full_runner_technical_failed_overall_success(tmp_path, monkeypatch):
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": TECHNICAL_FAILED_NARRATIVE + "\n" + _tail("workbuddy", "PASS", False),
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report


def test_g_hermes_technical_failed_success_no_false_positive():
    # hermes：句中 FAILED 非显式判定形态（无 Result:/FAILED: 前缀）→ 不阻断（FIX-001 保护保持）
    body = ("implemented ok. The previously FAILED test now passes; "
            "fixed the error handling. Overall result: SUCCESS.")
    assert verdict_blocked("hermes", body) is False
    assert runner_mod._aggregate_status(["hermes"], {"hermes": body}) == "SUCCESS"


def test_no_false_positive_lowercase_technical_words():
    # 小写技术词（failed test example / failure handling / error path）不匹配全大写结论词
    narrative = ("This test demonstrates a failed test example; the failure handling "
                 "and error path are covered by unit tests.")
    assert verdict_blocked("workbuddy", narrative) is False
    assert check_narrative_json_consistency(
        "workbuddy", narrative,
        {"verdict": "PASS", "blocking_rework": False, "findings": [], "warnings": []},
    ) == []


# ============ H: legacy narrative-only FAILED → blocking ============

def test_h_legacy_narrative_only_failed_blocking():
    # 无 structured（legacy）→ narrative-only FAILED 必须阻断（不 fail-open）
    assert runner_mod._aggregate_status(
        ["workbuddy"], {"workbuddy": "Result: FAILED - implementation incomplete."}) == "WAITING"
    assert runner_mod._aggregate_status(
        ["hermes"], {"hermes": "Result: FAILED - implementation incomplete."}) == "WAITING"
    stage = build_stage_result(
        agent="workbuddy", result_text="Result: FAILED - implementation incomplete.", output_dir=".",
    )
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE


# ============ I: invalid/mismatched structured result → fail closed ============

def test_i_mismatched_structured_result_fail_closed(tmp_path):
    # codex narrative REQUEST_CHANGE + structured APPROVE/blocking=false
    # → narrative verdict 与 structured verdict 冲突 → 不得被接受（fail closed）
    body = ("REQUEST_CHANGE: docs need rework\n" + _tail("codex", "APPROVE", False))
    data, status = extract_and_validate_structured("codex", body)
    stage = build_stage_result(agent="codex", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("codex", "REQUEST_CHANGE: docs need rework", out) is True


def test_i_invalid_structured_result_fail_closed(tmp_path):
    # blocking_rework 类型非法 → schema 拒绝（MALFORMED）→ 结构化结果不被接受为权威；
    # narrative FAILED → 聚合 fail closed → WAITING
    body = ("Result: FAILED - implementation incomplete.\n"
            + STRUCTURED_RESULT_BEGIN + "\n"
            + '{"verdict": "PASS", "blocking_rework": "yes", "findings": [], "warnings": []}\n'
            + STRUCTURED_RESULT_END)
    data, status = extract_and_validate_structured("workbuddy", body)
    assert data is None and status == "MALFORMED"
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "MALFORMED"
    assert stage["summary_complete"] is False
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": body}, out) == "WAITING"


# ============ Requirement 1：guard 识别全部显式失败语义 ============

@pytest.mark.parametrize("narrative", [
    "Result: FAIL",
    "Result: FAILED",
    "REQUEST_CHANGE: x",
    "FRAMEWORK_ERROR\nboom",
])
def test_guard_recognizes_all_explicit_failure_semantics(narrative):
    # guard 必须识别 FAIL / FAILED / REQUEST_CHANGE / FRAMEWORK_ERROR——
    # structured 声称 PASS/blocking=false 时一律判违规（fail closed）
    violations = check_narrative_json_consistency(
        "workbuddy", narrative,
        {"verdict": "PASS", "blocking_rework": False, "findings": [], "warnings": []},
    )
    assert violations, narrative


# ============ Requirement 2：_derive_verdict 词形归一化 ============

def test_derive_verdict_failed_normalization():
    # FAILED → FAIL（不派生成 PASS / PASS_WITH_WARNING）
    assert _derive_verdict("workbuddy", "Result: FAILED - implementation incomplete.") == "FAIL"
    assert _derive_verdict("workbuddy", "Verdict: FAILED") == "FAIL"
    assert _derive_verdict("workbuddy", "**Result: FAIL**") == "FAIL"
    # 显式通过结论存在 → 派生通过结论（历史/技术性 FAILED 引用不覆盖）
    assert _derive_verdict(
        "workbuddy", "**Result: PASS_WITH_WARNING**\n历史 FAILED 项已解决") == "PASS_WITH_WARNING"
    assert _derive_verdict(
        "workbuddy", "previously FAILED test now passes. Overall result: SUCCESS.") == "PASS"
    # codex：REQUEST_CHANGE 不派生成 APPROVE；SUCCESS 归一化为 APPROVE
    assert _derive_verdict("codex", "REQUEST_CHANGE: fix router") == "REQUEST_CHANGE"
    assert _derive_verdict("codex", "previous REQUEST_CHANGE resolved; APPROVE") == "APPROVE"
    assert _derive_verdict("codex", "Overall result: SUCCESS.") == "APPROVE"
    # 无结论词 / FRAMEWORK_ERROR 开头 → None
    assert _derive_verdict("workbuddy", "implemented ok") is None
    assert _derive_verdict("workbuddy", "FRAMEWORK_ERROR\nboom") is None
    assert _derive_verdict("hermes", "Result: FAILED") is None  # Hermes 无 verdict 语义
