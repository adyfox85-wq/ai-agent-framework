"""RW-022 FIX-004 regression tests：Consistency Violation Blocking Synchronization（TASK-007-FIX-004）。

核心缺陷（FIX-004）：
- CONSISTENCY_VIOLATION 时 FIX-003 已把 verdict 恢复为 narrative-derived FAIL，
  但 blocking_rework 仍保留 structured false → verdict=FAIL / blocking_rework=false
  内部语义矛盾，下游聚合可能据此 fail-open。
- FIX-004：violation 恢复 narrative-derived blocking verdict 时同步
  blocking_rework=True（fail-closed），并建立全局 invariant：
  blocking verdict → blocking_rework 必须 True（所有路径兜底）。

覆盖 TASK-007-FIX-004 Requirement 5 的 A–F：
- A: narrative FAIL + structured PASS/blocking=false → verdict FAIL + blocking=true
- B: narrative FAILED + structured PASS/blocking=false → verdict FAIL + blocking=true
- C: narrative REQUEST_CHANGE + structured APPROVE/blocking=false → REQUEST_CHANGE + blocking=true
- D: narrative SUCCESS + malformed blocking structured claim → 按 existing fail-safe
  policy 处理，不得 fail-open（非法 provenance → fail closed；schema 拒绝的
  blocking 声明不得成为权威）
- E: PASS_WITH_WARNING + explicit blocking=false + 无 inconsistency → blocking=false
- F: APPROVE + blocking=false → blocking=false

+ Requirement 3（non-blocking narrative 不得机械置 True）/ Requirement 4
（internal invariant）/ Requirement 7（aggregation 读取 corrected stage result）/
Requirement 6（previous RW-022 protections 无回归）。
"""
import json
from pathlib import Path

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework.context_packet import (
    STRUCTURED_RESULT_BEGIN,
    STRUCTURED_RESULT_END,
    _derive_verdict,
    blocking_invariant_violations,
    build_stage_result,
    check_narrative_json_consistency,
    extract_and_validate_structured,
    write_stage_result,
)
from ai_agent_framework.report import (
    BLOCKING_PROVENANCE_FRAMEWORK,
    BLOCKING_PROVENANCE_NARRATIVE,
    agent_result_blocked,
    verdict_blocked,
)
from ai_agent_framework.verdict_parser import parse_canonical_verdict

MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-RW022-FIX004

# Task Name
Consistency Violation Blocking Synchronization 测试

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _tail(agent: str, verdict: str, blocking: bool, warnings=None) -> str:
    """Agent 答复形状的机器可读结构化块（legacy 形状：无 blocking_provenance 字段）。"""
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


# ============ A: narrative FAIL + structured PASS / blocking=false → FAIL + blocking=true ============

def test_a_narrative_fail_structured_pass_blocking_synced(tmp_path):
    body = "**Result: FAIL**\nB1 broken\n" + _tail("workbuddy", "PASS", False)
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False
    assert stage["verdict"] == "FAIL"
    # FIX-004 核心：verdict=FAIL 不得对应 blocking_rework=false（同步为 True）
    assert stage["blocking_rework"] is True
    # blocking 由 narrative consistency recovery 得出 → provenance=narrative（不得伪装 structured）
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []
    # aggregation 读取 corrected stage result → 阻断
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("workbuddy", body, out) is True
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": body}, out) == "WAITING"


def test_a_full_runner_stage_json_synced_blocking(tmp_path, monkeypatch):
    # 端到端核心场景：narrative FAIL + structured PASS/blocking=false
    # → stage JSON 必须 verdict=FAIL AND blocking_rework=True AND CONSISTENCY_VIOLATION
    #   （FIX-004 修复前 blocking_rework 是 false——自相矛盾）；REPORT WAITING
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("**Result: FAIL**\nB1 broken\n" + _tail("workbuddy", "PASS", False)),
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []


# ============ B: narrative FAILED + structured PASS / blocking=false → FAIL + blocking=true ============

def test_b_narrative_failed_structured_pass_blocking_synced(tmp_path):
    body = "Result: FAILED - implementation incomplete.\n" + _tail("workbuddy", "PASS", False)
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "FAIL"  # FAILED 归一化为 FAIL
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": body}, out) == "WAITING"


# ============ C: narrative REQUEST_CHANGE + structured APPROVE / blocking=false → REQUEST_CHANGE + blocking=true ============

