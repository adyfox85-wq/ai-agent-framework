# AI Agent Framework v0.2 MVP 状态与交接快照

> 快照日期：2026-08-25  
> 用途：AI Agent Framework 项目长期恢复锚点。若后续对话上下文过长、记忆丢失或需要新建对话，应优先读取本文件，再继续规划。  
> 当前判断：**v0.2 自动化 MVP 核心闭环已通过真实项目连续试跑，可以进入收官/冻结阶段。**

---

## 1. 项目目标

AI Agent Framework 的目标是把原先需要用户人工在多个 Agent 之间复制粘贴的协作过程，统一为：

```text
Planner（ChatGPT）
  ↓
标准 TASK.md
  ↓
Framework Router
  ↓
Executor / Reviewer / Auditor 自动路由与执行
  ↓
REPORT.md
  ↓
Planner 吸收结果并规划下一 TASK
```

核心原则：

- TASK 是 Framework 唯一正式输入；
- REPORT 是 Planner 的正式回流输入；
- 用户不再人工传递 Hermes → WorkBuddy → Codex 的中间结果；
- Router 负责决定实际执行链；
- Reviewer/Auditor 可以阻止错误任务进入下一阶段；
- 常规任务不要求用户逐步确认，只有重大节点、风险或产品判断再交给用户。

---

## 2. 当前角色分工

### Planner

ChatGPT 项目规划对话。

负责：

- 理解需求；
- 拆 TASK；
- 定义 Objective / Scope / Acceptance Criteria；
- 读取 REPORT；
- 判断 SUCCESS / WAITING 后的下一动作；
- 生成下一 TASK 或 FIX TASK。

### Router

AI Agent Framework 内部路由层。

负责根据 TASK 内容决定：

- Hermes 是否需要执行；
- WorkBuddy 是否需要复核；
- Codex 是否需要审查。

### Executor

Hermes。

当前验证版本：Hermes Agent v0.20.1（2026.8.13）。

### Reviewer / Validator

WorkBuddy（CodeBuddy CLI）。

当前验证版本：2.137.1。

### Auditor

Codex CLI。

当前验证版本：codex-cli 0.149.0-alpha.4.1。

### Runtime

Python 3.11.15。

---

## 3. 当前关键目录

### Framework prototype

```text
<PROJECT_ROOT>-prototype
```

这是目前经过真实任务修复、验证的 **v0.2 prototype 工作版本**。

### 正式 Framework 目录

```text
<PROJECT_ROOT>
```

在本轮 prototype 修复过程中一直要求 **不要修改该正式目录**。

### 真实试跑业务项目

```text
<BUSINESS_PROJECT>
```

产品：示例业务 H5。

### Framework 业务任务输出

通常位于：

```text
<BUSINESS_PROJECT>\.aaf\<TASK-ID-or-task-file-stem>\
```

### TASK 临时下载位置

目前 Planner 生成的 TASK.md 通常下载到：

```text
<USER_HOME>\Downloads
```

---

## 4. 当前标准运行方式

先进入 Framework：

```powershell
cd <PROJECT_ROOT>-prototype
```

自动读取 Downloads 最新 MD：

```powershell
$task = Get-ChildItem "<USER_HOME>\Downloads\*.md" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$taskId = [System.IO.Path]::GetFileNameWithoutExtension($task.Name)
```

先 dry-run：

```powershell
python run.py "$($task.FullName)" `
  --workspace "<BUSINESS_PROJECT>" `
  --output "<BUSINESS_PROJECT>\.aaf\$taskId" `
  --dry-run
```

确认 Route 合理后正式执行：

```powershell
python run.py "$($task.FullName)" `
  --workspace "<BUSINESS_PROJECT>" `
  --output "<BUSINESS_PROJECT>\.aaf\$taskId"
```

对于需要保留旧失败证据的 FIX，可使用新输出目录，例如：

```text
TASK-008-FIX-001-RERUN
```

---

## 5. TASK 标准结构

Planner 当前约定 TASK 至少包含：

```text
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

