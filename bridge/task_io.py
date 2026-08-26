"""AAF Bridge — TASK 文本解析 / 校验 / 落盘（纯函数，可单测）。

Planner 输出标准 TASK 文本（含 AAF_TASK_BEGIN / AAF_TASK_END 标记），
Bridge 校验后落盘到 <Workspace>\\.aaf\\tasks\\active\\<Task-ID>.md。
"""
from __future__ import annotations

import re
import os
from pathlib import Path

BEGIN_MARKER = "AAF_TASK_BEGIN"
END_MARKER = "AAF_TASK_END"

# 单行必填字段（Task ID / Task Name / Workspace）
SINGLE_LINE_FIELDS = {
    "task id": "task_id",
    "task name": "task_name",
    "workspace": "workspace",
}

# 多行必填字段（Objective / Acceptance）：从字段行收集到下一个节
MULTI_LINE_FIELDS = {
    "objective": "objective",
    "acceptance": "acceptance",
}

# 下一节检测：markdown 标题（# ...）或 大写字段行（如 Requirements: / Scope:）
_SECTION_RE = re.compile(r"^\s*(#{1,6}\s+\S|[A-Z][A-Za-z /()\-]{2,40}:)")

# 不安全文件名字符（Task ID 用作文件名）
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class TaskParseError(ValueError):
    """TASK 文本格式/字段错误（message 面向用户）。"""


def extract_task_body(text: str) -> str:
    """提取 AAF_TASK_BEGIN ... AAF_TASK_END 之间的正文；无标记时报错。"""
    m = re.search(re.escape(BEGIN_MARKER) + r"(.*?)" + re.escape(END_MARKER), text, re.DOTALL)
    if not m:
        raise TaskParseError("缺少 AAF_TASK_BEGIN / AAF_TASK_END 标记")
    return m.group(1).strip()


def _read_single_line_field(body: str, field_key: str) -> str:
    """匹配 `Task ID: xxx` 或 `## Task ID` + 下一行值（兼容 Planner 两种格式）。

    行内空白统一用 [ \\t]（不含 \\n），避免 (?im)^ 跨行匹配导致位置偏移。
    """
    # 格式 1：同行值  Task ID: xxx / ## Task ID: xxx
    pat_inline = re.compile(
        r"(?im)^[ \t]*(?:#+[ \t]*)?" + re.escape(field_key) + r"[ \t]*[:：][ \t]*([^\r\n]+)[ \t]*$"
    )
    m = pat_inline.search(body)
    if m:
        return m.group(1).strip()
    # 格式 2：标题 + 下一非空行  ## Task ID\nAAF-X
    pat_heading = re.compile(r"(?im)^[ \t]*#+[ \t]*" + re.escape(field_key) + r"[ \t]*$")
    m = pat_heading.search(body)
    if m:
        rest = body[m.end():]
        for line in rest.splitlines():
            if line.strip():
                return line.strip()
    return ""


def _collect_multiline(body: str, start_idx: int) -> str:
    """从 start_idx（字段行之后）收集到下一节。"""
    lines = body.splitlines()
    collected = []
    for line in lines[start_idx:]:
        if _SECTION_RE.match(line):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _read_multiline_field(body: str, field_key: str) -> str:
    """匹配 Objective / Acceptance。

    - 同行值：`Acceptance: 内容`（含 `## Acceptance: 内容`）→ 返回该行
    - 纯标题或空冒号（`# Acceptance` / `Acceptance:`）→ 从下一行收集到下一节
    """
    # 同行值：必须带冒号且有非空内容（避免跨行把下一行误当同行值）
    pat_inline = re.compile(
        r"(?im)^[ \t]*(?:#+[ \t]*)?(?:" + re.escape(field_key) + r")[ \t]*[:：][ \t]*(\S.*)$"
    )
    m = pat_inline.search(body)
    if m:
        return m.group(1).strip()
    # 纯标题 / 空冒号：锚定行尾（行内空白不跨行）
    pat_heading = re.compile(
        r"(?im)^[ \t]*(?:#+[ \t]*)?(?:" + re.escape(field_key) + r")[ \t]*[:：]?[ \t]*$"
    )
    m = pat_heading.search(body)
    if not m:
        return ""
    line_no = body[: m.start()].count("\n")
    return _collect_multiline(body, line_no + 1)


def parse_task(body: str) -> dict[str, str]:
    """解析 TASK 正文，返回字段 dict（缺失字段为 ''）。"""
    result: dict[str, str] = {}
    for key, name in SINGLE_LINE_FIELDS.items():
        result[name] = _read_single_line_field(body, key)
    for key, name in MULTI_LINE_FIELDS.items():
        result[name] = _read_multiline_field(body, key)
    return result


def validate_task_text(
    text: str,
    expected_workspace: str,
) -> tuple[bool, list[str]]:
    """校验完整 TASK 文本。返回 (ok, errors)。"""
    errors: list[str] = []
    try:
        body = extract_task_body(text)
    except TaskParseError as e:
        return False, [str(e)]

    fields = parse_task(body)

    for name, label in [
        ("task_id", "Task ID"),
        ("task_name", "Task Name"),
        ("workspace", "Workspace"),
        ("objective", "Objective"),
        ("acceptance", "Acceptance"),
    ]:
        if not fields.get(name):
            errors.append(f"缺少必填字段: {label}")

    task_id = fields.get("task_id", "")
    if task_id and _UNSAFE_FILENAME_RE.search(task_id):
        errors.append(f"Task ID 包含不安全文件名字符: {task_id}")

    if not expected_workspace:
        errors.append("Bridge 当前未绑定 Workspace（请先设置 current_workspace）")
    elif fields.get("workspace") and expected_workspace:
        if os.path.normcase(os.path.normpath(fields["workspace"])) != os.path.normcase(
            os.path.normpath(expected_workspace)
        ):
            errors.append(
                f"Workspace 不匹配：TASK 声明 {fields['workspace']!r}，"
                f"Bridge 当前绑定 {expected_workspace!r}"
            )

    return (len(errors) == 0, errors)


def task_target_path(workspace: str, task_id: str) -> Path:
    """正式 TASK 落盘路径：<Workspace>\\.aaf\\tasks\\active\\<Task-ID>.md"""
    return Path(workspace) / ".aaf" / "tasks" / "active" / f"{task_id}.md"


def save_task(text: str, workspace: str, task_id: str) -> Path:
    """落盘正式 TASK.md。目录不存在则创建最小结构；已存在同名 → 抛 TaskParseError(TASK_ALREADY_EXISTS)。

    内容保留 Planner 提交的标准 TASK 正文（含 BEGIN/END 标记），不擅自改写语义。
    """
    target = task_target_path(workspace, task_id)
    if target.exists():
        raise TaskParseError(f"TASK_ALREADY_EXISTS: {task_id}（{target}）")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
