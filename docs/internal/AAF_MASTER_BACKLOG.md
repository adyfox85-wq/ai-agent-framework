# AAF_MASTER_BACKLOG.md

> Project: AI Agent Framework
> Document Type: **Living Long-Term Backlog / 长期问题与恢复登记**
> Established: 2026-08-27（AAF-MAINT-001-FIX-002）
> Last Updated: 2026-08-27（AAF-MAINT-003）
> Location: `docs/internal/AAF_MASTER_BACKLOG.md`

## Purpose

集中登记 AI Agent Framework 全部已确认的真实使用问题、观察项、防漂移
验证缺口、会话承接缺口、历史待恢复优化项与恢复/耐久性规则。

目标：即使任何 ChatGPT Project / conversation 丢失，只要保留
GitHub / 本地 repo / Obsidian 镜像，就不会遗忘后续仍需处理的事项。

## Long-Term Maintenance Rules（长期维护规则）

```
Authoritative Source:
  AI Agent Framework repository（本仓库，含 docs/internal/ 与 git history）

Obsidian:
  用于阅读、搜索和恢复的镜像（MIRROR ONLY，非独立权威源）

ChatGPT Project / Conversation:
  用于规划和协作，但不能作为唯一长期知识来源
```

## Status Vocabulary

仅使用以下状态：

```
OPEN
PARTIAL
OBSERVATION
SOLVED
RECOVERY_PENDING
DEFERRED
```

## Priority Vocabulary

仅使用以下优先级：

```
P0
P1
P2
P3
```

---

# 1. Real-World Usage / Usability Issues（RW）

## RW-001 — Bridge 提示音与弹窗视觉体验

| 字段 | 内容 |
|---|---|
| ID | RW-001 |
| Title | Bridge 提示音与弹窗视觉体验 |
| Category | Real-world usage / UX |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 真实使用观察 |
| Current Implementation | 现状：有提示音与确认/完成弹窗，但体验一般 |
| Remaining Gap | - 当前提示音体验一般<br>- 当前确认/完成弹窗较基础 |
| Decision | 后续与 Desktop/Tray UI 一起考虑；当前不单独开发 |
| Target | 与 Tray / Desktop UI 合并优化提示音与弹窗体验 |
| Do Not Forget | 属于体验优化，不是功能缺陷；不因美观单独重构 Bridge |

---

## RW-002 — 新用户 onboarding / 产品定位

| 字段 | 内容 |
|---|---|
| ID | RW-002 |
| Title | 新用户 onboarding / 产品定位 |
| Category | Real-world usage / Documentation |
| Status | PARTIAL |
| Priority | P2 |
| Evidence / Origin | 新用户上手路径观察 |
| Current Implementation | README / QUICKSTART / TROUBLESHOOTING 已完成主要工作（commit d97ab38） |
| Remaining Gap | 持续验证：陌生用户是否能仅凭仓库上手 |
| Decision | AAF 当前应描述为**本地 Multi-Agent Orchestration Framework / Tool**：<br>- 不是单纯 Meta Skill<br>- 不是 SaaS、IDE 或 ChatGPT 替代品<br>- 继续观察陌生用户上手情况 |
| Target | 新用户仅凭仓库可理解定位并完成 Quick Start |
| Do Not Forget | 产品定位说明要持续与 README 保持一致，防止表述漂移 |

---

## RW-003 — Bridge 自动识别与切换项目

| 字段 | 内容 |
|---|---|
| ID | RW-003 |
| Title | Bridge 自动识别与切换项目 |
| Category | Real-world usage / Bridge |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实事件：从 H5 workspace 切换回 AAF workspace 时，Bridge 因 current_workspace 不一致拒绝任务，需要人工修改 config 才能继续 |
| Current Implementation | 无自动切换；依赖人工修改 Bridge config（如 `~/.aaf-bridge/config.json` 的 current_project / current_workspace） |
| Remaining Gap | - 自动识别 TASK Workspace<br>- 新 workspace 明确确认<br>- Recent Projects<br>- 安全切换<br>- 不静默执行陌生路径 |
| Decision | 当前不实现（登记待办）；默认行为保持人工确认 |
| Target | Bridge 能自动识别 TASK 指定的 workspace，并在切换前明确确认 |
| Do Not Forget | **不静默执行陌生路径**；切换必须显式确认，安全优先 |

---

## RW-004 — Bridge 启动方式与 Windows Tray

