"""AI Agent Framework — Core-owned per-task OS-level exclusive file lock（Phase E §6B.1–§6B.3）。

职责：
- 为 Task 提供跨进程互斥的 terminal commit 锁（state.lock）
- Windows 优先使用 msvcrt.locking（OS-level byte-range exclusive lock，设计 §6B.3 指定）；
  POSIX 使用 fcntl.flock
- 锁是 OS 级锁：进程崩溃后 OS 自动释放；``state.lock`` 文件残留 **不代表** 锁被占用
  （§6B.20）——锁状态只能通过实际 acquire 得知，绝不用 ``if file exists`` 判断
- acquire / release 语义明确；可配置 timeout；锁失败返回明确错误（§6B.19）
- 不提供任何绕过锁的写终态路径

边界：
- 本模块只提供互斥原语；“谁能写终态”由 §6A.1 Terminal Authority 决定（Runner / Core
  recovery finalizer），Launcher / Desktop UI 不取得该锁写 Task terminal state
- 不得把 ``tmp + os.replace`` 当作跨进程 mutex（§6B.2/§6B.23）；os.replace 只承担
  单文件完整替换，跨进程 read/check/write 串行化由本锁提供
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK_BYTES = 1


class LockError(RuntimeError):
    """state.lock 获取失败（OS 错误；非超时）。"""


class LockTimeout(LockError):
    """在 timeout 内未能取得 state.lock（已被其他进程持有）。"""


def state_lock_path(output_dir: Path | str) -> Path:
    """state.lock 位置：<output_dir>/state.lock（与 task.json 同目录，§6B.1）。"""
    return Path(output_dir) / "state.lock"


class TaskStateLock:
    """per-task OS-level exclusive lock（``.aaf/<Task-ID>/state.lock``）。

    用法（推荐）::

        with task_state_lock(output_dir, task_id, timeout=10.0):
            # 锁内：reload task.json → inspect → decide → commit → release

    或显式::

        lock = TaskStateLock(output_dir, task_id, timeout=10.0)
        lock.acquire()
        try:
            ...
        finally:
            lock.release()

    - 同一 task 一把锁（锁路径由 output_dir 唯一决定）
    - 进程崩溃 / 未 release：OS 自动释放底层锁（Windows byte-range lock 与
      POSIX flock 均随进程终止释放），残留文件不构成障碍（§6B.20）
    - 获取失败（超时）抛 LockTimeout；OS 错误抛 LockError——调用方不得绕过锁直接写
    """

    def __init__(
        self,
        output_dir: Path | str,
        task_id: str,
        *,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
    ):
        self.output_dir = Path(output_dir)
        self.task_id = task_id
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.path = state_lock_path(self.output_dir)
        self._fd: int | None = None
        self._acquired = False

    # ---------- 生命周期 ----------

    def acquire(self) -> "TaskStateLock":
        """阻塞式尝试（带 timeout）：成功 → 返回 self；超时 → LockTimeout；OS 错 → LockError。"""
        if self._acquired:
            return self
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            # 确保文件至少 1 字节（Windows byte-range lock 需要文件中有可锁定的范围）
            if os.fstat(fd).st_size < _LOCK_BYTES:
                os.write(fd, b"\x00")
            deadline = time.monotonic() + max(0.0, self.timeout)
            while True:
                try:
                    self._try_lock(fd)
                    self._fd = fd
                    self._acquired = True
                    return self
                except _WouldBlock:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"state.lock 获取超时（{self.timeout}s）: {self.path} "
                            f"(task_id={self.task_id!r}; 可能被其他 finalizer 持有)"
                        ) from None
                    time.sleep(self.poll_interval)
        except BaseException:
            # 超时 / OS 错误 / 其他异常：确保 fd 关闭（关闭即释放任何已取得的部分锁）
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    def release(self) -> None:
        """释放锁（显式）。未持有 / 已释放 → no-op；OS 错误记录并继续关闭 fd。"""
        if not self._acquired or self._fd is None:
            return
        fd = self._fd
        try:
            self._unlock(fd)
        except OSError:
            pass  # 锁随 fd 关闭自动释放；unlock 失败不阻塞关闭
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            self._fd = None
            self._acquired = False

    # ---------- OS 锁原语 ----------

    def _try_lock(self, fd: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, _LOCK_BYTES)
            except OSError as exc:
                if exc.errno in (13, 36):  # EACCES / EDEADLK：已被其他进程持有
                    raise _WouldBlock from exc
                raise LockError(f"state.lock OS 锁定失败: {self.path} ({exc})") from exc
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (11, 13):  # EAGAIN / EACCES：已被持有
                    raise _WouldBlock from exc
                raise LockError(f"state.lock OS 锁定失败: {self.path} ({exc})") from exc

    def _unlock(self, fd: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, _LOCK_BYTES)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)

    def __enter__(self) -> "TaskStateLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class _WouldBlock(Exception):
    """内部信号：锁已被其他进程持有，本次尝试失败（可重试）。"""


@contextmanager
def task_state_lock(
    output_dir: Path | str,
    task_id: str,
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.05,
):
    """contextmanager 版 per-task 锁（§6B.2 临界区）。"""
    lock = TaskStateLock(output_dir, task_id, timeout=timeout, poll_interval=poll_interval)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()
