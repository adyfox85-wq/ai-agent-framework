# AAF_MASTER_BACKLOG.md

> Project: AI Agent Framework
> Document Type: **Living Long-Term Backlog / 长期问题与恢复登记**
> Established: 2026-08-27（AAF-MAINT-001-FIX-002）
> Last Updated: 2026-08-28（AAF-v0.4-TASK-005-B-FIX-001 — §5.4 更新：Obsidian Conversation Handoff Pilot 验证完成，PILOT / EXPERIMENTAL → **VERIFIED**；此前更新：AAF-MAINT-HANDOFF-001 — §5.2/§5.4 更新：Obsidian 双角色模型 + GitHub/Obsidian 分工规则）
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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Current Implementation | Phase B（AAF-v0.4-TASK-002，commit 6a9814d，2026-08-27 真实 Windows 验收 PASS）已交付：pythonw 无控制台后台启动（scripts/start_bridge.pyw）+ Tray skeleton（打开状态 / 重启 Bridge / 退出 AAF，ctypes Shell_NotifyIconW 零第三方依赖）+ 单实例 mutex + restart 交接。普通使用不再依赖持续打开 PowerShell / Terminal。仍无开机自动启动。 |
| Remaining Gap | 候选方向（Phase B 已覆盖项不再列为缺口）：<br>- 开机自动启动（autostart，未实现）<br>- Current Project 切换 / Open Status 增强 / Open Logs 文件级运行日志（未实现）<br>- 健康自恢复（见 RW-012，未实现） |
| Decision | 当前不实现（登记待办） |
| Target | Bridge 能由桌面壳层或后台机制管理，常驻可管理（Tray / 后台启动 / 状态入口）；普通使用时不依赖持续打开 PowerShell / Terminal 窗口 |
| Do Not Forget | 与 RW-006 / RW-010 相关联；不做成大型独立应用 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Current Implementation | Phase B（AAF-v0.4-TASK-002，commit 6a9814d）已新增 hotkey health 判定：`classify_bridge_health()`（listener registered + loop alive → OK / DEGRADED），每 5s 轮询，Tray 图标 / Tooltip 反映健康（IDI_APPLICATION ↔ IDI_WARNING）；FIX-001 真实 GUI 验收中健康显示正常（含 1409 冲突路径行为正确）。仍无 listener 自恢复；README Known Limitations 已登记该 issue。 |
| Remaining Gap | - listener self-recovery（自恢复，未实现）<br>- hotkey health（已部分覆盖：OK / DEGRADED 检测 + Tray 反映，无自动修复）<br>- restart UX（已有 Tray 重启入口，Phase B 已提供）<br>- singleton awareness（已有单实例 mutex，Phase B 已提供） |
| Decision | 当前不实现（登记待办）；出现时安全重启 Bridge |
| Target | listener 可自检、可自恢复、重启 UX 顺畅 |
| Do Not Forget | **Bridge process 存活不能单独证明 hotkey listener 健康** |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

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
| Evidence / Origin | 真实维护任务中 git push 曾出现直连 GitHub TLS EOF；使用本机 Clash SOCKS5 临时代理（socks5h://127.0.0.1:7897）后 push 成功。<br><br>2026-08-27 复现（AAF-MAINT-003）：直连 TLS EOF 再次出现；本次 socks5h://127.0.0.1:7897 模式不通（curl 000），同端口 HTTP 代理模式 http://127.0.0.1:7897 可用并 push 成功。 |
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

## RW-020 — Dead Runner / Orphaned RUNNING State Detection

