# AI Agent Framework v0.4 — Phase A Start Handoff

> Project: AI Agent Framework
> Date: 2026-08-27
> Purpose: Planner Conversation Rollover / v0.4 Phase A Start
> Repository: D:\AdyAI\ai-agent-framework
> GitHub: https://github.com/adyfox85-wq/ai-agent-framework

---

# 0. Handoff Purpose

本文件用于结束上一阶段 Planner conversation，
并在同一 ChatGPT Project 中启动新的 Planner conversation。

本次切换原因：

- 上一会话已经经历 v0.3 收官、Framework 实战维护、Master Backlog 建立、
  Desktop Shell 需求登记以及完整设计；
- 上下文长度已经较大；
- v0.4 即将进入正式实现阶段；
- 为降低 context compression、历史权重变化、scope drift 和遗忘风险，
  从 v0.4 Phase A 开始使用新的 Planner conversation。

本文件不是新的产品需求。

本文件的职责是：

1. 恢复当前真实项目状态；
2. 明确已经冻结的决定；
3. 明确当前阶段边界；
4. 防止新 Planner 重新设计已经完成的范围；
5. 明确下一步执行入口。

---

# 1. Source of Truth

后续任何 Planner conversation 不得只依赖 ChatGPT 历史聊天。

长期权威关系：

## Repository

AI Agent Framework repository 是 authoritative source。

正式目录：

D:\AdyAI\ai-agent-framework

## PROJECT_STATE

当前项目阶段与版本状态：

D:\AdyAI\ai-agent-framework\docs\internal\PROJECT_STATE.md

## Master Backlog

长期问题、真实使用缺口、观察项和恢复要求：

D:\AdyAI\ai-agent-framework\docs\internal\AAF_MASTER_BACKLOG.md

任何未来正式确认"稍后处理"的问题，
只有进入 AAF_MASTER_BACKLOG 才算完成长期登记。

## Design

Desktop Shell / Runtime Control 当前正式设计：

D:\AdyAI\ai-agent-framework\docs\design\AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md

## ChatGPT

ChatGPT Project / conversation 是：

Planner / reasoning / collaboration interface

不是唯一长期知识来源。

## Obsidian

Obsidian 是 human-readable mirror / recovery layer。

Mirror：

D:\AdyAI\Obsidian-Vault\AI Agent Framework\AAF_MASTER_BACKLOG.md

MIRROR ONLY。

Repository 版本始终优先。

---

# 2. Current Version State

## v0.2

CLOSED。

不得重新打开已完成范围。

## v0.3

CLOSED。

v0.3 已完成核心 Framework 能力，包括：

- Task Automation core
- Session Continuity core
- Project Boundary Control
- Router / Runner / REPORT chain
- Bridge
- Hermes / WorkBuddy / Codex execution chain

当前不得因为 v0.4 开发而重新定义 v0.3。

## v0.4

正式批准启动。

状态：

IN PROGRESS

正式方向：

Desktop Shell MVP / Runtime Observability & Control

当前 Phase：

Phase A — Runtime State Foundation

注意：

v0.4 的版本决定已经由 Planner/User 完成。

新会话不得再次询问：

"要不要启动 v0.4？"

也不得重新把 v0.4 改成别的主题。

---

# 3. v0.4 Frozen Direction

v0.4 当前主线：

A. Runtime State Foundation

B. Bridge Background / Tray Skeleton

C. Status Window + Chinese-first UI

D. Progress Visualization

E. Safe Cancel Lifecycle

F. Project Switching / Duplicate Task UX

当前只进入：

Phase A

后续 Phase 不得提前实现。

---

# 4. Desktop Shell Frozen Product Boundary

Desktop Shell 已完成正式设计。

定位：

Existing AAF Core
+
Lightweight Windows Desktop Shell / Tray

Desktop Shell 是操作与状态外壳。

它不替代：

- Router
- Runner
- Lifecycle
- Boundary
- Session
- Agent adapters
- TASK / REPORT protocol

Desktop Shell 不得自动扩展为：

- SaaS
- Web management platform
- multi-user backend
- account system
- cloud synchronization platform
- Agent marketplace
- plugin marketplace
- remote team management platform
- autonomous infinite Agent loop

除非未来有独立、明确的新版本决策。

AI suggestion 不自动成为 project requirement。

---

# 5. Desktop Shell Design Closure State

正式设计：

docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md

设计链：

AAF-DESIGN-001
→ AAF-DESIGN-001-FIX-001
→ AAF-DESIGN-001-FIX-002

最终：

Codex APPROVE

设计正式闭环。

不得在 Phase A 中重新设计整个 Desktop Shell。

---

# 6. Frozen Desktop UX Direction

