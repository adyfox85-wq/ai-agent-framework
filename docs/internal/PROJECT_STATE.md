# PROJECT_STATE.md

> Project: AI Agent Framework\
> Current Version: **v0.3**\
> Last Updated: 2026-08-26\
> Document Type: **Living Project State / 持续更新的当前状态入口**
>
> 本文件不是历史快照。后续每完成一个重要阶段、发生 Framework
> 级变更、版本状态变化或关键风险变化，都应更新本文件。
>
> 下方 v0.2 及更早内容属于历史状态，保留不删除；当前状态以顶部 v0.3 块为准。

------------------------------------------------------------------------

## 0. v0.3 Current Status（当前状态）

``` text
Version: v0.3
Core Implementation: COMPLETE
Core Acceptance: PASS
Lifecycle: READY_FOR_CLOSURE

v0.3 三大核心方向：
1. Task Automation     ✅ COMPLETE（000-A/B/C + 001 Validation + 002 Lifecycle + 003 Archive）
2. Session Continuity  ✅ COMPLETE（004）
3. Project Boundary    ✅ COMPLETE（005）

Regression Baseline: 191 passed（commit d1919b6 起，零回归）
E2E 主链验收: PASS（Bridge 校验 → Validation → Boundary → Lifecycle → Router → REPORT → Handoff）
Review: WorkBuddy APPROVE（v0.3 READY_TO_CLOSE）
Milestone Audit: Codex 本机不可用（公司电脑待执行，NON_BLOCKING）
Remote Sync: SUCCESS（d1919b6 已同步；如后续 push 失败会标记 REMOTE_SYNC_PENDING）

当前阶段：
v0.3 收官
→ 三大方向实现 ✅
→ Core Acceptance PASS ✅（AAF-V03-006）
→ READY_FOR_CLOSURE（当前）
→ v0.4 未启动（必须由 Planner / User 显式决定）
```

------------------------------------------------------------------------

## 1. Historical Status（v0.2 及更早，保留不删除）

## 1. Current Status

``` text
Version: v0.2
Lifecycle: v0.2 CLOSED

MVP Core Loop Validation: PASSED
Regression Baseline: 52 passed

Public Release: COMPLETED
Repository: Public — https://github.com/adyfox85-wq/ai-agent-framework
Release: v0.2.0-rc1 (2026-08-25, prerelease)

v0.2 Final Status:
- Migration Completed
- Validation Completed
- GitHub Repository Completed
- Open Source Sanitization Completed
- Public Release Completed

Latest Production Validation:
TASK-010
Current Status: SUCCESS
WorkBuddy: PASS_WITH_WARNING
Codex: APPROVE
Unresolved Issues: None identified.
```

当前结论：

> AI Agent Framework v0.2 自动化 MVP
> 核心闭环已经通过真实项目连续试跑验证，
> 并已完成正式化迁移、GitHub 公开仓库上线与 v0.2.0-rc1 Release。

当前阶段：

``` text
v0.2 收官
→ Freeze Preparation ✅
→ 正式化整理 ✅
→ GitHub Repositoryization ✅
→ Open Source Sanitization ✅
→ Public Release ✅
→ v0.2 CLOSED（当前）
```

------------------------------------------------------------------------

## 2. Current Architecture

固定角色：

``` text
Planner: ChatGPT
Router: AI Agent Framework
Executor: Hermes
Reviewer / Validator: WorkBuddy (CodeBuddy)
Milestone / Code Reviewer: Codex
Result Carrier: REPORT.md
```

正式执行链：

``` text
需求 / 产品规划
→ Planner
→ TASK.md
→ Framework Router
→ Hermes（需要执行时）
→ WorkBuddy
→ Codex（按任务需要）
→ REPORT.md
→ Planner
```

TASK.md 是 Framework 的唯一正式执行入口。

------------------------------------------------------------------------

## 3. Current Working Locations

### Verified prototype（冻结参考）

``` text
<PROJECT_ROOT>-prototype
```

这是 v0.2 真实试跑、修复和 52 项测试验证的原始工作源。
已完成正式迁移（AAF-TASK-004）后保持完整冻结，不再作为正式入口更新。

