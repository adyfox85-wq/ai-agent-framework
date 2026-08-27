# PROJECT_STATE.md

> Project: AI Agent Framework\
> Current Version: **v0.4（IN PROGRESS — Phase A/B/C/D COMPLETE；Phase E IN PROGRESS（E-Core / Soft Cancel COMPLETE）；Phase F NOT STARTED）**\
> Last Updated: 2026-08-27（AAF-v0.4-TASK-005-A — Phase E Core Cancel Foundation and Soft Cancel sync）\
> Document Type: **Living Project State / 持续更新的当前状态入口**
>
> 本文件不是历史快照。后续每完成一个重要阶段、发生 Framework
> 级变更、版本状态变化或关键风险变化，都应更新本文件。
>
> 下方 v0.3 及更早内容属于历史状态，保留不删除；当前状态以顶部 v0.4 块为准。

------------------------------------------------------------------------

## 0. v0.4 Current Status（当前状态）

``` text
Version: v0.4
Status: IN PROGRESS
Phase: A — Runtime State Foundation: COMPLETE
       B — Bridge Background / Tray Skeleton: COMPLETE
       C — Status Window + Chinese-first UI: COMPLETE
       D — Progress Visualization: COMPLETE
       E — Safe Cancel Lifecycle: IN PROGRESS（E-Core / Soft Cancel COMPLETE — AAF-v0.4-TASK-005-A；
           剩余 TASK-005-B Process Ownership / Force Cancel / Recovery Integration
           与 TASK-005-C Cancel UI + Windows E2E Closure 未交付 → Phase E 不得标 COMPLETE）
Direction: Desktop Shell MVP / Runtime Observability & Control

v0.4 主线（Phase 顺序）：
A. Runtime State Foundation（COMPLETE）
B. Bridge Background / Tray Skeleton（COMPLETE）
C. Status Window + Chinese-first UI（COMPLETE — 2026-08-27 closure：AAF-v0.4-TASK-003-FIX-001 正式同步；
   实现 + WorkBuddy 独立验证 + Codex 审查全部通过，见下方 Phase C 段落）
D. Progress Visualization（COMPLETE — 2026-08-27 closure：AAF-v0.4-TASK-004-FIX-001 正式收口；
   实现 + 测试 + 真实 Windows E2E + 独立 post-completion closure audit 通过，见下方 Phase D 段落）
E. Safe Cancel Lifecycle（IN PROGRESS — AAF-v0.4-TASK-005-A 已交付 E-Core / Soft Cancel：
   CANCELLED 终态、state.lock、terminal generation、reconciliation、recovery finalizer 基础、
   runner 检查点、cancel.request 契约；见下方 Phase E 段落。剩余子任务：
   TASK-005-B（Process Ownership / Force Cancel / Recovery Integration）+
   TASK-005-C（Cancel UI + Windows E2E Closure）完成后才能正式标记 COMPLETE）
F. Project Switching / Duplicate Task UX（NOT STARTED）

Phase F 不得提前实现 / 不得自动启动。

Phase C 目标：正式状态窗口（bridge/status_window.py）—— 只读观察 + 中文优先 +
六阶段条事实映射；Tray 接入（打开状态窗口复用/聚焦，关闭不退出 Bridge）；
现有弹窗文案中文化（不改 TASK 解析 / validation / launcher 语义 / lifecycle）。

Phase C Implementation（AAF-v0.4-TASK-003，2026-08-27）：
- Status Window：bridge/status_window.py（信息架构 §3 / wireframe §12.1；当前项目 / Bridge /
  热键 / Workspace / 当前任务（Task ID / Name / 阶段 / Agent / 已运行 / 最近活动 / 整体结果）/
  六阶段条（✓ ▶ ○ ⏸ ✗）；约 1 秒 after 只读刷新；单例复用/聚焦；关闭不退出 Bridge）
- Runtime State Source：全部展示可追溯到 task.json（runtime_state reader）/ route.json /
  boundary.json / REPORT.md / last_run.json / config.json / launcher 内存；UI 不写任何 canonical artifact
- Current Task 解析：launcher RUNNING 内存任务优先 → 最近 last_run；last_run 新增持久化 output_dir
  （legacy 无该字段时从 task_path 推导，不扫描 .aaf 猜测）
- Chinese-first：窗口/弹窗/按钮中文（设计 §11.1 文案表）；技术字段（Task ID / SUCCESS 等）保留英文原值；
  CANCELLED 未增加（Phase E 范围）
- Tray：菜单项改为「打开状态窗口」；Restart / Exit / 单实例 / 热键语义未变
- 回归：239 基线不降，全量 284 passed（+45 新增 tests/test_status_window.py）
- 真实 Windows E2E（.aaf/AAF-v0.4-TASK-003/：EVIDENCE.md、s1–s7 步骤脚本、各阶段截图）：
  后台 Bridge → Tray 打开状态窗口 → 空状态显示 → 真实 Ctrl+Alt+A 全路由任务
  （Hermes→WorkBuddy→Codex→REPORT）→ 状态窗口阶段变化可见（截图验证）→ SUCCESS 收敛
  （已完成（SUCCESS）/ 六阶段全 ✓）→ 关闭窗口 Bridge 存活 → 再次打开正常 →
  Restart/Exit 回归通过（Exit 确认窗中文按钮；状态文件 0 变更）→ Agent 子进程无 console 黑窗
- WorkBuddy: PASS_WITH_WARNING（无 blocking rework；warning = TASK #10 与冻结设计中文映射措辞差异
  （实现遵循冻结设计，正确）+ Validator 未亲自重跑完整 GUI E2E（证据由 Hermes 提供，结构支撑充分））
- Codex: APPROVE（Blocking Issues: NONE；Scope Leakage: NONE；Recommended Phase C Status: COMPLETE）
- Blocking: NONE（实现侧 + 验证侧）
- Remote Sync: SYNCED
- 正式 closure: AAF-v0.4-TASK-003-FIX-001（2026-08-27）——见下方「0.2 Phase C」段落与
  docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-C-CLOSURE-2026-08-27.md
- 汇总语义异常（已登记 RW-022，非 Phase C 实现问题）：最终 REPORT 顶部 Current Status 曾为 WAITING，
  但 WorkBuddy 无 blocking rework + Codex APPROVE + Blocking Issues NONE；该 WAITING 来自
  aggregation / warning semantics，不是 Phase C implementation blocker（详见 AAF_MASTER_BACKLOG.md RW-022）

Phase A 目标：task.json = live canonical runtime view
（started_at / stage / stage_started_at / last_activity_at / agent / phases），
统一 Runtime State reader（legacy 兼容），runner EXTEND ONLY 阶段写入。

Phase A Closure（AAF-v0.4-TASK-001-FIX-001 + FIX-002 + FIX-003，2026-08-27）：
- Tests: 216 passed
- Review: COMPLETE（WorkBuddy APPROVE + Codex APPROVE）
- Remote Sync: SYNCED — closure commits 均已纳入 origin/main
- Branch: main
- Ahead/Behind: 0/0（at closure verification）
- 实时 Git HEAD 属于执行时状态，不在本 Living Project State / durable closure doc
  中硬编码为永久当前值；实时 HEAD 请直接用 Git 查询（git rev-parse HEAD / git status）
- 历史记录（RW-018 Git/network observation）：FIX-001 初次 push 曾因 TLS EOF 失败，
  后续 WorkBuddy 独立验证中成功执行 push；仅作历史环境说明，
  当前无 remote sync blocking / PENDING
- Unresolved: None blocking
- Commit 历史归属: 5a8b76a（Phase A implementation）；f81c7ee（FIX-001 closure work）；
  ca06c29（FIX-001 REMOTE_SYNC_PENDING record）；e3d39e7（FIX-002 remote-state
  documentation sync attempt）；FIX-003（docs-only closure consistency fix，
  仅作历史 reference，不写为“永久 Current HEAD”）

Phase B 目标：Bridge 以 pythonw 无控制台常驻（scripts/start_bridge.pyw）+ Tray skeleton
（打开状态 / 重启 Bridge / 退出 AAF）+ 单实例 mutex + hotkey health 判定；
Core / UI 边界：Desktop Shell 只读产物，不复制 Router / Runner / Lifecycle。

Phase B Closure（AAF-v0.4-TASK-002 + AAF-v0.4-TASK-002-FIX-001，2026-08-27）：
- TASK: AAF-v0.4-TASK-002（Bridge Background / Tray Skeleton）
- Closure validation: AAF-v0.4-TASK-002-FIX-001（Phase B Hotkey End-to-End Closure Validation）
- Implementation commit: 6a9814d
- Tests: 233 passed（216 baseline + 17 新增，零下降）
- Background pythonw Bridge: PASS（无控制台常驻，真实 Windows 验收）
- Tray: PASS（Shell_NotifyIconW 真实创建；状态窗口可打开，关闭不退出 Bridge）
- Single instance: PASS（命名 mutex；restart 交接 WAIT_ABANDONED 路径实测通过）
- Ctrl+Alt+A real GUI E2E: PASS（Hotkey → Clipboard → TASK validation → Confirmation
  → Launcher → Framework → REPORT 全链路；原 error 1409 来源确认为旧 Bridge 自身遗留）
- Restart regression: PASS（重启后单实例 / Tray / Hotkey 全部恢复）
- Exit regression: PASS（Exit 不修改 canonical task terminal state；状态快照 diff 0/0/0）
- WorkBuddy: PASS_WITH_WARNING（唯一 warning = Codex closure review 延迟，后已由 Codex 独立执行）
- Codex: APPROVE
- Remote Sync: SYNCED
- Blocking: NONE
- 新发现缺口（非 Phase B blocker，仅长期登记，不在 Phase B 实现）：
  Bridge Restart / Exit 后 completion notification continuity 丢失
  → 已登记 RW-021（见 AAF_MASTER_BACKLOG.md），与 RW-020 明确区分
- Durable closure 报告：docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-B-CLOSURE-2026-08-27.md

Next Phase Candidate: Phase D — Progress Visualization
（历史记录：Phase C 完成时的候选标记；Phase D 已由 Planner 正式启动为 AAF-v0.4-TASK-004，
现为 IMPLEMENTATION COMPLETE 待验证——见上方 Phase D 段落）

v0.3: CLOSED（见下方历史块，不重开）
v0.4 启动决定：Planner / User 已批准（见
docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-A-START-HANDOFF-2026-08-27.md）
```

