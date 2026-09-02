from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .adapters import build_prompt_measured, run_agent
from . import adapters as adapters_mod
from . import cancel as cancel_mod
from . import control as control_mod
from . import model_observation as model_observation_mod
from .context_packet import (
    build_stage_result,
    extract_and_validate_structured,
    file_bytes,
    git_changed_files,
    git_head,
    measure_prompt,
    remote_sync_state,
    sha256_file,
    write_manifest,
    write_stage_result,
)
from . import cost_guard as cost_guard_mod
from . import proc_identity
from . import project_boundary
from . import active_routing as active_routing_mod
from . import model_registry as model_registry_mod
from .risk_contract import ROLE_EXECUTOR, ROLE_VALIDATOR
from . import fallback_runtime as fallback_runtime_mod
from . import shadow_observation as shadow_obs_mod
from . import task_lifecycle
from . import workbuddy_routing as workbuddy_routing_mod
from .report import agent_result_blocked, build_report, verdict_blocked
from .reconcile import reconcile_terminal_artifacts
from .router import ALLOWED_ROUTE_AGENTS, Route, RouteStatus, decide_route, parse_explicit_route
from .task_lifecycle import (
    TERMINAL_REASON_CANCEL_REQUESTED,
    TERMINAL_REASON_FRAMEWORK_ERROR,
    TERMINAL_REASON_NORMAL_COMPLETION,
    TERMINAL_REASON_WAITING,
    finalize_terminal,
)
from .task_validation import (
    TaskValidationError,
    ValidationResult,
    parse_task_fields,
    validate_task_text,
)

# soft cancel 的 runner 退出码：0（REPORT 已生成；Launcher 不得仅凭 exit code 把
# CANCELLED 判 FAILED——§6A.5 exit code 只是 evidence，不是判定）
CANCEL_EXIT_CODE = 0


class HandshakeError(RuntimeError):
    """Runner 启动 ownership handshake（§6A.6-4 / TASK-005-B req 8）失败。

    触发条件：control.json 存在但与本次 launch 上下文不匹配（launch_id / task_id /
    workspace 不一致、control 已 superseded、force_terminate_requested 已置位、
    或调用方未提供 expected launch_id 却存在 control）。
    处理：**fail safely**——不接管、不继续 agent execution、不获得 force ownership、
    不修改其他 task、不写任何 canonical。
    """


def runner_handshake(
    output_dir: Path,
    task_id: str,
    workspace: Path,
    expected_launch_id: str | None = None,
) -> dict | None:
    """Runner 启动 ownership handshake（§6A.6-4 / §6B.12-G；TASK-005-B req 5/8）。

    - 无 control.json → 返回 None（direct/legacy 调用路径：无 ownership 契约，
      照常执行但不获得 force ownership）
    - control.json 存在：
      * expected_launch_id 未提供 → 拒绝（无法证明本次运行属于已登记 launch；
        旧 launch 不得重新取得管理权——§6A.6“旧 launch 不得继续拥有 force kill 权”）
      * expected_launch_id != control.launch_id → 拒绝（launch mismatch）
      * control.task_id != task_id → 拒绝
      * control.workspace（规范化）!= workspace（规范化）→ 拒绝
      * control.superseded_by 非空 → 拒绝（superseded control 不再有效）
      * control.force_terminate_requested → 拒绝（该 launch 已被请求强制终止，
        迟到的 runner 不得继续执行）
      * 全部通过 → 原子回写 runner_pid / runner_creation_time（state.lock 内，
        与 Launcher 写入串行化），返回 control dict（= 取得 ownership）
    - 任何拒绝 → 抛 HandshakeError（调用方中止执行；零 canonical 写）
    """
    control, err = control_mod.read_control(output_dir)
    if control is None:
        if err:
            # 文件存在但损坏：不接管（fail closed；无 control = 无 ownership 契约）
            raise HandshakeError(f"HANDSHAKE_ERROR: control.json 损坏——{err}")
        return None
    if expected_launch_id is None:
        raise HandshakeError(
            "HANDSHAKE_ERROR: control.json 已存在但调用方未提供 expected launch_id——"
            "无法证明本次运行属于已登记 launch，拒绝接管（旧 launch 不得重新获得 "
            "force ownership；请通过 Launcher 发起新 launch，旧 launch 会被 supersede）"
        )
    if control.get("launch_id") != expected_launch_id:
        raise HandshakeError(
            f"HANDSHAKE_ERROR: launch_id mismatch——control.launch_id "
            f"{control.get('launch_id')!r} != expected {expected_launch_id!r}"
        )
    if control.get("task_id") != task_id:
        raise HandshakeError(
            f"HANDSHAKE_ERROR: task_id mismatch——control.task_id "
            f"{control.get('task_id')!r} != 本次任务 {task_id!r}"
        )
    if proc_identity.canonicalize_path(str(control.get("workspace") or "")) != proc_identity.canonicalize_path(str(workspace)):
        raise HandshakeError(
            f"HANDSHAKE_ERROR: workspace mismatch——control.workspace "
            f"{control.get('workspace')!r} != 本次 workspace {str(workspace)!r}"
        )
    if control.get("superseded_by"):
        raise HandshakeError(
            f"HANDSHAKE_ERROR: control 已被 supersede（superseded_by="
            f"{control.get('superseded_by')!r}）——旧 launch 不得重新接管"
        )
    if control.get("force_terminate_requested") is True:
        raise HandshakeError(
            "HANDSHAKE_ERROR: control.force_terminate_requested 已置位——"
            "该 launch 已被请求强制终止，迟到的 runner 不得继续 agent execution"
        )
    # 写回 runner 身份（§6A.6-4；state.lock 内原子；与 Launcher 的 RUNNING 回填串行化）
    ct = proc_identity.process_creation_time(os.getpid())
    control_mod.update_control(
        output_dir,
        {
            "runner_pid": os.getpid(),
            "runner_creation_time": ct.isoformat(timespec="milliseconds") if ct is not None else None,
        },
        task_id=task_id,
    )
    return control


def _result_is_valid(body: str) -> bool:
    body = body.strip()
    return bool(body) and not body.startswith('FRAMEWORK_ERROR')


