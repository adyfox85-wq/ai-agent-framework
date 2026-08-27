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
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config as cfg_mod
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


class AlreadyRunningError(RuntimeError):
    """已有 Framework TASK 在执行，拒绝并发。"""


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

    def to_dict(self) -> dict:
        return asdict(self)


class FrameworkLauncher:
    def __init__(self, run_py: Path | None = None, on_finished=None):
        self.state = IDLE
        self.last: RunInfo | None = None
        self.current: RunInfo | None = None  # 正在执行的任务（内存只读事实；结束后清空）
        self.on_finished = on_finished  # 回调（主线程轮询时调用）
        self._run_py = run_py  # 测试注入；默认定位仓库 run.py
        self._lock = threading.Lock()

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

    # ---------- 启动 ----------

    def launch(self, task_path: Path, workspace: str, output_dir: Path, task_id: str) -> bool:
        """启动 Framework 执行链（后台）。返回 True=已启动；抛 AlreadyRunningError=并发。

        启动失败（run.py 缺失/OSError）→ state=FAILED_TO_START，返回 False；
        已落盘 TASK.md 保留不动。
        """
        with self._lock:
            if self.state == RUNNING:
                raise AlreadyRunningError("AAF_TASK_ALREADY_RUNNING")
            run_py = self._resolve_run_py()
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            try:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(run_py),
                        str(task_path),
                        "--workspace",
                        str(workspace),
                        "--output",
                        str(output_dir),
                    ],
                    cwd=str(run_py.parent),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **no_console_kwargs(),  # Windows: CREATE_NO_WINDOW，run.py 不新建 console 窗口
                )
            except OSError as e:
                self.state = FAILED_TO_START
                self.last = RunInfo(
                    task_id=task_id,
                    task_path=str(task_path),
                    report_path=None,
                    exit_code=None,
                    result=RESULT_FAILED_TO_START,
                    output_dir=str(output_dir),
                )
                self._persist_last()
                return False
            self.state = RUNNING
            # 内存只读事实：当前正在执行的任务（供状态窗口解析当前任务；不落盘）
            self.current = RunInfo(
                task_id=task_id,
                task_path=str(task_path),
                report_path=None,
                exit_code=None,
                result="RUNNING",
                output_dir=str(output_dir),
            )
        threading.Thread(
            target=self._wait_and_finish,
            args=(proc, task_path, workspace, output_dir, task_id),
            daemon=True,
            name="aaf-bridge-framework-wait",
        ).start()
        return True

    # ---------- 等待与收尾 ----------

    def _wait_and_finish(
        self, proc: subprocess.Popen, task_path: Path, workspace: str, output_dir: Path, task_id: str
    ) -> None:
        """等待 Framework 子进程结束并收尾。

        顶层 try/except：任何异常都必须把 state 从 RUNNING 释放（置 FINISHED），
        否则并发保护会永久拒绝后续启动。
        """
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
            if exit_code != 0:
                result = RESULT_FAILED
                report_path = None
            elif report.exists():
                result = RESULT_FINISHED
                report_path = str(report)
            else:
                result = RESULT_REPORT_NOT_FOUND
                report_path = None
        except Exception:
            # 等待/读取异常：释放 RUNNING，标记失败，保留 TASK.md
            exit_code = None
            report_path = None
            result = RESULT_FAILED

        self.last = RunInfo(
            task_id=task_id,
            task_path=str(task_path),
            report_path=report_path,
            exit_code=exit_code,
            result=result,
            output_dir=str(output_dir),
        )
        self.current = None  # 收尾完成：不再有“当前运行中”任务
        self._persist_last()
        self.state = FINISHED
        if self.on_finished is not None:
            try:
                self.on_finished(self.last, output)
            except Exception:
                pass

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