| 字段 | 内容 |
|---|---|
| ID | RW-004 |
| Title | Bridge 启动方式与 Windows Tray |
| Category | Real-world usage / Bridge lifecycle |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实使用观察：电脑重启后 Bridge 当前不会自动恢复运行，Ctrl+Alt+A 因 Bridge 尚未启动而没有响应，用户需要重新启动 Bridge（曾需手工启动 python module；Terminal 关闭后 Bridge 停止） |
| Current Implementation | 当前电脑重启后 Bridge 不会自动启动；用户需要手工启动 python module；Terminal 关闭后 Bridge 停止 |
| Remaining Gap | 候选方向：<br>- Windows Tray<br>- 无终端后台启动<br>- Start / Restart / Exit<br>- Current Project<br>- Open Status / Logs |
| Decision | 当前不实现（登记待办） |
| Target | Bridge 能由桌面壳层或后台机制管理，常驻可管理（Tray / 后台启动 / 状态入口）；普通使用时不依赖持续打开 PowerShell / Terminal 窗口 |
| Do Not Forget | 与 RW-006 / RW-010 相关联；不做成大型独立应用 |

---

## RW-005 — Framework 执行速度与阶段耗时

| 字段 | 内容 |
|---|---|
| ID | RW-005 |
| Title | Framework 执行速度与阶段耗时 |
| Category | Observation / Performance |
| Status | OBSERVATION |
| Priority | P2 |
| Evidence / Origin | 真实 TASK-011 体感比手工流程慢 |
| Current Implementation | 各阶段（Validation / Boundary / Hermes / WorkBuddy / Codex / REPORT）已有既有执行链，但无阶段耗时可观测数据 |
| Remaining Gap | 先记录并测量各阶段耗时：<br>- Validation<br>- Boundary<br>- Hermes<br>- WorkBuddy<br>- Codex<br>- REPORT |
| Decision | 先增加可观测性，再判断性能优化；**不能为了提速直接删除质量保障阶段** |
| Target | 各阶段耗时可观测、可对比 |
| Do Not Forget | 提速不得以牺牲质量保障阶段为代价 |

---

## RW-006 — Runtime 状态可视化

| 字段 | 内容 |
|---|---|
| ID | RW-006 |
| Title | Runtime 状态可视化 |
| Category | Observation / Tooling |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实使用中无法直观看到任务当前处于哪个阶段，运行时存在明显"黑盒感"：<br>- 当前到底执行到哪一步<br>- 当前 Agent 是谁<br>- 还要多久<br>- 是否仍有活动<br>- 是否卡住<br><br>用户明确希望：可视化阶段流程、小进度条、百分比、最近活动、当前状态、停止按钮。<br>目标体验：**"看得到 → 看得懂 → 控得住"**。 |
| Current Implementation | 无统一可视化；状态分散在 task.json / run.json / REPORT |
| Remaining Gap | 未来 Runtime Status UI 应包含：<br>- 当前项目<br>- 当前 TASK<br>- 当前阶段（Validation / Boundary / Hermes / WorkBuddy / Codex / REPORT）<br>- 当前 Agent<br>- elapsed time<br>- last activity<br>- error / suspected stuck<br>- Stop Current Task<br>- overall progress indicator<br>- small progress bar<br>- estimated percentage<br><br>当前结果状态（SUCCESS / WAITING / FAILED / FRAMEWORK_ERROR）继续保持。 |
| Decision | 建议未来与 Tray / Desktop UI 合并，而不是建设大型 Web Dashboard。<br><br>**阶段状态是可靠事实**，例如：<br>Validation ✓<br>Boundary ✓<br>Hermes ✓<br>WorkBuddy ▶<br>Codex ○<br>REPORT ○<br><br>**百分比属于 estimated progress，不能伪装成精确真实剩余时间。**<br><br>第一版允许使用静态阶段权重（仅为未来实现候选，本任务不实现算法）：<br>Validation 5<br>Boundary 5<br>Hermes 45<br>WorkBuddy 20<br>Codex 20<br>REPORT 5<br><br>长期可根据真实阶段耗时统计校准权重（与 RW-005 联动）。 |
| Target | 单窗口可读的运行时状态：当前项目 / TASK / Agent / 阶段 / 进度 一眼可见 |
| Do Not Forget | 核心体验目标：<br>**看得到** → 当前项目 / TASK / Agent / 阶段 / 进度<br>**看得懂** → 中文状态 / 最近活动 / 错误 / 是否疑似卡住<br>**控得住** → Stop Task / Restart Bridge / Project Switch / Open Logs<br><br>进度百分比必须明确标注为估算值。<br>拒绝大而全的 Web Dashboard；保持轻量。 |

