"""AI Agent Framework — Windows process identity utilities（Phase E §6A.8 / §6B.13）。

职责（**只读**；本模块不含任何进程控制能力——无进程启动 / 终止 / 信号发送）：
- 获取真实 Windows process creation time（psutil 优先；ctypes GetProcessTimes fallback）
- 获取 live process command line（psutil cmdline；/proc fallback）
- Windows 命令行 tokenize（CommandLineToArgvW 规则）与规范化比较
- PID 存活判断（防 PID recycle：创建时间才是稳定身份）

设计依据：
- §6A.8：force termination 前必须比较 live creation time（防 PID recycle）与
  normalized command line（不能只判断“包含 run.py”）
- §6B.13：三方验证（registry vs control vs live process identity）
- §6A.8 规范化规则实现时精确定义：大小写归一、路径归一（绝对路径 + 统一分隔符）、
  **位置化比较**（Launcher 记录的 expected_command_line 就是本次 launch 的真实 argv，
  实况命令行 tokenize 后必须逐位置规范化相等——不采用顺序无关比较，避免
  ``run.py A --workspace B`` 与 ``run.py B --workspace A`` 同 token 集合误判）

创建时间一致性：同一进程的 kernel creation time 是进程不变属性，多次读取（Launcher
写 registry、Runner 写 control、verification 实况查询）返回同一值；比较统一走
``creation_times_equal``（ISO 字符串，微小浮点容差）。
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

_IS_WINDOWS = os.name == "nt"

# creation time 比较容差（秒）：同一进程多次读取应完全一致，容差只吸收
# FILETIME→datetime 的浮点噪声；PID recycle 的创建时间差 ≥ 秒级，不可能误判为一致。
_CREATION_TIME_TOLERANCE_S = 0.05


def _iso_ms(dt: datetime.datetime) -> str:
    """datetime → ISO（毫秒）。所有创建时间记录统一此格式（确定性的）。"""
    return dt.isoformat(timespec="milliseconds")


def process_creation_time(pid: int) -> datetime.datetime | None:
    """真实进程创建时间（本地时间）。

    - Windows：psutil 优先（7.x 已安装）；psutil 缺失 → ctypes OpenProcess +
      GetProcessTimes（PROCESS_QUERY_LIMITED_INFORMATION，权限需求最小）
    - POSIX：psutil 优先；缺失 → /proc/<pid>/stat starttime（不稳定内核时钟，仅尽力）
    - 失败 / 平台无支持 → None（调用方按“无法验证”处理，fail closed）
    """
    try:
        import psutil  # noqa: PLC0415

        return datetime.datetime.fromtimestamp(psutil.Process(pid).create_time())
    except Exception:
        pass
    if _IS_WINDOWS:
        return _ctypes_creation_time(pid)
    return _procfs_creation_time(pid)


def _ctypes_creation_time(pid: int) -> datetime.datetime | None:
    """ctypes GetProcessTimes fallback（psutil 缺失时）。"""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        ctime = wintypes.FILETIME()
        etime = wintypes.FILETIME()
        ktime = wintypes.FILETIME()
        utime = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(h, ctypes.byref(ctime), ctypes.byref(etime),
                                        ctypes.byref(ktime), ctypes.byref(utime)):
            return None
        ft = ctime.dwHighDateTime << 32 | ctime.dwLowDateTime
        if ft == 0:
            return None
        # FILETIME: 100ns ticks since 1601-01-01 UTC
        epoch = datetime.datetime(1601, 1, 1)
        return (epoch + datetime.timedelta(microseconds=ft / 10)).replace(tzinfo=None).astimezone()
    finally:
        kernel32.CloseHandle(h)


def _procfs_creation_time(pid: int) -> datetime.datetime | None:
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8", errors="replace") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        # starttime 是自 boot 起的 jiffies；无 boot 时间精确换算 → 尽力而为
        boot = datetime.datetime.fromtimestamp(_boot_time())
        start_ticks = float(fields[19])
        return boot + datetime.timedelta(seconds=start_ticks / os.sysconf("SC_CLK_TCK"))
    except Exception:
        return None


def _boot_time() -> float:
    try:
        import psutil  # noqa: PLC0415

        return psutil.boot_time()
    except Exception:
        return 0.0


def process_exists(pid: int) -> bool:
    """PID 是否存活（尽力而为；仅诊断，不是强保证——创建时间才是身份）。"""
    try:
        import psutil  # noqa: PLC0415

        return psutil.pid_exists(int(pid))
    except Exception:
        pass
    if _IS_WINDOWS:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return Path(f"/proc/{int(pid)}").exists()


def live_command_line(pid: int) -> list[str] | None:
    """live 进程的 argv 列表（Windows psutil 精确；POSIX /proc fallback；失败 → None）。"""
    try:
        import psutil  # noqa: PLC0415

        argv = psutil.Process(int(pid)).cmdline()
        return list(argv) if argv else None
    except Exception:
        pass
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\x00", b"\n")
        parts = [p for p in raw.decode("utf-8", errors="replace").split("\n") if p]
        return parts or None
    except Exception:
        return None


def live_process_identity(pid: int) -> dict | None:
    """live 进程身份快照（供 ownership verification 使用）。

    ``{"pid", "exists", "creation_time", "command_line"}``；查询失败 → None
    （调用方按“无法验证 live 身份”处理，fail closed）。
    """
    if not process_exists(pid):
        return {"pid": int(pid), "exists": False, "creation_time": None, "command_line": None}
    ct = process_creation_time(pid)
    return {
        "pid": int(pid),
        "exists": True,
        "creation_time": _iso_ms(ct) if ct is not None else None,
        "command_line": live_command_line(pid),
    }


def creation_times_equal(a: str | None, b: str | None) -> bool:
    """两条 ISO 创建时间记录是否一致（同一进程 → 相等；None 任一侧 → False）。

    - 防 PID recycle：真实 recycle 的两进程创建时间差 ≥ 秒级，远大于容差
    - 记录缺失 / 不可解析 → False（fail closed：无法证明一致 = 不一致）
    """
    if not a or not b:
        return False
    try:
        da = datetime.datetime.fromisoformat(a)
        db = datetime.datetime.fromisoformat(b)
    except (TypeError, ValueError):
        return False
    return abs((da - db).total_seconds()) <= _CREATION_TIME_TOLERANCE_S


# ---------------------------------------------------------------------------
# 命令行 tokenize / 规范化（§6A.8 精确实现）
# ---------------------------------------------------------------------------


def tokenize_windows_cmdline(cmdline: str) -> list[str]:
    """按 CommandLineToArgvW 规则 tokenize Windows 命令行字符串。

    - 空白分隔；双引号分组；``\\`` 转义规则与 CRT 一致（实现见下）
    - 非字符串 / 空 → []
    """
    if not isinstance(cmdline, str) or not cmdline:
        return []
    args: list[str] = []
    cur: list[str] = []
    in_quotes = False
    i = 0
    n = len(cmdline)
    while i < n:
        ch = cmdline[i]
        if ch == "\\":
            backslashes = 0
            while i < n and cmdline[i] == "\\":
                backslashes += 1
                i += 1
            if i < n and cmdline[i] == '"':
                # 偶数个 \ → 输出一半 \，引号是分组符；奇数个 → 输出 (n-1)/2 个 \ + 字面 "
                cur.append("\\" * (backslashes // 2))
                if backslashes % 2 == 1:
                    cur.append('"')
                i += 1
            else:
                cur.append("\\" * backslashes)
        elif ch == '"':
            in_quotes = not in_quotes
            i += 1
        elif ch in " \t" and not in_quotes:
            if cur:
                args.append("".join(cur))
                cur = []
            i += 1
        else:
            cur.append(ch)
            i += 1
    if cur:
        args.append("".join(cur))
    return args


def _path_like(token: str) -> bool:
    """判断 token 是否应按路径规范化（绝对/相对路径特征或常见可执行/脚本后缀）。"""
    if not token:
        return False
    if token.startswith(("\\\\", "//")):  # UNC
        return True
    if len(token) >= 2 and token[1] == ":" and token[0].isalpha():  # 盘符
        return True
    if "/" in token or "\\" in token or token.startswith("."):
        return True
    low = token.lower()
    return low.endswith((".py", ".pyw", ".exe", ".cmd", ".bat", ".ps1"))


def canonicalize_command_line(argv: list[str]) -> list[str]:
    """命令行规范化（§6A.8：大小写归一、路径归一（绝对路径 + 统一分隔符）、确定性）。

    - 路径 token（盘符 / 分隔符 / 脚本后缀 / UNC）→ ``os.path.normcase(os.path.abspath(...))``
    - 非路径 token → casefold（Windows 大小写不敏感比较；选项参数等不区分大小写）
    - 返回规范化后的 token 列表；比较必须逐位置相等（Launcher 记录的
      expected_command_line 是本次 launch 的真实 argv，实况必须完全一致）
    """
    out: list[str] = []
    for token in argv or []:
        if _path_like(token):
            try:
                out.append(os.path.normcase(os.path.abspath(token)))
            except Exception:
                out.append(str(token).casefold())
        else:
            out.append(str(token).casefold())
    return out


def command_line_matches(live_cmdline: str | list[str] | None, expected_argv: list[str] | None) -> bool:
    """实况命令行与 expected argv 是否匹配（规范化后逐位置相等）。

    - live 为 str（Win32_Process.CommandLine）→ 先 tokenize
    - expected 缺失 / live 缺失 / token 数不同 → False（fail closed）
    - **argv[0]（python 解释器）不参与比较**：uv venv 的 python.exe 是重定向壳，
      真实解释器（子进程）的 argv[0] 与启动时传入的壳路径不同——解释器身份由
      PID + creation time + launch_root_pid 绑定；命令行身份绑定 runner entry
      （argv[1] 起：run.py / dummy_runner.py + task/workspace/output/launch-id 参数）
    - 绝不退化为“包含 run.py”子串判断（TASK req 10）
    """
    if not expected_argv:
        return False
    if isinstance(live_cmdline, str):
        live_tokens = tokenize_windows_cmdline(live_cmdline)
    elif isinstance(live_cmdline, list):
        live_tokens = live_cmdline
    else:
        return False
    if not live_tokens:
        return False
    if len(live_tokens) != len(expected_argv):
        return False
    return canonicalize_command_line(live_tokens[1:]) == canonicalize_command_line(expected_argv[1:])


def canonicalize_path(p: str) -> str:
    """路径规范化（registry/control 的 workspace/output_dir 比较用）。"""
    try:
        return os.path.normcase(os.path.abspath(str(p)))
    except Exception:
        return str(p).casefold()
