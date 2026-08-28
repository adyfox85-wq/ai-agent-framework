"""AI Agent Framework — Soft Cancel external request artifact 契约（Phase E §6.3/§6A.15/§6B）。

cancel.request 的角色：
- **external cancellation request，不是 terminal truth**（§6A.15）
- canonical source = Core lifecycle state（task.json）；request 只表达“用户想取消”
- 最终 canonical terminal 只有 CANCELLED；CANCEL_REQUESTED / CANCELLING 只作为
  request / 控制语义，**不属于 task.json 合法 status**（§6A.3）

路径：``.aaf/<Task-ID>/cancel.request``（与 task.json 同目录）

Schema（最小 JSON）：:

    {
      "task_id": "AAF-XXX",          // 绑定任务（校验用）
      "requested_at": "2026-08-27T10:00:00+08:00",
      "request": "soft_cancel"        // 本 TASK 唯一请求类型
    }

- 不包含任何会成为 terminal authority 的字段（无 status / terminal_generation 等）
- 读取方（Runner 检查点 / recovery finalizer / reconciliation）只读，不据此裁决终态；
  recovery finalizer 的权威 evidence 验证在 state.lock 临界区内完成
- 重复请求幂等：重复写同一内容无副作用；canonical 结果只能有一个（§6A.14）
- 无效 / 部分请求安全处理：解析失败或字段非法 → inspect 返回 warning，
  Core 按“无请求”继续执行并记录不一致警告（§6A.15 / §6A.3），不破坏执行

FIX-003（AAF-v0.4-TASK-005-A-FIX-003）— cancel.request mutation 锁序列化协议：
- cancel.request **不是 canonical terminal truth**（§6A.15）
  **≠** request mutation 可以绕过 recovery 同步（FIX-003）
- 因为 request 在 recovery protocol 中是 **authority evidence**（soft recovery 的
  合法证据），Framework-owned 的 request mutation（write / replace / consume）必须
  与 terminal writers 共享同一 per-task ``state.lock``（§6B.1）：
  recovery 在锁内验证 evidence 与 commit CANCELLED 之间，另一个 Framework writer
  不能替换 / 删除 / consume 该 request（evidence 真正 lock-stable）
- 本模块只提供**官方 mutation 路径**（write_cancel_request / consume_cancel_request /
  锁内 helper），全部经同一 ``task_state_lock``；不拦截用户手工删除文件
- 锁获取失败（超时 / OS 错误）：抛 ``LockTimeout`` / ``LockError``（显式错误），
  不写 request、不 consume、不 fallback 成无锁写（§6B.19 同规则）
- 读取（inspect / read）保持无锁：非权威读；recovery 的权威验证在其锁内完成

FIX-001（AAF-v0.4-TASK-005-C-FIX-001）— canonical time semantics：
- ``requested_at`` 合法取值：offset-aware ISO 8601（+08:00 / +00:00 / Z 等）
  或 legacy naive（本地墙上时间，历史 writer 默认格式）
- elapsed-time 计算**唯一**入口 = ``requested_at_elapsed_seconds``：
  统一规范化到 aware（UTC）后再做算术，杜绝 naive/aware 直接相减
  （TypeError: can't subtract offset-naive and offset-aware datetimes）
- malformed / 非法 → None（fail closed：不得产生 force eligibility）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .lock_utils import task_state_lock
from .task_lifecycle import LifecycleError, read_status  # canonical task.json 唯一读取器

CANCEL_REQUEST_FILENAME = "cancel.request"
CANCEL_REQUEST_DONE = "cancel.done"

# 本 TASK（005-A，soft cancel）唯一请求类型；force cancel 属 TASK-005-B
CANCEL_REQUEST_TYPE_SOFT = "soft_cancel"
VALID_REQUEST_TYPES = (CANCEL_REQUEST_TYPE_SOFT,)


class CancelRequestIdentityError(RuntimeError):
    """write_cancel_request 身份护栏拒绝：canonical task.json 已存在且 task_id 不匹配。

    request 只是外部意图 artifact，不得覆盖 canonical identity（FIX-003 req 8）；
    调用方应使用与 canonical task.json 一致的 task_id（或先建立 canonical）。
    """


def parse_requested_at(requested_at: str) -> datetime | None:
    """严格解析 cancel.request 的 ``requested_at``（ISO 8601 时间戳）。

    - 合法 → datetime；非法（非字符串 / 无法解析）→ None
    - 供 recovery finalizer 做 authority evidence 校验（FIX-001 req 8：
      ``requested_at`` present / valid enough per current contract）；
      runner 检查点仍按 §6A.15 宽松处理（无效请求 → warning，不拒绝执行）
    """
    if not isinstance(requested_at, str) or not requested_at:
        return None
    try:
        return datetime.fromisoformat(requested_at)
    except ValueError:
        return None


def _local_timezone() -> timezone:
    """本机本地时区 tzinfo（固定 offset；Windows / 无 tz 数据库环境同样可用）。

    legacy naive timestamp 的明确解释：与历史 ``write_cancel_request`` 默认
    ``datetime.now().isoformat()``（本地墙上时间）语义一致（FIX-001 req 4）。
    """
    return datetime.now().astimezone().tzinfo


def normalize_aware(dt: datetime) -> datetime:
    """规范化 datetime：aware → 原样；naive → 明确解释为本地时间（附本地 offset）。

    - 返回 aware datetime；不改变时刻（naive 本地墙上时间 = 本地时区同一时刻）
    - 杜绝 naive / aware 直接混算（FIX-001 req 1：canonical UTC/aware elapsed
      contract 的唯一入口）
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=_local_timezone())
    return dt


