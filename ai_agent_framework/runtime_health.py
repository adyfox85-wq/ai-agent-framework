"""AI Agent Framework — Runtime Health assessment（RW-020，只读）。

Lifecycle State 与 Runtime Health 严格分离（RW-020 Important Boundary）：

- Lifecycle State（task.json status）：RUNNING / SUCCESS / WAITING / FAILED / CANCELLED
- Runtime Health（本模块）：对 canonical RUNNING 的 liveness 观察——
  HEALTHY / STALE / PROCESS_MISSING / AGENT_MISSING / SUSPICIOUS_DEAD /
  RECOVERING / TERMINAL_PENDING / UNKNOWN / NOT_APPLICABLE

权威边界：
- 本模块**只读**：不写 task.json / run.json / REPORT.md / control.json / 任何
  canonical artifact；dead-runner detection 只产生 health + warning + diagnostics。
- Terminal authority 保持 Core / Lifecycle（既有 Safe Cancel / recovery 架构）；
  Status Window / Bridge / UI 不得经本模块把 RUNNING 改为 FAILED / CANCELLED。

判定原则（Req 2 / 4）：
- 不使用单一 PID 或单一时间阈值直接判死。SUSPICIOUS_DEAD（「任务可能已异常中断」）
  需要组合：runner 进程缺失 / 身份无法证明为本任务 owner（PID reuse fail-safe）+
  last_activity_at stale + 期望当前阶段产物缺失。
- 假阳性保护：
  * runner 存活且身份一致 → HEALTHY（长时间无 stdout 不算死）
  * canonical terminal 已提交（run.json 终态）→ canonical wins（TERMINAL_PENDING）
  * force-cancel / soft-cancel 恢复流程进行中（且 runner 存活）→ RECOVERING
  * PID recycle / ownership mismatch → 不把 unrelated process 当 owner（fail-safe）
  * 无 ownership 记录（legacy / 直接运行）→ 无法验证进程 → 只给 STALE / AGENT_MISSING
    警告，不升级为 SUSPICIOUS_DEAD（不能证明死，不得误报）
- stale timestamp alone（Req E）→ 只产生 STALE 警告，不足以判死。

恢复路径（Req 6）：诊断输出 Framework 既有 resume-from 命令（不另造第二套
lifecycle / resume architecture）。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import control as control_mod
from . import proc_identity
from . import runtime_state as runtime_state_mod
from .task_lifecycle import TERMINAL_STATUSES

# Health 词汇（RW-020 backlog：HEALTHY / STALE / PROCESS_MISSING / AGENT_MISSING /
# UNKNOWN；SUSPICIOUS_DEAD = 组合信号死判提示；其余为保护性状态）
HEALTH_HEALTHY = "HEALTHY"
HEALTH_STALE = "STALE"
HEALTH_PROCESS_MISSING = "PROCESS_MISSING"
HEALTH_AGENT_MISSING = "AGENT_MISSING"
HEALTH_SUSPICIOUS_DEAD = "SUSPICIOUS_DEAD"
HEALTH_RECOVERING = "RECOVERING"
HEALTH_TERMINAL_PENDING = "TERMINAL_PENDING"
HEALTH_UNKNOWN = "UNKNOWN"
HEALTH_NOT_APPLICABLE = "NOT_APPLICABLE"

# last_activity_at 停滞阈值：与 bridge/stuck.py 的 suspected-stuck 阈值一致
# （10 分钟；两处独立常量化避免跨层 import，语义同步维护）。
LAST_ACTIVITY_STALE_THRESHOLD_SECONDS = 10 * 60

# 面向用户的死判警告文案（Req 5：中文明确显示）
WARNING_SUSPICIOUS_DEAD = "任务可能已异常中断"
WARNING_PROCESS_MISSING = "任务运行进程不存在"
WARNING_AGENT_MISSING = "当前阶段未见预期产物"
WARNING_STALE = "任务已长时间无活动"

# 恢复方式前缀（Req 6：引导进入既有 resume 路径）
RESUME_HINT_HEADER = "恢复方式（Framework 既有 resume 路径，复用已完成 Agent 结果并继续未完成阶段）："


@dataclass
class RuntimeHealth:
    """结构化 runtime health 判定（只读；不写任何 canonical artifact）。"""

    health: str
    task_id: str = ""
    stage: str | None = None
    agent: str | None = None
    signals: dict = field(default_factory=dict)   # 信号名 → bool | None
    diagnostics: list = field(default_factory=list)  # 中文诊断行
    warning: str = ""                              # 面向用户警告文案（''=无警告）
    warning_detail: str = ""                       # 警告详情（中文）
    resume_hint: str = ""                          # 既有恢复路径提示

    def to_dict(self) -> dict:
        return {
            "health": self.health,
            "task_id": self.task_id,
            "stage": self.stage,
            "agent": self.agent,
            "signals": dict(self.signals),
            "diagnostics": list(self.diagnostics),
            "warning": self.warning,
            "warning_detail": self.warning_detail,
            "resume_hint": self.resume_hint,
        }


# ---------------------------------------------------------------------------
# 信号采集辅助（确定性；全部只读）
# ---------------------------------------------------------------------------


def last_activity_stale(iso: str | None, now: datetime | None = None) -> bool | None:
    """last_activity_at 是否停滞（≥ 阈值）。缺失 / 非法 ISO → None（无法观察）。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    now = now or datetime.now()
    return max(0.0, (now - dt).total_seconds()) >= LAST_ACTIVITY_STALE_THRESHOLD_SECONDS