---

## RW-007 — Agent executable discovery reliability

| 字段 | 内容 |
|---|---|
| ID | RW-007 |
| Title | Agent executable discovery reliability |
| Category | Real-world usage / Environment |
| Status | PARTIAL |
| Priority | P2 |
| Evidence / Origin | 真实事件：Codex 升级后安装 hash 目录变化导致 command discovery 失败（TASK-011 中 `MISSING_COMMAND: codex`） |
| Current Implementation | 已通过 commit **7cbf594** 处理当前 OpenAI Codex hash-directory upgrade 场景（registry PATH 优先 + hash 目录 fallback，仅针对 codex） |
| Remaining Gap | Hermes / WorkBuddy 当前主要依赖 PATH，尚未出现同类真实故障；继续 Observation |
| Decision | 不提前建设大型通用 executable manager |
| Target | 三个 Agent executable 在当前环境可稳定发现 |
| Do Not Forget | fallback 仅针对已出现真实故障的 codex；不扩为通用 manager |

---

## RW-008 — TASK / Bridge parser compatibility

| 字段 | 内容 |
|---|---|
| ID | RW-008 |
| Title | TASK / Bridge parser compatibility |
| Category | Real-world usage / Parser |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实问题：最初 TASK 中以下单行字段出现换行格式时 Bridge 校验失败：Task ID / Task Name / Workspace。另：Planner 富文本 / Markdown 转义曾造成 marker 和文本格式风险 |
| Current Implementation | README 已提供规避方式（推荐单行字段、纯文本代码块输出 TASK）；Bridge parser 对单行格式工作正常 |
| Remaining Gap | 未来希望同时支持：<br>- `Task ID: VALUE`（单行）<br>- 字段名后一行再给 VALUE<br>- Markdown heading 形式<br>parser 代码层仍有兼容性缺口 |
| Decision | 当前不修改 parser（登记待办）；使用 README 规避方式 |
| Target | parser 兼容多种合理排版，且不受 Markdown 转义影响 |
| Do Not Forget | README 规避 ≠ 代码层已兼容；缺口仍在 |

---

## RW-009 — ChatGPT Project / Conversation disaster recovery

| 字段 | 内容 |
|---|---|
| ID | RW-009 |
| Title | ChatGPT Project / Conversation disaster recovery |
| Category | Durability / Recovery |
| Status | PARTIAL |
| Priority | P0 |
| Evidence / Origin | 长期维护原则：AAF 后续维护不能依赖某一个永久存在的 ChatGPT Project 或历史 conversation |
| Current Implementation | 已有恢复资产雏形：README、PROJECT_STATE、closing handoffs；本任务新增 Master Backlog |
| Remaining Gap | 完整 Recovery flow 需持续演练并保持资产最新：<br><br>GitHub / local repo<br>→ README<br>→ PROJECT_STATE<br>→ AAF_MASTER_BACKLOG<br>→ latest closing handoff<br>→ 创建新的 ChatGPT Project / Planner conversation<br>→ 继续维护 |
| Decision | 即使旧 ChatGPT Project 或 conversation 不存在，Framework 仍能恢复到可继续升级的状态 |
| Target | 零 ChatGPT 依赖的恢复链验证通过 |
| Do Not Forget | ChatGPT 是规划/协作界面，不是唯一长期知识来源 |

---

## RW-010 — Desktop App / Windows Program Packaging

| 字段 | 内容 |
|---|---|
| ID | RW-010 |
| Title | Desktop App / Windows Program Packaging |
| Category | Future capability / Packaging |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 长期候选方向（与 RW-004 / RW-006 / RW-014 / RW-015 相关联，见 Desktop / Runtime UX Cluster） |
| Current Implementation | 无桌面壳层；Bridge 以 python module 运行 |
| Remaining Gap | 长期候选：<br>- Tray<br>- Status Window<br>- Project selector<br>- Settings<br>- Start / Stop / Restart Bridge |
| Decision | 原则：**Desktop App ≠ 重写 AAF**。复用现有 Framework Core，增加小型桌面壳层。目标架构：<br><br>AAF Core<br>↓<br>Desktop Shell / Tray<br><br>核心执行逻辑保持独立，UI 只负责操作、状态和生命周期入口。<br>**明确不扩展到**：<br>- SaaS<br>- 多用户后台<br>- 云端管理平台<br>- Agent marketplace<br>- 无限自主循环 |
| Target | 轻量桌面壳层，不改变 Framework Core 边界 |
| Do Not Forget | 小而本地；禁止膨胀为平台 |