### 0.1 Phase A — Runtime State Foundation（COMPLETE）

- TASK: AAF-v0.4-TASK-001（2026-08-27）；closure: AAF-v0.4-TASK-001-FIX-001 + FIX-002 + FIX-003（2026-08-27）
- 状态：COMPLETE（WorkBuddy APPROVE + Codex APPROVE；216 passed；Remote Sync SYNCED；
  实时 HEAD 属执行时状态，用 Git 查询，不在此处硬编码为永久当前值）
- 范围：task.json live runtime state / Runtime State reader / runner 阶段写入 / PROJECT_STATE 同步
- 禁止（Phase A 不实现）：Tray / status window / pystray / autostart / progress bar / stuck 算法 /
  Safe Cancel（CANCELLED / control.json / state.lock / launch registry / force kill）/
  project switching UI / Duplicate dialog / Desktop Shell packaging

### 0.2 Phase B — Bridge Background / Tray Skeleton（COMPLETE）

- TASK: AAF-v0.4-TASK-002（2026-08-27）；closure: AAF-v0.4-TASK-002-FIX-001（Phase B Hotkey
  End-to-End Closure Validation，2026-08-27，真实 Windows GUI 验收）
- 状态：COMPLETE（WorkBuddy PASS_WITH_WARNING + Codex APPROVE；233 passed；
  Remote Sync SYNCED；实时 HEAD 属执行时状态，用 Git 查询，不在此处硬编码为永久当前值）
