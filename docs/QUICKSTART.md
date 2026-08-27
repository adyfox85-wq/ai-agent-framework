# AI Agent Framework — Quick Start

> 面向第一次使用的用户。完整概念见 [README](../README.md)。

## 你需要先有

- Windows + Python 3.11+
- Hermes CLI、WorkBuddy/CodeBuddy CLI（Codex 可选）
- 一个业务项目目录（比如 `D:\projects\my-app`）

## Step 1 — Clone Framework

```bash
git clone https://github.com/adyfox85-wq/ai-agent-framework.git
cd ai-agent-framework
```

## Step 2 — 确认 Agent CLI

```bash
python --version      # 3.11+
hermes --version
codebuddy --version
codex --version       # 可选；路由需要 Codex 时才用
```

## Step 3 — 启动 Bridge（必须先做）

有两种方式，**普通使用推荐后台方式**（不再需要持续打开 PowerShell / Terminal）：

### 方式 A：后台方式（推荐）

双击仓库下的 `scripts\start_bridge.pyw`（或命令行执行 `pythonw scripts\start_bridge.pyw`）。

- 无控制台窗口，Bridge 常驻系统托盘（任务栏右下角 AAF 图标）
- 图标 Tooltip 显示状态；右键菜单提供：**打开状态窗口**、**重启 Bridge**、**退出 AAF**
- 单实例保护：重复启动不会产生第二个 Bridge（提示后自动退出）

### 方式 B：调试方式

```bash
python -m bridge.main
```

看到下面输出即成功：

```
AAF Bridge 运行中 | 热键: Ctrl+Alt+A | 项目: '...'
```

需要查看日志 / 排查热键问题时使用；后台模式无控制台输出。

**Bridge 没启动时，Ctrl+Alt+A 不会有任何反应。**

## Step 4 — 配置目标 Project / Workspace

编辑 `%USERPROFILE%\.aaf-bridge\config.json`：

```json
{
  "hotkey": "ctrl+alt+a",
  "current_project": "My App",
  "current_workspace": "D:\\projects\\my-app"
}
```

保存后无需重启 Bridge（支持热加载）。

## Step 5 — 让 Planner 输出标准 AAF TASK

让 ChatGPT 或其他 Planner 在**纯文本代码块**中输出：

```
AAF_TASK_BEGIN
Task ID: MY-001
Task Name: My First Task
Workspace: D:\projects\my-app

Objective:
做一件明确的事，说明目标和边界。

Acceptance:
1. 完成标准
2. 可验证结果
AAF_TASK_END
```

关键：字段写单行（`Task ID: MY-001`），不要用 Markdown 转义。

## Step 6 — Copy TASK

复制上面的 TASK 全文（含 AAF_TASK_BEGIN / AAF_TASK_END）。

## Step 7 — 按 Ctrl+Alt+A

Bridge 会读取剪贴板并解析 TASK。

## Step 8 — 确认弹窗

检查弹窗显示的信息：
- Task ID（如 `MY-001`）
- Task Name
- 当前项目（应为 `My App`）
- Workspace（应为 `D:\projects\my-app`）

信息不对 → 检查第 4 步配置或 TASK 内容。

## Step 9 — 点击「执行」

Bridge 校验通过后点击「执行」，Framework 开始后台运行。

## Step 10 — Framework 后台运行

执行链按路由进行（通常是 Hermes → WorkBuddy → Codex）。期间你可以正常使用电脑（看视频、聊天等）。

**谨慎**：不要在同一个 workspace 上同时启动另一个写任务。

## Step 10.5 — 用 Tray 管理 Bridge（后台方式）

右键任务栏右下角的 AAF 图标：

| 菜单项 | 作用 |
|---|---|
| 打开状态窗口 | 打开正式状态窗口（见下）；再次点击会复用并聚焦已打开的窗口，不会重复创建 |
| 重启 Bridge | 退出当前实例并自动启动新实例（热键在新实例中重新注册；不会出现两个 Bridge 并存） |
| 退出 AAF | 退出 Bridge / Tray 宿主（不会取消正在执行的任务，Framework 继续在后台跑完） |

### 状态窗口显示什么（只读观察界面）

状态窗口每约 1 秒自动刷新，展示来自真实运行产物的状态：

- **Bridge / 项目区**：当前项目、Bridge 状态（正常运行/异常）、热键、Workspace
- **当前任务区**：Task ID、Task Name、当前阶段、当前 Agent（Hermes / WorkBuddy / Codex）、
  已运行时长、最近活动、整体结果（执行中 / 已完成 / 等待处理 / 执行失败 / 已取消）、
  整体进度（估算百分比 + 进度条）、当前阶段占比
- **六阶段条**：Validation / Boundary / Hermes / WorkBuddy / Codex / Report，
  每个阶段显示 ✓ 已完成 / ▶ 进行中 / ○ 未开始 / ⏸ 等待处理 / ✗ 失败；进行中阶段高亮
- **疑似停滞提示**：任务 RUNNING 且最近 10 分钟无活动时显示黄色提示
  「⚠ 任务可能已停滞（最近 N 分钟没有活动）」——这只是可观测提示，不会自动
  终止或修改任务状态
- **操作**：查看日志、查看任务目录（打开任务输出目录）、关闭、重启 Bridge、退出 AAF

要点：

- 状态窗口是**只读观察界面**，不会修改任何任务文件（task.json / run.json 由 Framework 自己写）。
- **关闭状态窗口不会退出 Bridge** —— 需要时随时从 Tray 再次打开。
- 没有任务时窗口显示"当前没有任务"，不会报错；Task ID / 状态等英文技术字段保留原值。
- **整体进度是估算值，不是精确剩余进度**：由固定阶段权重（Validation 5% / Boundary 5% /
  Hermes 45% / WorkBuddy 20% / Codex 20% / Report 5%）与阶段完成事实计算；
  进度条旁标注「估算」。**100% 只在任务 SUCCESS 时保证**；FAILED / WAITING / CANCELLED 时
  进度定格在已完成事实，不会显示 100%。