---

## RW-011 — Router local constraint classification incident

| 字段 | 内容 |
|---|---|
| ID | RW-011 |
| Title | Router local constraint classification incident |
| Category | Incident / Router |
| Status | SOLVED |
| Priority | P1 |
| Evidence / Origin | AAF-MAINT-001 因局部范围限制被错误路由（局部禁止修改产品代码的约束被误判为任务级 review 模式），Hermes 未执行；route 被错误定为复核类（非执行类），实际执行动作（创建 backlog / 更新 PROJECT_STATE / commit+push）全部被压制 |
| Current Implementation | 已修复：commit **457df93**（execution intent 与局部限制能够区分；206 tests passed；WorkBuddy APPROVE；Codex APPROVE；Remote Sync SUCCESS）。详见 `docs/internal/AAF-HOTFIX-ROUTER-READONLY.md` |
| Remaining Gap | 无（该 incident 已解决）；相关语义隔离问题见 RW-013 |
| Decision | **要求保留该事故历史，不因为已经解决而删除** |
| Target | 同类局部约束不再触发错误路由（已达成） |
| Do Not Forget | `.aaf/AAF-MAINT-001/` 保留为真实事故证据；不删除、不覆盖 |

---

## RW-012 — Bridge hotkey listener runtime reliability

| 字段 | 内容 |
|---|---|
| ID | RW-012 |
| Title | Bridge hotkey listener runtime reliability |
| Category | Real-world usage / Bridge |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实使用至少两次出现：<br>- Bridge 进程看似仍存在<br>- Ctrl+Alt+A 无响应<br>- 重启 Bridge 后恢复<br><br>另一次电脑重启后无响应属于 Bridge 尚未配置自动启动（见 RW-004），是**不同场景**，应分别说明 |
| Current Implementation | 无 listener 健康检测；无自恢复；README Known Limitations 已登记该 issue |
| Remaining Gap | - hotkey health<br>- listener self-recovery<br>- restart UX<br>- singleton awareness |
| Decision | 当前不实现（登记待办）；出现时安全重启 Bridge |
| Target | listener 可自检、可自恢复、重启 UX 顺畅 |
| Do Not Forget | **Bridge process 存活不能单独证明 hotkey listener 健康** |

---

## RW-013 — Router self-triggering reference trap

| 字段 | 内容 |
|---|---|
| ID | RW-013 |
| Title | Router self-triggering reference trap |
| Category | Incident / Router |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | AAF-MAINT-001-FIX-001 为描述前一次 Router incident（RW-011），在 Background 中引用 Router 自己用于分类的特殊短语，导致当前 Router 再次根据全文命中 review route，Hermes 第二次被跳过 |
| Current Implementation | Runtime Diagnose 已确认：<br>- current source loaded（Router source 正确）<br>- no stale route（route.json 非 stale）<br>- no wrong import（import path 正确）<br>- no routing truncation（TASK 在 routing 前未截断）<br>- Direct Probe reproduced the same route（与 stored route.json 一致）<br><br>根因属于 self-triggering reference trap：当前 Router 基于全文 keyword/signal 判断，任务中"讨论规则本身"和"真正发出规则要求"没有语义隔离 |
| Remaining Gap | 当前 Router 基于全文 keyword/signal 判断，"讨论规则本身"和"真正发出规则要求"没有语义隔离 |
| Decision | **本任务只登记，不修改 Router**（Framework runtime implementation 保持现状） |
| Target | Future candidate：评估结构化字段优先、section-aware routing、或其他不会被引用文本自触发的方案 |
| Do Not Forget | - 本任务及后续登记文档**不原样引用任何 Router 触发短语**，防止再次自我触发<br>- `.aaf/AAF-MAINT-001-FIX-001/` 保留为真实事故证据 |

---

## RW-014 — Task Stop / Cancel Capability

