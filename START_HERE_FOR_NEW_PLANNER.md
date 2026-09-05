# START HERE — AAF 新 Planner / 新会话接管入口

> 本文件是 AI Agent Framework（AAF）仓库面向**新 Planner** 的正式接管入口：
> 新 ChatGPT 账号、DeepSeek、Gemini、Codex/Claude 对话、或任何 LLM / Agent——只要将接任 Planner 角色。
> 目标：即使旧 ChatGPT 账号 / 旧对话 / 旧 Project 全部失效，只凭本仓库即可恢复上下文并继续规划。
> **不需要任何旧聊天历史。Git 仓库 + runtime = framework authority（不是任何聊天窗口）。**
>
> 更新：2026-09-05（AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001；v0.5 PERSONAL MVP FROZEN 期间 docs-only 新增；2026-09-05 AAF-v0.5-PH1-PORTABILITY-CLOSE-001：PH-1 = CLOSED / COMPLETE 收口，PH-2/PH-3 = NOT STARTED）
> 角色契约权威细节：`docs/internal/AAF_ROLE_CONTRACTS.md`；任务记录：`docs/internal/AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001-REPORT.md`；PH-1 收口记录：`docs/internal/AAF-v0.5-PH1-PORTABILITY-CLOSE-001-REPORT.md`

## 0. 一分钟结论

- **AAF 是什么**：本地运行的个人轻量 Agent 协作 / 调度 MVP（v0.5 PERSONAL MVP，FROZEN）。它减少
  Planner / Executor / Validator / Reviewer 之间的人工 copy/paste 与消息 relay，标准化 TASK 交接与
  REPORT 返回。实现 = Python runtime（Bridge + runner + router + adapters）+ 本 git 仓库。
- **AAF 不是托管在 ChatGPT 里**：Bridge 是本机程序（`python -m bridge.main`），读剪贴板 TASK、
  调本地 Agent CLI（`hermes` / `codebuddy` / `codex`）。Planner 永远在框架外部，通过 TASK 文本参与。
- **当前状态**：v0.5 = PERSONAL MVP FROZEN / CLOSED / COMPLETE / SYNCED（2026-09-05 冻结；
  baseline = `0c5dfad`；恢复分支 `backup/2026-09-05-v0.5-mvp-frozen`）。A0–A5 = CLOSED / COMPLETE /
  SYNCED；v0.4 = FROZEN 基线。v0.5 PH-1 Portability Hardening = CLOSED / COMPLETE（2026-09-05 AAF-v0.5-PH1-PORTABILITY-CLOSE-001 收口；docs-only；Gap Audit 判定 = PH1_RUNTIME_GAPS_NOT_BLOCKING；PH-2 / PH-3 = NOT STARTED，无自动激活）。当前无进行中 PH 任务。
- **你的角色（Planner）**：规划者 + 最终决策者。你输出标准 AAF TASK；框架按 Route 调度
  Executor → Validator → Reviewer；REPORT 交回给你，你决定下一步。框架**不**自动创建下一 TASK、
  不自动写回 ChatGPT（交接需要一次人工 copy/paste——这是 MVP 的显式边界，不是缺陷）。
- **四个抽象角色**（当前映射 = replaceable implementations，替换不重定义 AAF）：
  Planner = ChatGPT ｜ Executor = Hermes ｜ Validator = WorkBuddy ｜ Reviewer = Codex（按 Route 可选）。
  Router = AAF runtime 本身（决定执行链），不是 Agent 产品。

## 1. 角色与当前映射（摘要；完整契约见 AAF_ROLE_CONTRACTS.md）

| 角色 | 抽象职责（最小契约要点） | 当前映射 | 替换分类（证据见契约文档 §6） |
|---|---|---|---|
| Planner | 读权威状态 → 输出标准 AAF TASK → 读并验收 REPORT → 决定下一步；不做执行冒充 | ChatGPT | CONTRACT_REPLACEABLE_NOW（产品外角色，零 runtime 变更） |
| Executor | 消费 immutable TASK authority；只执行 assigned scope；产出证据与有效结构化结果；如实报告 blocker | Hermes | REPLACEABLE_WITH_ADAPTER（单点编辑，见契约文档 §6-§8） |
| Validator | 独立复核实际证据，不默认相信 Executor summary；显式 PASS / PASS_WITH_WARNING / FAIL | WorkBuddy | REPLACEABLE_WITH_ADAPTER |
| Reviewer | 独立审查 TASK + 执行证据 + validator 结果；支持 APPROVE / REQUEST_CHANGE authority；只读 | Codex（按 Route） | REPLACEABLE_WITH_ADAPTER |
| Router | 依显式 `Route:` 字段（唯一权威）或 legacy 关键词推断执行链；非法 route fail-closed | AAF runtime | 不适用（框架自身） |