| 字段 | 内容 |
|---|---|
| ID | RW-020 |
| Title | Dead Runner / Orphaned RUNNING State Detection |
| Category | Runtime Reliability / Runtime Observability |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | AAF-v0.4-TASK-001-FIX-003 real incident, 2026-08-27。任务进入 WORKBUDDY 阶段后（Hermes 已完成）：task.status=RUNNING、stage=WORKBUDDY、agent=workbuddy、last_activity_at 停止更新、workbuddy_result.md 从未生成、WorkBuddy 进程已不存在、Framework runner 进程已不存在、Bridge 进程已不存在、REPORT.md 未生成；task.json 长时间保持 RUNNING / WORKBUDDY，用户无任何提示只能继续等待。<br><br>后续通过 Framework resume 恢复：复用 Hermes result → WorkBuddy PASS → Codex APPROVE → REPORT → SUCCESS / COMPLETED。恢复机制有效，但 **Dead Runner Detection 缺失**。<br><br>2026-08-27 再次真实复现（AAF-v0.4-TASK-004 Phase D）：实现与 E2E 全部完成后（.aaf/AAF-v0.4-TASK-004/REPORT.md 已生成，mtime 2026-08-27 20:03:04），canonical task.json 仍残留 RUNNING / HERMES（started_at = last_activity_at = updated_at = 2026-08-27T19:07:15，不再推进）；2026-08-27 20:18:33 process check（AAF_TASK004_PROCESS_CHECK.txt）：无任何相关 TASK-004 runner 进程、Bridge 进程亦不存在；canonical RUNNING 未被自动对账 / 回收（该 run 的 runner 进程在 E2E 前由 cleanup.py 清理，task.json 只读保留未改）。<br><br>Phase D UI suspected-stuck（bridge/stuck.py，仅观察提示）**不解决 RW-020**：它只提示「任务可能已停滞」，不做 ownership / process liveness 检测、不做 canonical 对账；RW-020 完整协议（liveness 跟踪、staleness + artifact expectation、Resume / Diagnostics / Resolve UX）仍未实现。 |
| Problem | RUNNING 目前只表达 lifecycle state，不能证明 execution owner / runner / 当前 agent 仍存活。 |
| Desired Behavior | 未来 AAF Runtime Health / Desktop Shell 应区分 **Lifecycle State** 与 **Runtime Health**。至少检测可疑组合：task.status=RUNNING + runner ownership/process missing + 当前 agent process missing + last_activity_at stale + expected result artifact missing，并提示「任务可能已异常中断」。潜在用户动作：Resume Task / View Diagnostics / Resolve or Mark Failed（通过权威 lifecycle 路径）。 |
| Important Boundary | Runtime Health detection **不得**允许 Desktop Shell / UI 独立写入权威 terminal task state。例：canonical lifecycle=RUNNING、runtime health=PROCESS_MISSING / STALE、UI=warning only；Terminal authority 保持 Core / Lifecycle（遵循既有 Safe Cancel / recovery 架构）。 |
| Current Implementation | 无 runtime health 检测；RUNNING 无 liveness 语义。 |
| Remaining Gap | - runner ownership / process liveness tracking<br>- agent process liveness<br>- last_activity_at staleness threshold<br>- expected artifact expectation (result file) check<br>- 「任务可能已异常中断」warning 呈现<br>- Resume / Diagnostics / Resolve UX（warning only，不改 terminal authority） |
| Decision | 当前只登记（本维护任务不实现）。近期待办 P1。 |
| Target | Desktop Shell（或等价 Runtime Health 层）能区分 lifecycle 与 health；stale / dead runner 能预警；恢复走既有 resume / authoritative lifecycle。 |
| Related | RW-005（阶段耗时）、RW-006（Runtime 状态可视化）、RW-012（hotkey listener runtime reliability）、RW-014（Task Stop / Cancel） |
| Do Not Forget | **RUNNING ≠ alive**。运行时健康与生命周期终态权威必须分离；UI 只能 warning，不能写终态。 |

---

## RW-021 — Bridge Restart / Exit Completion Notification Continuity