未来用户体验目标：

看得到
→ 当前 Project / TASK / Agent / Stage / Progress

看得懂
→ Chinese-first 状态 / 最近活动 / Error / suspected stuck

控得住
→ Stop Task / Restart Bridge / Project Switch / Open Logs

未来状态窗口期望包含：

- 当前项目
- 当前 Task
- 当前阶段
- 当前 Agent
- elapsed
- last activity
- stage progress
- estimated progress bar
- errors
- suspected stuck
- Stop Current Task

注意：

estimated percentage 是 UX estimate。

它不是：

- 精确任务完成度
- 精确剩余时间
- Core authoritative state

真实 Stage State 与 Estimated Percentage 必须分离。

---

# 7. Safe Cancel Design — Already Closed

Safe Cancel 已经过两轮 Codex architecture fix。

不要在 Phase A 重新设计。

正式设计原则：

## Terminal Truth

task.json terminal record
是唯一 canonical terminal truth。

## Terminal Finalizer

Runner / Lifecycle Core
是唯一 authoritative terminal finalizer。

Launcher / Desktop Shell 不直接裁决 Task terminal state。

## Cross-process Arbitration

Future Phase E 使用：

Core-owned per-task OS-level exclusive state lock

设计路径：

.aaf/<Task-ID>/state.lock

normal completion 与 cancel 的 winner：

谁先在同一 Core lock 下完成合法 terminal commit，
谁胜出。

## Reconciliation

Core-owned：

reconcile_terminal_artifacts(...)

用于根据 canonical terminal state 幂等修复：

- run.json
- REPORT.md

## Force Cancel Ownership

未来使用三方验证：

Bridge persistent launch registry
+
Task control.json
+
Live Windows process identity

Bridge registry：

~/.aaf-bridge/launches/<launch_id>.json

ownership uncertain：

REFUSE FORCE TERMINATION

## Complexity

Cancel Lifecycle:
HIGH

Core Intrusion Risk:
MEDIUM

Desktop Shell overall：
仍保持轻量，不因为 Cancel 把整个产品评为 HIGH。

注意：

这些全部属于 Phase E。

Phase A 不实现：

- CANCELLED
- state.lock
- control.json
- launch registry
- force kill
- reconciliation

---

# 8. Current Master Backlog

正式长期登记：

docs/internal/AAF_MASTER_BACKLOG.md

当前已登记至少：

RW-001 ~ RW-019
BND-001
CTX-001
HIST-001

其中与 Desktop / Runtime 直接相关的 Cluster 包括：

RW-003
Bridge project switching

RW-004
Bridge background / Tray

RW-006
Runtime status visualization

RW-010
Desktop program packaging

RW-012
Hotkey listener reliability

RW-014
Task Stop / Cancel

RW-015
Chinese-first Desktop UI

RW-016
Duplicate Task Status UX

不要在新会话因为看到这些问题，
一次性全部实现。

它们属于不同 Phase。

---

# 9. Important Historical Incidents

以下历史不得遗忘，但不属于 Phase A 当前修复范围。

## RW-011

Router local constraint classification incident。

AAF-MAINT-001 因局部限制被误判为 review-only，
导致 Hermes 被跳过。

已解决：

commit 457df93

Status:
SOLVED

不得重新修。

## RW-013

Router self-triggering reference trap。

TASK Background 引用 Router 自身分类短语，
导致 Router 再次自触发。

Status:
OPEN

当前只登记。

Phase A 不处理 Router。

## RW-012

Bridge process alive
不等于 hotkey listener healthy。

至少发生两次：

进程存在
但 Ctrl+Alt+A 无响应
重启 Bridge 后恢复。

另：

电脑重启后 Bridge 未启动

属于 RW-004，
与 hotkey listener unhealthy 是不同场景。

Phase A 不修 Bridge health。

## RW-016

TASK_ALREADY_EXISTS 真实 UX 问题：

Task 已经运行/完成，
但 duplicate 提示只告诉"已存在"，
不告诉：

- RUNNING
- WAITING
- SUCCESS
- FAILED
- stage
- REPORT

Phase F 处理。

---

# 10. Current Environment Observations

以下均已进入 Backlog，不得因为看到它们而偏离 Phase A。

## RW-017

.aaf/ 当前长期显示 untracked。

.gitignore 的 .aaf-*/ 不匹配实际 .aaf/。

当前仅 Observation。

Phase A 不修改 .gitignore。

## RW-018

GitHub push 曾出现 TLS EOF。

执行环境曾通过本机 Clash proxy 成功 push。

属于 Environment observation。

不要把 proxy logic 放进 Framework Core。

## RW-019