- 范围：pythonw 无控制台后台宿主（scripts/start_bridge.pyw）/ Tray skeleton（打开状态 /
  重启 Bridge / 退出 AAF，ctypes Shell_NotifyIconW 零第三方依赖）/ 单实例 mutex /
  hotkey health 判定（OK / DEGRADED）/ restart 交接 / exit 语义（不改 canonical state）/
  Core / UI 边界只读
- 验收证据：.aaf/AAF-v0.4-TASK-002-FIX-001/（EVIDENCE.md、status_window.png、
  s1–s6 步骤脚本、REPORT.md）；正式 closure 报告见
  docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-B-CLOSURE-2026-08-27.md
- 新发现缺口：Bridge Restart / Exit 后 completion notification continuity 丢失
  → 已登记 RW-021（非 Phase B blocker，不重开 Phase B，不在本阶段实现）
- 禁止（Phase B 不实现）：Phase C-F 全部内容 / autostart / Safe Cancel（CANCELLED /
  cancel.request / control.json / state.lock / launch registry / force kill）/
  RW-020 / completion reattachment

### 0.2 Phase C — Status Window + Chinese-first UI（COMPLETE）

- TASK: AAF-v0.4-TASK-003（2026-08-27）；closure: AAF-v0.4-TASK-003-FIX-001（Phase C Closure Sync，2026-08-27）
- 状态：COMPLETE（WorkBuddy PASS_WITH_WARNING（无 blocking rework）+ Codex APPROVE；284 passed；
  Remote Sync SYNCED；实时 HEAD 属执行时状态，用 Git 查询，不在此处硬编码为永久当前值）
- Implementation commit: 5458def（feat(v0.4-phase-c): status window + chinese-first UI）
- 范围：bridge/status_window.py 正式状态窗口（Bridge/Project 区 + Current Task 区 + 六阶段条
  ✓▶○⏸✗、约 1s tkinter.after 只读刷新、单例复用/聚焦、关闭不退出 Bridge）/ Chinese-first
  （窗口/弹窗/按钮中文、技术字段保留英文原值）/ Runtime State 只读展示（runtime_state reader +
  last_run.json + config + launcher 内存；UI 零写 canonical artifact）/ Tray「打开状态窗口」接入
  （restart / exit / 单实例 / 热键语义未变）/ 现有 Bridge 弹窗文案中文化
  （不改 TASK 解析 / validation / launcher 语义 / lifecycle）