| 字段 | 内容 |
|---|---|
| ID | RW-021 |
| Title | Bridge Restart / Exit Completion Notification Continuity |
| Category | Bridge lifecycle / Runtime UX / Completion notification |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | AAF-v0.4-TASK-002-FIX-001 real Windows validation, 2026-08-27。真实验收中主动执行了 Bridge Restart / Exit / restart：Framework runner / validation task 可以继续运行并最终生成 SUCCESS REPORT，但启动该 task 的原 Bridge instance 被 Restart / Exit 后，新 Bridge instance 不会自动恢复原 launcher wait-thread / completion callback，用户没有收到原有「任务完成」提示 / Planner Handoff copy action，只能手工发现 REPORT.md。<br><br>2026-08-27 再次复现（AAF-v0.4-TASK-003）：Phase C E2E 过程中 Bridge 被正常切换/重启后，runner / task 最终完成并产生 REPORT，但用户未收到 completion notification / Planner Handoff copy action（与既有登记一致，仅补充事实，未重复新建 issue）。<br><br>2026-08-27 第三次真实复现（AAF-v0.4-TASK-004 Phase D）：Phase D 真实 Windows E2E 全链路完成后，最终 REPORT 已成功生成（.aaf/AAF-v0.4-TASK-004/REPORT.md，SUCCESS，mtime 20:03:04），但 E2E 流程中 Bridge 经历 Exit / Restart，用户未收到最终 completion window / Planner Handoff copy action，只能从文件系统手工取回 REPORT.md（与既有登记一致，仅补充事实，未重复新建 issue）。 |
| Scenario | Bridge instance A 启动 Framework task → Framework runner 独立继续运行 → Bridge A 被 Restart / Exit → Bridge instance B 启动 → runner 最终正常完成并生成 REPORT → Bridge B 不持有原 launcher completion callback → 用户没有收到完成通知 / Planner Handoff copy action |
| Current Implementation | Launcher completion callback / wait-thread 属原 Bridge process 内存；Bridge restart 后新 instance 不会重新关联旧 in-flight runner。 |
| Problem | Framework execution success 和用户 completion notification 是两个不同事实：REPORT 已成功生成 ≠ 用户一定收到完成提示。任务产物完整（canonical task / REPORT 最终 SUCCESS），但用户侧 notification continuity 丢失。 |
| Not RW-020 | RW-020 = RUNNING 状态残留，但 runner / agent 已死亡（Dead Runner / Orphaned RUNNING）。本问题 = runner 仍然存活并成功完成，但 Bridge 换代后 completion notification continuity 丢失。两者是不同的失败模式，不合并、不互相覆盖。 |
| Important Boundary | 这不是 task lifecycle corruption：canonical task / REPORT 可以最终 SUCCESS，缺失的是 Bridge-side observation / reattachment / notification continuity。不允许 UI 自行修改 canonical terminal state。 |
| Remaining Gap | - Bridge restart 后发现 in-flight task<br>- 完成后恢复 notification<br>- Planner Handoff / REPORT availability 提示<br>- 与未来 launch ownership / persistent registry 架构保持一致（设计 §6B.11–§6B.16 Bridge launch registry / §15 Phase E）<br>- 不重复实现 Core lifecycle |
| Decision | 当前只登记。不重开 Phase B。不得在本任务实现 reattachment。 |
| Target | Bridge 换代（Restart / Exit / relaunch）后仍能发现 in-flight task，并在其完成后恢复 completion notification / Planner Handoff / REPORT availability 提示。 |
| Related | RW-020（明确区分，见上）、RW-014（Task Stop / Cancel）、RW-016（Duplicate Task Status UX）；设计文档 `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md` §6B（launch registry / ownership 恢复协议）、§7（Bridge Background Runtime）、§15（Phase E Safe Cancel Lifecycle）——仅引用未来架构关系，不提前实现 Phase E |
| Do Not Forget | Framework execution success 和用户 completion notification 是两个不同事实。REPORT 已成功生成 ≠ 用户一定收到完成提示。 |

---

## RW-022 — Framework Final Status Aggregation: PASS_WITH_WARNING + APPROVE + Blocking NONE → WAITING

