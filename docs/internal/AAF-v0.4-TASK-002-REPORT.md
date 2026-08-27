# AAF-v0.4-TASK-002-REPORT

- Task: AAF-v0.4-TASK-002 (v0.4 Phase B — Bridge Background / Tray Skeleton)
- Date: 2026-08-27
- Type: v0.4 Phase B 实施（不实现 C-F；不启动 Desktop Shell 后续 Phase）
- Status: **IMPLEMENTATION COMPLETE（待 WorkBuddy 独立验收 + Codex review 后由 Planner 判定 COMPLETE）**
- Executor: Hermes

---

## Implementation Status ✅

1. **Background Bridge Host（Requirement 1 / Acceptance 1-2）**
   - 新增 `scripts/start_bridge.pyw`：pythonw 无控制台入口（双击或 `pythonw scripts\start_bridge.pyw`）
   - `bridge/main.py`：所有 print 改为 `_log()`（pythonw 下 sys.stdout=None 不崩溃）；入口保留 `python -m bridge.main` 调试模式
   - 启动失败兜底：写入 `~/.aaf-bridge/bridge_error.log` + 弹窗（不静默退出）
   - Bridge 核心执行流程零改动（Router / Runner / Lifecycle / launcher 未重写）

2. **Tray Skeleton（Requirement 2 / Acceptance 4-6）**
   - 新增 `bridge/tray.py`：ctypes Shell_NotifyIconW 零第三方依赖（消息专用窗口 + 独立 daemon 线程，复用 HotkeyListener 模式）
   - 菜单最小三项：**打开状态 / Bridge 信息**、**重启 Bridge**、**退出 AAF**（+ 灰显健康信息行）；双击图标 = 打开状态
   - 打开状态 = `bridge/ui.py` 新增 `show_bridge_status()` 最小信息窗口（Bridge 状态 / 热键 / 当前项目 / 当前 Workspace / 最近 Task），Phase C 预留接入点；实测关闭窗口不退出 Bridge
   - Tray 启动失败不致命：仅提示，热键继续可用

3. **Restart Bridge（Requirement 3 / Acceptance 7）**
   - Tray 菜单 → 注销热键 → 启动新实例（pythonw + start_bridge.pyw，env `AAF_BRIDGE_RESTART=1`）→ 旧实例立即退出
   - 单实例命名 mutex（`bridge/main.py` `SingleInstance`，CreateMutexW + WaitForSingleObject）：防双开；旧实例退出 → mutex abandoned → 新实例接管（WAIT_ABANDONED 路径，进程级实测通过）
   - 不修改正在执行 Task 的 canonical terminal state；不实现 Phase E（无 ownership verification / cancel / taskkill）

4. **Exit AAF（Requirement 4 / Acceptance 8）**
   - Tray 菜单 → 确认窗（明确提示"不取消正在执行的任务"）→ 只退出宿主
   - 不写 cancel.request / control.json / task.json / run.json；无 CANCELLED / FAILED 语义

5. **Hotkey Regression（Requirement 5）**
   - 热键 → 剪贴板 → 校验 → 确认 → 落盘 → launcher → Framework 执行链代码零改动（仅 `_poll_events` 增加 tray 事件分支，互不影响）
   - 注意：本机实测 **Ctrl+Alt+A 当前被外部程序占用**（详见 Unresolved Issues），冲突路径已验证：Bridge 保持运行、health 显示"异常"、Tray 正常

6. **Hotkey Health（Requirement 6，Phase B 最小范围）**
   - `classify_bridge_health()`：listener registered + loop alive → OK / DEGRADED（§8 模型，复用现有 wait_ready/error/is_alive）
   - 每 5s 轮询 → Tray 图标/Tooltip 反映健康（IDI_APPLICATION ↔ IDI_WARNING）
   - 未实现 heartbeat / self-healing / RW-020

7. **Core / UI Boundary（Requirement 7）**
   - Desktop Shell 只读产物（last_run.json 读取、config 读取）；无任何 Router/Runner/Lifecycle/Boundary/Agent adapter/TASK/REPORT 协议复制
   - 不写 task.json / run.json；Phase A runtime state 只读

8. **Documentation（Requirement 8）**
   - `docs/QUICKSTART.md`：Step 3 双模式启动（后台 pythonw 推荐 + 调试模式）；Step 10.5 Tray 管理说明
   - `docs/TROUBLESHOOTING.md`：A（热键占用 → 改 config）、H（Tray 重启）、I（单实例/交接窗口）、J（bridge_error.log）、K（Tray 不出现）
   - 未宣称完成 Desktop App packaging