| 字段 | 内容 |
|---|---|
| ID | RW-014 |
| Title | Task Stop / Cancel Capability |
| Category | Runtime UX / Lifecycle Control |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实执行 AAF 任务过程中，用户发现 Execute 后若需要中断当前任务，现有产品没有明确的 Stop / Cancel 操作入口。当前只能借助外部进程管理方式处理，这对日常用户不友好，也容易造成状态与实际进程不一致 |
| Current Implementation | 当前 Bridge / Framework 具备任务启动与运行链，但没有正式面向用户的 Current Task Cancel 控制 |
| Remaining Gap | 未来需要设计正式取消语义，至少考虑：<br>- 停止当前 Framework runner<br>- 停止与当前 TASK 对应的 agent chain<br>- 不影响 Bridge 本身继续工作<br>- 不误伤其他独立 Hermes / WorkBuddy / Codex 会话<br>- 保留已有 .aaf 任务证据<br>- 明确记录取消后的 task lifecycle 状态<br>- UI 中提供明确的"停止当前任务"操作<br>- 防止重复点击和状态竞争<br>- 必要时提供确认步骤<br>- 能区分正常取消、执行失败和外部进程异常终止 |
| Decision | 当前先登记。后续与 Runtime Status / Tray / Desktop Shell 设计一起规划。不能仅做一个粗暴 kill-process 按钮 |
| Target | 未来 Desktop Shell / Runtime UX implementation phase |
| Do Not Forget | 用户需要的是"安全停止当前 TASK"，而不是"关闭整个 AAF"——Stop Current Task 与 Exit AAF 必须明确区分 |

---

## RW-015 — Chinese-first Desktop / Tray User Interface

| 字段 | 内容 |
|---|---|
| ID | RW-015 |
| Title | Chinese-first Desktop / Tray User Interface |
| Category | Desktop UX |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 用户明确提出：未来 AAF 如果形成桌面小程序、Tray 或 Status Window，面向人的界面最好默认使用中文 |
| Current Implementation | AAF 当前仍以 CLI、Bridge 弹窗、Markdown 报告和技术状态字段为主，尚未形成统一桌面 UI |
| Remaining Gap | 未来用户界面需要定义：<br>- 中文按钮<br>- 中文状态描述<br>- 中文错误提示<br>- 中文设置项<br>- 中文项目切换<br>- 中文任务控制<br>- 中文运行进度<br><br>底层技术字段允许继续保留：<br>SUCCESS / WAITING / FAILED / FRAMEWORK_ERROR / Hermes / WorkBuddy / Codex<br>但面向用户时应提供清晰中文表达 |
| Decision | Chinese-first。当前不因为国际化需求增加复杂语言系统。未来如确有公开用户需求，再评估中英文切换 |
| Target | Desktop Shell / Tray UX phase |
| Do Not Forget | 日志和内部协议可以继续英文，用户操作界面优先中文 |

---

## RW-016 — Duplicate Task Status UX

| 字段 | 内容 |
|---|---|
| ID | RW-016 |
| Title | Duplicate Task Status UX |
| Category | Runtime UX / Bridge |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实使用：AAF-MAINT-002 实际已经执行完成，用户再次按 Ctrl+Alt+A 提交相同 Task ID 时只收到 TASK_ALREADY_EXISTS。用户无法从弹窗判断任务到底是 RUNNING / WAITING / SUCCESS / FAILED / stale；也没有查看任务 / 查看状态 / 打开 REPORT 的入口。 |
| Current Implementation | Bridge duplicate protection 能阻止相同 Task ID 重复登记，但提示仅说明"任务已存在"。 |
| Remaining Gap | 未来 duplicate 提示应尽量显示：<br>- Task ID<br>- Current Status<br>- Current Stage<br>- Last Run Time<br>- Result<br>- REPORT 是否存在<br><br>并提供候选入口：<br>- 查看任务<br>- 查看状态<br>- 打开 REPORT<br>- 关闭提示<br><br>如任务仍在运行：显示当前阶段和 elapsed。<br>如任务已完成：明确 SUCCESS / WAITING / FAILED。 |
| Decision | 当前只登记。未来与 Desktop Shell / Runtime Status UI 合并设计。 |
| Target | 用户不需要打开 .aaf 文件夹猜任务状态。 |
| Do Not Forget | TASK_ALREADY_EXISTS 本身不是错误；真正 UX 缺口是"只告诉存在，不告诉现在是什么状态"。 |

---

## RW-017 — .aaf Runtime Artifact Git Ignore Consistency

