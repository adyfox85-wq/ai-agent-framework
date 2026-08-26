"""AI Agent Framework — Project Boundary Control 测试。"""
import json
from pathlib import Path
import pytest

from ai_agent_framework import project_boundary
from ai_agent_framework.project_boundary import (
    BOUNDARY_NOT_CONFIGURED,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_NONE,
    BoundaryCheckResult,
    ProjectBoundary,
    check_task,
    load_boundary,
    parse_boundary,
    write_boundary_json,
)


SCOPE_TEXT = """# Project Scope — Test

## Core Goal
做测试框架

## Current Scope
- 组件 A
- 组件 B

## Frozen Boundaries
- 不修改 workbuddy_skills/skills/
- 不重写 router.py

## Approved Extensions
- 组件 C（已批准）

## Backlog / Future Ideas
- 以后做组件 D
"""

TASK_OK = """# Task ID
T-1

# Task Name
ok

# Objective
实现组件 A 的功能

# Acceptance
1. 通过
"""

TASK_FROZEN_PHRASE = TASK_OK.replace("组件 A 的功能", "重写 router.py 的路由逻辑")

TASK_FROZEN_PATH = TASK_OK.replace("组件 A 的功能", "修改 workbuddy_skills/skills/ 下文件")


def _ws(tmp_path) -> Path:
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    return ws


# ---------- parse / load ----------

def test_parse_real_repo_scope():
    """真实仓库 docs/PROJECT_SCOPE.md 可被确定性解析。"""
    text = Path("docs/PROJECT_SCOPE.md").read_text(encoding="utf-8")
    b = parse_boundary(text, "docs/PROJECT_SCOPE.md")
    assert b.configured
    assert b.core_goal != "UNKNOWN"
    assert b.frozen_boundaries  # 至少含 v0.1 不在范围内
    assert any("Hermes" in x or "配置" in x for x in b.frozen_boundaries)


def test_parse_sections():
    b = parse_boundary(SCOPE_TEXT)
    assert b.core_goal == "做测试框架"
    assert b.current_scope == ["组件 A", "组件 B"]
    assert b.frozen_boundaries == ["不修改 workbuddy_skills/skills/", "不重写 router.py"]
    assert b.approved_extensions == ["组件 C（已批准）"]
    assert b.backlog == ["以后做组件 D"]


def test_missing_scope_not_configured(tmp_path):
    ws = _ws(tmp_path)
    b = load_boundary(ws)
    assert b.configured is False
    assert b.source_path is None


def test_malformed_sections_no_crash(tmp_path):
    """坏格式（无标题/乱内容）不崩溃 → 空列表/UNKNOWN。"""
    b = parse_boundary("随便一段没有标题的文字\n- 不是节")
    assert b.core_goal == "UNKNOWN"
    assert b.current_scope == []
    assert b.frozen_boundaries == []
    assert b.configured is True  # 文件存在即可解析（内容空则字段空）


def test_load_scope_file_explicit(tmp_path):
    ws = _ws(tmp_path)
    scope = ws / "custom-scope.md"
    scope.write_text("# Project Scope\n\n## Core Goal\n定制\n", encoding="utf-8")
    b = load_boundary(ws, scope_file=scope)
    assert b.configured
    assert b.core_goal == "定制"
    assert b.source_path == str(scope)


def test_backlog_distinction():
    """Backlog 与 Current Scope 分离（解析互不污染）。"""
    b = parse_boundary(SCOPE_TEXT)
    assert "以后做组件 D" in b.backlog
    assert "以后做组件 D" not in b.current_scope


# ---------- check_task ----------

def test_normal_task_no_high_risk(tmp_path):
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    b = load_boundary(ws)
    r = check_task(b, TASK_OK)
    assert r.configured
    assert r.severity == SEVERITY_NONE
    assert r.warnings == []


def test_frozen_phrase_hit_medium(tmp_path):
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    r = check_task(load_boundary(ws), TASK_FROZEN_PHRASE)
    assert r.severity == SEVERITY_MEDIUM
    assert any("router.py" in w for w in r.warnings)
    assert "router.py" in r.matched_boundaries


def test_real_scope_multiconcept_frozen_hit(tmp_path):
    """真实格式：'不修改 Hermes 配置 / WorkBuddy 配置 / 账号 / token'（/ 是多概念分隔符，非路径）。
    TASK 提到其中一个概念 → MEDIUM（不得因含 / 被跳过）。"""
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(
        "## Frozen Boundaries\n\n- 不修改 Hermes 配置 / WorkBuddy 配置 / 账号 / token\n", encoding="utf-8")
    b = load_boundary(ws)
    task = "# Task ID\nT-X\n\n# Objective\n修改 Hermes 配置\n\n# Acceptance\n1. 通过\n"
    r = check_task(b, task)
    assert r.severity == SEVERITY_MEDIUM
    assert any("Hermes 配置" in w for w in r.warnings)
    # 真实路径（含 / 的路径片段）仍是 HIGH
    task2 = "# Task ID\nT-X\n\n# Objective\n删除 docs/internal 历史材料\n\n# Acceptance\n1. 通过\n"
    scope2 = ws / "docs" / "PROJECT_SCOPE.md"
    scope2.write_text("## Frozen Boundaries\n\n- 不删除 docs/internal 历史材料\n", encoding="utf-8")
    r2 = check_task(load_boundary(ws), task2)
    assert r2.severity == SEVERITY_HIGH


