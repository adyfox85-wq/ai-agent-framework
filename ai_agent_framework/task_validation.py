"""AI Agent Framework — Formal Task Validation（确定性、本地、无 LLM、无 Agent）。

职责：
- 任何正式 TASK 进入 Router / Runner / Agent 之前先经过统一校验
- 只判断"格式是否合法、完整、可执行"，不做业务合理性判断
- 不负责 Project Scope Enforcement
- 不调用任何 LLM / Hermes / WorkBuddy / Codex

执行顺序：TASK → Validate → Router → Runner → Agents
（Validator 是最终执行边界；Bridge task_io 校验是早期 UX Guard，两层并存）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 正式必填字段（TASK 文件内）
# 注：Workspace 由 CLI 参数 --workspace 强制（argparse required），
# 与 v0.2 现有语义一致（旧格式 TASK 文件内无 Workspace 字段）；
# TASK 文件内若有 Workspace 字段则校验其合法性，缺失不算文件错误。
REQUIRED_FIELDS = ("Task ID", "Task Name", "Objective", "Acceptance")

# 字段别名（旧格式用 "Acceptance Criteria"，新格式用 "Acceptance"）
_FIELD_ALIASES = {
    "Acceptance": ("Acceptance", "Acceptance Criteria"),
}

# 允许存在但不强制
OPTIONAL_FIELDS = (
    "Workspace",  # 旧格式 TASK 文件内无此字段（CLI --workspace 强制）；存在时校验
    "Background",
    "Requirements",
    "Scope",
    "Out of Scope",
    "Scope / Out of Scope",
    "Context",
    "Source of Truth",
    "Validation",
    "Files",
    "Route",
    "Route Hint",
    "Execution Policy",
    "Planner Notes",
)

VALIDATION_FAILED_MARKER = "TASK_VALIDATION_FAILED"

# 非法 Task ID / Workspace 字符（路径分隔符、穿越、控制字符）
_PATH_SEPARATORS = re.compile(r"[/\\]")
_DOTDOT = re.compile(r"(^|[\s/\\])\.\.[\s/\\]|(^|[\s/\\])\.\.$")
_ABSOLUTE_WINDOWS = re.compile(r"^[A-Za-z]:[\\/]")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# machine-authoritative control field（如 Route）唯一性契约的通用 regex 缓存
_FIELD_OCCURRENCE_RE_CACHE: dict[str, re.Pattern] = {}


def count_field_occurrences(body: str, field_key: str) -> int:
    """统计字段出现次数（同行式 `Key: value` 或标题式 `# Key` + 下一行值）。

    machine-authoritative control field（如 Route，FIX-005 Req 6/7）要求
    唯一：出现次数 >1 → 调用方必须 fail-closed（不得 first/last wins）。
    其他 machine-authoritative control fields 如有同类唯一性 contract，
    可复用本 helper 保证契约一致（不得扩大重构范围）。
    """
    pat = _FIELD_OCCURRENCE_RE_CACHE.get(field_key)
    if pat is None:
        pat = re.compile(
            r"(?im)^[ \t]*(?:#+[ \t]*)?"
            + re.escape(field_key)
            + r"[ \t]*(?:[:：]|$)"
        )
        _FIELD_OCCURRENCE_RE_CACHE[field_key] = pat
    return len(pat.findall(body or ""))


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class TaskValidationError(ValueError):
    """TASK 校验失败（携带 ValidationResult）。"""

    def __init__(self, result: ValidationResult):
        self.result = result
        lines = [VALIDATION_FAILED_MARKER]
        if result.errors:
            lines.append("Missing / Invalid:")
            lines.extend(f"- {e}" for e in result.errors)
        super().__init__("\n".join(lines))


# ---------- 解析（确定性文本提取，与 bridge/task_io 规则保持一致） ----------

def _read_single_line_field(body: str, field_key: str) -> str:
    """匹配 `Task ID: xxx` 或 `## Task ID` + 下一行值。"""
    pat_inline = re.compile(
        r"(?im)^[ \t]*(?:#+[ \t]*)?" + re.escape(field_key) + r"[ \t]*[:：][ \t]*([^\r\n]+)[ \t]*$"
    )
    m = pat_inline.search(body)
    if m:
        return m.group(1).strip()
    pat_heading = re.compile(r"(?im)^[ \t]*#+[ \t]*" + re.escape(field_key) + r"[ \t]*$")
    m = pat_heading.search(body)
    if m:
        for line in body[m.end():].splitlines():
            if line.strip():
                # 标题后第一个非空行若是另一节标题（# 开头）→ 本字段值为空
                if line.lstrip().startswith("#"):
                    return ""
                return line.strip()
    return ""


# 大节边界：# 或 ## 标题（### 及更深是内容子节，不截断）、或大写字段名
_SECTION_RE = re.compile(r"^[ \t]*(#{1,2}[ \t]+\S|[A-Z][A-Za-z /()\-]{2,40}[:：])")


def _read_multiline_field(body: str, field_key: str) -> str:
    """匹配 Objective / Acceptance（同行值或后续多行）。"""
    pat_inline = re.compile(
        r"(?im)^[ \t]*(?:#+[ \t]*)?(?:" + re.escape(field_key) + r")[ \t]*[:：][ \t]*(\S.*)$"
    )
    m = pat_inline.search(body)
    if m:
        return m.group(1).strip()
    pat_heading = re.compile(
        r"(?im)^[ \t]*(?:#+[ \t]*)?(?:" + re.escape(field_key) + r")[ \t]*[:：]?[ \t]*$"
    )
    m = pat_heading.search(body)
    if not m:
        return ""
    collected = []
    for line in body.splitlines()[body[: m.start()].count("\n") + 1:]:
        if line.strip() == "AAF_TASK_END":
            break
        if _SECTION_RE.match(line):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def parse_task_fields(task_text: str) -> dict[str, str]:
    """提取 TASK 字段（含可选字段；找不到 → 空字符串）。"""
    keys = tuple(dict.fromkeys(list(REQUIRED_FIELDS) + list(OPTIONAL_FIELDS)))
    fields = {key: "" for key in keys}
    for key in keys:
        if key in ("Objective", "Acceptance"):
            aliases = _FIELD_ALIASES.get(key, (key,))
            for alias in aliases:
                fields[key] = _read_multiline_field(task_text, alias)
                if fields[key]:
                    break
        else:
            fields[key] = _read_single_line_field(task_text, key)
    return fields


# ---------- 校验 ----------

def _task_id_errors(task_id: str) -> list[str]:
    """Task ID 最小安全规则：非空、无路径分隔符、无目录穿越、无绝对路径、无控制字符。"""
    errors = []
    if not task_id:
        errors.append("Task ID 为空")
        return errors
    if _PATH_SEPARATORS.search(task_id):
        errors.append("Task ID 包含路径分隔符（/ 或 \\）")
    if _DOTDOT.search(task_id):
        errors.append("Task ID 包含目录穿越（..）")
    if _ABSOLUTE_WINDOWS.match(task_id) or task_id.startswith("/"):
        errors.append("Task ID 是绝对路径")
    if _CONTROL_CHARS.search(task_id):
        errors.append("Task ID 包含控制字符")
    if any(c in task_id for c in ':?"*<>|'):
        errors.append("Task ID 包含非法文件名字符")
    return errors


def _workspace_errors(workspace: str) -> list[str]:
    """Workspace 基本校验：非空、可解析为路径、无控制字符/明显非法。"""
    errors = []
    if not workspace:
        errors.append("Workspace 为空")
        return errors
    if _CONTROL_CHARS.search(workspace):
        errors.append("Workspace 包含控制字符")
        return errors
    try:
        Path(workspace)
    except (ValueError, OSError):
        errors.append("Workspace 无法解析为路径")
    return errors


def validate_task_text(task_text: str) -> ValidationResult:
    """校验 TASK 文本：必填字段非空 + Task ID 安全 + Workspace（若存在）合法 +
    显式 Route fail-closed（FIX-004 Req 7/8/9）。"""
    fields = parse_task_fields(task_text)
    errors: list[str] = []

    missing = [key for key in REQUIRED_FIELDS if not fields[key]]
    if missing:
        errors.append("缺失必填字段: " + ", ".join(missing))

    errors.extend(_task_id_errors(fields["Task ID"]))
    # Workspace：CLI --workspace 已强制；TASK 文件内存在时才校验
    if fields["Workspace"]:
        errors.extend(_workspace_errors(fields["Workspace"]))

    # FIX-004 Req 7–9：显式 Route fail-closed——非法 agent / malformed syntax /
    # empty route / duplicate structure → Validation FAIL（不得回退 heuristic）；
    # 只有 TASK 完全没有 Route 字段（ABSENT）才允许 legacy inference。
    # 延迟 import 规避 router ↔ task_validation 的模块级循环依赖
    # （router 顶层 import parse_task_fields；调用时两模块均已加载完成）。
    from .router import RouteStatus, parse_explicit_route

    route_result = parse_explicit_route(task_text)
    if route_result.status is RouteStatus.INVALID:
        errors.append(f"非法显式 Route: {route_result.error or 'invalid route structure'}")

    return ValidationResult(valid=not errors, errors=errors)


def validate_task_file(task_file: Path) -> tuple[str, ValidationResult]:
    """读取并校验 TASK 文件；返回 (原文, ValidationResult)。"""
    task = task_file.read_text(encoding="utf-8")
    return task, validate_task_text(task)
