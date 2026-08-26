# AI Agent Framework — v0.3 CLOSING HANDOFF

- Date: 2026-08-26
- Type: Stage Closing Handoff（里程碑收官交接，原则上冻结，不持续覆盖）
- Predecessor: docs/handoffs/AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md

---

## 1. v0.3 Core Goal

> 减少用户作为多个 AI Agent 之间人工搬运者的工作，同时：
> - 保留多模型复核结构（Hermes 执行 / WorkBuddy 复核 / Codex milestone audit）
> - 保留 Human / Planner 最终决策权
> - 防止项目范围持续漂移
> - 支持同项目长会话之间安全承接

## 2. Completed Scope

| 任务 | 交付 | 状态 |
|---|---|---|
| AAF-V03-000-A | Bridge Intake（剪贴板 → TASK.md，UX Guard） | CLOSED |
| AAF-V03-000-B | Bridge → Framework Auto Launch（subprocess run.py） | CLOSED |
| AAF-V03-000-C | Copy Last Report + Planner Handoff（剪贴板回传） | CLOSED |
| AAF-V03-001 | Formal Task Validation（权威校验层，CLI 不可绕过） | CLOSED |
| AAF-V03-002 | Formal Task Lifecycle（CREATED/RUNNING/WAITING/SUCCESS/FAILED） | CLOSED |
| AAF-V03-003 | Formal Task Artifact Archive（Task Package 显式归档） | CLOSED |
| AAF-V03-004 | Formal Session Continuity（SESSION_SUMMARY + NEXT_SESSION_START） | CLOSED |
| AAF-V03-005 | Formal Project Boundary Control（PROJECT_SCOPE + warning-first） | CLOSED |
| **AAF-V03-006** | **v0.3 Core Acceptance & Closure** | **COMPLETE — PASS** |

## 3. Final Architecture

```
Planner (ChatGPT)
→ 粘贴 TASK 文本
→ Bridge（Ctrl+Alt+A 热键 / 手动）→ TASK.md（<ws>/.aaf/tasks/active/<ID>.md）
→ Framework runner（subprocess 自动启动）
    → Validation（task_validation.py，权威，CLI 同路径）
    → Boundary Check（project_boundary.py，warning-first → boundary.json）
    → Lifecycle（task_lifecycle.py → task.json：CREATED → RUNNING → 终态）
    → Router（router.py，v0.2 未重写）→ Adapters（Hermes/WorkBuddy/Codex 按 route）
    → REPORT.md（report.py，v0.2 未重写）
→ [Copy Report] → Planner Handoff（REPORT 原文 + Git Closure Snapshot）
→ 显式 Archive（task_archive.py → .aaf/archive/<ID>/，status 不变）
→ 显式 Session Rollover（session_continuity.py → SESSION_SUMMARY + NEXT_SESSION_START）
→ 新 Session 从 PROJECT_SCOPE（project_boundary.py）+ NEXT_SESSION_START 继续

职责分离：
- TASK.md = formal input
- task.json = execution lifecycle（machine state）
- boundary.json = scope risk（machine state）
- REPORT.md = execution result（human/Planner readable）
- archive location = storage lifecycle（ARCHIVED 从不进 Task Status）
- sessions/ = 会话承接 artifact（与 Task archive 分离）
```

## 4. Latest Test Baseline

``` text
191 passed（零回归，从 v0.2 52 passed 起全程递增）
新增测试：task_io(14) → handoff(14) → validation(26) → lifecycle(19) → archive(16) → session(14) → boundary(18) + runner 修正
```

## 5. Git Baseline

``` text
Latest Commit: d1919b6（feat: AAF-V03-005 formal project boundary control）
Commits: 26（main）
Remote: origin/main = d1919b6（本地 tracking 0/0 同步确认）
Repository: https://github.com/adyfox85-wq/ai-agent-framework（Public）
Remote Sync: SUCCESS（验收时网络 ls-remote 失败为 VPN 未开，本地 tracking 已确认同步）
```

## 6. Known Non-blocking Issues

1. Boundary warning（boundary.json severity/warnings）暂未注入 REPORT/Handoff 展示层——机器态正确，Planner 决策点暂不可见（WorkBuddy 建议 close 后跟踪）。
2. Codex milestone audit 本机不可用（在公司电脑），v0.3 closure 建议在公司电脑补一次只读 audit（见第 9 节）。
3. 同秒连续 3 次 Session rollover 会触发覆盖保护拒绝（显式低频操作，可接受）。
4. HIGH 路径命中时短语循环可能多发一条冗余 MEDIUM warning（severity 仍 HIGH，无害）。
5. 远程实时确认依赖 VPN（无 VPN 时 ls-remote 超时，本地 tracking 仍准确）。

## 7. Explicit Future Ideas（NOT CURRENT SCOPE）

- Task Registry（全局任务索引，基于 task.json）
- DECISION_LOG（决策记录，独立处理）
- Bridge UX 增强：Copy Next Session Start、Archive 按钮、Boundary warning 展示
- retention policy / ZIP 压缩（Archive 增强）
- 自动上下文长度检测提示
- 跨 Agent 交接包模板增强
- MCP / Browser Extension / Dashboard（明确 Non-goal）

## 8. What NOT to Reopen

v0.3 已验收冻结，不得无新证据重开：

- 重写已验证 Router / report.py / adapters.py（v0.2 核心，v0.3 全程未触碰）
- 重做 Validation / Lifecycle / Archive / Session / Boundary 已验证语义
- 让 ARCHIVED 进入 Task Status
- 为"更漂亮"进行无目标架构重构
- 引入数据库 / SQLite / 向量库 / 无限记忆 / 自动下一 TASK / 自动 ChatGPT 会话
- 自动修改 PROJECT_SCOPE（唯一显式入口：project_boundary_cli add-backlog）
- 删除 docs/internal 历史材料 / .aaf-backup 备份
- force push / reset / rebase / amend / clean / 改写历史

## 9. Conditions for Starting v0.4

v0.4 必须由 Planner / User 显式启动（本文件不宣布 v0.4）。启动条件建议：

1. 用户显式决定进入 v0.4（新 TASK 文本）。
2. 建议先在公司电脑补一次 Codex 只读 milestone audit（本机不可用项）。
3. 无 unresolved BLOCKING（当前：无）。
4. v0.4 候选方向（仅 Future Idea，未批准）：Task Registry / DECISION_LOG / Bridge UX / retention / 其他用户指定方向。
5. 不得从本 handoff 自动推导 v0.4 范围。
