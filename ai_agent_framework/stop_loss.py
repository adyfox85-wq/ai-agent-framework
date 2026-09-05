"""AAF — v0.5 Cost Stop-Loss shared vocabulary & evidence helpers（AAF-v0.5-COST-STOP-LOSS-001）。

Scope（严格执行，不扩大）：
- 纯常量 / 纯函数模块（零 I/O、零 subprocess、零 framework import）——只定义
  机器可读 stop-loss 词汇、rate-limit/quota 证据识别、per-attempt timeout 策略
  解析与 terminal-reason 分类规则。执行方（adapters / workbuddy_retry / runner）
  各自消费本模块，不做任何进程/调度/看门狗编排。
- 不新增 token-budget / billing engine（无可靠 provider token telemetry 时不猜 token）。
- 不修改 FREE/PAID routing semantics；不实施 PH-2 / PH-3。
- 分类只基于真实 CLI evidence（429 / rate limit / quota / empty-stream 文案），
  不凭空造字符串规则；无证据 → 不声称（None）。

背景（Cost Reality Audit, .aaf/AAF-v0.5-COST-EFFICIENCY-ROUTING-REALITY-AUDIT-001）：
- Hermes stage 曾出现 ~3600.89s subprocess 硬等待（TimeoutExpired，无进度烧 token）。
- WorkBuddy 曾出现长等待 / retry / 429 / empty-output；429 此前仅被归类为
  "empty output (exit=0)"，非限频感知，重试未等到 reset → 徒劳烧 budget。
- 原则：能免费优先；速度慢可接受，但**不允许无进展长期烧 token**；stop-loss 后
  fail closed + 保留工作产物 + 允许 RESUME（本模块不实现 resume——那是 runner/
  lifecycle 语义）。
"""
from __future__ import annotations

import os
import re
import subprocess

# ---------------------------------------------------------------------------
# Machine-readable terminal stop reasons（Requirement 7 词汇表）
# ---------------------------------------------------------------------------
STOP_REASON_ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
STOP_REASON_RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"
STOP_REASON_NO_PROGRESS = "NO_PROGRESS"
STOP_REASON_RATE_LIMIT = "RATE_LIMIT"
STOP_REASON_QUOTA = "QUOTA"
STOP_REASON_PROVIDER_FAILURE = "PROVIDER_FAILURE"
STOP_REASON_TOOL_OR_TEST_STILL_ACTIVE = "TOOL_OR_TEST_STILL_ACTIVE"

TERMINAL_STOP_REASONS = (
    STOP_REASON_ATTEMPT_TIMEOUT,
    STOP_REASON_RETRIES_EXHAUSTED,
    STOP_REASON_NO_PROGRESS,
    STOP_REASON_RATE_LIMIT,
    STOP_REASON_QUOTA,
    STOP_REASON_PROVIDER_FAILURE,
    STOP_REASON_TOOL_OR_TEST_STILL_ACTIVE,
)

STOP_LOSS_ARTIFACT = "stop_loss.json"

# ---------------------------------------------------------------------------
# Per-attempt bounded timeout 策略（Hermes / Codex；WorkBuddy 已有 AAF_WORKBUDDY_*）
# ---------------------------------------------------------------------------
ENV_HERMES_ATTEMPT_TIMEOUT = "AAF_HERMES_ATTEMPT_TIMEOUT"
ENV_CODEX_ATTEMPT_TIMEOUT = "AAF_CODEX_ATTEMPT_TIMEOUT"

