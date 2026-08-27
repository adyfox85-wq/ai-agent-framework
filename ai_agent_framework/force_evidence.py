"""AI Agent Framework — Structured Force Termination Evidence（Phase E §6B.17 / TASK-005-B req 19/21）。

force evidence 的角色：
- **recovery input，不是 terminal truth**（req 19）：Launcher 成功发出 verified
  process-tree termination 后生成的结构化证据；Core recovery finalizer 据此
  授权 CANCELLED 收敛（req 20/22）
- **不得退回任意 evidence 字符串授权**（req 20/AC）：证据必须是本 schema 的结构化
  JSON，且 finalizer 在 state.lock 临界区内交叉验证 evidence ↔ control.json ↔
  Bridge launch registry（launch_id / task_id / runner 身份 / ownership verified /
  非 superseded）——伪造 / 过期 / 不匹配 → 安全失败（零 canonical 写）

写者：Launcher（Bridge 侧，termination 后原子写）。
读者：Core recovery finalizer（finalize_cancelled force path，锁内验证）。

存储位置：``~/.aaf-bridge/launches/<launch_id>.force-evidence.json``（与 registry 同目录）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

FORCE_EVIDENCE_SCHEMA_VERSION = 1
FORCE_EVIDENCE_KIND = "force_termination"

# 允许的 verification result（Launcher 只会在 VERIFIED / REAUTHENTICATED 时执行 kill）
VALID_VERIFICATION_RESULTS = ("VERIFIED", "REAUTHENTICATED")

REQUIRED_FIELDS = (
    "schema_version",
    "kind",
    "task_id",
    "launch_id",
    "runner_pid",
    "runner_creation_time",
    "workspace",
    "output_dir",
    "expected_runner_entry",
    "expected_command_line",
    "verification_result",
    "verification_checks",
    "termination_requested_at",
    "termination_observed_at",
    "termination_exit_status",
    "termination_command",
    "registry_path",
    "control_path",
)


class ForceEvidenceError(ValueError):
    """force evidence 缺失 / 损坏 / 不匹配 / 非法（fail closed）。"""


def build_force_evidence(
    *,
    task_id: str,
    launch_id: str,
    runner_pid: int,
    runner_creation_time: str | None,
    workspace: str,
    output_dir: str,
    expected_runner_entry: str,
    expected_command_line: list[str],
    verification_result: str,
    verification_checks: dict,
    termination_requested_at: str,
    termination_observed_at: str,
    termination_exit_status: int,
    termination_command: list[str],
    registry_path: str,
    control_path: str,
    launch_root_pid: int | None = None,
) -> dict:
    """构造结构化 force evidence（TASK req 21 字段集的最小可实施集）。

    ``launch_root_pid``：启动时直连子进程（进程树 kill 根；uv venv 重定向壳场景与
    runner_pid 不同）——可选诊断字段，不是 ownership 校验字段。
    """
    ev = {
        "schema_version": FORCE_EVIDENCE_SCHEMA_VERSION,
        "kind": FORCE_EVIDENCE_KIND,
        "task_id": task_id,
        "launch_id": launch_id,
        "runner_pid": int(runner_pid),
        "runner_creation_time": runner_creation_time,
        "workspace": str(workspace),
        "output_dir": str(output_dir),
        "expected_runner_entry": expected_runner_entry,
        "expected_command_line": list(expected_command_line),
        "verification_result": verification_result,
        "verification_checks": dict(verification_checks),
        "termination_requested_at": termination_requested_at,
        "termination_observed_at": termination_observed_at,
        "termination_exit_status": int(termination_exit_status),
        "termination_command": list(termination_command),
        "registry_path": str(registry_path),
        "control_path": str(control_path),
    }
    if launch_root_pid is not None:
        ev["launch_root_pid"] = int(launch_root_pid)
    return ev


def validate_force_evidence(data: dict) -> list[str]:
    """结构校验 → 错误列表（空 = 结构合法）。验证语义在 finalizer 锁内完成。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["force evidence 不是 JSON object"]
    if data.get("schema_version") != FORCE_EVIDENCE_SCHEMA_VERSION:
        errors.append(f"schema_version != {FORCE_EVIDENCE_SCHEMA_VERSION}")
    if data.get("kind") != FORCE_EVIDENCE_KIND:
        errors.append(f"kind != {FORCE_EVIDENCE_KIND!r}")
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺少必需字段: {field}")
    if data.get("verification_result") not in VALID_VERIFICATION_RESULTS:
        errors.append(f"verification_result 非法: {data.get('verification_result')!r}")
    checks = data.get("verification_checks")
    if not isinstance(checks, dict) or not checks:
        errors.append("verification_checks 必须是非空 dict（逐项校验结果）")
    else:
        if not all(isinstance(v, bool) for v in checks.values()):
            errors.append("verification_checks 值必须是 bool")
        if not all(checks.values()):
            errors.append("verification_checks 存在 False 项——ownership 未全部通过，不得作为 force evidence")
    for ts_field in ("termination_requested_at", "termination_observed_at"):
        val = data.get(ts_field)
        if not isinstance(val, str) or not val:
            errors.append(f"{ts_field} 必须是时间戳字符串")
        else:
            try:
                datetime.fromisoformat(val)
            except ValueError:
                errors.append(f"{ts_field} 不是合法 ISO 时间戳: {val!r}")
    if not isinstance(data.get("runner_pid"), int):
        errors.append("runner_pid 必须是 int")
    if not isinstance(data.get("expected_command_line"), list):
        errors.append("expected_command_line 必须是 list")
    if not isinstance(data.get("termination_exit_status"), int):
        errors.append("termination_exit_status 必须是 int")
    return errors


def write_force_evidence(path: Path | str, data: dict) -> Path:
    """原子写 force evidence（tmp + os.replace；写前结构验证）。"""
    path = Path(path)
    errors = validate_force_evidence(data)
    if errors:
        raise ForceEvidenceError(f"force evidence 结构非法: {'; '.join(errors)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise ForceEvidenceError(f"force evidence 写入失败: {path} ({exc})") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


def read_force_evidence(path: Path | str) -> tuple[dict | None, str | None]:
    """只读 force evidence → (data, error)。损坏 / 结构非法 → (None, error)。"""
    path = Path(path)
    if not path.exists():
        return None, f"force evidence 不存在: {path}"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"force evidence 不可读: {path} ({exc})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"force evidence 损坏（JSON 解析失败）: {path} ({exc})"
    errors = validate_force_evidence(data)
    if errors:
        return None, f"force evidence 结构非法: {'; '.join(errors)}"
    return data, None
