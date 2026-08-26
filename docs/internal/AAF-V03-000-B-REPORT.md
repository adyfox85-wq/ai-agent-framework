# AAF-V03-000-B-REPORT

- Task: AAF-V03-000-B (AAF Bridge → Framework Auto Launch)
- Date: 2026-08-26
- Type: v0.3 开发任务（Bridge 接通 Framework 执行链）
- Status: **COMPLETE — WorkBuddy APPROVE**
- Executor: Hermes / Reviewer: WorkBuddy

---

## 1. Implementation Status

**新增 `bridge/launcher.py`（FrameworkLauncher）** —— Bridge = Transport + Launcher + Status Observer（不复制执行链）：

| 能力 | 实现 |
|---|---|
| Framework 调用 | ✅ `subprocess.Popen([python, run.py, task, --workspace, ws, --output, out])` 复用现有正式入口，零复制 |
| 后台执行 | ✅ 独立子进程 + daemon 等待线程；Bridge UI/热键不阻塞 |
| Bridge 状态机 | ✅ IDLE / RUNNING / FINISHED / FAILED_TO_START（自身状态，不替代 Framework 结论） |
| 单任务并发保护 | ✅ RUNNING 时 launch 抛 `AAF_TASK_ALREADY_RUNNING`（锁内原子检查） |
| 启动失败保护 | ✅ OSError → FAILED_TO_START，保留已落盘 TASK.md，Bridge 不崩溃 |
| REPORT 定位 | ✅ `output_dir/REPORT.md`（与 runner 输出一致）；缺失 → REPORT_NOT_FOUND |
| Last info 持久化 | ✅ `~/.aaf-bridge/last_run.json`（task_id/task_path/report_path/exit_code/result，供 V03-000-C） |
| 完成提示 | ✅ AAF TASK RUNNING / FINISHED / FAILED / REPORT_NOT_FOUND（主线程弹窗，线程安全） |
| Cancel | ✅ 确认窗口 Cancel 后不落盘不启动 |

**main.py 集成**：Execute → 落盘 TASK.md → 自动 launch → RUNNING 提示；launcher 完成回调经 queue → 主线程 FINISHED/FAILED 提示。

**v0.2 核心零改动**：router.py / runner.py / report.py / adapters.py / run.py 全部未修改（git diff 为空，WorkBuddy 隔离性 VERIFIED）。

## 2. Test Status

✅ **84 passed in 0.11s**（75 v0.2+前序 Bridge + 9 launcher 新增）：

- Framework launch（参数构造正确：run.py + task + --workspace + --output）
- 状态机序列（IDLE→RUNNING→FINISHED）
- 并发保护（RUNNING 拒绝第二次启动）
- 启动失败（OSError → FAILED_TO_START + TASK 保留）
- REPORT 发现 / 缺失（FINISHED / REPORT_NOT_FOUND）
- 失败 exit（RESULT_FAILED）
- Last info 持久化 / 缺失返回 None
- **wait 异常释放回归**（ISSUE-1：异常后 state 释放、可再次启动）

端到端冒烟（真实 run.py dry-run）：route `hermes -> workbuddy` + REPORT 生成 ✅（Bridge 将调用的命令链真实可用）。

## 3. Review Status

| 轮次 | 结论 | 内容 |
|---|---|---|
| 第一轮 | **REQUEST_CHANGE** | ISSUE-1（中）：`_wait_and_finish` 无顶层异常保护，wait 异常会卡死 RUNNING 导致后续启动永久被拒 |
| 修复后 | **APPROVE** ✅ | 顶层 try/except + 异常释放 FINISHED + 持久化失败 RunInfo + 回归测试 |

## 4. Git Commit Status

| 项 | 状态 |
|---|---|
| Commit | 待提交（本任务完成后 commit：`feat: AAF-V03-000-B bridge framework auto launch`） |
| 涉及文件 | `bridge/launcher.py`（新）、`bridge/main.py`（集成）、`tests/test_bridge_launcher.py`（新）、本报告 |
| v0.2 核心 | 零修改 |

## 5. Remote Sync Status

| 项 | 状态 |
|---|---|
| 本地 commit | 提交后确认 |
| 远程同步 | 提交后 push（如网络失败将重试；参考 AAF-V03-000-A push 经验） |
| 远程基线 | `adyfox85-wq/ai-agent-framework`（此前 18 commits 已同步） |

## 6. Unresolved Issues

无阻断问题。

非阻断备注：
1. `load_last()` 在 Bridge 启动时不加载到内存——V03-000-C 应直接读 `last_run.json` 文件（设计如此）
2. 真实 Framework 执行会消耗 Agent 额度（设计目标：自动执行链）；本任务测试全部 mock
3. 无第三方依赖新增（纯标准库 subprocess/threading/ctypes/tkinter）

---

## 附：Acceptance 对照（20 项）

✅ 全部满足：A 原有能力保持（75 基线不降）｜Execute 后落盘+自动启动｜无需手动开 Hermes/复制 TASK｜复用现有 Router/Agent 规则｜UI 不冻结（后台线程）｜并发保护｜启动失败不崩溃｜REPORT 定位｜REPORT_NOT_FOUND｜Last Report Path 保存｜不自动下一 TASK｜不无限执行｜新增测试覆盖（launch/background/concurrent/failure/report discovery/missing）｜完整回归通过｜WorkBuddy 复核｜REPORT 含 Git/Remote 状态。