Route Hint 只是建议，最终 Route 由 Router 决定。

Planner Notes 必须尽量写明：

- 当前项目阶段；
- 已完成范围；
- 不允许重新打开的历史任务；
- 与前一 TASK / FIX 的关系；
- 已知 warning 中哪些不属于本任务。

---

## 6. 已验证的真实闭环

v0.2 已经不是只通过 smoke test，而是在 `<BUSINESS_PROJECT>` 上连续运行真实开发任务。

已覆盖的核心流程：

```text
TASK.md
→ Router
→ Hermes
→ WorkBuddy
→ Codex
→ 状态聚合
→ REPORT.md
→ Planner
```

同时真实覆盖：

```text
SUCCESS
WAITING
REQUEST_CHANGE
FIX TASK
APPROVE
resume
Framework Error 修复
```

因此判断 Framework 是否正确的标准不是“每个业务 TASK 一次 SUCCESS”，而是：

- 该执行时执行；
- 该复核时复核；
- 发现业务缺陷时能阻断；
- FIX 后能恢复；
- 最终状态不误报；
- REPORT 能给 Planner 足够上下文。

---

## 7. 业务 H5 真实试跑进度

截至 TASK-010：

- TASK-001：工程恢复与开发启动；
- TASK-002：首页 Home；
- TASK-003：关系页；
- TASK-004：用户建档；
- TASK-004-FIX-001：出生信息数据契约修正；
- TASK-005-FIX-001：我的命盘详情第一阶段；
- TASK-006：推演页第一阶段；
- TASK-007：“问一件事”第一阶段；
- TASK-008：报告页 / 报告详情第一阶段；
- TASK-008-FIX-001：报告详情 React Hooks 条件调用修复；
- TASK-009：关系合盘第一阶段；
- TASK-009-FIX-001：关系详情 → 合盘入口与 TA 预选补齐；
- TASK-010：“我的”页第一阶段。

TASK-010 最终正式 REPORT：

```text
Current Status: SUCCESS
Route: hermes -> workbuddy -> codex
WorkBuddy: PASS_WITH_WARNING
Codex: APPROVE
Unresolved Issues: None identified.
```

TASK-010 也是本轮人为设定的 Framework v0.2 MVP 收官观察任务。

关键意义：在此前 Router / 状态聚合等修复完成后，TASK-010 没有再暴露新的 Framework 自身 bug，直接完成完整真实链路。

---

## 8. Framework v0.2 期间暴露并修复的关键问题

### 8.1 CLI 环境 / PATH

最初 CodeBuddy / Codex 在 PowerShell 中无法直接调用。

最终验证：

- Hermes：可用；
- CodeBuddy：可用；
- Codex：可用；
- Python：可用。

Codex 用户 PATH 曾补入具体 hash 版本目录，因此未来 Codex 升级后可能需要更新 PATH。

### 8.2 WorkBuddy 长 Prompt → WinError 206

根因：

完整 TASK + Hermes Result 被作为超长 `codebuddy -p "..."` 命令行参数传递，超过 Windows CreateProcess 命令行长度限制。

修复：

- WorkBuddy prompt 改为 stdin 传输；
- CLI 参数保持短；
- 不截断 Hermes 上下文。

真实 TASK-003 恢复成功。

### 8.3 Hermes workspace 错位

早期 smoke test 中 Hermes 曾把文件写到 Temp。

原因与 `TERMINAL_CWD` / workspace 语义有关。

修复：Framework prompt 强制注入 workspace 绝对路径。

### 8.4 CodeBuddy 未认证时静默空输出

CodeBuddy 未登录时曾 exit 0 但没有有效结果。

修复：

- 用户完成 CodeBuddy `/login`；
- Adapter 增加“空输出 = 失败”保护。

### 8.5 Router：`UI` 子串误伤

早期 Router 使用裸子串，`requirements` 等文本可能包含 `ui` 字符组合，导致错误视觉任务判断。

修复：短 ASCII 词使用词边界匹配。

### 8.6 Router：实现任务被 visual_review 否决

