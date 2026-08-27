"""AAF Bridge — Phase D 进度估算（纯函数，可脱离 tkinter 单测）。

职责（冻结设计 §4 / §15 Phase D）：
- 集中定义六阶段静态权重（§4.2，合计 100）
- 由阶段事实（stage_states 输出）+ lifecycle status + 阶段已用时长，
  确定性估算整体进度百分比（§4.1.2–4.1.5）
- 只读估算：绝不写 task.json / run.json / route.json / boundary.json / REPORT.md

边界（设计 §4.1）：
- Stage State（阶段事实）与 Estimated Percentage（估算百分比）严格分离；
  本模块只产出估算值，阶段事实仍由 status_window.stage_states 提供
- 不实现 ETA / 剩余时间 / 动态权重校准（RW-005 数据未上线前禁止）

收敛规则（§4.1.5 强制性）：
- SUCCESS → 100%（已完成）
- WAITING → 停在已完成（SUCCESS）阶段权重和（等待处理，不增长）
- FAILED  → 停在失败阶段之前（失败阶段标 ✗；进行中阶段的部分估算不计入）
- CANCELLED → 停在取消时刻的权重和（已取消，不再变化，**不显示 100%**）
- 无任务 / task.json 缺失 → 0（暂无进度信息）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# 阶段权重（冻结设计 §4.2 —— 集中定义、可单测、不散落在 UI code）
# ---------------------------------------------------------------------------
PHASE_WEIGHTS = {
    "VALIDATION": 5,
    "BOUNDARY": 5,
    "HERMES": 45,
    "WORKBUDDY": 20,
    "CODEX": 20,
    "REPORT": 5,
}
assert sum(PHASE_WEIGHTS.values()) == 100, "阶段权重合计必须为 100（设计 §4.2）"

# 进行中阶段内部有限平滑（设计 §4.1.4）：
# 0% → 50% 线性（仅基于该阶段自身已用时长），固定上限 60 分钟为满分，超过后停在 50%。
STAGE_RUNNING_MAX_FRACTION = 0.5
STAGE_SMOOTH_FULL_SECONDS = 3600  # 60 分钟

# 中文文案（设计 §12.1 wireframe / §11.1 文案表）
PROGRESS_LABEL = "整体进度"
ESTIMATE_HINT = "估算"
NO_INFO_TEXT = "整体进度：暂无进度信息"
DONE_TEXT = "整体进度：100%（已完成）"


@dataclass
class ProgressEstimate:
    """一次确定性估算结果（全部为展示就绪值）。"""

    percent: int  # 0..100
    credits: dict = field(default_factory=dict)  # {stage: 0..权重}（信息性）


def running_fraction(elapsed_seconds: float | None) -> float:
    """进行中阶段内部部分进度比例（0.0～0.5）。

    线性：0s → 0.0；STAGE_SMOOTH_FULL_SECONDS（60 分钟）→ 0.5；此后固定 0.5。
    缺失 / 非法 → 0.0（保守，不凭空给进度）。
    """
    if elapsed_seconds is None or elapsed_seconds < 0:
        return 0.0
    return min(
        STAGE_RUNNING_MAX_FRACTION,
        elapsed_seconds / STAGE_SMOOTH_FULL_SECONDS * STAGE_RUNNING_MAX_FRACTION,
    )


def stage_credit(stage: str, state: str | None, elapsed_seconds: float | None = None) -> float:
    """单个阶段的进度 credit（0..该阶段权重）。

    - SUCCESS → 全权重
    - RUNNING → 权重 × running_fraction（内部有限平滑）
    - PENDING / WAITING / FAILED / SKIPPED / 未知 → 0
    """
    weight = float(PHASE_WEIGHTS.get(stage, 0))
    if state == "SUCCESS":
        return weight
    if state == "RUNNING":
        return weight * running_fraction(elapsed_seconds)
    return 0.0


def estimate_progress(
    strip: dict,
    status: str | None,
    stage_elapsed: dict | None = None,
) -> ProgressEstimate:
    """整体进度估算（确定性规则，设计 §4.1.2–4.1.5）。

    输入全部来自只读事实：stage_states() 的阶段状态、task.json 的 status、
    阶段已用时长。同一输入永远得到同一输出；百分比不随等待时间流逝而增长
    （除进行中阶段的固定线性平滑，其随时间单调递增，超过上限停在 50%）。

    单调性：
    - 正常推进序列（RUNNING → SUCCESS 过渡）单调不倒退；
    - 终态 FAILED / WAITING / CANCELLED 按收敛规则冻结在事实进度（可能低于失败前
      进行中阶段的估算值）——设计 §4.1.5 明确允许（"停在失败阶段之前"），
      属估算→事实的收敛，非持续推进，有测试覆盖。
    """
    stage_elapsed = stage_elapsed or {}
    if status == "SUCCESS":
        credits = {
            s: (float(PHASE_WEIGHTS.get(s, 0)) if st == "SUCCESS" else 0.0)
            for s, st in strip.items()
        }
        percent = 100
    elif status in ("WAITING", "FAILED", "CANCELLED"):
        # 收敛：冻结在已完成阶段权重和；进行中阶段的部分估算不计入。
        # CANCELLED（§4.1.5）：停在取消时刻的权重和，不显示 100%
        credits = {
            s: (float(PHASE_WEIGHTS.get(s, 0)) if st == "SUCCESS" else 0.0)
            for s, st in strip.items()
        }
        percent = round(sum(credits.values()))
    else:
        credits = {s: stage_credit(s, st, stage_elapsed.get(s)) for s, st in strip.items()}
        percent = round(sum(credits.values()))
    percent = min(100, max(0, percent))
    return ProgressEstimate(percent=percent, credits=credits)


def progress_text(percent: int, *, status: str | None = None, has_info: bool = True) -> str:
    """进度行完整文案（设计 §12.1：`整体进度：约 64%（估算）`）。"""
    if not has_info:
        return NO_INFO_TEXT
    if status == "SUCCESS":
        return DONE_TEXT
    return f"整体进度：约 {percent}%（{ESTIMATE_HINT}）"


def stage_share_text(strip: dict) -> str:
    """当前进行中阶段占比文本；无进行中阶段 → 空串（设计 §3 允许附加）。"""
    for stage, state in strip.items():
        if state == "RUNNING":
            return f"当前阶段占比：{int(PHASE_WEIGHTS.get(stage, 0))}%"
    return ""


def stage_elapsed_map(runtime) -> dict:
    """每个阶段的已用秒数（供 RUNNING 阶段内部平滑使用）。

    优先 phase entry 的 started_at（该阶段自身已用时长，设计 §4.1.4）；
    无 phases 记录时用 runtime.stage_started_at 兜底（仅当 stage 匹配）。
    缺失 → None（credit 保守计 0）。
    """
    result: dict = {}
    if runtime is None:
        return result
    for stage in PHASE_WEIGHTS:
        iso = None
        if hasattr(runtime, "phase_started_at"):
            try:
                iso = runtime.phase_started_at(stage)
            except Exception:
                iso = None
        if not iso and getattr(runtime, "stage", None) == stage:
            iso = getattr(runtime, "stage_started_at", None)
        result[stage] = _seconds_since(iso)
    return result


def _seconds_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0.0, (datetime.now() - dt).total_seconds())