def test_frozen_path_hit_high(tmp_path):
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    r = check_task(load_boundary(ws), TASK_FROZEN_PATH)
    assert r.severity == SEVERITY_HIGH
    assert any("frozen path" in w for w in r.warnings)


def test_unconfigured_check_no_warnings(tmp_path):
    b = ProjectBoundary(configured=False)
    r = check_task(b, TASK_FROZEN_PATH)
    assert r.configured is False
    assert r.severity == SEVERITY_NONE
    assert r.warnings == []


def test_boundary_check_error_code_name():
    assert BOUNDARY_NOT_CONFIGURED == "BOUNDARY_NOT_CONFIGURED"


# ---------- boundary.json ----------

def test_boundary_json_write(tmp_path):
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    r = check_task(load_boundary(ws), TASK_FROZEN_PATH)
    out = ws / ".aaf" / "T-1"
    path = write_boundary_json(out, "T-1", r, "docs/PROJECT_SCOPE.md")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("task_id", "configured", "severity", "warnings", "matched_boundaries", "checked_at", "source_path"):
        assert key in data
    assert data["task_id"] == "T-1"
    assert data["severity"] == SEVERITY_HIGH
    assert data["configured"] is True


# ---------- runner 集成（warning 不阻断 / validation 跳过） ----------

def _valid_task_text(task_id="T-B"):
    return f"""# Task ID
{task_id}

# Task Name
boundary runner test

# Objective
实现组件 A 的功能

# Acceptance
1. 通过
"""


def test_warning_does_not_block_router(tmp_path):
    """HIGH warning 仍执行 Router（warning-first）。"""
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    task_file = ws / "T.md"
    task_file.write_text(_valid_task_text().replace("组件 A 的功能", "修改 workbuddy_skills/skills/ 下文件"), encoding="utf-8")
    import ai_agent_framework.runner as runner_mod
    out = ws / ".aaf" / "T-B"
    report = runner_mod.run(task_file, ws, out, dry_run=True)
    assert report.exists()  # 正常生成 REPORT（Router 未被阻断）
    bj = out / "boundary.json"
    assert bj.exists()
    data = json.loads(bj.read_text(encoding="utf-8"))
    assert data["severity"] == SEVERITY_HIGH
    assert (out / "route.json").exists()  # Router 已执行


def test_validation_failure_skips_boundary(tmp_path):
    """Validation 失败 → 不执行 Boundary Check（不写 boundary.json）。"""
    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    task_file = ws / "bad.md"
    task_file.write_text("# Task ID\nT-BAD\n\n# Objective\n缺 Acceptance\n", encoding="utf-8")
    import ai_agent_framework.runner as runner_mod
    from ai_agent_framework.task_validation import TaskValidationError
    out = ws / ".aaf" / "T-BAD"
    with pytest.raises(TaskValidationError):
        runner_mod.run(task_file, ws, out, dry_run=True)
    assert not (out / "boundary.json").exists()


# ---------- Session Continuity 集成 ----------

def test_session_carries_boundary(tmp_path):
    """Session rollover 继承 PROJECT_SCOPE 的 Core Goal / Frozen Boundaries / Current Scope。"""
    from ai_agent_framework.session_continuity import rollover

    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(SCOPE_TEXT, encoding="utf-8")
    r = rollover(ws, phase="ph", next_step="ns")
    summary = Path(r.summary_path).read_text(encoding="utf-8")
    next_start = Path(r.next_start_path).read_text(encoding="utf-8")
    assert "## Core Goal\n做测试框架" in summary
    assert "不修改 workbuddy_skills/skills/" in summary
    assert "不修改 workbuddy_skills/skills/" in next_start  # NEXT 携带 Frozen Boundaries
    assert "组件 A" in next_start  # Current Scope 携带


def test_missing_scope_does_not_break_session(tmp_path):
    from ai_agent_framework.session_continuity import rollover

    ws = _ws(tmp_path)
    r = rollover(ws, project="P", core_goal="g")  # 无 PROJECT_SCOPE / PROJECT_STATE
    text = Path(r.summary_path).read_text(encoding="utf-8")
    assert "## Core Goal\ng" in text
    next_start = Path(r.next_start_path).read_text(encoding="utf-8")
    assert "- (not configured)" in next_start


def test_session_scope_beats_state_priority(tmp_path):
    """PROJECT_SCOPE 优先于 PROJECT_STATE（正式 Boundary Source 优先级）。"""
    from ai_agent_framework.session_continuity import rollover

    ws = _ws(tmp_path)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "PROJECT_SCOPE.md").write_text(
        "## Core Goal\nSCOPE 目标\n\n## Frozen Boundaries\nSCOPE 冻结\n", encoding="utf-8")
    (ws / "PROJECT_STATE.md").write_text(
        "## Core Goal\nSTATE 目标\n\n## Frozen Boundaries\nSTATE 冻结\n", encoding="utf-8")
    r = rollover(ws, phase="ph")
    summary = Path(r.summary_path).read_text(encoding="utf-8")
    assert "## Core Goal\nSCOPE 目标" in summary  # PROJECT_SCOPE 优先
    assert "SCOPE 冻结" in summary
    assert "STATE 目标" not in summary
    # 无 PROJECT_SCOPE 时退回 PROJECT_STATE
    ws2 = tmp_path / "projB"
    ws2.mkdir()
    (ws2 / "PROJECT_STATE.md").write_text("## Core Goal\nSTATE 目标\n", encoding="utf-8")
    r2 = rollover(ws2, phase="ph")
    assert "## Core Goal\nSTATE 目标" in Path(r2.summary_path).read_text(encoding="utf-8")
