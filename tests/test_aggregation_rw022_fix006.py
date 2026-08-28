"""RW-022 FIX-006 regression tests：Line-Level Verdict Authority（TASK-007-FIX-006）。

核心缺陷（FIX-006，CLOSURE-004 真实 incident）：
- WorkBuddy narrative 首行 ``## VALIDATOR VERDICT: **PASS_WITH_WARNING**`` 是唯一
  真实结论（blocking rework=NO），但正文第 3 节示例枚举中包含
  ``最终判定：**REQUEST_CHANGE**`` 与 ``Overall result: SUCCESS.`` 等 inline
  example——FIX-005 遗留的行内整体标签正则（_INLINE_RE）在句中匹配它们为
  canonical，blocking-match precedence 误选 REQUEST_CHANGE → fresh
  workbuddy_result.json 错误记录 verdict=REQUEST_CHANGE / blocking_rework=true。

FIX-006 收敛（Requirement 1）：verdict authority 只属于**独立、明确、
line-level 的 overall verdict / result / conclusion 声明行**；正文句子中的
verdict-like label 只是内容不是结论（Requirement 2）；code / inline code /
JSON / blockquote / 普通 section heading 均无权威（Requirement 3–5）；真实
canonical conclusion 不被后文 token 改变（Requirement 6）；无独立结论行 →
fail-safe 不 fail-open（Requirement 8）。context_packet / report / consistency
guard 继续共用 verdict_parser 统一语义（Requirement 9）；blocking invariant
保持（Requirement 10）。

覆盖：
- Requirement 1 line-level 权威形态全集（含整体标签行首形态）
- Requirement 2–5 无权威形态（prose / code / JSON / quote / heading）
- Requirement 6/11 CLOSURE-004 exact-shape 回归（真实 incident 同形）
- Requirement 12 CLOSURE-003 回归
- Requirement 13 Adversarial Matrix A–I
- Requirement 14 Framework aggregation 回归
- Requirement 15 既有保护抽查（fail-closed / invariant / aggregation）
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
T-RW022-FIX006

# Task Name
Line-Level Verdict Authority 测试

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


# ============ Requirement 1：Line-Level Authority 形态全集 ============

@pytest.mark.parametrize("narrative,agent,expected_verdict,expected_blocked,expected_token", [
    # 任务列出的典型 line-level 形态
    ("VERDICT: FAIL", "workbuddy", "FAIL", True, "FAIL"),
    ("Verdict: PASS", "workbuddy", "PASS", False, "PASS"),
    ("Result: FAILED", "workbuddy", "FAIL", True, "FAILED"),
    ("Result: SUCCESS", "workbuddy", "PASS", False, "SUCCESS"),
    ("结论：REQUEST_CHANGE", "workbuddy", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    ("审查结论：APPROVE", "workbuddy", "PASS", False, "APPROVE"),
    ("VALIDATOR VERDICT: PASS_WITH_WARNING", "workbuddy", "PASS_WITH_WARNING", False,
     "PASS_WITH_WARNING"),
    ("Codex Verdict: REQUEST_CHANGE", "codex", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    ("总体结果：SUCCESS", "workbuddy", "PASS", False, "SUCCESS"),
    ("最终判定：APPROVE", "codex", "APPROVE", False, "APPROVE"),
    # Markdown line wrapper
    ("## VERDICT: **FAIL**", "workbuddy", "FAIL", True, "FAIL"),
    ("# Result: **SUCCESS**", "codex", "APPROVE", False, "SUCCESS"),
    ("**Verdict: PASS**", "workbuddy", "PASS", False, "PASS"),
    ("## Codex Verdict: REQUEST_CHANGE", "codex", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    ("## Result: SUCCESS", "workbuddy", "PASS", False, "SUCCESS"),
    ("### 结论：PASS", "workbuddy", "PASS", False, "PASS"),
    # 整行整体标签（label 位于逻辑行首——FIX-006：句中形态无 authority）
    ("Overall result: SUCCESS.", "workbuddy", "PASS", False, "SUCCESS"),
    ("Final verdict: APPROVE", "codex", "APPROVE", False, "APPROVE"),
    ("Final conclusion: APPROVE", "codex", "APPROVE", False, "APPROVE"),
    # 裸 token 整行（legacy 兼容形态）
    ("PASS", "workbuddy", "PASS", False, "PASS"),
    ("APPROVE", "codex", "APPROVE", False, "APPROVE"),
    ("REQUEST_CHANGE: fix router", "codex", "REQUEST_CHANGE", True, "REQUEST_CHANGE"),
    ("FAILED: implementation incomplete", "workbuddy", "FAIL", True, "FAILED"),
])
def test_line_level_verdict_parsing(narrative, agent, expected_verdict, expected_blocked,
                                    expected_token):
    c = parse_canonical_verdict(narrative)
    assert c is not None and c.token == expected_token, narrative
    assert canonical_blocking(narrative) is expected_blocked, narrative
    assert _derive_verdict(agent, narrative) == expected_verdict, narrative
    assert verdict_blocked(agent, narrative) is expected_blocked, narrative
    status = runner_mod._aggregate_status([agent], {agent: narrative})
    assert status == ("WAITING" if expected_blocked else "SUCCESS"), narrative


# ============ Requirement 2：正文句子中的 verdict-like label 无权威 ============
# （FIX-006：句中 "Overall result: SUCCESS." / "Final verdict: APPROVE" 不再权威）

PROSE_NO_AUTHORITY = [
    "PASS 证据\n实现已完成",
    "## PASS evidence",
    "## REQUEST_CHANGE example",
    "## SUCCESS path",
    "## FAILED test cases",
    "SUCCESS path implemented",
    "previous result was PASS",
    "previous verdict: PASS.",
    "test FAILED example",
    "This case should produce REQUEST_CHANGE.",
    "expected result is SUCCESS.",
    "implemented and verified. Overall result: SUCCESS.",   # 句中整体标签（核心）
    "review complete. Final verdict: APPROVE",              # 句中整体标签（核心）
    "the previously FAILED test now passes",
    "All checks passed. SUCCESS.",
    "structured PASS conflicts with narrative FAIL.",
    "前一轮 verdict: PASS。",
]


@pytest.mark.parametrize("narrative", PROSE_NO_AUTHORITY)
def test_prose_tokens_have_no_line_level_authority(narrative):
    # 正文 token / 句中 label 只是内容，不是结论（Requirement 2）——不产生 canonical verdict
    assert parse_canonical_verdict(narrative) is None, narrative
    assert canonical_blocking(narrative) is None, narrative


# ============ Requirement 3：code / inline code / JSON 无权威 ============

CODE_NO_AUTHORITY = [
    "`REQUEST_CHANGE`",                       # inline code 整行
    "`Verdict: PASS`",
    "This case should produce `REQUEST_CHANGE`.",
    "例如：structured `PASS` conflicts with narrative FAIL.",
    '```json\n{"verdict": "PASS"}\n```',      # code fence / JSON example
    '```\nVerdict: FAIL\n```',
    '{"verdict": "PASS"}',                    # 无 code 包裹的 JSON example
    '"result": "SUCCESS"',
]


@pytest.mark.parametrize("narrative", CODE_NO_AUTHORITY)
def test_code_and_json_have_no_authority(narrative):
    assert parse_canonical_verdict(narrative) is None, narrative
    assert canonical_blocking(narrative) is None, narrative


@pytest.mark.parametrize("narrative,expected_token", [
    # fence / inline code 内容无权威；当前独立 conclusion 行才是 authority
    ("```\nVerdict: FAIL\n```\nVerdict: PASS", "PASS"),
    ("`REQUEST_CHANGE`\nVerdict: PASS", "PASS"),
    ('```json\n{"verdict": "REQUEST_CHANGE"}\n```\nCodex Verdict: APPROVE', "APPROVE"),
    ("Codex Verdict: APPROVE\n`REQUEST_CHANGE` example in body", "APPROVE"),
])
def test_code_excluded_but_current_conclusion_line_is_authority(narrative, expected_token):
    c = parse_canonical_verdict(narrative)
    assert c is not None and c.token == expected_token, narrative


# ============ Requirement 4：blockquote / 历史引用 无当前权威 ============

@pytest.mark.parametrize("narrative,expected_token", [
    ("> Verdict: PASS\nVerdict: FAIL", "FAIL"),          # quote 历史 → 当前 FAIL authority
    ("> Result: SUCCESS\nResult: FAILED", "FAILED"),
    ("> Codex Verdict: APPROVE\nCodex Verdict: REQUEST_CHANGE", "REQUEST_CHANGE"),
    ("> previous reviewer: Verdict: PASS\nVerdict: FAIL", "FAIL"),
])
def test_blockquote_has_no_current_authority(narrative, expected_token):
    c = parse_canonical_verdict(narrative)
    assert c is not None and c.token == expected_token, narrative


def test_blockquote_only_no_verdict():
    # 只有引用行 → 无当前结论 → None（不得把历史引用当当前 verdict）
    assert parse_canonical_verdict("> Verdict: PASS") is None
    assert parse_canonical_verdict("> Result: SUCCESS") is None
    assert canonical_blocking("> Verdict: PASS") is None


# ============ Requirement 5：普通 section heading 无权威；带 label 的 heading 有权威 ============

@pytest.mark.parametrize("heading", [
    "## PASS evidence",
    "## REQUEST_CHANGE example",
    "## SUCCESS path",
    "## FAILED test cases",
    "### FAIL 证据",
    "## SUCCESS 路径",
])
def test_plain_headings_are_not_verdict_lines(heading):
    assert parse_canonical_verdict(heading) is None, heading


@pytest.mark.parametrize("heading,expected_token", [
    ("## VERDICT: FAIL", "FAIL"),
    ("## Result: SUCCESS", "SUCCESS"),
    ("## Codex Verdict: REQUEST_CHANGE", "REQUEST_CHANGE"),
    ("### 结论：PASS", "PASS"),
])
def test_labeled_headings_are_verdict_lines(heading, expected_token):
    c = parse_canonical_verdict(heading)
    assert c is not None and c.token == expected_token, heading


# ============ Requirement 6：Current Conclusion Precedence ============

def test_current_canonical_conclusion_not_overridden_by_body_tokens():
    # 可信 current canonical conclusion（PASS_WITH_WARNING）存在 → 后续正文任意
    # PASS / FAIL / FAILED / SUCCESS / REQUEST_CHANGE / APPROVE token 均不得改变
    narrative = (
        "## VALIDATOR VERDICT: **PASS_WITH_WARNING**\n"
        "正文讨论了 PASS、FAIL、FAILED、SUCCESS、REQUEST_CHANGE、APPROVE 等历史场景；"
        "expected result is SUCCESS；previous verdict: PASS."
    )
    c = parse_canonical_verdict(narrative)
    assert c is not None and c.token == "PASS_WITH_WARNING", narrative
    assert canonical_blocking(narrative) is False
    assert _derive_verdict("workbuddy", narrative) == "PASS_WITH_WARNING"
    assert verdict_blocked("workbuddy", narrative) is False
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": narrative}) == "SUCCESS"


# ============ Requirement 7 / 13-I：多个独立 canonical conclusion 行 → fail-safe ============

@pytest.mark.parametrize("narrative", [
    "Verdict: PASS\nsome body\nVerdict: FAIL",
    "Verdict: FAIL\nsome body\nVerdict: PASS",
    "## Result: SUCCESS\nbody\n## VERDICT: **FAILED**",
])
def test_multiple_genuine_conclusion_lines_fail_safe_blocking(narrative):
    # 两条都是显式 conclusion 行（都有匹配证据）→ blocking conclusion 优先（fail-safe）；
    # 不得取通过方而 fail-open
    c = parse_canonical_verdict(narrative)
    assert c is not None, narrative
    assert canonical_blocking(narrative) is True, narrative
    assert verdict_blocked("workbuddy", narrative) is True


# ============ Requirement 8 / 13-H：Ambiguous narrative 不 fail-open ============

def test_ambiguous_narrative_fail_safe():
    # 无独立 conclusion 行 + 正文含多个 verdict token → 不得从 prose / example /
    # inline token 猜 verdict（不得 fail-open SUCCESS）
    narrative = ("PASS evidence and FAIL examples are both mentioned in the body; "
                 "SUCCESS path also discussed. No overall conclusion line given.")
    assert parse_canonical_verdict(narrative) is None
    assert canonical_blocking(narrative) is None
    assert _derive_verdict("workbuddy", narrative) is None
    assert verdict_blocked("workbuddy", narrative) is True   # required agent fail-safe
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": narrative}) == "WAITING"
    # hermes（无 verdict 语义）：正文技术描述不阻断（FIX-001 保持）
    assert verdict_blocked("hermes", narrative) is False


# ============ Requirement 11：CLOSURE-004 Exact Shape 回归 ============
# 与 2026-08-28 CLOSURE-004 真实 WorkBuddy narrative 同形：首行
# ## VALIDATOR VERDICT: **PASS_WITH_WARNING**，后文含说明性 `REQUEST_CHANGE` /
# `SUCCESS` / `PASS_WITH_WARNING` inline code 与 adversarial table/prose。

CLOSURE004_WORKBUDDY_SHAPE = """## VALIDATOR VERDICT: **PASS_WITH_WARNING**

