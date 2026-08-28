"""RW-008：TASK Intake Parser compatibility（Compact TASK + CRLF/BOM/multiline）。

复现场景（生产实证）：
- Planner 生成标准 Compact TASK，Acceptance 为 20 项编号列表，后续还有
  Expected Final Result / Route / Route Hint。
- Bridge intake 弹出「缺少必填字段: Acceptance」，但 Acceptance 实际存在。
- Root cause：bridge/task_io 与 task_validation 的行锚定正则用 `[ \t]*$`，
  CRLF 下 `\r` 卡住匹配 → Acceptance 标题行解析失败 → 字段为空。

本文件验证：
1. 用户形状（Compact、同行值字段、编号 Acceptance、后续 section）可解析；
2. CRLF / 混合行尾 / BOM / whitespace / EOF 边界兼容；
3. missing / empty / duplicate Acceptance 仍然 fail-closed；
4. 两层校验（bridge.task_io UX guard + task_validation 最终边界）行为一致。
"""
import pytest

from bridge.task_io import parse_task, validate_task_text as bridge_validate
from ai_agent_framework.task_validation import (
    parse_task_fields,
    validate_task_text as formal_validate,
)

WS = r"D:\AdyAI\ai-agent-framework"

# 与 Planner 当前 TASK 同形的标准 Compact TASK（同行值字段 + 编号 Acceptance）
COMPACT_TASK = """AAF_TASK_BEGIN
Task ID: AAF-RW008-001
Task Name: RW008 acceptance parse
Workspace: D:/AdyAI/ai-agent-framework

Objective:
Implement the acceptance parsing fix.

Acceptance:
1. alpha
2. beta
3. gamma
4. delta
5. epsilon
6. zeta
7. eta
8. theta
9. iota
10. kappa
11. lambda
12. mu
13. nu
14. xi
15. omicron
16. pi
17. rho
18. sigma
19. tau
20. upsilon

Expected Final Result:
SUCCESS

Route: hermes -> workbuddy -> codex

Route Hint:
hint text here

AAF_TASK_END
"""


def _crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


def _acceptance_ok(fields: dict) -> bool:
    acc = fields.get("acceptance") or fields.get("Acceptance") or ""
    return bool(acc) and acc.strip().startswith("1.")


def _bridge_valid(text: str) -> tuple[bool, list[str]]:
    return bridge_validate(text, WS)


def _formal_valid(text: str):
    return formal_validate(text)


# ---------- 用户复现形状：Compact TASK，Acceptance 区块 CRLF 混合 ----------

def test_compact_task_lf_baseline():
    ok, errors = _bridge_valid(COMPACT_TASK)
    assert ok is True, errors
    assert _formal_valid(COMPACT_TASK).valid is True


def test_compact_task_acceptance_block_crlf_mixed():
    """Acceptance 区块 CRLF（其余 LF）→ 修复前 acceptance 缺失（生产复现）。"""
    lines = COMPACT_TASK.split("\n")
    out, in_acc = [], False
    for ln in lines:
        if ln.startswith("Acceptance:"):
            in_acc = True
        elif ln.startswith("Expected Final Result:"):
            in_acc = False
        out.append(ln + ("\r" if in_acc else ""))
    text = "\n".join(out)
    # Bridge UX guard
    ok, errors = _bridge_valid(text)
    assert ok is True, errors
    # Formal validator（最终边界）
    r = _formal_valid(text)
    assert r.valid is True, r.errors
    fields = parse_task(text)
    assert fields["acceptance"].strip().startswith("1. alpha"), fields["acceptance"]


def test_compact_task_full_crlf():
    text = _crlf(COMPACT_TASK)
    ok, errors = _bridge_valid(text)
    assert ok is True, errors
    assert _formal_valid(text).valid is True


# ---------- BOM / whitespace ----------

def test_utf8_bom_prefix_ok():
    text = "\ufeff" + COMPACT_TASK
    ok, errors = _bridge_valid(text)
    assert ok is True, errors
    assert _formal_valid(text).valid is True


def test_leading_trailing_whitespace_ok():
    text = COMPACT_TASK.replace("Acceptance:\n", "  Acceptance:  \n")
    ok, errors = _bridge_valid(text)
    assert ok is True, errors
    assert _formal_valid(text).valid is True


# ---------- multiline / long list / following sections / EOF ----------

def test_long_numbered_acceptance_with_following_sections():
    """20 项编号 + 后续 Expected Final Result / Route / Route Hint。"""
    ok, errors = _bridge_valid(COMPACT_TASK)
    assert ok is True, errors
    r = _formal_valid(COMPACT_TASK)
    assert r.valid is True, r.errors
    fields = parse_task_fields(COMPACT_TASK)
    assert fields["Acceptance"].count("\n") >= 19


def test_acceptance_at_eof_boundary():
    """Acceptance 是最后一个节（无后续 section）→ EOF 边界不截断。"""
    tail = """Acceptance:
1. alpha
2. beta

AAF_TASK_END
"""
    text = COMPACT_TASK.rsplit("Acceptance:", 1)[0] + tail
    ok, errors = _bridge_valid(text)
    assert ok is True, errors
    assert _formal_valid(text).valid is True


# ---------- fail-closed：missing / empty / duplicate ----------

def test_missing_acceptance_rejected():
    text = COMPACT_TASK.replace("Acceptance:\n", "").replace(
        "1. alpha\n", "").replace("2. beta\n", "").replace("3. gamma\n", "")
    ok, errors = _bridge_valid(text)
    assert ok is False
    assert any("Acceptance" in e for e in errors)
    assert _formal_valid(text).valid is False


def test_empty_acceptance_rejected():
    """Acceptance 标题存在但无内容 → 拒绝（不得误判为存在）。"""
    text = COMPACT_TASK.replace(
        "Acceptance:\n1. alpha\n2. beta\n3. gamma\n4. delta\n5. epsilon\n"
        "6. zeta\n7. eta\n8. theta\n9. iota\n10. kappa\n11. lambda\n12. mu\n"
        "13. nu\n14. xi\n15. omicron\n16. pi\n17. rho\n18. sigma\n19. tau\n20. upsilon\n\n",
        "Acceptance:\n\n",
    )
    ok, errors = _bridge_valid(text)
    assert ok is False
    assert any("Acceptance" in e for e in errors)
    assert _formal_valid(text).valid is False


def test_duplicate_acceptance_fail_closed():
    """两个 Acceptance 节 → fail-closed 拒绝（不得 first/last wins）。"""
    text = COMPACT_TASK.replace(
        "Expected Final Result:",
        "Acceptance:\n99. second acceptance\n\nExpected Final Result:",
    )
    ok, errors = _bridge_valid(text)
    assert ok is False
    assert any("Acceptance" in e and "重复" in e for e in errors)
    r = _formal_valid(text)
    assert r.valid is False
    assert any("Acceptance" in e and "重复" in e for e in r.errors)


# ---------- 两层解析一致性（parse 层直接验证） ----------

def test_parse_task_acceptance_crlf_heading_only():
    """仅 Acceptance 标题行 CRLF（其余 LF）——最小 repro。"""
    lines = COMPACT_TASK.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("Acceptance:"):
            lines[i] = ln + "\r"
    text = "\n".join(lines)
    body = text[text.index("AAF_TASK_BEGIN") + len("AAF_TASK_BEGIN"):]
    body = body[: body.index("AAF_TASK_END")]
    fields = parse_task(body)
    assert fields["acceptance"].strip().startswith("1."), fields["acceptance"]
