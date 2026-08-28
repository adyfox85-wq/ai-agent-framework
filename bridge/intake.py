"""AAF Bridge — TASK 提交流程决策（Phase F / TASK-006；纯逻辑可单测）。

将「剪贴板 TASK 文本 → 决策」从 tkinter 主流程中分离：
- plan_submission：只读决策（不写任何文件）。输出 SubmissionPlan（action + 全部 UI 字段）
- apply_submission：确认后的执行侧（切换持久化 + 落盘 TASK.md；由 main.py 在 UI 确认后调用）
- main.py 只负责：读剪贴板 → plan → UI 对话框 → apply → launcher.launch → 提示

决策规则（TASK req 1–13）：
- Workspace 以 canonical TASK Workspace 字段为准（req 1），不猜路径
- SAME → proceed（无额外确认，req 2）
- KNOWN → confirm_switch（明确显示当前/目标项目，req 3）
- UNKNOWN → confirm_unknown（fail-safe 暂停 + 明确确认，req 4）
- INVALID → reject + 明确原因，fail closed（req 5）
- launcher RUNNING：目标 workspace 不同 → reject（req 7：不跨 workspace 混跑；
  明确提示当前任务正在运行）；相同 workspace 的新任务 → proceed，由 launcher
  既有并发保护拒绝第二 runner（既有 contract，不另造架构）
- duplicate：running → reject 不启动第二份 runner（req 9）；
  completed/abnormal/unknown → reject + 状态卡片（req 8/10：不覆盖 artifacts，
  需新 Task ID；不另造 rerun 架构）
- 本模块不改写 Task ID / Workspace / canonical terminal / 历史 artifacts（req 12）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg_mod
from . import duplicate as dup_mod
from . import task_io
from . import workspace as ws_mod
from .launch_registry import ACTIVE_STATES, list_launches

ACTION_PROCEED = "proceed"
ACTION_CONFIRM_SWITCH = "confirm_switch"
ACTION_CONFIRM_UNKNOWN = "confirm_unknown"
ACTION_REJECT = "reject"

VALID_ACTIONS = (ACTION_PROCEED, ACTION_CONFIRM_SWITCH, ACTION_CONFIRM_UNKNOWN, ACTION_REJECT)

# 必填字段（与 task_io.validate_task_text 同源，中文 label 一致）
_REQUIRED_FIELDS = (
    ("task_id", "Task ID"),
    ("task_name", "Task Name"),
    ("workspace", "Workspace"),
    ("objective", "Objective"),
    ("acceptance", "Acceptance"),
)


@dataclass
class SubmissionPlan:
    """提交流程决策结果（只读事实；UI 据此渲染确认窗/错误/卡片）。"""

    action: str = ACTION_PROCEED  # proceed / confirm_switch / confirm_unknown / reject
    reasons: list[str] = field(default_factory=list)  # reject 原因（中文）
    task_id: str = ""
    task_name: str = ""
    workspace: str = ""  # TASK 声明（canonical 来源）
    task_text: str = ""  # 含 BEGIN/END 标记的完整正文（apply 落盘用）
    current_project: str = ""
    current_workspace: str = ""
    target_project: str = ""  # 目标项目展示名
    is_known: bool = False
    is_same: bool = False
    switch_workspace: bool = False  # 确认后需持久化切换
    running_blocked: bool = False  # 当前任务 RUNNING 导致拒绝切换
    running_task_id: str | None = None
    duplicate: dup_mod.DuplicateInfo | None = None

    @property
    def is_reject(self) -> bool:
        return self.action == ACTION_REJECT


def _active_registry_launches() -> list[dict]:
    """registry 全部活跃（PREPARED/RUNNING）launch（跨 workspace；只读）。"""
    try:
        return [e for e in list_launches() if e.get("state") in ACTIVE_STATES]
    except Exception:  # noqa: BLE001 —— registry 不可读不阻断：fail 方向是「多查一次状态」
        return []


def plan_submission(text: str, cfg: dict, launcher=None, cfg_path: Path | None = None) -> SubmissionPlan:
    """只读决策：TASK 文本 → SubmissionPlan。不写任何文件。

    launcher 需暴露 .state（IDLE/RUNNING…）与 .current（RunInfo | None，含 .task_id）。
    传 None 或属性缺失视为无运行中任务（测试/复用场景）。
    cfg_path：config.json 路径（默认 CONFIG_PATH；测试注入隔离目录）。
    """
    plan = SubmissionPlan(current_project=str(cfg.get("current_project") or ""),
                          current_workspace=str(cfg.get("current_workspace") or "").strip())

    # 1) 解析（marker / 字段）
    try:
        body = task_io.extract_task_body(text)
    except task_io.TaskParseError as e:
        plan.action = ACTION_REJECT
        plan.reasons.append(str(e))
        return plan
    fields = task_io.parse_task(body)
    plan.task_id = fields.get("task_id", "")
    plan.task_name = fields.get("task_name", "")
    plan.workspace = fields.get("workspace", "").strip()
    plan.task_text = f"{task_io.BEGIN_MARKER}\n{body}\n{task_io.END_MARKER}"

    # 2) 必填字段 / 不安全文件名（与 task_io 同规则，workspace 匹配除外——Phase F 改为切换流程）
    for name, label in _REQUIRED_FIELDS:
        if not fields.get(name):
            plan.reasons.append(f"缺少必填字段: {label}")
    if plan.task_id and task_io._UNSAFE_FILENAME_RE.search(plan.task_id):
        plan.reasons.append(f"Task ID 包含不安全文件名字符: {plan.task_id}")
    if plan.reasons:
        plan.action = ACTION_REJECT
        return plan

    # 3) Workspace 校验（fail closed：不合规即拒绝，不自动修复成其它路径）
    ok, reason = ws_mod.check_workspace(plan.workspace)
    if not ok:
        plan.action = ACTION_REJECT
        plan.reasons.append(reason)
        return plan

    # 4) Workspace 分类
    known_ws = cfg_mod.known_workspaces(cfg_path)
    cls = ws_mod.classify_workspace(plan.workspace, plan.current_workspace, known_ws)
    plan.is_same = cls == ws_mod.SAME
    plan.is_known = cls in (ws_mod.SAME, ws_mod.KNOWN)
    if cls == ws_mod.KNOWN:
        plan.action = ACTION_CONFIRM_SWITCH
        plan.switch_workspace = True
    elif cls == ws_mod.UNKNOWN:
        plan.action = ACTION_CONFIRM_UNKNOWN
        plan.switch_workspace = True
    else:
        plan.action = ACTION_PROCEED
    plan.target_project = ws_mod.target_project_name(
        plan.workspace, plan.current_project, plan.current_workspace, cfg.get("recent_projects") or []
    )

    # 5) Running Task 保护（req 7）：RUNNING 时不得为切换而跨 workspace
    running = launcher is not None and getattr(launcher, "state", "IDLE") == "RUNNING"
    running_task_id = None
    if running:
        cur = getattr(launcher, "current", None)
        running_task_id = getattr(cur, "task_id", None) if cur is not None else None
        plan.running_task_id = running_task_id
        if not (plan.current_workspace and cfg_mod.same_workspace(plan.workspace, plan.current_workspace)):
            plan.action = ACTION_REJECT
            plan.running_blocked = True
            plan.reasons.append(
                f"当前任务正在运行（Task ID: {running_task_id or '未知'}）："
                f"不能切换项目，不得跨 workspace 混跑。"
                f"请等待当前任务结束后再提交。"
            )
            return plan

    # 6) Duplicate 检测（canonical TASK.md 存在性；registry 活跃 + launcher 当前任务）
    active = _active_registry_launches()
    launcher_cur_tid = running_task_id if running else None
    dup_info = dup_mod.inspect_duplicate(plan.task_id, plan.workspace, active, launcher_cur_tid)

    if dup_info is not None:
        plan.duplicate = dup_info
        if dup_info.kind == dup_mod.KIND_RUNNING:
            plan.action = ACTION_REJECT
            plan.reasons.append(
                f"同 Task ID 正在运行（{dup_info.task_id}）：不启动第二份 runner，"
                f"不创建并行重复 execution（req 9）。请等待其结束后再提交。"
            )
        else:
            # completed / abnormal / unknown：既有 contract 不允许 rerun → 明确拒绝，
            # 说明需新 Task ID；不另造 rerun 架构（req 10/12）
            plan.action = ACTION_REJECT
            plan.reasons.append(
                f"{dup_info.reason}——本次提交未写入任何文件，历史 artifacts 未被覆盖。"
            )
        return plan

    # 7) 无 duplicate：按 workspace 分类放行
    return plan


def apply_submission(plan: SubmissionPlan, cfg_path: Path | None = None) -> Path:
    """确认后执行：切换持久化（如需）→ 落盘 TASK.md → 返回 target 路径。

    - 切换持久化唯一入口 = config.update_project（设计 §9.2.5）
    - 落盘沿用 task_io.save_task（TASK_ALREADY_EXISTS 兜底保护仍在，绝不放宽）
    - 调用方（main.py）须在 UI 确认后调用；本函数不负责 UI/launcher
    """
    if plan.switch_workspace:
        cfg_mod.update_project(plan.target_project, plan.workspace, cfg_path)
    target = task_io.save_task(plan.task_text, plan.workspace, plan.task_id)
    return target