def requested_at_elapsed_seconds(requested_at: str | None, now: datetime | None = None) -> float | None:
    """cancel.request ``requested_at`` → 已流逝秒数（FIX-001 canonical elapsed contract）。

    Canonical 语义（§6A.15 / FIX-001 req 1）：
    - 所有算术在 aware（统一到 UTC）上进行；绝不与 naive now 直接相减
      （修复：TypeError: can't subtract offset-naive and offset-aware datetimes）
    - 合法 ISO 8601（aware：+08:00 / +00:00 / Z 等 UTC equivalent；legacy naive）→
      ``max(0.0, elapsed)``（未来时间戳 → 0.0，不产生负年龄）
    - legacy naive → 明确解释为本地时间（与历史 writer 默认语义一致，req 4）
    - 非法 / malformed / 非字符串 → None（fail closed：调用方不得据此产生
      force eligibility，req 5）
    - ``now`` 仅供确定性测试注入（aware 或 naive 均可；naive 同样按本地解释）
    """
    if not isinstance(requested_at, str) or not requested_at:
        return None
    ts = parse_requested_at(requested_at)
    if ts is None:
        return None
    now_dt = now if now is not None else datetime.now(timezone.utc)
    elapsed = (
        normalize_aware(now_dt).astimezone(timezone.utc)
        - normalize_aware(ts).astimezone(timezone.utc)
    ).total_seconds()
    return max(0.0, elapsed)


@dataclass
class CancelRequest:
    task_id: str
    requested_at: str
    request: str = CANCEL_REQUEST_TYPE_SOFT

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "requested_at": self.requested_at, "request": self.request}


def cancel_request_path(output_dir: Path | str) -> Path:
    return Path(output_dir) / CANCEL_REQUEST_FILENAME


def _canonical_task_id(output_dir: Path) -> str | None:
    """锁内读取 canonical task.json 的 task_id（FIX-003 req 8 身份护栏）。

    - 无 task.json / 损坏 / 缺 task_id → None（legacy / 未知 canonical：
      按“无 canonical”兼容处理，不阻止 request 写入——request 仍只是外部意图）
    - 有合法 task_id → 返回；写者据此拒绝明显的 mismatch 写入
    - 复用 task_lifecycle.read_status（canonical task.json 唯一读取器，
      不复制第二套解析逻辑）
    """
    try:
        data = read_status(output_dir)
    except (LifecycleError, OSError):
        return None
    if data is None:
        return None
    tid = data.get("task_id")
    return tid if isinstance(tid, str) and tid else None


