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

```bash
python -m bridge.main
```

看到下面输出即成功：

```
AAF Bridge 运行中 | 热键: Ctrl+Alt+A | 项目: '...'
```

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
- Project（应为 `My App`）
- Workspace（应为 `D:\projects\my-app`）

信息不对 → 检查第 4 步配置或 TASK 内容。

## Step 9 — 点击 Execute

Bridge 校验通过后点击 Execute，Framework 开始后台运行。

## Step 10 — Framework 后台运行

执行链按路由进行（通常是 Hermes → WorkBuddy → Codex）。期间你可以正常使用电脑（看视频、聊天等）。

**谨慎**：不要在同一个 workspace 上同时启动另一个写任务。

## Step 11 — 完成后点击 Copy Report

Framework 完成后 Bridge 提供 Copy Report。

## Step 12 — 回到 Planner 粘贴

把 REPORT 粘贴给 Planner。Planner 阅读：
- 是否 SUCCESS / WAITING / FAILED
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

> 注意：resume 只对 `FRAMEWORK_ERROR`（环境/框架错误）阶段重新执行。
> 若某个 Agent 返回业务性失败（如 FAIL / REQUEST_CHANGE），该结果会被视为已完成并复用，
> 任务通常仍停在 WAITING —— 需要按 REPORT 的返工项处理后**重新规划 / 创建新 TASK**（或先移除旧结果文件后再考虑重跑）。
