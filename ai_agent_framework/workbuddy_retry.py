"""AAF — WorkBuddy Stage Reliability / Bounded Transient Retry（AAF-v0.4-TASK-011）。

Scope（严格执行，不扩大）：
- 只处理 WorkBuddy / CodeBuddy stage 的 **transport execution 层** transient recovery。
- Hermes / Codex stage 默认不重试（本模块只被 WorkBuddy 调用；无通用 orchestration
  redesign）。
- retry 永远复用同一次 invocation（same agent / same current CodeBuddy model &
  default config / same prompt / same workspace / same execution role）——绝不换模型、
  不换 provider、不升级付费层级、不修改用户配置。
- 业务 verdict（WorkBuddy 返回的 PASS / PASS_WITH_WARNING / FAIL）**不是** transport
  failure：一旦获得非空、可用的输出立即停止 retry，verdict 交给 Framework authority
  处理（structured result contract / blocking provenance / verdict parsing 不变）。
- 有界：max_attempts、per-attempt timeout、bounded backoff、overall stage budget。
- fail-closed：retries 用尽 → ``WorkBuddyRetriesExhausted``（runner → FRAMEWORK_ERROR；
  Codex 不运行；任务 WAITING）。
- 进程卫生：timeout → 整棵进程树 kill（Windows taskkill /PID /T /F）+ 有界等待 +
  管道排空（无 orphan / 无 zombie / 无 pipe leak / 无并发 child）。
- **confirmed-dead-before-retry（AAF-v0.4-TASK-011-FIX-001）**：timeout 的 attempt
  只有在 child 终止被**确认**（观察到 poll() 非 None / taskkill 树杀成功）且注册表
  ownership 释放后才允许 retry；终止无法确认 → cleanup failure / fail closed、
  绝不重试、child PID 保持注册（Registry Gate 防任何后续 spawn）。
- **single absolute stage deadline（AAF-v0.4-TASK-011-FIX-001）**：
  ``stage_deadline = stage_start + overall_stage_budget`` 是唯一绝对墙钟上限；
  attempt execution / backoff / taskkill wait / kill grace / communicate reap
  全部从同一 deadline 派生并被其裁剪；attempt timeout 预留 ``cleanup_reserve``
  有界清理窗口，绝不因清理而超出 budget。
- **Windows tree cleanup authority（AAF-v0.4-TASK-011-FIX-002）**：Windows 上
  cleanup 成功必须基于足够强的 process-tree evidence——taskkill /PID /T /F
  实际尝试且成功（或等价强证据）+ 顶层确认退出 + reap 完成/明确分类；只 kill
  顶层成功（或只观察顶层 poll() != None）**不是** safe cleanup（不得报告 fake
  tree success）。tree 未确认 → cleanup safety=UNKNOWN/FAILED → fail closed、
  不 retry、child PID 保持注册（Registry Gate）。
- **safe cleanup reserve minimum + attempt admission（FIX-002）**：
  ``AAF_WORKBUDDY_CLEANUP_RESERVE`` 被钳制到 ``MIN_SAFE_CLEANUP_RESERVE``
  下限（配置 reserve=0 也不能关闭 tree safety）；每次 attempt 启动前确认
  remaining budget > effective safe cleanup reserve + minimum useful attempt
  runtime，不足则不启动（cleanup budget 在启动 attempt 之前就保留）。

Failure classification（只基于真实 CLI evidence，不凭空造字符串规则）：
RETRYABLE_TRANSIENT：
- ``TimeoutExpired``（CLOSURE-003 真实形态：3600s 硬等待）
- exit=0 + stdout 为空（CLOSURE-002 真实形态）
- CodeBuddy 自身 stderr 的 gateway placeholder-only 证据
  （``Empty stream: upstream gateway sent only placeholder chunks without any
    model output (chunks=N, bytes=N)``——CLOSURE-002 真实 stderr）
NON_RETRYABLE（快速失败，不无意义重试）：
- missing executable（MISSING_COMMAND）
- 非零退出且无 transient gateway evidence（unauthenticated / invalid config /
  CLI fatal 等永久性证据）
- spawn / pipe 级 fatal

遥测：每次执行返回完整 attempt telemetry（machine artifact ``workbuddy_attempts.json``
由 runner 持久化；REPORT 只含紧凑摘要）。最终只有单一 canonical workbuddy_result；
attempt logs 是 supporting evidence。

v0.5 COST-STOP-LOSS-001 扩展（最小可审计止损；语义全部向后兼容）：
- 429 / rate limit / quota evidence（CLI 文案）→ 独立分类 ``rate_limit``/``quota``：
  reset 窗口可解析且落在剩余安全 budget 内 → 有界等到 reset 再试一次；否则**尽早
  fail closed**（RATE_LIMIT/QUOTA terminal reason），绝不烧剩余 attempts / 空转到
  stage budget。
- repeated no-progress（连续 empty-output / 相同失败原因 ≥ 3，仅当 operator 配置
  max_attempts>2 时生效）→ 提前终止（NO_PROGRESS）。默认 2-attempt 语义零变化。
- 全部终态带机器可读 ``telemetry.terminal_reason``（stop_loss 词汇）；timeout 清理
  排出的 partial output 含明确 tool/test markers → TOOL_OR_TEST_STILL_ACTIVE。
- no-progress 判定只作用于"已完成的失败 attempt 之间"，绝不打断在跑 tool/test。
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .subprocess_utils import no_console_kwargs
from . import stop_loss as stop_loss_mod

# ---------------------------------------------------------------------------
# 可测试别名（monkeypatch 只影响本模块引用，不影响全局 subprocess）
# ---------------------------------------------------------------------------
_Popen = subprocess.Popen
_TimeoutExpired = subprocess.TimeoutExpired

# ---------------------------------------------------------------------------
# 默认策略（安全默认值，env 可覆盖；基于本项目已记录的真实 WorkBuddy stage
# timing——成功 stage 实测 ~556s（AAF-v0.4-TASK-010-FIX-001），故 per-attempt
# timeout 默认 900s 留足余量，不再只能依赖统一 3600s 硬等待）
# ---------------------------------------------------------------------------
DEFAULT_MAX_ATTEMPTS = 2  # initial + 1 retry
DEFAULT_PER_ATTEMPT_TIMEOUT = 900.0  # 秒（实测成功 stage ~556s）
DEFAULT_BACKOFF_SECONDS = 30.0  # 有界确定性 backoff（不得 tight loop 撞 gateway）
DEFAULT_OVERALL_STAGE_BUDGET = 0.0  # 0 → 按公式计算（见 load_workbuddy_policy）
# 清理预留（TASK-011-FIX-001 Requirement 10）：attempt timeout 不得超过
# remaining - cleanup_reserve，保证 timeout 后仍有界清理窗口（taskkill ≤30s +
# kill grace ≤5s + reap 2×5s + 余量 ≈ 45~50s，默认 60s 安全覆盖）。
DEFAULT_CLEANUP_RESERVE = 60.0
# FIX-002 Requirement 3/4/12：安全清理预留下限——Windows process-tree cleanup
# （taskkill /T /F ≤30s + kill grace ≤5s + reap 2×5s + 余量）的最低有界窗口。
# 任何配置（env）或构造的 cleanup_reserve 都不得低于此值（policy 加载钳制 +
# orchestrator admission 双保险）；低于它时按它计算，保证真实 attempt 一旦
# 启动必然预留足够 bounded cleanup window（Requirement 3 最终保证）。
MIN_SAFE_CLEANUP_RESERVE = 60.0

ENV_MAX_ATTEMPTS = "AAF_WORKBUDDY_MAX_ATTEMPTS"
ENV_TIMEOUT = "AAF_WORKBUDDY_TIMEOUT"
ENV_BACKOFF = "AAF_WORKBUDDY_BACKOFF"
ENV_STAGE_BUDGET = "AAF_WORKBUDDY_STAGE_BUDGET"
ENV_CLEANUP_RESERVE = "AAF_WORKBUDDY_CLEANUP_RESERVE"
ENV_DISABLE = "AAF_WORKBUDDY_RETRY"  # 0/false/off → 单次 attempt（无 retry，旧语义）
_DISABLED_VALUES = frozenset({"0", "false", "off", "no", "disable", "disabled"})

# 有界清理参数（TASK-011-FIX-001 Requirement 12/14：全部被 stage deadline 裁剪，
# 无独立全尺寸等待可静默超出 budget；清理自身有界，绝不无限 wait/poll/communicate）
TASKKILL_TIMEOUT = 30.0
KILL_GRACE_SECONDS = 5.0
REAP_COMMUNICATE_TIMEOUT = 5.0
REAP_ATTEMPTS = 2
POLL_INTERVAL = 0.05
MIN_ATTEMPT_TIMEOUT = 0.05  # 低于此值不再启动 attempt（budget 不足，fail closed）
# FIX-002 Requirement 6：attempt admission 的“minimum useful attempt runtime”——
# 剩余 budget 必须 > safe cleanup reserve + 该值才允许启动 attempt。
MIN_ATTEMPT_RUNTIME = MIN_ATTEMPT_TIMEOUT

# 已知 transient gateway evidence（CodeBuddy CLI 自身输出；CLOSURE-002 真实 stderr）
_PLACEHOLDER_GATEWAY_RES = (
    re.compile(r"(?i)empty\s+stream"),
    re.compile(r"(?i)placeholder\s+chunks?"),
    re.compile(r"(?i)no\s+model\s+output"),
)

FAILURE_CLASS_RETRYABLE = "retryable_transient"
FAILURE_CLASS_NON_RETRYABLE = "non_retryable"
# v0.5 COST-STOP-LOSS-001：限频/quota evidence 独立分类（429 / rate limit /
# quota 文案；evidence-based，见 stop_loss.detect_rate_limit_evidence）。它们既
# 不是"等一下就好的瞬态"，也不是"永久配置错误"——orchestrator 按 reset 窗口与
# remaining budget 决定有界等待或尽早 fail closed（不空转到 stage budget）。
FAILURE_CLASS_RATE_LIMIT = "rate_limit"
FAILURE_CLASS_QUOTA = "quota"

# v0.5 COST-STOP-LOSS-001：repeated no-progress 提前止损阈值（连续 attempt 级
# evidence 判定）。默认 2 次 attempt 的既有语义完全保留（阈值 3 > 默认
# max_attempts 2）；仅当 operator 配置更高 max_attempts 时，连续 3 次
# empty-output / 相同失败原因不再无意义烧掉剩余 attempts / stage budget。
# （合规长任务不受影响：本判定只作用于"已完成的失败 attempt 之间"，绝不打断
# 在跑的 tool/test；实测存在 empty,empty,success 恢复序列 → 阈值定为 3。）
NO_PROGRESS_EARLY_STOP_EMPTY_SEQUENCE = 3
NO_PROGRESS_EARLY_STOP_IDENTICAL_SEQUENCE = 3

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"
OUTCOME_PERMANENT_FAILURE = "PERMANENT_FAILURE"
OUTCOME_CLEANUP_FAILURE = "CLEANUP_FAILURE"  # FIX-001：child 终止未确认 → 安全失败


class FailureClass(Enum):
    RETRYABLE_TRANSIENT = FAILURE_CLASS_RETRYABLE
    NON_RETRYABLE = FAILURE_CLASS_NON_RETRYABLE
    # v0.5 COST-STOP-LOSS-001：429 / rate limit / quota evidence（CLI 文案识别）
    RATE_LIMIT = FAILURE_CLASS_RATE_LIMIT
    QUOTA = FAILURE_CLASS_QUOTA


@dataclass(frozen=True)
class WorkBuddyRetryPolicy:
    """有界 retry 策略（配置 / 可测试）。"""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    per_attempt_timeout: float = DEFAULT_PER_ATTEMPT_TIMEOUT
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    overall_stage_budget: float = DEFAULT_OVERALL_STAGE_BUDGET
    # FIX-001 Requirement 10：attempt timeout 从 remaining 中预留的有界清理窗口
    # （attempt_timeout <= remaining - cleanup_reserve）
    cleanup_reserve: float = DEFAULT_CLEANUP_RESERVE


@dataclass(frozen=True)
class CleanupResult:
    """进程清理的结构化结果（Requirement 4：callers 必须基于此结果行动）。

    - ``terminated_confirmed``: 进程不再存活被**观察到**（poll() 非 None）——
      不是“kill() 被调用”，而是终止被确认（Requirement 5）。
    - ``reaped_confirmed``: 管道已排空 / communicate 已返回（资源已回收）。
    - ``method``: 确认途径（already-exited / taskkill-tree / taskkill+kill /
      kill / none）。
    - ``failure_reason``: 未确认时的人类可读原因（否则 None）。
    - FIX-002 Requirement 1/2/8（Windows process-tree cleanup authority）：
      ``tree_confirmed``: CodeBuddy descendant process tree 终止被确认（Windows
      下 = taskkill /T /F 尝试成功或等价强证据 + 顶层确认退出）；非 Windows
      恒为 True（平台差异显式）。
      ``taskkill_attempted`` / ``taskkill_success``: taskkill /T /F 是否实际
      尝试 / 是否返回成功（Windows 树级证据原语；非 Windows 恒为 False）。
    """

    terminated_confirmed: bool
    reaped_confirmed: bool
    method: str
    failure_reason: str | None = None
    tree_confirmed: bool = False
    taskkill_attempted: bool = False
    taskkill_success: bool = False


@dataclass
class AttemptRecord:
    """单次 attempt 的完整 evidence（machine artifact 逐条记录）。"""

    attempt_index: int
    status: str  # SUCCESS / FAILED
    failure_class: str | None = None  # retryable_transient / non_retryable
    retry_reason: str | None = None
    timed_out: bool = False
    stdout_empty: bool = False
    exit_code: int | None = None
    timeout_used: float = 0.0
    elapsed_seconds: float = 0.0
    stderr_tail: str = ""
    # FIX-001 Requirement 19：清理证据（normal 退出 → cleanup_confirmed=True /
    # method=natural-exit；timeout 清理 → 按 CleanupResult 填）
    cleanup_confirmed: bool | None = None
    cleanup_failure: bool = False
    cleanup_method: str | None = None
    cleanup_reason: str | None = None
    # FIX-002 Requirement 8/17：Windows process-tree cleanup evidence 遥测
    # （tree 是否确认、taskkill /T /F 是否尝试 / 是否成功；非 Windows 语义见
    # CleanupResult —— taskkill 字段恒 False、tree_confirmed 恒 True）
    cleanup_tree_confirmed: bool | None = None
    taskkill_attempted: bool | None = None
    taskkill_success: bool | None = None
    # v0.5 COST-STOP-LOSS-001：限频 attempt 的 reset 窗口（秒；单位明确才解析，
    # 无/不可解析 → None = 无法证明可等 → orchestrator 尽早 fail closed）
    rate_limit_reset_seconds: float | None = None
    # v0.5 COST-STOP-LOSS-001：timeout attempt 清理时排出的 partial output 是否
    # 含明确 tool/test 活动 markers（TOOL_OR_TEST_STILL_ACTIVE 判定 evidence；
    # 启发式，absent ≠ 无活动——absent → ATTEMPT_TIMEOUT）
    timeout_activity_markers: bool = False

    def to_dict(self) -> dict:
        return {
            "attempt_index": self.attempt_index,
            "status": self.status,
            "failure_class": self.failure_class,
            "retry_reason": self.retry_reason,
            "timed_out": self.timed_out,
            "stdout_empty": self.stdout_empty,
            "exit_code": self.exit_code,
            "timeout_used": round(float(self.timeout_used), 3),
            "elapsed_seconds": round(float(self.elapsed_seconds), 3),
            "stderr_tail": self.stderr_tail,
            "cleanup_confirmed": self.cleanup_confirmed,
            "cleanup_failure": self.cleanup_failure,
            "cleanup_method": self.cleanup_method,
            "cleanup_reason": self.cleanup_reason,
            "cleanup_tree_confirmed": self.cleanup_tree_confirmed,
            "taskkill_attempted": self.taskkill_attempted,
            "taskkill_success": self.taskkill_success,
            "rate_limit_reset_seconds": self.rate_limit_reset_seconds,
            "timeout_activity_markers": self.timeout_activity_markers,
        }


@dataclass
class AttemptOutcome:
    output: str | None
    record: AttemptRecord


class WorkBuddyStageError(RuntimeError):
    """retry 层终端错误基类；携带完整 telemetry（runner 持久化为 machine artifact）。"""

    def __init__(self, message: str, telemetry: dict | None = None):
        super().__init__(message)
        self.telemetry: dict = telemetry or {}


class WorkBuddyPermanentError(WorkBuddyStageError):
    """NON_RETRYABLE：快速失败，不无意义重试（missing exe / auth-config 永久错误等）。"""


class WorkBuddyRetriesExhausted(WorkBuddyStageError):
    """retryable failures 用尽全部有界 attempt → fail closed。"""


class WorkBuddyConcurrencyError(WorkBuddyStageError):
    """内部不变量违规：spawn 前仍有遗留 active child（fail closed）。"""


class WorkBuddyCleanupError(WorkBuddyStageError):
    """清理安全失败（FIX-001 Requirement 3）：child 终止未能确认 → fail closed、
    绝不重试、child PID 保持注册（不得降级为普通 TimeoutExpired 后重试）。"""


# ---------------------------------------------------------------------------
# 并发/孤儿防护（module-level registry；单线程 runner 内安全）
# ---------------------------------------------------------------------------
_ACTIVE_CHILD_PIDS: set[int] = set()
_CHILD_LOCK = threading.Lock()


def active_child_pids() -> list[int]:
    """当前已注册、尚未结束的 WorkBuddy child pid 列表（调试 / 测试用）。"""
    with _CHILD_LOCK:
        return sorted(_ACTIVE_CHILD_PIDS)


def _assert_no_active_children() -> None:
    """spawn 前不变量：上一 attempt 的 child 必须已结束并注销（无并发 / 无 orphan）。"""
    with _CHILD_LOCK:
        stale = sorted(_ACTIVE_CHILD_PIDS)
    if stale:
        raise WorkBuddyConcurrencyError(
            "active WorkBuddy child(ren) still registered before spawn: "
            f"{stale}（并发/遗留 child 不变量违规，fail closed）"
        )


def _register_child(pid: int) -> None:
    with _CHILD_LOCK:
        _ACTIVE_CHILD_PIDS.add(pid)


def _unregister_child(pid: int) -> None:
    with _CHILD_LOCK:
        _ACTIVE_CHILD_PIDS.discard(pid)


# ---------------------------------------------------------------------------
# Failure classification（只基于实际 CLI evidence）
# ---------------------------------------------------------------------------


def _is_placeholder_gateway(stderr: str) -> bool:
    """CodeBuddy 自身 gateway placeholder-only 证据（CLOSURE-002 真实 stderr 形态）。"""
    return bool(stderr) and any(p.search(stderr) for p in _PLACEHOLDER_GATEWAY_RES)


def classify_failure(
    *, timed_out: bool, returncode: int | None, stdout: str, stderr: str
) -> tuple[FailureClass, str]:
    """把一次失败 attempt 分类为 retryable transient / non-retryable。

    规则只基于真实 incident evidence，不得凭空造字符串规则：
    - 429 / rate limit / quota 文案（v0.5 COST-STOP-LOSS-001）→ RATE_LIMIT/QUOTA
      （独立分类；orchestrator 按 reset 窗口决定有界等待或尽早 fail closed——
       audit 实测 429 被误归为 "empty output (exit=0)" 后重试未等 reset → 徒劳）
    - TimeoutExpired（CLOSURE-003）→ retryable
    - exit=0 + 空 stdout（CLOSURE-002）→ retryable
    - 任何含 gateway placeholder-only evidence 的 stderr → retryable
    - 其余（非零退出且无 transient evidence：unauthenticated / invalid config /
      CLI fatal 等永久性）→ non_retryable
    """
    # v0.5 COST-STOP-LOSS-001：限频/quota evidence 优先于通用分类（429 常常表现为
    # exit=0 + 空 stdout 或非零退出 + stderr 文案——都先做限频识别）
    evidence_kind, evidence_detail = stop_loss_mod.detect_rate_limit_evidence(
        f"{stdout}\n{stderr}"
    )
    if evidence_kind is not None:
        cls = (
            FailureClass.QUOTA
            if evidence_kind == stop_loss_mod.STOP_REASON_QUOTA
            else FailureClass.RATE_LIMIT
        )
        return cls, evidence_detail or evidence_kind.lower()
    if timed_out:
        return FailureClass.RETRYABLE_TRANSIENT, "TimeoutExpired"
    if returncode == 0 and not (stdout or "").strip():
        if _is_placeholder_gateway(stderr):
            return (
                FailureClass.RETRYABLE_TRANSIENT,
                "empty output (exit=0); upstream gateway placeholder-only",
            )
        return FailureClass.RETRYABLE_TRANSIENT, "empty output (exit=0)"
    if _is_placeholder_gateway(stderr):
        return FailureClass.RETRYABLE_TRANSIENT, "upstream gateway placeholder-only output"
    return FailureClass.NON_RETRYABLE, f"exit={returncode}"


# ---------------------------------------------------------------------------
# 策略加载（env 可配置；非法值回退默认；绝不无限重试）
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_workbuddy_policy() -> WorkBuddyRetryPolicy:
    """读取 env 配置的 WorkBuddy retry 策略（安全默认值；可测试）。

    - ``AAF_WORKBUDDY_RETRY=0`` → max_attempts 强制为 1（无自动 retry，旧语义）。
    - ``AAF_WORKBUDDY_STAGE_BUDGET`` 未配置/<=0 → 按公式
      ``max_attempts*per_attempt_timeout + (max_attempts-1)*backoff`` 计算，
      保证默认策略下 budget 恒 >= 全部 attempts + backoff 的数学总和；
      且 budget 至少容纳一次完整 attempt + cleanup reserve（FIX-001 Req 10）。
    """
    max_attempts = max(1, _env_int(ENV_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS))
    per_attempt_timeout = max(1.0, _env_float(ENV_TIMEOUT, DEFAULT_PER_ATTEMPT_TIMEOUT))
    backoff = max(0.0, _env_float(ENV_BACKOFF, DEFAULT_BACKOFF_SECONDS))
    cleanup_reserve = max(0.0, _env_float(ENV_CLEANUP_RESERVE, DEFAULT_CLEANUP_RESERVE))
    # FIX-002 Requirement 3/4/12（Config Safety）：用户配置
    # （AAF_WORKBUDDY_CLEANUP_RESERVE=0 或其它过低值）不得关闭 process-tree
    # safety invariant —— 钳制到 MIN_SAFE_CLEANUP_RESERVE（Option B: clamp）。
    # 任何真实 attempt 一旦启动，必须预留足够 bounded cleanup window 使
    # Windows tree cleanup path（taskkill /T /F）有机会安全执行。
    cleanup_reserve = max(cleanup_reserve, MIN_SAFE_CLEANUP_RESERVE)
    budget = _env_float(ENV_STAGE_BUDGET, DEFAULT_OVERALL_STAGE_BUDGET)
    if budget <= 0:
        budget = max_attempts * per_attempt_timeout + (max_attempts - 1) * backoff
    budget = max(budget, per_attempt_timeout + cleanup_reserve)  # 至少一次完整 attempt + 清理窗口
    if os.environ.get(ENV_DISABLE, "").strip().lower() in _DISABLED_VALUES:
        max_attempts = 1
    return WorkBuddyRetryPolicy(
        max_attempts=max_attempts,
        per_attempt_timeout=per_attempt_timeout,
        backoff_seconds=backoff,
        overall_stage_budget=budget,
        cleanup_reserve=cleanup_reserve,
    )


# ---------------------------------------------------------------------------
# 进程清理（Windows 行为；有界；全部被 stage deadline 裁剪；返回结构化结果）
# ---------------------------------------------------------------------------


def _remaining_until(deadline: float | None) -> float | None:
    """从绝对 deadline 到现在的剩余秒数（None → 无 deadline 限制）。"""
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def _clipped_timeout(deadline: float | None, nominal: float) -> float:
    """把有界等待的 nominal 时长裁剪到剩余 deadline（Requirement 12）。"""
    remaining = _remaining_until(deadline)
    if remaining is None:
        return nominal
    return min(nominal, remaining)


def _taskkill(pid: int, timeout: float = TASKKILL_TIMEOUT) -> bool:
    """Windows: ``taskkill /PID <pid> /T /F``（整棵进程树）。失败 → False。

    timeout 由调用方裁剪到剩余 stage deadline（绝不独立全尺寸等待）。
    """
    try:
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=timeout,
            **no_console_kwargs(),
        )
        return r.returncode == 0
    except Exception:
        return False


@dataclass(frozen=True)
class TreeKillOutcome:
    """``_kill_process_tree`` 的结构化结果（FIX-002 Requirement 1/2/8/9）。

    - ``terminated_confirmed``: 顶层 proc 终止被观察到（poll() 非 None）。
    - ``tree_confirmed``: CodeBuddy descendant process tree 终止被确认。
      Windows：仅当 taskkill /T /F 实际尝试且成功（或等价强证据）+ 顶层确认
      退出；只 kill 顶层成功 ≠ tree confirmed。非 Windows：恒等于
      terminated_confirmed（平台差异显式）。
    - ``method``: 确认途径（already-exited / taskkill-tree / taskkill+kill /
      kill / none）。
    - ``taskkill_attempted`` / ``taskkill_success``: Windows 树级证据原语。
    - ``failure_reason``: tree/termination 未确认时的人类可读原因（否则 None）。
    """

    terminated_confirmed: bool
    tree_confirmed: bool
    method: str
    taskkill_attempted: bool = False
    taskkill_success: bool = False
    failure_reason: str | None = None


def _kill_process_tree(proc, deadline: float | None) -> TreeKillOutcome:
    """确保 child（Windows 下为整棵进程树）已死，并**确认**终止。

    返回 TreeKillOutcome：
    - ``terminated_confirmed=True`` 仅当终止被**观察到**（final liveness check：
      ``proc.poll() is not None``），不是“kill() 被调用”就算成功（Requirement 5）。
    - FIX-002 Requirement 1/2（Windows Tree Cleanup Authority）：Windows 上
      tree cleanup 成功必须基于足够强的 process-tree evidence——taskkill /T /F
      实际尝试 + 成功 + 顶层确认退出。以下情况 **不得** 报告 safe cleanup：
      taskkill 未执行 / taskkill 无可验证成功证据 / 只调用 proc.kill() /
      只观察顶层 poll() != None。tree 无法确认 → tree_confirmed=False，
      callers 必须 fail closed（no retry、registry 保留）。
    - 非 Windows：保持原语义（直接子进程 kill 确认即安全；平台差异显式）。
    - kill grace 轮询被剩余 deadline 裁剪（Requirement 9/12）；清理自身有界
      （Requirement 14：无无限 poll 循环）。taskkill 同样受绝对 deadline 约束
      （Requirement 7），但 admission + cleanup reserve 保证正常 timeout
      cleanup 时仍有真实 taskkill 时间窗口（Requirement 5）。
    """
    is_nt = os.name == "nt"
    if proc.poll() is not None:
        if is_nt:
            # 顶层自行退出：无 taskkill 树级证据 → 无法证明 descendant tree 已终止。
            # （不得把顶层退出自动等价为整树安全终止）
            return TreeKillOutcome(
                True, False, "already-exited", False, False,
                "top-level process already exited but Windows descendant process "
                "tree termination unconfirmed (no taskkill /T /F evidence)",
            )
        return TreeKillOutcome(True, True, "already-exited")
    taskkill_attempted = False
    taskkill_success = False
    if is_nt:
        # FIX-002 Requirement 7：taskkill 受绝对 deadline 约束（裁剪到剩余）；
        # Requirement 11：deadline 耗尽（timeout<=0）→ taskkill 不执行 —— 但
        # 后续 fallback 顶层 kill 成功也**不**构成 tree confirmed（fail closed）。
        taskkill_timeout = _clipped_timeout(deadline, TASKKILL_TIMEOUT)
        taskkill_attempted = taskkill_timeout > 0
        if taskkill_attempted:
            taskkill_success = _taskkill(proc.pid, timeout=taskkill_timeout)
        if taskkill_success:
            # taskkill /T /F 返回成功（树杀已发出）：有界等待顶层退出——
            # 观察到顶层退出后，taskkill 成功 + 顶层确认退出 = 最强树级证据
            grace = _clipped_timeout(deadline, KILL_GRACE_SECONDS)
            poll_deadline = time.monotonic() + grace
            while time.monotonic() < poll_deadline:
                if proc.poll() is not None:
                    return TreeKillOutcome(True, True, "taskkill-tree", True, True)
                time.sleep(POLL_INTERVAL)
            # taskkill 成功但顶层尚未观察到退出 → 继续 fallback kill（下面统一收口）
    # fallback：顶层 kill（Requirement 9——proc.kill() 可以作为 fallback，但
    # 在 Windows 上 fallback 顶层 kill 成功 ≠ process-tree cleanup confirmed）
    try:
        proc.kill()
    except Exception:
        pass
    grace = _clipped_timeout(deadline, KILL_GRACE_SECONDS)
    poll_deadline = time.monotonic() + grace
    while time.monotonic() < poll_deadline:
        if proc.poll() is not None:
            if is_nt:
                if taskkill_success:
                    # taskkill 成功（树杀证据）+ 顶层已确认退出 = 等价强证据
                    return TreeKillOutcome(True, True, "taskkill+kill", True, True)
                return TreeKillOutcome(
                    True, False, "kill", taskkill_attempted, taskkill_success,
                    "top-level process killed/confirmed exited but Windows "
                    "descendant process tree termination unconfirmed (taskkill "
                    "/T /F not verified)",
                )
            return TreeKillOutcome(True, True, "kill")
        time.sleep(POLL_INTERVAL)
    # grace 耗尽：最后再尝试一次直接 kill，然后必须观察到终止
    try:
        proc.kill()
    except Exception:
        pass
    if proc.poll() is not None:
        if is_nt:
            if taskkill_success:
                return TreeKillOutcome(True, True, "taskkill+kill", True, True)
            return TreeKillOutcome(
                True, False, "kill", taskkill_attempted, taskkill_success,
                "top-level process killed/confirmed exited but Windows descendant "
                "process tree termination unconfirmed (taskkill /T /F not verified)",
            )
        return TreeKillOutcome(True, True, "kill")
    return TreeKillOutcome(
        False, False, "none", taskkill_attempted, taskkill_success,
        "process termination could not be confirmed after taskkill/kill sequence "
        "(child may still be alive; fail closed, no retry)",
    )


def _cleanup_is_safe(cleanup: CleanupResult) -> bool:
    """FIX-002 Requirement 2/9/10：cleanup safety contract 判定。

    Windows：terminated_confirmed **且** tree_confirmed 才允许释放 ownership /
    允许 retry（Registry Gate）；只 kill 顶层成功（或只观察顶层退出）不是
    safe cleanup。非 Windows：保持原语义（terminated_confirmed 即安全）——
    平台差异显式（Requirement 15）。
    """
    if os.name == "nt":
        return cleanup.terminated_confirmed and cleanup.tree_confirmed
    return cleanup.terminated_confirmed


def _terminate_and_reap(proc, deadline: float | None) -> tuple[str, str, CleanupResult]:
    """kill 进程树 + 确认终止 + 排空 stdin/stdout/stderr 管道 + reap。

    返回 (stdout, stderr, CleanupResult)。绝不抛出（timeout 清理路径不得掩盖
    原始失败）。语义（FIX-001 Requirement 1/3/4/12 + FIX-002 Requirement 1/2/8）：
    - Windows：cleanup safety = terminated_confirmed **且** tree_confirmed
      （taskkill /T /F 树级证据）；两者缺一 → ``_cleanup_is_safe()=False``，
      callers 必须 fail closed（不得降级为普通 TimeoutExpired 后重试）。
    - 非 Windows：终止被确认 → 有界排空管道（communicate 裁剪到剩余 deadline）；
      reap 失败如实记录 ``reaped_confirmed=False``（进程已死，无并发风险，
      如实分类）。
    - 终止/tree **未**确认 → ``terminated_confirmed/tree_confirmed=False`` +
      failure_reason；callers 必须 fail closed（不得降级为普通 TimeoutExpired
      后重试）。
    """
    outcome = _kill_process_tree(proc, deadline)
    stdout, stderr = "", ""
    reaped = False
    failure_reason: str | None = outcome.failure_reason
    safe = outcome.terminated_confirmed and (
        os.name != "nt" or outcome.tree_confirmed
    )
    if safe:
        for _ in range(REAP_ATTEMPTS):
            comm_timeout = _clipped_timeout(deadline, REAP_COMMUNICATE_TIMEOUT)
            if comm_timeout <= 0:
                break
            try:
                stdout, stderr = proc.communicate(timeout=comm_timeout)
                reaped = True
                break
            except Exception:
                time.sleep(POLL_INTERVAL)
                try:
                    proc.kill()
                except Exception:
                    pass
        if not reaped:
            failure_reason = (
                "process termination confirmed but pipes could not be drained "
                "(reap unconfirmed; no concurrency risk)"
            )
    elif failure_reason is None:
        failure_reason = (
            "process termination could not be confirmed after taskkill/kill "
            "sequence (child may still be alive; fail closed, no retry)"
        )
    return stdout, stderr, CleanupResult(
        terminated_confirmed=outcome.terminated_confirmed,
        reaped_confirmed=reaped,
        method=outcome.method,
        failure_reason=failure_reason,
        tree_confirmed=outcome.tree_confirmed,
        taskkill_attempted=outcome.taskkill_attempted,
        taskkill_success=outcome.taskkill_success,
    )


# ---------------------------------------------------------------------------
# 单次 attempt（Popen 显式 timeout 处理，保证可清理）
# ---------------------------------------------------------------------------


def _stderr_tail(stderr: str, limit: int = 600) -> str:
    lines = (stderr or "").strip().splitlines()
    return ("\n".join(lines[-5:]))[-limit:]


def _run_single_attempt(
    args: list[str],
    env: dict,
    stdin_data: str | None,
    workspace: Path,
    timeout: float,
    deadline: float | None = None,
) -> AttemptOutcome:
    """执行一次 WorkBuddy invocation（Popen；显式 timeout + 确认式清理）。

    FIX-001（Requirement 1/2/3/5）：
    - child 一旦 spawn 即注册；**只有**终止被确认后才注销（confirmed-dead 才释放
      ownership；never ``alive child + absent registry + retry permitted``）。
    - timeout / I/O 失败路径执行确认式清理（``_terminate_and_reap`` 返回
      CleanupResult）：terminated_confirmed → 注销 + 正常分类（TimeoutExpired 等）；
      **未确认 → cleanup_failure=True、PID 保持注册**（Registry Gate 保留），
      分类为 NON_RETRYABLE 安全失败——绝不降级为普通 TimeoutExpired 后重试。
    - 清理等待（taskkill / grace / communicate）全部由 deadline 裁剪。

    返回 AttemptOutcome(output, record)：成功 → output 非空、record.status=SUCCESS；
    失败 → output=None、record 携带 failure_class / retry_reason / cleanup evidence。
    """
    start = time.monotonic()
    proc = None
    stdout = ""
    stderr = ""
    timed_out = False
    spawn_error: str | None = None
    cleanup: CleanupResult | None = None
    # v0.5 COST-STOP-LOSS-001：timeout attempt 的 tool/test-activity markers 与
    # rate-limit reset 窗口（attempt 级 evidence；orchestrator/终态分类消费）
    timeout_activity_markers = False
    rate_limit_reset_seconds: float | None = None
    try:
        _assert_no_active_children()
        try:
            proc = _Popen(
                args,
                cwd=str(workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **no_console_kwargs(),
            )
        except (OSError, ValueError) as exc:
            spawn_error = f"process start failed: {type(exc).__name__}: {exc}"
            proc = None
        if proc is not None:
            _register_child(proc.pid)
            try:
                stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
            except _TimeoutExpired:
                timed_out = True
                stdout, stderr, cleanup = _terminate_and_reap(proc, deadline)
            except (OSError, ValueError) as exc:
                spawn_error = f"process I/O failed: {type(exc).__name__}: {exc}"
                stdout, stderr, cleanup = _terminate_and_reap(proc, deadline)
            # 注册表所有权（Requirement 2 + FIX-002 Requirement 10 Registry Gate）：
            # 只有 cleanup safety contract 满足（Windows = terminated **且**
            # tree 确认；非 Windows = terminated 确认）才注销；未确认 → 保持注册
            # —— 绝不能出现 alive/可能存活 child + 无 registry + retry
            if cleanup is not None:
                if _cleanup_is_safe(cleanup):
                    _unregister_child(proc.pid)
                # else: 保持注册（Windows tree 未确认同样不释放 ownership）
            else:
                # communicate 正常返回 → 进程已退出（returncode 非 None）且已 reap
                _unregister_child(proc.pid)
    finally:
        # 注意：这里**不**无条件注销（FIX-001 Requirement 2）——未确认终止的
        # child 必须保留在 registry，直到 terminal cleanup-failure 状态被处理。
        pass

    elapsed = round(time.monotonic() - start, 3)
    exit_code = proc.returncode if proc is not None else None
    stderr_tail = _stderr_tail(stderr)

    exited_naturally = proc is not None and cleanup is None and exit_code is not None
    if cleanup is not None:
        cleanup_safe = _cleanup_is_safe(cleanup)
        cleanup_confirmed = cleanup_safe and cleanup.reaped_confirmed
        cleanup_failure = not cleanup_safe
        cleanup_method = cleanup.method
        cleanup_reason = cleanup.failure_reason
        cleanup_tree_confirmed = cleanup.tree_confirmed
        taskkill_attempted = cleanup.taskkill_attempted
        taskkill_success = cleanup.taskkill_success
    elif exited_naturally:
        cleanup_confirmed, cleanup_failure, cleanup_method, cleanup_reason = (
            True, False, "natural-exit", None,
        )
        cleanup_tree_confirmed, taskkill_attempted, taskkill_success = (
            True, False, False,
        )
    else:
        cleanup_confirmed, cleanup_failure, cleanup_method, cleanup_reason = (
            None, False, None, None,
        )
        cleanup_tree_confirmed, taskkill_attempted, taskkill_success = (
            None, None, None,
        )

    if spawn_error:
        cls, reason, stdout_empty_flag = (
            FailureClass.NON_RETRYABLE, spawn_error, False,
        )
    elif timed_out and cleanup_failure:
        # FIX-001 Requirement 3：清理不确定性不得降级为普通 TimeoutExpired
        cls, reason, stdout_empty_flag = (
            FailureClass.NON_RETRYABLE,
            f"cleanup could not be confirmed: {cleanup_reason}",
            False,
        )
    elif timed_out:
        cls, reason, stdout_empty_flag = (
            FailureClass.RETRYABLE_TRANSIENT, "TimeoutExpired", False,
        )
        # v0.5 COST-STOP-LOSS-001：timeout 清理排出的 partial output 含明确
        # tool/test 活动 markers → attempt 级 evidence（TOOL_OR_TEST_STILL_ACTIVE
        # 判定用；absent → ATTEMPT_TIMEOUT，绝不把无证据 timeout 猜成 tool 活动）
        timeout_activity_markers = stop_loss_mod.timeout_shows_tool_activity(
            f"{stdout}\n{stderr}"
        )
    elif exit_code != 0:
        cls, reason = classify_failure(
            timed_out=False, returncode=exit_code, stdout=stdout, stderr=stderr
        )
        stdout_empty_flag = not (stdout or "").strip()
    elif not (stdout or "").strip():
        cls, reason = classify_failure(
            timed_out=False, returncode=0, stdout="", stderr=stderr
        )
        stdout_empty_flag = True
    else:
        cls, reason, stdout_empty_flag = None, None, False

    # v0.5 COST-STOP-LOSS-001：限频 attempt 解析 reset 窗口（单位明确才解析；
    # None = 无法证明可等 → orchestrator 尽早 fail closed，不空等到 budget）
    if cls in (FailureClass.RATE_LIMIT, FailureClass.QUOTA):
        rate_limit_reset_seconds = stop_loss_mod.parse_rate_limit_reset(
            f"{stdout}\n{stderr}"
        )

    record = AttemptRecord(
        attempt_index=0,  # orchestrator 回填
        status="FAILED" if cls is not None else "SUCCESS",
        failure_class=cls.value if cls is not None else None,
        retry_reason=reason,
        timed_out=timed_out,
        stdout_empty=stdout_empty_flag,
        exit_code=exit_code,
        timeout_used=round(float(timeout), 3),
        elapsed_seconds=elapsed,
        stderr_tail=stderr_tail,
        cleanup_confirmed=cleanup_confirmed,
        cleanup_failure=cleanup_failure,
        cleanup_method=cleanup_method,
        cleanup_reason=cleanup_reason,
        cleanup_tree_confirmed=cleanup_tree_confirmed,
        taskkill_attempted=taskkill_attempted,
        taskkill_success=taskkill_success,
        rate_limit_reset_seconds=rate_limit_reset_seconds,
        timeout_activity_markers=timeout_activity_markers,
    )
    return AttemptOutcome(stdout if cls is None else None, record)


# ---------------------------------------------------------------------------
# 有界 retry 编排（initial + bounded retries；绝不无限重试）
# ---------------------------------------------------------------------------


def _build_telemetry(
    policy: WorkBuddyRetryPolicy,
    attempts: list[AttemptRecord],
    outcome: str,
    last_failure: AttemptRecord | None,
    timed_out_occurred: bool,
    empty_occurred: bool,
    retry_reasons: list[str],
    stage_elapsed: float,
    stage_deadline: float | None = None,
    cleanup_failure_occurred: bool = False,
    retry_suppressed_reason: str | None = None,
    # v0.5 COST-STOP-LOSS-001：机器可读 terminal reason（vocabulary 见
    # stop_loss.TERMINAL_STOP_REASONS）+ 限频 evidence 标志
    terminal_reason: str | None = None,
    rate_limit_occurred: bool = False,
) -> dict:
    return {
        "agent": "workbuddy",
        "policy": {
            "max_attempts": policy.max_attempts,
            "per_attempt_timeout": round(float(policy.per_attempt_timeout), 3),
            "backoff_seconds": round(float(policy.backoff_seconds), 3),
            "overall_stage_budget": round(float(policy.overall_stage_budget), 3),
            "cleanup_reserve": round(float(policy.cleanup_reserve), 3),
            # FIX-002 Requirement 17：admission 实际使用的安全预留
            # （>= MIN_SAFE_CLEANUP_RESERVE；配置低于下限时被钳制）
            "cleanup_reserve_effective": round(
                float(max(policy.cleanup_reserve, MIN_SAFE_CLEANUP_RESERVE)), 3
            ),
        },
        "attempt_count": len(attempts),
        "retried": len(attempts) > 1,
        "outcome": outcome,
        # FIX-001 Requirement 9/19：单一绝对 stage deadline（monotonic）+ 实际墙钟
        "stage_deadline_monotonic": (
            round(float(stage_deadline), 3) if stage_deadline is not None else None
        ),
        "stage_total_elapsed_seconds": round(float(stage_elapsed), 3),
        "timeout_occurred": timed_out_occurred,
        "empty_occurred": empty_occurred,
        "cleanup_failure_occurred": cleanup_failure_occurred,
        "retry_suppressed_reason": retry_suppressed_reason,
        "retry_reasons": retry_reasons,
        # v0.5 COST-STOP-LOSS-001：机器可读 terminal stop reason（stop-loss 词汇）
        "terminal_reason": terminal_reason,
        "rate_limit_occurred": rate_limit_occurred,
        "last_failure": last_failure.to_dict() if last_failure is not None else None,
        "attempts": [a.to_dict() for a in attempts],
    }


def _render_failure_message(telemetry: dict) -> str:
    """REPORT/result 的紧凑失败历史（总 attempts / last failure / retry reasons /
    elapsed / timeout & empty-output 是否发生 / cleanup failure）——不得只给
    FRAMEWORK_ERROR 丢历史。"""
    policy = telemetry.get("policy") or {}
    lines = [
        f'WorkBuddy stage {telemetry.get("outcome", "FAILED")} after '
        f'{telemetry.get("attempt_count", 0)} attempt(s) '
        f'(stage total elapsed {telemetry.get("stage_total_elapsed_seconds", 0.0):.1f}s; '
        f'per-attempt timeout {policy.get("per_attempt_timeout", 0.0):.0f}s; '
        f'overall stage budget {policy.get("overall_stage_budget", 0.0):.0f}s)'
    ]
    # v0.5 COST-STOP-LOSS-001：机器可读 terminal stop reason（REPORT/result 可见）
    if telemetry.get("terminal_reason"):
        lines.append(f'terminal stop reason: {telemetry["terminal_reason"]}')
    if telemetry.get("rate_limit_occurred"):
        lines.append("rate limit / quota evidence: yes")
    for a in telemetry.get("attempts", []):
        lines.append(
            f'- attempt {a.get("attempt_index")}: {a.get("status")} '
            f'class={a.get("failure_class")} reason={a.get("retry_reason")} '
            f'timed_out={a.get("timed_out")} stdout_empty={a.get("stdout_empty")} '
            f'cleanup_confirmed={a.get("cleanup_confirmed")} '
            f'cleanup_failure={a.get("cleanup_failure")} '
            f'cleanup_tree_confirmed={a.get("cleanup_tree_confirmed")} '
            f'taskkill_attempted={a.get("taskkill_attempted")} '
            f'taskkill_success={a.get("taskkill_success")} '
            f'exit={a.get("exit_code")} elapsed={a.get("elapsed_seconds", 0.0):.1f}s'
        )
    lf = telemetry.get("last_failure")
    if lf:
        lines.append(f'last failure: {lf.get("retry_reason")}')
    lines.append(f'timeout occurred: {"yes" if telemetry.get("timeout_occurred") else "no"}')
    lines.append(f'empty-output occurred: {"yes" if telemetry.get("empty_occurred") else "no"}')
    if telemetry.get("cleanup_failure_occurred"):
        lines.append(
            "cleanup failure: previous child termination could not be confirmed "
            "(no retry; fail closed)"
        )
    if telemetry.get("retry_suppressed_reason"):
        lines.append(f'retry suppressed: {telemetry["retry_suppressed_reason"]}')
    if lf and lf.get("stderr_tail"):
        lines.append(f"last stderr tail: {lf['stderr_tail'][-300:]}")
    return "\n".join(lines)


def permanent_stage_error(message: str, retry_reason: str) -> WorkBuddyPermanentError:
    """invocation 层永久失败（如 missing executable）的带 telemetry 错误。"""
    telemetry = {
        "agent": "workbuddy",
        "policy": None,
        "attempt_count": 0,
        "retried": False,
        "outcome": OUTCOME_PERMANENT_FAILURE,
        "stage_deadline_monotonic": None,
        "stage_total_elapsed_seconds": 0.0,
        "timeout_occurred": False,
        "empty_occurred": False,
        "cleanup_failure_occurred": False,
        "retry_suppressed_reason": None,
        "retry_reasons": [],
        "terminal_reason": None,
        "rate_limit_occurred": False,
        "last_failure": {
            "attempt_index": 0,
            "status": "FAILED",
            "failure_class": FAILURE_CLASS_NON_RETRYABLE,
            "retry_reason": retry_reason,
            "timed_out": False,
            "stdout_empty": False,
            "exit_code": None,
            "timeout_used": 0.0,
            "elapsed_seconds": 0.0,
            "stderr_tail": "",
            "cleanup_confirmed": None,
            "cleanup_failure": False,
            "cleanup_method": None,
            "cleanup_reason": None,
            "cleanup_tree_confirmed": None,
            "taskkill_attempted": None,
            "taskkill_success": None,
        },
        "attempts": [],
    }
    return WorkBuddyPermanentError(message, telemetry)


def run_workbuddy_with_retry(
    args: list[str],
    env: dict,
    stdin_data: str | None,
    workspace: Path,
    policy: WorkBuddyRetryPolicy | None = None,
) -> tuple[str, dict]:
    """WorkBuddy stage 有界 retry 执行（TASK-011 核心）。

    返回 ``(output, telemetry)``：
    - 有效输出（非空、可解析/可用）一旦出现立即返回，后续 attempt 绝不执行；
      业务 verdict（哪怕 FAIL）不是 transport failure，不触发 retry。
    - retryable failures 在 max_attempts 内自动重试（同一 invocation、有界 backoff、
      per-attempt timeout、整体 stage budget 硬上限）。
    - NON_RETRYABLE → ``WorkBuddyPermanentError``（快速失败）。
    - retries 用尽 → ``WorkBuddyRetriesExhausted``（fail closed；telemetry 完整）。
    """
    policy = policy or load_workbuddy_policy()
    stage_start = time.monotonic()
    # FIX-001 Requirement 9/11：单一绝对 stage deadline——attempt / backoff /
    # cleanup（taskkill / grace / reap）全部从同一 deadline 派生并被其裁剪。
    stage_deadline = stage_start + policy.overall_stage_budget
    attempts: list[AttemptRecord] = []
    last_failure: AttemptRecord | None = None
    timed_out_occurred = False
    empty_occurred = False
    retry_reasons: list[str] = []
    cleanup_failure_occurred = False
    retry_suppressed_reason: str | None = None
    # v0.5 COST-STOP-LOSS-001：attempt 级 no-progress / 限频 evidence 累计
    consecutive_empty = 0
    consecutive_identical = 0
    prev_retry_reason: str | None = None
    gateway_evidence_occurred = False
    rate_limit_occurred = False

    def _is_gateway_reason(reason: str | None) -> bool:
        return bool(reason) and any(p.search(reason) for p in _PLACEHOLDER_GATEWAY_RES)

    def _terminal_reason_for(last: AttemptRecord | None) -> str:
        """stop-loss 终态机器可读原因（raise 点调用；确定性映射，evidence-based）。"""
        if last is None:
            return stop_loss_mod.STOP_REASON_RETRIES_EXHAUSTED
        if last.failure_class == FAILURE_CLASS_QUOTA:
            return stop_loss_mod.STOP_REASON_QUOTA
        if last.failure_class == FAILURE_CLASS_RATE_LIMIT:
            return stop_loss_mod.STOP_REASON_RATE_LIMIT
        if last.timed_out:
            return (
                stop_loss_mod.STOP_REASON_TOOL_OR_TEST_STILL_ACTIVE
                if last.timeout_activity_markers
                else stop_loss_mod.STOP_REASON_ATTEMPT_TIMEOUT
            )
        if gateway_evidence_occurred:
            return stop_loss_mod.STOP_REASON_PROVIDER_FAILURE
        if consecutive_empty >= 2 or consecutive_identical >= 2:
            return stop_loss_mod.STOP_REASON_NO_PROGRESS
        return stop_loss_mod.STOP_REASON_RETRIES_EXHAUSTED

    def telemetry(outcome: str, last: AttemptRecord | None,
                  terminal_reason: str | None = None) -> dict:
        return _build_telemetry(
            policy, attempts, outcome, last,
            timed_out_occurred, empty_occurred, retry_reasons,
            time.monotonic() - stage_start, stage_deadline,
            cleanup_failure_occurred, retry_suppressed_reason,
            terminal_reason=terminal_reason,
            rate_limit_occurred=rate_limit_occurred,
        )

    def _exhausted_raise(last: AttemptRecord | None) -> None:
        """统一 RETRIES_EXHAUSTED raise（terminal reason 由 attempt evidence 映射）。"""
        terminal = _terminal_reason_for(last)
        tm = telemetry(OUTCOME_RETRIES_EXHAUSTED, last, terminal)
        raise WorkBuddyRetriesExhausted(_render_failure_message(tm), tm)

    for attempt_index in range(1, policy.max_attempts + 1):
        now = time.monotonic()
        if now >= stage_deadline:
            if not retry_suppressed_reason:
                retry_suppressed_reason = "stage deadline reached"
            break
        remaining = stage_deadline - now
        if attempt_index > 1:
            # 有界确定性 backoff（不 tight loop 撞 gateway）；sleep 不超出剩余 budget
            if policy.backoff_seconds > 0:
                backoff = min(policy.backoff_seconds, max(0.0, remaining))
                if backoff > 0:
                    time.sleep(backoff)
                remaining = max(0.0, stage_deadline - time.monotonic())
        # FIX-001 Requirement 10 + FIX-002 Requirement 5/6：attempt timeout 不得
        # 超过 remaining - effective_cleanup_reserve，保证 timeout 后仍有有界清理
        # 窗口（绝不因清理超出 budget；cleanup budget 在启动 attempt 之前就保留，
        # 不是等 deadline 耗尽才发现没时间安全 kill tree）。
        # FIX-002 Requirement 3：effective reserve 被 MIN_SAFE_CLEANUP_RESERVE
        # 兜底（policy 直接构造传低值也无法破坏 Windows tree cleanup 安全性）。
        effective_reserve = max(policy.cleanup_reserve, MIN_SAFE_CLEANUP_RESERVE)
        attempt_timeout = max(
            0.0, min(policy.per_attempt_timeout, remaining - effective_reserve)
        )
        if attempt_timeout <= MIN_ATTEMPT_RUNTIME:
            # FIX-002 Requirement 6（Attempt Admission Control）：剩余 budget 必须
            # > minimum safe cleanup budget + minimum useful attempt runtime，
            # 否则不启动该 attempt（fail closed / retries exhausted / budget
            # exhausted）——绝不允许启动一个必然没有安全 cleanup 时间的 attempt。
            if not retry_suppressed_reason:
                retry_suppressed_reason = (
                    f"insufficient safe budget for another attempt "
                    f"(remaining {remaining:.1f}s <= safe cleanup reserve "
                    f"{effective_reserve:.1f}s + minimum attempt runtime "
                    f"{MIN_ATTEMPT_RUNTIME:.2f}s)"
                )
            break
        try:
            outcome = _run_single_attempt(
                args, env, stdin_data, workspace, attempt_timeout,
                deadline=stage_deadline,
            )
        except WorkBuddyConcurrencyError as exc:
            raise WorkBuddyConcurrencyError(
                str(exc),
                telemetry(OUTCOME_PERMANENT_FAILURE, last_failure),
            ) from exc
        record = outcome.record
        record.attempt_index = attempt_index
        attempts.append(record)
        if record.status == "SUCCESS":
            # 有效输出停止 retry（含业务 FAIL verdict——verdict 归 Framework authority）
            return outcome.output, telemetry(OUTCOME_SUCCESS, last_failure)
        last_failure = record
        if record.cleanup_failure:
            # FIX-001 Requirement 3/7/13：清理未确认 → cleanup failure / fail closed；
            # 绝不启动下一个 attempt；child PID 保持注册（Requirement 15）。
            cleanup_failure_occurred = True
            if not retry_suppressed_reason:
                retry_suppressed_reason = (
                    "previous child process termination unconfirmed "
                    "(child remains registered; no retry)"
                )
            raise WorkBuddyCleanupError(
                _render_failure_message(telemetry(OUTCOME_CLEANUP_FAILURE, record)),
                telemetry(OUTCOME_CLEANUP_FAILURE, record),
            )
        # v0.5 COST-STOP-LOSS-001：no-progress 簿记——只消费"已完成的失败 attempt"
        # 的 evidence，绝不在 attempt 执行中打断（合规长跑 tool/test 不被误杀）。
        if record.stdout_empty:
            consecutive_empty += 1
        else:
            consecutive_empty = 0
        if record.retry_reason and record.retry_reason == prev_retry_reason:
            consecutive_identical += 1
        else:
            consecutive_identical = 1
        prev_retry_reason = record.retry_reason
        if _is_gateway_reason(record.retry_reason) or (
            record.stderr_tail and _is_placeholder_gateway(record.stderr_tail)
        ):
            gateway_evidence_occurred = True
        if record.failure_class in (FAILURE_CLASS_RATE_LIMIT, FAILURE_CLASS_QUOTA):
            # v0.5 COST-STOP-LOSS-001：限频/quota 感知（audit：429 此前被误归为
            # empty output、重试未等 reset → 徒劳）。reset 窗口可解析且在剩余
            # budget 内 → 有界等待一次（provider/model wait 可接受）；否则**尽早
            # fail closed**——绝不烧掉剩余 attempts 或空转到 stage budget。
            rate_limit_occurred = True
            if record.retry_reason:
                retry_reasons.append(record.retry_reason)
            remaining_attempts = policy.max_attempts - attempt_index
            if remaining_attempts <= 0:
                break
            reset_s = record.rate_limit_reset_seconds
            now2 = time.monotonic()
            remaining2 = max(0.0, stage_deadline - now2)
            if reset_s is None or reset_s <= 0 or remaining2 <= effective_reserve:
                if not retry_suppressed_reason:
                    retry_suppressed_reason = (
                        "rate limit/quota evidence without a reachable reset "
                        "window (reset "
                        + (f"{reset_s:.0f}s" if reset_s is not None else "unknown")
                        + f", remaining budget {remaining2:.0f}s) — no reasonable "
                        "success signal; early stop-loss (RESUME after reset)"
                    )
                _exhausted_raise(record)
            wait = min(reset_s, remaining2)
            if remaining2 - wait <= effective_reserve + MIN_ATTEMPT_RUNTIME:
                if not retry_suppressed_reason:
                    retry_suppressed_reason = (
                        f"rate limit reset window ({reset_s:.0f}s) not reachable "
                        f"within remaining safe budget ({remaining2:.0f}s) — "
                        "early stop-loss (RESUME after reset)"
                    )
                _exhausted_raise(record)
            # 有界 provider/model wait：等到 reset 后再试一次（不 tight loop）
            time.sleep(max(0.0, wait))
            continue
        if record.failure_class == FailureClass.RETRYABLE_TRANSIENT.value:
            if record.retry_reason:
                retry_reasons.append(record.retry_reason)
            if record.timed_out:
                timed_out_occurred = True
            if record.stdout_empty:
                empty_occurred = True
            # v0.5 COST-STOP-LOSS-001：repeated no-progress（连续 empty-output /
            # 相同失败原因达到阈值）→ 提前终止，不烧掉剩余 attempts / budget。
            if (
                consecutive_empty >= NO_PROGRESS_EARLY_STOP_EMPTY_SEQUENCE
                or consecutive_identical >= NO_PROGRESS_EARLY_STOP_IDENTICAL_SEQUENCE
            ):
                if not retry_suppressed_reason:
                    retry_suppressed_reason = (
                        f"repeated no-progress failure "
                        f"({consecutive_empty} consecutive empty-output, "
                        f"{consecutive_identical} consecutive identical reason "
                        f"{record.retry_reason!r}) — early stop-loss"
                    )
                _exhausted_raise(record)
            continue
        # NON_RETRYABLE：快速失败，不无意义重试
        raise WorkBuddyPermanentError(
            _render_failure_message(telemetry(OUTCOME_PERMANENT_FAILURE, record)),
            telemetry(OUTCOME_PERMANENT_FAILURE, record),
        )

    # retryable failures 用尽（bounded）/ budget 不足 → fail closed
    _exhausted_raise(last_failure)