- 验收证据：.aaf/AAF-v0.4-TASK-003/（EVIDENCE.md、空状态截图 + 4 张阶段截图 + 最终收敛截图、
  s1–s7 步骤脚本、evidence.jsonl）；正式 closure 报告见
  docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-C-CLOSURE-2026-08-27.md
- 测试：284 passed（239 基线 + 45 新增 tests/test_status_window.py，零下降；覆盖 req 19 A–L 全项：
  status/stage/agent 映射、legacy/缺失字段、空状态、当前任务解析、elapsed/last activity 格式化、
  窗口单例、Tray 集成、中文文案、刷新回调安全）
- Windows E2E：PASS（后台 Bridge → Tray 打开状态窗口 → 空状态显示 → 真实 Ctrl+Alt+A 全路由任务
  Hermes→WorkBuddy→Codex→REPORT → 阶段变化可见（截图验证）→ SUCCESS 收敛（已完成（SUCCESS）/
  六阶段全 ✓）→ 关闭窗口 Bridge 存活 → 再次打开正常 → Restart/Exit 回归通过
  （Exit 确认窗中文按钮；状态文件 0 变更）→ Agent 子进程无 console 黑窗）
- Current Task resolution: PASS / Stage strip: PASS / elapsed / last activity: PASS /
  singleton window behavior: PASS / Tray integration: PASS / no-console regression: PASS
- WorkBuddy: PASS_WITH_WARNING（无 blocking rework；warning = TASK #10 与冻结设计中文映射措辞差异 +
  Validator 未重跑完整 GUI E2E，均非代码问题）
- Codex: APPROVE（Blocking Issues: NONE；Scope Leakage: NONE；Recommended Phase C Status: COMPLETE）
- Remote Sync: SYNCED
- Phase D-F scope leakage: NONE
- Blocking: NONE
- 汇总语义异常（已登记 RW-022，非 Phase C 实现问题）：最终 REPORT 顶部 Current Status 曾为 WAITING，
  但 WorkBuddy PASS_WITH_WARNING（无 blocking rework）+ Codex APPROVE + Blocking Issues NONE；
  该 WAITING 来自 aggregation / warning semantics，不是 Phase C implementation blocker
  （详见 AAF_MASTER_BACKLOG.md RW-022）
- 既有缺口（不重复登记）：Bridge Restart / Exit 后 completion notification continuity 丢失
  → RW-021（OPEN / P2）；Phase C E2E 中再次复现，已按 RW-021 覆盖，未重复新建 issue，本阶段不实现
- 禁止（Phase C 不实现）：Phase D-F 全部内容（progress bar / percentage / phase weights /
  stuck detection / Safe Cancel / launch registry / completion reattachment / project switching /
  Duplicate UX）/ RW-020 / RW-021 / final-status aggregation fix

### 0.2 Phase D — Progress Visualization（COMPLETE）

- TASK: AAF-v0.4-TASK-004（2026-08-27）；closure: AAF-v0.4-TASK-004-FIX-001（Phase D Post-Completion
  Closure Audit，2026-08-27）
- 状态：COMPLETE（实现 + 334 passed + 真实 Windows E2E + 独立 post-completion closure audit 全部通过；
  WorkBuddy 独立验证 + Codex closure review 由 AAF-v0.4-TASK-004-FIX-001 route 阶段（hermes→workbuddy→codex）
  在 Executor 返回后依次执行，判定记录于该任务 REPORT.md；Remote Sync SYNCED）
- Implementation commit: 6c27a27（feat(v0.4-phase-d): progress visualization + suspected-stuck）
- 范围：bridge/progress.py（集中权重表 §4.2 Validation 5 / Boundary 5 / Hermes 45 / WorkBuddy 20 / Codex 20 /
  Report 5 合计 100 断言保护 + 确定性估算纯函数 §4.1：已完成阶段全权重；进行中阶段内部 0%–50% 线性、60 分钟
  封顶；SUCCESS→100%；WAITING/FAILED 冻结在已完成阶段权重和；无任务/无 task.json → 0；legacy 缺失 phases
  不崩溃 + 中文文案 §12.1）/ bridge/stuck.py（suspected-stuck 最小观察 §5.2：RUNNING + last_activity_at
  距今 ≥ 10 分钟 →「⚠ 任务可能已停滞（最近 N 分钟没有活动）」；阈值集中常量化；只提示、零 canonical 写入；
  RW-020 边界）/ bridge/status_window.py（整体进度条 Canvas 只读渲染 +「整体进度：约 N%（估算）」+
  当前阶段占比 + stuck 黄色横幅 + 进行中阶段高亮 +「查看任务目录」按钮；约 1s tkinter.after 只读刷新、
  Tk 主线程更新、关闭后刷新安全）/ docs（QUICKSTART / TROUBLESHOOTING：进度是估算、100% 只在 SUCCESS
  保证、stuck 仅可疑）