Independent re-verification against actual workspace state (no files modified — only read + in-process probes; two temp dirs under `.aaf/` were created and removed during probing).

### 1. Fresh runner (Req 1)
- `git rev-parse HEAD` = `bcae4279da8a8f4d1597e58c996c5652aaa67924` = target commit. ✓

### 3. Canonical verdict probes (Req 4–6, in-process, not by function name)
| Case | Result | Expected | ✓ |
|---|---|---|---|
| A `## VERDICT: **FAIL**` + body `## PASS 证据` / `SUCCESS example` | blocked=True, verdict_ok=False | FAIL / blocking | ✓ |
| B `Result: FAILED` + body PASS/APPROVE/SUCCESS | blocked=True | blocking | ✓ |
| C `Verdict: REQUEST_CHANGE` + `APPROVE example` | blocked=True | blocking | ✓ |
| D `Result: SUCCESS` + FAILED/failure/error discussion | blocked=False, ok=True | non-blocking | ✓ |

13 extra adversarial forms verified: `**Verdict: PASS**`, `## Verdict: **PASS_WITH_WARNING**`, `## 审查结论：APPROVE`, `结论：**REQUEST_CHANGE**`, `最终判定：**REQUEST_CHANGE**`, `最终结论：
**APPROVE**`, `**结论：FAIL —— …**`, `VALIDATOR VERDICT:`, `Codex Verdict:`, `Overall result: SUCCESS.`, both canonical-conflict orders (FAIL-then-PASS and PASS-then-FAIL → blocking token wins, fail-safe). All real historical artifact forms parse correctly.