> 替换任一 concrete 产品（ChatGPT / Hermes / WorkBuddy / Codex）本身**不**重定义 AAF——
> 只要替换品满足对应角色契约（v0.5「MVP FROZEN」块 + AAF_ROLE_CONTRACTS.md）。

## 2. 规划前必须清楚的三件事

1. **权威 = 仓库，不是聊天**。聊天记录会丢；仓库不会（本机 + GitHub origin + backup 分支）。
   你在对话里"记得"的任何状态，最终都要能在仓库文件里找到出处，否则不采信。
2. **你在框架外部**。你不执行代码、不写文件、不假装自己是 Hermes / WorkBuddy / Codex 的产物；
   执行与验证由框架路由到真实 CLI。你只输出 TASK、读 REPORT、做决策。
3. **TASK = 本轮 delta，不是知识库**（Anti-Bloat Policy，docs/internal/AAF_TASK_EXECUTION_POLICY.md）。
   背景用 path/section 引用（Source of Truth 节），不复制全文；同一约束只写一次。

## 3. 新 Planner 恢复上下文（按顺序读）

1. 本文件（START_HERE_FOR_NEW_PLANNER.md）
2. `README.md`（产品定位 / 12 步 Quick Start / 版本表 / troubleshooting）
3. `docs/internal/PROJECT_STATE.md`（**权威当前状态**：顶部 Last Updated 链 → v0.5 段「MVP FROZEN」
   块与最新状态块；下方 v0.4 及更早 = 冻结历史，只读不改写）
4. `docs/internal/AAF_MASTER_BACKLOG.md`（长期问题 / 恢复登记；§5.1 恢复链、§5.3 ChatGPT 丢失恢复原则）
5. `docs/internal/AAF_ROLE_CONTRACTS.md`（四角色契约 + 替换流程权威）
6. 最近执行结果与交接：目标业务项目 `.aaf/<最近 Task ID>/REPORT.md`（最近一轮 truth + Planner
   Handoff）+ `docs/internal/handoffs/` 最新 closing handoff（跨阶段交接）
7. 产出 TASK 前：`templates/TASK.md` + `docs/internal/AAF_TASK_EXECUTION_POLICY.md`
   （Compact schema / Stage Context Packet / 结构化结果契约）

> 最小恢复集 = 1 + 2 + 3 顶部 + 最近 REPORT（§4-§5 给出操作所需全部格式，见下）。

## 4. 怎么生成一个合规的 AAF TASK

规则（违反 = Bridge/Validation 拒绝或 fail-closed）：

- 输出放在**纯文本代码块**；必须以 `AAF_TASK_BEGIN` 开始、`AAF_TASK_END` 结尾。
- 不要用 Markdown 转义（`AAF\_TASK\_BEGIN` 会被当作缺 marker）；关键字段单行：
  `Task ID:` / `Task Name:` / `Workspace:` / `Risk:` / `Route:`。
- 最小必填字段（Validation 强制）：Task ID / Task Name / Objective / Acceptance（另加 Workspace 供执行）。
- `Workspace` = 目标业务项目**绝对路径**，必须与 Bridge 当前 workspace 一致（binding 不匹配 → 拒绝）。
- `Risk:` 可选；词汇只允许 `LOW / MEDIUM / HIGH / CRITICAL`（缺失 = 向后兼容；非法值 = 校验拒绝）。
- `Route:` 可选 machine 字段；只允许 `hermes / workbuddy / codex`（分隔符容忍 `->` / `→` / `,`）；
  未知 agent / 重复 / malformed → **Task Validation FAIL（fail-closed）**，绝不静默回退。
- 通用结构（字段语义见 templates/TASK.md）：Task ID / Task Name / Workspace / Risk / Objective /
  Context（引用不复制）/ Source of Truth（只列 path）/ Requirements / Scope / Out of Scope /
  Validation / Acceptance / Route / Route Hint。

最小示例：

```text
AAF_TASK_BEGIN
Task ID: DEMO-002
Task Name: Demo Task
Workspace: D:\path\to\project
Risk: MEDIUM
Objective:
做一件事，说清楚目标与边界。

Acceptance:
1. 完成标准
2. 可验证结果

Route: hermes -> workbuddy -> codex
AAF_TASK_END
```

> 本仓库 docs/internal/ 下的正式任务 REPORT 与你的上一个 TASK prompt 都是真实范例。

## 5. 闭环：TASK 怎么进去、REPORT 怎么回来

