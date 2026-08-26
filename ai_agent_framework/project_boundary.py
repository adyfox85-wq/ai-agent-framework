"""AI Agent Framework — 最小、正式、确定性 Project Boundary Control。

职责：
- 读取正式 PROJECT_SCOPE.md（<ws>/PROJECT_SCOPE.md 或 <ws>/docs/PROJECT_SCOPE.md）
- 结构化表达：Core Goal / Current Scope / Frozen Boundaries / Approved Extensions / Backlog
- Task Boundary Check（WARNING-FIRST；显式 frozen path 命中 → HIGH）
- 写 boundary.json（机器状态，不污染 Lifecycle 核心状态）

边界：
- 不调用 LLM / Agent；确定性规则
- 不自动修改 PROJECT_SCOPE；不自动加入 Backlog
- 不改变 Validation / Router / Lifecycle 职责

职责分离：
- Validation：格式是否合法
- Boundary：是否存在范围风险（warning-first，默认不阻断）
- Router：Agent 路径
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

BOUNDARY_NOT_CONFIGURED = "BOUNDARY_NOT_CONFIGURED"
BOUNDARY_CHECK_ERROR = "BOUNDARY_CHECK_ERROR"

SEVERITY_NONE = "NONE"
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"

SCOPE_FILENAMES = ("PROJECT_SCOPE.md", "docs/PROJECT_SCOPE.md")

# 中英 section 标题别名
_SECTIONS = {
    "core_goal": ("Core Goal", "核心目标", "项目定位"),
    "current_scope": ("Current Scope", "当前范围", "范围内"),
    "frozen_boundaries": ("Frozen Boundaries", "Frozen Boundaries / Non-goals", "冻结边界", "不在范围内", "Non-goals"),
    "approved_extensions": ("Approved Extensions", "已批准扩展"),
    "backlog": ("Backlog", "Future Ideas", "Backlog / Future Ideas", "待办", "未来想法"),
    "last_updated": ("Last Updated", "最后更新"),
}

_UNKNOWN = "UNKNOWN"
UNKNOWN = _UNKNOWN  # 公开别名（Session 集成复用）


class BoundaryError(RuntimeError):
    """Boundary 模块错误（fail-open：调用方记录 warning 不阻断执行）。"""


# ---------- 确定性 Markdown section parser ----------

def _section_items(text: str, *headings: str) -> list[str]:
    """提取指定标题下的条目（- 列表 / 数字列表 / 纯文本行）；无 → []。"""
    pat = re.compile(
        r"(?im)^[ \t]*(?:#{1,4}[ \t]+)(?:" + "|".join(re.escape(h) for h in headings) + r")[ \t]*$"
    )
    m = pat.search(text)
    if not m:
        return []
    items = []
    for line in text[m.end():].splitlines():
        if re.match(r"^[ \t]*#{1,4}[ \t]+\S", line):
            break
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[-*•]\s*", "", s)
        s = re.sub(r"^\d+[.)]\s*", "", s)
        s = s.strip("`")
        if s:
            items.append(s)
    return items


def _first_value(items: list[str]) -> str:
    return items[0] if items else _UNKNOWN


def parse_boundary(text: str, source_path: str | None = None) -> ProjectBoundary:
    """确定性解析 PROJECT_SCOPE 文本 → ProjectBoundary。"""
    core_goal = _first_value(_section_items(text, *_SECTIONS["core_goal"]))
    current_scope = _section_items(text, *_SECTIONS["current_scope"])
    frozen = _section_items(text, *_SECTIONS["frozen_boundaries"])
    extensions = _section_items(text, *_SECTIONS["approved_extensions"])
    backlog = _section_items(text, *_SECTIONS["backlog"])
    return ProjectBoundary(
        core_goal=core_goal,
        current_scope=current_scope,
        frozen_boundaries=frozen,
        approved_extensions=extensions,
        backlog=backlog,
        source_path=source_path,
        configured=True,
    )


def _scope_file_candidates(workspace: Path) -> list[Path]:
    return [workspace / name for name in SCOPE_FILENAMES]


def load_boundary(workspace: Path | str, scope_file: Path | str | None = None) -> ProjectBoundary:
    """读取正式 PROJECT_SCOPE。缺失/不可读 → configured=False（不崩溃）。"""
    ws = Path(workspace)
    candidates = [Path(scope_file)] if scope_file is not None else _scope_file_candidates(ws)
    for cand in candidates:
        if cand.is_file():
            try:
                text = cand.read_text(encoding="utf-8")
            except OSError as exc:
                return ProjectBoundary(configured=False, source_path=str(cand), parse_error=str(exc))
            return parse_boundary(text, source_path=str(cand))
    return ProjectBoundary(configured=False, source_path=None)


# ---------- Task Boundary Check（warning-first） ----------

_NEG_PREFIX = re.compile(r"^(不|不要|禁止|别|勿|Do not|Don't|Never)[\s修改重写改触碰动]*", re.IGNORECASE)


def _normalize(item: str) -> str:
    """剥离常见否定前缀（不修改/不重写 → 修改/重写），用于子串匹配。"""
    return _NEG_PREFIX.sub("", item).strip()


def _frozen_path_tokens(boundary: ProjectBoundary) -> list[str]:
    """从 Frozen Boundaries 提取路径 token（含 / 或 \ 的路径片段）。"""
    tokens = []
    for item in boundary.frozen_boundaries:
        for seg in re.findall(r"[\w.\-]+(?:[/\\][\w.\-]+)+[/\\]?", item):
            tokens.append(seg.strip().strip("`").rstrip("/\\"))
    return tokens


def _task_field_text(task_text: str, field: str) -> str:
    """提取 TASK 指定字段文本（Objective/Requirements/Scope/Files/Background...）。"""
    pat = re.compile(r"(?im)^[ \t]*#+[ \t]*" + re.escape(field) + r"[ \t]*$")
    m = pat.search(task_text)
    if not m:
        return ""
    out = []
    for line in task_text[m.end():].splitlines():
        if re.match(r"^[ \t]*#{1,4}[ \t]+\S", line):
            break
        out.append(line.strip())
    return " ".join(out)


def check_task(boundary: ProjectBoundary, task_text: str) -> BoundaryCheckResult:
    """确定性边界检查。

    规则：
    1. 未配置边界 → configured=False，无 warning（BOUNDARY_NOT_CONFIGURED 语义）
    2. TASK 文本显式引用 frozen path → severity=HIGH + warning
    3. TASK 文本含 frozen boundary 短语（非路径）→ severity=MEDIUM + warning
    4. 否则 → severity=NONE
    只做子串/exact match；不做语义判断；默认不阻断 Router。
    """
    now = datetime.now().isoformat(timespec="seconds")
    if not boundary.configured:
        return BoundaryCheckResult(configured=False, warnings=[], matched_boundaries=[], severity=SEVERITY_NONE, checked_at=now)

    # 组合任务字段（Objective/Requirements/Scope/Files/Background）
    parts = []
    for fld in ("Objective", "Requirements", "Scope", "Files", "Background"):
        v = _task_field_text(task_text, fld)
        if v:
            parts.append(fld + ": " + v)
    combined = "\n".join(parts)

    warnings: list[str] = []
    matched: list[str] = []
    path_hits: list[str] = []

    # 1) 显式 frozen path 命中 → HIGH（仅真实路径 token：workbuddy_skills/skills 等）
    path_tokens = _frozen_path_tokens(boundary)
    for token in path_tokens:
        if token and token in combined:
            warnings.append(f"Task explicitly references frozen path: {token}")
            matched.append(token)
            path_hits.append(token)

    # 2) frozen boundary 短语命中（非真实路径）→ MEDIUM
    #    支持 " / " 分隔的多概念条目（如 不修改 Hermes 配置 / WorkBuddy 配置）
    for item in boundary.frozen_boundaries:
        for part in re.split(r"\s*/\s*", item):
            norm = _normalize(part)
            if len(norm) < 4:
                continue
            if any(t in norm for t in path_tokens):
                continue  # 含真实路径 → 已按 HIGH 处理
            if norm in combined:
                warnings.append(f"Task references frozen boundary: {part}")
                matched.append(norm)

    if path_hits:
        severity = SEVERITY_HIGH
    elif warnings:
        severity = SEVERITY_MEDIUM
    else:
        severity = SEVERITY_NONE
    return BoundaryCheckResult(
        configured=True,
        warnings=warnings,
        matched_boundaries=matched,
        severity=severity,
        checked_at=now,
    )


def write_boundary_json(output_dir: Path | str, task_id: str, result: BoundaryCheckResult, source_path: str | None) -> Path:
    """写 <output_dir>/boundary.json（机器状态）。原子写，避免部分损坏。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": task_id,
        "configured": result.configured,
        "severity": result.severity,
        "warnings": result.warnings,
        "matched_boundaries": result.matched_boundaries,
        "checked_at": result.checked_at,
        "source_path": source_path,
    }
    path = out / "boundary.json"
    tmp = out / "boundary.json.tmp"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise BoundaryError(f"boundary.json 写入失败: {path} ({exc})") from exc
    return path


@dataclass
class ProjectBoundary:
    core_goal: str = _UNKNOWN
    current_scope: list[str] = field(default_factory=list)
    frozen_boundaries: list[str] = field(default_factory=list)
    approved_extensions: list[str] = field(default_factory=list)
    backlog: list[str] = field(default_factory=list)
    source_path: str | None = None
    configured: bool = False
    parse_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "core_goal": self.core_goal,
            "current_scope": self.current_scope,
            "frozen_boundaries": self.frozen_boundaries,
            "approved_extensions": self.approved_extensions,
            "backlog": self.backlog,
            "source_path": self.source_path,
            "configured": self.configured,
            "parse_error": self.parse_error,
        }


@dataclass
class BoundaryCheckResult:
    configured: bool
    warnings: list[str]
    matched_boundaries: list[str]
    severity: str
    checked_at: str

    def to_dict(self) -> dict:
        return {
            "configured": self.configured,
            "warnings": self.warnings,
            "matched_boundaries": self.matched_boundaries,
            "severity": self.severity,
            "checked_at": self.checked_at,
        }