| 字段 | 内容 |
|---|---|
| ID | RW-017 |
| Title | .aaf Runtime Artifact Git Ignore Consistency |
| Category | Repository hygiene / Runtime artifacts |
| Status | OBSERVATION |
| Priority | P3 |
| Evidence / Origin | 真实执行中 git status 长期显示 .aaf/ 为 untracked。 |
| Current Implementation | 当前 .gitignore 存在 .aaf-*/ 模式，但该模式不覆盖实际 runtime 目录 .aaf/。 |
| Remaining Gap | 评估是否应明确忽略 .aaf/，同时确认是否有任何 .aaf artifact 需要长期保留在 repo。 |
| Decision | 当前只登记，不修改 .gitignore。 |
| Target | 未来明确 runtime artifact 与 repository history 的边界。 |
| Do Not Forget | .aaf 中包含真实运行证据，不能在未确认 archive / recovery 策略前直接清理或删除。 |

---

## RW-018 — GitHub Push / Proxy Environment Reliability

| 字段 | 内容 |
|---|---|
| ID | RW-018 |
| Title | GitHub Push / Proxy Environment Reliability |
| Category | Environment / Git Operations |
| Status | OBSERVATION |
| Priority | P3 |
| Evidence / Origin | 真实维护任务中 git push 曾出现直连 GitHub TLS EOF；使用本机 Clash SOCKS5 临时代理（socks5h://127.0.0.1:7897）后 push 成功。 |
| Current Implementation | AAF Core 不管理 Git 网络代理。Git push 由执行环境完成。 |
| Remaining Gap | 观察该问题是否重复发生。 |
| Decision | 当前不把代理配置写入 Framework Core。如未来频繁复现，再考虑：documentation / environment preflight / clearer push failure guidance。 |
| Target | Git push 失败时能明确区分 Framework 故障与外部网络环境故障。 |
| Do Not Forget | 网络代理属于环境层，不要因为单次 TLS 问题扩大 AAF Core scope。 |

---

## RW-019 — Agent Review Execution Evidence Consistency

| 字段 | 内容 |
|---|---|
| ID | RW-019 |
| Title | Agent Review Execution Evidence Consistency |
| Category | Agent execution / Observability |
| Status | OBSERVATION |
| Priority | P2 |
| Evidence / Origin | AAF-MAINT-002 Hermes 报告曾描述"本机未安装 Codex CLI"，但 Framework 最终 REPORT / Agent Results 中存在真实 Codex Reviewer APPROVE。两种表述并存，环境描述不一致。 |
| Current Implementation | 最终 Framework REPORT 能保存各 Agent 结果，但不同执行者的环境描述可能不一致。 |
| Remaining Gap | 未来需要更清楚地区分：<br>- Agent CLI discovered<br>- Agent actually launched<br>- fallback / inline audit<br>- independent reviewer result<br>- environment where the check occurred |
| Decision | 当前只登记。不要据此开发 universal executable manager。 |
| Target | 用户和 Planner 能从 REPORT 判断："哪个 Agent 真正独立执行过，在哪个环境执行，是否使用 fallback。" |
| Do Not Forget | "报告里有 Codex 内容"和"本机 Codex CLI 独立执行成功"不是完全相同的事实，未来应避免模糊表述。 |

---

## 1.1 Desktop Shell Principle（桌面壳层设计原则）

> 本原则**不是新的产品功能条目**，
> 用于约束 RW-004、RW-006、RW-010、RW-012、RW-014、RW-015、RW-016 的未来实现。

Future AAF Desktop Shell 的定位是：

```
现有 AAF Core
+
轻量 Windows 操作与状态外壳
```

它未来可以承担：

- Bridge 后台运行入口
- Current Project
- Current Task
- 当前执行阶段
- elapsed time
- last activity
- agent 状态
- error / stuck 状态
- Stop / Cancel Current Task
- Restart Bridge
- Project switch
- Open Logs
- Settings
- Exit AAF

但 Desktop Shell 不替代：

- Router
- Runner
- Lifecycle
- Boundary
- Session
- Agent adapters
- TASK / REPORT protocol

### 1.1.1 防漂移边界（Anti-Drift Boundary）

未来桌面化**不能自动扩展**为：

- SaaS
- Web management platform
- multi-user backend
- account system
- cloud synchronization platform
- Agent marketplace
- plugin marketplace
- remote team control center
- autonomous infinite Agent loop

除非未来出现独立、明确的新决策。

### 1.1.2 目标架构（Target Architecture）

```
AAF Core
↓
Desktop Shell / Tray
```

核心执行逻辑保持独立，
UI 只负责操作、状态和生命周期入口。
Desktop App ≠ 重写 AAF。

---

## 1.2 Desktop / Runtime UX Cluster（问题簇）

