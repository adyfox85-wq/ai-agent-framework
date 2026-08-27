"""AI Agent Framework — Soft Cancel external request artifact 契约（Phase E §6.3/§6A.15）。

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
- 写入必须原子（tmp + os.replace）；读取方（Runner 检查点 / recovery finalizer /
  reconciliation）只读，不据此裁决终态
- 重复请求幂等：重复写同一内容无副作用；canonical 结果只能有一个（§6A.14）
- 无效 / 部分请求安全处理：解析失败或字段非法 → inspect 返回 warning，
  Core 按“无请求”继续执行并记录不一致警告（§6A.15 / §6A.3），不破坏执行
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CANCEL_REQUEST_FILENAME = "cancel.request"
CANCEL_REQUEST_DONE = "cancel.done"

# 本 TASK（005-A，soft cancel）唯一请求类型；force cancel 属 TASK-005-B
CANCEL_REQUEST_TYPE_SOFT = "soft_cancel"
VALID_REQUEST_TYPES = (CANCEL_REQUEST_TYPE_SOFT,)


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


@dataclass
class CancelRequest:
    task_id: str
    requested_at: str
    request: str = CANCEL_REQUEST_TYPE_SOFT

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "requested_at": self.requested_at, "request": self.request}


def cancel_request_path(output_dir: Path | str) -> Path:
    return Path(output_dir) / CANCEL_REQUEST_FILENAME


def write_cancel_request(
    output_dir: Path | str,
    task_id: str,
    requested_at: str | None = None,
) -> Path:
    """原子写入 cancel.request（外部请求；由 UI / Launcher / 测试调用）。

    - 幂等：重复调用写相同内容
    - 原子：tmp + os.replace（不承担跨进程互斥；request 不是终态，无锁要求）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
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


def consume_cancel_request(output_dir: Path | str) -> bool:
    """将 cancel.request 改名为 cancel.done（evidence 保留，§6.6）。

    - 幂等：无 request 文件 → False；改名成功 → True
    - request 保留为证据（改名而非删除）
    """
    path = cancel_request_path(output_dir)
    if not path.exists():
        return False
    done = path.with_name(CANCEL_REQUEST_DONE)
    try:
        os.replace(path, done)
        return True
    except OSError:
        return False