1. Bridge 已启动：`python -m bridge.main`（配置 `%USERPROFILE%\.aaf-bridge\config.json`；
   hotkey 默认 `ctrl+alt+a`；Bridge 不自动开机启动）。
2. 复制 TASK 全文 → 按 Ctrl+Alt+A → Bridge 校验（BEGIN/END / Task ID 唯一 / Workspace binding /
   duplicate / 项目切换确认）→ 确认 Execute。
3. 框架在业务项目 `.aaf/<Task ID>/` 下运行：冻结 `TASK.snapshot.md`（immutable execution snapshot +
   raw-byte SHA-256）→ 按 route.json 依次执行各 stage（Hermes → WorkBuddy → Codex），每 stage 独立
   prompt（下游只收结构化摘要 + artifact 引用，不默认全文注入）→ 聚合终态 → 生成 REPORT.md。
4. 完成弹窗 → **Copy Report** → 粘贴回 Planner 对话。REPORT.md 结构：
   `## Current Status`（SUCCESS / WAITING）/ `## Task Reference`（snapshot path + hash）/
   `## Agent Results`（各 stage 摘要 + 完整结果路径）/ `## Unresolved Issues` /
   `## Planner Handoff`（给你下轮决策的权威指令段）。

### Planner Handoff 语义（= 下轮指令）

- **Current Status = SUCCESS**：全部必需节点通过且无 blocking。规划下一个**最小**任务；
  **不重开已完成 scope**。
- **Current Status = WAITING**：存在 blocker（见下）。读 `## Unresolved Issues` 定位是哪个
  stage / 什么 blocker，先解决再规划。
- Hermes 缺有效结果 / FRAMEWORK_ERROR / 必需 route agent 未跑 → integrity note + WAITING
  （Route Completeness Guard：**exit 0 / "FINISHED" 不构成验收通过**；结构化块缺失或损坏、空输出、
  未认证 CLI 静默无输出等一律按失败处理——见 AAF_TASK_EXECUTION_POLICY.md §4-§5）。

## 6. 状态与判定词汇（怎么读结果）

| 来源 | 输出词汇 | 含义 |
|---|---|---|
| Hermes（Executor） | status: SUCCESS / FAILED（结构化块 + narrative） | 执行自报；commit/changed_files **以框架 git 观察为准**，不取自报 |
| WorkBuddy（Validator） | PASS / PASS_WITH_WARNING / FAIL（+ blocking_rework） | 独立复核结论；FAIL = blocking |
| Codex（Reviewer） | APPROVE / REQUEST_CHANGE | 审查结论；REQUEST_CHANGE = blocking |
| Framework 终态 | SUCCESS / WAITING / FAILED / CANCELLED | 聚合：任一 blocking（FAIL / FAILED / REQUEST_CHANGE / FRAMEWORK_ERROR / 必需节点无效）→ WAITING，不误报 SUCCESS |

- WorkBuddy / Codex 的答复必须以 `AAF_STRUCTURED_RESULT_BEGIN {JSON} AAF_STRUCTURED_RESULT_END`
  结尾（framework 注入的契约，非自选）；缺失 / 损坏 → 显式 `structured_summary_status =
  NOT_PROVIDED / MALFORMED`，下游必须读 narrative。
- `[]` 表示"确认没有"；未确认的项不放入数组（unknown ≠ empty）。
- **terminal WAITING 的 Task ID 不得原样重跑**：同 Task ID 重复提交 = duplicate 拒绝
  （Bridge 状态卡片 / TASK_ALREADY_EXISTS，不覆盖 artifacts）。合法路径：
  a) 若属 stage 失败可修复（如 CLI 缺失、transient 429）→ 同一 execution 目录 `--resume-from`
     续跑（复用已完成 stage，只跑失败/缺失 stage）；真实 blocker（REQUEST_CHANGE / FAIL）必须先解决；
  b) 开新 TASK——FIX 惯例：**新 Task ID**，Context 引用 parent Task ID + 其 Unresolved /
     REQUEST_CHANGE 项，只写本轮 delta（见 AAF_TASK_EXECUTION_POLICY.md §1.4）。
- **REPORT 之后怎么继续**：SUCCESS → 下一最小任务 / 收口 / 停止（你决定，框架不自动续）；
  WAITING → 按 Unresolved Issues 规划 FIX；每轮结束做 Stage Retrospective（Policy §13）。

## 7. 安全与 scope 铁规则