包含以下独立条目：

- RW-004 — Bridge 后台启动 / Tray
- RW-006 — Runtime 状态可视化
- RW-010 — Desktop App / Windows Program Packaging
- RW-012 — Hotkey listener runtime reliability
- RW-014 — Task Stop / Cancel Capability
- RW-015 — Chinese-first Desktop UI
- RW-016 — Duplicate Task Status UX

各条目**保留各自独立 ID**。
Cluster 只是帮助未来统一设计，
**不能把各问题合并**后丢失原有 Evidence / Status / Priority。

---

# 2. Anti-Drift（BND）

## BND-001 — Planner-layer Anti-Drift Validation

| 字段 | 内容 |
|---|---|
| ID | BND-001 |
| Title | Planner-layer Anti-Drift Validation |
| Category | Anti-Drift / Governance |
| Status | PARTIAL |
| Priority | P2 |
| Evidence / Origin | 防漂移原则：suggestion 不得自动成为 requirement |
| Current Implementation | v0.3 Framework 层已有：<br>- PROJECT_SCOPE<br>- Boundary Check<br>- warning-first<br>- suggestion 不自动成为项目要求<br>- 不自动扩大 scope<br>- 不自动写 backlog<br>- 不自动产生下一 TASK |
| Remaining Gap | ChatGPT Planner 长期对话中仍需验证：<br>- context compression<br>- weighting change<br>- accumulated requirements<br>- model tendency<br><br>是否会导致：<br>- 思路漂移<br>- scope creep<br>- 历史决定遗忘<br>- suggestion 被误升级成 requirement |
| Decision | 必须明确：**Framework 层完成，不等于 Planner conversation 层已经完全解决** |
| Target | Planner 长期对话中思路漂移与 scope creep 可被识别并控制 |
| Do Not Forget | Framework 层机制不能替代 Planner 层验证；持续观察 |

---

# 3. Session Continuity（CTX）

## CTX-001 — Context Length / Conversation Rollover UX

| 字段 | 内容 |
|---|---|
| ID | CTX-001 |
| Title | Context Length / Conversation Rollover UX |
| Category | Session continuity / UX |
| Status | PARTIAL |
| Priority | P1 |
| Evidence / Origin | 真实需求：ChatGPT conversation 过长需要无遗失承接 |
| Current Implementation | v0.3 已有：<br>- explicit rollover<br>- SESSION_SUMMARY.md<br>- NEXT_SESSION_START.md<br>- bounded recent context |
| Remaining Gap | 用户真正希望实现：<br>1. ChatGPT conversation 接近过长时获得提醒；<br>2. 整理当前阶段状态；<br>3. 生成完整承接材料；<br>4. 引导进入新的 conversation；<br>5. 新 conversation 可直接继续；<br>6. 不遗失：<br>   - 当前状态<br>   - 已完成 TASK<br>   - 未完成问题<br>   - 边界<br>   - 决策<br>   - 下一步 |
| Decision | 原则：不做 infinite memory；不自动无限生成会话 |
| Target | 一次显式 rollover 完成 1-6 的完整承接体验 |
| Do Not Forget | 承接材料须可被新 conversation 直接读取并继续 |

---

# 4. Historical Recovery（HIST）

## HIST-001 — Historical Framework Optimization Set Recovery

| 字段 | 内容 |
|---|---|
| ID | HIST-001 |
| Title | Historical Framework Optimization Set Recovery |
| Category | Historical recovery |
| Status | RECOVERY_PENDING |
| Priority | P2 |
| Evidence / Origin | 用户记得早期曾讨论过一组约 10 个 Framework 优化项 |
| Current Implementation | 无（尚未恢复） |
| Remaining Gap | 当前没有足够可靠证据恢复其精确原文 |
| Decision | 必须保留其"存在"这一事实，但**不能根据今天的问题、模型常识或推测重新凑成十项**（本任务未自行重构） |
| Target | 记录：`Known historical optimization set exists; exact original list not yet recovered.` |
| Do Not Forget | 后续候选恢复来源：<br>- old handoffs<br>- PROJECT_STATE history<br>- ChatGPT exported conversations<br>- Obsidian notes<br>- local Markdown records |

---

# 5. Recovery / Durability（恢复与耐久性）

## 5.1 长期恢复资产

以下资产是 Framework 长期维护的恢复链（按读取顺序）：