早期逻辑类似：

```text
needs_execution = execution_hit and not visual_review
```

导致同时出现 UI / review 文本的真实前端任务跳过 Hermes。

修复：明确 execution 意图优先于 review/visual 文本。

### 8.7 Router：英文 implementation / fix / recovery 未覆盖

早期执行词主要是中文。

补充英文 execution signals，包括 implementation / fix / repair / restore / recovery / modify / create / refactor / feature 等。

### 8.8 Router：禁止事项中的“不实现”误判整个 TASK 只读

TASK-005-FIX-001 中存在：

```text
不实现真实排盘
不生成真实命盘算法
```

这些只是 Scope 禁止项，却被 READONLY 信号误判为“整个任务不执行”。

修复：拆分 strong readonly 与 weak/local readonly；execution 优先。

### 8.9 Router：局部“不改变”再次误判只读

TASK-008-FIX-001 中：

```text
不改变收藏业务语义
```

曾命中 strong readonly，导致 bugfix 被路由成：

```text
workbuddy -> codex
```

修复：收紧全局 readonly 信号，只保留类似：

```text
不修改任何文件
不要修改任何文件
不进行任何修改
read-only
只检查
```

同时补充 bugfix / patch / correct / correctness / React Hooks 等执行与代码风险词。

真实 TASK-008-FIX-001 后续成功走：

```text
hermes -> workbuddy -> codex
```

### 8.10 Runner：缺失必需 Executor 仍可能继续

已增加执行链保护：

- 必需 agent 缺失/无效结果 → 停止后续链路；
- 状态进入 WAITING；
- REPORT 标注缺失节点。

### 8.11 Resume 机制

TASK-003 WorkBuddy 出错后需要避免重复执行 Hermes。

新增 `--resume-from` 最小恢复机制：

- 读取已有 route/result；
- 跳过已完成有效节点；
- 从失败节点继续；
- 保留已完成 Agent 结果。

### 8.12 状态聚合误判历史 REQUEST_CHANGE

曾出现 WorkBuddy/Codex 报告写：

```text
原 REQUEST_CHANGE 已关闭
```

Runner 却因为裸子串 `REQUEST_CHANGE in body` 把任务误判为 WAITING。

同样，Hermes 日志中的 `Failed to read file` 也曾被 `FAILED` 误判成任务失败。

修复：

- 结论优先；
- WorkBuddy PASS / PASS_WITH_WARNING 视为通过；
- Codex APPROVE 视为通过；
- 只识别真正的当前 verdict 阻断标记；
- 历史引用、warning、工具级 failed 描述不再直接阻断。

### 8.13 Unresolved Issues 误收集整份正常报告

早期 `_extract_unresolved` 通过裸 marker 搜索，导致包含 FAIL/REQUEST_CHANGE 历史文本的正常 PASS/APPROVE 报告被塞入 Unresolved。

修复后：

```text
PASS + APPROVE
→ SUCCESS
→ Unresolved Issues: None identified.
```

### 8.14 Dry-run 误导性 integrity notes

早期 dry-run 因 Agent 本来就不会执行，却显示 Hermes/WorkBuddy missing notes。

已修复：DRY_RUN 不再生成这种误导性 unresolved notes。

---

## 9. 当前测试状态

最后一次 Framework Router 修复后：

```text
52 / 52 tests passed
```

此前状态聚合修复阶段为：

```text
46 / 46 tests passed
```

真实 TASK-008-FIX-001 完整 dry-run 也验证：

```text
hermes -> workbuddy -> codex
Unresolved Issues: None identified.
```

之后 TASK-008-FIX-001、TASK-009、TASK-009-FIX-001、TASK-010 均继续用于真实生产试跑。

---

## 10. TASK-010 最终验证事实

TASK-010：“我的”页第一阶段。

最终：

```text
SUCCESS
hermes -> workbuddy -> codex
```

WorkBuddy：

```text
PASS_WITH_WARNING
```

Codex：

```text
APPROVE
```

Unresolved：

