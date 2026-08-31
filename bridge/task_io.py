"""AAF Bridge — TASK 文本解析 / 校验 / 落盘（纯函数，可单测）。

Planner 输出标准 TASK 文本（含 AAF_TASK_BEGIN / AAF_TASK_END 标记），
Bridge 校验后落盘到 <Workspace>\\.aaf\\tasks\\active\\<Task-ID>.md。
"""
from __future__ import annotations

import re
import os
from pathlib import Path

from ai_agent_framework.risk_contract import RISK_CLASSES  # 唯一 risk 词汇 authority（A1 契约）

BEGIN_MARKER = "AAF_TASK_BEGIN"
END_MARKER = "AAF_TASK_END"

# 单行必填字段（Task ID / Task Name / Workspace）
SINGLE_LINE_FIELDS = {
    "task id": "task_id",
    "task name": "task_name",
    "workspace": "workspace",
    # AAF-v0.5-A2-SHADOW-ROUTING-003：可选结构化 task risk（Planner 显式声明）。
    # 缺失 = 向后兼容；存在但非法 = 严格拒绝（fail-closed，不静默降级）。
    "risk": "risk",
}

# 多行必填字段（Objective / Acceptance）：从字段行收集到下一个节
MULTI_LINE_FIELDS = {
    "objective": "objective",
    "acceptance": "acceptance",
}

# 下一节检测：markdown 标题（# ...）或 大写字段行（如 Requirements: / Scope:）
# 大节边界：# 或 ## 标题（### 及更深是内容子节，不截断）、或大写字段名
_SECTION_RE = re.compile(r"^[ \t]*(#{1,2}[ \t]+\S|[A-Z][A-Za-z /()\-]{2,40}:)")

# AAF-v0.5-A2-SHADOW-ROUTING-003：Risk 是**顶层**字段（template 位置 = Workspace 之后、
# Objective 之前）。识别边界 = 首个 Objective 节起始；Objective 之后的 `Risk:` 行是
# 正文 prose，不得当作字段声明（与 framework task_validation 同一规则）。
_OBJECTIVE_START_RE = re.compile(
    r"(?im)^[ \t]*(?:#+[ \t]*)?Objective[ \t]*[:：][ \t]*\S[^\r\n]*$"
    r"|^[ \t]*(?:#+[ \t]*)?Objective[ \t]*[:：]?[ \t]*$"
)


def _risk_preamble(body: str) -> str:
    """返回 Risk 字段可识别的顶层 preamble（首个 Objective 节之前）。"""
    m = _OBJECTIVE_START_RE.search(body or "")
    return body if m is None else body[: m.start()]

# 不安全文件名字符（Task ID 用作文件名）
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class TaskParseError(ValueError):
    """TASK 文本格式/字段错误（message 面向用户）。"""


def extract_task_body(text: str) -> str:
    """提取 AAF_TASK_BEGIN ... AAF_TASK_END 之间的正文；无标记时报错。

    RW-008 生产 blocker（TASK-009 实证）：标记必须**独立成行**匹配
    （``^AAF_TASK_END$`` MULTILINE），不得匹配正文中出现的
    ``AAF_TASK_END authority`` 等文档性说明——否则 body 被提前截断，
    后面的 Acceptance / Route 字段全部丢失，Bridge 误报
    「缺少必填字段: Acceptance」。BEGIN/END 均为独立行是 AAF 模板
    与落盘格式的既有契约（``f"{BEGIN_MARKER}\\n{body}\\n{END_MARKER}"``）。
    """
    m = re.search(
        r"^\ufeff?[ \t]*" + re.escape(BEGIN_MARKER) + r"[ \t]*\r?$"
        r"(.*?)"
        r"^[ \t]*" + re.escape(END_MARKER) + r"[ \t]*\r?$",
        text,
        re.MULTILINE | re.DOTALL,
    )
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
                # 标题后第一个非空行若是另一节标题（# 开头）→ 本字段值为空
                if line.lstrip().startswith("#"):
                    return ""
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
    """解析 TASK 正文，返回字段 dict（缺失字段为 ''）。

    RW-008：解析前统一归一化行尾（CRLF → LF）。行锚定正则依赖
    MULTILINE ``$``（断言在 ``\\n`` 前），CRLF 下 ``\\r`` 会卡住
    ``[ \\t]*$``，导致 ``Acceptance:`` 等标题行匹配失败（生产复现：
    「缺少必填字段: Acceptance」）。归一化只影响解析，不改原文语义；
    落盘仍保留 Planner 原始正文。
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    result: dict[str, str] = {}
    for key, name in SINGLE_LINE_FIELDS.items():
        if name == "risk":
            # AAF-v0.5-A2-SHADOW-ROUTING-003：Risk 只在顶层 preamble 识别（正文推断被禁止）
            result[name] = _read_single_line_field(_risk_preamble(body), key)
        else:
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

    # RW-008：Acceptance 唯一性 fail-closed（与 Route 契约一致；不得 first/last wins）
    acc_occurrences = len(
        re.findall(r"(?im)^[ \t]*(?:#+[ \t]*)?Acceptance[ \t]*(?:[:：]|$)", body or "")
    )
    if acc_occurrences > 1:
        errors.append("Acceptance 字段重复声明（fail-closed，不得 first/last wins）")

    # AAF-v0.5-A2-SHADOW-ROUTING-003：Risk 唯一性（顶层 preamble 内）fail-closed
    # FIX-001（唯一 blocker）：显式声明但值为空/纯空白（`Risk:` / `Risk:   `）
    # 必须 fail-closed——「已声明」≠「缺失」；只有字段完全缺失才允许向后兼容
    # （shadow = RISK_UNAVAILABLE），声明一次且无值绝不降级成 RISK_UNAVAILABLE。
    risk_preamble = _risk_preamble(body)
    risk_occurrences = len(
        re.findall(r"(?im)^[ \t]*(?:#+[ \t]*)?Risk[ \t]*(?:[:：]|$)", risk_preamble)
    )
    if risk_occurrences > 1:
        errors.append("Risk 字段重复声明（fail-closed，不得 first/last wins）")

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

    # AAF-v0.5-A2-SHADOW-ROUTING-003：可选结构化 task risk（早期 UX Guard，
    # 与 framework task_validation 的正式校验保持一致）：缺失 = 向后兼容；
    # 存在但非法 = 严格拒绝（不静默降级、不做大小写/同义词猜测）。
    # FIX-001：声明一次但值为空/纯空白 = 严格拒绝（不降级成缺失/RISK_UNAVAILABLE）。
    risk_value = (fields.get("risk") or "").strip()
    if risk_occurrences >= 1 and not risk_value:
        errors.append(
            "Risk 字段已声明但值为空（fail-closed：显式声明必须携带合法 Risk 值；"
            "只有字段缺失才允许向后兼容，不得静默当作 RISK_UNAVAILABLE）"
        )
    elif risk_value and risk_value not in RISK_CLASSES:
        errors.append(
            f"非法 Risk 字段: {risk_value!r}（只接受 {', '.join(RISK_CLASSES)}；"
            "Planner 显式 Risk 必须是结构化词汇，不做大小写/同义词猜测）"
        )

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