Agent Review Execution Evidence Consistency。

"REPORT 中有 Codex 内容"

不一定等价于：

"本机 Codex CLI 已独立成功执行"。

未来需要更明确的 execution evidence。

Phase A 不开发 universal executable manager。

---

# 11. Historical Optimization Set

HIST-001

Status:
RECOVERY_PENDING

Known historical optimization set exists;
exact original list not yet recovered.

用户记得早期曾讨论约 10 个 Framework 优化项。

当前禁止：

根据今天的 Backlog
+
模型常识
+
猜测

重新凑十项。

只能在找到真实历史证据后恢复。

---

# 12. Planner Anti-Drift Rules

新会话必须遵守以下规则。

## Rule 1

FIRST READ：

AAF_MASTER_BACKLOG.md

然后再规划新的 AAF 工作。

## Rule 2

AI suggestion is possibility,
not automatically project requirement.

任何新 idea：

想到
→ 记录
→ 分类
→ 定优先级
→ 在合适阶段处理

不能：

想到
→ 马上实现
→ 打断当前 Phase

## Rule 3

当前 Phase 边界优先。

Phase A 不因为相关性而顺手实现：

- Tray
- Desktop window
- progress percentage
- Cancel
- autostart
- Project Switch
- Duplicate UX
- hotkey recovery

## Rule 4

不要重新设计已经 Codex APPROVE 的 Desktop architecture，
除非真实 implementation evidence 证明设计有问题。

## Rule 5

不要重新打开：

v0.2
v0.3
已 CLOSED TASK

## Rule 6

不要自动创建下一 TASK。

每个正式 Framework TASK 完成后：

REPORT
→ Planner review
→ 判断是否 SUCCESS / WAITING
→ 再规划下一 TASK

## Rule 7

如果发现新的实际问题：

先判断是否是当前 blocker。

不是 blocker：

进入 AAF_MASTER_BACKLOG。

不得因此扩大当前 Task。

---

# 13. New Conversation Current Mission

新 Planner conversation 的唯一当前主线：

v0.4
Phase A — Runtime State Foundation

目标：

让 AAF Core 自己可靠地回答：

- 当前 Task
- 当前 status
- 当前 stage
- 当前 agent
- started_at
- stage_started_at
- last_activity_at
- phases
- phase timestamps

为未来 Desktop Shell 提供可靠真实状态。

原则：

UI 以后读取 Core state。

UI 不自己靠文件存在性猜生命周期。

---

# 14. Phase A Must NOT Implement

明确禁止 Phase A 提前实现：

- Tray
- tkinter status window
- pystray
- pythonw background shell
- Windows Startup
- progress bar visual
- estimated percentage algorithm
- suspected stuck algorithm
- Safe Cancel lifecycle
- CANCELLED state
- control.json
- state.lock
- Bridge launch registry
- force process termination
- project switching UI
- Duplicate Task dialog
- full Desktop Shell packaging

Phase A 只建设 Runtime State Foundation。

---

# 15. Phase A Planned Task

Planner 已经生成：

Task ID:

AAF-v0.4-TASK-001

Task Name:

Runtime State Foundation

该 TASK 尚未执行。

新会话不得假设其已经完成。

正式执行前，
可以基于本 Handoff 与 Source of Truth
重新输出该 TASK 或直接使用上一会话保存的 TASK 文本。

核心目标：

扩展 task.json live runtime state，
建立统一 Runtime State reader，
保持 legacy compatibility，
补完整测试。

历史 test baseline：

206 passed

新增测试后允许测试总数增加，
要求全部 PASS。

---

# 16. Phase A Expected State Model

当前规划方向包括：

started_at
stage
stage_started_at
last_activity_at
agent
phases

Stage 至少支持：

VALIDATION
BOUNDARY
HERMES
WORKBUDDY
CODEX
REPORT
COMPLETED

Phase 状态应能表达：

PENDING
RUNNING
SUCCESS
WAITING
FAILED
SKIPPED

但最终字段设计应服从当前真实代码，
优先复用已有语义。

Safe Cancel 的 CANCELLED
不属于 Phase A。

---

# 17. Canonical Runtime Boundary

Phase A 目标：

task.json
=
live canonical runtime view

run.json
=
保留现有 completed run summary / existing role

不要让两个文件竞争同一个职责。

未来 Desktop Shell 应通过：

Core runtime state reader

获取状态。

不得复制 lifecycle logic 到 Bridge / UI。

---

# 18. New Conversation Required Reading

新会话开始后，优先提供以下文件。

## Required 1

D:\AdyAI\ai-agent-framework\docs\internal\PROJECT_STATE.md

作用：

确定版本、当前 Phase 与项目实时状态。