- **进度不是 canonical lifecycle**：任务的权威状态始终是 `task.json`（由 Framework 写入）；
  进度条只读展示、永不回写任何状态文件。

> 注意：重启 / 退出 Bridge 不会修改正在执行 Task 的状态文件（task.json / run.json 由 Framework 自己写）。

## 取消任务（Soft Cancel，Phase E Core）

v0.4 Phase E 已交付 **CANCELLED 终态 + cooperative soft cancel Core**（`AAF-v0.4-TASK-005-A`）：

- **CANCELLED 是合法终态**（`SUCCESS / WAITING / FAILED / CANCELLED`）；任务取消后
  `task.json / run.json / REPORT.md` 状态一致为 `CANCELLED`，已完成阶段的 Agent 结果全部保留。
- **取消请求文件**：`.aaf/<Task-ID>/cancel.request`（最小 JSON：`task_id / requested_at / request`）。
  它是**外部请求，不是 terminal truth**——最终状态永远由 Core 根据 `task.json` 裁决
  （`task.json` 是唯一 canonical terminal truth，经 `state.lock` 锁内提交）。
- **Runner 在安全检查点收敛**：收到有效 `cancel.request` 后不启动后续 Agent；
  已完成产物保留；Core 依次落盘 `task.json(CANCELLED)` → `run.json(CANCELLED)` → `REPORT.md(CANCELLED)`。
- **late cancel 不覆盖已提交终态**：任务已 SUCCESS / WAITING / FAILED 后到达的取消请求会被吸收 / 忽略。
- **幂等**：重复 cancel 不会重复收尾 / 重复 bump generation（`terminal_generation` 单调递增）。
- **恢复 finalizer（Core-owned）**：`python -m ai_agent_framework.finalize_cancelled
  --task-id <ID> --workspace <WS> --output <OUT>`（幂等；已有终态不改写，只做 reconciliation）。
  - **安全契约（FIX-001 + FIX-002）**：soft cancel 收敛**必须**先存在合法 matching `cancel.request`
    （`request=soft_cancel`、`task_id` 与 canonical `task.json.task_id` 一致、`requested_at`
    为合法 ISO 时间戳）且 canonical `task.json` 已存在；缺失 / 损坏 / 不匹配 →
    明确失败（exit code 6），**不得**修改 canonical、不得提交 CANCELLED。
  - **单一锁原子协议（FIX-002）**：canonical identity 验证、terminal arbitration、
    `cancel.request` evidence 验证与新 CANCELLED 提交发生在**同一个 `state.lock`
    临界区**内（验证与提交之间不释放锁）；CLI 与 library 使用完全相同的原子验证路径，
    无 bypass。已有终态（SUCCESS / WAITING / FAILED / CANCELLED）在锁内被保留，
    不要求 evidence，reconciliation 仍执行。
  - **Force recovery 未开放**：`--cancel-mode force` / `--reason FORCE_CANCELLED` 在
    TASK-005-B 交付前一律返回 `FORCE_RECOVERY_NOT_AVAILABLE`（不伪造 force evidence）。
  - `--evidence` 只是 **diagnostic note**，不是 authority evidence。
- **尚未交付**（属于后续 TASK-005-B / 005-C，Phase E 未 COMPLETE）：
  - 状态窗口「停止当前任务」按钮（005-C）
  - Force Cancel（进程树强终止 + ownership verification）（005-B）
  - 因此**不要**宣称"状态窗口已可停止任务"。

> 当前状态窗口只读展示 CANCELLED（「已取消」）+ 进度定格；写入 `cancel.request` 的
> 正式 UI 入口在 TASK-005-C 交付前，仅可通过 CLI / 测试 / 手动写文件使用。

## Step 11 — 完成后点击「复制报告」

Framework 完成后 Bridge 提供「复制报告」按钮（把 REPORT 转成 Planner Handoff 复制到剪贴板）。

## Step 12 — 回到 Planner 粘贴

把 REPORT 粘贴给 Planner。Planner 阅读：
- 是否 SUCCESS / WAITING / FAILED / CANCELLED
- Agent 结果
- Unresolved Issues
- 决定下一步（修复、收口或新任务）

---

## 第一个任务失败怎么办

1. 看 REPORT / Troubleshooting（`docs/TROUBLESHOOTING.md`）
2. 修复环境问题（如缺失 CLI）
3. 用 resume 只重跑**因环境/框架错误（FRAMEWORK_ERROR，如 MISSING_COMMAND）失败的阶段**：

```bash
python run.py <TASK.md> --workspace D:\projects\my-app \
  --output D:\projects\my-app\.aaf\MY-001 --resume-from D:\projects\my-app\.aaf\MY-001
```

已完成的 Agent 结果会被复用，不会从头执行。

> 注意：resume 只对 **非终态**任务生效（如 runner 中断后残留 `RUNNING` 的现场）。
> FIX-001 后 terminal precedence（§6A.2）：SUCCESS / WAITING / FAILED / CANCELLED 一旦
> committed，任何 late non-terminal update（含 resume 的 RUNNING 写入）都会被拒绝，
> 任务保持终态、不重跑，resume 返回已有 REPORT。
> 若某个 Agent 返回业务性失败（如 FAIL / REQUEST_CHANGE），该结果会被视为已完成并复用，
> 任务通常仍停在 WAITING —— 需要按 REPORT 的返工项处理后**重新规划 / 创建新 TASK**（或先移除旧结果文件后再考虑重跑）。
