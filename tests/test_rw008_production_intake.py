"""RW-008 生产 intake blocker：marker extraction 提前截断（TASK-009 实证）。

Root cause（2026-08-29 生产复现）：
- bridge/task_io.extract_task_body 用 `BEGIN + (.*?) + END`（非贪婪）匹配
  从第一个 AAF_TASK_BEGIN 到**第一个** AAF_TASK_END 子串。
- Planner 标准 TASK 正文（如 TASK-009）在 Requirements 里写了
  "AAF_TASK_BEGIN / AAF_TASK_END authority"（文档性说明）→ 被当作结束标记，
  后面的 Requirements / Acceptance / Route / Route Hint 全部丢弃
  → Bridge 报「缺少必填字段: Acceptance」。
- 61e3a05（CRLF fix）不涉及此路径，故重启后仍复现。

修复：BEGIN/END 标记改为独立行锚定（^...$ MULTILINE），正文中的
"AAF_TASK_END authority" 非独立行，不再误截断。
"""
from pathlib import Path

import pytest

from bridge.task_io import (
    BEGIN_MARKER,
    END_MARKER,
    extract_task_body,
    parse_task,
    validate_task_text,
)

WS = r"D:\AdyAI\ai-agent-framework"
FIXTURE = Path(__file__).parent / "fixtures" / "TASK-009-production.md"


def _production_task() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# ---------- 生产实证：TASK-009 全文（正文含 AAF_TASK_END 字样） ----------

def test_extract_body_uses_last_independent_end_marker():
    """正文中提到的 'AAF_TASK_END authority' 不得截断 body。"""
    text = _production_task()
    body = extract_task_body(text)
    assert "Acceptance:" in body, "body 被提前截断：真实 Acceptance 字段丢失"
    assert "Route:" in body
    assert "Expected Final Result:" in body
    # body 长度应接近全文（仅去掉 BEGIN/END 两行）
    assert len(body) > 4000, f"body 异常短: {len(body)}"


def test_production_task_009_passes_bridge_validation():
    """exact production regression：真实报错 TASK 必须通过 Bridge 校验。"""
    text = _production_task()
    ok, errors = validate_task_text(text, WS)
    assert ok is True, errors


def test_production_task_009_parse_acceptance():
    fields = parse_task(_production_task())
    assert fields["acceptance"].strip().startswith("1. Current formal"), fields["acceptance"]
    assert "21. tracked tree clean" in fields["acceptance"]


def test_production_task_009_crlf_variant_passes():
    """同一 production TASK 的 CRLF 变体也必须通过（与 LF 同权）。"""
    text = _production_task().replace("\n", "\r\n")
    ok, errors = validate_task_text(text, WS)
    assert ok is True, errors


# ---------- 独立行 marker 语义保持 ----------

def test_extract_body_between_independent_markers():
    body = extract_task_body(f"前文\n{BEGIN_MARKER}\nTask ID: X\n{END_MARKER}\n后文")
    assert body == "Task ID: X"


def test_extract_body_missing_markers_raises():
    from bridge.task_io import TaskParseError

    with pytest.raises(TaskParseError):
        extract_task_body("Task ID: X")


def test_extract_body_inline_end_marker_ignored():
    """正文里 'AAF_TASK_END authority'（非独立行）不截断；真正独立 END 才结束。"""
    body = extract_task_body(
        f"{BEGIN_MARKER}\nTask ID: X\nAAF_TASK_END authority 说明\nAcceptance: ok\n{END_MARKER}"
    )
    assert "Acceptance: ok" in body
    assert "authority" in body
