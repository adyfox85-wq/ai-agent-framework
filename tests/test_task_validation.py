"""AI Agent Framework — 正式 Task Validation 测试（单测 + integration）。"""
from pathlib import Path
import pytest

from ai_agent_framework.task_validation import (
    REQUIRED_FIELDS,
    TaskValidationError,
    ValidationResult,
    parse_task_fields,
    validate_task_text,
)
from ai_agent_framework import runner

VALID_TASK = """# Task ID
AAF-V03-001

# Task Name
Formal Task Validation

# Workspace
D:\\AdyAI\\ai-agent-framework

# Objective
为 Framework 增加正式 Task Validation 层。

# Acceptance
1. 合法 TASK 通过校验
2. 非法 TASK 被拒绝

AAF_TASK_END
"""


def _task(**overrides):
    text = VALID_TASK
    for key, value in overrides.items():
        if value is None:  # 删除字段
            text = text.replace(f"\n# {key}\n", "\n").replace(f"\n# {key}\n", "\n")
        else:
            old = text.split(f"# {key}\n", 1)[1].split("\n\n", 1)[0] if f"# {key}\n" in text else ""
            text = text.replace(old, value)
    return text


# ---------- 解析 ----------

def test_parse_fields():
    f = parse_task_fields(VALID_TASK)
    assert f["Task ID"] == "AAF-V03-001"
    assert f["Task Name"] == "Formal Task Validation"
    assert f["Workspace"] == r"D:\AdyAI\ai-agent-framework"
    assert f["Objective"].startswith("为 Framework")
    assert f["Acceptance"].startswith("1.")


def test_parse_single_line_style():
    text = "Task ID: AAF-X\nTask Name: n\nWorkspace: D:\\ws\nObjective: o\nAcceptance: a"
    f = parse_task_fields(text)
    assert f["Task ID"] == "AAF-X"
    assert f["Objective"] == "o"


# ---------- 必填字段 ----------

def test_valid_task():
    r = validate_task_text(VALID_TASK)
    assert r.valid is True
    assert r.errors == []


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_required_field(field):
    # 删除字段标题+值，模拟缺失
    lines = []
    skip_next = False
    for line in VALID_TASK.splitlines():
        if skip_next:
            skip_next = False
            continue
        if line.startswith(f"# {field}"):
            skip_next = True  # 跳过该字段标题+值
            continue
        lines.append(line)
    r = validate_task_text("\n".join(lines))
    assert r.valid is False
    assert any(field in e for e in r.errors)


def test_empty_field_is_missing():
    text = VALID_TASK.replace("为 Framework 增加正式 Task Validation 层。", "   ")
    r = validate_task_text(text)
    assert r.valid is False
    assert any("Objective" in e for e in r.errors)


def test_optional_fields_missing_ok():
    text = VALID_TASK
    for key in ("Background", "Requirements", "Scope", "Files", "Route Hint", "Execution Policy"):
        text = text.replace(f"# {key}\n", "")
    r = validate_task_text(text)
    assert r.valid is True


# ---------- Task ID 安全 ----------

@pytest.mark.parametrize(
    "bad_id",
    [
        "AAF/../../etc/passwd",
        "..\\..\\windows",
        "..",
        "a/b",
        "a\\b",
        "C:\\Windows",
        "/etc/passwd",
        "bad:name",
    ],
)
def test_task_id_unsafe(bad_id):
    text = VALID_TASK.replace("AAF-V03-001", bad_id)
    r = validate_task_text(text)
    assert r.valid is False
    assert any("Task ID" in e for e in r.errors)


def test_task_id_normal_ok():
    for good in ("AAF-V03-001", "TASK-123", "abc_def", "X-01"):
        r = validate_task_text(VALID_TASK.replace("AAF-V03-001", good))
        assert r.valid is True, good


# ---------- Workspace ----------