- 进度规则（确定性，单调性）：正常推进序列单调不倒退（0→5→14→21→55→85→96→100）；SUCCESS→100%；
  FAILED/WAITING 终态按设计 §4.1.5 冻结在已完成阶段权重和（估算→事实收敛，明确理由 + 测试覆盖）
- 只读边界：进度/停滞全部由 runtime_state reader + task.json phases + timestamps 计算；
  UI 零写 task.json / run.json / route.json / boundary.json / REPORT.md / cancel.request
- 测试：334 passed（284 基线 + 50 新增 tests/test_progress.py，零下降；覆盖 TASK req 22 A–T 全项：
  0% / 各阶段 running / SUCCESS 100 / FAILED <100 / WAITING 冻结 / legacy / no-task / monotonic /
  stuck 阈值上下 / SUCCESS·FAILED·WAITING 不显示 stuck / last_activity·stage_started_at 缺失 /
  中文文案 / 权重表集中 / GUI 进度条·横幅·高亮·任务目录按钮 / 无 CANCELLED scope leak）
- 真实 Windows E2E（.aaf/AAF-v0.4-TASK-004/：EVIDENCE.md、evidence.jsonl、9 张截图、e2e_phase_d.py）：
  Tray 打开状态窗口（空状态）→ stuck fixture 独立验证（真实 Tk 断言 + live 窗口截图）→ 真实 Ctrl+Alt+A
  全路由任务（Hermes→WorkBuddy→Codex→REPORT）→ 进度采样 [10, 55, 75, 100] 单调推进 →
  SUCCESS = 100%（全绿进度条 +「整体进度：100%（已完成）」）→ 关闭窗口 Bridge 存活 → 重开进度仍正确 →
  三 Agent 进程树 console_windows 全空（无 console 黑窗）→ 无 Tk callback 异常 → Tray Exit 正常退出；
  像素级验证进度条绿色随百分比单调递增、stuck 横幅仅 stuck 态出现
- 独立 post-completion closure audit（AAF-v0.4-TASK-004-FIX-001，2026-08-27）：
  - Source of Truth 核对：PROJECT_STATE / AAF_MASTER_BACKLOG / 冻结设计 §4/§5/§12.1 / Phase C closure
    handoff / .aaf/AAF-v0.4-TASK-004 全部证据 / 当前代码（progress.py / stuck.py / status_window.py /
    tests/test_progress.py）逐一核对一致
  - 实现侧独立核对通过：progress bar / percentage text / 固定确定性权重模型 / 权重集中 / SUCCESS=100 /
    FAILED·WAITING 收敛 / 单调正常序列 / Chinese-first / suspected-stuck warning / stuck 只读 /
    零 canonical 写入 / 无 Phase E/F 泄漏（bridge/ 无 cancel.request / control.json / state.lock /
    launch registry / force kill / CANCELLED 实现，仅注释声明不实现）
  - 权重模型核对：实现 == 冻结设计（Validation 5 / Boundary 5 / Hermes 45 / WorkBuddy 20 / Codex 20 /
    Report 5 = 100，assert 保护）
  - 进度语义核对：no task → 0；RUNNING 阶段估算；completed 阶段全权重；SUCCESS=100；FAILED<100；
    WAITING 不自动推进；legacy/缺失字段安全；正常生命周期进度不倒退
  - stuck 语义核对：suspected-stuck ≠ dead runner 判定；阈值集中（10 分钟常量）；仅 RUNNING + stale
    last_activity 提示；零 canonical mutation；无自动 resume / cancel / force kill；RW-020 未标 solved
  - 测试独立重跑：`pytest -q` = **334 passed in 4.45s**（零下降）
  - E2E 证据独立复核：evidence.jsonl 全步骤一致；progress samples [10,55,75,100] 单调；SUCCESS=100；
    独立像素抽样 s4_status_final.png 绿色进度条存在（335 样本点）而 s2_status_empty.png 无（0）；
    三 Agent console_count=0；bridge_error.log 不存在（无 Tk callback 异常）
  - RW-020 真实复现（追加证据，不标 solved）：TASK-004 canonical task.json 残留 RUNNING/HERMES
    （started_at = last_activity_at = 19:07:15）而 runner / Bridge 已不存在、REPORT.md 已生成（20:03:04）；
    UI suspected-stuck 不解决 RW-020（见 AAF_MASTER_BACKLOG.md RW-020）
  - RW-021 真实复现（追加证据，不实现 callback recovery）：Phase D E2E Bridge Exit/Restart 后 REPORT 已生成
    但用户未收到最终 completion window（见 AAF_MASTER_BACKLOG.md RW-021）
  - 新登记 backlog：RW-023（E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop，
    OPEN/P2）、RW-024（Completion Dialog Copy Report UX，OPEN/P2）——均无既有等价 issue，未重复创建
  - WorkBuddy: 独立验证（本任务 route 阶段执行，verdict 见 AAF-v0.4-TASK-004-FIX-001 REPORT.md）
  - Codex: closure review（本任务 route 阶段执行，verdict 见 AAF-v0.4-TASK-004-FIX-001 REPORT.md）
  - Blocking: NONE（实现侧 + 审计侧）
  - Remote Sync: SYNCED
  - 正式 closure 报告：docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-D-CLOSURE-2026-08-27.md
