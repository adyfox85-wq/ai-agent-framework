"""AAF Bridge — task_io 解析/校验/落盘测试。"""
from pathlib import Path
import pytest

from bridge.task_io import (
    BEGIN_MARKER,
    END_MARKER,
    extract_task_body,
    parse_task,
    save_task,
    task_target_path,
    validate_task_text,
    TaskParseError,
)

WS = r"D:\AdyAI\ai-agent-framework"

SAMPLE_TASK = f"""# Task ID
AAF-V03-000-A

# Task Name
AAF Bridge Minimal Intake

# Workspace
{WS}

# Objective
实现一个 Windows 本地 AAF Bridge 最小入口。

# Requirements
- 热键 Ctrl+Alt+A
- 剪贴板读取

# Acceptance
1. 热键可触发
2. 合法 TASK 落盘

AAF_TASK_END
"""


def _wrapped(body: str) -> str:
    return f"AAF_TASK_BEGIN\n{body}\nAAF_TASK_END"


# ---------- 解析 ----------

def test_extract_body_between_markers():
    body = extract_task_body(f"前文\nAAF_TASK_BEGIN\nTask ID: X\nAAF_TASK_END\n后文")
    assert body == "Task ID: X"


def test_extract_body_missing_markers_raises():
    with pytest.raises(TaskParseError):
        extract_task_body("Task ID: X")


def test_parse_single_line_fields():
    body = _wrapped("# Task ID\nAAF-X\n\n# Task Name\n名字\n\n# Workspace\nD:\\ws")
    f = parse_task(body)
    assert f["task_id"] == "AAF-X"
    assert f["task_name"] == "名字"
    assert f["workspace"] == r"D:\ws"


def test_parse_multiline_fields():
    body = _wrapped(SAMPLE_TASK.replace("AAF_TASK_END", ""))
    f = parse_task(body)
    assert f["objective"] == "实现一个 Windows 本地 AAF Bridge 最小入口。"
    assert f["acceptance"].startswith("1.")
    assert "落盘" in f["acceptance"]


# ---------- 校验 ----------

def test_validate_ok_when_fields_and_workspace_match():
    ok, errors = validate_task_text(_wrapped(SAMPLE_TASK.replace("AAF_TASK_END", "")), WS)
    assert ok is True
    assert errors == []


def test_validate_missing_marker():
    ok, errors = validate_task_text("Task ID: X\nTask Name: Y\nWorkspace: Z", WS)
    assert ok is False
    assert any("标记" in e for e in errors)


def test_validate_missing_required_field():
    body = _wrapped("# Task ID\nAAF-X\n\n# Workspace\nD:\\ws\n\n# Objective\nobj\n\n# Acceptance\nacc")
    ok, errors = validate_task_text(body, r"D:\ws")
    assert ok is False
    assert any("Task Name" in e for e in errors)


def test_validate_workspace_mismatch():
    body = _wrapped(SAMPLE_TASK.replace("AAF_TASK_END", ""))
    ok, errors = validate_task_text(body, r"D:\OTHER\PROJECT")
    assert ok is False
    assert any("Workspace 不匹配" in e for e in errors)


def test_validate_unsafe_task_id():
    body = _wrapped("# Task ID\nAAF/X\\Y\n\n# Task Name\nn\n\n# Workspace\nD:\\ws\n\n# Objective\nobj\n\n# Acceptance\nacc")
    ok, errors = validate_task_text(body, r"D:\ws")
    assert ok is False
    assert any("不安全文件名字符" in e for e in errors)


def test_validate_workspace_case_insensitive():
    body = _wrapped(SAMPLE_TASK.replace("AAF_TASK_END", "").replace(WS, WS.lower()))
    ok, errors = validate_task_text(body, WS)
    assert ok is True


# ---------- 落盘 ----------

def test_target_path():
    p = task_target_path(r"D:\ws", "AAF-X")
    assert p == Path(r"D:\ws\.aaf\tasks\active\AAF-X.md")


def test_save_task_creates_minimal_dirs(tmp_path):
    target = save_task("content", str(tmp_path), "AAF-T1")
    assert target == tmp_path / ".aaf" / "tasks" / "active" / "AAF-T1.md"
    assert target.read_text(encoding="utf-8") == "content"
    # 只创建最小目录
    assert (tmp_path / ".aaf" / "tasks" / "active").is_dir()
    assert not (tmp_path / ".aaf" / "archive").exists()


def test_save_task_duplicate_raises(tmp_path):
    save_task("first", str(tmp_path), "AAF-T1")
    with pytest.raises(TaskParseError) as ei:
        save_task("second", str(tmp_path), "AAF-T1")
    assert "TASK_ALREADY_EXISTS" in str(ei.value)
    # 原文件未被覆盖
    assert (tmp_path / ".aaf" / "tasks" / "active" / "AAF-T1.md").read_text(encoding="utf-8") == "first"


def test_save_task_keeps_full_task_text_with_markers(tmp_path):
    """落盘内容保留 Planner 标准 TASK 正文（含 BEGIN/END），不写入标记外前后文。"""
    text = (
        "聊天前文...\n"
        "AAF_TASK_BEGIN\n"
        "Task ID: AAF-X\n\nTask Name: n\n\nWorkspace: W\n\nObjective: o\n\nAcceptance: a\n"
        "AAF_TASK_END\n"
        "聊天后文..."
    )
    body = extract_task_body(text)
    target = save_task(
        f"{BEGIN_MARKER}\n{body}\n{END_MARKER}", str(tmp_path), "AAF-X"
    )
    content = target.read_text(encoding="utf-8")
    assert content.startswith("AAF_TASK_BEGIN")
    assert content.endswith("AAF_TASK_END")
    assert "聊天前文" not in content
    assert "聊天后文" not in content