- **v0.5 = FROZEN**：不重开 A0–A5 实现 scope；A6（health/quarantine/requalification/calibration）、
  A4+（HIGH/CRITICAL WorkBuddy、Codex/multi-agent routing）、non-MVP 列表（long-term memory /
  self-learning / large DAG / agent marketplace / distributed workers/queue / large dashboard-platform
  UI / plugin ecosystem / complex autonomous scheduling / complex long-term model scoring /
  large-scale subagent system / Agent OS expansion / 图形化 Cost Gate UX）一律 NOT_REQUIRED_FOR_MVP。
- **post-freeze opt-in**：新 framework capability 必须先经用户（Ady）**显式 scope 批准**才进 mainline；
  旧 roadmap future phases 不自动激活。
- **历史不改写**：PROJECT_STATE v0.4 段 / A0-A5 实现记录 / 旧 roadmap / REQUIRED_BEFORE_A5_CLOSE
  9 项原文 = 冻结历史，只读。
- **Git 纪律**：默认 **no push**（route 独立验证完成后才按惯例 sync）；通常恰好一个 docs/state
  commit；不 amend；不 rewrite history；不动他人分支。
- **改动边界**：不修改 runtime 除非 TASK 显式授权（本 PH-1 = docs-only）；
  跨 Agent 交接材料必须自包含（供无上下文的复核者直接使用）。
- 成本纪律：A0 Paid Guard fail-closed——付费模型执行需要一次性精确授权；Planner 不要试图绕过
  （无授权 → WAITING/COST_APPROVAL_REQUIRED）。

## 8. 角色替换（Planner 被替换 / 替换他人）——诚实评估

- **Planner 今天就可替换**：Planner 在框架外部、无 CLI 绑定——任何能读仓库上下文并能输出标准
  AAF TASK 文本的 LLM / Agent 都可接任，**零 runtime 变更**。DeepSeek / Gemini / 新 ChatGPT 账号均可；
  实际条件 = 能读到权威文件（或由人粘贴关键上下文：本文件 + PROJECT_STATE 顶部 + 最近 REPORT）。
- **Executor / Validator / Reviewer（Hermes / WorkBuddy / Codex）今天不能零改动替换**：
  runtime 以 agent 名白名单 + 每 CLI 调用分支驱动（router.py ALLOWED_ROUTE_AGENTS / adapters.py
  ROLE_INSTRUCTIONS + CLI 发现 + 上游依赖表 / runner.py 按 route agent 赋 role + A0/A3/A4/A5
  模型层），替换 = 按 AAF_ROLE_CONTRACTS.md §6-§8 的最小安全流程做**单点 adapter 编辑** +
  全量回归 + fresh-runner 验证。**不要声称"任意 Agent 即插即用"**——runtime 证据不支持。
- 替换本身不重定义 AAF（见 §1 注）。本任务**没有**构建 plugin ecosystem / 动态 adapter 加载 /
  model marketplace（显式 out of scope，v0.5 non-MVP 列表）。

## 9. 恢复点 / handoff 资产（丢失后在哪儿继续）

- 长期恢复链（backlog §5.1）：README → PROJECT_STATE → AAF_MASTER_BACKLOG → latest closing
  handoff → git history。
- GitHub：`origin/main`；backup 分支 `backup/2026-09-05-pre-mvp-freeze` 与
  `backup/2026-09-05-v0.5-mvp-frozen`（= 0c5dfad，v0.5 冻结点；local + origin 均已存在）。
- `docs/internal/handoffs/`：各版本 closing handoff（最新 v0.4 = AI-Agent-Framework-v0.4-CLOSING-HANDOFF-2026-08-29.md；
  v0.5 当前状态以 PROJECT_STATE v0.5 块为准）。
- 业务侧真值：目标项目 `.aaf/<Task ID>/REPORT.md`（最近一轮 execution truth）；Drive Emergency
  Planner Handoff（用户处，freeze criteria ⑨ 事实）。
- Obsidian：`D:\AdyAI\Obsidian-Vault\AI Agent Framework\CURRENT_HANDOFF.md`（working-knowledge 层，
  MIRROR ONLY，非权威；见 backlog §5.4）。

## 10. 你现在该做的

1. 按 §3 读权威文件（至少 1–3 顶部 + 最近 REPORT）；
2. 与用户（Ady）确认：当前目标、workspace、scope 边界（frozen MVP 内 / 显式批准的 PH 任务）；
3. 输出下一个标准 AAF TASK（§4 格式；含 Route / Risk）；
4. 等 REPORT → 按 §5-§6 语义决策 → 重复。

---
*本文档是 Living 入口：如与 PROJECT_STATE / 契约文档冲突，以后者为准；如发现过时，请以正式 TASK
更新本文档（本仓库修改 = docs-only 纪律，同 v0.5 post-freeze opt-in 政策）。*