def test_c_narrative_request_change_structured_approve_blocking_synced(tmp_path):
    body = "REQUEST_CHANGE: docs need rework\n" + _tail("codex", "APPROVE", False)
    data, status = extract_and_validate_structured("codex", body)
    stage = build_stage_result(agent="codex", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "REQUEST_CHANGE"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("codex", body, out) is True
    assert runner_mod._aggregate_status(["codex"], {"codex": body}, out) == "WAITING"


# ============ D: narrative SUCCESS + malformed blocking structured claim → fail-safe，不得 fail-open ============

def test_d_success_narrative_invalid_provenance_fail_closed(tmp_path):
    # 非法 blocking_provenance（bogus）= malformed blocking claim → fail closed：
    # blocking_rework=True + provenance=framework + MALFORMED，即使 narrative 明确 SUCCESS
    body = ("All checks passed. SUCCESS.\n" + STRUCTURED_RESULT_BEGIN + "\n"
            + json.dumps({"verdict": "PASS", "blocking_rework": False,
                          "blocking_provenance": "bogus",
                          "findings": [], "warnings": []})
            + "\n" + STRUCTURED_RESULT_END)
    data, status = extract_and_validate_structured("workbuddy", body)
    assert data is not None and status == "OK"  # schema 放行 → build_stage_result 判定
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "MALFORMED"
    assert stage["summary_complete"] is False
    assert stage["blocking_rework"] is True  # 不得 fail-open
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_FRAMEWORK
    assert blocking_invariant_violations(stage) == []
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("workbuddy", body, out) is True
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": body}, out) == "WAITING"


def test_d_success_narrative_schema_malformed_claim_not_authoritative(tmp_path):
    # blocking_rework 类型非法 → schema 拒绝整块（MALFORMED）：malformed claim 永远
    # 不能成为 no-blocking authority；决策回到 narrative（FIX-005 canonical
    # semantic——narrative 明确 overall result SUCCESS 且无任何阻断信号 → 非阻断）
    body = ("All checks passed.\nOverall result: SUCCESS.\n" + STRUCTURED_RESULT_BEGIN + "\n"
            + json.dumps({"verdict": "PASS", "blocking_rework": "yes",
                          "findings": [], "warnings": []})
            + "\n" + STRUCTURED_RESULT_END)
    data, status = extract_and_validate_structured("workbuddy", body)
    assert data is None and status == "MALFORMED"
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "MALFORMED"
    assert stage["summary_complete"] is False
    assert stage["verdict"] == "PASS"
    assert stage["blocking_rework"] is False  # 来自 narrative（canonical SUCCESS），不是 malformed claim
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []
    # malformed claim 被拒绝（MALFORMED + summary_complete=False）→ 不是 structured authority；
    # aggregation 走 narrative：narrative 明确 overall result SUCCESS 且无阻断信号 → 非阻断
    # （existing fail-safe policy）；malformed claim 本身在任何情况下都不能声明权威 no-blocking
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked(
        "workbuddy", "All checks passed.\nOverall result: SUCCESS.", out) is False
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": body}, out) == "SUCCESS"
    # FIX-005：无 canonical verdict 行的 ambiguous narrative（"SUCCESS." 是句中
    # token，不是 verdict 行）→ 不猜 PASS → verdict=None + fail-safe 阻断（不 fail-open）
    ambiguous = ("All checks passed. SUCCESS.\n" + STRUCTURED_RESULT_BEGIN + "\n"
                 + json.dumps({"verdict": "PASS", "blocking_rework": "yes",
                               "findings": [], "warnings": []})
                 + "\n" + STRUCTURED_RESULT_END)
    assert parse_canonical_verdict("All checks passed. SUCCESS.") is None
    data3, status3 = extract_and_validate_structured("workbuddy", ambiguous)
    assert data3 is None and status3 == "MALFORMED"
    stage3 = build_stage_result(agent="workbuddy", result_text=ambiguous, output_dir=tmp_path,
                                structured=data3, structured_status=status3)
    assert stage3["verdict"] is None
    assert stage3["blocking_rework"] is True
    assert blocking_invariant_violations(stage3) == []
    # 同一 rejection 路径下 narrative 带阻断信号 → 仍 fail closed（不因 MALFORMED 而 fail-open）
    fail_body = ("Result: FAILED - implementation incomplete.\n" + STRUCTURED_RESULT_BEGIN + "\n"
                 + json.dumps({"verdict": "PASS", "blocking_rework": "yes",
                               "findings": [], "warnings": []})
                 + "\n" + STRUCTURED_RESULT_END)
    data2, status2 = extract_and_validate_structured("workbuddy", fail_body)
    assert data2 is None and status2 == "MALFORMED"
    stage2 = build_stage_result(agent="workbuddy", result_text=fail_body, output_dir=tmp_path,
                                structured=data2, structured_status=status2)
    assert stage2["blocking_rework"] is True  # narrative FAILED → blocking（fail closed）
    write_stage_result(out, stage2)
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": fail_body}, out) == "WAITING"


# ============ E: PASS_WITH_WARNING + explicit blocking=false + 无 inconsistency → blocking=false ============

def test_e_pass_with_warning_blocking_false_not_flipped(tmp_path, monkeypatch):
    body = ("**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n"
            + _tail("workbuddy", "PASS_WITH_WARNING", False, warnings=["W1: 文档瑕疵"]))
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "COMPLETE"
    assert stage["verdict"] == "PASS_WITH_WARNING"
    assert stage["blocking_rework"] is False  # 不机械翻转
    assert blocking_invariant_violations(stage) == []
    # 完整链：PASS_WITH_WARNING + APPROVE + no blocking → SUCCESS
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": body,
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    wb_stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert wb_stage["blocking_rework"] is False
    assert blocking_invariant_violations(wb_stage) == []


# ============ F: APPROVE + blocking=false → blocking=false ============

def test_f_approve_blocking_false_not_flipped(tmp_path, monkeypatch):
    body = "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False)
    data, status = extract_and_validate_structured("codex", body)
    stage = build_stage_result(agent="codex", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "COMPLETE"
    assert stage["verdict"] == "APPROVE"
    assert stage["blocking_rework"] is False  # 不机械翻转
    assert blocking_invariant_violations(stage) == []
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": "**Result: PASS**\nverified\n" + _tail("workbuddy", "PASS", False),
        "codex": body,
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    cx_stage = json.loads((out / "codex_result.json").read_text(encoding="utf-8"))
    assert cx_stage["blocking_rework"] is False
    assert blocking_invariant_violations(cx_stage) == []


# ============ Requirement 3：non-blocking narrative 不得机械置 True ============

def test_violation_with_non_blocking_narrative_not_mechanically_blocked(tmp_path):
    # 违规仅来自 warnings 消失，narrative 明确 PASS → blocking 不得被机械置 True
    # （violation 本身不创造 blocking；blocking 由 narrative-derived verdict 决定）
    body = "**Result: PASS**\nW1: 文档瑕疵\n" + _tail("workbuddy", "PASS", False, warnings=[])
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "PASS"
    assert stage["blocking_rework"] is False  # 不机械翻转
    assert blocking_invariant_violations(stage) == []


def test_violation_narrative_pass_structured_fail_not_mechanical(tmp_path):
    # narrative 明确 PASS + structured 声称 FAIL/blocking=true → violation；
    # narrative-derived verdict 非 blocking → 不因 violation 机械翻转 blocking
    # （structured 声称的 blocking=True 保留——fail-safe 方向不受审查）；provenance=narrative
    body = ("All items verified.\n## Result: PASS\n"
            + STRUCTURED_RESULT_BEGIN + "\n"
            + json.dumps({"verdict": "FAIL", "blocking_rework": True,
                          "findings": [], "warnings": []})
            + "\n" + STRUCTURED_RESULT_END)
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "PASS"  # narrative-derived 通过结论
    assert stage["blocking_rework"] is True  # 来自 structured 声明（未机械翻转成 False）
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []


# ============ Requirement 4：internal invariant（blocking verdict ↔ blocking_rework） ============

def test_invariant_check_flags_blocking_verdict_without_blocking():
    problems = blocking_invariant_violations(
        {"verdict": "FAIL", "blocking_rework": False, "status": "SUCCESS"})
    assert any("blocking verdict" in p for p in problems)
    assert blocking_invariant_violations(
        {"verdict": "REQUEST_CHANGE", "blocking_rework": False, "status": "SUCCESS"})
    assert blocking_invariant_violations(
        {"verdict": "FAILED", "blocking_rework": False, "status": "SUCCESS"})
    assert blocking_invariant_violations(
        {"verdict": "FRAMEWORK_ERROR", "blocking_rework": False, "status": "SUCCESS"})


def test_invariant_check_flags_framework_hard_failure_without_blocking():
    # framework hard failure（status=FAILED）→ blocking_rework 必须 True，无论 agent 声称
    problems = blocking_invariant_violations(
        {"verdict": "PASS", "blocking_rework": False, "status": "FAILED"})
    assert any("framework hard failure" in p for p in problems)


def test_invariant_check_accepts_valid_stages():
    assert blocking_invariant_violations(
        {"verdict": "FAIL", "blocking_rework": True, "status": "FAILED"}) == []
    assert blocking_invariant_violations(
        {"verdict": "PASS", "blocking_rework": False, "status": "SUCCESS"}) == []
    assert blocking_invariant_violations(
        {"verdict": "PASS_WITH_WARNING", "blocking_rework": False, "status": "SUCCESS"}) == []
    assert blocking_invariant_violations(
        {"verdict": "APPROVE", "blocking_rework": False, "status": "SUCCESS"}) == []
    # hermes 无 verdict 语义 → None 不算 blocking verdict
    assert blocking_invariant_violations(
        {"verdict": None, "blocking_rework": False, "status": "SUCCESS"}) == []
    # agent 显式声明 provenance=framework（FIX-002 声明语义）不是 framework hard failure
    assert blocking_invariant_violations(
        {"verdict": "APPROVE", "blocking_rework": False, "status": "SUCCESS",
         "blocking_provenance": "framework"}) == []


def test_build_stage_result_outputs_satisfy_invariant(tmp_path):
    # A–F + framework hard failure 路径的全部 build_stage_result 产物必须满足 invariant
    stages = []
    body = "**Result: FAIL**\nB1 broken\n" + _tail("workbuddy", "PASS", False)
    data, status = extract_and_validate_structured("workbuddy", body)
    stages.append(build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                                     structured=data, structured_status=status))
    body = "Result: FAILED - implementation incomplete.\n" + _tail("workbuddy", "PASS", False)
    data, status = extract_and_validate_structured("workbuddy", body)
    stages.append(build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                                     structured=data, structured_status=status))
    body = "REQUEST_CHANGE: docs need rework\n" + _tail("codex", "APPROVE", False)
    data, status = extract_and_validate_structured("codex", body)
    stages.append(build_stage_result(agent="codex", result_text=body, output_dir=tmp_path,
                                     structured=data, structured_status=status))
    body = ("**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n"
            + _tail("workbuddy", "PASS_WITH_WARNING", False, warnings=["W1: 文档瑕疵"]))
    data, status = extract_and_validate_structured("workbuddy", body)
    stages.append(build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                                     structured=data, structured_status=status))
    body = "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False)
    data, status = extract_and_validate_structured("codex", body)
    stages.append(build_stage_result(agent="codex", result_text=body, output_dir=tmp_path,
                                     structured=data, structured_status=status))
    # framework hard failure：FRAMEWORK_ERROR + structured no-blocking / 空结果
    stages.append(build_stage_result(agent="workbuddy", result_text="FRAMEWORK_ERROR\nboom",
                                     output_dir=tmp_path,
                                     structured={"verdict": "PASS", "blocking_rework": False,
                                                 "findings": [], "warnings": []},
                                     structured_status="OK"))
    stages.append(build_stage_result(agent="workbuddy", result_text="", output_dir=tmp_path))
    # 非法 provenance → fail closed
    stages.append(build_stage_result(agent="workbuddy", result_text="All checks passed. SUCCESS.",
                                     output_dir=tmp_path,
                                     structured={"verdict": "PASS", "blocking_rework": False,
                                                 "blocking_provenance": "bogus",
                                                 "findings": [], "warnings": []},
                                     structured_status="OK"))
    for stage in stages:
        assert blocking_invariant_violations(stage) == [], stage


