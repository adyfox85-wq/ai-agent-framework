# AI Agent Framework v0.2｜阶段交接与新对话启动基线

> 日期：2026-08-25\
> 用途：终止当前超长对话，作为项目下一阶段新对话的正式启动基线。\
> 配套文件：`AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md`
> 为项目事实快照；本文件负责下一阶段边界、行为限制与交接规则。

## 一、当前结论

AI Agent Framework v0.2 自动化 MVP
的核心闭环已经通过真实项目连续试跑验证。

固定链路：

``` text
Planner(ChatGPT)
→ TASK.md
→ Framework Router
→ Hermes Executor
→ WorkBuddy Reviewer
→ Codex Review
→ REPORT.md
→ Planner
```

当前阶段已经从"验证 Framework 是否成立"切换为：

**v0.2 收官 → 冻结 → 正式化整理 → GitHub 仓库化 → 可迁移性验证。**

未经用户明确决定，不进入 v0.3。

## 二、关键路径与环境

-   prototype：`D:\AdyAI\ai-agent-framework-v0.2-prototype`
-   正式 Framework 目录：`D:\AdyAI\ai-agent-framework`
-   当前真实试跑项目：`D:\AdyAI\guoxue-skills-lab`
-   禁止随意修改：`D:\AdyAI\guoxue-skills-lab\workbuddy_skills\skills\`
-   Hermes：v0.20.1
-   CodeBuddy：2.137.1
-   Codex CLI：0.149.0-alpha.4.1
-   Python：3.11.15
-   CodeBuddy 已登录；Codex 已加入 PATH。部分网络下 Codex websocket
    可能失败，但已验证 HTTPS fallback 可工作。

## 三、TASK 规则

TASK 是 Framework 唯一正式执行入口，不再以"给 Hermes
一段自然语言指令"作为正式开发流程。

标准结构：

``` text
# Task ID
# Task Name
# Objective
# Background / Current State
# Requirements
# Scope / 禁止事项
# Files / Resources
# Acceptance Criteria
# Route Hint
# Planner Notes
```

编号必须唯一、连续。Route Hint 只是建议，最终 Route 由 Router
决定。Planner Notes
必须写清当前阶段、已完成事项、禁止重复事项以及与历史任务关系。

## 四、已经验证的能力

截至 TASK-010 已真实验证：

-   正常任务可以自动完成
    `Hermes → WorkBuddy → Codex → REPORT → SUCCESS`。
-   Codex 发现真实业务缺陷时 Framework 能正确停在
    `WAITING`，不会误报成功。
-   `REQUEST_CHANGE` 可以进入 FIX TASK，再走完整链路并转为 `APPROVE`。
-   `PASS_WITH_WARNING + APPROVE` 可以正确聚合为 `SUCCESS`。
-   dry-run 可在正式执行前检查 Route。
-   Framework Error、resume、状态聚合等异常路径均经过真实问题验证。
-   TASK-010 在没有新增 Framework 补丁的情况下直接完成
    `SUCCESS / PASS_WITH_WARNING / APPROVE / None identified`。

因此：**v0.2 MVP 核心闭环验证通过。**

## 五、已暴露并修复的 Framework 问题

### 1. Windows 长 Prompt / WinError 206

WorkBuddy 曾把 50KB+ prompt 作为命令行参数传递，超过 Windows
CreateProcess 限制。现已改为 stdin 传输，完整上下文不截断。

### 2. Hermes workspace 错位

真实 smoke test 曾因临时 workspace / 环境变量导致写错位置。现已在 prompt
中强制注入 workspace 绝对路径。

### 3. CodeBuddy 未登录时静默空输出

已增加空输出失败保护；CodeBuddy 已完成登录。

### 4. Router 多轮边界误判

已经处理 UI 子串、review/validation、英文
implementation/fix/recovery、强弱
readonly、局部"不实现/不改变"约束、bugfix/React Hooks correctness
等误判。

原则已固定：

**明确 execution / fix / modify 意图优先于
review/validation；只有明确"只检查 / 不修改任何文件 /
read-only"等全局只读任务才允许跳过 Hermes。**

### 5. Resume

已有最小 `--resume-from`，可以复用已完成 Agent
结果，避免无意义重复执行。

### 6. 状态聚合

已修复裸子串 `REQUEST_CHANGE / FAIL / Failed to...`
导致历史引用或工具描述被误判的问题。当前采用结论优先；真正阻断结论才进入
WAITING / Unresolved Issues。

最后已知测试基线：**52 passed**。

## 六、关键真实试跑历史

-   TASK-003：真实自动链成功；期间暴露长 Prompt / resume 等问题。
-   TASK-004 及 FIX：验证 Codex 可阻断真实数据契约问题。
-   TASK-005 及 FIX：暴露 Router、readonly、状态聚合边界并完成修复。
-   TASK-006：成功。
-   TASK-007：成功。
-   TASK-008：Codex 因 React Hooks 条件调用给出 REQUEST_CHANGE。
-   TASK-008-FIX-001：修复后 SUCCESS / PASS_WITH_WARNING / APPROVE。
-   TASK-009：Codex 发现"关系详情页 → 关系合盘"入口缺失。
-   TASK-009-FIX-001：修复后 SUCCESS / PASS_WITH_WARNING / APPROVE。
-   TASK-010：未再修改 Framework，直接完成 SUCCESS / PASS_WITH_WARNING /
    APPROVE / None identified。

TASK-010 是 v0.2 MVP 验证阶段的收官观察点。

# 七、明确边界

新对话不得把项目当成"刚开始设计 Framework"。

没有新的、可复现证据时，禁止重新：

-   设计 Planner / Router / Executor / Reviewer / Codex 基本角色；
-   推翻 TASK 作为唯一正式输入；
-   重写已验证 Router；
-   重做 stdin 长 prompt；
-   重做 resume；
-   重做状态聚合；
-   把 TASK-001～TASK-010 当成未完成重新执行；
-   为"更漂亮"进行无目标架构重构。

Framework 收官不得随意修改国学业务项目。

当前验证修复发生在 prototype。**不得默认正式目录已经同步 prototype
的全部修复。** 正式化时必须先盘点差异，再迁移，禁止直接覆盖。

禁止未经明确风险确认执行：

-   删除历史 TASK / REPORT；
-   清空 `.aaf` 历史证据；
-   覆盖正式目录；
-   强制 reset / clean；
-   删除备份；
-   大规模移动文件；
-   修改 `workbuddy_skills/skills/`。

## 八、行为限制：禁止 AI 自行"换 3"

用户明确要求："不要让 AI 进行换 3。"

按当前项目语境，本交接将其落实为：

**未经用户明确决定，AI 不得自行把当前工作切换/升级到 v0.3，不得擅自开展
v0.3 功能设计或实现。**

当前任务是 **v0.2 收官**，不是 v0.3 开发。

可以记录 v0.3 候选事项到
backlog，但不得以"顺手优化""以后会需要""架构升级"为理由提前实施。

如果用户所说"换
3"另有特定含义，新对话应以用户后续解释为准；解释前至少严格执行上述"不自行进入
v0.3"的限制。

# 九、新对话行为约束

1.  读取交接后直接承接，不要重新询问 Framework
    是什么、角色是谁、路径在哪里、TASK 怎么运行、Framework
    是否已经验证。
2.  常规、低风险、可回滚事项主动推进，不逐步要求用户确认。
3.  只有重大架构分叉、覆盖/删除风险、版本边界变化、GitHub
    公开策略、认证授权等事项才要求用户判断。
4.  不把 `PASS_WITH_WARNING` 自动升级成 blocker；必须区分
    PASS_WITH_WARNING、REQUEST_CHANGE、FAIL、FRAMEWORK_ERROR。
5.  不为了"完善"无限扩 scope。v0.2 收官目标是把已验证 MVP
    固化为可靠、可理解、可迁移的正式版本。
6.  用户需要命令时，优先提供"一整段完整可复制"的 PowerShell 命令块。
7.  不默认加入 Claude Code；现有角色仍是 Hermes + WorkBuddy + Codex。

# 十、两个对话交接必须注意

1.  新对话优先同时读取本文件与 v0.2 MVP 状态快照。
2.  本文件规定"如何继续与边界"；状态快照记录"发生过什么与当前事实"。
3.  口头判断若与真实 REPORT 冲突，以 REPORT、代码与测试证据为准。
4.  dry-run 的 `(not run)` 不是 Agent 故障。
5.  业务 TASK 的 WAITING / REQUEST_CHANGE 不等于 Framework
    失败。先区分业务问题与编排层问题。
6.  Router 错路由、Agent 调用异常、结果丢失、状态误聚合、resume
    失败等才属于 Framework 自身 bug。
7.  不依赖模糊记忆恢复历史；优先读取交接文件、REPORT、测试和代码。
8.  TASK-010 后国学项目进入 Framework 的生产使用阶段，不再默认承担 v0.2
    验证职责。
9.  收官必须保留 WAITING、REQUEST_CHANGE、FIX、APPROVE、SUCCESS
    等真实历史证据。
10. GitHub 化前检查
    token、认证信息、`.env`、本机绝对路径、临时输出、隐私及不应公开文件。
11. 当前真实环境是 Windows；不得未经验证宣称 Linux/macOS 行为完全一致。
12. CodeBuddy 登录态可能失效；Codex websocket 可能失败并 fallback
    HTTPS。
13. `52 passed` 是迁移前已知回归基线。正式化后必须重新跑测试。
14. prototype → 正式版本迁移后，应再跑一次最小 smoke TASK 验证完整链路。
15. 不得因为换了新对话就重新发明与现有 v0.2 不兼容的工作流。

# 十一、下一阶段建议顺序

1.  冻结当前 prototype 基线。
2.  盘点 prototype 与正式 Framework 目录差异。
3.  识别应保留/删除/归档的测试物、备份物、历史输出。
4.  设计正式仓库目录结构。
5.  迁移已验证代码，保留回滚能力。
6.  固化 README、安装、运行、TASK/REPORT 规范。
7.  固化 dry-run、正式运行、resume 命令。
8.  整理测试和回归基线。
9.  检查敏感信息与本机耦合。
10. GitHub 仓库化并建立版本/changelog。
11. 从正式目录重新跑测试与最小 smoke TASK。
12. 完成 v0.2 freeze/release。

**在以上收官完成前，不启动 v0.3。**

# 十二、长期恢复文件

建议长期保留：

``` text
AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md
AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md
```

前者是历史事实快照，原则上冻结；本文件是阶段交接入口。

正式仓库后建议再维护：

``` text
PROJECT_STATE.md
```

用于持续更新当前状态，不覆盖历史快照。

# 十三、新对话启动语

新建 AI Agent Framework 项目对话后，上传两份交接文件并发送：

> 这是 AI Agent Framework 项目的新阶段对话。请先完整读取我提供的 v0.2
> MVP
> 状态快照和阶段交接文件，并把它们作为当前项目事实基线。不要重新规划已经完成的
> v0.2 验证阶段，不要自行进入 v0.3。当前目标是完成 AI Agent Framework
> v0.2 的收官、冻结、正式化整理与 GitHub
> 仓库化。先根据交接文件恢复当前状态，再规划收官工作的第一步。

# 十四、当前对话终止点

``` text
AI Agent Framework v0.2
MVP 核心闭环：验证通过
真实生产试跑：TASK-010 已成功完成
Framework 新增阻塞 Bug：无
当前阶段：验证阶段结束
下一阶段：v0.2 收官 / Freeze / Repositoryization
v0.3：未经用户明确决定，不启动
```

本文件即下一对话的正式交接入口。