def test_workspace_empty_invalid():
    # Workspace 由 CLI 强制（TASK 文件内可选）——缺失不再算文件错误；
    # 但"存在且非法"必须拒绝
    text = VALID_TASK.replace("# Workspace\nD:\\AdyAI\\ai-agent-framework\n", "")
    r = validate_task_text(text)
    assert r.valid is True  # 文件内缺失 Workspace = 合法（CLI --workspace 强制）


def test_workspace_blank_value_invalid():
    # 值留空行 → 等价缺失 → 合法（同上）
    text = VALID_TASK.replace("D:\\AdyAI\\ai-agent-framework", "")
    r = validate_task_text(text)
    assert r.valid is True


def test_workspace_present_but_invalid_rejected():
    text = VALID_TASK.replace("D:\\AdyAI\\ai-agent-framework", "D:\\bad\x00path")
    r = validate_task_text(text)
    assert r.valid is False
    assert any("Workspace" in e for e in r.errors)


def test_workspace_control_chars_invalid():
    text = VALID_TASK.replace(r"D:\AdyAI\ai-agent-framework", "D:\\bad\x00path")
    r = validate_task_text(text)
    assert r.valid is False


def test_workspace_relative_ok():
    """相对路径合法（runner 会创建目录，与现有 CLI 语义一致：不要求存在）。"""
    text = VALID_TASK.replace(r"D:\AdyAI\ai-agent-framework", "./work")
    r = validate_task_text(text)
    assert r.valid is True


# ---------- Integration：Router 边界 ----------

def test_valid_task_reaches_router(monkeypatch, tmp_path):
    """合法 TASK：Router 被调用（dry-run 不启动 Agent）。"""
    called = {"route": False}
    original = runner.decide_route

    def spy_route(task):
        called["route"] = True
        return original(task)

    monkeypatch.setattr(runner, "decide_route", spy_route)
    task_file = tmp_path / "TASK.md"
    task_file.write_text(VALID_TASK, encoding="utf-8")
    out = tmp_path / "out"
    report = runner.run(task_file, Path(tmp_path / "ws"), out, dry_run=True)
    assert called["route"] is True
    assert report.exists()
    assert "DRY_RUN" in report.read_text(encoding="utf-8")


def test_invalid_task_stops_before_router(monkeypatch, tmp_path):
    """非法 TASK：Router 不被调用、Agent 不启动、抛 TaskValidationError。"""
    agent_calls = []

    def bad_agent(agent, prompt, workspace):
        agent_calls.append(agent)
        return "SHOULD NOT HAPPEN"

    monkeypatch.setattr(runner, "decide_route", lambda task: (_ for _ in ()).throw(AssertionError("router must not run")))
    monkeypatch.setattr(runner, "run_agent", bad_agent)

    invalid = VALID_TASK.replace("# Objective\n为 Framework 增加正式 Task Validation 层。", "# Objective\n\n")
    task_file = tmp_path / "BAD.md"
    task_file.write_text(invalid, encoding="utf-8")
    with pytest.raises(TaskValidationError) as ei:
        runner.run(task_file, Path(tmp_path / "ws"), tmp_path / "out")
    assert ei.value.result.valid is False
    assert "Objective" in "\n".join(ei.value.result.errors)
    assert agent_calls == []
    assert not (tmp_path / "out" / "route.json").exists()


def test_cli_invalid_exit_code(tmp_path):
    """CLI 直接调用 run.py：非法 TASK → 非零退出 + 清晰错误。"""
    invalid = VALID_TASK.replace(
        "# Acceptance\n1. 合法 TASK 通过校验\n2. 非法 TASK 被拒绝", "# Acceptance\n\n"
    )
    task_file = tmp_path / "BAD.md"
    task_file.write_text(invalid, encoding="utf-8")
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "run.py", str(task_file), "--workspace", str(tmp_path / "ws"), "--output", str(tmp_path / "out"), "--dry-run"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 2
    assert "TASK_VALIDATION_FAILED" in r.stdout
    assert "Acceptance" in r.stdout