def test_structured_only_fail_verdict_blocking_false_fail_closed(tmp_path):
    # 边角：narrative 无显式结论词（guard 无违规）但 structured 直接声明 verdict=FAIL +
    # blocking_rework=false（structured 内部自相矛盾）→ final invariant 兜底 fail-closed：
    # blocking verdict → blocking_rework 必须 True
    stage = build_stage_result(
        agent="workbuddy", result_text="implemented ok. tested everything.", output_dir=tmp_path,
        structured={"verdict": "FAIL", "blocking_rework": False,
                    "blocking_provenance": "structured",
                    "findings": [], "warnings": []},
        structured_status="OK",
    )
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True  # final invariant 兜底（不得 FAIL + no-blocking）
    assert blocking_invariant_violations(stage) == []
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("workbuddy", "implemented ok. tested everything.", out) is True


# ============ Requirement 7：aggregation 读取 corrected stage result ============

def test_aggregation_fail_request_change_never_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for agent, body in (
        ("workbuddy", "**Result: FAIL**\nB1 broken\n" + _tail("workbuddy", "PASS", False)),
        ("codex", "REQUEST_CHANGE: docs need rework\n" + _tail("codex", "APPROVE", False)),
    ):
        data, status = extract_and_validate_structured(agent, body)
        stage = build_stage_result(agent=agent, result_text=body, output_dir=tmp_path,
                                   structured=data, structured_status=status)
        write_stage_result(out, stage)
        assert stage["blocking_rework"] is True
        assert runner_mod._aggregate_status([agent], {agent: body}, out) == "WAITING"
        assert "## Current Status\nWAITING" in runner_mod.build_report(
            "t", [agent], {agent: body}, "WAITING", output_dir=out)