## Test Status ✅ **233 passed**（216 baseline + 17 新增，零下降）

- 新增 `tests/test_bridge_tray.py`（17）：Tray 菜单规格（最小三项 + 健康行）/ 事件映射 / health 判定（4 场景）/ 重启 argv 构造（pythonw + fallback）/ 状态窗口内容行（3）/ 单实例真实进程级（防双开、释放后可获取、restart 交接 handoff）/ NOTIFYICONDATAW 结构 / TrayIcon 可构造不启动
- 全量：`233 passed in ~3s`（基线 216 无回归）

## Live Smoke（真实进程级，本机 Windows 10 实测）✅

| 检查项 | 结果 |
|---|---|
| pythonw 启动并持续存活 | ✅ |
| Tray Shell_NotifyIcon 真实创建/删除 | ✅ TRAY_PROBE_OK |
| 单实例：第二启动被拒 | ✅ BUSY |
| Restart 交接：kill 旧实例 → 新实例(restart 模式)接管，进程数=1 | ✅ |
| 清理：无残留 Bridge 进程 | ✅ |
| 状态窗口打开→关闭→root 存活 | ✅ |
| 热键归属验证 | ⏸ 环境被外部程序占用（SKIP，见 Unresolved） |

## Phase B 边界 ✅（Do Not Do 检查）

未新增：CANCELLED / cancel.request / control.json / state.lock / launch registry / force kill / terminal reconciliation / Safe Cancel / progress / stuck / 完整状态窗口 / Chinese-first UI / project switching / Duplicate UX（grep 全仓库仅出现于"不实现"注释）。
未修改：Router / Runner / Lifecycle / adapters / launcher.py / config.py / task_io.py / win32.py / handoff.py / Phase A schema。

## Core Files Changed

| 文件 | 变更 |
|---|---|
| `bridge/tray.py` | **新增**（ctypes Shell_NotifyIconW Tray + 菜单 + 健康显示） |
| `bridge/main.py` | EXTEND（单实例 mutex / health / Tray 集成 / restart / exit / pythonw 安全输出） |
| `bridge/ui.py` | EXTEND（show_bridge_status / ask_exit_aaf，纯新增函数） |
| `scripts/start_bridge.pyw` | **新增**（pythonw 无控制台入口） |
| `tests/test_bridge_tray.py` | **新增**（17 测试） |
| `docs/QUICKSTART.md` | 后台/调试双模式 + Tray 管理 |
| `docs/TROUBLESHOOTING.md` | A/H/I 更新 + J/K 新增 |

**零改动**：launcher.py / config.py / task_io.py / win32.py / handoff.py / ai_agent_framework/*。

## Unresolved Issues

1. **本机 Ctrl+Alt+A 被外部程序占用（环境条件，非 Phase B 缺陷）**：smoke 前探测 `RegisterHotKey` 即返回 1409（ERROR_HOTKEY_ALREADY_REGISTERED），其它组合（Ctrl+Alt+F9 / Ctrl+Alt+Z / Alt+A / Ctrl+Shift+X）均空闲；已排查非 Bridge / 非 Hermes / 无截图类进程。Bridge 冲突路径行为正确（提示 + DEGRADED 健康 + 继续运行）。WorkBuddy 验收热键功能时：需先释放该组合或临时改 config hotkey。建议后续如 Ady 想换默认热键，可另行决策（不属本 TASK）。
2. **Restart 后孤儿 runner 交接**（已知/设计内，RW-020 与 Phase E 覆盖）：Bridge 重启/退出时正在执行的 runner 子进程按 Windows 语义孤儿化继续运行，新实例 launcher 内存态重置（IDLE）。Phase B 明确不实现 orphaned RUNNING 检测（RW-020 / Do Not Do D），不重复登记。
3. **无 console 下热键冲突/启动错误的可见性**：pythonw 模式依赖弹窗 + bridge_error.log，日志已实现；后续如需文件级运行日志可入 backlog（未登记，非 Phase B 范围）。

## Git / Remote Sync

- 提交待执行（本报告同 commit）。Remote sync：如 push 受 RW-018 网络环境影响失败，将记录 REMOTE_SYNC_PENDING，由 WorkBuddy/Planner 独立验证时处理。
- Branch: main（当前 HEAD 以 `git rev-parse HEAD` 实时查询为准，不在此处硬编码）。

## Next Phase Candidate

Phase C — Status Window + Chinese-first UI（不得自动启动；由 Planner / User 显式决定）。
