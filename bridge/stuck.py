"""AAF Bridge — Phase D suspected-stuck 最小观察（纯函数，可脱离 tkinter 单测）。

Lifecycle State vs Runtime Health 严格分离（RW-020 边界，设计 §5.3）：
- task.status = RUNNING 只表达 lifecycle 声称"仍在执行"，不证明 runner / agent 存活
- 本模块只做"可疑停滞"只读提示；绝不修改 task.json / run.json / 任何 canonical state
- 不实现 RW-020 完整 dead-runner ownership protocol / 自动修复（Phase E 范围）
- 不把 suspicious stuck 当作确定进程已死（用户需查看日志/任务目录进一步判断）

最小判定（可观察信号组合，TASK req 8 / 设计 §5.2）：
1. task.status == RUNNING（lifecycle 声称执行中）
2. last_activity_at 存在且距今 ≥ STUCK_LAST_ACTIVITY_THRESHOLD_SECONDS
   （无可观察活动）
「阶段未变」隐含在信号 2 中：runner 每次阶段 / agent 边界更新都会刷新
last_activity_at（task_lifecycle.update_status），last_activity 停滞即代表
阶段与活动均未推进。不把进程存活当作有进展的证据（设计 §5.3）。
"""
from __future__ import annotations

from datetime import datetime

# 阈值：设计 §5.2 —— last_activity_at 距今 ≥ 10 分钟（且阶段未变）→ suspected stuck。
# 集中常量化、可单测、不散落 magic number（TASK req 9）。
STUCK_LAST_ACTIVITY_THRESHOLD_SECONDS = 10 * 60

STUCK_WARNING_TEXT = "⚠ 任务可能已停滞"  # 设计 §11.1：suspected stuck → 疑似卡住
STUCK_HINT_LABEL = "疑似卡住"  # 设计 §11.1 文案表（技术字段保留英文原值）


def last_activity_age_seconds(iso: str | None, now: datetime | None = None) -> float | None:
    """last_activity_at → 距今秒数；缺失 / 非法 ISO → None（无法观察，不得臆断）。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    now = now or datetime.now()
    return max(0.0, (now - dt).total_seconds())


def suspected_stuck(runtime, now: datetime | None = None) -> tuple[bool, str, str]:
    """(是否可疑停滞, 警告文案, 详情文案)。

    - 仅提示；不改 canonical state（acceptance：stuck warning 不改任何状态）
    - SUCCESS / FAILED / WAITING / 无 last_activity_at / 未超过阈值 → 不判定
    - 只读观察：runner 是否真的存活不在本阶段判定范围（RW-020 明确边界）
    """
    if runtime is None or runtime.status != "RUNNING":
        return False, "", ""
    age = last_activity_age_seconds(runtime.last_activity_at, now)
    if age is None or age < STUCK_LAST_ACTIVITY_THRESHOLD_SECONDS:
        return False, "", ""
    minutes = int(age // 60)
    return True, STUCK_WARNING_TEXT, f"最近 {minutes} 分钟没有活动"