def test_aggregation_pass_with_warning_approve_no_blocking_success(tmp_path, monkeypatch):
    # PASS_WITH_WARNING + APPROVE + no blocking → SUCCESS（不被 FIX-004 误伤）
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n"
                      + _tail("workbuddy", "PASS_WITH_WARNING", False,
                              warnings=["W1: 文档瑕疵"])),
        "codex": "最终判定：APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report


# ============ Requirement 6：previous RW-022 protections 无回归 ============

def test_failed_recognition_preserved():
    assert _derive_verdict("workbuddy", "Result: FAILED - implementation incomplete.") == "FAIL"
    assert verdict_blocked("workbuddy", "Result: FAILED - implementation incomplete.") is True
    # technical FAILED false-positive protection：明确 overall SUCCESS → 不误判
    technical = ("implemented and verified. The previously FAILED test is now covered; "
                 "the failure handling path works as expected.\n"
                 "Overall result: SUCCESS.")
    assert verdict_blocked("workbuddy", technical) is False
    assert check_narrative_json_consistency(
        "workbuddy", technical,
        {"verdict": "PASS", "blocking_rework": False, "findings": [], "warnings": []}) == []


def test_framework_error_and_empty_result_fail_closed_preserved(tmp_path):
    stage = build_stage_result(
        agent="workbuddy", result_text="FRAMEWORK_ERROR\nRuntimeError: boom", output_dir=tmp_path,
        structured={"verdict": "PASS", "blocking_rework": False,
                    "findings": [], "warnings": []},
        structured_status="OK",
    )
    assert stage["status"] == "FAILED"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_FRAMEWORK
    assert blocking_invariant_violations(stage) == []
    empty = build_stage_result(agent="workbuddy", result_text="", output_dir=tmp_path)
    assert empty["status"] == "FAILED"
    assert empty["blocking_rework"] is True
    assert empty["blocking_provenance"] == BLOCKING_PROVENANCE_FRAMEWORK
    assert blocking_invariant_violations(empty) == []