| 字段 | 内容 |
|---|---|
| ID | RW-022 |
| Title | Framework Final Status Aggregation: PASS_WITH_WARNING + APPROVE + Blocking NONE → WAITING |
| Category | Framework lifecycle / Report aggregation / Planner handoff semantics |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | AAF-v0.4-TASK-003 real execution, 2026-08-27。最终 REPORT 顶部 Current Status = WAITING，但：Hermes implementation SUCCESS、Tests 284 passed、WorkBuddy PASS_WITH_WARNING（blocking rework: NONE）、Codex APPROVE（Blocking Issues: NONE）、Scope Leakage: NONE、Remote Sync: SYNCED、Codex Recommended Phase C Status = COMPLETE。<br><br>同类顶部 WAITING 先前已出现于 AAF-v0.4-TASK-002（Phase B）REPORT（当时 Codex closure review 在 REPORT 生成时点尚未完成，属可解释实例）；Phase C 为更干净的反例：全部 Agent 均已完成且无 blocking，顶部仍聚合为 WAITING。 |
| Observed Behavior | - Hermes implementation success（284 passed）<br>- WorkBuddy PASS_WITH_WARNING（无 blocking rework）<br>- Codex APPROVE / Blocking Issues NONE<br>- Scope Leakage NONE / Remote Sync SYNCED<br>- 但最终 REPORT 顶部 Current Status = WAITING |
| Problem | Framework final status aggregation 疑似把 warning / unresolved 文本段当作 blocking 处理：即使 reviewer 明确报告 no blocking rework / no blocking issues，只要存在非阻断 warning 文本，顶部状态仍被聚合为 WAITING。WAITING 因此无法表达「确实需要后续处理」与「有非阻断 warning 的 SUCCESS」的区别，会误导 Planner / user 认为需要干预。 |
| Desired Behavior | Final task status aggregation 应区分：<br>A. Blocking rework：FAIL / REQUEST_CHANGE / unresolved blocking issue / execution failure<br>B. Non-blocking warning：PASS_WITH_WARNING / informational warning / recommendation / documentation blemish<br>当最终 reviewer 明确 APPROVE 且 blocking issues = NONE 时，非阻断 warning 不应自动强制顶部 WAITING。目标：Planner / user 能区分「SUCCESS with warnings」与「WAITING（确实需要后续处理）」。 |
| Important Boundary | 本登记不修改 lifecycle semantics、不修改 task terminal state、不重写历史 REPORT；aggregation fix 属 Framework Core 变更，须由 Planner 立项，不在此登记任务中实现。 |
| Current Implementation | 无；最终 REPORT 顶部状态由 Framework aggregation 生成，当前将非阻断 warning 亦聚合为 WAITING。 |
| Remaining Gap | Framework REPORT aggregation 层需区分 blocking / non-blocking 类别，并据此决定顶部状态（属 Framework Core 变更）。 |
| Decision | 当前只登记（本 closure sync 任务不实现 aggregation fix）。 |
| Target | 最终 REPORT 顶部状态：SUCCESS（含 PASS_WITH_WARNING 且无 blocking）≠ WAITING（确实需要后续处理）。WAITING 应表达「需要后续处理 / 尚未闭环」，而不是「存在任意 warning 文本」。 |
| Related | RW-019（Agent review evidence consistency）、RW-021（completion notification continuity，同为 REPORT 生成 ≠ 用户闭环的语义区分）；AAF-v0.4-TASK-002（Phase B）为同现象早期实例 |
| Do Not Forget | 本次顶部 WAITING 不是 Phase C implementation failure；不得据此重开 Phase C、不得改写历史 REPORT、不得手动改写 task terminal state。 |

---

## RW-023 — E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop

| 字段 | 内容 |
|---|---|
| ID | RW-023 |
| Title | E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop |
| Category | Validation orchestration / GUI automation / test harness |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | AAF-v0.4-TASK-004（Phase D）真实 Windows E2E，2026-08-27（.aaf/AAF-v0.4-TASK-004/e2e_phase_d.py）。GUI E2E 使用**固定** validation Task ID：`AAF-v0.4-TASK-004-E2E`（脚本常量 TASK_ID，第 46 行）。重复 validation 时驱动自身预删 active task 文件与证据目录（`TASK_FILE.unlink()` + `shutil.rmtree(OUT_DIR)`，注释明确为「清理陈旧产物…避免 TASK_ALREADY_EXISTS / 误报」）；热键触发走 attempt 1..3 重试循环，并对「任务已在执行」（duplicate guard 弹窗）等 blocker 弹窗反复关闭后重试。本次运行 attempt=1 即成功（未出现真实 destructive loop），但代码路径完整具备：固定 ID 复用 → duplicate guard 正确拒绝 → automation 仍可能继续重开 Bridge 菜单 / 状态窗口 / 重试热键 → 用户看到鼠标 / 焦点被抢占；同时 `rmtree(OUT_DIR)` 使同一 E2E task 的旧证据被覆盖（.aaf/AAF-v0.4-TASK-004-E2E/ 仅保留最后一次运行产物），artifact / report provenance 混淆。 |
| Problem | GUI E2E 使用固定 validation Task ID，重复验证时：duplicate guard 正确拒绝重复（预期行为），但 automation 可能继续 GUI loop（重开 Bridge menu / status window / re-trigger hotkey）；用户看到 mouse/focus hijacking；artifact/report provenance 变得模糊；同一 E2E task 证据可能被覆盖 / 重写。 |
| Desired Behavior | 每次 GUI E2E 应：使用**唯一** validation Task ID（如时间戳 / 运行号后缀），或检测到已完成 validation 后**安全跳过**；automation 必须有明确终止条件；duplicate rejection 后不得继续 GUI loop。 |
| Current Implementation | Phase D E2E 脚本 e2e_phase_d.py 当前用固定 ID + 预删陈旧产物 + 有限重试（attempt ≤ 3）规避；无唯一 ID 机制、无「已完成则跳过」机制。 |
| Remaining Gap | - 唯一 validation Task ID 生成<br>- 已完成 validation 检测与安全跳过<br>- automation 明确终止条件<br>- duplicate rejection 后停止 GUI loop |
| Decision | 本任务只登记，不实现修复（E2E orchestration 属 test harness 改进，须由 Planner 立项）。 |
| Target | 重复 GUI E2E 验证不会产生 duplicate trigger / GUI loop / 证据覆盖。 |
| Related | RW-016（Duplicate Task Status UX——面向最终用户的 duplicate 提示状态缺口，属产品 UX，非测试 harness 编排，不合并）；RW-019（Agent review execution evidence consistency——重复验证证据 provenance 的相邻观察）。 |
| Do Not Forget | duplicate guard 本身正确拒绝是**预期行为**；问题在 harness 复用固定 ID + 无终止条件导致的 loop 与证据覆盖，不在 Framework lifecycle。 |

---

## RW-024 — Completion Dialog Copy Report UX（复制报告二次弹窗 + Z 序问题）

| 字段 | 内容 |
|---|---|
| ID | RW-024 |
| Title | Completion Dialog Copy Report UX（复制报告后二次弹窗 + Z 序问题） |
| Category | Runtime UX / Bridge / Completion dialog |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 用户明确反馈（2026-08-27，Phase D 期间）。当前行为（bridge/main.py `_copy_last_report()`，line 405–420）：任务完成 → 弹出第一个完成窗口 → 点击「复制报告」→ `ui.show_info("报告已复制", …)` 再弹出第二个提示窗口 → 第二窗口可能落在第一个窗口后面 → 点确定后两个窗口一起关闭。 |
| Problem | 完成通知被拆成两个 modal：复制动作触发第二个弹窗，与主完成窗口存在 Z 序竞争；用户看到两个窗口叠在一起，点确定后两个一起关闭。 |
| Desired Behavior | 任务完成 → 只保留一个完成窗口。按钮：[复制报告] [关闭]。点击「复制报告」：复制到剪贴板、不弹第二个 modal、不关闭主完成窗口、可在原窗口显示轻量反馈「已复制 ✓」、可重复复制；只有主动点击「关闭」才关闭完成窗口。 |
| Current Implementation | 完成时弹主完成窗口；点「复制报告」另弹提示窗（show_info），两窗叠置；点确定后两窗一起关闭。 |
| Remaining Gap | 单窗 UX 改造：合并按钮、就地反馈、关闭语义唯一。 |
| Decision | 本任务只登记，不实现。 |
| Target | 完成通知单窗口：复制不弹新 modal、不关主窗、原地轻量反馈；仅「关闭」按钮关闭。 |
| Related | 与 RW-021（completion notification continuity——Bridge 换代后「通知是否送达」的连续性缺口）**明确区分**：RW-024 是「通知窗口自身交互」的 UX 缺陷；与 RW-023（E2E orchestration）无关；与 RW-016（duplicate 状态 UX）无关。 |
| Do Not Forget | 不合并到 RW-021 / RW-016 / RW-023；属独立 completion dialog UX 条目。 |