```
1. README
2. PROJECT_STATE（docs/internal/PROJECT_STATE.md）
3. AAF_MASTER_BACKLOG（docs/internal/AAF_MASTER_BACKLOG.md）
4. latest closing handoff（docs/internal/handoffs/）
5. git history
```

## 5.2 角色与权威关系

```
Repository（GitHub / local repo）:
  authoritative source —— 唯一权威长期知识源

ChatGPT（Project / conversation）:
  planner / discussion interface —— 用于规划和协作

Obsidian（D:\AdyAI\Obsidian-Vault\AI Agent Framework\）:
  human-readable mirror and recovery layer —— 用于阅读、搜索和恢复
```

## 5.3 ChatGPT 丢失后的恢复原则

即使旧 ChatGPT Project 或 conversation 不存在：

```
GitHub / local repo
→ README
→ PROJECT_STATE
→ AAF_MASTER_BACKLOG
→ latest closing handoff
→ 创建新的 ChatGPT Project / Planner conversation
→ 继续维护
```

Framework 仍能恢复到可继续升级的状态（见 RW-009）。

## 5.4 Obsidian 镜像政策

- Obsidian 中的 AAF 文档是 **MIRROR ONLY** 镜像。
- 镜像文件顶部声明来源与"MIRROR ONLY"。
- 不将镜像作为独立权威版本维护。
- 镜像由维护任务显式建立；**不开发自动同步程序或 Obsidian plugin**。

---

# 6. Update Rules（更新规则）

1. 本文件是 **Living** 文档，随真实证据持续更新。
2. 以后任何被正式确认"稍后处理"的问题，**必须进入 Master Backlog 才算长期登记完成**。
3. 新条目使用本文件规定的 Status / Priority 词汇，禁止自造状态。
4. 每个正式条目至少包含：ID / Title / Category / Status / Priority /
   Evidence / Origin / Current Implementation / Remaining Gap / Decision /
   Target / Do Not Forget。
5. 登记未来功能方向时必须同时写明边界（不做哪些），防止范围膨胀。
6. 已解决事故（SOLVED）保留历史记录，不删除、不覆盖。
7. 描述 Router 相关事件时，**不原样引用任何 Router 触发短语**，
   防止全文信号匹配再次自我触发。
8. **Before planning new AAF work: FIRST READ this file.**
9. 事故证据目录 `.aaf/AAF-MAINT-001/` 与 `.aaf/AAF-MAINT-001-FIX-001/`
   保留为真实历史证据，不删除、不覆盖。

---

# 7. Summary（当前登记总览）

| ID | Title | Status | Priority |
|---|---|---|---|
| RW-001 | Bridge 提示音与弹窗视觉体验 | OPEN | P2 |
| RW-002 | 新用户 onboarding / 产品定位 | PARTIAL | P2 |
| RW-003 | Bridge 自动识别与切换项目 | OPEN | P1 |
| RW-004 | Bridge 启动方式与 Windows Tray | OPEN | P1 |
| RW-005 | Framework 执行速度与阶段耗时 | OBSERVATION | P2 |
| RW-006 | Runtime 状态可视化 | OPEN | P1 |
| RW-007 | Agent executable discovery reliability | PARTIAL | P2 |
| RW-008 | TASK / Bridge parser compatibility | OPEN | P1 |
| RW-009 | ChatGPT Project / Conversation disaster recovery | PARTIAL | P0 |
| RW-010 | Desktop App / Windows Program Packaging | OPEN | P2 |
| RW-011 | Router local constraint classification incident | SOLVED | P1 |
| RW-012 | Bridge hotkey listener runtime reliability | OPEN | P1 |
| RW-013 | Router self-triggering reference trap | OPEN | P1 |
| RW-014 | Task Stop / Cancel Capability | OPEN | P1 |
| RW-015 | Chinese-first Desktop / Tray User Interface | OPEN | P2 |
| RW-016 | Duplicate Task Status UX | OPEN | P1 |
| RW-017 | .aaf Runtime Artifact Git Ignore Consistency | OBSERVATION | P3 |
| RW-018 | GitHub Push / Proxy Environment Reliability | OBSERVATION | P3 |
| RW-019 | Agent Review Execution Evidence Consistency | OBSERVATION | P2 |
| BND-001 | Planner-layer Anti-Drift Validation | PARTIAL | P2 |
| CTX-001 | Context Length / Conversation Rollover UX | PARTIAL | P1 |
| HIST-001 | Historical Framework Optimization Set Recovery | RECOVERY_PENDING | P2 |