### Formal Framework directory（唯一正式入口）

``` text
<PROJECT_ROOT>
```

状态：v0.2 已完成正式迁移与正式验证（AAF-TASK-004 / AAF-TASK-005）。

- 核心代码、测试、模板、文档已迁移；
- 52 passed 已在正式目录验证通过；
- TASK → Router → Agent → REPORT 真实闭环已验证；
- WorkBuddy 独立 review：FORMAL_REPOSITORY_OK；
- **本目录是 v0.2 唯一正式入口。**

### Current production-use project

``` text
<BUSINESS_PROJECT>
```

该项目已经完成 TASK-001 ～ TASK-010 及多个 FIX TASK 的真实 Framework
试跑。

Framework 收官不得随意修改业务项目代码。

禁止修改：

``` text
<BUSINESS_PROJECT>\workbuddy_skills\skills\
```

------------------------------------------------------------------------

## 4. Validation Baseline

当前已知回归基线：

``` text
52 passed
```

已经真实验证：

-   TASK → Router → Agent chain → REPORT；
-   Hermes execution；
-   WorkBuddy 独立复核；
-   Codex APPROVE / REQUEST_CHANGE；
-   SUCCESS / WAITING 状态；
-   FIX TASK；
-   stdin 长 prompt；
-   Windows WinError 206 修复；
-   workspace 绝对路径；
-   CodeBuddy 空输出保护；
-   Router execution / review / readonly 边界；
-   resume；
-   状态聚合；
-   Unresolved Issues 聚合；
-   dry-run Route 验证。

TASK-010 在没有新增 Framework 补丁的情况下直接完成：

``` text
SUCCESS
PASS_WITH_WARNING
APPROVE
None identified
```

因此 v0.2 MVP 验证阶段已结束。

------------------------------------------------------------------------

## 5. Known Non-blocking Risks / Notes

当前已知但非阻断：

1.  WorkBuddy 某些环境下不能独立复跑 browser smoke。
2.  业务项目工作树可能包含跨 TASK 历史未提交改动，不能自动解释为当前
    TASK 越界。
3.  CodeBuddy 登录态未来可能失效，需要重新 `/login`。
4.  Codex websocket 在部分网络环境可能失败，但已验证可 fallback HTTPS。
5.  当前真实运行基线是 Windows；尚不能未经验证宣称 Linux/macOS
    完全等价。
6.  verdict 聚合仍依赖 Agent
    输出遵守当前结论格式规范，后续正式化时应记录该契约。

这些事项当前不要求生成新的 FIX TASK，除非出现新的可复现阻断证据。

------------------------------------------------------------------------

## 6. Current Objective

当前唯一主目标：

> **完成 AI Agent Framework v0.2 的收官、冻结、正式化整理与 GitHub
> 仓库化。**

当前不是 v0.3 开发阶段。

未经用户明确决定：

``` text
v0.3 = NOT STARTED
```

AI 不得自行切换、升级或开展 v0.3 功能实现。

可以记录 future / backlog，但不得提前实施。

------------------------------------------------------------------------

## 7. Next Action

下一步优先事项：

### Step 1 --- Baseline Freeze

冻结当前已经验证的 prototype 状态，确保收官整理前有可靠回滚点。

### Step 2 --- Directory Diff / Inventory

盘点：

``` text
<PROJECT_ROOT>-prototype
```

与：

``` text
<PROJECT_ROOT>
```

之间的实际差异。

目标：

-   确认哪些修复只存在于 prototype；
-   确认哪些文件属于测试/备份/临时输出；
-   确认哪些文件应该进入正式仓库；
-   确认哪些文件必须排除；
-   不直接覆盖正式目录。

### Step 3 --- Repository Formalization

在差异盘点后继续：

-   正式目录结构；
-   README；
-   安装说明；
-   TASK / REPORT 规范；
-   dry-run / run / resume 标准命令；
-   tests；
-   changelog / version；
-   `.gitignore`；
-   敏感信息检查；
-   GitHub 仓库化。

### Step 4 --- Final Verification

正式化迁移后：

