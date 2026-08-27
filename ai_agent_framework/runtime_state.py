"""AI Agent Framework — 统一 Runtime State reader（v0.4 Phase A）。

职责：
- 从 task.json 读取结构化 live runtime state（供未来 Desktop Shell 展示，不复制 Lifecycle 逻辑）
- legacy compatibility：旧 task.json 无新字段也可读（不崩溃）
- 只读；不修改任何文件

Canonical 边界：
- task.json = live canonical runtime view
- run.json = completed run summary（本模块不读取 run.json 作为 runtime 状态）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .task_lifecycle import VALID_STAGES, VALID_PHASE_STATES, read_status

# 兼容导出（供外部引用单一来源）
STAGES = VALID_STAGES
PHASE_STATES = VALID_PHASE_STATES


@dataclass
class RuntimeState:
    """结构化 runtime view（全部字段可缺失——legacy 兼容）。

    - task_id: str | None
    - status: str | None（CREATED / RUNNING / WAITING / SUCCESS / FAILED）
    - stage: 当前阶段 | None
    - agent: 当前 Agent（hermes / workbuddy / codex）| None
    - started_at / stage_started_at / last_activity_at / updated_at: str | None（ISO）
    - phases: {stage: {state, started_at, updated_at}}
    """

    task_id: str | None = None
    status: str | None = None
    stage: str | None = None
    agent: str | None = None
    started_at: str | None = None
    stage_started_at: str | None = None
    last_activity_at: str | None = None
    updated_at: str | None = None
    report_path: str | None = None
    phases: dict = field(default_factory=dict)

    # --- 只读访问器 ---

    def current_stage(self) -> str | None:
        return self.stage

    def current_agent(self) -> str | None:
        return self.agent

    def phase_state(self, stage: str) -> str | None:
        entry = self.phases.get(stage)
        return entry.get("state") if isinstance(entry, dict) else None

    def phase_started_at(self, stage: str) -> str | None:
        entry = self.phases.get(stage)
        return entry.get("started_at") if isinstance(entry, dict) else None

    def elapsed_seconds(self) -> float | None:
        """自 started_at 起的秒数；无 started_at → None。"""
        return _elapsed(self.started_at)

    def stage_elapsed_seconds(self) -> float | None:
        """自 stage_started_at 起的秒数；无 → None。"""
        return _elapsed(self.stage_started_at)

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "stage": self.stage,
            "agent": self.agent,
            "started_at": self.started_at,
            "stage_started_at": self.stage_started_at,
            "last_activity_at": self.last_activity_at,
            "updated_at": self.updated_at,
            "report_path": self.report_path,
            "phases": self.phases,
        }


def _elapsed(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0.0, (datetime.now() - dt).total_seconds())


def read_runtime_state(output_dir: Path | str) -> RuntimeState | None:
    """读取 <output_dir>/task.json 为 RuntimeState。

    - task.json 不存在 → None
    - task.json 损坏 → 抛 LifecycleError（不静默吞掉）
    - 老 task.json（无 runtime 字段）→ 正常返回（缺失字段为 None / {}）
    """
    data = read_status(Path(output_dir))
    if data is None:
        return None
    return RuntimeState(
        task_id=data.get("task_id"),
        status=data.get("status"),
        stage=data.get("stage"),
        agent=data.get("agent"),
        started_at=data.get("started_at"),
        stage_started_at=data.get("stage_started_at"),
        last_activity_at=data.get("last_activity_at"),
        updated_at=data.get("updated_at"),
        report_path=data.get("report_path"),
        phases=data.get("phases") or {},
    )
