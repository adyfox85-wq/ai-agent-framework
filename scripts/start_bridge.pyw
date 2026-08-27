"""AAF Bridge — 无控制台后台启动入口（pythonw / 双击 .pyw）。

- pythonw 运行本文件：无 Console / PowerShell / Terminal 窗口，Bridge 常驻 Tray
- 启动失败（如导入错误）写入 ~/.aaf-bridge/bridge_error.log，并弹窗提示
- 调试仍可用：python -m bridge.main（保留控制台输出）
"""
import sys
import traceback
from pathlib import Path


def _log_startup_error() -> None:
    """启动异常落盘（pythonw 无控制台，必须留痕）。"""
    try:
        from bridge.config import CONFIG_DIR

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG_DIR / "bridge_error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
    except Exception:
        pass


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from bridge.main import main as bridge_main

        return bridge_main()
    except Exception:  # noqa: BLE001 —— 入口兜底：记录 + 弹窗，不静默退出
        _log_startup_error()
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "AAF Bridge — 启动失败",
                "Bridge 启动失败，详情已写入:\n"
                f"{Path.home() / '.aaf-bridge' / 'bridge_error.log'}",
            )
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