def test_legacy_narrative_fallback_preserved(tmp_path):
    # legacy（无 structured）narrative REQUEST_CHANGE → blocking + provenance=narrative
    stage = build_stage_result(agent="codex", result_text="REQUEST_CHANGE: docs need rework",
                               output_dir=tmp_path)
    assert stage["verdict"] == "REQUEST_CHANGE"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    assert blocking_invariant_violations(stage) == []
    assert runner_mod._aggregate_status(["codex"], {"codex": "REQUEST_CHANGE: docs need rework"}) == "WAITING"


def test_success_with_warning_semantics_preserved(tmp_path):
    # narrative SUCCESS + W1 标记 + structured PASS/warnings 同步 → COMPLETE 非阻断
    body = ("Overall result: SUCCESS\nW1: 文档瑕疵\n"
            + _tail("workbuddy", "PASS", False, warnings=["W1: 文档瑕疵"]))
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "COMPLETE"
    assert stage["verdict"] == "PASS"  # SUCCESS → PASS（official verdict）
    assert stage["blocking_rework"] is False
    assert blocking_invariant_violations(stage) == []


def test_no_false_positive_lowercase_technical_words():
    # 小写技术词（failed test example / failure handling / error path）不是全大写
    # 结论 token → 不产生 canonical verdict（FIX-005：正文 token 无权威）
    narrative = ("This test demonstrates a failed test example; the failure handling "
                 "and error path are covered by unit tests.")
    assert parse_canonical_verdict(narrative) is None
    assert check_narrative_json_consistency(
        "workbuddy", narrative,
        {"verdict": "PASS", "blocking_rework": False, "findings": [], "warnings": []}) == []
    # 无 canonical verdict 行的 ambiguous narrative（Requirement 7）：required
    # agent（workbuddy）不得凭正文 token 猜通过 → fail-safe 阻断（不 fail-open）；
    # hermes（无 verdict 语义）技术性描述不阻断
    assert verdict_blocked("workbuddy", narrative) is True
    assert verdict_blocked("hermes", narrative) is False
