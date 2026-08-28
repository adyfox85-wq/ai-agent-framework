"""AAF Bridge — Phase C 正式状态窗口（中文优先、只读观察界面）。

信息架构（冻结设计 §3 / §12.1 wireframe）：
- Bridge / Project 区：当前项目 / Bridge 状态 / 热键 / Workspace
- Current Task 区：Task ID / Task Name / 当前阶段 / 当前 Agent /
  已运行（elapsed）/ 最近活动 / 整体结果 / 整体进度（估算百分比 + 进度条）/
  当前阶段占比 / suspected-stuck 提示
- Stage Strip：Validation / Boundary / Hermes / WorkBuddy / Codex / Report
  （✓ 已完成 / ▶ 进行中 / ○ 未开始 / ⏸ 等待处理 / ✗ 失败；进行中阶段高亮）
- 操作：查看日志 / 查看任务目录 / 关闭 / 重启 Bridge / 退出 AAF

Phase D（进度可视化）：
- 进度估算纯函数在 bridge/progress.py（权重表集中定义，设计 §4.2）
- suspected-stuck 观察纯函数在 bridge/stuck.py（设计 §5.2，只提示不改状态）
- 进度条为只读估算展示，不写任何 canonical artifact

Core / UI 边界（设计 §14）：
- 只读观察：读 task.json（经 runtime_state reader）/ route.json / boundary.json /
  REPORT.md / last_run.json / config.json / launcher 内存状态；
  绝不写 task.json / run.json / route.json / boundary.json / REPORT.md
- 不复制 Router / Runner / Lifecycle / Agent 逻辑
- Phase E：CANCELLED 作为合法终态已进入状态映射（§11.1 CANCELLED → 已取消）与
  进度收敛（§4.1.5 停在取消时刻权重和）
- Phase E / TASK-005-C（本文件主体）：Status Window Cancel UX
  - [停止当前任务]：只写 cancel.request（§6.1 控制代理契约，经 Core-owned
    cancel 模块原子写 + state.lock 序列化）；**UI 绝不直接写任何 terminal 状态**
  - [强制停止]：只有 backend（launcher.force_eligible）明确返回 force eligible
    才显示/启用（req 6）；点击后必须第二次明确中文确认（req 4/5），才调用
    launcher.request_force_cancel（verified ownership + 进程树终止 + 结构化
    force evidence + Core recovery finalizer；§6B.17）
  - CANCEL_REQUESTED / CANCELLING 等中间态**只属于 UI/control 状态**（§6A.3），
    绝不进入 task.json 合法 status 集合（VALID_STATUSES 不变）
  - canonical terminal 是最终结果来源：任务先完成 vs 取消请求竞争 → UI 跟随
    canonical（任务已先完成 / 已取消），不猜测（req 8）
  - 窗口/重启后从 canonical artifacts + cancel.request + registry 恢复 UI 状态，
    不依赖 UI 内存（req 9）
- 不实现 Phase F（项目切换 / Duplicate UX）；stuck 仅提示，不做 definitive
  dead-runner 判定（RW-020 边界）

本模块可脱离 tkinter 主循环单测（纯函数部分）；窗口与控制器在主线程使用。
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from . import config as cfg_mod
from . import launch_registry as reg_mod
from . import task_io
from . import progress as progress_mod
from . import stuck as stuck_mod
from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import runtime_health as runtime_health_mod
from ai_agent_framework import runtime_state as runtime_state_mod
from ai_agent_framework.task_lifecycle import TERMINAL_STATUSES

REFRESH_INTERVAL_MS = 1000  # 刷新频率：约 1 秒（只读轻量刷新，TASK req 16）

UNKNOWN = "—"

# 进度条宽度（Phase D；仅展示，不写任何 artifact）
PROGRESS_BAR_WIDTH = 200

# 当前进行中阶段高亮底色（Phase D req 6：允许附加当前阶段高亮）
STAGE_RUNNING_BG = "#dce9ff"

# 六阶段条（设计 §3；COMPLETED 是终态标记，不属于阶段条）
STAGE_ORDER = ("VALIDATION", "BOUNDARY", "HERMES", "WORKBUDDY", "CODEX", "REPORT")

STAGE_DISPLAY = {
    "VALIDATION": "Validation",
    "BOUNDARY": "Boundary",
    "HERMES": "Hermes",
    "WORKBUDDY": "WorkBuddy",
    "CODEX": "Codex",
    "REPORT": "Report",
    "COMPLETED": "已完成",
}

# 生命周期状态 → 中文（设计 §11.1；CANCELLED 为 Phase E 合法终态，§11.1 文案表已定义）
STATUS_LABELS = {
    "CREATED": "已创建",
    "RUNNING": "执行中",
    "WAITING": "等待处理",
    "SUCCESS": "已完成",
    "FAILED": "执行失败",
    "CANCELLED": "已取消",
}

# Bridge 侧收尾分类 → 中文（task.json 缺失时的兜底展示；不是 lifecycle 终态裁决）
# CANCELLED：launcher 读取 canonical terminal 后跟随的 Bridge 侧分类（§6A.5）
LAUNCHER_RESULT_LABELS = {
    "FINISHED": "已完成",
    "FAILED": "执行失败",
    "REPORT_NOT_FOUND": "未找到报告",
    "FAILED_TO_START": "启动失败",
    "CANCELLED": "已取消",
}

# ---------------------------------------------------------------------------
# Phase E / TASK-005-C：Stop / Cancel UX 状态机（UI/control 态；§6A.3）
# ---------------------------------------------------------------------------
# 这些状态**只属于 Status Window / Launcher 控制语义**（§6A.3 最小中间状态：
# CANCEL_REQUESTED / CANCELLING 允许作为 UI/内存态 + control.json 字段），
# **绝不写入 task.json**（VALID_STATUSES 不变；terminal 只有 CANCELLED）。
#
# 推导只依赖 canonical artifacts（task.json / cancel.request / launch registry /
# force eligibility backend），不依赖 UI 内存——窗口/重启后从 artifacts 恢复（req 9）。
#
# 状态表（req 2 至少区分：正在运行 / 请求停止 / 正在取消 / 已取消 / 已完成 /
# 停止失败 / 无法安全停止）：
#   RUNNING        正在运行    可停止（无 cancel.request 的非终态任务）
#   STOP_REQUESTED 请求停止    停止请求已发送，正在等待任务安全退出（软取消窗口内）
#   CANCELLING     正在取消    软取消超时任务仍未退出 → 提供 [强制停止]（force eligible 时）
#   CANCELLED      已取消      canonical terminal = CANCELLED
#   COMPLETED      已完成      其他 canonical terminal（曾有请求 → 任务已先完成）
#   STOP_UNSAFE    无法安全停止 force 不可用（ownership UNCERTAIN/STALE 等）→ 不提供 Force
#   UNKNOWN        无法确认    任务状态不可验证 → 不提供 Stop（req 1：不可验证不提供误导 Stop）
CANCEL_UI_RUNNING = "RUNNING"
CANCEL_UI_STOP_REQUESTED = "STOP_REQUESTED"
CANCEL_UI_CANCELLING = "CANCELLING"
CANCEL_UI_CANCELLED = "CANCELLED"
CANCEL_UI_COMPLETED = "COMPLETED"
CANCEL_UI_STOP_UNSAFE = "STOP_UNSAFE"
CANCEL_UI_UNKNOWN = "UNKNOWN"

# 用户反馈文案（req 10：中文、不裸露 technical internal states 为主要文案）
MSG_STOP_SENT = "停止请求已发送，正在等待任务安全退出"
MSG_WAITING_EXIT = "停止请求已发送，正在等待任务安全退出"
MSG_FORCE_OPTION = "任务仍未退出，可选择强制停止"
MSG_FORCE_CONFIRM = "强制停止确认"
MSG_CANCELLED = "任务已取消"
MSG_COMPLETED_FIRST = "任务已先完成（取消请求已被吸收）"
MSG_COMPLETED = "任务已完成"
MSG_UNSAFE_FORCE = "无法安全强制停止：当前无法确认任务状态（可能已结束或无法安全终止）"
MSG_STOP_CONFIRM = "停止确认"

# 非终态（等待软取消收敛 / 未发请求）时显示的用户文案（防止暴露原始技术原因）
_CANCEL_UI_LABELS = {
    CANCEL_UI_RUNNING: "正在运行",
    CANCEL_UI_STOP_REQUESTED: "请求停止",
    CANCEL_UI_CANCELLING: "正在取消",
    CANCEL_UI_CANCELLED: "已取消",
    CANCEL_UI_COMPLETED: "已完成",
    CANCEL_UI_STOP_UNSAFE: "无法安全停止",
    CANCEL_UI_UNKNOWN: "无法确认",
}


@dataclass(frozen=True)
class CancelUi:
    """Status Window 的 Stop / Cancel UX 状态（UI/control 态，绝不写入 task.json）。

    - state：CANCEL_UI_* 代码（§6A.3 最小中间状态；非 task.json status）
    - label / message：中文用户文案（req 10；technical detail 只进 force_detail）
    - can_stop / can_force：按钮可用性（req 1/6——只有 backend 明确 eligible 才 True）
    - force_detail：force 不可用时的诊断原因（次要信息，不裸露为主要文案）
    """

    state: str
    label: str
    message: str
    can_stop: bool = False
    can_force: bool = False
    force_detail: str = ""


def _force_detail_cn(detail: str | None) -> str:
    """backend force eligibility 原因 → 中文摘要（技术代码保留在括号内作诊断）。"""
    if not detail:
        return ""
    d = str(detail)
    if d.startswith("OWNERSHIP_") or d.startswith("REGISTRY_") or "STALE" in d or "UNCERTAIN" in d:
        return f"任务状态无法安全确认（{d[:120]}）"
    if d.startswith("NO_ACTIVE_LAUNCH"):
        return "找不到该任务的启动记录"
    if d.startswith("NO_SOFT_CANCEL_REQUEST"):
        return "未找到有效的取消请求"
    if d.startswith("SOFT_CANCEL_TIMEOUT_NOT_REACHED"):
        return "仍在等待任务安全退出"
    if d.startswith("CANCEL_REQUEST"):
        return "取消请求无效或异常"
    return d[:200]


def derive_cancel_ui(
    *,
    runtime_status: str | None,
    has_cancel_request: bool,
    request_age: float | None,
    soft_timeout: float,
    force_eligible: bool | None = None,
    force_detail: str | None = None,
) -> CancelUi:
    """纯函数：由 canonical 事实推导 Stop / Cancel UX 状态（无副作用、无 UI 内存）。

    规则（req 7/8：canonical terminal 优先；UI 不裁决）：
    - canonical terminal = CANCELLED → 已取消（无论 cancel.request 是否残留）
    - canonical terminal = SUCCESS/WAITING/FAILED → 已完成；若曾有取消请求 →
      「任务已先完成」（late cancel absorbed，req 8）
    - 无 canonical（不可验证）→ 不提供 Stop（req 1）
    - 非终态 + 无 cancel.request → 正在运行（可停止）
    - 非终态 + 有请求 + 软取消窗口内 → 请求停止（等待安全退出；不提供 Force）
    - 非终态 + 有请求 + 超时：force eligible（backend 明确返回）→ 正在取消 +
      [强制停止]；否则 → 无法安全停止（fail closed，req 5/6）
    """
    if runtime_status is None:
        return CancelUi(CANCEL_UI_UNKNOWN, _CANCEL_UI_LABELS[CANCEL_UI_UNKNOWN], "", False, False, "")
    if runtime_status == "CANCELLED":
        return CancelUi(CANCEL_UI_CANCELLED, _CANCEL_UI_LABELS[CANCEL_UI_CANCELLED], MSG_CANCELLED, False, False, "")
    if runtime_status in TERMINAL_STATUSES:
        msg = MSG_COMPLETED_FIRST if has_cancel_request else MSG_COMPLETED
        return CancelUi(CANCEL_UI_COMPLETED, _CANCEL_UI_LABELS[CANCEL_UI_COMPLETED], msg, False, False, "")
    # 非终态（RUNNING / CREATED …）
    if not has_cancel_request:
        return CancelUi(CANCEL_UI_RUNNING, _CANCEL_UI_LABELS[CANCEL_UI_RUNNING], "", True, False, "")
    if request_age is None or request_age < soft_timeout:
        return CancelUi(
            CANCEL_UI_STOP_REQUESTED, _CANCEL_UI_LABELS[CANCEL_UI_STOP_REQUESTED],
            MSG_WAITING_EXIT, False, False, "",
        )
    # soft timeout 已到，任务仍未退出（req 4：不自动 kill；UI 明确说明 + 提供 Force）
    if force_eligible:
        return CancelUi(
            CANCEL_UI_CANCELLING, _CANCEL_UI_LABELS[CANCEL_UI_CANCELLING],
            MSG_FORCE_OPTION, False, True, "",
        )
    return CancelUi(
        CANCEL_UI_STOP_UNSAFE, _CANCEL_UI_LABELS[CANCEL_UI_STOP_UNSAFE],
        MSG_UNSAFE_FORCE, False, False, _force_detail_cn(force_detail),
    )


def collect_cancel_ui(
    launcher,
    task_id: str,
    output_dir: Path | None,
    runtime_status: str | None,
    *,
    soft_timeout: float | None = None,
) -> CancelUi | None:
    """从真实 artifacts 收集 Cancel UI 事实（只读；force eligibility 经 launcher backend）。

    - 无 launcher / 无任务 / 无输出目录 → None（不提供 Stop）
    - runtime_status 为 None（canonical 缺失/不可验证）→ UNKNOWN（不提供 Stop）
    - cancel.request 存在 → 计算请求年龄；软取消超时后才询问 backend
      force_eligible（backend 明确返回 True 才允许 Force，req 6），且 force
      可用时再经 launcher.ownership_status 确认 ownership VERIFIED/REAUTHENTICATED
      ——UNCERTAIN / STALE / mismatch → 不提供 Force（fail closed）
    """
    if launcher is None or not task_id or output_dir is None:
        return None
    if runtime_status is None:
        return CancelUi(CANCEL_UI_UNKNOWN, _CANCEL_UI_LABELS[CANCEL_UI_UNKNOWN], "", False, False, "")
    req, _warning = cancel_mod.inspect_cancel_request(output_dir)
    has_req = req is not None
    age: float | None = None
    if req is not None:
        # FIX-001（005-C-FIX-001）：elapsed 统一走 canonical UTC/aware contract——
        # 合法 offset-aware（+08:00 / +00:00 / Z）与 legacy naive 均正确换算，
        # malformed → None（fail closed：不产生 force eligibility）。
        age = cancel_mod.requested_at_elapsed_seconds(req.requested_at)
    timeout = soft_timeout
    if timeout is None:
        timeout = float(cfg_mod.load_config().get("force_cancel_soft_timeout", 30.0))
    eligible: bool | None = None
    why: str | None = None
    if runtime_status not in TERMINAL_STATUSES and has_req and age is not None and age >= timeout:
        try:
            eligible, why = launcher.force_eligible(task_id)
            if eligible:
                # req 6：force 只对 backend 明确验证过 ownership 的 launch 提供
                # （UNCERTAIN / STALE / mismatch → 不显示/不启用 Force，fail closed）。
                # ownership_status 是 launcher 只读诊断 API（TASK-005-B req 31）。
                if hasattr(launcher, "ownership_status"):
                    verdict = launcher.ownership_status(task_id)
                    if verdict is None or not verdict.ok():
                        vresult = getattr(verdict, "result", "NO_VERDICT")
                        eligible = False
                        why = f"OWNERSHIP_{vresult}: force eligibility 需要 verified ownership"
        except Exception as exc:  # noqa: BLE001 —— backend 检查失败 → fail closed 不提供 Force
            eligible, why = False, f"force eligibility 检查失败: {type(exc).__name__}: {exc}"
    return derive_cancel_ui(
        runtime_status=runtime_status,
        has_cancel_request=has_req,
        request_age=age,
        soft_timeout=timeout,
        force_eligible=eligible,
        force_detail=why,
    )

# Bridge 健康 → 中文（与 bridge/main.py 的展示层一致；状态码仍是技术字段）
HEALTH_LABELS = {"OK": "正常运行", "DEGRADED": "异常"}

# Agent 显示名（技术字段保留英文原值；null → —）
AGENT_LABELS = {"hermes": "Hermes", "workbuddy": "WorkBuddy", "codex": "Codex"}

# 阶段状态 → (符号, 中文)（设计 §3 词汇表；SKIPPED 按未开始显示）
PHASE_STATE_DISPLAY = {
    "PENDING": ("○", "未开始"),
    "RUNNING": ("▶", "进行中"),
    "SUCCESS": ("✓", "已完成"),
    "WAITING": ("⏸", "等待处理"),
    "FAILED": ("✗", "失败"),
    "SKIPPED": ("○", "未开始"),
}

_FONT_BOLD = ("Segoe UI", 9, "bold")
_FONT_NORMAL = ("Segoe UI", 9)


# ---------------------------------------------------------------------------
# 纯函数：映射与格式化（可单测）
# ---------------------------------------------------------------------------


def overall_status_label(status: str | None) -> str:
    """lifecycle status → 中文。未知/缺失 → —。"""
    if not status:
        return UNKNOWN
    return STATUS_LABELS.get(status, UNKNOWN)


def agent_label(agent: str | None) -> str:
    """agent → 显示名：hermes→Hermes / workbuddy→WorkBuddy / codex→Codex / 空→—。"""
    if not agent:
        return UNKNOWN
    return AGENT_LABELS.get(agent.lower(), agent)


def stage_state_label(state: str | None) -> tuple[str, str]:
    """阶段状态 → (符号, 中文)。缺失→未开始；未知原始值→未知。"""
    if not state:
        return ("○", "未开始")
    return PHASE_STATE_DISPLAY.get(state, ("○", "未知"))


def stage_display_name(stage: str | None) -> str:
    """阶段名 → 展示名（技术名保留英文；COMPLETED→已完成；缺失→—）。"""
    if not stage:
        return UNKNOWN
    return STAGE_DISPLAY.get(stage, stage)


def format_elapsed(seconds: float | None) -> str:
    """elapsed 文本（事实时间差，无 ETA / 预测）：12分34秒 / 1小时5分 / —。"""
    if seconds is None:
        return UNKNOWN
    s = max(0, int(seconds))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


def format_last_activity(iso: str | None, now: datetime | None = None) -> str:
    """最近活动相对时间：刚刚 / 2分钟前 / 3小时前 / 2天前；缺失或非法 → —。"""
    if not iso:
        return UNKNOWN
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return UNKNOWN
    now = now or datetime.now()
    seconds = max(0, (now - dt).total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)}分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)}小时前"
    return f"{int(seconds // 86400)}天前"


# ---------------------------------------------------------------------------
# 纯函数：阶段条（事实映射，UI cannot guess）
# ---------------------------------------------------------------------------


def read_route_agents(output_dir: Path | str | None) -> list[str] | None:
    """读 route.json 的 agents 列表；缺失/损坏 → None（不猜测）。"""
    if output_dir is None:
        return None
    p = Path(output_dir) / "route.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        agents = data.get("agents")
        if isinstance(agents, list):
            return [str(a) for a in agents]
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return None


def stage_states(runtime, output_dir, route_agents) -> dict[str, str]:
    """六阶段条状态映射（事实优先：phases → legacy 产物存在性）。

    返回 {stage: phase_state}，phase_state ∈ VALID_PHASE_STATES。
    不读取 run.json 作为运行期状态；不实现 Phase D 估算。
    """
    phases = runtime.phases if runtime is not None else {}
    out = Path(output_dir) if output_dir is not None else None
    result = {}
    for stage in STAGE_ORDER:
        entry = phases.get(stage)
        if isinstance(entry, dict) and entry.get("state"):
            result[stage] = entry["state"]
        else:
            result[stage] = _stage_state_fallback(stage, runtime, out, route_agents)
    return result


def _stage_state_fallback(stage: str, runtime, out: Path | None, route_agents) -> str:
    """无 phases 记录时的 legacy 兼容映射（冻结设计 §3 文件存在性映射）。

    - VALIDATION：task.json 存在 ⇒ Validation 已通过（Validation 失败不产生任何 artifact）
    - BOUNDARY：boundary.json 存在 ⇒ 完成；任务 RUNNING 且尚无 ⇒ 进行中
    - Agent 阶段：不在 route ⇒ 未开始；result 已写 ⇒ 完成；仅 prompt ⇒ 进行中
    - REPORT：REPORT.md 存在 ⇒ 完成；全部 route agent 完成且任务 RUNNING ⇒ 进行中
    """
    if stage == "VALIDATION":
        return "SUCCESS" if runtime is not None else "PENDING"
    if stage == "BOUNDARY":
        if out is not None and (out / "boundary.json").exists():
            return "SUCCESS"
        if runtime is not None and runtime.status == "RUNNING":
            return "RUNNING"
        return "PENDING"
    if stage in ("HERMES", "WORKBUDDY", "CODEX"):
        agent = stage.lower()
        if route_agents is not None and agent not in route_agents:
            return "PENDING"  # 本任务不含该阶段
        if out is not None:
            if (out / f"{agent}_result.md").exists():
                return "SUCCESS"
            if (out / f"{agent}_prompt.md").exists():
                return "RUNNING"
        return "PENDING"
    if stage == "REPORT":
        if out is not None and (out / "REPORT.md").exists():
            return "SUCCESS"
        if (
            runtime is not None
            and runtime.status == "RUNNING"
            and route_agents
            and out is not None
            and all((out / f"{a}_result.md").exists() for a in route_agents)
        ):
            return "RUNNING"
        return "PENDING"
    return "PENDING"


# ---------------------------------------------------------------------------
# 纯函数：当前任务解析（TASK req 7 —— 确定性规则）
# ---------------------------------------------------------------------------


@dataclass
class TaskRef:
    """当前/最近任务引用（只读事实，不写任何 artifact）。"""

    task_id: str
    output_dir: Path | None
    task_path: Path | None = None


class _Record:
    """dict → 属性访问（读 last_run.json 的鸭子类型记录）。"""

    def __init__(self, data: dict):
        self.__dict__.update(data)


def _as_path(value) -> Path | None:
    if not value:
        return None
    try:
        return Path(value)
    except TypeError:
        return None


def _load_last_run_file():
    """直接读 last_run.json（无 launcher 上下文时的兜底；缺失/损坏 → None）。"""
    p = cfg_mod.CONFIG_DIR / "last_run.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return _Record(data)
    except (json.JSONDecodeError, OSError, TypeError):
        return None
    return None


def _output_dir_for_last(last) -> Path | None:
    """last 记录 → 输出目录：优先持久化字段；legacy 无该字段时从 task_path 推导。"""
    od = getattr(last, "output_dir", None)
    if od:
        return _as_path(od)
    task_path = getattr(last, "task_path", None)
    task_id = getattr(last, "task_id", None)
    if task_path and task_id:
        try:
            p = Path(task_path)
            if p.name == f"{task_id}.md" and p.parent.name == "active" and p.parent.parent.name == "tasks":
                # <ws>/.aaf/tasks/active/<id>.md → <ws>/.aaf/<id>
                return p.parent.parent.parent.parent / ".aaf" / task_id
        except Exception:
            return None
    return None


def resolve_current_task(launcher=None, last=None) -> TaskRef | None:
    """当前任务解析（确定性优先级）：

    1. 当前 launcher RUNNING 任务（内存事实，最优先）
    2. 最近 last_run 任务（launcher.last / last_run.json）
    3. 无 → None（空状态，不扫描 .aaf 猜测）
    """
    if launcher is not None:
        if getattr(launcher, "state", None) == "RUNNING":
            cur = getattr(launcher, "current", None)
            if cur is not None:
                return TaskRef(
                    task_id=str(getattr(cur, "task_id", "") or ""),
                    output_dir=_as_path(getattr(cur, "output_dir", None)),
                    task_path=_as_path(getattr(cur, "task_path", None)),
                )
        if last is None:
            last = getattr(launcher, "last", None) or launcher.load_last()
    if last is None:
        last = _load_last_run_file()
    if last is None:
        return None
    return TaskRef(
        task_id=str(getattr(last, "task_id", "") or ""),
        output_dir=_output_dir_for_last(last),
        task_path=_as_path(getattr(last, "task_path", None)),
    )


def _read_task_name(task_path) -> str:
    """从 TASK.md 读取 Task Name（只读；缺失/损坏 → ''，不崩溃）。"""
    try:
        text = Path(task_path).read_text(encoding="utf-8")
        body = task_io.extract_task_body(text)
        return task_io.parse_task(body).get("task_name", "") or ""
    except Exception:
        return ""


def _log_target(runtime, ref: TaskRef) -> Path | None:
    """[查看日志] 目标：REPORT.md 所在目录（优先）→ 任务输出目录。"""
    if runtime is not None and runtime.report_path:
        try:
            return Path(runtime.report_path).parent
        except Exception:
            pass
    return ref.output_dir


# ---------------------------------------------------------------------------
# 状态快照（窗口渲染的单一数据源）
# ---------------------------------------------------------------------------


@dataclass
class StatusSnapshot:
    """状态窗口一次渲染所需的全部展示数据（全部为展示就绪文本/事实）。"""

    # Bridge / Project 区
    project: str
    workspace: str
    bridge_status: str
    bridge_detail: str
    hotkey: str
    # Current Task 区
    has_task: bool
    task_id: str
    task_name: str
    stage: str
    agent: str
    elapsed: str
    last_activity: str
    overall: str
    overall_raw: str
    # Stage Strip
    stage_strip: dict = field(default_factory=dict)
    # Phase D：整体进度（只读估算；不写任何 artifact）
    progress_percent: int = 0
    progress_text: str = ""
    stage_share_text: str = ""
    # Phase D：suspected-stuck 提示（仅观察；不改 canonical state）
    stuck: bool = False
    stuck_warning: str = ""
    stuck_detail: str = ""
    # 查看日志 / 查看任务目录 / REPORT
    task_dir: str | None = None
    log_dir: str | None = None
    report_path: str | None = None
    empty_hint: str | None = None
    # Phase E / TASK-005-C：Stop / Cancel UX（UI/control 态；None = 不提供 Stop）
    cancel_ui: CancelUi | None = None
    # TASK-007 / RW-020：Runtime Health（只读观察；lifecycle 与 health 严格分离）
    # health = 技术判定码；health_warning = 面向用户中文警告；health_detail = 警告详情；
    # health_diagnostics = 诊断行（[查看诊断] 展示）；resume_hint = 既有恢复路径提示
    health: str = ""
    health_warning: str = ""
    health_detail: str = ""
    health_diagnostics: list = field(default_factory=list)
    resume_hint: str = ""


def _empty_stage_strip() -> dict:
    return {s: "PENDING" for s in STAGE_ORDER}


def unknown_snapshot() -> StatusSnapshot:
    """provider 异常时的兜底快照（全未知，不崩溃）。"""
    return StatusSnapshot(
        project=UNKNOWN,
        workspace=UNKNOWN,
        bridge_status=UNKNOWN,
        bridge_detail="",
        hotkey=UNKNOWN,
        has_task=False,
        task_id="",
        task_name="",
        stage="",
        agent="",
        elapsed="",
        last_activity="",
        overall="",
        overall_raw="",
        stage_strip=_empty_stage_strip(),
        progress_percent=0,
        progress_text=progress_mod.NO_INFO_TEXT,
        stage_share_text="",
        stuck=False,
        stuck_warning="",
        stuck_detail="",
        task_dir=None,
        log_dir=None,
        report_path=None,
        empty_hint="状态读取失败，请稍后重试。",
    )


def collect_status(cfg: dict, health: tuple, launcher) -> StatusSnapshot:
    """从真实状态源汇总一次状态快照（只读；不写任何 artifact）。"""
    health_code, health_detail = (health or ("", ""))
    bridge_label = HEALTH_LABELS.get(health_code, health_code or UNKNOWN)
    detail_text = f"（{health_detail}）" if health_detail and health_detail != bridge_label else ""
    hotkey = cfg.get("hotkey", "ctrl+alt+a")
    parsed = cfg_mod.parse_hotkey(hotkey)
    hotkey_desc = cfg_mod.describe_hotkey(*parsed) if parsed else repr(hotkey)

    last = None
    if launcher is not None:
        last = getattr(launcher, "last", None) or launcher.load_last()
    ref = resolve_current_task(launcher, last=last)

    runtime = None
    if ref is not None and ref.output_dir is not None:
        try:
            runtime = runtime_state_mod.read_runtime_state(ref.output_dir)
        except Exception:
            runtime = None  # 损坏/partial artifact → 未知，不崩溃、不修复

    project = str(cfg.get("current_project") or "（未设置）")
    workspace = str(cfg.get("current_workspace") or "（未设置）")
    bridge_status = f"{bridge_label}{detail_text}"

    if ref is None:
        return StatusSnapshot(
            project=project,
            workspace=workspace,
            bridge_status=bridge_status,
            bridge_detail=health_detail or "",
            hotkey=hotkey_desc,
            has_task=False,
            task_id="",
            task_name="",
            stage="",
            agent="",
            elapsed="",
            last_activity="",
            overall="",
            overall_raw="",
            stage_strip=_empty_stage_strip(),
            progress_percent=0,
            progress_text=progress_mod.NO_INFO_TEXT,
            stage_share_text="",
            stuck=False,
            stuck_warning="",
            stuck_detail="",
            task_dir=None,
            log_dir=None,
            report_path=None,
            empty_hint="当前没有任务。\n使用 Ctrl+Alt+A 粘贴 TASK 后开始执行。",
            cancel_ui=None,
        )

    task_name = _read_task_name(ref.task_path) if ref.task_path else ""
    route = read_route_agents(ref.output_dir) if ref.output_dir is not None else None
    strip = stage_states(runtime, ref.output_dir, route)
    log_dir = _log_target(runtime, ref)
    task_dir = str(ref.output_dir) if ref.output_dir is not None else None

    # --- Phase D：进度估算 + suspected-stuck 提示（只读；确定性；不写任何 artifact） ---
    status = runtime.status if runtime is not None else None
    est = progress_mod.estimate_progress(strip, status, progress_mod.stage_elapsed_map(runtime))
    stuck, stuck_warning, stuck_detail = stuck_mod.suspected_stuck(runtime)
    progress_text = progress_mod.progress_text(est.percent, status=status, has_info=runtime is not None)
    share_text = progress_mod.stage_share_text(strip)

    # --- TASK-007 / RW-020：Runtime Health（只读观察；lifecycle 与 health 严格分离） ---
    # 只对 canonical RUNNING 做 liveness 观察；只产生 health + warning + diagnostics，
    # 绝不写任何 canonical terminal（Terminal authority 保持 Core / Lifecycle）。
    health = runtime_health_mod.RuntimeHealth(
        runtime_health_mod.HEALTH_NOT_APPLICABLE, signals={},
    )
    if status == 'RUNNING' and ref.output_dir is not None:
        try:
            health = runtime_health_mod.collect_health(
                ref.output_dir,
                registry_dir=reg_mod.registry_root(),
            )
        except Exception:  # noqa: BLE001 —— 只读健康检查异常不得破坏状态窗口
            health = runtime_health_mod.RuntimeHealth(
                runtime_health_mod.HEALTH_UNKNOWN, signals={},
                diagnostics=['runtime health 读取失败（只读检查异常，不影响任务执行）'],
            )

    # --- Phase E / TASK-005-C：Stop / Cancel UX（只读 artifacts + launcher backend） ---
    cancel_ui = collect_cancel_ui(
        launcher, ref.task_id or "", ref.output_dir, status,
    )

    if runtime is not None:
        elapsed = format_elapsed(runtime.elapsed_seconds())
        activity = format_last_activity(runtime.last_activity_at)
        stage_disp = stage_display_name(runtime.stage)
        agent_disp = agent_label(runtime.agent)
        overall_raw = runtime.status or ""
        overall = overall_status_label(runtime.status)
        report_path = runtime.report_path or None
    else:
        # task.json 缺失（如 Validation 失败 / legacy）：只显示 last_run 事实，不猜测
        elapsed = UNKNOWN
        activity = UNKNOWN
        stage_disp = UNKNOWN
        agent_disp = UNKNOWN
        last_result = getattr(last, "result", "") if last else ""
        overall_raw = last_result
        overall = LAUNCHER_RESULT_LABELS.get(last_result, last_result or UNKNOWN)
        report_path = getattr(last, "report_path", None) or None

    return StatusSnapshot(
        project=project,
        workspace=workspace,
        bridge_status=bridge_status,
        bridge_detail=health_detail or "",
        hotkey=hotkey_desc,
        has_task=True,
        task_id=ref.task_id or UNKNOWN,
        task_name=task_name or UNKNOWN,
        stage=stage_disp,
        agent=agent_disp,
        elapsed=elapsed,
        last_activity=activity,
        overall=overall,
        overall_raw=overall_raw,
        stage_strip=strip,
        progress_percent=est.percent,
        progress_text=progress_text,
        stage_share_text=share_text,
        stuck=stuck,
        stuck_warning=stuck_warning,
        stuck_detail=stuck_detail,
        task_dir=task_dir,
        log_dir=str(log_dir) if log_dir else None,
        report_path=report_path,
        empty_hint=None,
        cancel_ui=cancel_ui,
        health=health.health,
        health_warning=health.warning,
        health_detail=health.warning_detail,
        health_diagnostics=list(health.diagnostics),
        resume_hint=health.resume_hint,
    )


def open_directory(path: str | Path) -> bool:
    """打开目录（Windows os.startfile；其他平台 explorer 兜底）。失败返回 False。"""
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["explorer", str(path)])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# tkinter 状态窗口（主线程；after 刷新；关闭安全停止）
# ---------------------------------------------------------------------------


class StatusWindow(tk.Toplevel):
    """正式状态窗口（Phase C）。

    - 只读展示：所有数据来自 provider() → StatusSnapshot
    - 约 1 秒 after 自动刷新；窗口关闭后刷新回调安全停止（TASK req 15/16）
    - 关闭（WM_DELETE_WINDOW / [关闭]）只销毁本窗口，不退出 Bridge
    """

    def __init__(self, root, provider, on_close=None, on_restart=None, on_exit=None,
                 on_stop_request=None, on_force_request=None):
        super().__init__(root)
        self._provider = provider
        self._on_close = on_close
        self._on_restart_cb = on_restart
        self._on_exit_cb = on_exit
        # Phase E / TASK-005-C：Stop / Force 动作回调（由 Bridge main 接线到 launcher
        # backend——本窗口只发请求，不直接 kill / 不写 canonical terminal，req 7）
        self._on_stop_cb = on_stop_request
        self._on_force_cb = on_force_request
        self._after_id = None
        self._closed = False
        self._empty_shown = True
        self._log_dir = None
        self._task_dir = None
        self._cancel_task_id = None
        self._force_shown = False
        # TASK-007 / RW-020：health 诊断缓存（[查看诊断] 展示；只读）
        self._health_diagnostics: list = []
        self._health_resume_hint = ""

        self.title("AAF 状态窗口 — AI Agent Framework")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self.refresh()
        self._schedule()

    # ---------- UI 构建 ----------

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 2}

        tk.Label(self, text="AI Agent Framework — 状态窗口", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 4)
        )

        # --- Bridge / Project 区 ---
        row = 1
        self._lbl_project = self._field_row(row, "当前项目：", columnspan=3, wraplength=300)
        row += 1
        self._lbl_bridge = self._field_row(row, "Bridge 状态：")
        row += 1
        self._lbl_hotkey = self._field_row(row, "热键：")
        row += 1
        self._lbl_workspace = self._field_row(row, "Workspace：", columnspan=3, wraplength=380)

        self._sep1 = tk.Frame(self, height=1, bg="#cccccc")
        self._sep1.grid(row=row + 1, column=0, columnspan=4, sticky="ew", padx=10, pady=4)

        # --- 当前任务区（有任务时显示） ---
        task_row = row + 2
        self._task_frame = tk.Frame(self)
        self._task_frame.grid(row=task_row, column=0, columnspan=4, sticky="ew")
        tk.Label(self._task_frame, text="当前任务", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", **pad
        )
        self._lbl_task_id = self._field_in_frame(self._task_frame, 1, "Task ID：")
        self._lbl_task_name = self._field_in_frame(self._task_frame, 2, "Task Name：", wraplength=300)
        self._lbl_stage = self._field_in_frame(self._task_frame, 3, "当前阶段：")
        self._lbl_agent = self._field_in_frame(self._task_frame, 4, "当前 Agent：")
        self._lbl_elapsed = self._field_in_frame(self._task_frame, 5, "已运行：")
        self._lbl_activity = self._field_in_frame(self._task_frame, 6, "最近活动：")
        self._lbl_overall = self._field_in_frame(self._task_frame, 7, "整体结果：")

        # Phase E / TASK-005-C：停止状态（UI/control 态；只读展示，不写 canonical）
        self._lbl_cancel_state = self._field_in_frame(self._task_frame, 8, "停止状态：")
        self._lbl_cancel_msg = tk.Label(
            self._task_frame, text="", font=("Segoe UI", 8), fg="#666666",
            wraplength=300, justify="left",
        )
        self._lbl_cancel_msg.grid(row=9, column=1, columnspan=3, sticky="w", padx=8, pady=0)

        # 整体进度（Phase D：只读估算；设计 §12.1 文案 + 进度条）
        self._lbl_progress = tk.Label(
            self._task_frame, text=progress_mod.NO_INFO_TEXT, font=("Segoe UI", 9, "bold")
        )
        self._lbl_progress.grid(row=10, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 1))
        self._progress_canvas = tk.Canvas(
            self._task_frame,
            width=PROGRESS_BAR_WIDTH,
            height=14,
            bg="#e8e8e8",
            highlightthickness=1,
            highlightbackground="#bbbbbb",
        )
        self._progress_canvas.grid(row=10, column=2, columnspan=2, sticky="ew", padx=8, pady=(4, 1))
        self._progress_fill = None

        # 当前阶段占比（Phase D req 6：允许附加；仅进行中阶段显示）
        self._lbl_stage_share = tk.Label(
            self._task_frame, text="", font=("Segoe UI", 8), fg="#666666"
        )
        self._lbl_stage_share.grid(row=11, column=0, columnspan=4, sticky="w", padx=8, pady=0)

        # suspected-stuck 提示横幅（Phase D：只观察、不改 canonical state；默认隐藏）
        self._lbl_stuck = tk.Label(
            self._task_frame,
            text="",
            font=("Segoe UI", 9, "bold"),
            fg="#7a5c00",
            bg="#fff8dc",
            anchor="w",
            justify="left",
        )
        self._lbl_stuck.grid_remove()

        # TASK-007 / RW-020：Runtime Health 警告横幅（只读观察；lifecycle 与 health
        # 严格分离——绝不写 canonical terminal；默认隐藏）
        self._lbl_health = tk.Label(
            self._task_frame,
            text="",
            font=("Segoe UI", 9, "bold"),
            fg="#8b0000",
            bg="#ffe9e9",
            anchor="w",
            justify="left",
            wraplength=380,
        )
        self._lbl_health.grid_remove()

        tk.Frame(self._task_frame, height=1, bg="#cccccc").grid(
            row=12, column=0, columnspan=4, sticky="ew", padx=4, pady=4
        )

        # 阶段条（六阶段：Validation … Report；进行中阶段高亮）
        self._cells: dict[str, tk.Label] = {}
        self._cell_default_bg: dict[str, str] = {}
        for i, stage in enumerate(STAGE_ORDER):
            cell = tk.Label(
                self._task_frame,
                text=f"{STAGE_DISPLAY.get(stage, stage)}\n○ 未开始",
                font=("Segoe UI", 9),
                justify="center",
                relief="groove",
                width=11,
                padx=4,
                pady=4,
            )
            cell.grid(row=13, column=i, padx=3, pady=4)
            self._cells[stage] = cell
            self._cell_default_bg[stage] = str(cell.cget("bg"))

        # --- 空状态区（无任务时显示） ---
        self._empty_frame = tk.Frame(self)
        self._empty_lbl = tk.Label(
            self._empty_frame,
            text="",
            font=("Segoe UI", 10),
            fg="#666666",
            justify="left",
            wraplength=420,
        )
        self._empty_lbl.pack(padx=12, pady=14, anchor="w")

        # --- 操作按钮 ---
        btns = tk.Frame(self)
        btns.grid(row=task_row + 1, column=0, columnspan=4, pady=(8, 2))
        self.btn_log = tk.Button(btns, text="查看日志", width=10, command=self._on_open_log)
        self.btn_log.pack(side="left", padx=5)
        self.btn_task_dir = tk.Button(btns, text="查看任务目录", width=12, command=self._on_open_task_dir)
        self.btn_task_dir.pack(side="left", padx=5)
        # TASK-007 / RW-020：[查看诊断]——展示 runtime health 诊断 + 既有恢复路径（只读；
        # 不写 canonical；Diagnostics / Resume UX，Req 5/6）
        self.btn_diag = tk.Button(btns, text="查看诊断", width=10, command=self._on_open_diagnostics)
        self.btn_diag.pack(side="left", padx=5)
        # Phase E / TASK-005-C：[停止当前任务] 只发 soft cancel 请求；[强制停止] 只在
        # backend 明确 force eligible 时显示（req 6），点击后经二次中文确认才触发
        self.btn_stop = tk.Button(btns, text="停止当前任务", width=12, command=self._on_stop)
        self.btn_stop.pack(side="left", padx=5)
        self.btn_force = tk.Button(btns, text="强制停止", width=9, command=self._on_force)
        tk.Button(btns, text="关闭", width=10, command=self.close).pack(side="left", padx=5)
        tk.Button(btns, text="重启 Bridge", width=12, command=self._on_restart).pack(side="left", padx=5)
        tk.Button(btns, text="退出 AAF", width=12, command=self._on_exit).pack(side="left", padx=5)

        tk.Label(
            self,
            text="停止/强制停止仅发送控制请求，最终任务状态由任务框架决定；关闭窗口不会退出 Bridge。",
            font=("Segoe UI", 8),
            fg="#666666",
        ).grid(row=task_row + 2, column=0, columnspan=4, padx=12, pady=(2, 8))

    def _field_row(self, row: int, label: str, columnspan: int = 1, wraplength: int | None = None):
        tk.Label(self, text=label, font=_FONT_BOLD).grid(row=row, column=0, sticky="ne", padx=12, pady=2)
        value = tk.Label(self, text="", font=_FONT_NORMAL, wraplength=wraplength, justify="left")
        value.grid(row=row, column=1, columnspan=columnspan, sticky="w", padx=8, pady=2)
        return value

    def _field_in_frame(self, frame, row: int, label: str, wraplength: int | None = None):
        tk.Label(frame, text=label, font=_FONT_BOLD).grid(row=row, column=0, sticky="ne", padx=8, pady=1)
        value = tk.Label(frame, text="", font=_FONT_NORMAL, wraplength=wraplength, justify="left")
        value.grid(row=row, column=1, columnspan=3, sticky="w", padx=8, pady=1)
        return value

    # ---------- 刷新（主线程 after 循环；关闭后安全停止） ----------

    def _schedule(self) -> None:
        if self._closed:
            return
        try:
            self._after_id = self.after(REFRESH_INTERVAL_MS, self._tick)
        except tk.TclError:
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        self.refresh()
        self._schedule()

    def refresh(self) -> None:
        """执行一次轻量只读刷新（provider 异常 / 窗口已销毁 → 安全返回）。"""
        if self._closed or not self._winfo_alive():
            return
        try:
            snapshot = self._provider()
        except Exception:
            snapshot = unknown_snapshot()
        if not self._winfo_alive():
            return
        self._render(snapshot)

    def _winfo_alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    # ---------- 渲染 ----------

    def _render(self, snap: StatusSnapshot) -> None:
        self._lbl_project.config(text=snap.project)
        self._lbl_bridge.config(text=snap.bridge_status)
        self._lbl_hotkey.config(text=snap.hotkey)
        self._lbl_workspace.config(text=snap.workspace)

        self._log_dir = snap.log_dir
        self.btn_log.config(state="normal" if snap.log_dir else "disabled")
        self._task_dir = getattr(snap, "task_dir", None)
        self.btn_task_dir.config(state="normal" if self._task_dir else "disabled")

        if not snap.has_task:
            self._empty_shown = True
            self._task_frame.grid_remove()
            self._empty_frame.grid()
            self._empty_lbl.config(text=snap.empty_hint or "")
            self._cancel_task_id = None
            self._update_cancel_buttons(None)
            return

        self._empty_shown = False
        self._empty_frame.grid_remove()
        self._task_frame.grid()
        self._lbl_task_id.config(text=snap.task_id)
        self._lbl_task_name.config(text=snap.task_name)
        self._lbl_stage.config(text=snap.stage)
        self._lbl_agent.config(text=snap.agent)
        self._lbl_elapsed.config(text=snap.elapsed)
        self._lbl_activity.config(text=snap.last_activity)
        self._lbl_overall.config(text=f"{snap.overall}（{snap.overall_raw}）" if snap.overall_raw else snap.overall)

        # Phase E / TASK-005-C：停止状态（UI/control 态展示 + 按钮可用性）
        cu = getattr(snap, "cancel_ui", None)
        if cu is not None:
            self._lbl_cancel_state.config(text=cu.label)
            self._lbl_cancel_msg.config(text=cu.message)
            self._lbl_cancel_state.grid()
            self._lbl_cancel_msg.grid()
        else:
            self._lbl_cancel_state.grid_remove()
            self._lbl_cancel_msg.grid_remove()
        self._cancel_task_id = snap.task_id if cu is not None else None
        self._update_cancel_buttons(cu)

        # Phase D：整体进度（只读估算；防御性读取兼容旧 provider 快照）
        self._lbl_progress.config(
            text=getattr(snap, "progress_text", "") or progress_mod.NO_INFO_TEXT
        )
        self._lbl_stage_share.config(text=getattr(snap, "stage_share_text", "") or "")
        self._draw_progress_bar(getattr(snap, "progress_percent", 0) or 0)

        # Phase D：suspected-stuck 提示（只观察；不改 canonical state）
        if getattr(snap, "stuck", False):
            warning = getattr(snap, "stuck_warning", "") or stuck_mod.STUCK_WARNING_TEXT
            detail = getattr(snap, "stuck_detail", "") or ""
            self._lbl_stuck.config(text=f"{warning}（{detail}）" if detail else warning)
            self._lbl_stuck.grid()
        else:
            self._lbl_stuck.grid_remove()

        # TASK-007 / RW-020：Runtime Health 警告横幅（只观察；不改 canonical state；
        # 「任务可能已异常中断」中文明确显示 + 安全入口见 [查看诊断]）
        self._health_diagnostics = list(getattr(snap, "health_diagnostics", []) or [])
        self._health_resume_hint = getattr(snap, "resume_hint", "") or ""
        self.btn_diag.config(
            state="normal" if self._health_diagnostics else "disabled"
        )
        hw = getattr(snap, "health_warning", "") or ""
        hd = getattr(snap, "health_detail", "") or ""
        if hw:
            self._lbl_health.config(text=f"⚠ {hw}" + (f"（{hd}）" if hd else ""))
            self._lbl_health.grid()
        else:
            self._lbl_health.grid_remove()

        for stage, state in snap.stage_strip.items():
            cell = self._cells.get(stage)
            if cell is None:
                continue
            symbol, label = stage_state_label(state)
            cell.config(text=f"{STAGE_DISPLAY.get(stage, stage)}\n{symbol} {label}")
            cell.config(bg=STAGE_RUNNING_BG if state == "RUNNING" else self._cell_default_bg.get(stage, ""))

    def _draw_progress_bar(self, percent: int) -> None:
        """重绘进度条填充（0% → 空；100% → 全宽）。"""
        try:
            percent = min(100, max(0, int(percent)))
        except (TypeError, ValueError):
            percent = 0
        if self._progress_fill is not None:
            try:
                self._progress_canvas.delete(self._progress_fill)
            except tk.TclError:
                pass
            self._progress_fill = None
        if percent <= 0:
            return
        width = max(2, int(PROGRESS_BAR_WIDTH * percent / 100.0))
        self._progress_fill = self._progress_canvas.create_rectangle(
            0, 0, width, 14, fill="#4caf50", outline=""
        )

    # ---------- Phase E / TASK-005-C：停止/强制停止按钮状态 ----------

    def _update_cancel_buttons(self, cu: CancelUi | None) -> None:
        """按 CancelUi 状态更新 [停止当前任务] / [强制停止]（设计 §6.9 状态机）。

        - can_stop → 「停止当前任务」可用
        - 请求停止 / 正在取消 / 无法安全停止 → 按钮变灰文案「正在取消…」（§6.9）
        - terminal / 无任务 / 不可验证 → 禁用
        - [强制停止] 只在 backend 明确 force eligible 时显示（req 6）
        """
        if cu is not None and cu.can_stop:
            self.btn_stop.config(text="停止当前任务", state="normal")
        elif cu is not None and cu.state in (
            CANCEL_UI_STOP_REQUESTED, CANCEL_UI_CANCELLING, CANCEL_UI_STOP_UNSAFE,
        ):
            self.btn_stop.config(text="正在取消…", state="disabled")
        else:
            self.btn_stop.config(text="停止当前任务", state="disabled")

        if cu is not None and cu.can_force:
            if not self._force_shown:
                self.btn_force.pack(side="left", padx=5, before=self.btn_stop)
                self._force_shown = True
            self.btn_force.config(state="normal")
        else:
            if self._force_shown:
                try:
                    self.btn_force.pack_forget()
                except tk.TclError:
                    pass
                self._force_shown = False

    # ---------- 操作 ----------

    def _on_open_log(self) -> None:
        if self._log_dir:
            open_directory(self._log_dir)

    def _on_open_task_dir(self) -> None:
        if getattr(self, "_task_dir", None):
            open_directory(self._task_dir)

    def _on_open_diagnostics(self) -> None:
        """[查看诊断]：展示 Runtime Health 诊断 + 既有恢复路径（只读；不写 canonical）。

        内容来自最近一次 collect_status 的 health_diagnostics / resume_hint——
        窗口不重新执行诊断、不触碰任何 canonical artifact。
        """
        lines = ["【任务运行诊断】（只读观察）", "=" * 40]
        for d in getattr(self, "_health_diagnostics", []) or []:
            lines.append(f"- {d}")
        hint = getattr(self, "_health_resume_hint", "") or ""
        if hint:
            lines.append("")
            lines.append(hint)
        try:
            messagebox.showinfo("任务诊断", "\n".join(lines), parent=self)
        except tk.TclError:
            pass

    def _on_stop(self) -> None:
        """[停止当前任务]：只发送 soft cancel 请求（req 3；UI 不写 terminal）。

        实际写入经 main.py 接线到 Core-owned cancel 模块（state.lock 序列化）；
        本窗口只转发当前任务的 task_id / output_dir。
        """
        task_id = self._cancel_task_id
        if not task_id or self._on_stop_cb is None:
            return
        try:
            self._on_stop_cb(task_id, getattr(self, "_task_dir", None))
        except Exception:  # noqa: BLE001 —— 单次动作异常不崩溃窗口
            pass

    def _on_force(self) -> None:
        """[强制停止]：只在 force eligible 时可达（按钮可见性由 _update_cancel_buttons
        控制，req 6）；二次中文确认由 main.py 的对话框负责（req 4/5），确认后才调用
        launcher.request_force_cancel（verified ownership + evidence + Core finalizer）。
        """
        task_id = self._cancel_task_id
        if not task_id or self._on_force_cb is None:
            return
        try:
            self._on_force_cb(task_id)
        except Exception:  # noqa: BLE001 —— 单次动作异常不崩溃窗口
            pass

    def _on_restart(self) -> None:
        if self._on_restart_cb is not None:
            try:
                self._on_restart_cb()
            except Exception:
                pass

    def _on_exit(self) -> None:
        if self._on_exit_cb is not None:
            try:
                self._on_exit_cb()
            except Exception:
                pass

    def close(self) -> None:
        """关闭窗口：取消刷新回调 → 销毁窗口 → 通知 on_close（不退出 Bridge）。"""
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.destroy()
        except tk.TclError:
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass


class StatusWindowController:
    """状态窗口单例控制（Tray → 打开 → 复用/聚焦；关闭不退出 Bridge）。

    - open()：已存在且存活 → 复用 + 聚焦；否则新建（不无限创建重复窗口）
    - 窗口关闭 → 引用清空，下次 open() 新建
    """

    def __init__(self, root, provider, on_restart=None, on_exit=None, on_close=None,
                 on_stop_request=None, on_force_request=None):
        self.root = root
        self.provider = provider
        self.on_restart = on_restart
        self.on_exit = on_exit
        self.on_close = on_close
        # Phase E / TASK-005-C：Stop / Force 动作回调（Bridge main 接线 launcher backend）
        self.on_stop_request = on_stop_request
        self.on_force_request = on_force_request
        self.window: StatusWindow | None = None

    def open(self) -> StatusWindow:
        if self._alive():
            try:
                self.window.lift()
                self.window.focus_force()
            except Exception:
                pass
            return self.window
        self.window = StatusWindow(
            self.root,
            provider=self.provider,
            on_close=self._on_window_closed,
            on_restart=self.on_restart,
            on_exit=self.on_exit,
            on_stop_request=self.on_stop_request,
            on_force_request=self.on_force_request,
        )
        return self.window

    def _alive(self) -> bool:
        w = self.window
        if w is None:
            return False
        try:
            return bool(w.winfo_exists())
        except tk.TclError:
            self.window = None
            return False

    def _on_window_closed(self) -> None:
        self.window = None
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:
                pass