def write_cancel_request(
    output_dir: Path | str,
    task_id: str,
    requested_at: str | None = None,
    *,
    lock_timeout: float = 10.0,
) -> Path:
    """原子写入 cancel.request（外部请求；由 UI / Launcher / 测试调用）。

    FIX-003：与 terminal writers 共享同一 per-task ``state.lock``（§6B.1）——
    recovery 在锁内验证 evidence 与 commit CANCELLED 之间，本 writer 无法
    替换 / 删除 request（authority evidence 真正 lock-stable）。

    - acquire state.lock → 锁内身份护栏（canonical task.json 已存在且 task_id
      不匹配 → 拒绝写入，抛 ``CancelRequestIdentityError``；无 canonical /
      legacy 目录兼容写入）→ 原子 tmp + os.replace → release
    - 幂等：重复调用写相同内容（相同 task_id 无副作用）
    - 锁获取失败（超时 / OS 错误）：抛 ``LockTimeout`` / ``LockError``，**不写
      request、不 fallback 成无锁写**（§6B.19 同规则）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with task_state_lock(output_dir, task_id, timeout=lock_timeout):
        return _write_cancel_request_locked(output_dir, task_id, requested_at)


def _write_cancel_request_locked(
    output_dir: Path,
    task_id: str,
    requested_at: str | None = None,
) -> Path:
    """锁内写实现（FIX-003 req 3/7：调用方**必须已持有** state.lock，不重复 acquire）。

    与 public ``write_cancel_request`` 同一套 request schema / 写入语义
    （不复制两套实现）；caller-already-locked path 直接调用本 helper
    （原则与 ``task_lifecycle._finalize_terminal_locked`` 一致）。
    """
    canonical_task_id = _canonical_task_id(output_dir)
    if canonical_task_id is not None and canonical_task_id != task_id:
        raise CancelRequestIdentityError(
            f"CANCEL_REQUEST_IDENTITY_ERROR: cancel.request 写入被拒绝——"
            f"canonical task.json task_id {canonical_task_id!r} != 请求 task_id "
            f"{task_id!r}（request 只是外部意图 artifact，不得覆盖 canonical "
            f"identity；无 canonical / legacy 目录仍兼容写入）"
        )
    req = CancelRequest(
        task_id=task_id,
        requested_at=requested_at or datetime.now().isoformat(timespec="seconds"),
    )
    path = cancel_request_path(output_dir)
    tmp = path.with_suffix(".request.tmp")
    tmp.write_text(json.dumps(req.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def inspect_cancel_request(output_dir: Path | str) -> tuple[CancelRequest | None, str | None]:
    """读取并校验 cancel.request。

    返回 (request, warning)：
    - 无文件 → (None, None)
    - 合法请求 → (CancelRequest, None)
    - 无效 / 部分请求（损坏 JSON / 缺字段 / 非法类型）→ (None, warning)
      —— 调用方按“无请求”继续执行并记录 warning（§6A.15：不拒绝执行）

    FIX-003：本读取无锁（非权威读）；recovery finalizer 的权威 evidence 验证
    在其 state.lock 临界区内完成（锁内重新读取当前 request）。
    """
    path = cancel_request_path(output_dir)
    if not path.exists():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cancel.request 不可读: {path} ({exc})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"cancel.request 损坏（JSON 解析失败，已忽略）: {path} ({exc})"
    if not isinstance(data, dict):
        return None, f"cancel.request 结构非法（非 JSON object，已忽略）: {path}"
    task_id = data.get("task_id")
    requested_at = data.get("requested_at")
    request = data.get("request")
    if not isinstance(task_id, str) or not task_id:
        return None, f"cancel.request 缺少有效 task_id（已忽略）: {path}"
    if not isinstance(requested_at, str) or not requested_at:
        return None, f"cancel.request 缺少有效 requested_at（已忽略）: {path}"
    if request not in VALID_REQUEST_TYPES:
        return None, f"cancel.request 请求类型非法 {request!r}（允许: {VALID_REQUEST_TYPES}，已忽略）: {path}"
    return CancelRequest(task_id=task_id, requested_at=requested_at, request=request), None


def read_cancel_request(output_dir: Path | str) -> CancelRequest | None:
    """便捷读取：仅返回合法请求；无效 / 缺失 → None（细节用 inspect_cancel_request）。"""
    req, _ = inspect_cancel_request(output_dir)
    return req


def consume_cancel_request(
    output_dir: Path | str,
    task_id: str | None = None,
    *,
    lock_timeout: float = 10.0,
) -> bool:
    """将 cancel.request 改名为 cancel.done（evidence 保留，§6.6）。

    FIX-003：与 terminal writers 共享同一 per-task ``state.lock``——recovery
    正持锁验证 request 时，本 consumer 不能静默 consume / 移除证据。

    - acquire state.lock → 锁内判断存在 → rename → release（存在判断 + rename
      同属一个锁临界区，FIX-003 req 4/9）
    - 幂等：无 request 文件 → False；改名成功 → True；重复 consume → False
    - ``task_id`` 仅用于锁错误信息（锁路径由 output_dir 唯一决定）；None 时回退
      目录名
    - 锁获取失败（超时 / OS 错误）：抛 ``LockTimeout`` / ``LockError``，**不
      consume、不 fallback 无锁 rename**（§6B.19 同规则）
    """
    output_dir = Path(output_dir)
    lock_task_id = task_id or output_dir.name or "?"
    with task_state_lock(output_dir, lock_task_id, timeout=lock_timeout):
        return _consume_cancel_request_locked(output_dir)


def _consume_cancel_request_locked(output_dir: Path) -> bool:
    """锁内 consume 实现（调用方**必须已持有** state.lock，不重复 acquire）。"""
    path = cancel_request_path(output_dir)
    if not path.exists():
        return False
    done = path.with_name(CANCEL_REQUEST_DONE)
    try:
        os.replace(path, done)
        return True
    except OSError:
        return False