### WorkBuddy blocking_rework
**NO**

```
VERDICT: PASS_WITH_WARNING
blocking_rework: false
blocking_provenance: narrative
```
"""


def test_closure004_exact_shape_verdict_is_pass_with_warning():
    # 真实 incident 同形：inline examples（`REQUEST_CHANGE` / `SUCCESS` /
    # `PASS_WITH_WARNING` / table prose）不得覆盖首行 canonical conclusion
    c = parse_canonical_verdict(CLOSURE004_WORKBUDDY_SHAPE)
    assert c is not None and c.token == "PASS_WITH_WARNING"
    assert c.kind == "line"
    assert canonical_blocking(CLOSURE004_WORKBUDDY_SHAPE) is False
    assert _derive_verdict("workbuddy", CLOSURE004_WORKBUDDY_SHAPE) == "PASS_WITH_WARNING"
    assert verdict_blocked("workbuddy", CLOSURE004_WORKBUDDY_SHAPE) is False
    assert runner_mod._aggregate_status(
        ["workbuddy"], {"workbuddy": CLOSURE004_WORKBUDDY_SHAPE}) == "SUCCESS"


def test_closure004_shape_full_runner_pass_with_warning(tmp_path, monkeypatch):
    # 端到端：WorkBuddy PASS_WITH_WARNING（adversarial body）+ Codex APPROVE
    # + no hard failure → REPORT Current Status = SUCCESS；workbuddy_result.json
    # verdict=PASS_WITH_WARNING / blocking_rework=false（真实 incident 修复后形状）
    out = _run_chain(tmp_path, monkeypatch, {
        "hermes": "implemented ok\n" + _tail("hermes", None, False),
        "workbuddy": (CLOSURE004_WORKBUDDY_SHAPE + "\n"
                      + _tail("workbuddy", "PASS_WITH_WARNING", False,
                              warnings=["W1: 文档瑕疵"])),
        "codex": ("## Codex Verdict: APPROVE\nBlocking Issues: NONE\n"
                  + _tail("codex", "APPROVE", False)),
    })
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "## Current Status\nSUCCESS" in report
    assert "## Current Status\nWAITING" not in report
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage["verdict"] == "PASS_WITH_WARNING"
    assert stage["blocking_rework"] is False
    assert stage["blocking_provenance"] == BLOCKING_PROVENANCE_NARRATIVE


# ============ Requirement 12：CLOSURE-003 回归 ============

def test_closure003_shape_verdict_is_fail():
    # CLOSURE-003 真实 incident 形状：## VERDICT: **FAIL** + 正文 ## PASS 证据 /
    # SUCCESS example → FAIL / blocking（正文示例不得覆盖真实 FAIL）
    narrative = ("## VERDICT: **FAIL**\n\n## PASS 证据\n实现未完成，存在阻断问题\n"
                 "SUCCESS example 仅为历史引用")
    c = parse_canonical_verdict(narrative)
    assert c is not None and c.token == "FAIL"
    assert canonical_blocking(narrative) is True
    assert _derive_verdict("workbuddy", narrative) == "FAIL"
    assert verdict_blocked("workbuddy", narrative) is True
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": narrative}) == "WAITING"


def test_closure003_shape_full_runner_waiting(tmp_path, monkeypatch):
    # WorkBuddy canonical FAIL + 正文 PASS 证据；Codex REQUEST_CHANGE
    # → REPORT Current Status NOT SUCCESS
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


# ============ Requirement 13：Adversarial Matrix A–I ============

@pytest.mark.parametrize("narrative,agent,expected_verdict,expected_blocked", [
    # A. Verdict: PASS + body inline `REQUEST_CHANGE` → PASS
    ("Verdict: PASS\nThis case should produce `REQUEST_CHANGE`.", "workbuddy", "PASS", False),
    # B. Verdict: FAIL + body inline `SUCCESS` → FAIL
    ("Verdict: FAIL\nbody contains `SUCCESS` example", "workbuddy", "FAIL", True),
    # C. Result: SUCCESS + body "expected Result: FAILED example" → SUCCESS
    ("Result: SUCCESS\nexpected Result: FAILED example in test description",
     "workbuddy", "PASS", False),
    # D. Codex Verdict: APPROVE + body `REQUEST_CHANGE` → APPROVE
    ("Codex Verdict: APPROVE\nhistorical `REQUEST_CHANGE` items all closed",
     "codex", "APPROVE", False),
    # E. blockquote > Verdict: FAIL + current Verdict: PASS → PASS
    ("> Verdict: FAIL\nVerdict: PASS", "workbuddy", "PASS", False),
    # F. code fence contains Verdict: FAIL + current PASS → PASS
    ("```\nVerdict: FAIL\n```\nVerdict: PASS", "workbuddy", "PASS", False),
    # G. JSON contains verdict REQUEST_CHANGE + current APPROVE → APPROVE
    ('```json\n{"verdict": "REQUEST_CHANGE"}\n```\nVerdict: APPROVE',
     "codex", "APPROVE", False),
    # I. two genuine canonical contradictory conclusion lines → fail-safe blocking
    ("Verdict: PASS\nsome body\nVerdict: FAIL", "workbuddy", "FAIL", True),
    ("Verdict: FAIL\nsome body\nVerdict: PASS", "workbuddy", "FAIL", True),
])
def test_adversarial_matrix_line_level(narrative, agent, expected_verdict, expected_blocked):
    assert _derive_verdict(agent, narrative) == expected_verdict, narrative
    assert verdict_blocked(agent, narrative) is expected_blocked, narrative
    status = runner_mod._aggregate_status([agent], {agent: narrative})
    assert status == ("WAITING" if expected_blocked else "SUCCESS"), narrative


def test_adversarial_h_ambiguous_no_fail_open():
    # H. no canonical conclusion + body 含多个 verdict token → UNKNOWN/fail-safe
    narrative = ("PASS evidence and FAIL examples and SUCCESS path all mentioned; "
                 "no overall conclusion line.")
    assert parse_canonical_verdict(narrative) is None
    assert canonical_blocking(narrative) is None
    assert verdict_blocked("workbuddy", narrative) is True      # 不得 fail-open
    assert runner_mod._aggregate_status(["workbuddy"], {"workbuddy": narrative}) == "WAITING"


# ============ Requirement 14：Framework Aggregation 回归 ============

def test_aggregation_pass_with_warning_with_adversarial_body_success():
    # WorkBuddy: PASS_WITH_WARNING + body 含 adversarial verdict examples；
    # Codex: APPROVE；无 framework hard failure → Current Status = SUCCESS
    results = {
        "workbuddy": ("## VALIDATOR VERDICT: **PASS_WITH_WARNING**\n"
                      "body includes `REQUEST_CHANGE`, `SUCCESS`, `PASS_WITH_WARNING` examples\n"
                      "| A `## VERDICT: **FAIL**` | blocked=True | ✓ |"),
        "codex": "## Codex Verdict: APPROVE\nBlocking Issues: NONE",
    }
    assert runner_mod._aggregate_status(["workbuddy", "codex"], results) == "SUCCESS"
    report = build_report(task="T", route=["workbuddy", "codex"], results=results,
                          status="SUCCESS")
    assert "## Current Status\nSUCCESS" in report


def test_aggregation_fail_with_pass_examples_not_success():
    # WorkBuddy: VERDICT: FAIL + body 含 PASS examples；Codex: REQUEST_CHANGE
    # → Current Status != SUCCESS
    results = {
        "workbuddy": "VERDICT: FAIL\nbody includes PASS examples and SUCCESS path",
        "codex": "Codex Verdict: REQUEST_CHANGE\nneeds rework",
    }
    assert runner_mod._aggregate_status(["workbuddy", "codex"], results) == "WAITING"
    report = build_report(task="T", route=["workbuddy", "codex"], results=results,
                          status="WAITING")
    assert "## Current Status\nWAITING" in report
    assert "## Current Status\nSUCCESS" not in report


# ============ Requirement 9：Shared Parser Semantics ============

def test_unified_line_level_semantic_context_packet_and_report():
    # 同一 narrative：context_packet._derive_verdict / report.verdict_blocked /
    # verdict_parser.canonical_blocking 必须一致（单一 parser 复用，无规则漂移）
    c4 = CLOSURE004_WORKBUDDY_SHAPE
    assert parse_canonical_verdict(c4).token == "PASS_WITH_WARNING"
    assert canonical_blocking(c4) is False
    assert _derive_verdict("workbuddy", c4) == "PASS_WITH_WARNING"
    assert verdict_blocked("workbuddy", c4) is False

    fail_narrative = "## VERDICT: **FAIL**\n## PASS 证据"
    assert parse_canonical_verdict(fail_narrative).token == "FAIL"
    assert canonical_blocking(fail_narrative) is True
    assert _derive_verdict("workbuddy", fail_narrative) == "FAIL"
    assert verdict_blocked("workbuddy", fail_narrative) is True

    codex_narrative = "## Codex Verdict: REQUEST_CHANGE\n`APPROVE example` in body"
    assert parse_canonical_verdict(codex_narrative).token == "REQUEST_CHANGE"
    assert canonical_blocking(codex_narrative) is True
    assert _derive_verdict("codex", codex_narrative) == "REQUEST_CHANGE"
    assert verdict_blocked("codex", codex_narrative) is True


# ============ Requirement 10 / 15：Blocking Invariant + 既有保护 ============

def test_blocking_invariant_holds_for_line_level_stages(tmp_path):
    for narrative, agent, verdict, blocking in [
        ("VERDICT: FAIL\nbody `PASS` example", "workbuddy", "FAIL", True),
        ("## VERDICT: **FAILED**\nSUCCESS example", "workbuddy", "FAIL", True),
        ("Result: PASS_WITH_WARNING\n`FAIL` historical", "workbuddy", "PASS_WITH_WARNING", False),
        ("## Codex Verdict: APPROVE\n> Verdict: FAIL", "codex", "APPROVE", False),
        (CLOSURE004_WORKBUDDY_SHAPE, "workbuddy", "PASS_WITH_WARNING", False),
    ]:
        stage = build_stage_result(agent=agent, result_text=narrative, output_dir=tmp_path)
        assert stage["verdict"] == verdict, narrative
        assert stage["blocking_rework"] is blocking, narrative
        assert blocking_invariant_violations(stage) == [], narrative


def test_framework_error_and_empty_fail_closed_preserved(tmp_path):
    # Requirement 15：framework hard failure precedence / missing result fail-closed
    stage = build_stage_result(
        agent="workbuddy", result_text="FRAMEWORK_ERROR\nRuntimeError: boom", output_dir=tmp_path,
        structured={"verdict": "PASS", "blocking_rework": False,
                    "findings": [], "warnings": []},
        structured_status="OK",
    )
    assert stage["status"] == "FAILED"
    assert stage["blocking_rework"] is True
    assert stage["blocking_provenance"] == "framework"   # framework hard failure provenance
    assert blocking_invariant_violations(stage) == []
    empty = build_stage_result(agent="workbuddy", result_text="", output_dir=tmp_path)
    assert empty["status"] == "FAILED"
    assert empty["blocking_rework"] is True
    assert blocking_invariant_violations(empty) == []


def test_consistency_violation_fail_closed_preserved(tmp_path):
    # Requirement 15：structured PASS 与 canonical narrative FAIL 明确冲突
    # → CONSISTENCY_VIOLATION + blocking=true（fail closed 保持）
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


def test_success_with_warning_semantics_preserved(tmp_path):
    # Requirement 15：narrative line-level SUCCESS + W1 标记 + structured
    # PASS/warnings → COMPLETE 非阻断（SUCCESS-with-warning 语义保持）
    body = ("Overall result: SUCCESS\nW1: 文档瑕疵\n"
            + _tail("workbuddy", "PASS", False, warnings=["W1: 文档瑕疵"]))
    data, status = extract_and_validate_structured("workbuddy", body)
    stage = build_stage_result(agent="workbuddy", result_text=body, output_dir=tmp_path,
                               structured=data, structured_status=status)
    assert stage["structured_summary_status"] == "COMPLETE"
    assert stage["summary_complete"] is True
    assert stage["verdict"] == "PASS"
    assert stage["blocking_rework"] is False
    assert blocking_invariant_violations(stage) == []