def _aggregate_status(agents: list[str], results: dict[str, str], output_dir=None) -> str:
    """所有必需节点通过（无缺失 / FRAMEWORK_ERROR / FAILED / FAIL / REQUEST_CHANGE）→ SUCCESS，否则 WAITING。

    RW-022：优先使用 structured result（``<agent>_result.json`` 的 blocking_rework——
    Agent 显式声明的事实），structured 缺失 / 损坏时 fallback 到 legacy narrative keyword
    判定（``agent_result_blocked``；fail-safe——无法证明无阻断时不得 SUCCESS）。
    """
    for agent in agents:
        if agent_result_blocked(agent, results.get(agent, ''), output_dir):
            return 'WAITING'
    return 'SUCCESS'


def _verify_resume_route_evidence(output_dir: Path, route: Route) -> None:
    """route.json 只作 persisted execution evidence（FIX-005 Req 2/5）。

    authoritative route 由调用方从 immutable TASK.snapshot.md 重新派生
    （``decide_route(snapshot)``）；此处比较 persisted ``route.json`` 与
    snapshot-derived route：``agents`` 必须完全一致（顺序敏感）。任何不一致 /
    损坏 / 含未知 agent / 缺少 required agent → **fail closed**：抛
    TaskValidationError（resume 被拒绝；不启动后续 Agent；不得 SUCCESS）。
    """
    rj = output_dir / 'route.json'
    try:
        route_data = json.loads(rj.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise TaskValidationError(ValidationResult(
            valid=False,
            errors=[(
                f'RESUME_ROUTE_EVIDENCE: route.json 无法读取/解析'
                f'（{type(exc).__name__}: {exc}）——persisted route evidence '
                f'损坏，resume fail closed'
            )],
        ))
    persisted_agents = route_data.get('agents') if isinstance(route_data, dict) else None
    if not isinstance(persisted_agents, list) or any(
        not isinstance(a, str) for a in persisted_agents
    ):
        raise TaskValidationError(ValidationResult(
            valid=False,
            errors=[
                'RESUME_ROUTE_EVIDENCE: route.json 缺少合法 agents 数组——'
                'persisted route evidence 非法，resume fail closed'
            ],
        ))
    unknown = [a for a in persisted_agents if a not in ALLOWED_ROUTE_AGENTS]
    if unknown:
        raise TaskValidationError(ValidationResult(
            valid=False,
            errors=[(
                f'RESUME_ROUTE_EVIDENCE: route.json 含未知 route agent '
                f'{unknown}——persisted route evidence 非法，resume fail closed'
            )],
        ))
    if persisted_agents != route.agents:
        raise TaskValidationError(ValidationResult(
            valid=False,
            errors=[(
                f'RESUME_ROUTE_EVIDENCE: persisted route.json route '
                f'({" -> ".join(persisted_agents)}) 与 snapshot-derived '
                f'required route ({" -> ".join(route.agents)}) 不一致——'
                f'resume rejected（fail closed；route.json 不得缩短或改变 '
                f'required route）'
            )],
        ))


def _load_resume_state(output_dir: Path, required_agents: list[str]) -> dict[str, str]:
    """从已有输出目录恢复 agent 结果（仅限 snapshot-derived required route）。

    FIX-005 Req 3/4：复用集合严格受 ``required_agents``（snapshot-derived
    required route）约束——即使 persisted route.json 被篡改成更短的链，
    也不得据此认为后续 agent 非必需；缺失的 required agent 在 resume 时
    重新执行。route.json 不参与结果加载范围。
    """
    results: dict[str, str] = {}
    for agent in required_agents:
        rf = output_dir / f'{agent}_result.md'
        if rf.exists():
            body = rf.read_text(encoding='utf-8')
            if not body.strip().startswith('FRAMEWORK_ERROR'):
                results[agent] = body
    return results


def _check_cancel(output_dir: Path, task_id: str, task_file: Path, workspace: Path) -> bool:
    """Safe checkpoint：读取 cancel.request（§6.3 / §6A.11）。

    - 无请求 / 无效请求（warning 记录，不拒绝执行，§6A.15）→ False（继续）
    - 有效请求 → Core 收敛：task.json(CANCELLED) → run.json(CANCELLED) →
      REPORT(CANCELLED)（§6A.4 顺序；经 state.lock 锁内提交 + reconciliation）
    - 若已有其他终态（如 SUCCESS 已 canonical committed）→ 保留现有终态，
      derived artifacts 跟随 canonical（§6A.2 late cancel 被吸收）
    - 返回 True = 任务已终态化（调用方应停止后续 Agent）
    """
    req, warning = cancel_mod.inspect_cancel_request(output_dir)
    if warning:
        print(f"[cancel] {warning}", file=sys.stderr)
        return False
    if req is None:
        return False
    if req.task_id != task_id:
        print(
            f"[cancel] cancel.request task_id 不匹配（{req.task_id!r} != {task_id!r}），已忽略",
            file=sys.stderr,
        )
        return False
    finalize_terminal(
        output_dir,
        task_id=task_id,
        status='CANCELLED',
        task_path=task_file,
        workspace=workspace,
        report_path=str(output_dir / 'REPORT.md'),
        reason='CANCEL_REQUESTED',
        terminal_reason=TERMINAL_REASON_CANCEL_REQUESTED,
        cancel_mode='soft',
    )
    # derived artifacts 跟随 canonical（幂等；若为 absorbed 场景则按其终态重建）
    reconcile_terminal_artifacts(task_id, workspace, output_dir)
    return True


def run(task_file: Path, workspace: Path, output_dir: Path, dry_run: bool = False, resume_from: Path | None = None,
        launch_id: str | None = None) -> Path:
    # --- Execution Identity / Snapshot Authority（FIX-004 Req 3/4） ---
    # 已有 execution directory（含 resume）：TASK.snapshot.md 存在 → snapshot 从入口
    # 起就是 execution authority——task validation / Task ID / route / boundary /
    # ownership handshake identity / 下游 prompt 一律基于 snapshot；active TASK 只作
    # provenance / resume request locator，绝不重新成为 execution authority。
    # 新 execution：intake active TASK → validate intake → freeze TASK.snapshot.md →
    # 从那一刻起所有 execution semantics 使用 snapshot（不得再使用 mutable intake）。
    exec_dir = resume_from if resume_from is not None else output_dir
    snapshot_path = exec_dir / 'TASK.snapshot.md'

    if snapshot_path.exists():
        task = snapshot_path.read_text(encoding='utf-8')
        result = validate_task_text(task)
        if not result.valid:
            raise TaskValidationError(result)
        # intake locator 与 snapshot identity 严重冲突（Task ID 不一致）→ 显式拒绝
        # resume，不得静默采用新 active 内容（FIX-004 Req 5）
        if task_file.exists():
            try:
                intake_id = parse_task_fields(task_file.read_text(encoding='utf-8')).get('Task ID')
            except (OSError, UnicodeError):
                intake_id = None
            snapshot_id = parse_task_fields(task).get('Task ID')
            if intake_id and snapshot_id and intake_id != snapshot_id:
                raise TaskValidationError(ValidationResult(
                    valid=False,
                    errors=[(
                        f"Execution identity conflict: active TASK Task ID {intake_id!r} "
                        f"!= snapshot Task ID {snapshot_id!r}——intake locator 与 "
                        f"execution snapshot 严重冲突，拒绝 resume（不得静默采用新 "
                        f"active 内容；确需新任务请使用新的 execution directory）"
                    )],
                ))
    else:
        task = task_file.read_text(encoding='utf-8')
        result = validate_task_text(task)
        if not result.valid:
            raise TaskValidationError(result)

    task_id = parse_task_fields(task)["Task ID"]  # 从 snapshot（或即将冻结的 intake）派生
    head_at_start = git_head(workspace)  # manifest HEAD（非 git 仓库 → None，不虚构）

    # --- Runner ownership handshake（TASK-005-B req 5/8；§6A.6-4） ---
    # control.json 缺失 → 跳过（direct/legacy 无 ownership 契约）；存在但不匹配 →
    # HandshakeError（fail safely：不接管 / 不执行 / 零 canonical 写）。
    # 位置：Validation 之后、任何 lifecycle 写入之前；handshake identity 使用
    # snapshot 派生的 task_id（FIX-004 Req 3）。
    runner_handshake(output_dir, task_id, workspace, expected_launch_id=launch_id)

    try:
        # --- Lifecycle 状态编排（确定性，不调用 LLM） ---
        def _ls(status, *, report_path=None, reason=None, stage=None, agent=None, phase_state="RUNNING"):
            res = task_lifecycle.update_status(
                output_dir,
                task_id=task_id,
                status=status,
                task_path=task_file,
                workspace=workspace,
                report_path=report_path,
                reason=reason,
                stage=stage,
                agent=agent,
                phase_state=phase_state,
            )
            if res.preserved:
                # §6A.2 / §6B.18 Case B：另一 finalizer（recovery/cancel/其他 runner）
                # 已提交终态（如 Agent 执行期间 CANCELLED）——late runtime/stage update
                # 被拒绝，canonical 保持不变；中断本 run，派生产物跟随 canonical。
                # FIX-001：update_status 与 terminal finalizer 共享 state.lock，
                # 锁内 reload 保证这里读到的是已提交的 terminal truth。
                raise task_lifecycle.TerminalAlreadyCommitted(res)
            return res

        def _finalize(status, *, report_path=None, reason=None, stage=None, agent=None, phase_state=None,
                      terminal_reason=None, cancel_mode=None):
            return finalize_terminal(
                output_dir,
                task_id=task_id,
                status=status,
                task_path=task_file,
                workspace=workspace,
                report_path=report_path,
                reason=reason,
                stage=stage,
                agent=agent,
                phase_state=phase_state,
                terminal_reason=terminal_reason,
                cancel_mode=cancel_mode,
            )

        # 检查点：Validation 完成后 / Boundary 前（取消 → 不启动后续任何环节）
        if _check_cancel(output_dir, task_id, task_file, workspace):
            return output_dir / 'REPORT.md'

        if resume_from is not None:
            output_dir = resume_from
            # --- Resume Route Authority（FIX-005 Req 1–4）---
            # authoritative route 必须重新从 immutable TASK.snapshot.md 派生
            # （此时 task 已是 snapshot 内容；无 snapshot 的 legacy 目录 =
            # 已验证 intake，随后补写为 snapshot）。route.json 只作 persisted
            # execution evidence：必须与 snapshot-derived route 完全一致，
            # 否则 fail closed（不启动后续 Agent / 不得 SUCCESS）。
            route = decide_route(task)
            _verify_resume_route_evidence(output_dir, route)
            # 结果复用集合受 snapshot-derived required route 约束：
            # tampered route.json 不得缩短 required agent set。
            results = _load_resume_state(output_dir, route.agents)
            # legacy resume 目录（FIX-002 之前的旧目录）可能没有 snapshot →
            # 从已验证任务内容补写（保证 manifest / prompt 引用可解析）
            if not (output_dir / 'TASK.snapshot.md').exists():
                (output_dir / 'TASK.snapshot.md').write_text(task, encoding='utf-8')
            _ls('RUNNING', reason='RESUMED')  # WAITING/... → RUNNING
        else:
            # --- Immutable Task Snapshot：freeze（FIX-002 Req 1/2 + FIX-004 Req 4） ---
            # 新 execution：intake 已校验 → 先冻结 TASK.snapshot.md，从此刻起
            # route / boundary / lifecycle / packet 一律使用 snapshot 内容，
            # 不再使用 mutable intake text。
            output_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(task, encoding='utf-8')
            # --- Boundary Check（snapshot 内容；warning-first，fail-open）---
            # 不阻断执行；边界模块自身错误也 fail-open（外围功能不使核心链路不可用）
            try:
                boundary = project_boundary.load_boundary(workspace)
                bcheck = project_boundary.check_task(boundary, task)
                project_boundary.write_boundary_json(output_dir, task_id, bcheck, boundary.source_path)
            except project_boundary.BoundaryError as exc:
                bcheck = project_boundary.BoundaryCheckResult(
                    configured=False,
                    warnings=[f"BOUNDARY_CHECK_ERROR: {exc}"],
                    matched_boundaries=[],
                    severity="NONE",
                    checked_at=datetime.now().isoformat(timespec="seconds"),
                )
                project_boundary.write_boundary_json(output_dir, task_id, bcheck, None)
            route = decide_route(task)
            # Route Completeness / Acceptance Bypass Guard（FIX-003 Req 3/4 + FIX-004 Req 7）：
            # TASK 显式声明的 Route 是 authoritative；Router 必须与其一致。
            # 若声明了 required route（如含 codex）而实际计算路由不含该 agent，
            # 必须在 Validation 阶段直接失败——不得跑完后误报 SUCCESS。
            # （decide_route 已优先采纳显式 Route；此处是防御性不变量断言。
            #   INVALID 显式 Route 已由 formal validation fail-closed，不会到达此处。）
            declared_route = parse_explicit_route(task)
            if declared_route.status is RouteStatus.VALID and route.agents != declared_route.agents:
                raise TaskValidationError(ValidationResult(
                    valid=False,
                    errors=[(
                        f"Route inconsistency: TASK 显式声明 Route: "
                        f"{' -> '.join(declared_route.agents)}，但 Router 计算结果为 "
                        f"{' -> '.join(route.agents)}——拒绝以错误路由继续执行"
                    )],
                ))
            results = {}
            _ls('CREATED')  # 通过 Validation，尚未执行 Agent 链

        # --- Hash Single Source（FIX-002 Req 2 + FIX-004 Req 1/2/6） ---
        # Task Hash = snapshot 文件原始 bytes 的标准 SHA-256（sha256_file），
        # bytes = 文件实际大小（stat().st_size）——外部工具（certutil / sha256sum /
        # hashlib.read_bytes）可直接复算，与换行风格（CRLF/LF）无关。
        # 整个 execution lifecycle 只计算一次，并在 manifest / prompt / REPORT 复用。
        task_hash = sha256_file(snapshot_path)
        task_bytes = file_bytes(snapshot_path)

        (output_dir / 'route.json').write_text(
            json.dumps({'agents': route.agents, 'reason': route.reason}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        dry = bool(dry_run)
        prompt_metrics: dict[str, dict] = {}
        # TASK-010：遥测开关只读一次（AAF_MODEL_OBSERVATION=0 关闭整层；
        # 默认开启。辅助 telemetry，不参与 execution authority）。
        mo_enabled = model_observation_mod.observations_enabled()
        if dry:
            status = 'DRY_RUN'  # 保留现有 dry-run 语义（route only，不执行 Agent）
            final_status = 'CREATED'  # 未正式执行 Agent 链 → 终态保持 CREATED，不伪装 SUCCESS
        else:
            # 检查点：Boundary 完成后 / Hermes 前（取消 → Hermes 不启动）
            if _check_cancel(output_dir, task_id, task_file, workspace):
                return output_dir / 'REPORT.md'
            _ls('RUNNING', reason=('RESUMED' if resume_from is not None else None))  # 真正进入执行链
            for agent in route.agents:
                if agent in results:
                    continue  # resume：复用已完成结果，不重复执行
                # 检查点：上一 Agent 完成后 / 下一 Agent 前
                # （Hermes 完成后 / WorkBuddy 前；WorkBuddy 完成后 / Codex 前）
                if _check_cancel(output_dir, task_id, task_file, workspace):
                    return output_dir / 'REPORT.md'
                stage_name = agent.upper()
                _ls('RUNNING', stage=stage_name, agent=agent, phase_state='RUNNING')
                # Stage Context Packet 协议（Requirement 4）：下游 prompt 只引用结构化摘要 +
                # artifact 路径；旧目录 / 缺 JSON 自动 legacy fallback（Requirement 8）
                # FIX-002 Req 1/2：task 引用统一使用 immutable snapshot（path + 单一 hash）
                head_before = git_head(workspace)
                prompt, prompt_meta = build_prompt_measured(
                    agent, task, results, workspace,
                    output_dir=output_dir, task_path=snapshot_path, task_hash=task_hash,
                )
                (output_dir / f'{agent}_prompt.md').write_text(prompt, encoding='utf-8')
                # Context size 可观测性（Requirement 10）：每 stage 记录 prompt chars/bytes +
                # embedded/referenced artifact counts
                prompt_metrics[agent] = {
                    **measure_prompt(prompt, prompt_meta.get('embedded_artifact_count', 0),
                                     prompt_meta.get('referenced_artifact_count', 0)),
                    'path': str(output_dir / f'{agent}_prompt.md'),
                }
                # TASK-010（Model Observability / Execution Metrics Foundation）：
                # stage 时序 + 只读模型 discovery。telemetry 是辅助层——任何 discovery
                # 失败都非阻塞（safe_discover_agent 吸收异常；UNKNOWN 记录）；
                # AAF_MODEL_OBSERVATION=0 时整层关闭（行为与引入前完全一致）。
                stage_started_iso = None
                stage_elapsed = None
                if mo_enabled:
                    stage_started_iso = datetime.now().isoformat(timespec='seconds')
                    stage_started_mono = time.monotonic()
                # v0.5 A3 active routing（authoritative；TASK: AAF-v0.5-A3-HERMES-FREE-ROUTING-001）。
                # 复用现有 Risk + Registry + selector（不创建第二套路由判断）：仅当
                # Hermes executor task 显式声明 Risk: LOW 且现有 selector 选出已
                # QUALIFIED 的 LOCAL_FREE/FREE candidate 时，本 shadow decision 升级为
                # 真实 model/provider 选择（routing_applied=true → 设置
                # AAF_HERMES_MODEL / AAF_HERMES_PROVIDER / AAF_HERMES_BASE_URL 覆盖，
                # adapters.run_agent 透传 -m / --provider；base_url = registry evidence
                # 端点事实，供 A0 guard 以既有 loopback 判定识别 LOCAL_FREE）。
                # 其余情况（Risk 缺失 / MEDIUM/HIGH/CRITICAL / 无候选 / 非 FREE /
                # qualification 不满足）→ routing_applied=false，保持 configured
                # model/provider。无 silent fallback：routing_applied 后 invocation
                # 失败按现有异常语义如实 FRAMEWORK_ERROR（链中断 → WAITING），
                # 绝不自动改用其他模型。审计 artifact = active_routing.json
                # （authoritative=true，与 shadow_observation.json 的 hypothetical
                # 决策明确区分）；artifact 写失败 → fail closed（无审计证据不得路由）。
                # env 覆盖在本 stage 全流程（含 model observation / shadow observation——
                # 它们必须如实看到实际 invocation model）之后还原，绝不影响后续 stage。
                routing_env_saved = None
                active_routing_ref = None
                wb_routing_env_saved = None
                wb_active_routing_ref = None
                if agent == 'hermes':
                    task_risk = parse_task_fields(task).get('Risk') or None
                    try:
                        _eff = cost_guard_mod.resolve_effective_hermes()
                        _cfg_model = _eff.get('model')
                        _cfg_provider = _eff.get('provider')
                    except Exception:
                        _cfg_model = None
                        _cfg_provider = None
                    active_record = active_routing_mod.decide_active_route(
                        task_risk, ROLE_EXECUTOR, agent,
                        model_registry_mod.baseline_registry(),
                        risk_source=(shadow_obs_mod.TASK_RISK_SOURCE
                                     if task_risk is not None else None),
                        configured_model=_cfg_model,
                        configured_provider=_cfg_provider,
                    )
                    active_routing_mod.save_active_routing(output_dir, active_record)
                    active_routing_ref = {
                        'authority': str(output_dir / active_routing_mod.ARTIFACT_FILENAME),
                        'entry': agent,
                    }
                    if active_record['routing_applied']:
                        routing_env_saved = active_routing_mod.apply_routing_env(active_record)
                elif agent == 'workbuddy':
                    # v0.5 A4 active economic routing（TASK: AAF-v0.5-A4-WORKBUDDY-
                    # ECONOMIC-ROUTING-001 [LOW] + -002 [MEDIUM]；FIX-001：经济两
                    # 候选 gate 收口，A4 = STARTED）。复用现有 selector
                    # （capability+qualification）+ A4 economic fact layer，不创建
                    # 第二套 eligibility 系统：仅当显式 Risk: LOW 或 MEDIUM（002
                    # 把 risk 域从 explicit LOW 扩展到 explicit LOW + MEDIUM；MEDIUM
                    # 复用同一 selector 的 capability floor —— risk_contract
                    # RISK_FLOORS[MEDIUM].validator = T3，绝不单独放宽 eligibility）
                    # 且至少两个 eligible WorkBuddy candidates 且经济事实
                    # FRESH/完整/一致/可审计 **且经济过滤后仍至少两个可信候选**
                    # （FIX-001：economically_trustworthy >= 2 —— 两候选 gate 作用
                    # 于 capability+qualification+trustworthy-economics 全部过滤
                    # 之后，只剩 1 个 → INSUFFICIENT_ECONOMIC_CANDIDATES → Auto）
                    # 时，经济 winner 升级为真实 per-run --model
                    # （routing_applied=true → 设置 AAF_WORKBUDDY_MODEL 覆盖，
                    # adapters._workbuddy_invocation 精确追加 --model <winner>；
                    # 无 --effort / 无 provider override / 无 fallback / 无 retry
                    # escalation）。其余情况（Risk 缺失 / HIGH/CRITICAL /
                    # 不足两个 eligible / 经济事实 stale-unknown-不完整 / 经济后
                    # 不足两个可信候选 / 无确定性可信经济 winner）→
                    # routing_applied=false，保持 CodeBuddy Auto。审计 artifact =
                    # workbuddy_active_routing.json（authoritative=true，与
                    # shadow_observation.json hypothetical / active_routing.json A3
                    # Hermes 明确区分）；artifact 写失败 → fail closed（无审计证据
                    # 不得路由）。无 silent fallback：routing 后 invocation 失败按
                    # 现有异常语义如实 FRAMEWORK_ERROR（链中断 → WAITING），绝不
                    # 自动退回 Auto 或换模型。
                    task_risk = parse_task_fields(task).get('Risk') or None
                    wb_record = workbuddy_routing_mod.decide_workbuddy_route(
                        task_risk, ROLE_VALIDATOR, agent,
                        model_registry_mod.baseline_registry(),
                        facts=None,
                        now=datetime.now().astimezone(),
                        risk_source=(shadow_obs_mod.TASK_RISK_SOURCE
                                     if task_risk is not None else None),
                    )
                    workbuddy_routing_mod.save_workbuddy_routing(output_dir, wb_record)
                    wb_active_routing_ref = {
                        'authority': str(output_dir / workbuddy_routing_mod.ARTIFACT_FILENAME),
                        'entry': agent,
                    }
                    if wb_record['routing_applied']:
                        wb_routing_env_saved = workbuddy_routing_mod.apply_workbuddy_model_env(wb_record)
                # v0.5 A5（TASK: AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001）：Hermes
                # executor stage 的**原始 invocation 真实失败后**（本 try/except
                # 捕获到 invocation 异常），至多一次 automatic FREE/LOCAL_FREE
                # model-level fallback（decision authority =
                # fallback_contract.decide_fallback；Requirement-3 cost gate 复用
                # A3 成本闸词汇；candidate admission 复用 A0 Paid Guard）。
                # A3 初始 active-routing 行为零修改（fallback 绝不与 initial
                # model selection 混淆）；Risk 缺失 → 无法按 contract 决策 →
                # 不评估（保持原失败语义）。audit artifact = fallback_runtime.json。
                # A5 层内部任何异常都不掩盖原始 stage 失败（记录到 stderr）。
                fb_exc = None
                try:
                    if agent == 'hermes':
                        # v0.5 A0 Paid Guard（fail-closed，TASK: AAF-v0.5-A0-PAID-GUARD-001）：
                        # Hermes subprocess 创建前求值成本授权。付费/成本未知模型在无
                        # 精确 task-scoped 授权时 → BLOCKED_COST_APPROVAL（Hermes 不启动，
                        # blocked 文本以 FRAMEWORK_ERROR 开头 → 链中断 → WAITING；
                        # resume 时不会把 blocked result 当已完成结果复用）。
                        # FIX-002/FIX-003：state_dir=output_dir —— 一次性授权在准入
                        # 边界原子 claim（exclusive-create 跨进程权威），同 execution
                        # 上下文内同一授权值不可 replay（fail closed）。
                        # A3：routing_applied 时 env 覆盖已生效——guard 解析的
                        # effective model == 实际 invocation model（既有不变量保持）；
                        # LOCAL_FREE 候选经既有 classify_cost loopback 判定放行，
                        # Paid Guard 未被绕过（非免费路径继续遵循 A0 规则）。
                        guard_record = cost_guard_mod.evaluate(
                            task_id, agent, state_dir=output_dir
                        )
                        (output_dir / cost_guard_mod.ARTIFACT_FILENAME).write_text(
                            json.dumps(guard_record, ensure_ascii=False, indent=2),
                            encoding='utf-8',
                        )
                        if guard_record['decision'] == cost_guard_mod.DECISION_BLOCKED_COST_APPROVAL:
                            result_text = cost_guard_mod.blocked_stage_text(guard_record)
                        else:
                            result_text = run_agent(agent, prompt, workspace)
                    else:
                        result_text = run_agent(agent, prompt, workspace)
                except Exception as exc:
                    fb_exc = exc
                    result_text = f'FRAMEWORK_ERROR\n{type(exc).__name__}: {exc}'
                # v0.5 A5（续）：真实原始 invocation 失败（异常）后才评估 fallback；
                # guard 前置阻断（无异常、COST_APPROVAL_REQUIRED 文本）不是模型执行
                # 失败 → 无 fallback 上下文（A0 authority 持有），不评估。
                fallback_runtime_ref = None
                fallback_overlay_saved = None
                if agent == 'hermes' and fb_exc is not None:
                    try:
                        fb_risk = parse_task_fields(task).get('Risk') or None
                        if fb_risk is not None:
                            fb_outcome = fallback_runtime_mod.run_fallback_after_failure(
                                task_id=task_id,
                                risk_class=fb_risk,
                                risk_source=shadow_obs_mod.TASK_RISK_SOURCE,
                                stage_agent=agent,
                                role=ROLE_EXECUTOR,
                                registry=model_registry_mod.baseline_registry(),
                                output_dir=output_dir,
                                prompt=prompt,
                                workspace=workspace,
                                invoke=run_agent,
                                failure_exc=fb_exc,
                            )
                            if fb_outcome is not None:
                                if fb_outcome.get('result_text') is not None:
                                    result_text = fb_outcome['result_text']
                                a5_audit_closure_error = fb_outcome.get('audit_closure_error')
                                if a5_audit_closure_error:
                                    # v0.5 A5 FIX-001：authoritative audit 未闭合 →
                                    # fallback 输出不得成为 stage result（fallback
                                    # 层已返回 result_text=None / used=false）——
                                    # 显式 surface audit failure：stderr + 追加到
                                    # stage result 文本（attempt 证据持久化，绝不
                                    # 静默丢弃；不发起第三模型、不重试 fallback）。
                                    print(
                                        f'[a5-fallback] {a5_audit_closure_error}',
                                        file=sys.stderr,
                                    )
                                    result_text = (
                                        f'{result_text}\n'
                                        'FRAMEWORK_ERROR[a5-fallback audit '
                                        'closure failed]: '
                                        f'{a5_audit_closure_error}'
                                    )
                                fallback_runtime_ref = fb_outcome.get('artifact_ref')
                                fallback_overlay_saved = fb_outcome.get('overlay_saved') or None
                    except Exception as a5_exc:
                        # A5 层内部失败不得掩盖原始 stage 失败（也不得导致第二模型）
                        print(
                            f'[a5-fallback] layer error: {type(a5_exc).__name__}: {a5_exc}',
                            file=sys.stderr,
                        )
                # TASK-011：WorkBuddy stage attempt telemetry（machine artifact；
                # supporting evidence——canonical 结果仍只有 <agent>_result.md/json）。
                wb_retry_meta = None
                if agent == 'workbuddy':
                    wb_retry_meta = adapters_mod.pop_workbuddy_telemetry()
                    if wb_retry_meta:
                        (output_dir / 'workbuddy_attempts.json').write_text(
                            json.dumps(wb_retry_meta, ensure_ascii=False, indent=2),
                            encoding='utf-8',
                        )
                if mo_enabled:
                    stage_elapsed = round(time.monotonic() - stage_started_mono, 3)
                results[agent] = result_text
                (output_dir / f'{agent}_result.md').write_text(result_text, encoding='utf-8')
                # Structured stage result（Requirement 5 + FIX-002 Req 6–9）：
                # narrative 保留追溯；机器可读块经提取 + schema validation 后合并；
                # findings/warnings 未提供 → None（UNKNOWN），绝不伪装为空数组；
                # summary 不完整 / 与 narrative 不一致 → 显式 PARTIAL/UNKNOWN。
                structured, structured_status = extract_and_validate_structured(agent, result_text)
                model_ref = None
                shadow_ref = None  # v0.5 A2-002：telemetry 关闭时同样不产生 shadow artifact
                if mo_enabled:
                    # 只读 discovery（帮助/config 查询；不发付费推理、不改任何配置）；
                    # registry（model_observation.json）是 model observation 单一 authority，
                    # stage result 只携带引用（无重复 truth source）。
                    # 双保险非阻塞：observe_stage 内部自吸收 + runner 级 try/except，
                    # 任何 telemetry 失败（含 registry 写失败）都不影响 Agent 执行。
                    try:
                        observation = model_observation_mod.observe_stage(output_dir, agent)
                    except Exception:
                        observation = None
                    if observation is not None:
                        model_ref = {
                            'authority': str(output_dir / model_observation_mod.ARTIFACT_FILENAME),
                            'entry': agent,
                        }
                    # v0.5 A2-002：Hermes shadow observation（observation-only bypass）。
                    # 只接 Hermes stage（Requirement 1，不扩到 WorkBuddy/Codex）；非阻塞
                    # （任何失败 → 无 artifact，绝不影响 Agent 执行）；shadow 路径不发起
                    # 任何额外 CLI / provider / LLM 调用——只消费上面的 observation 并写
                    # audit JSON（Requirement 5）。
                    # v0.5 A2-003：TASK Risk 字段 = Planner 显式声明的结构化 task risk
                    # （唯一权威词汇 risk_contract.RISK_CLASSES；snapshot 已通过
                    # validate_task_text，非法值在 Validation 阶段 fail-closed）。runner
                    # 只读解析 snapshot 顶层 Risk 字段并透传给 shadow observation——
                    # risk_source 固定标记为 task/planner provenance；缺失 → 保持
                    # RISK_UNAVAILABLE（绝不从 prose / Task Name / Route / 路径推断）。
                    shadow_ref = None
                    if agent == 'hermes':
                        try:
                            task_risk = parse_task_fields(task).get('Risk') or None
                            shadow_record = shadow_obs_mod.observe_shadow_stage(
                                output_dir, agent, observation=observation,
                                risk_class=task_risk,
                                risk_source=(shadow_obs_mod.TASK_RISK_SOURCE
                                             if task_risk is not None else None),
                            )
                        except Exception:
                            shadow_record = None
                        if shadow_record is not None:
                            shadow_ref = {
                                'authority': str(output_dir / shadow_obs_mod.ARTIFACT_FILENAME),
                                'entry': agent,
                            }
                # v0.5 A5：fallback candidate env 覆盖还原（同样在 observation
                # 之后——observation 必须如实看到 final actual invocation model；
                # 还原顺序 = 设置的逆序：先 fallback overlay，再 A3 routing）。
                if fallback_overlay_saved is not None:
                    active_routing_mod.restore_routing_env(fallback_overlay_saved)
                # v0.5 A3：routing env 覆盖还原（在 model observation / shadow
                # observation 之后——它们必须如实看到实际 invocation model）。
                if routing_env_saved is not None:
                    active_routing_mod.restore_routing_env(routing_env_saved)
                # v0.5 A4：WorkBuddy AAF_WORKBUDDY_MODEL 覆盖还原（同样在
                # observation 之后；绝不泄漏到后续 stage / 调用方）。
                if wb_routing_env_saved is not None:
                    workbuddy_routing_mod.restore_workbuddy_model_env(wb_routing_env_saved)
                head_after = git_head(workspace)
                stage = build_stage_result(
                    agent=agent,
                    result_text=result_text,
                    output_dir=output_dir,
                    head_before=head_before,
                    head_after=head_after,
                    changed_files=git_changed_files(
                        workspace, head_before=head_before, head_after=head_after
                    ),
                    structured=structured,
                    structured_status=structured_status,
                    stage_started_at=stage_started_iso,
                    stage_elapsed_seconds=stage_elapsed,
                    model_observation_ref=model_ref,
                )
                if wb_retry_meta:
                    # TASK-011：attempt 摘要进 stage result（Model Observation 可读
                    # attempt_count；详细 attempt evidence 在 workbuddy_attempts.json）
                    stage['execution_retries'] = {
                        'agent': 'workbuddy',
                        'attempt_count': wb_retry_meta.get('attempt_count'),
                        'retried': bool(wb_retry_meta.get('retried')),
                        'outcome': wb_retry_meta.get('outcome'),
                        'artifact_path': str(output_dir / 'workbuddy_attempts.json'),
                    }
                if shadow_ref:
                    # v0.5 A2-002：shadow observation authority 引用（不复制记录内容；
                    # 详细 shadow 决策/状态在 shadow_observation.json）。
                    stage['shadow_observation_ref'] = dict(shadow_ref)
                if active_routing_ref:
                    # v0.5 A3-001：authoritative active-routing authority 引用
                    # （详细决策在 active_routing.json；与 shadow 引用并存——
                    # hypothetical shadow decision 与 authoritative active decision
                    # 在 stage result 中明确区分）。
                    stage['active_routing_ref'] = dict(active_routing_ref)
                if fallback_runtime_ref:
                    # v0.5 A5-001：authoritative A5 fallback runtime audit 引用
                    # （详细记录在 fallback_runtime.json——仅当 Hermes stage 原始
                    # invocation 失败并触发 A5 评估时存在）。
                    stage['fallback_runtime_ref'] = dict(fallback_runtime_ref)
                if wb_active_routing_ref:
                    # v0.5 A4-001：WorkBuddy authoritative active-routing authority
                    # 引用（详细决策在 workbuddy_active_routing.json；与 A3 Hermes
                    # active_routing.json 及 A2 shadow_observation.json 明确区分）。
                    stage['workbuddy_active_routing_ref'] = dict(wb_active_routing_ref)
                write_stage_result(output_dir, stage)
                valid = _result_is_valid(result_text)
                _ls('RUNNING', stage=stage_name, agent=agent, phase_state=('SUCCESS' if valid else 'FAILED'))
                if not valid:
                    break  # 执行链保护：必需节点无有效结果 → 停止后续节点
            # 检查点：Codex 完成后 / Report finalization 前
            if _check_cancel(output_dir, task_id, task_file, workspace):
                return output_dir / 'REPORT.md'
            status = _aggregate_status(route.agents, results, output_dir)
            final_status = 'SUCCESS' if status == 'SUCCESS' else 'WAITING'

        # 执行链完整性保护：必需 Executor / Validator / Reviewer 无有效结果 → REPORT 明确标记
        # （FIX-003 Req 3：required route 含 codex 而 codex 未执行 / 缺结果 /
        # FRAMEWORK_ERROR → 不得 SUCCESS；_aggregate_status 已保证 WAITING，
        # 这里补充显式 integrity note。dry-run 不执行 Agent，属预期，不生成误导性 notes）
        integrity_notes = []
        if not dry:
            if 'hermes' in route.agents and not _result_is_valid(results.get('hermes', '')):
                integrity_notes.append('Required executor Hermes did not run or produced no valid result')
            if 'workbuddy' in route.agents and not _result_is_valid(results.get('workbuddy', '')):
                integrity_notes.append('Required validator WorkBuddy did not run or produced no valid result')
            if 'codex' in route.agents and not _result_is_valid(results.get('codex', '')):
                integrity_notes.append('Required reviewer Codex did not run or produced no valid result')

        # Context Manifest / Integrity（Requirement 6）：stage 产物 path+hash 可追溯引用；
        # 引用模式不因文件后来变化而失去可追溯性（check_references 可验证）
        manifest_stages = {}
        for agent in route.agents:
            md = output_dir / f'{agent}_result.md'
            js = output_dir / f'{agent}_result.json'
            manifest_stages[agent] = {
                'result_md': {'path': str(md), 'hash': sha256_file(md), 'bytes': file_bytes(md)},
                'result_json': {'path': str(js), 'hash': sha256_file(js), 'bytes': file_bytes(js)},
            }
        write_manifest(
            output_dir,
            task_path=snapshot_path,
            task_hash=task_hash,
            task_bytes=task_bytes,
            workspace=str(workspace),
            head=head_at_start,
            stages=manifest_stages,
            prompts=prompt_metrics,
            intake_task_path=task_file,
        )

        # Remote Sync 真值（FIX-002 Req 4/5）：区分 commit graph sync 与 tracked tree；
        # Task Remote Sync 仅当 tracked 修改已 commit + push 才为 SYNCED。
        # 非 git 仓库 → NOT_APPLICABLE（REPORT 不输出 Remote Sync 段，不虚构）。
        sync_state = remote_sync_state(workspace)

        # TASK-010：REPORT 只拿紧凑 model observation 摘要（lazy artifact；
        # 详细 discovery metadata 只在 model_observation.json）。
        # dry-run 不执行 Agent → 无观测数据 → 不输出该段（不虚构）。
        model_observations = None
        if mo_enabled and not dry:
            model_observations = model_observation_mod.model_report_data(output_dir, route.agents)

        report = build_report(
            task, route.agents, results, status, integrity_notes,
            task_path=snapshot_path, task_hash=task_hash, output_dir=output_dir,
            sync_state=sync_state, intake_task_path=task_file,
            model_observations=model_observations,
        )
        report_path = output_dir / 'REPORT.md'

        # REPORT 阶段完成 + 终态（dry-run: CREATED + reason=DRY_RUN；REPORT 生成后回填 report_path）
        if not dry:
            # §6A.4 artifact order：Core 裁决 → task.json 终态提交（锁内）→ run.json → REPORT
            _ls('RUNNING', stage='REPORT', agent=None, phase_state='SUCCESS')
            terminal_reason = (
                TERMINAL_REASON_NORMAL_COMPLETION if final_status == 'SUCCESS' else TERMINAL_REASON_WAITING
            )
            canonical = _finalize(
                final_status,
                report_path=report_path,
                stage='COMPLETED',
                agent=None,
                phase_state=('SUCCESS' if final_status == 'SUCCESS' else 'WAITING'),
                terminal_reason=terminal_reason,
            )
            if canonical.status != final_status:
                # 另一 finalizer 先 commit（§6B.18 Case B：如 recovery 已写 CANCELLED）：
                # 保留现有 canonical，派生产物跟随 canonical（不覆盖成 SUCCESS/WAITING）
                reconcile_terminal_artifacts(task_id, workspace, output_dir)
                report_path = output_dir / 'REPORT.md'
            else:
                # 我们胜出：run.json 跟随 canonical terminal（status + generation）
                (output_dir / 'run.json').write_text(
                    json.dumps(
                        {
                            'timestamp': canonical.terminal_at or datetime.now().isoformat(timespec='seconds'),
                            'status': canonical.status,
                            'terminal_generation': canonical.terminal_generation,
                            'task_id': task_id,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding='utf-8',
                )
                # REPORT 跟随 canonical（附加 Terminal Generation provenance，§6B.4）
                report = build_report(
                    task, route.agents, results, status, integrity_notes,
                    terminal=canonical.to_dict(),
                    task_path=snapshot_path, task_hash=task_hash, output_dir=output_dir,
                    sync_state=sync_state, intake_task_path=task_file,
                    model_observations=model_observations,
                )
                report_path.write_text(report, encoding='utf-8')
        else:
            _ls(final_status, report_path=report_path, reason=('DRY_RUN' if dry else None))
            report_path.write_text(report, encoding='utf-8')
        return report_path
    except TaskValidationError:
        raise  # Validation 失败：不进 Lifecycle（不生成虚假状态）
    except task_lifecycle.TerminalAlreadyCommitted as exc:
        # §6B.18 Case B（FIX-001）：另一 finalizer 已提交终态（典型：Agent 执行期间
        # recovery/cancel finalizer 提交 CANCELLED）。Runner 的 late runtime/stage
        # update 已被拒绝（canonical 保持终态）；不再启动后续 Agent；
        # 派生产物跟随 canonical（run.json / REPORT 由 reconciliation 补齐）。
        # 已完成 agent artifacts 保留（reconciliation 不删除任何 artifact）。
        reconcile_terminal_artifacts(task_id, workspace, output_dir)
        return output_dir / 'REPORT.md'
    except Exception as exc:
        # Framework 级失败：锁内提交 FAILED 终态后重新抛出（保持调用方行为；异常中断也有明确 lifecycle 记录）
        try:
            finalize_terminal(
                output_dir,
                task_id=task_id,
                status='FAILED',
                task_path=task_file,
                workspace=workspace,
                reason=f'FRAMEWORK_ERROR: {type(exc).__name__}: {exc}',
                terminal_reason=TERMINAL_REASON_FRAMEWORK_ERROR,
            )
        except Exception:
            pass  # FAILED 记录本身失败不能掩盖原始异常
        raise


def main() -> None:
    p = argparse.ArgumentParser(description='AI Agent Framework v0.2 prototype runner')
    p.add_argument('task', type=Path, help='TASK.md path')
    p.add_argument('--workspace', type=Path, required=True, help='Business project workspace')
    p.add_argument('--output', type=Path, default=Path('.aaf-run'), help='Run output directory')
    p.add_argument('--dry-run', action='store_true', help='Route only; do not invoke agents')
    p.add_argument('--resume-from', type=Path, default=None, help='Resume an existing run output dir (reuses completed agent results)')
    p.add_argument('--launch-id', default=None, help='Expected launch_id for ownership handshake (TASK-005-B; Launcher 传入)')
    args = p.parse_args()
    try:
        report = run(args.task, args.workspace, args.output, args.dry_run, args.resume_from,
                     launch_id=args.launch_id)
    except HandshakeError as exc:
        # ownership handshake 失败：fail safely（不接管 / 不执行 / 零 canonical 写）
        print(str(exc), file=sys.stderr)
        raise SystemExit(3)
    except TaskValidationError as exc:
        # 校验失败：清晰错误 + 非零退出；不进入 Router / 不启动 Agent
        print(str(exc))
        print(f"Task: {args.task}")
        raise SystemExit(2)
    print(report)


if __name__ == '__main__':
    main()