```text
None identified.
```

独立验证包括：

- `npx tsc --noEmit` 通过；
- Executor / WorkBuddy `npm run build` 通过；
- Mock 账号/权益数据集中管理；
- TA / report / favorite count 来自已有 Mock；
- 未建档/已建档入口切换正确；
- 没有真实 OAuth / 支付 / 数据库 / 通知 / WebView 能力；
- Codex 明确 APPROVE。

Codex 自身只读环境 build 遇到 `.vite-temp` EPERM，但认定为审查环境限制，不是源代码缺陷。

---

## 11. 当前已知非阻断风险

### Browser smoke 独立复跑能力

WorkBuddy 当前环境多次无法独立执行浏览器 smoke。

Executor 可跑 browser smoke，Reviewer 主要通过代码/数据/构建独立验证其前提。

当前定性：**非阻断 warning**。

未来可在 v0.3 或专门验收环境中增强浏览器级独立复核。

### 跨 TASK 工作树历史未提交

`<BUSINESS_PROJECT>` 工作树存在 TASK-003～010 的历史未提交/混合改动风险。

这不是 Framework 核心链路失败，但在未来：

- commit；
- 发布；
- PR；
- 自动回滚；

时必须处理任务隔离。

### Codex 网络

Codex websocket 曾受网络影响失败，但 CLI 可以 fallback HTTPS。

重要审查时 VPN 可提高稳定性。

### Codex PATH

当前 PATH 指向具体版本 hash 目录，升级后可能需要重新补 PATH。

### Agent verdict 规范

当前状态聚合仍依赖比较规范的 Agent verdict，例如：

```text
PASS
PASS_WITH_WARNING
APPROVE
FAIL
REQUEST_CHANGE
FAILED
```

若未来 Agent 全部改用自然语言/中文小写结论，需要更强结构化输出协议。

---

## 12. 当前版本判断

截至 TASK-010：

> **AI Agent Framework v0.2 自动化 MVP 核心闭环验证通过。**

理由不是简单“连续几个任务 SUCCESS”，而是已经真实验证：

1. 新 TASK 正常执行；
2. Router 可以选择正确 Agent；
3. Hermes 可修改真实项目；
4. WorkBuddy 可独立复核；
5. Codex 可发现真实业务缺陷；
6. REQUEST_CHANGE 会阻止任务错误关闭；
7. Planner 可生成 FIX TASK；
8. FIX 可重新完整执行；
9. Codex 可从 REQUEST_CHANGE 转 APPROVE；
10. 状态聚合最终可正确给出 SUCCESS / WAITING；
11. Framework Error 可修复并 resume；
12. REPORT 可作为 Planner 下一轮唯一回流输入。

TASK-010 没有暴露新的 Framework 自身缺陷，因此可以结束“持续把业务 TASK 当 Framework 验证任务”的阶段。

后续业务 H5 的 TASK-011、012……应视为 **Framework 的生产使用**，不是继续证明 Framework 是否存在。

---

## 13. 现在不要做的事情

v0.2 收官阶段不要无理由继续修改 Router / Runner。

不要因为普通业务 TASK 出现 REQUEST_CHANGE 就判断 Framework 有 bug。

判断原则：

- 如果 Codex 正确发现业务代码问题 → Framework 正常；
- 如果 Router 跳过本应执行的 Hermes → Framework bug；
- 如果 PASS/APPROVE 被错误聚合成 WAITING → Framework bug；
- 如果 Agent 调用失败/结果丢失但 Framework 仍 SUCCESS → Framework bug；
- 如果业务实现不符合 TASK，被 Reviewer/Auditor 拦住 → Framework 正常。

不要重新打开已经验证完成的 Framework bug，除非新的真实证据证明回归。

---

## 14. v0.2 收官建议顺序

下一阶段建议按以下顺序进行：

### A. 冻结当前 prototype

- 确认当前代码状态；
- 跑最终全量测试；
- 保存版本快照；
- 不再随业务 TASK 任意修改。

### B. 整理仓库