- 历史 task.json 残留说明：TASK-004 canonical task.json 的 RUNNING/HERMES 残留属 RW-020 真实复现证据，
  本 audit 只读保留、不修改其终态、不手工标 SUCCESS；该 run 的 runner 已不存在（E2E 前 cleanup.py 清理）
- 禁止（Phase D 不实现）：Phase E/F 全部内容（Safe Cancel / CANCELLED / cancel.request / control.json /
  state.lock / launch registry / force kill / project switching / Duplicate UX）/ RW-020 完整 dead-runner
  protocol / RW-021 / RW-022 aggregation fix
- Next Phase Candidate: Phase E — Safe Cancel Lifecycle（已由 Planner 正式启动为 AAF-v0.4-TASK-005-A，
  E-Core / Soft Cancel 交付完成；Phase E 未 COMPLETE，见下方 Phase E 段落）

### 0.2 Phase E — Safe Cancel Lifecycle（IN PROGRESS — E-Core / Soft Cancel COMPLETE）

- TASK: AAF-v0.4-TASK-005-A（2026-08-27）；范围：Phase E Core Cancel Foundation + Soft Cancel
  （冻结设计 §6 / §6A / §6B 的 E-Core 部分；Force Cancel / ownership / UI 分离到后续 TASK）
- 状态：**IN PROGRESS — E-Core / Soft Cancel COMPLETE（实现 + 测试 + 真实 E2E 通过；**
  **WorkBuddy / Codex 独立验证由本任务 route 阶段执行，判定记录于任务 REPORT；**
  **Phase E 不得标 COMPLETE，剩余 TASK-005-B + TASK-005-C 未交付）**
- 实现内容：
  - `ai_agent_framework/lock_utils.py`（新）：Core-owned per-task OS-level exclusive `state.lock`
    （§6B.1–§6B.3；Windows msvcrt.locking / POSIX flock；timeout；残留文件不占锁；crash 后 OS 自动释放；
    锁失败明确错误 FINALIZATION_BUSY；不绕过锁）
  - `ai_agent_framework/task_lifecycle.py`：CANCELLED 加入 VALID_STATUSES；TERMINAL_STATUSES =
    {SUCCESS, WAITING, FAILED, CANCELLED}（§6A.1）；`finalize_terminal()` 统一锁内 critical section
    （§6B.2：锁内 reload → terminal arbitration → 原子提交 + terminal_generation/terminal_at/
    terminal_reason/cancel_mode → release）；`update_status` 拒绝终态（防绕过锁）；
    `read_canonical_terminal()` 只读 canonical；legacy 无 generation 兼容
  - `ai_agent_framework/cancel.py`（新）：cancel.request 契约（task_id / requested_at / request=soft_cancel；
    原子写；无效请求安全处理返回 warning；非 terminal truth §6A.15）
  - `ai_agent_framework/reconcile.py`（新）：`reconcile_terminal_artifacts()`（§6B.6–§6B.8；
    无 canonical 不臆造；幂等补齐 run.json / REPORT.md；不改 canonical；generation 对齐；
    完整一致 no-op）
  - `ai_agent_framework/finalize_cancelled.py`（新）：Core-owned recovery finalizer 基础
    （§6A.12/§6B.21；CLI `python -m ai_agent_framework.finalize_cancelled`；幂等；
    已有终态不改写；**本 TASK 不从 Launcher 调用它去 taskkill**——Force Cancel 链留 005-B）
  - `ai_agent_framework/runner.py`：安全检查点（Validation 后 / Boundary 前；Boundary 后 / Hermes 前；
    Agent 之间；Codex 后 / Report 前）；有效 cancel.request → 不启动后续 Agent →
    task.json(CANCELLED) → run.json(CANCELLED) → REPORT(CANCELLED)（§6A.4 顺序）；
    统一经 finalize_terminal 提交终态；FRAMEWORK_ERROR 路径同样锁内提交；soft cancel exit code = 0
  - `ai_agent_framework/report.py`：REPORT 支持 CANCELLED（Current Status: CANCELLED + 「任务已取消」+
    Task ID / 取消时间 / 已完成阶段与 Agent 结果保留 / 后续阶段未执行；不伪造 Force Cancel /
    PID kill / ownership verified）+ Terminal Generation provenance
  - `ai_agent_framework/task_archive.py`：TERMINAL_STATUSES 单一来源（含 CANCELLED，可归档 §6.6）
  - `bridge/launcher.py`：RESULT_CANCELLED + wait thread 最小 canonical-aware 兼容读取（§6A.5：
    exit code 只是 evidence；canonical 存在则跟随 Core outcome；完整 wait-thread 归 005-B）
  - `bridge/status_window.py`：STATUS_LABELS / LAUNCHER_RESULT_LABELS 增加 CANCELLED → 「已取消」
    （§11.1 最小 compatibility；最终 [停止当前任务] 按钮属 005-C）
  - `bridge/progress.py`：CANCELLED 收敛（§4.1.5：停在取消时刻权重和，不显示 100%）
  - `docs/QUICKSTART.md` / `docs/TROUBLESHOOTING.md`：CANCELLED / soft cancel Core 契约 /
    cancel.request 是 request 不是 truth / Phase E 未 COMPLETE / Force Cancel 未交付
