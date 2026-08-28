"""RW-022 FIX-005 regression tests：Canonical Verdict Parsing（TASK-007-FIX-005）。

核心缺陷（FIX-005，RW-022 最后根因）：
- 旧 framework 扫描整篇 narrative 任意位置的 PASS / PASS_WITH_WARNING / SUCCESS /
  FAIL / FAILED 等词，让正文标题、示例、历史引用覆盖真实 overall verdict。
- CLOSURE-003 已真实复现：WorkBuddy narrative 首行 ``## VERDICT: **FAIL**``，
  但正文存在 ``## PASS 证据`` → 旧 parser 生成 verdict=PASS_WITH_WARNING /
  blocking_rework=false → Codex REQUEST_CHANGE 后最终 REPORT 仍 SUCCESS（fail-open）。

FIX-005 收敛为：legacy narrative verdict 只从**明确、可识别的 overall
conclusion / verdict / result 行**解析（Requirement 1–3）；正文 token 只是
内容不是结论（Requirement 2）；无 canonical verdict 行的 ambiguous narrative
不得 fail-open（Requirement 7）。

覆盖：
- Canonical verdict parser 单元测试（Requirement 1 的全部形态 + 正文无权威）
- Adversarial Matrix A–L（Requirement 12）
- REPORT 聚合回归（Requirement 11）
- context_packet / report 统一 canonical semantic（Requirement 13）
- CLOSURE-003 shape 回归（Requirement 12-L）
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
    extract_and_validate_structured,
    write_stage_result,
)
from ai_agent_framework.report import (
    BLOCKING_PROVENANCE_NARRATIVE,
    agent_result_blocked,
    build_report,
    verdict_blocked,
)
from ai_agent_framework.verdict_parser import canonical_blocking, parse_canonical_verdict

MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-RW022-FIX005

# Task Name
Canonical Verdict Parsing 测试

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _tail(agent: str, verdict: str, blocking: bool, warnings=None) -> str:
    """Agent 答复形状的机器可读结构化块（legacy 形状：无 blocking_provenance）。"""
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


# ============ Requirement 1：Canonical Verdict Source 单元测试 ============

@pytest.mark.parametrize("narrative,agent,expected_verdict,expected_blocked,expected_token", [
    # 任务列出的全部 canonical 形态
    ("VERDICT: FAIL", "workbuddy", "FAIL", True, "FAIL"),
    ("Verdict: PASS", "workbuddy", "PASS", False, "PASS"),
    ("Result: FAILED", "workbuddy", "FAIL", True, "FAILED"),
    ("Result: SUCCESS", "workbuddy", "PASS", False, "SUCCESS"),
    ("结论：REQUEST_CHANGE", "workbuddy", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    ("审查结论：APPROVE", "workbuddy", "PASS", False, "APPROVE"),
    ("VALIDATOR VERDICT: PASS_WITH_WARNING", "workbuddy", "PASS_WITH_WARNING", False,
     "PASS_WITH_WARNING"),
    ("Codex Verdict: REQUEST_CHANGE", "codex", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    # Markdown 包裹
    ("## VERDICT: **FAIL**", "workbuddy", "FAIL", True, "FAIL"),
    ("# Result: **SUCCESS**", "codex", "APPROVE", False, "SUCCESS"),
    ("## VALIDATOR REPORT\n**Result: PASS_WITH_WARNING**\nW1: x",
     "workbuddy", "PASS_WITH_WARNING", False, "PASS_WITH_WARNING"),
    # 行内整体标签
    ("implemented and verified. Overall result: SUCCESS.", "workbuddy", "PASS", False, "SUCCESS"),
    ("review complete. Final verdict: APPROVE", "codex", "APPROVE", False, "APPROVE"),
    # 裸 token 整行 / 行首前缀（legacy 兼容形态）
    ("PASS", "workbuddy", "PASS", False, "PASS"),
    ("APPROVE", "codex", "APPROVE", False, "APPROVE"),
    ("REQUEST_CHANGE: fix router", "codex", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    ("FAILED: implementation incomplete", "workbuddy", "FAIL", True, "FAILED"),
])
def test_canonical_verdict_parsing(narrative, agent, expected_verdict, expected_blocked,
                                   expected_token):
    c = parse_canonical_verdict(narrative)
    assert c is not None and c.token == expected_token, narrative
    assert canonical_blocking(narrative) is expected_blocked, narrative
    assert _derive_verdict(agent, narrative) == expected_verdict, narrative
    assert verdict_blocked(agent, narrative) is expected_blocked, narrative
    status = runner_mod._aggregate_status([agent], {agent: narrative})
    assert status == ("WAITING" if expected_blocked else "SUCCESS"), narrative


# ============ Requirement 2：正文 token 无 verdict authority ============

BODY_TOKENS_NO_AUTHORITY = [
    "PASS 证据\n实现已完成",
    "## PASS 证据\n实现已完成",
    "SUCCESS path implemented",
    "previous result was PASS",
    "test FAILED example",
    "failure handling is covered",
    "REQUEST_CHANGE example shown",
    "> previous verdict: PASS",          # quoted 历史
    "> VERDICT: FAIL",                   # quoted 历史 reviewer output（blockquote 排除）
    "the previously FAILED test now passes",
    '```json\n{"verdict": "PASS"}\n```',  # code block / JSON example
    "fixed the error path",
    "All checks passed. SUCCESS.",        # 无标签句中 token
]


@pytest.mark.parametrize("narrative", BODY_TOKENS_NO_AUTHORITY)
def test_body_tokens_have_no_verdict_authority(narrative):
    # 正文 token 只是内容，不是结论（Requirement 2）——不产生 canonical verdict
    assert parse_canonical_verdict(narrative) is None, narrative
    assert canonical_blocking(narrative) is None, narrative


# ============ Requirement 12：Adversarial Matrix A–L ============

@pytest.mark.parametrize("narrative,agent,expected_verdict,expected_blocked", [
    # A: VERDICT: FAIL + body "PASS evidence" → FAIL / blocking
    ("VERDICT: FAIL\nPASS evidence", "workbuddy", "FAIL", True),
    # B: VERDICT: FAILED + body "SUCCESS example" → FAIL / blocking
    ("VERDICT: FAILED\nSUCCESS example", "workbuddy", "FAIL", True),
    # C: VERDICT: REQUEST_CHANGE + body "APPROVE example" → blocking
    ("VERDICT: REQUEST_CHANGE\nAPPROVE example", "codex", "REQUEST_CHANGE", True),
    # D: RESULT: SUCCESS + body discusses FAILED/error/failure → success/non-blocking
    ("RESULT: SUCCESS\nthe FAILED path and error handling were tested in unit tests",
     "workbuddy", "PASS", False),
    # E: PASS_WITH_WARNING explicit + body contains FAIL examples → non-blocking（无真阻断）
    ("Result: PASS_WITH_WARNING\nFAIL examples were historical; no real blocker",
     "workbuddy", "PASS_WITH_WARNING", False),
    # F: Markdown ## VERDICT: **FAIL** → FAIL
    ("## VERDICT: **FAIL**", "workbuddy", "FAIL", True),
    # G: quoted previous "previous verdict: PASS" + 当前 explicit VERDICT: FAIL → FAIL
    ("previous verdict: PASS\nVERDICT: FAIL", "workbuddy", "FAIL", True),
    # H: code block {"verdict":"PASS"} + 当前 explicit VERDICT: FAIL → FAIL
    ('```json\n{"verdict": "PASS"}\n```\nVERDICT: FAIL', "workbuddy", "FAIL", True),
    # L: CLOSURE-003 shape：## VERDICT: **FAIL** + 正文 ## PASS 证据 → parsed FAIL
    ("## VERDICT: **FAIL**\n\n## PASS 证据\n实现未完成，存在阻断问题",
     "workbuddy", "FAIL", True),
])
def test_adversarial_matrix_explicit_conclusion_precedence(narrative, agent, expected_verdict,
                                                           expected_blocked):
    # Requirement 3：explicit canonical verdict line 是 legacy narrative authority——
    # 后文/正文无论多少 PASS/SUCCESS/APPROVE 都不得覆盖
    assert _derive_verdict(agent, narrative) == expected_verdict, narrative
    assert verdict_blocked(agent, narrative) is expected_blocked, narrative
    assert canonical_blocking(narrative) is expected_blocked, narrative
    status = runner_mod._aggregate_status([agent], {agent: narrative})
    assert status == ("WAITING" if expected_blocked else "SUCCESS"), narrative
    # REPORT 聚合（无 JSON legacy 路径）：blocking → Current Status NOT SUCCESS
    report = build_report(task="T", route=[agent], results={agent: narrative},
                          status="WAITING" if expected_blocked else "SUCCESS")
    assert "## Current Status\n" in report


def test_i_ambiguous_narrative_no_explicit_line_fail_safe():
    # Requirement 7 / 12-I：无 explicit verdict line，正文含 PASS 和 FAIL 词
    # → UNKNOWN/fail-safe，不得凭 token 猜 SUCCESS（required agent 不 fail-open）
    narrative = ("PASS evidence and FAIL examples are both mentioned in the body; "
                 "no overall conclusion line given.")
    assert parse_canonical_verdict(narrative) is None
    assert canonical_blocking(narrative) is None
    assert _derive_verdict("workbuddy", narrative) is None
    assert verdict_blocked("workbuddy", narrative) is True
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": narrative}) == "WAITING"
    # hermes（无 verdict 语义）：正文技术描述不阻断（FIX-001 保持）
    assert verdict_blocked("hermes", narrative) is False


def test_j_structured_pass_conflicts_canonical_narrative_fail(tmp_path):
    # Requirement 12-J / 4：structured PASS 与 canonical narrative FAIL 明确冲突
    # → CONSISTENCY_VIOLATION + blocking=true（fail closed）
    body = ("VERDICT: FAIL\nB1 broken\n" + _tail("workbuddy", "PASS", False))
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["summary_complete"] is False
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE
    out = tmp_path / "out"
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked("workbuddy", body, out) is True
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": body}, out) == "WAITING"


def test_k_structured_approve_canonical_approve_consistent(tmp_path):
    # Requirement 12-K：structured APPROVE + canonical APPROVE → 一致（COMPLETE 非阻断）
    body = ("Codex Verdict: APPROVE\nBlocking Issues: NONE\n"
            + _tail("codex", "APPROVE", False))
    data, status = extract_and_validate_structured("codex", body)
    stage = build_stage_result(agent="codex", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "COMPLETE"
    assert stage["summary_complete"] is True
    assert stage["verdict"] == "APPROVE"
    assert stage["blocking_rework"] is False


def test_closure003_shape_full_runner_waiting(tmp_path, monkeypatch):
    # CLOSURE-003 真实 incident 形状端到端：WorkBuddy canonical FAIL + 正文
    # "## PASS 证据"；Codex REQUEST_CHANGE → REPORT Current Status 必须 NOT SUCCESS
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("## VERDICT: **FAIL**\n\n## PASS 证据\n实现未完成\n"
                      + _tail("workbuddy", "FAIL", True)),
        "codex": ("## Codex Verdict: REQUEST_CHANGE\n需要返工\n"
                  + _tail("codex", "REQUEST_CHANGE", True)),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    assert "## Current Status\nSUCCESS" not in report
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True


def test_closure003_shape_structured_pass_still_fail_closed(tmp_path, monkeypatch):
    # 更严苛：WorkBuddy structured 块错误声称 PASS/blocking=false（旧 fail-open 的
    # JSON 形状）+ narrative canonical FAIL → CONSISTENCY_VIOLATION + WAITING
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("## VERDICT: **FAIL**\n\n## PASS 证据\n实现未完成\n"
                      + _tail("workbuddy", "PASS", False)),
        "codex": "## Codex Verdict: APPROVE\nBlocking Issues: NONE\n" + _tail("codex", "APPROVE", False),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    assert "## Current Status\nSUCCESS" not in report
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "FAIL"
    assert stage["blocking_rework"] is True


# ============ Requirement 11：Final REPORT Aggregation 回归 ============

def test_report_regression_narrative_fail_and_codex_request_change_not_success(tmp_path, monkeypatch):
    # WorkBuddy canonical narrative VERDICT: FAIL + 正文 PASS evidence / SUCCESS example；
    # Codex REQUEST_CHANGE → REPORT Current Status 必须 NOT SUCCESS
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("VERDICT: FAIL\nPASS evidence\nSUCCESS example\n"
                      + _tail("workbuddy", "FAIL", True)),
        "codex": ("REQUEST_CHANGE: need rework\n" + _tail("codex", "REQUEST_CHANGE", True)),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    assert "## Current Status\nSUCCESS" not in report


def test_report_regression_pass_with_warning_approve_success(tmp_path, monkeypatch):
    # WorkBuddy PASS_WITH_WARNING + Codex APPROVE + no blocking → REPORT Current Status = SUCCESS
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": ("## Result: PASS_WITH_WARNING\nW1: 文档瑕疵\nFAILED 场景为历史引用\n"
                      + _tail("workbuddy", "PASS_WITH_WARNING", False, warnings=["W1: 文档瑕疵"])),
        "codex": ("## Codex Verdict: APPROVE\nBlocking Issues: NONE\n"
                  + _tail("codex", "APPROVE", False)),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    assert "## Unresolved Issues\nNone identified." in report
    assert "W1: 文档瑕疵" in report


def test_report_regression_legacy_narrative_only_no_json():
    # 无 <agent>_result.json（legacy）：纯 narrative canonical 判定
    # FAIL + REQUEST_CHANGE → Current Status NOT SUCCESS
    report = build_report(
        task="T", route=["hermes", "workbuddy", "codex"],
        results={
            "hermes": "implemented ok",
            "workbuddy": "## VERDICT: **FAIL**\nPASS evidence\nSUCCESS example",
            "codex": "## Codex Verdict: REQUEST_CHANGE\n需要返工",
        },
        status="WAITING",
    )
    assert "## Current Status\nWAITING" in report
    unresolved = report.split("## Unresolved Issues")[1]
    assert "workbuddy" in unresolved and "codex" in unresolved


# ============ Requirement 13：context_packet / report 统一 canonical semantic ============

def test_unified_verdict_semantic_context_packet_and_report():
    # 同一 narrative：context_packet._derive_verdict / report.verdict_blocked /
    # verdict_parser.canonical_blocking 必须一致（单一 parser 复用，无规则漂移）
    fail_narrative = "## VERDICT: **FAIL**\nPASS evidence"
    assert _derive_verdict("workbuddy", fail_narrative) == "FAIL"
    assert verdict_blocked("workbuddy", fail_narrative) is True
    assert canonical_blocking(fail_narrative) is True

    pass_narrative = "## Result: SUCCESS\nFAILED 场景为历史引用"
    assert _derive_verdict("workbuddy", pass_narrative) == "PASS"
    assert verdict_blocked("workbuddy", pass_narrative) is False
    assert canonical_blocking(pass_narrative) is False

    codex_narrative = "## Codex Verdict: REQUEST_CHANGE\nAPPROVE example"
    assert _derive_verdict("codex", codex_narrative) == "REQUEST_CHANGE"
    assert verdict_blocked("codex", codex_narrative) is True
    assert canonical_blocking(codex_narrative) is True


def test_blocking_invariant_holds_for_canonical_stages(tmp_path):
    # Requirement 8：blocking verdict → blocking_rework=true；non-blocking explicit
    # verdict + 无 hard failure → blocking_rework=false（invariant 保持）
    from ai_agent_framework.context_packet import blocking_invariant_violations
    for narrative, agent, verdict, blocking in [
        ("VERDICT: FAIL\nPASS evidence", "workbuddy", "FAIL", True),
        ("VERDICT: FAILED\nSUCCESS example", "workbuddy", "FAIL", True),
        ("Result: PASS_WITH_WARNING\nFAIL examples", "workbuddy", "PASS_WITH_WARNING", False),
        ("Codex Verdict: APPROVE", "codex", "APPROVE", False),
    ]:
        stage = build_stage_result(agent=agent, result_text=narrative, output_dir=tmp_path)
        assert stage["verdict"] == verdict, narrative
        assert stage["blocking_rework"] is blocking, narrative
        assert blocking_invariant_violations(stage) == [], narrative


# ============ 结构化块剥离语义（FIX-003 保持）：JSON 结论词不是 narrative 证据 ============

def test_structured_tail_json_tokens_are_not_narrative_evidence():
    # narrative 无 canonical 行，结构化块 JSON 含 PASS → 不得派生成通过 verdict
    # （JSON 结论词不是 narrative 证据——FIX-003 / FIX-005 保持）
    body = ("implemented ok, no explicit verdict line\n"
            + STRUCTURED_RESULT_BEGIN + "\n"
            + json.dumps({"verdict": "PASS", "blocking_rework": False,
                          "findings": [], "warnings": []})
            + "\n" + STRUCTURED_RESULT_END)
    assert _derive_verdict("workbuddy", body) is None
    assert verdict_blocked("workbuddy", body) is True  # ambiguous narrative → fail-safe


def test_structured_tail_fail_json_does_not_override_narrative_success():
    # narrative 明确 canonical SUCCESS + 结构化块 JSON 声称 FAIL → verdict 保持
    # narrative 派生 PASS（guard 检查 JSON 不得把 narrative 通过覆盖为阻断）
    body = ("## Result: SUCCESS\nverified\n"
            + STRUCTURED_RESULT_BEGIN + "\n"
            + json.dumps({"verdict": "FAIL", "blocking_rework": True,
                          "findings": [], "warnings": []})
            + "\n" + STRUCTURED_RESULT_END)
    assert _derive_verdict("workbuddy", body) == "PASS"
    # build_stage_result：narrative PASS vs structured FAIL → CONSISTENCY_VIOLATION，
    # verdict 恢复 narrative-derived PASS（FIX-004 保持：非 blocking 不机械翻转）
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=".",
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "CONSISTENCY_VIOLATION"
    assert stage["verdict"] == "PASS"
    assert stage["blocking_rework"] is True  # structured 声明的 blocking 保持（fail-safe 方向）