1.  重跑完整测试；
2.  基线不得无解释低于当前 `52 passed`；
3.  从正式目录执行最小 smoke TASK；
4.  验证完整链路；
5.  再决定 v0.2 Freeze / Release。

------------------------------------------------------------------------

## 8. Hard Boundaries

没有新的可复现证据时，不得重新：

-   设计基本 Agent 角色；
-   推翻 TASK 唯一输入机制；
-   重写已验证 Router；
-   重做 stdin 长 prompt；
-   重做 resume；
-   重做状态聚合；
-   把 TASK-001 ～ TASK-010 当成未完成重新执行；
-   为"更漂亮"进行无目标架构重构。

禁止未经风险确认：

-   删除历史 TASK / REPORT；
-   清空 `.aaf` 历史证据；
-   删除备份；
-   覆盖正式目录；
-   强制 reset / clean；
-   大范围移动用户文件；
-   修改 `workbuddy_skills/skills/`。

------------------------------------------------------------------------

## 9. Source-of-Truth Documents

本项目当前有三类恢复文档。

### A. Historical MVP Snapshot --- Frozen

建议正式保存为：

``` text
docs/status/AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md
```

作用：

> 记录 v0.2 MVP 验证完成时的完整历史事实。

原则上冻结，不持续覆盖。

### B. Conversation / Stage Handoff --- Frozen

建议正式保存为：

``` text
docs/handoffs/AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md
```

作用：

> 结束上一超长对话，并规定新阶段的边界、行为限制和恢复规则。

原则上冻结，不持续覆盖。

### C. Current Project State --- Living

本文件正式保存为：

``` text
PROJECT_STATE.md
```

建议位于 Framework 仓库根目录。

作用：

> **当前项目状态的持续更新入口。**

后续新对话、换模型、隔一段时间恢复项目时，应优先读取本文件，再按需要查阅历史快照与阶段交接。

------------------------------------------------------------------------

## 10. Update Rules for Future Conversations

后续负责 AI Agent Framework 的对话必须知道本文件存在。

发生以下情况时应更新 `PROJECT_STATE.md`：

-   完成一个 v0.2 收官步骤；
-   prototype → 正式目录迁移；
-   测试基线变化；
-   新增或关闭 Framework 级风险；
-   GitHub 仓库建立；
-   v0.2 freeze / release；
-   用户明确决定进入新的版本阶段。

更新原则：

1.  更新当前事实，不改写历史。
2.  历史细节进入 handoff / changelog，不无限堆入本文件。
3.  任何状态结论优先依据真实测试、REPORT 和代码证据。
4.  不因为新对话上下文缺失而重新规划已完成阶段。
5.  新对话完成重要工作后，应主动判断是否需要同步更新本文件。

------------------------------------------------------------------------

## 11. Recovery Protocol

新对话恢复项目时，读取顺序：

``` text
1. PROJECT_STATE.md
2. docs/status/AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md
3. docs/handoffs/AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md
4. 必要时查看真实 REPORT / tests / source code
```

恢复后必须接受以下当前事实：

``` text
v0.2 MVP Validation: PASSED
Regression Baseline: 52 passed
Latest Production Validation: TASK-010 SUCCESS
Current Lifecycle: CLOSING / FREEZE PREPARATION
Next Work: prototype/formal directory inventory and v0.2 formalization
v0.3: NOT STARTED
```

------------------------------------------------------------------------

## 12. Current State Summary

``` text
Project:
AI Agent Framework

Version:
v0.2

MVP Validation:
PASSED

Regression:
52 passed

Latest Real Task:
TASK-010 SUCCESS

Framework Blocking Bug:
None currently known

Working Source:
<PROJECT_ROOT>
(formal repository — v0.2 formalized, AAF-TASK-004/005)

Formal Directory:
<PROJECT_ROOT>
(migrated and validated)

Current Phase:
v0.2 CLOSED

Immediate Next Step:
v0.3 Planning (NOT STARTED — requires explicit user decision)

GitHub:
Public — https://github.com/adyfox85-wq/ai-agent-framework
Release: v0.2.0-rc1 (2026-08-25)

v0.3:
NOT STARTED
DO NOT START WITHOUT EXPLICIT USER DECISION
```
