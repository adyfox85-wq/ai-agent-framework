"""AAF Bridge — Framework Launcher（Transport + Launcher + Status Observer）。

职责：
- 通过 subprocess 调用现有正式入口 run.py（不复制执行链）
- 后台运行（独立进程 + 等待线程），不阻塞 Bridge UI / 热键
- 单任务并发保护（RUNNING 时拒绝新任务）
- 启动失败保护（保留已落盘 TASK.md，标记 FAILED_TO_START）
- 完成后定位 REPORT.md；缺失标记 REPORT_NOT_FOUND
- 保存 Last Task / Last Report / Last Result / Exit Code（供 V03-000-C 使用）

Bridge 自身状态：IDLE / RUNNING / FINISHED / FAILED_TO_START
（不替代 Framework 内部 SUCCESS / WAITING 等任务结论。）

Phase E（TASK-005-A + TASK-005-B）：
- TASK-005-A：RESULT_CANCELLED + wait thread 最小 canonical-aware 兼容读取
- TASK-005-B（本文件主体）：Process Ownership / Force Cancel / Recovery Integration
  - launch_id（每次真实 launch 唯一；uuid4().hex）
  - control.json（task-owned 契约，§6A.7）与 Bridge launch registry（§6B.11）
  - launch order（§6B.12：launch_id → registry PREPARED → control → Popen →
    PID/creation time → RUNNING → runner handshake 回写）
  - ownership verification（§6A.8 11 项 / §6B.13 三方）→ VERIFIED 才允许 force kill
  - restart reauthentication（recover_launches，§6B.13；launcher_instance_id 只作诊断）
  - force cancel API（request_force_cancel：soft timeout 门槛 + ownership verification
    → taskkill /T /F（仅 verified PID）→ 结构化 force evidence → Core recovery
    finalizer（CLI 子进程）→ canonical CANCELLED → last_run 跟随 canonical）
  - 严禁 soft timeout 自动 taskkill（req 17）；显式 force request 才终止
  - wait thread canonical-aware（§6B.22：有 canonical 跟随 + 派生产物不完整 →
    reconciliation；无 canonical + force 已请求 → 轮询/调 finalizer 恢复；否则 legacy 分类）
  - Launcher 永不直接写 task.json 终态（§6A.1 / §14.4）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from . import config as cfg_mod
from . import launch_registry as reg_mod
from . import ownership as ownership_mod
from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import control as control_mod
from ai_agent_framework import force_evidence as force_evidence_mod
from ai_agent_framework import proc_identity
from ai_agent_framework.subprocess_utils import no_console_kwargs

IDLE = "IDLE"
RUNNING = "RUNNING"
FINISHED = "FINISHED"
FAILED_TO_START = "FAILED_TO_START"

# 结果细分（保存在 last_run）
RESULT_FINISHED = "FINISHED"
RESULT_FAILED = "FAILED"
RESULT_REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
RESULT_FAILED_TO_START = "FAILED_TO_START"
# Phase E（TASK-005-A 最小兼容，设计 §6A.5）：canonical terminal = CANCELLED 时
# wait thread 跟随 Core outcome 的 Bridge 侧分类；exit code 只是 evidence，不是判定。
RESULT_CANCELLED = "CANCELLED"

# force cancel 相关（TASK-005-B；设计 §6A.11 阈值配置化，默认 30s）
FORCE_CANCEL_SOFT_TIMEOUT_DEFAULT = 30.0
# force termination 后等待 canonical CANCELLED 的最长时间（request_force_cancel
# 同步调用 finalizer；wait thread 轮询此窗口吸收时序）
FORCE_CANONICAL_POLL_WAIT = 15.0
FORCE_CANONICAL_POLL_INTERVAL = 0.2
# Core CLI 子进程超时（reconcile / finalizer）
CORE_CLI_TIMEOUT = 90.0

# taskkill 成功终止的 exit code（FIX-001 req 5）：**只有 0** 才算 verified successful
# termination。128（进程已不存在）不是本进程终止动作的验证结果——nonzero /
# missing / malformed → fail closed，不得授权新的 CANCELLED。
_TASKKILL_OK_EXIT_CODES = (force_evidence_mod.SUCCESSFUL_TERMINATION_EXIT_STATUS,)

# 默认软取消超时（无配置时）
_DEFAULT_SOFT_TIMEOUT = 30.0


class AlreadyRunningError(RuntimeError):
    """已有 Framework TASK 在执行，拒绝并发。"""


class OwnershipRefusedError(RuntimeError):
    """ownership verification 未通过 → 拒绝 force termination（§6A.8：不能降级成
    “看起来像”就杀）。"""


@dataclass
class RunInfo:
    task_id: str
    task_path: str
    report_path: str | None
    exit_code: int | None
    result: str
    # Phase C：任务输出目录（<ws>/.aaf/<task_id>）。legacy last_run.json 缺失时默认 None，
    # 状态窗口据此读取 task.json / route.json / REPORT.md。
    output_dir: str | None = None
    # TASK-005-B：last_run 镜像 canonical 的 provenance（诊断用；非 terminal truth）
    launch_id: str | None = None
    terminal_generation: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ForceCancelResult:
    """request_force_cancel 的结构化结果（拒绝 / 成功 / 证据 / finalizer 结果）。"""

    task_id: str
    ok: bool
    launch_id: str | None = None
    refusal_reason: str | None = None
    verdict: ownership_mod.OwnershipVerdict | None = None
    evidence_path: str | None = None
    termination_exit_status: int | None = None
    termination_output: str | None = None
    finalizer_exit_code: int | None = None
    finalizer_output: str | None = None
    canonical_status: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict.to_dict() if self.verdict else None
        return d


class FrameworkLauncher:
    def __init__(self, run_py: Path | None = None, on_finished=None, registry_dir: Path | None = None):
        self.state = IDLE
        self.last: RunInfo | None = None
        self.current: RunInfo | None = None  # 正在执行的任务（内存只读事实；结束后清空）
        self.on_finished = on_finished  # 回调（主线程轮询时调用）
        self._run_py = run_py  # 测试注入；默认定位仓库 run.py
        self._lock = threading.Lock()
        # TASK-005-B：launcher instance identity（§6B.16——只作诊断来源；restart 接管
        # 不要求 instance_id 相同）
        self.launcher_instance_id = reg_mod.new_launch_id()
        self._registry_dir = registry_dir  # 测试注入；默认 registry_root()
        self._active_launch: dict[str, str] = {}  # task_id → launch_id（内存活跃映射）
        self.recovered_ownership: dict[str, ownership_mod.OwnershipVerdict] = {}  # restart 认证结果（只读诊断）

    # ---------- 路径 ----------

    @staticmethod
    def default_run_py() -> Path:
        """仓库根 run.py（本文件上级的上级）。"""
        return Path(__file__).resolve().parent.parent / "run.py"

    def _resolve_run_py(self) -> Path:
        p = self._run_py or self.default_run_py()
        return p.resolve()

    @staticmethod
    def default_output_dir(workspace: str, task_id: str) -> Path:
        """Framework 输出目录：<Workspace>\\.aaf\\<Task-ID>（沿用业务项目惯例）。"""
        return Path(workspace) / ".aaf" / task_id

    @staticmethod
    def report_path_for(output_dir: Path) -> Path:
        return output_dir / "REPORT.md"

    @staticmethod
    def _read_canonical_terminal(output_dir: Path) -> dict | None:
        """只读 Core canonical terminal（§6A.5 wait thread 跟随 Core outcome）。

        经 ai_agent_framework.task_lifecycle 的只读 reader（§14.4 允许的只读 Core 依赖）；
        无终态 / 读取失败 → None（回退 legacy 分类）。绝不在此写终态。
        """
        try:
            from ai_agent_framework.task_lifecycle import read_canonical_terminal

            result = read_canonical_terminal(output_dir)
            return result.to_dict() if result is not None else None
        except Exception:
            return None

    @staticmethod
    def _derived_consistent(output_dir: Path, canonical: dict) -> bool:
        """派生产物是否已跟随 canonical（run.json status+generation + REPORT 存在）。

        只做廉价检查；不完整 → 调用方触发 Core reconciliation CLI（幂等）。
        """
        run_path = output_dir / "run.json"
        if not run_path.exists():
            return False
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(run, dict):
            return False
        if run.get("status") != canonical.get("status"):
            return False
        if run.get("terminal_generation") != canonical.get("terminal_generation"):
            return False
        return (output_dir / "REPORT.md").exists()

    # ---------- Core CLI 子进程调用（§14.4：Launcher 不 import Core 执行逻辑） ----------

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _run_core_cli(self, argv: list[str], timeout: float = CORE_CLI_TIMEOUT) -> subprocess.CompletedProcess | None:
        """以无控制台子进程调用正式 Core entry point（reconcile / finalize_cancelled）。

        任何失败（OS / timeout / 子进程 API 异常）都返回伪 CompletedProcess——
        Core CLI 失败**绝不能**让 wait thread 崩溃（分类仍按 canonical 进行）。
        """
        try:
            return subprocess.run(
                [sys.executable, *argv],
                cwd=str(self._repo_root()),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **no_console_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001 —— CLI 失败不阻断 wait thread 收尾
            try:
                return subprocess.CompletedProcess(argv, -1, stdout="", stderr=f"core CLI 失败: {type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001
                return None

    def _invoke_reconcile(self, task_id: str, workspace: str, output_dir: Path) -> int | None:
        """派生产物不完整 → Core reconciliation（幂等；不改 canonical；§6B.7-C）。"""
        proc = self._run_core_cli(
            ["-m", "ai_agent_framework.reconcile",
             "--task-id", task_id, "--workspace", str(workspace), "--output", str(output_dir)]
        )
        return proc.returncode if proc is not None else None

    def _invoke_force_recovery(
        self, task_id: str, workspace: str, output_dir: Path, evidence_path: Path,
    ) -> tuple[int | None, str]:
        """verified force termination 后调用 Core recovery finalizer（§6A.12/§6B.17；
        幂等；Launcher 不直接写终态）。返回 (exit_code, output)。"""
        proc = self._run_core_cli(
            ["-m", "ai_agent_framework.finalize_cancelled",
             "--task-id", task_id, "--workspace", str(workspace), "--output", str(output_dir),
             "--reason", "FORCE_CANCELLED", "--cancel-mode", "force",
             "--force-evidence", str(evidence_path)]
        )
        if proc is None:
            return None, ""
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    # ---------- 启动 ----------

    def launch(self, task_path: Path, workspace: str, output_dir: Path, task_id: str,
               launch_id: str | None = None) -> bool:
        """启动 Framework 执行链（后台）。返回 True=已启动；抛 AlreadyRunningError=并发。

        启动失败（run.py 缺失/OSError）→ state=FAILED_TO_START，返回 False；
        已落盘 TASK.md 保留不动。

        TASK-005-B launch order（§6B.12）：
        A. generate launch_id（同一 task 新 launch 必须新 launch_id；旧 launch 被 supersede）
        B. registry PREPARED
        C. control.json（同一 launch_id；expected_command_line = 本次真实 argv）
        D. launch runner（Popen，--launch-id 传入）
        E. get runner PID
        F. get runner creation time（真实 Windows 进程创建时间）→ registry/control RUNNING
        G. Runner handshake（runner 进程内）校验并回写 runner_pid / runner_creation_time
        """
        with self._lock:
            if self.state == RUNNING:
                raise AlreadyRunningError("AAF_TASK_ALREADY_RUNNING")
            run_py = self._resolve_run_py()
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # A. 每次真实 launch 生成唯一 launch_id（§6A.6）
            new_launch_id = launch_id or reg_mod.new_launch_id()

            # 同一 task 的旧活跃 launch → supersede（registry SUPERSEDED；TASK req 13）
            superseded = reg_mod.supersede_existing_for_task(task_id, new_launch_id, root=self._registry_dir)
            for old_id in superseded:
                # 旧 control（若仍指向旧 launch）标记 superseded_by（新 control 写入会覆盖）
                try:
                    old_ctrl, cerr = control_mod.read_control(output_dir)
                    if old_ctrl is not None and old_ctrl.get("launch_id") == old_id and not old_ctrl.get("superseded_by"):
                        control_mod.update_control(output_dir, {"superseded_by": new_launch_id}, task_id=task_id)
                except control_mod.ControlError:
                    pass

            argv = [
                sys.executable,
                str(run_py),
                str(task_path),
                "--workspace",
                str(workspace),
                "--output",
                str(output_dir),
                "--launch-id",
                new_launch_id,
            ]

            # B. registry PREPARED（§6B.12-B）
            reg_mod.create_prepared(
                launch_id=new_launch_id,
                task_id=task_id,
                workspace=str(workspace),
                output_dir=str(output_dir),
                expected_runner_entry=run_py.name,
                expected_command_line=argv,
                launcher_instance_id=self.launcher_instance_id,
                root=self._registry_dir,
            )

            # C. control.json（§6B.12-C；task-owned；原子写 + schema 验证）
            control_mod.write_control(
                output_dir,
                control_mod.new_control(
                    task_id=task_id,
                    workspace=str(workspace),
                    launch_id=new_launch_id,
                    launcher_pid=os.getpid(),
                    launcher_instance_id=self.launcher_instance_id,
                    expected_runner_entry=run_py.name,
                    expected_command_line=argv,
                ),
                task_id=task_id,
            )

            # D. launch runner（无控制台；§6A.4 同款 no_console_kwargs——req 36）
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=str(run_py.parent),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **no_console_kwargs(),  # Windows: CREATE_NO_WINDOW，run.py 不新建 console 窗口
                )
            except OSError as e:
                # 启动失败：registry 不得永久 PREPARED；control 不得留 phantom RUNNING
                # （§6B.12 / TASK req 7）
                try:
                    reg_mod.mark_exited(
                        new_launch_id, exit_result=RESULT_FAILED_TO_START,
                        note=f"Popen failed: {e}", root=self._registry_dir,
                    )
                    control_mod.update_control(
                        output_dir, {"start_failed": True, "start_failed_at": datetime.now().isoformat(timespec="seconds")},
                        task_id=task_id,
                    )
                except (reg_mod.RegistryError, control_mod.ControlError):
                    pass
                self.state = FAILED_TO_START
                self.last = RunInfo(
                    task_id=task_id,
                    task_path=str(task_path),
                    report_path=None,
                    exit_code=None,
                    result=RESULT_FAILED_TO_START,
                    output_dir=str(output_dir),
                    launch_id=new_launch_id,
                )
                self._persist_last()
                return False

            # E/F. PID + 真实 Windows process creation time → registry/control RUNNING（§6B.12-F）
            runner_pid = getattr(proc, "pid", None)
            runner_ct = None
            if runner_pid is not None:
                ct = proc_identity.process_creation_time(runner_pid)
                runner_ct = ct.isoformat(timespec="milliseconds") if ct is not None else None
            try:
                if runner_pid is not None:
                    reg_mod.mark_running(new_launch_id, runner_pid, runner_ct, root=self._registry_dir)
                    # launch_root_pid = Popen 直连子（进程树 kill 根；runner 自报 pid 可能不同——
                    # uv venv python 重定向壳场景：真实解释器是壳的子进程）
                    reg_mod.update_registry(
                        new_launch_id, {"launch_root_pid": int(runner_pid)}, root=self._registry_dir,
                    )
                    control_mod.update_control(
                        output_dir,
                        {"runner_pid": runner_pid, "runner_creation_time": runner_ct},
                        task_id=task_id,
                    )
                else:
                    reg_mod.update_registry(new_launch_id, {"state": reg_mod.REGISTRY_STATE_RUNNING}, root=self._registry_dir)
            except (reg_mod.RegistryError, control_mod.ControlError):
                pass  # RUNNING 标记失败不阻断启动；ownership verification 会因缺字段 fail closed

            self.state = RUNNING
            # 内存只读事实：当前正在执行的任务（供状态窗口解析当前任务；不落盘）
            self.current = RunInfo(
                task_id=task_id,
                task_path=str(task_path),
                report_path=None,
                exit_code=None,
                result="RUNNING",
                output_dir=str(output_dir),
                launch_id=new_launch_id,
            )
            self._active_launch[task_id] = new_launch_id

        threading.Thread(
            target=self._wait_and_finish,
            args=(proc, task_path, workspace, output_dir, task_id, new_launch_id),
            daemon=True,
            name="aaf-bridge-framework-wait",
        ).start()
        return True

    # ---------- 等待与收尾（TASK-005-B：canonical-aware，§6B.22） ----------

    def _wait_and_finish(
        self, proc: subprocess.Popen, task_path: Path, workspace: str, output_dir: Path, task_id: str,
        launch_id: str,
    ) -> None:
        """等待 Framework 子进程结束并收尾（§6B.22 canonical-aware）。

        顶层 try/except：任何异常都必须把 state 从 RUNNING 释放（置 FINISHED），
        否则并发保护会永久拒绝后续启动。

        分类规则（§6B.22 / TASK req 24/25）：
        - canonical terminal 存在 → last_run 跟随 canonical（CANCELLED/SUCCESS/WAITING/FAILED）；
          派生产物不完整 → 触发 Core reconciliation（不改变 canonical）
        - 无 canonical：
          * force 已请求（control.force_terminate_requested）→ 轮询 canonical
            （request_force_cancel 同步调 finalizer）；超时且 evidence 存在 → 调 finalizer；
            仍无 → 归类 abnormal（不推导 terminal；Launcher 永不写终态）
          * 非 force：exit 0 + REPORT → FINISHED；exit != 0 → FAILED（legacy 分类）
        - registry → EXITED（TASK req 26；幂等）
        """
        exit_code: int | None = None
        report_path: str | None = None
        result = RESULT_FAILED
        canonical: dict | None = None
        try:
            # 收集输出（run.py 会打印 REPORT 路径；失败时含 stderr）
            output = ""
            if proc.stdout:
                try:
                    output = proc.stdout.read()
                except Exception:
                    output = ""
            exit_code = proc.wait()

            report = self.report_path_for(output_dir)
            canonical = self._read_canonical_terminal(output_dir)

            if canonical is not None:
                status = canonical.get("status")
                # 派生产物不完整 → Core reconciliation（幂等；不改 canonical；§6B.6）
                if not self._derived_consistent(output_dir, canonical):
                    self._invoke_reconcile(task_id, workspace, output_dir)
                    canonical = self._read_canonical_terminal(output_dir) or canonical
                if status == "CANCELLED":
                    result = RESULT_CANCELLED
                elif status in ("SUCCESS", "WAITING"):
                    result = RESULT_FINISHED if report.exists() else RESULT_REPORT_NOT_FOUND
                elif status == "FAILED":
                    result = RESULT_FAILED
                else:  # 非终态（异常边界）：回退 legacy 分类
                    canonical = None
                if canonical is not None:
                    report_path = str(report) if report.exists() else None
            if canonical is None:
                # 无 canonical terminal：先看是否 force 已请求（§6B.17 恢复路径）
                force_requested = False
                control, cerr = control_mod.read_control(output_dir)
                if cerr:
                    control = None
                if control is not None and control.get("force_terminate_requested") is True:
                    force_requested = True
                if force_requested:
                    # 轮询等待 request_force_cancel 同步调用的 finalizer 提交 CANCELLED
                    canonical = self._poll_canonical(output_dir, FORCE_CANONICAL_POLL_WAIT)
                    if canonical is None:
                        # 兜底：evidence 已落盘 + 进程已死 → 自身调 finalizer（幂等）
                        ev_path = reg_mod.force_evidence_path_for(launch_id, self._registry_dir)
                        if ev_path.exists():
                            self._invoke_force_recovery(task_id, workspace, output_dir, ev_path)
                            canonical = self._poll_canonical(output_dir, FORCE_CANONICAL_POLL_WAIT)
                    if canonical is not None and canonical.get("status") == "CANCELLED":
                        result = RESULT_CANCELLED
                        report_path = str(report) if report.exists() else None
                    else:
                        # 恢复未得到合法 outcome → abnormal（不推导 terminal；req 25）
                        result = RESULT_FAILED
                        report_path = None
                elif exit_code != 0:
                    result = RESULT_FAILED
                    report_path = None
                elif report.exists():
                    result = RESULT_FINISHED
                    report_path = str(report)
                else:
                    result = RESULT_REPORT_NOT_FOUND
                    report_path = None

            # registry → EXITED（TASK req 26；幂等；force 路径可能已置 EXITED）
            try:
                reg_mod.mark_exited(launch_id, exit_result=result, root=self._registry_dir)
            except reg_mod.RegistryError:
                pass
        except Exception:
            # 等待/读取异常：释放 RUNNING，标记失败，保留 TASK.md
            exit_code = None
            report_path = None
            result = RESULT_FAILED
            try:
                reg_mod.mark_exited(launch_id, exit_result=result, note="wait thread exception", root=self._registry_dir)
            except reg_mod.RegistryError:
                pass

        self.last = RunInfo(
            task_id=task_id,
            task_path=str(task_path),
            report_path=report_path,
            exit_code=exit_code,
            result=result,
            output_dir=str(output_dir),
            launch_id=launch_id,
            terminal_generation=(
                canonical.get("terminal_generation") if canonical is not None else None
            ),
        )
        self.current = None  # 收尾完成：不再有“当前运行中”任务
        self._active_launch.pop(task_id, None)
        self._persist_last()
        self.state = FINISHED
        if self.on_finished is not None:
            try:
                self.on_finished(self.last, output)
            except Exception:
                pass

    @staticmethod
    def _poll_canonical(output_dir: Path, wait: float) -> dict | None:
        """轮询 canonical terminal（force 恢复后 finalizer 提交 CANCELLED 的时序窗口）。"""
        deadline = time.monotonic() + max(0.0, wait)
        while time.monotonic() < deadline:
            canonical = FrameworkLauncher._read_canonical_terminal(output_dir)
            if canonical is not None:
                return canonical
            time.sleep(FORCE_CANONICAL_POLL_INTERVAL)
        return None

    def _sync_registry_identity(self, launch_id: str, output_dir: Path) -> bool:
        """registry 采纳 runner 自报身份（handshake 回写后；§6A.6-4/§6B.12-G）。

        runner 的 ``os.getpid()`` 是真正执行任务的进程；启动时 Popen 直连子可能是
        重定向壳（uv venv python on Windows）——两 pid 可不同。registry 的
        ``runner_pid`` 以 runner 自报为准（ownership 三方校验基准），
        ``launch_root_pid`` 保留 Popen 直连子（进程树 kill 根）。

        - 在**验证路径**（request_force_cancel / recover_launches / ownership_status）
          内调用：control.runner_pid 已回写且与 registry 不同 → 采纳（原子；幂等）
        - control 未回写 / 已一致 → no-op，返回 False
        """
        ctrl, err = control_mod.read_control(output_dir)
        if err or ctrl is None or ctrl.get("runner_pid") is None:
            return False
        entry, reg_err = reg_mod.read_registry(launch_id, root=self._registry_dir)
        if reg_err or entry is None:
            return False
        if entry.get("runner_pid") == ctrl.get("runner_pid"):
            return False
        try:
            reg_mod.update_registry(
                launch_id,
                {
                    "runner_pid": int(ctrl["runner_pid"]),
                    "runner_creation_time": ctrl.get("runner_creation_time"),
                    "launch_root_pid": entry.get("runner_pid") or entry.get("launch_root_pid"),
                },
                root=self._registry_dir,
            )
            return True
        except reg_mod.RegistryError:
            return False

    # ---------- 状态保存（供 V03-000-C） ----------

    def _last_run_path(self) -> Path:
        return cfg_mod.CONFIG_DIR / "last_run.json"

    def _persist_last(self) -> None:
        if self.last is None:
            return
        try:
            self._last_run_path().parent.mkdir(parents=True, exist_ok=True)
            self._last_run_path().write_text(
                json.dumps(self.last.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def load_last(self) -> RunInfo | None:
        p = self._last_run_path()
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return RunInfo(**data)
        except (json.JSONDecodeError, TypeError, OSError):
            return None

    # ---------- Phase E / TASK-005-B：ownership + force cancel ----------

    def _resolve_launch_id(self, task_id: str, launch_id: str | None) -> str | None:
        if launch_id:
            return launch_id
        return self._active_launch.get(task_id)

    def ownership_status(self, task_id: str, launch_id: str | None = None) -> ownership_mod.OwnershipVerdict | None:
        """只读 ownership 判定（未来 UI 诊断；TASK req 31 最小兼容）。"""
        lid = self._resolve_launch_id(task_id, launch_id)
        if not lid:
            return None
        # 验证路径内先做 handshake 身份采纳（registry 跟随 runner 自报；uv venv 壳场景）
        registry, _ = reg_mod.read_registry(lid, root=self._registry_dir)
        if registry is not None and registry.get("output_dir"):
            self._sync_registry_identity(lid, Path(str(registry["output_dir"])))
        verdict = ownership_mod.verify_runner_ownership(
            task_id=task_id, launch_id=lid, registry_dir=self._registry_dir,
            mark_exited_on_terminal=True,
        )
        return verdict

    def force_eligible(self, task_id: str, launch_id: str | None = None, *,
                       soft_timeout: float | None = None) -> tuple[bool, str]:
        """soft cancel 超时 → 暴露 'force eligible' 状态（TASK req 15；**不自动 kill**）。

        - 必须已存在 soft cancel.request 且 elapsed >= 阈值（默认 30s，配置
          force_cancel_soft_timeout 可调）
        - 顺带把 cancel.request 镜像到 control.cancel_requested（§6A.15）
        - 达到 timeout ≠ 自动 force kill（req 17）；kill 仍需显式 request_force_cancel
        """
        lid = self._resolve_launch_id(task_id, launch_id)
        if not lid:
            return False, "NO_ACTIVE_LAUNCH"
        registry, err = reg_mod.read_registry(lid, root=self._registry_dir)
        if err or registry is None:
            return False, f"REGISTRY_UNAVAILABLE: {err or 'not found'}"
        output_dir = Path(str(registry.get("output_dir") or ""))
        req, warning = cancel_mod.inspect_cancel_request(output_dir)
        if warning:
            return False, f"CANCEL_REQUEST_INVALID: {warning}"
        if req is not None:
            try:
                control_mod.update_control(
                    output_dir,
                    {"cancel_requested": True, "cancel_requested_at": req.requested_at},
                    task_id=task_id,
                )
            except control_mod.ControlError:
                pass
        timeout = (
            soft_timeout if soft_timeout is not None
            else float(cfg_mod.load_config().get("force_cancel_soft_timeout", _DEFAULT_SOFT_TIMEOUT))
        )
        if req is None:
            return False, "NO_SOFT_CANCEL_REQUEST"
        # FIX-001（005-C-FIX-001）：elapsed 统一走 canonical UTC/aware contract——
        # 合法 offset-aware（+08:00 / +00:00 / Z）与 legacy naive 均正确换算，
        # malformed → None → fail closed（不产生 force eligibility）。
        elapsed = cancel_mod.requested_at_elapsed_seconds(req.requested_at)
        if elapsed is None:
            return False, "CANCEL_REQUEST_BAD_TIMESTAMP"
        if elapsed < timeout:
            return False, f"SOFT_CANCEL_TIMEOUT_NOT_REACHED: {elapsed:.1f}s < {timeout:.1f}s"
        return True, f"soft cancel timeout reached ({elapsed:.1f}s >= {timeout:.1f}s)"

    def request_force_cancel(self, task_id: str, launch_id: str | None = None, *,
                             soft_timeout: float | None = None,
                             require_eligibility: bool = True) -> ForceCancelResult:
        """Launcher-level force cancel API（TASK req 16/17/18/19）。

        流程（§6B.17 / TASK req 16-19）：
        1. resolve launch
        2. ownership verification（§6A.8 11 项 / §6B.13）→ 必须 VERIFIED（或 restart
           后 REAUTHENTICATED）→ 否则 REFUSE（不 kill；req 11/12/Z）
        3. force eligibility（soft cancel 超时；req 15/17；require_eligibility 可关）
        4. control.force_terminate_requested = true（原子；state.lock 内）
        5. 只对 verified PID 执行 taskkill /T /F（进程树；不误杀无关进程；req 18）
        6. 记录结构化 force evidence（registry + <launch_id>.force-evidence.json；req 19/21）
        7. registry force 字段 + EXITED（幂等）
        8. 调 Core recovery finalizer（CLI；Launcher 不写终态；req 20）
        9. 返回结构化结果（canonical_status 供调用方镜像 last_run——由 wait thread 完成）

        严禁：soft timeout → 自动 taskkill（本 API 是显式 force action；req 17）。
        """
        lid = self._resolve_launch_id(task_id, launch_id)
        if not lid:
            return ForceCancelResult(task_id=task_id, ok=False, refusal_reason="NO_ACTIVE_LAUNCH")

        # 验证路径内先做 handshake 身份采纳（registry 跟随 runner 自报身份；
        # uv venv 重定向壳场景下 Popen 直连子 ≠ 真实解释器；§6A.6-4/§6B.12-G）
        pre_reg, _ = reg_mod.read_registry(lid, root=self._registry_dir)
        if pre_reg is not None and pre_reg.get("output_dir"):
            self._sync_registry_identity(lid, Path(str(pre_reg["output_dir"])))

        # 2. ownership verification（核心安全门槛；§6A.8 任一失败 → REFUSE）
        verdict = ownership_mod.verify_runner_ownership(
            task_id=task_id, launch_id=lid, registry_dir=self._registry_dir
        )
        if not verdict.ok():
            return ForceCancelResult(
                task_id=task_id, launch_id=lid, ok=False,
                refusal_reason=f"OWNERSHIP_{verdict.result}: {'; '.join(verdict.failures)[:500]}",
                verdict=verdict,
            )
        output_dir = Path(str(verdict.registry.get("output_dir") or ""))
        runner_pid = int(verdict.registry.get("runner_pid"))
        launch_root_pid = verdict.registry.get("launch_root_pid")
        registry_path = reg_mod.registry_path(lid, self._registry_dir)
        control_path = control_mod.control_path(output_dir)

        # 3. eligibility（soft cancel 超时门槛；req 15）
        if require_eligibility:
            eligible, why = self.force_eligible(task_id, lid, soft_timeout=soft_timeout)
            if not eligible:
                return ForceCancelResult(
                    task_id=task_id, launch_id=lid, ok=False,
                    refusal_reason=f"NOT_ELIGIBLE: {why}", verdict=verdict,
                )

        # 4. control.force_terminate_requested（原子；state.lock 内）
        requested_at = datetime.now().isoformat(timespec="seconds")
        try:
            control_mod.update_control(
                output_dir,
                {"force_terminate_requested": True, "force_terminate_requested_at": requested_at},
                task_id=task_id,
            )
        except control_mod.ControlError as exc:
            return ForceCancelResult(
                task_id=task_id, launch_id=lid, ok=False,
                refusal_reason=f"CONTROL_UPDATE_FAILED: {exc}", verdict=verdict,
            )

        # 5. verified process tree termination（只使用 verified PID；req 18）
        #    runner_pid = 自报真实执行进程（ownership 校验基准）；launch_root_pid =
        #    Popen 直连子（uv venv 重定向壳场景的进程树 kill 根）——先杀 runner 树，
        #    再补杀壳（若不同；不 /T 只杀壳本身，避免扩大范围）
        kill_cmd = ["taskkill", "/T", "/F", "/PID", str(runner_pid)]
        term_status: int | None = None
        term_output = ""
        try:
            kill_proc = subprocess.run(
                kill_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30.0,
                **no_console_kwargs(),
            )
            term_status = kill_proc.returncode
            term_output = ((kill_proc.stdout or "") + (kill_proc.stderr or "")).strip()
            if launch_root_pid is not None and int(launch_root_pid) != runner_pid:
                root_proc = subprocess.run(
                    ["taskkill", "/F", "/PID", str(int(launch_root_pid))],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15.0,
                    **no_console_kwargs(),
                )
                # 壳通常随子进程退出已消失（128）；失败不改变主判定
                term_output = (term_output + " | root=" + (root_proc.stderr or "").strip()[:200]).strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            term_status = -1
            term_output = f"taskkill 调用失败: {exc}"

        observed_at = datetime.now().isoformat(timespec="seconds")
        termination_observed = term_status in _TASKKILL_OK_EXIT_CODES
        if not termination_observed:
            # 无法验证成功终止（exit != 0，含 128 进程已不存在 / 权限 / 超时 / 其他
            # 错误）→ 不调 finalizer（不得以未验证成功的终止授权 CANCELLED；FIX-001
            # req 5）；evidence 记录失败事实并保留（registry 同步 force_termination_failed）
            ev = force_evidence_mod.build_force_evidence(
                task_id=task_id, launch_id=lid,
                runner_pid=runner_pid,
                runner_creation_time=verdict.registry.get("runner_creation_time"),
                workspace=str(verdict.registry.get("workspace") or ""),
                output_dir=str(output_dir),
                expected_runner_entry=str(verdict.registry.get("expected_runner_entry") or ""),
                expected_command_line=list(verdict.registry.get("expected_command_line") or []),
                verification_result=verdict.result,
                verification_checks=verdict.checks,
                termination_requested_at=requested_at,
                termination_observed_at=observed_at,
                termination_exit_status=int(term_status),
                termination_command=kill_cmd,
                registry_path=str(registry_path),
                control_path=str(control_path),
                launch_root_pid=int(launch_root_pid) if launch_root_pid is not None else None,
            )
            try:
                ev_path = reg_mod.force_evidence_path_for(lid, self._registry_dir)
                force_evidence_mod.write_force_evidence(ev_path, ev)
            except force_evidence_mod.ForceEvidenceError:
                ev_path = None
            try:
                reg_mod.update_registry(
                    lid,
                    {
                        "force_terminate_requested_at": requested_at,
                        "force_termination_observed_at": observed_at,
                        "force_termination_exit_status": int(term_status),
                        "force_termination_output": term_output[:500],
                        "force_termination_failed": True,
                    },
                    root=self._registry_dir,
                )
            except reg_mod.RegistryError:
                pass
            return ForceCancelResult(
                task_id=task_id, launch_id=lid, ok=False,
                refusal_reason=f"TERMINATION_FAILED: taskkill exit={term_status} ({term_output[:300]})",
                verdict=verdict, evidence_path=str(ev_path) if ev_path else None,
                termination_exit_status=term_status, termination_output=term_output,
            )

        # 6. 结构化 force evidence（TASK req 19/21）
        ev = force_evidence_mod.build_force_evidence(
            task_id=task_id, launch_id=lid,
            runner_pid=runner_pid,
            runner_creation_time=verdict.registry.get("runner_creation_time"),
            workspace=str(verdict.registry.get("workspace") or ""),
            output_dir=str(output_dir),
            expected_runner_entry=str(verdict.registry.get("expected_runner_entry") or ""),
            expected_command_line=list(verdict.registry.get("expected_command_line") or []),
            verification_result=verdict.result,
            verification_checks=verdict.checks,
            termination_requested_at=requested_at,
            termination_observed_at=observed_at,
            termination_exit_status=int(term_status),
            termination_command=kill_cmd,
            registry_path=str(registry_path),
            control_path=str(control_path),
            launch_root_pid=int(launch_root_pid) if launch_root_pid is not None else None,
        )
        ev_path = reg_mod.force_evidence_path_for(lid, self._registry_dir)
        try:
            force_evidence_mod.write_force_evidence(ev_path, ev)
        except force_evidence_mod.ForceEvidenceError as exc:
            return ForceCancelResult(
                task_id=task_id, launch_id=lid, ok=False,
                refusal_reason=f"EVIDENCE_WRITE_FAILED: {exc}", verdict=verdict,
                termination_exit_status=term_status, termination_output=term_output,
            )

        # 7. registry 记录 termination evidence + EXITED（幂等；TASK req 19/26；
        #    FIX-001 req 6：durable bridge evidence——requested / observed /
        #    exit status / evidence path / verification result+checks 全部落盘，
        #    Core finalizer 锁内独立核对 registry ↔ evidence 一致）
        try:
            reg_mod.update_registry(
                lid,
                {
                    "force_terminate_requested_at": requested_at,
                    "force_termination_observed_at": observed_at,
                    "force_termination_exit_status": int(term_status),
                    "force_termination_output": term_output[:500],
                    "force_evidence_path": str(ev_path),
                    "force_termination_verification_result": verdict.result,
                    "force_termination_verification_checks": verdict.checks,
                    "state": reg_mod.REGISTRY_STATE_EXITED,
                    "exited_at": observed_at,
                    "exit_result": "FORCE_TERMINATED",
                },
                root=self._registry_dir,
            )
        except reg_mod.RegistryError:
            pass

        # 8. Core recovery finalizer（Launcher 不写终态；req 20；幂等）
        fc_exit, fc_output = self._invoke_force_recovery(task_id, str(verdict.registry.get("workspace") or ""), output_dir, ev_path)
        canonical = self._read_canonical_terminal(output_dir)
        canonical_status = canonical.get("status") if canonical else None

        return ForceCancelResult(
            task_id=task_id, launch_id=lid, ok=True, verdict=verdict,
            evidence_path=str(ev_path),
            termination_exit_status=term_status, termination_output=term_output,
            finalizer_exit_code=fc_exit, finalizer_output=fc_output[:1000],
            canonical_status=canonical_status,
        )

    def recover_launches(self, registry_dir: Path | None = None) -> dict:
        """Launcher / Tray restart 后重新认证（§6B.13 / TASK req 12/35）。

        - 扫描 registry 活跃条目（PREPARED / RUNNING）→ 三方验证
          （registry + control + live process；launcher_instance_id 不要求相同——§6B.16）
        - 全部一致 → REAUTHENTICATED（记入 self._active_launch → force capability 可用）
        - 任一失败 → UNCERTAIN（拒绝 force kill；只读记录，不自动改终态）
        - 特殊：registry 活跃 + 进程已消失 + 无终态 + **本 launch 自己的 force
          evidence 已存在**（Bridge 曾在 verified termination 后、finalizer 前崩溃）
          → 调 Core finalizer（幂等）收敛 CANCELLED——只针对本协议创建的 launch，
          **不扫描旧历史 task 自动改终态**（RW-020 保持 OPEN）
        """
        root = Path(registry_dir) if registry_dir else (self._registry_dir or reg_mod.registry_root())
        result: dict[str, ownership_mod.OwnershipVerdict] = {}
        for entry in reg_mod.list_launches(root=root):
            if entry.get("state") not in reg_mod.ACTIVE_STATES:
                continue
            lid = entry.get("launch_id")
            tid = entry.get("task_id")
            if not lid or not tid:
                continue
            # handshake 身份采纳（restart 前实例可能在采纳前崩溃；registry 跟随
            # runner 自报身份——§6A.6-4；uv venv 重定向壳场景必需）
            out_dir = Path(str(entry.get("output_dir") or ""))
            if str(out_dir):
                self._sync_registry_identity(lid, out_dir)
            verdict = ownership_mod.reauthenticate_launch(task_id=tid, launch_id=lid, registry_dir=root)
            result[lid] = verdict
            if verdict.ok():
                self._active_launch[tid] = lid
                continue
            # 本协议 launch 的 verified force termination 残留（Bridge 中途崩溃）：
            # evidence 存在 + 原进程已消失 + 任务尚无终态 → Core finalizer 幂等收敛。
            # FIX-001（req 6）：finalizer 要求 registry 也独立记录 force termination
            # 关键事实（durable bridge evidence）并逐项一致——若 Bridge 在 evidence
            # 写入后、registry 更新前崩溃，registry 缺 force 字段 → finalizer fail
            # closed（零 canonical 写，任务保持非终态，安全失败）
            if verdict.result == ownership_mod.STALE and verdict.checks.get("process_exists") is False \
                    and verdict.checks.get("task_not_terminal") is True:
                ev_path = reg_mod.force_evidence_path_for(lid, root)
                if ev_path.exists():
                    out_dir = Path(str(entry.get("output_dir") or ""))
                    ws = str(entry.get("workspace") or "")
                    if str(out_dir) and ws:
                        self._invoke_force_recovery(tid, ws, out_dir, ev_path)
                        try:
                            reg_mod.mark_exited(lid, exit_result="RECOVERED", note="force evidence recovery", root=root)
                        except reg_mod.RegistryError:
                            pass
        self.recovered_ownership = result
        return result