- 测试：**391 passed**（334 基线 + 57 新增，零下降；tests/test_phase_e_core.py 45 项覆盖 req 28 A–Z
  全项 + tests/test_phase_e_concurrency.py 真实子进程锁/竞态 5 项（req 29，不 mock 锁）+
  tests/test_phase_e_e2e.py 真实 E2E 4 项（req 30 两个 scenario + CLI 级 run.py / finalize_cancelled））
- 真实软取消 E2E：Scenario 1（Hermes 前 cancel → Hermes 不启动 → CANCELLED 全套产物）PASS；
  Scenario 2（Hermes 完成 → WorkBuddy 前 cancel → Hermes result 保留 → CANCELLED）PASS；
  真实 run.py CLI 子进程 + finalize_cancelled CLI 幂等 PASS
- 边界遵守：无 Force Kill（taskkill 零实现）、无 Bridge launch registry、无 Status Window Stop 按钮、
  RW-020/021/022/023/024 未自动修复、历史 TASK-004 task.json 未修改、用户本地 helper
  （scripts/start_bridge_hidden.vbs / AAF_TASK004_PROCESS_CHECK.txt / .aaf/）未动
- WorkBuddy / Codex：由本任务 route 阶段执行（verdict 见任务 REPORT.md）
- Next Phase Step（唯一）：**AAF-v0.4-TASK-005-B — Phase E Process Ownership + Force Cancel +
  Recovery Integration**（不得自动执行；005-B + 005-C 全部完成后 Phase E 才可标 COMPLETE）

### 0.2 v0.3 历史状态（CLOSED，保留）

``` text
Version: v0.3
Core Implementation: COMPLETE
Core Acceptance: PASS
Lifecycle: CLOSED（v0.3 已收官；不因 v0.4 开发重新定义 v0.3）

v0.3 三大核心方向：
1. Task Automation     ✅ COMPLETE（000-A/B/C + 001 Validation + 002 Lifecycle + 003 Archive）
2. Session Continuity  ✅ COMPLETE（004）
3. Project Boundary    ✅ COMPLETE（005）

v0.3 closure: WorkBuddy APPROVE + Codex milestone audit APPROVE + Blocking=0
```

### 0.1 Maintenance Period（当前维护/观察期）

v0.3 已 CLOSED，当前为维护 / 观察期。此期间只做：

