"""AAF Bridge — Runner Ownership Verification（Phase E §6A.8 / §6B.13 / TASK-005-B req 11）。

Force termination 前必须全部通过 11 项校验（TASK req 11；§6A.8 表 + §6B.13 十项
汇总）；任一失败 → 拒绝 force termination，**不得降级成“看起来像”就杀**（§6A.8）。

校验矩阵（registry ↔ control ↔ live process ↔ canonical）:

   1. registry.launch_id == control.launch_id
   2. registry.task_id == control.task_id
   3. workspace 相同（registry.workspace 规范化 == control.workspace 规范化）
   4. 目标 task_id 相同（registry/control == 请求 task_id）
   5. runner PID 相同（live.pid == registry.runner_pid == control.runner_pid）
   6. live 进程存在
   7. creation time 相同（live == registry == control；防 PID recycle）
   8. 命令行规范化匹配（live == registry.expected_command_line == control.expected_command_line）
   9. registry state 有效（PREPARED / RUNNING）
  10. control 未被 superseded（superseded_by 为空）
  11. task.json 尚无 terminal state（§6A.10 stale 规则）

结果：VERIFIED（全部通过）/ STALE（进程消失 / PID recycle / terminal /
superseded / registry EXITED 类） / UNCERTAIN（其余不匹配）。STALE / UNCERTAIN
一律**拒绝 force kill**（§6A.9/§6B.13）。

live process identity 可注入（live_identity_override）——测试确定性 + 防止误杀真实进程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_agent_framework import control as control_mod
from ai_agent_framework import proc_identity
from ai_agent_framework.task_lifecycle import read_canonical_terminal

from . import launch_registry as reg_mod

VERIFIED = "VERIFIED"
UNCERTAIN = "UNCERTAIN"
STALE = "STALE"
REAUTHENTICATED = "REAUTHENTICATED"

# 全部检查项（11 项；TASK req 11）
CHECK_NAMES = (
    "registry_control_launch_id_match",
    "registry_control_task_id_match",
    "workspace_match",
    "target_task_id_match",
    "runner_pid_match",
    "process_exists",
    "creation_time_match",
    "command_line_match",
    "registry_state_valid",
    "control_not_superseded",
    "task_not_terminal",
)


@dataclass
class OwnershipVerdict:
    """结构化 ownership 判定（VERIFIED / STALE / UNCERTAIN / REAUTHENTICATED）。"""

    result: str
    launch_id: str
    task_id: str
    checks: dict = field(default_factory=dict)  # check 名 → bool
    failures: list = field(default_factory=list)  # 失败项说明
    registry: dict | None = None
    control: dict | None = None
    live: dict | None = None

    def ok(self) -> bool:
        return self.result in (VERIFIED, REAUTHENTICATED)

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "launch_id": self.launch_id,
            "task_id": self.task_id,
            "checks": dict(self.checks),
            "failures": list(self.failures),
        }


def _same_path(a: str | None, b: str | None) -> bool:
    return bool(a and b and proc_identity.canonicalize_path(a) == proc_identity.canonicalize_path(b))


def verify_runner_ownership(
    *,
    task_id: str,
    launch_id: str,
    registry_dir: Path | None = None,
    live_identity_override: dict | None = None,
    mark_exited_on_terminal: bool = False,
) -> OwnershipVerdict:
    """三方 ownership verification（§6B.13）。

    - registry_dir：registry 根目录（默认 registry_root()；测试注入 tmp）
    - live_identity_override：注入 live 进程身份（测试 / E2E 确定性）；
      缺省 → proc_identity.live_process_identity(registry.runner_pid)
    - mark_exited_on_terminal：检测到 task terminal 时顺带把 registry 标记 EXITED
      （TASK req 26；幂等；不改变 canonical 本身）
    """
    failures: list[str] = []
    checks: dict[str, bool] = {}

    # --- 读取两份持久记录 ---
    registry, reg_err = reg_mod.read_registry(launch_id, root=registry_dir)
    if reg_err:
        failures.append(f"registry 不可用: {reg_err}")
        return OwnershipVerdict(UNCERTAIN, launch_id, task_id, checks={}, failures=failures)
    if registry is None:
        failures.append(f"registry 不存在: launch_id={launch_id}")
        return OwnershipVerdict(UNCERTAIN, launch_id, task_id, checks={}, failures=failures)

    output_dir = Path(str(registry.get("output_dir") or ""))
    control, ctrl_err = control_mod.read_control(output_dir) if str(output_dir) else (None, "registry.output_dir 缺失")
    if ctrl_err:
        failures.append(f"control 不可用: {ctrl_err}")

    reg_task_id = str(registry.get("task_id") or "")
    ctrl_task_id = str(control.get("task_id") or "") if control else ""

    # 1. registry.launch_id == control.launch_id
    check_ok = control is not None and registry.get("launch_id") == control.get("launch_id")
    checks[CHECK_NAMES[0]] = check_ok
    if not check_ok:
        failures.append(
            f"launch_id 交叉不一致: registry={registry.get('launch_id')!r} "
            f"control={control.get('launch_id') if control else None!r}"
        )

    # 2. registry.task_id == control.task_id
    check_ok = control is not None and reg_task_id == ctrl_task_id
    checks[CHECK_NAMES[1]] = check_ok
    if not check_ok:
        failures.append(f"task_id 交叉不一致: registry={reg_task_id!r} control={ctrl_task_id!r}")

    # 3. workspace 相同
    check_ok = control is not None and _same_path(str(registry.get("workspace") or ""), str(control.get("workspace") or ""))
    checks[CHECK_NAMES[2]] = check_ok
    if not check_ok:
        failures.append(
            f"workspace 不一致: registry={registry.get('workspace')!r} control={control.get('workspace') if control else None!r}"
        )

    # 4. 目标 task_id 相同（请求 task_id == registry == control）
    check_ok = reg_task_id == task_id and ctrl_task_id == task_id
    checks[CHECK_NAMES[3]] = check_ok
    if not check_ok:
        failures.append(f"目标 task_id 不一致: 请求={task_id!r} registry={reg_task_id!r} control={ctrl_task_id!r}")

    runner_pid = registry.get("runner_pid")
    runner_ct = registry.get("runner_creation_time")

    # 5. runner PID 相同（live == registry == control）
    live = live_identity_override
    if live is None and runner_pid is not None:
        live = proc_identity.live_process_identity(runner_pid)
    live_pid = int(live["pid"]) if live and live.get("pid") is not None else None
    check_ok = (
        live is not None
        and runner_pid is not None
        and live_pid == int(runner_pid)
        and (control is None or control.get("runner_pid") is None or control.get("runner_pid") == int(runner_pid))
    )
    checks[CHECK_NAMES[4]] = check_ok
    if not check_ok:
        failures.append(
            f"runner PID 不一致: registry={runner_pid!r} live={live_pid!r} "
            f"control={control.get('runner_pid') if control else None!r}"
        )

    # 6. live 进程存在
    check_ok = live is not None and bool(live.get("exists"))
    checks[CHECK_NAMES[5]] = check_ok
    if not check_ok:
        failures.append(f"live 进程不存在（runner_pid={runner_pid!r}）")

    # 7. creation time 相同（live == registry == control；防 PID recycle）
    live_ct = live.get("creation_time") if live else None
    ctrl_ct = control.get("runner_creation_time") if control else None
    check_ok = (
        proc_identity.creation_times_equal(live_ct, runner_ct)
        and (ctrl_ct is None or proc_identity.creation_times_equal(live_ct, ctrl_ct))
    )
    checks[CHECK_NAMES[6]] = check_ok
    if not check_ok:
        failures.append(
            f"creation time 不一致（PID recycle 风险）: live={live_ct!r} "
            f"registry={runner_ct!r} control={ctrl_ct!r}"
        )

    # 8. 命令行规范化匹配（live vs registry.expected_command_line vs control.expected_command_line）
    live_argv = live.get("command_line") if live else None
    check_ok = bool(
        live_argv
        and proc_identity.command_line_matches(live_argv, registry.get("expected_command_line"))
        and (control is None or proc_identity.command_line_matches(live_argv, control.get("expected_command_line")))
    )
    checks[CHECK_NAMES[7]] = check_ok
    if not check_ok:
        failures.append(
            f"命令行不匹配: live={live_argv!r} vs expected={registry.get('expected_command_line')!r}"
        )

    # 9. registry state 有效（PREPARED / RUNNING）
    reg_state = registry.get("state")
    check_ok = reg_state in reg_mod.ACTIVE_STATES
    checks[CHECK_NAMES[8]] = check_ok
    if not check_ok:
        failures.append(f"registry state 非法: {reg_state!r}（仅 {reg_mod.ACTIVE_STATES} 可 force）")

    # 10. control 未被 superseded
    ctrl_sup = control.get("superseded_by") if control else None
    check_ok = control is not None and not ctrl_sup
    checks[CHECK_NAMES[9]] = check_ok
    if not check_ok:
        failures.append(f"control 已 superseded（superseded_by={ctrl_sup!r}）")

    # 11. task.json 尚无 terminal state（§6A.10 stale 规则）
    #     - task.json 缺失（PREPARED 早期）→ 无终态，通过
    #     - task.json 存在且非终态 → 通过
    #     - task.json 存在终态 → 不通过（STALE：force authority 已失去）
    #     - task.json 损坏 / 不可读 → 不通过（fail closed：无法证明无终态）
    terminal = None
    terminal_err: str | None = None
    if str(output_dir):
        try:
            terminal = read_canonical_terminal(output_dir)
        except Exception as exc:  # noqa: BLE001 —— canonical 损坏按“不可证明无终态”处理
            terminal_err = f"task.json 损坏/不可读: {exc}"
    check_ok = terminal is None and terminal_err is None
    checks[CHECK_NAMES[10]] = check_ok
    if not check_ok:
        failures.append(
            f"task 已有 canonical terminal: {terminal.status if terminal is not None else '?'}"
            if terminal is not None
            else f"无法证明任务无终态: {terminal_err}"
        )

    # --- 归类 ---
    if not checks or not all(checks.values()):
        stale_like = {
            "process_exists": False,
            "creation_time_match": False,
            "control_not_superseded": False,
            "registry_state_valid": False,
            "task_not_terminal": False,
        }
        if any(checks.get(k) is False for k in stale_like):
            result = STALE
        else:
            result = UNCERTAIN
        if mark_exited_on_terminal and not checks.get("task_not_terminal", True) and reg_state in reg_mod.ACTIVE_STATES:
            try:
                reg_mod.mark_exited(launch_id, exit_result="TERMINAL", note="canonical terminal detected", root=registry_dir)
            except reg_mod.RegistryError:
                pass
        return OwnershipVerdict(result, launch_id, task_id, checks=checks, failures=failures,
                                registry=registry, control=control, live=live)

    return OwnershipVerdict(VERIFIED, launch_id, task_id, checks=checks, failures=[],
                            registry=registry, control=control, live=live)


def reauthenticate_launch(
    *,
    task_id: str,
    launch_id: str,
    registry_dir: Path | None = None,
    live_identity_override: dict | None = None,
) -> OwnershipVerdict:
    """Launcher restart 重新认证（§6B.13 / TASK req 12）：registry + control +
    live process 三方验证；全部一致 → REAUTHENTICATED；任一失败 → UNCERTAIN（拒绝
    force kill）。**不要求 launcher_instance_id 相同**（§6B.16 / TASK req 6/V）。"""
    verdict = verify_runner_ownership(
        task_id=task_id,
        launch_id=launch_id,
        registry_dir=registry_dir,
        live_identity_override=live_identity_override,
    )
    if verdict.result == VERIFIED:
        verdict.result = REAUTHENTICATED
    return verdict