---

## RW-025 — Session Continuity Clock Flake（test_first_rollover_generates_files 秒级时钟边界）

| 字段 | 内容 |
|---|---|
| ID | RW-025 |
| Title | Session Continuity Clock Flake（test_first_rollover_generates_files 秒级时钟边界） |
| Category | Tests / Session Continuity |
| Status | OPEN |
| Priority | P3 |
| Evidence / Origin | AAF-MAINT-CONTEXT-001 全量跑测观察（2026-08-28）：`tests/test_session_continuity.py::test_first_rollover_generates_files` 偶发失败——`session_id()` 使用 `datetime.now()`，两次调用落在不同秒即失败；全量连跑 3 次仅 1 次出现，隔离复跑通过；该文件未被 AAF-MAINT-CONTEXT-001 / FIX-001 改动 |
| Problem | 秒级时钟边界 flake：同一测试内两次取当前时间跨秒 → 断言失败；属测试环境问题，非产品缺陷 |
| Current Implementation | 无（未修复；本任务明确不处理，仅登记） |
| Remaining Gap | 需要 freeze / monotonic 时钟或跨秒容错断言 |
| Decision | 仅登记为后续维护项，不实现（AAF-MAINT-CONTEXT-001-FIX-001 范围外） |
| Target | 后续维护任务引入确定性时间（freeze / monotonic）后关闭 |
| Do Not Forget | 修复时不得改变 session rollover 语义；与产品行为无关，纯测试时钟边界 |

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

## CTX-002 — TASK / Stage Prompt / REPORT Context Bloat（层层全文叠加）

| 字段 | 内容 |
|---|---|
| ID | CTX-002 |
| Title | TASK / Stage Prompt / REPORT Context Bloat（eager full-content chaining） |
| Category | Framework protocol / Context 管理 |
| Status | SOLVED（2026-08-28，AAF-MAINT-CONTEXT-001 交付） |
| Priority | P1 |
| Evidence / Origin | 真实运行观察：Hermes → WorkBuddy → Codex 层层全文叠加——WorkBuddy prompt 嵌入 Hermes narrative 全文，Codex prompt 再嵌入 Hermes + WorkBuddy 全文；REPORT 再复制整份 Original Task 与全部 Agent 全文。同一信息在 prompt / REPORT 中重复 3–5 次 |
| Current Implementation | **Stage Context Packet 协议（reference-based / lazy-loading）**：<br>- 正式 Anti-Bloat Policy：`docs/internal/AAF_TASK_EXECUTION_POLICY.md`<br>- Compact TASK Schema：`templates/TASK.md`（TASK = current delta）<br>- 下游 prompt 只接收 TASK 引用 + 结构化摘要（`<agent>_result.json`）+ changed files / commit / evidence 路径；narrative 全文按需读取<br>- `context_manifest.json`：TASK snapshot（`TASK.snapshot.md`，immutable）/ stage artifacts path+hash 可追溯引用（`check_references` 完整性检查）<br>- REPORT `## Original Task` 全文 → `## Task Reference`（Task ID / Snapshot Path / Hash）+ `## Remote Sync`（Commit Sync / Tracked Working Tree / Task Remote Sync）<br>- Semantic Coverage Guard（`verify_semantic_coverage`）：压缩是去重，不是删约束<br>- Context size 每 stage 可观测（chars/bytes + embedded/referenced counts）<br>- 测量证据：同一 fixture（固定 workspace 路径）old full-chain 26,211 chars → new packet 5,379 chars（-79.5%，embedded=0，referenced=1/2；复算来源 tests/test_context_integrity.py test_context_size_fixture_exact_numbers；历史 25,609→3,301 / 26,191→3,585 为 superseded 初算值）<br>- Structured summary 契约（FIX-002）：`AAF_STRUCTURED_RESULT_BEGIN/END` JSON 块 + schema validation；findings/warnings 未提取 → null（UNKNOWN），不伪装为 []；narrative/JSON 一致性 guard（W1/W2/W3 → warnings 不得为 []）<br>- Anti-Regression 测试：`tests/test_context_compaction.py`（23 项）+ `tests/test_context_integrity.py`（22 项） |
| Remaining Gap | 无 blocking gap。Guard 是确定性子串检查；改写措辞的语义等价性依赖 WorkBuddy 独立验证（设计如此，非缺陷） |
| Decision | 新协议作为默认路径；旧目录自动 legacy fallback（Backward Compat） |
| Target | 已达成：重复输入明显下降、零信息丢失、独立验证逻辑与安全边界不变 |
| Do Not Forget | 不得恢复 eager full-content chaining；Anti-Bloat 规则见 Policy §12 反回归 guard |

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
  working knowledge / conversation handoff layer（PILOT / EXPERIMENTAL，2026-08-28 建立）
  + human-readable mirror（MIRROR ONLY）—— 阅读、搜索、恢复与工作记录（详见 §5.4）
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