目标：把当前 prototype 从“本机实验目录”整理成可维护项目。

需要考虑：

- README；
- 目录结构说明；
- 安装说明；
- 环境依赖；
- Windows 使用方式；
- TASK / REPORT 示例；
- dry-run / normal / resume 使用方式；
- Router 规则说明；
- 状态语义；
- troubleshooting；
- tests。

### C. GitHub 仓库化

整理后上传 GitHub，并建立明确版本标签，例如：

```text
v0.2.0-mvp
```

具体版本号由收官规划决定，不在本快照中强制。

### D. 固化跨项目使用方式

当前 Framework 仍主要通过 PowerShell / Python CLI 运行。

后续需要决定：

- 是否继续 CLI-first；
- 是否包装成安装命令；
- 是否提供 inbox / watcher；
- 是否做成 meta skill；
- 是否提供项目级配置；
- 是否让 Planner 直接触发 Framework。

这些属于 v0.3 / 产品化方向，不应在 v0.2 收官时一次全部扩张。

### E. v0.3 候选

可能包括：

- 更结构化 Agent verdict；
- 更稳健 Router（减少纯词表依赖）；
- 浏览器 Validator 独立复跑；
- git/worktree 任务隔离；
- task lifecycle 状态机；
- inbox / 自动发现 TASK；
- 项目配置文件；
- 更方便的启动入口；
- GitHub/PR 集成。

v0.3 需求应基于生产使用中真实出现的问题，而不是现在提前堆功能。

---

## 15. 新对话恢复协议

如果以后新建 AI Agent Framework 对话，第一条建议发送：

```text
这是 AI Agent Framework v0.2 项目的状态交接文件。请先完整读取并以它作为当前项目事实基线。不要重新讨论已经关闭的 Framework bug，也不要重新验证 TASK-001～010。当前目标是从 v0.2 MVP 已验证完成的状态继续进行收官 / GitHub 仓库化 / 后续 v0.3 规划。若新证据与交接文件冲突，以新证据为准，并明确指出冲突。
```

然后上传本文件。

如果是业务 H5 Planner 新对话，则不要直接把整个 Framework 历史重新塞进去；只需说明：

```text
项目已正式使用 AI Agent Framework v0.2。
Planner 负责生成 TASK，Framework 负责 Router → Hermes → WorkBuddy → Codex → REPORT，Planner 读取 REPORT 后规划下一任务。
Framework v0.2 MVP 已经在 TASK-001～010 真实试跑完成，后续默认视为生产工具，不再重复验证 Framework 本身。
```

---

## 16. 当前恢复锚点

若未来上下文出现“记忆涣散”，优先恢复以下事实：

```text
Framework：AI Agent Framework v0.2
状态：MVP 核心闭环已验证通过，准备收官
prototype：<PROJECT_ROOT>-prototype
正式目录：<PROJECT_ROOT>（此前未修改）
真实试跑项目：<BUSINESS_PROJECT>
Planner：ChatGPT
Executor：Hermes
Reviewer：WorkBuddy / CodeBuddy
Auditor：Codex
输入：TASK.md
输出：REPORT.md
最新真实收官观察任务：TASK-010
TASK-010：SUCCESS
Route：hermes -> workbuddy -> codex
WorkBuddy：PASS_WITH_WARNING
Codex：APPROVE
Unresolved：None identified
下一阶段：v0.2 冻结、仓库整理、GitHub 化，而不是继续证明 Framework 能不能跑
```

---

## 17. 文件定位

本文件本身应作为 AI Agent Framework 项目的长期状态文件保存。

建议最终放入 Framework 仓库，例如：

```text
docs/status/AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md
```

或保留一个稳定别名：

```text
PROJECT_STATE.md
```

建议做法：

- 日期快照文件保留历史；
- `PROJECT_STATE.md` 始终指向/更新为最新状态。

这样以后既能知道“现在在哪”，也能回溯每个阶段。

---

**快照结论：AI Agent Framework v0.2 已结束核心链路验证阶段，可以进入正式收官。**