# Hermes 默认 per-attempt 上限（无 env、无 Risk 时）。evidence：recon 实测成功
# Hermes stage p90≈1164s / max≈1886s（113 个成功阶段），3600s 级别只出现在
# 无进度死 run。2400s 保留 100% 已观测成功样本并留 ~27% 余量。
DEFAULT_HERMES_ATTEMPT_TIMEOUT = 2400.0
# Codex 默认 per-attempt 上限。evidence：71 个成功 review stage max≈224s → 600s
# （2.7x 余量）。Codex review 不跑 executor 级 tool/test 长任务。
DEFAULT_CODEX_ATTEMPT_TIMEOUT = 600.0
# 无 Risk 字段任务的保守默认（evidence：29 个无 Risk 成功 stage max≈1370s）。
DEFAULT_HERMES_TIMEOUT_NO_RISK = 1800.0
# Risk 分级默认（evidence：按 Risk 分组的成功 Hermes stage 最大值——
# HIGH 1886s / MEDIUM 891s / LOW 926s / NONE 1370s；CRITICAL 无样本，取 HIGH 值）。
HERMES_RISK_TIER_TIMEOUT: dict[str | None, float] = {
    "CRITICAL": 2400.0,
    "HIGH": 2400.0,
    "MEDIUM": 1500.0,
    "LOW": 1200.0,
    None: DEFAULT_HERMES_TIMEOUT_NO_RISK,
}
# 未知/非法 risk（validation 已 fail-closed，此处防御）→ 无 Risk 保守值
UNKNOWN_RISK_TIMEOUT = DEFAULT_HERMES_TIMEOUT_NO_RISK


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def resolve_agent_attempt_timeout(agent: str, risk_class: str | None = None,
                                  env=None) -> float:
    """Hermes/Codex per-attempt timeout（秒）——env override 优先，否则分级默认。

    - hermes：AAF_HERMES_ATTEMPT_TIMEOUT（operator override）→ Risk 分级默认。
    - codex：AAF_CODEX_ATTEMPT_TIMEOUT → 600s（review 无长 tool 任务）。
    - workbuddy：返回默认上限（不消费——retry 层用 AAF_WORKBUDDY_*；此处仅供
      调用方统一接口，绝不被 subprocess.run 使用）。
    本函数从不把 timeout 调"短到会误杀合法长任务"——默认值全部 ≥ 对应 risk 档
    已观测成功 stage 的 p100（evidence 见上）；operator 显式 env 可调（有意的
    越权覆盖，保留逃生口）。
    """
    env = os.environ if env is None else env
    if agent == "hermes":
        raw = env.get(ENV_HERMES_ATTEMPT_TIMEOUT, "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
        if risk_class and str(risk_class).strip().upper() in HERMES_RISK_TIER_TIMEOUT:
            return HERMES_RISK_TIER_TIMEOUT[str(risk_class).strip().upper()]
        return HERMES_RISK_TIER_TIMEOUT.get(None, DEFAULT_HERMES_TIMEOUT_NO_RISK)
    if agent == "codex":
        raw = env.get(ENV_CODEX_ATTEMPT_TIMEOUT, "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
        return DEFAULT_CODEX_ATTEMPT_TIMEOUT
    # workbuddy（retry 层自管）与未知 agent：返回 Hermes 默认（不参与决策）
    return DEFAULT_HERMES_ATTEMPT_TIMEOUT


# ---------------------------------------------------------------------------
# Rate limit / quota evidence（429 / quota / throttle；只基于真实 CLI 文案）
# ---------------------------------------------------------------------------
_RATE_QUOTA_RE_QUOTA = re.compile(
    r"(?i)\bquota\b.{0,60}(?:exceeded|exhausted|insufficient|limit|depleted|用完|超限|配额)"
    r"|\b(?:exceeded|exhausted|insufficient)\b.{0,40}\bquota\b"
)
_RATE_QUOTA_RE_RATE = (
    re.compile(r"(?i)\b429\b"),
    re.compile(r"(?i)rate\s*[-_]?limit"),
    re.compile(r"(?i)too\s+many\s+requests"),
    re.compile(r"(?i)throttl"),
    re.compile(r"(?i)request\s+limit"),
    re.compile(r"(?i)retry\s+(?:after|in)"),
    re.compile(r"(?i)try\s+again\s+(?:in|later)"),
    re.compile(r"(?i)limit\s+of\s+requests"),
    re.compile(r"(?i)限流|频率限制|请求过多"),
)

_RESET_TIME_UNIT_SECONDS = {
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
}
_RESET_RE_PATTERNS = (
    # "retry after 45 seconds" / "try again in 5 minutes" / "back off 30s"
    re.compile(
        r"(?i)(?:retry|try\s+again|back\s+off|try)(?:\s+(?:after|in))?"
        r"\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])\b"
    ),
    # "rate limit ... reset(s)(in|after) 90 seconds"
    re.compile(
        r"(?i)rate\s*[-_]?limit[^\n]{0,80}?\breset(?:s|ted)?\b[^\n]{0,40}?"
        r"(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?|[smh])\b"
    ),
    # "resets in 90 seconds" / "reset after 5 minutes"
    re.compile(
        r"(?i)\breset(?:s|ted)?\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*"
        r"(seconds?|minutes?|hours?|[smh])\b"
    ),
)


def detect_rate_limit_evidence(text: str | None) -> tuple[str | None, str | None]:
    """识别 CLI 输出中的 rate-limit/quota evidence。返回 (kind, detail)。

    kind ∈ {STOP_REASON_RATE_LIMIT, STOP_REASON_QUOTA, None}。detail = 首个命中行
    （截断）。QUOTA 词证据优先于通用 RATE_LIMIT（quota 是 per-task/per-key 上限，
    reset 窗口通常远超 stage budget；429/rate limit 是瞬时限频）。无证据 → (None,
    None)（绝不把普通文本猜成限频）。
    """
    if not text:
        return None, None
    for line in text.splitlines():
        if _RATE_QUOTA_RE_QUOTA.search(line):
            return STOP_REASON_QUOTA, line.strip()[:200] or None
    for pat in _RATE_QUOTA_RE_RATE:
        m = pat.search(text)
        if m:
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            if end == -1:
                end = len(text)
            return STOP_REASON_RATE_LIMIT, text[start:end].strip()[:200] or None
    return None, None


def parse_rate_limit_reset(text: str | None) -> float | None:
    """从限频文案解析 reset 等待秒数（单位明确才解析；无单位/无文案 → None）。

    None 语义：无法证明 reset 窗口可等 → 调用方应尽早 stop（不空转到 stage
    budget）。秒数解析后由 orchestrator 与 remaining budget 比较决定等还是停。
    """
    if not text:
        return None
    for pat in _RESET_RE_PATTERNS:
        for m in pat.finditer(text):
            try:
                amount = float(m.group(1))
            except ValueError:
                continue
            unit = m.group(2).lower()
            mult = _RESET_TIME_UNIT_SECONDS.get(unit)
            if mult is None:
                continue
            return amount * mult
    return None


# ---------------------------------------------------------------------------
# Timeout 场景的 tool/test-activity evidence（TOOL_OR_TEST_STILL_ACTIVE）
# ---------------------------------------------------------------------------
# 保守启发式（只认明确的"仍在跑工具/测试"字样；absent → ATTEMPT_TIMEOUT，绝不
# 把无证据 timeout 猜成 tool 活动）。
_TOOL_ACTIVITY_MARKERS = (
    re.compile(r"(?i)\brunning\s+(?:tests?|builds?|tools?|pytest|unittest)\b"),
    re.compile(r"(?i)\b(?:pytest|unittest)\b"),
    re.compile(r"(?i)\b(?:test|build)\s+(?:session|started|starting|in\s+progress)\b"),
    re.compile(r"(?i)\bbuilding\b"),
    re.compile(r"(?i)\brunning\s+(?:npm|pip|gradle|mvn|make|go\s+test)\b"),
)


def timeout_shows_tool_activity(text: str | None) -> bool:
    """timeout 清理时排出的 partial output 是否含明确的 tool/test 活动 markers。

    这是"distinguishable"判定（Requirement 7：TOOL_OR_TEST_STILL_ACTIVE where
    distinguishable）：命中 → 停止原因是"有界 attempt 预算耗尽时 child 仍在跑
    合法工具/测试"，与 NO_PROGRESS（无任何进展证据）区分；未命中 → ATTEMPT_TIMEOUT。
    注意：本函数**不参与** attempt 执行中的任何决策——绝不打断在跑的工具/测试。
    """
    if not text:
        return False
    return any(p.search(text) for p in _TOOL_ACTIVITY_MARKERS)


# ---------------------------------------------------------------------------
# Terminal-reason 分类（runner/artifacts 用；纯判定，无 I/O）
# ---------------------------------------------------------------------------
def classify_terminal_reason(*, agent: str, exc: BaseException | None,
                             wb_telemetry: dict | None,
                             result_text: str | None) -> tuple[str | None, str | None]:
    """把一次最终失败的 stage 映射到机器可读 stop reason（无匹配 → (None, None)）。

    顺序（确定性；基于真实 evidence，不叠加猜测）：
    1. WorkBuddy retry 层 telemetry 自报 terminal_reason（rate/quota/no-progress/
       attempt-timeout 等由 orchestrator 在 raise 点显式计算）——PERMANENT_FAILURE /
       CLEANUP_FAILURE 无 vocab reason → None（outcome 本身已机器可读）。
    2. subprocess.TimeoutExpired（Hermes/Codex 单 attempt 硬等待被有界终止）→
       ATTEMPT_TIMEOUT（A5/既有语义不变：异常类型原样传递，仅分类）。
    3. 异常/结果文本中的 429 / quota evidence → RATE_LIMIT / QUOTA。
    4. 其余（普通 RuntimeError / CLI 永久错误 / verdict 型失败）→ None（非
       stop-loss 场景，保留既有 FRAMEWORK_ERROR / verdict 语义）。
    """
    if wb_telemetry:
        outcome = wb_telemetry.get("outcome")
        if outcome and outcome != "SUCCESS":
            reason = wb_telemetry.get("terminal_reason")
            if reason:
                detail = (
                    wb_telemetry.get("retry_suppressed_reason")
                    or (wb_telemetry.get("last_failure") or {}).get("retry_reason")
                )
                return reason, detail
            return None, None
    if exc is not None:
        if isinstance(exc, subprocess.TimeoutExpired):
            return (
                STOP_REASON_ATTEMPT_TIMEOUT,
                f"{agent} attempt exceeded its bounded per-attempt timeout "
                f"({getattr(exc, 'timeout', None)}s)",
            )
        exc_text = f"{type(exc).__name__}: {exc}"
        kind, detail = detect_rate_limit_evidence(exc_text)
        if kind is not None:
            return kind, detail
    if result_text:
        kind, detail = detect_rate_limit_evidence(result_text)
        if kind is not None:
            return kind, detail
    return None, None


def build_stop_loss_record(*, agent: str, task_id: str, exc: BaseException | None,
                           wb_telemetry: dict | None, result_text: str | None,
                           elapsed_seconds: float | None) -> dict | None:
    """构造 stop_loss.json 机器记录；无已识别 stop reason → None（调用方不写文件）。"""
    reason, detail = classify_terminal_reason(
        agent=agent, exc=exc, wb_telemetry=wb_telemetry, result_text=result_text
    )
    if reason is None:
        return None
    record: dict = {
        "schema_version": 1,
        "task_id": task_id,
        "agent": agent,
        "terminal_reason": reason,
        "detail": detail,
        "triggered_at": _iso_now(),
        "elapsed_seconds": round(float(elapsed_seconds), 1) if elapsed_seconds else None,
    }
    if wb_telemetry:
        record["outcome"] = wb_telemetry.get("outcome")
        record["attempt_count"] = wb_telemetry.get("attempt_count")
        record["attempts_artifact"] = "workbuddy_attempts.json"
        record["notes"] = [
            "WorkBuddy retry 层已停止；详细 attempt evidence 见 workbuddy_attempts.json",
            "RESUME/recovery：保留本目录全部 artifacts；修复后以 --resume-from 重新执行本 stage",
        ]
    else:
        record["outcome"] = "stage_attempt_failed"
        record["attempt_count"] = 1
        record["notes"] = [
            f"{agent} stage 最终失败（stop-loss 有界终止）；stage result/attempt "
            "evidence 见本目录 *_result.md / *_result.json",
            "RESUME/recovery：保留本目录全部 artifacts；修复后以 --resume-from 重新执行本 stage",
        ]
    return record


def _iso_now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