## 5.4 Obsidian 政策（2026-08-28 更新：双角色 + 分工规则，AAF-MAINT-HANDOFF-001）

Obsidian 中的 AAF 文档承担两种角色：

1. **MIRROR（既有政策）**：repo 正式资产的镜像 —— MIRROR ONLY，顶部声明来源；
   不作为独立权威版本维护；镜像由维护任务显式建立；
   **不开发自动同步程序或 Obsidian plugin**。
2. **Working Knowledge / Conversation Handoff 层（VERIFIED，2026-08-28 由
   AAF-v0.4-TASK-005-B-FIX-001 验证）**：
   working knowledge、discussion、draft、conversation handoff、stage retrospective、
   未定 / 未提升决策、每日项目笔记。当前 Pilot 只含一个入口文件
   `CURRENT_HANDOFF.md`；不建复杂结构 / plugin / 自动化；
   **验证完成**（验证 = 新 Planner 对话读取 CURRENT_HANDOFF 后准确恢复项目状态——
   005-B-FIX-001 会话即该新 Planner 对话，经 CURRENT_HANDOFF + PROJECT_STATE
   恢复项目状态成功，PILOT / EXPERIMENTAL → VERIFIED）。

GitHub / Obsidian 知识分工（当前工作规则）：
- GitHub / repo（正式 / 已提升知识；代码与版本权威）：code、formal policy、
  frozen design、PROJECT_STATE、MASTER_BACKLOG、formal REPORTs、promoted / finalized assets
- Obsidian（Working Knowledge 层）：working knowledge、discussion、draft、
  conversation handoff、stage retrospective、uncertain / not-yet-promoted decisions、
  daily project notes
- **一条信息只有一个 active authority；禁止维护两份可编辑的权威副本。**

Promotion 模型：
Obsidian working knowledge → stable conclusion → Framework task → 提升进 repo / GitHub 正式资产

未来泛化（planned policy，未激活，AAF-MAINT-HANDOFF-001）：
若本 Pilot 成功，同类 conversation-handoff 模式可推广为其他用户项目的默认做法；
当前不迁移 / 不修改其他项目。

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
| RW-020 | Dead Runner / Orphaned RUNNING State Detection | OPEN | P1 |
| RW-021 | Bridge Restart / Exit Completion Notification Continuity | OPEN | P2 |
| RW-022 | Framework Final Status Aggregation: PASS_WITH_WARNING + APPROVE + Blocking NONE → WAITING | OPEN | P1 |
| RW-023 | E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop | OPEN | P2 |
| RW-024 | Completion Dialog Copy Report UX（复制报告二次弹窗 + Z 序问题） | OPEN | P2 |
| RW-025 | Session Continuity Clock Flake（test_first_rollover_generates_files 秒级时钟边界） | OPEN | P3 |
| BND-001 | Planner-layer Anti-Drift Validation | PARTIAL | P2 |
| CTX-001 | Context Length / Conversation Rollover UX | PARTIAL | P1 |
| CTX-002 | TASK / Stage Prompt / REPORT Context Bloat（层层全文叠加） | SOLVED | P1 |
| HIST-001 | Historical Framework Optimization Set Recovery | RECOVERY_PENDING | P2 |