def last_activity_age_seconds(iso: str | None, now: datetime | None = None) -> float | None:
    """last_activity_at 距今秒数；缺失 / 非法 → None。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0.0, ((now or datetime.now()) - dt).total_seconds())


def read_route_agents(output_dir: Path | str) -> list[str] | None:
    """读 route.json 的 agents；缺失 / 损坏 → None（不猜测）。"""
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


def expected_stage_artifact_missing(
    stage: str | None, agent: str | None, output_dir: Path | str, route_agents: list[str] | None = None,
) -> bool | None:
    """当前阶段期望产物是否缺失（None = 无法定义期望 / 不适用）。

    - Agent 阶段（HERMES / WORKBUDDY / CODEX）：``<agent>_prompt.md`` 存在而
      ``<agent>_result.md`` 缺失 → True（agent 已被调用但未产出结果）；
      prompt 也不存在 → False（尚未被调用，不算缺失）；result 存在 → False
    - REPORT：REPORT.md 缺失且全部 route agent 结果齐全 → True；否则 False
    - 其他（VALIDATION / BOUNDARY / COMPLETED / 未知）→ None
    """
    out = Path(output_dir)
    if not stage:
        return None
    stage_u = str(stage).upper()
    if stage_u in ("HERMES", "WORKBUDDY", "CODEX"):
        ag = stage_u.lower()
        if (out / f"{ag}_result.md").exists():
            return False
        if (out / f"{ag}_prompt.md").exists():
            return True  # agent 已被调用但未产出——可能死亡 / 卡死
        return False
    if stage_u == "REPORT":
        if (out / "REPORT.md").exists():
            return False
        route = route_agents if route_agents is not None else read_route_agents(out)
        if route and all((out / f"{a}_result.md").exists() for a in route):
            return True  # 全部 agent 完成但 REPORT 未生成
        return False
    return None


def _read_registry_entry(launch_id: str | None, registry_dir) -> dict | None:
    """直接读 Bridge launch registry 单条目（不 import bridge，避免 Core→Bridge 反向依赖）。

    缺失 / 损坏 → None（registry 只是第二份证据；control.json 为主）。
    """
    if not launch_id or not registry_dir:
        return None
    path = Path(registry_dir) / f"{launch_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _runner_identity_ok(live: dict | None, runner_ct: str | None, expected_cmdline) -> bool | None:
    """live 进程身份是否可证明为本任务 runner（防 PID recycle / 不把 unrelated process 当 owner）。

    - 无任何身份记录（creation time 与 expected_command_line 均无）→ None（无法验证）
    - 有记录 creation time 但不一致 → False（PID recycle / 身份不匹配，fail-safe）
    - creation time 一致 + 命令行匹配 / 无法获取命令行 → True（创建时间是稳定身份）
    - 命令行可比较但不匹配 → False
    """
    if live is None or not live.get("exists"):
        return None
    if not runner_ct and not expected_cmdline:
        return None
    ct_ok = proc_identity.creation_times_equal(live.get("creation_time"), runner_ct)
    if runner_ct and ct_ok is False:
        return False  # 创建时间不匹配 → 该 PID 不是本任务 runner（PID reuse 风险）
    cmd = live.get("command_line")
    if expected_cmdline:
        if not cmd:
            return None  # 无法获取 live 命令行 → 无法验证（fail-safe：不判死）
        return proc_identity.command_line_matches(cmd, expected_cmdline)
    return True


def _runner_evidence(recorded: bool, alive: bool | None, identity_ok: bool | None) -> str:
    """runner 证据归类：ALIVE_OK / ALIVE_UNVERIFIED / DEAD / UNKNOWN。

    - 无 ownership 记录（legacy / 直接运行）→ UNKNOWN（无法验证进程，不判死）
    - 进程不存在 → DEAD
    - 进程存活但身份明确不匹配（PID reuse）→ DEAD（不把 unrelated process 当 owner）
    - 进程存活 + 身份一致 → ALIVE_OK
    - 进程存活 + 身份无法验证 → ALIVE_UNVERIFIED（不判死）
    - 进程查询失败（权限 / 平台）→ UNKNOWN（fail-safe：不能证明死）
    """
    if not recorded:
        return "UNKNOWN"
    if alive is False:
        return "DEAD"
    if alive is True:
        if identity_ok is False:
            return "DEAD"  # PID reuse / ownership mismatch → 视为 runner 缺失
        if identity_ok is True:
            return "ALIVE_OK"
        return "ALIVE_UNVERIFIED"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# 纯判定（可单测：RW-020 regression A–F）
# ---------------------------------------------------------------------------


def assess_health(
    runtime_status: str | None,
    signals: dict,
    *,
    task_id: str = "",
    stage: str | None = None,
    agent: str | None = None,
    now: datetime | None = None,
) -> RuntimeHealth:
    """纯函数：由 lifecycle status + 信号组合判定 runtime health（无副作用）。

    signals 键（bool | None）：
    - runner_pid_recorded / runner_process_alive / runner_identity_ok
    - last_activity_stale / expected_artifact_missing
    - recovery_in_progress / terminal_pending
    - agent_process_alive（可选佐证；无法验证时 None，不驱动判定）
    """
    if runtime_status != "RUNNING":
        return RuntimeHealth(
            HEALTH_NOT_APPLICABLE, task_id=task_id, stage=stage, agent=agent,
            signals=dict(signals),
            diagnostics=["任务不在 RUNNING（无 liveness 判定）"],
        )
    if signals.get("terminal_pending"):
        return RuntimeHealth(
            HEALTH_TERMINAL_PENDING, task_id=task_id, stage=stage, agent=agent,
            signals=dict(signals),
            diagnostics=["canonical terminal 已提交（run.json 终态）——canonical 优先，"
                         "UI / 派生产物尚未刷新"],
        )
    if signals.get("recovery_in_progress"):
        return RuntimeHealth(
            HEALTH_RECOVERING, task_id=task_id, stage=stage, agent=agent,
            signals=dict(signals),
            diagnostics=["取消 / 强制取消恢复流程进行中——不判定 dead"],
        )

    evidence = _runner_evidence(
        bool(signals.get("runner_pid_recorded")),
        signals.get("runner_process_alive"),
        signals.get("runner_identity_ok"),
    )
    stale = signals.get("last_activity_stale")
    artifact_missing = signals.get("expected_artifact_missing")
    diag: list[str] = []

    if evidence == "ALIVE_OK":
        h = RuntimeHealth(
            HEALTH_HEALTHY, task_id=task_id, stage=stage, agent=agent, signals=dict(signals),
            diagnostics=["runner 进程存活且身份一致（creation time + 命令行验证通过）"],
        )
        if stale is True:
            h.diagnostics.append("注：last_activity 已停滞——runner 存活中，属正常长执行 / "
                                 "无 stdout 场景，不判死（RW-020 假阳性保护）")
        return h

    if evidence == "ALIVE_UNVERIFIED":
        diag.append("runner 进程存活但身份无法完全验证（缺创建时间 / 命令行记录）——不判死")
        if artifact_missing is True:
            h = HEALTH_AGENT_MISSING
            diag.append(f"当前阶段 {stage or '?'} 期望产物缺失（agent 已调用但未产出结果）")
        elif stale is True:
            h = HEALTH_STALE
            diag.append("last_activity 停滞")
        else:
            h = HEALTH_HEALTHY
        return _build(h, task_id, stage, agent, signals, diag)

    if evidence == "DEAD":
        diag.append("runner 进程缺失 / 身份无法证明为本任务 owner（fail-safe：不把 "
                    "unrelated process 当 owner）")
        if stale is True and artifact_missing is True:
            diag.append("last_activity 停滞 + 期望阶段产物缺失——组合信号判死")
            return _build(HEALTH_SUSPICIOUS_DEAD, task_id, stage, agent, signals, diag,
                          warning=WARNING_SUSPICIOUS_DEAD)
        if stale is True:
            diag.append("last_activity 停滞（单一时间信号不足判死，仅警告）")
        if artifact_missing is True:
            diag.append(f"当前阶段 {stage or '?'} 期望产物缺失")
        return _build(HEALTH_PROCESS_MISSING, task_id, stage, agent, signals, diag,
                      warning=WARNING_PROCESS_MISSING)

    # UNKNOWN：无 ownership 记录 / 无法查询进程
    diag.append("无 runner ownership 记录或无法查询进程（legacy / 直接运行 / 权限限制）"
                "——无法证明 runner 已死，不得误报 dead")
    if artifact_missing is True:
        diag.append(f"当前阶段 {stage or '?'} 期望产物缺失")
        return _build(HEALTH_AGENT_MISSING, task_id, stage, agent, signals, diag,
                      warning=WARNING_AGENT_MISSING)
    if stale is True:
        diag.append("last_activity 停滞（单一时间信号不足判死，仅警告）")
        return _build(HEALTH_STALE, task_id, stage, agent, signals, diag,
                      warning=WARNING_STALE)
    return _build(HEALTH_UNKNOWN, task_id, stage, agent, signals, diag)


def _build(health: str, task_id: str, stage, agent, signals: dict, diag: list[str],
           warning: str = "") -> RuntimeHealth:
    detail = ""
    if warning == WARNING_SUSPICIOUS_DEAD:
        detail = " ".join(d for d in diag if "组合信号判死" not in d)
    elif warning:
        detail = "；".join(d for d in diag if "不足判死" not in d and "不判死" not in d)
    return RuntimeHealth(
        health, task_id=task_id, stage=stage, agent=agent,
        signals=dict(signals), diagnostics=list(diag),
        warning=warning, warning_detail=detail[:400],
    )


# ---------------------------------------------------------------------------
# 文件级采集（只读 facade；Status Window / CLI 使用）
# ---------------------------------------------------------------------------


def collect_health(
    output_dir: Path | str,
    *,
    registry_dir: Path | str | None = None,
    live_identity_override: dict | None = None,
    now: datetime | None = None,
) -> RuntimeHealth:
    """从真实 artifacts 采集 runtime health（只读；不写任何文件）。

    - task.json（runtime_state）→ lifecycle status / stage / agent / last_activity_at
    - control.json → launch_id / runner_pid / runner_creation_time / expected_command_line
      / cancel_requested / force_terminate_requested / workspace
    - registry（registry_dir 提供时）→ 第二份 ownership 证据（bridge-owned；缺失不阻断）
    - live process（proc_identity；测试可注入 live_identity_override）
    - run.json → terminal_pending（canonical wins）
    """
    out = Path(output_dir)
    runtime = runtime_state_mod.read_runtime_state(out)
    if runtime is None:
        return RuntimeHealth(HEALTH_NOT_APPLICABLE, signals={}, diagnostics=["task.json 不存在"])
    if runtime.status != "RUNNING":
        return RuntimeHealth(
            HEALTH_NOT_APPLICABLE, task_id=runtime.task_id or "",
            stage=runtime.stage, agent=runtime.agent,
            signals={}, diagnostics=[f"任务 lifecycle status = {runtime.status}（非 RUNNING）"],
        )

    control, ctrl_err = control_mod.read_control(out)
    if ctrl_err:
        control = None
    registry = _read_registry_entry(control.get("launch_id") if control else None, registry_dir)

    runner_pid = None
    if control and control.get("runner_pid") is not None:
        runner_pid = control["runner_pid"]
    elif registry and registry.get("runner_pid") is not None:
        runner_pid = registry["runner_pid"]
    runner_ct = None
    if control and control.get("runner_creation_time"):
        runner_ct = control["runner_creation_time"]
    elif registry and registry.get("runner_creation_time"):
        runner_ct = registry["runner_creation_time"]
    expected_cmdline = None
    if control and control.get("expected_command_line"):
        expected_cmdline = control["expected_command_line"]
    elif registry and registry.get("expected_command_line"):
        expected_cmdline = registry["expected_command_line"]

    signals: dict = {
        "runner_pid_recorded": runner_pid is not None,
        "runner_process_alive": None,
        "runner_identity_ok": None,
    }
    if runner_pid is not None:
        live = live_identity_override or proc_identity.live_process_identity(int(runner_pid))
        signals["runner_process_alive"] = bool(live and live.get("exists"))
        signals["runner_identity_ok"] = _runner_identity_ok(live, runner_ct, expected_cmdline)

    signals["last_activity_stale"] = last_activity_stale(runtime.last_activity_at, now)
    route = read_route_agents(out)
    signals["expected_artifact_missing"] = expected_stage_artifact_missing(
        runtime.stage, runtime.agent, out, route,
    )

    # recovery / terminal 保护信号
    force_requested = bool(control and control.get("force_terminate_requested") is True)
    cancel_requested = bool(control and control.get("cancel_requested") is True)
    alive = signals["runner_process_alive"]
    signals["recovery_in_progress"] = force_requested or (cancel_requested and alive is True)
    terminal_pending = False
    run_path = out / "run.json"
    if run_path.exists():
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
            terminal_pending = bool(run and run.get("status") in TERMINAL_STATUSES)
        except (OSError, json.JSONDecodeError):
            terminal_pending = False
    signals["terminal_pending"] = terminal_pending

    h = assess_health(
        runtime.status, signals,
        task_id=runtime.task_id or "", stage=runtime.stage, agent=runtime.agent, now=now,
    )

    # 诊断补充（事实行）
    if runner_pid is not None:
        h.diagnostics.append(
            f"runner 记录: pid={runner_pid}, creation_time={runner_ct or '未记录'}, "
            f"alive={signals['runner_process_alive']}, identity_ok={signals['runner_identity_ok']}"
        )
    else:
        h.diagnostics.append("runner 记录: 无（无 control.json / registry ownership 记录）")
    age = last_activity_age_seconds(runtime.last_activity_at, now)
    if age is not None:
        h.diagnostics.append(f"last_activity_at: {int(age)} 秒前（stage={runtime.stage or '?'}, "
                             f"agent={runtime.agent or '?'}）")
    if force_requested:
        h.diagnostics.append("control.force_terminate_requested=True（强制取消恢复流程）")
    if cancel_requested:
        h.diagnostics.append("control.cancel_requested=True（软取消请求）")
    if terminal_pending:
        h.diagnostics.append("run.json 已含 canonical terminal——以 canonical 为准")

    # 恢复提示（Req 6：既有 resume 路径；不另造第二套架构）
    # workspace 来源：control.workspace 优先；legacy 目录（无 control）回退 task.json
    # workspace 字段（runtime reader 不暴露，此处直接读原始数据）。
    ws = (control or {}).get("workspace") or ""
    if not ws:
        try:
            from .task_lifecycle import read_status
            state_data = read_status(out)
            if isinstance(state_data, dict):
                ws = str(state_data.get("workspace") or "")
        except Exception:  # noqa: BLE001 —— 提示缺失不阻断诊断
            ws = ""
    snapshot = out / "TASK.snapshot.md"
    if snapshot.exists() and ws:
        h.resume_hint = (
            f"{RESUME_HINT_HEADER}\n"
            f"  python run.py {snapshot} --workspace {ws} --output {out} --resume-from {out}"
        )
    return h


# ---------------------------------------------------------------------------
# CLI（诊断查看入口；只读）
# ---------------------------------------------------------------------------


def _render_text(h: RuntimeHealth) -> str:
    lines = [
        f"Runtime Health: {h.health}",
        f"Task: {h.task_id or '(unknown)'}",
        f"Stage: {h.stage or '—'} / Agent: {h.agent or '—'}",
    ]
    if h.warning:
        lines.append(f"警告: {h.warning}" + (f"（{h.warning_detail}）" if h.warning_detail else ""))
    lines.append("诊断:")
    for d in h.diagnostics:
        lines.append(f"  - {d}")
    if h.resume_hint:
        lines.append(h.resume_hint)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AAF Runtime Health diagnostics（只读）")
    p.add_argument("--output", required=True, help="任务输出目录（<ws>/.aaf/<Task-ID>）")
    p.add_argument("--registry-dir", default=None, help="Bridge launch registry 根目录（可选）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    args = p.parse_args(argv)
    h = collect_health(args.output, registry_dir=args.registry_dir)
    if args.json:
        print(json.dumps(h.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_text(h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