## Required 2

D:\AdyAI\ai-agent-framework\docs\internal\AAF_MASTER_BACKLOG.md

作用：

防止遗忘长期问题，
并防止 suggestion / observation 被错误升级。

## Required 3

D:\AdyAI\ai-agent-framework\docs\design\AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md

作用：

恢复 Desktop Shell 已完成的 architecture，
尤其 Phase A-F 边界和 Safe Cancel 已冻结设计。

## Required 4

D:\AdyAI\ai-agent-framework\docs\internal\handoffs\AI-Agent-Framework-v0.4-PHASE-A-START-HANDOFF-2026-08-27.md

即本文件。

作用：

连接两个 Planner conversation。

---

# 19. Files NOT Required at New Conversation Start

默认不要一次性上传全部历史 REPORT。

例如：

- AAF-MAINT-001*
- AAF-MAINT-002
- AAF-MAINT-003
- AAF-DESIGN-001
- FIX-001
- FIX-002

这些历史保留在 repo / git / .aaf 中。

只有发生：

- 状态争议
- 设计追溯
- incident 复盘
- Codex finding 核对

时再读取对应 REPORT。

减少新会话初始上下文负担。

---

# 20. Runtime Artifact Location

每个执行 Task 的 runtime artifacts：

<workspace>\.aaf\<Task-ID>\

例如：

D:\AdyAI\ai-agent-framework\.aaf\AAF-DESIGN-001-FIX-002\

可能包含：

task.json
route.json
boundary.json
run.json
hermes_prompt.md
hermes_result.md
workbuddy_prompt.md
workbuddy_result.md
codex_prompt.md
codex_result.md
REPORT.md

Canonical active TASK：

<workspace>\.aaf\tasks\active\<Task-ID>.md

注意：

.aaf
是 runtime state/history。

docs/internal
是 durable project knowledge。

不要混淆。

---

# 21. Previous Conversation Closing State

最后完成：

AAF-DESIGN-001-FIX-002

Result:

Codex APPROVE

Commit:

dbea5e26aa77a47de5c0f071afd6000670dd5cbe

Remote:

SYNCED

Test baseline:

206 passed

v0.3:

CLOSED

v0.4:

Approved to start

Current planned work:

AAF-v0.4-TASK-001
Runtime State Foundation

Execution status:

NOT YET EXECUTED

---

# 22. New Planner Start Rule

新会话建立后：

1. 读取本 Handoff；
2. 读取 PROJECT_STATE；
3. 读取 AAF_MASTER_BACKLOG；
4. 读取 Desktop Shell Design；
5. 不重新复盘整个 v0.3；
6. 不重新设计 Desktop Shell；
7. 不重新讨论是否启动 v0.4；
8. 直接恢复 Phase A；
9. 若 AAF-v0.4-TASK-001 尚未执行，则以该任务作为下一正式动作；
10. 常规项直接推进，只有真正重大决策才询问用户。

---

# 23. Do Not Forget

- 一个 Phase 一个 Planner conversation。
- 长对话接近下一阶段时主动准备 rollover。
- Repository 是 authoritative。
- ChatGPT 不是永久 memory。
- Master Backlog 是长期未完成问题登记。
- Handoff 是会话之间的桥。
- REPORT 是执行结果，不是长期状态文件的替代。
- suggestion 不自动变 requirement。
- 已 CLOSED 范围不要重新打开。
- 不自动扩大 Phase scope。
- 不为了 Desktop UI 重写 AAF Core。
- 当前唯一主线是 v0.4 Phase A Runtime State Foundation。

---

# 24. Recommended New Conversation First Message

请读取我提供的以下 4 份文件，恢复 AI Agent Framework 当前状态：

1. PROJECT_STATE.md
2. AAF_MASTER_BACKLOG.md
3. AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md
4. AI-Agent-Framework-v0.4-PHASE-A-START-HANDOFF-2026-08-27.md

这是同一个 AI Agent Framework 项目的新 Planner conversation。

请严格按照 Handoff 恢复，不重新设计已经完成并通过 Codex 的 Desktop Shell architecture，不重新打开 v0.3，不自动扩大 scope。

当前正式状态：

- v0.3 CLOSED
- v0.4 已正式批准启动
- 当前 Phase：Phase A — Runtime State Foundation
- AAF-v0.4-TASK-001 已规划，但尚未执行
- 当前 test baseline：206 passed

当前唯一主线是继续 v0.4 Phase A。

请先确认你已正确恢复：
1. Current Version
2. Current Phase
3. Frozen Scope
4. Current Next Task
5. Do-Not-Do Boundary

确认无误后直接继续推进，不需要重新询问是否启动 v0.4。
