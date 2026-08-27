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
  进度收敛（§4.1.5 停在取消时刻权重和）；最终 [停止当前任务] 按钮与取消状态机
  属 TASK-005-C，本窗口不实现
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

from . import config as cfg_mod
from . import task_io
from . import progress as progress_mod
from . import stuck as stuck_mod
from ai_agent_framework import runtime_state as runtime_state_mod

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

    def __init__(self, root, provider, on_close=None, on_restart=None, on_exit=None):
        super().__init__(root)
        self._provider = provider
        self._on_close = on_close
        self._on_restart_cb = on_restart
        self._on_exit_cb = on_exit
        self._after_id = None
        self._closed = False
        self._empty_shown = True
        self._log_dir = None
        self._task_dir = None

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

        # 整体进度（Phase D：只读估算；设计 §12.1 文案 + 进度条）
        self._lbl_progress = tk.Label(
            self._task_frame, text=progress_mod.NO_INFO_TEXT, font=("Segoe UI", 9, "bold")
        )
        self._lbl_progress.grid(row=8, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 1))
        self._progress_canvas = tk.Canvas(
            self._task_frame,
            width=PROGRESS_BAR_WIDTH,
            height=14,
            bg="#e8e8e8",
            highlightthickness=1,
            highlightbackground="#bbbbbb",
        )
        self._progress_canvas.grid(row=8, column=2, columnspan=2, sticky="ew", padx=8, pady=(4, 1))
        self._progress_fill = None

        # 当前阶段占比（Phase D req 6：允许附加；仅进行中阶段显示）
        self._lbl_stage_share = tk.Label(
            self._task_frame, text="", font=("Segoe UI", 8), fg="#666666"
        )
        self._lbl_stage_share.grid(row=9, column=0, columnspan=4, sticky="w", padx=8, pady=0)

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

        tk.Frame(self._task_frame, height=1, bg="#cccccc").grid(
            row=10, column=0, columnspan=4, sticky="ew", padx=4, pady=4
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
            cell.grid(row=11, column=i, padx=3, pady=4)
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
        tk.Button(btns, text="关闭", width=10, command=self.close).pack(side="left", padx=5)
        tk.Button(btns, text="重启 Bridge", width=12, command=self._on_restart).pack(side="left", padx=5)
        tk.Button(btns, text="退出 AAF", width=12, command=self._on_exit).pack(side="left", padx=5)

        tk.Label(
            self,
            text="状态窗口为只读观察界面；关闭窗口不会退出 Bridge。",
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

    # ---------- 操作 ----------

    def _on_open_log(self) -> None:
        if self._log_dir:
            open_directory(self._log_dir)

    def _on_open_task_dir(self) -> None:
        if getattr(self, "_task_dir", None):
            open_directory(self._task_dir)

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

    def __init__(self, root, provider, on_restart=None, on_exit=None, on_close=None):
        self.root = root
        self.provider = provider
        self.on_restart = on_restart
        self.on_exit = on_exit
        self.on_close = on_close
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