- 文档、登记、恢复资产维护（如本任务）；
- 已确认真实问题的 hotfix（须独立记录，不重开 v0.3 Scope）。
- AAF-DESIGN-001（2026-08-27）：**Desktop Shell design completed / implementation not started**。设计规格见 `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（仅设计，无产品功能实现；是否纳入 v0.4 由 Planner 决策）。

**不**做：新功能实现；v0.4 规划以外的工作；自动进入下一 TASK。

### 0.2 近期 Hotfix 与真实事故记录

| 事项 | 状态 | 记录 |
|---|---|---|
| Agent 子进程黑色 console 窗口抑制 hotfix | COMPLETE | commit **44ecfa8**（AAF-v0.4-TASK-002-FIX-003：Windows 下 Hermes / WorkBuddy / Codex 子进程统一 CREATE_NO_WINDOW 无控制台；共享 helper `ai_agent_framework/subprocess_utils.py`，Bridge launcher 同类修正；239 passed；真实 Windows 探针 Hermes/WorkBuddy/Codex 均无 console 窗口） |
| Codex command discovery hotfix | COMPLETE | commit **7cbf594**（Codex 升级 hash 目录变化导致 discovery 失败 → registry PATH 优先 + hash 目录 fallback；198 passed） |
| Router local readonly constraint hotfix | COMPLETE | commit **457df93**（execution intent 与局部限制区分；206 passed；WorkBuddy APPROVE + Codex APPROVE） |
| AAF-MAINT-001 routing incident | 已登记 | 局部范围限制被误判为任务级 review 模式 → Hermes 被跳过；Root cause 与修复见 `AAF-HOTFIX-ROUTER-READONLY.md`；事故登记 RW-011 |
| AAF-MAINT-001-FIX-001 self-triggering routing incident | 已登记 | 为描述前一次事故引用 Router 分类短语 → 全文信号匹配再次触发 review route → Hermes 第二次被跳过；Runtime Diagnose 排除 stale route / wrong import / truncation，根因为 self-triggering reference trap；事故登记 RW-013 |

两个事故任务证据保留：

``` text
.aaf/AAF-MAINT-001/
.aaf/AAF-MAINT-001-FIX-001/
```

不删除、不覆盖。

### 0.3 Current Usability Gaps（当前已知可用性缺口）

详见 `docs/internal/AAF_MASTER_BACKLOG.md`（完整登记），摘要：

- Bridge 无开机自动启动（RW-004；Phase B 已提供 pythonw 后台 + Tray skeleton，autostart 仍未实现）；
- 项目切换需人工改 config（RW-003）；
- hotkey listener 偶发失活，重启恢复（RW-012）；
- TASK parser 对换行格式兼容性有限（RW-008）；
- 无运行时状态可视化（RW-006）；Phase C（v0.4）已交付只读状态窗口（当前项目 / 任务 / 阶段 / Agent / 结果），
  剩余缺口：进度估算 / stuck 提示 / 停止入口（Phase D/E）；
- 重复提交 Task 仅提示 TASK_ALREADY_EXISTS，无状态 / 查看 / REPORT 入口（RW-016）；
- 无当前任务 Stop / Cancel 入口（RW-014）；
- 无统一桌面 UI；未来 Chinese-first（RW-015）；Phase C（v0.4）已交付中文优先的状态窗口与弹窗文案；
- 无会话过长提醒/承接 UX（CTX-001）；
- 环境 / 仓库观察项：.aaf ignore 一致性、Git push 代理可靠性、Agent review 证据一致性（RW-017～RW-019，详见 Master Backlog，仅登记不实现）。

### 0.4 Source / Mirror / Recovery Policy（长期政策）

``` text
Repository（GitHub / local repo）:
  authoritative source —— 唯一权威长期知识源

ChatGPT（Project / conversation）:
  planner / discussion interface —— 规划和协作界面，
  不能作为唯一长期知识来源

Obsidian（D:\AdyAI\Obsidian-Vault\AI Agent Framework\）:
  human-readable mirror and recovery layer —— MIRROR ONLY，
  非独立权威版本；不开发自动同步程序或 Obsidian plugin
```

ChatGPT disaster recovery principle（详见 RW-009）：

``` text
GitHub / local repo → README → PROJECT_STATE
→ AAF_MASTER_BACKLOG → latest closing handoff
→ 创建新的 ChatGPT Project / Planner conversation → 继续维护
```

即使旧 ChatGPT Project 或 conversation 不存在，Framework 仍能恢复到
可继续升级的状态。

### 0.5 Future Planning Rule（未来规划规则）

``` text
Before planning new AAF work:
FIRST READ:
docs/internal/AAF_MASTER_BACKLOG.md
```

以后任何被正式确认"稍后处理"的问题，**必须进入 Master Backlog 才算
长期登记完成**。

v0.4 IN PROGRESS — Phase A/B/C/D COMPLETE；Phase E IN PROGRESS（E-Core / Soft Cancel COMPLETE，由 AAF-v0.4-TASK-005-A 交付；剩余 TASK-005-B + TASK-005-C 未交付，Phase E 不得标 COMPLETE）；Phase F NOT STARTED，不得自动启动；Next Phase Step = AAF-v0.4-TASK-005-B（Phase E Process Ownership + Force Cancel + Recovery Integration）。

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
