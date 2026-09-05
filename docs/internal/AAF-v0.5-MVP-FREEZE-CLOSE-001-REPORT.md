# AAF-v0.5-MVP-FREEZE-CLOSE-001 — Formalize and Close the AAF v0.5 Personal MVP Boundary（Closure Record）

> Task: 基于已完成的 AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001，将当前 AAF 正式收口为「个人轻量 Agent 协作调度 MVP」，固化 MVP 边界、退出条件和非 MVP 范围（docs-only closure；不得新增 runtime 能力，不启动 A6 或 A4+）
> Executor: Hermes（AAF Executor stage）2026-09-05
> Status: **v0.5 MVP FROZEN（freeze closure record 备妥——依 AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001 = MVP_EXIT_READY 正式化，docs-only；final closure route acceptance = PENDING——WorkBuddy 独立验证 + Codex closure 按 route 阶段执行，route legs 完成后按 A2-A5 closure 惯例复查/收口；未超前声称 route verdicts）**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex closure 为接受前置条件，按 route 阶段执行）——route 当前状态：**Hermes executor leg = COMPLETED（本 closure record + 一个 docs commit）；WorkBuddy = PENDING；Codex = PENDING（见 §6）**
> Baseline: HEAD = origin/main = `7eeaf830b882294fe44fec403eaf38cad2760321`（AAF-v0.5-A5-CLOSURE-STATE-FINALIZE-001；local == origin/main，ahead/behind = 0/0）
> Snapshot: `.aaf/AAF-v0.5-MVP-FREEZE-CLOSE-001/TASK.snapshot.md`（immutable execution snapshot，Task Hash 9cec9d7f5180e3c79ff85369fab7fc49d0387407c967be14b40c91819833c534）
> Audit: AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001（.aaf/AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001/REPORT.md；Current Status = SUCCESS / 判定 = MVP_EXIT_READY / Unresolved = None；全程只读零变更）

## 1. 结论（先给结论）

1. ✅ **v0.5 = 个人轻量 Agent 协作调度 MVP，正式收口（freeze closure record 备妥）**：2026-09-05，本任务依已完成的 AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001（只读审计 = **MVP_EXIT_READY**：能力图 15 项全部 MVP_SUFFICIENT、**MVP_MISSING = 无**、A6 全 scope 与 A4+ 均显式 NOT_REQUIRED_FOR_MVP、剩余工作 = docs / 正式冻结 / handoff only）正式化 MVP 产品定义 / 能力边界 / freeze criteria / post-freeze policy / 角色契约（docs-only closure record，零 runtime/code/test/model-registry/economics/qualification 变化）。final closure route acceptance = **PENDING**——WorkBuddy 独立验证 + Codex closure 为 route 后续 legs，按 A2-A5 closure 惯例执行（本 executor leg 不自行宣布 route verdicts）。
2. ✅ **MVP 产品定义与主目标成文**：AAF = 个人轻量 Agent 协作 / 调度 MVP——primary purpose = 减少 Planner / Executor / Validator / Reviewer 之间的人工 copy/paste 与人工消息 relay、标准化任务交接与结果返回、提供基本 execution / validation / review / recovery / risk / cost / fallback 保障、允许未来替换任一角色实现、保持 small / understandable / maintainable；主目标 = 消除或大幅减少人工 copy/paste 与 relay，保持稳定 task -> execution -> validation -> review -> report -> planner 循环（Requirement 2/3）。
3. ✅ **当前 MVP 能力边界 = sufficient，不重开 A0-A5**：audit 能力图 15 项（task intake / Bridge / routing / executor / validator / reviewer / REPORT+planner handoff / task state / recovery+resume / risk routing / 窄域 model routing / cost guard / fallback / git+sync closure / role replaceability）全部 grounded 于 v0.4 FROZEN 基线或 A0-A5 CLOSED / COMPLETE / SYNCED 权威块；role replaceability 的最小 gap（映射文档化）已由本 freeze record 的抽象角色契约 + concrete mapping 标注闭合（docs 级，零 runtime 变更）（Requirement 4）。
4. ✅ **MVP_EXIT_READY 显式记录**（Requirement 5）；**A6_FULL_SCOPE_NOT_REQUIRED_FOR_MVP 显式记录**（Requirement 6）；**A4+ = NOT_REQUIRED_FOR_MVP 显式记录**（Requirement 7）。
5. ✅ **non-MVP 扩张显式 bounded**：long-term memory system / self-learning / large DAG orchestration / agent marketplace / distributed workers / distributed queue / large dashboard / platform UI（含 Desktop Shell / Tray 扩展与 RW-014 遗留 Tray 停止项）/ plugin ecosystem / complex autonomous scheduling / complex long-term model scoring / large-scale subagent system / general-purpose Agent OS/platform expansion / 图形化 Cost Gate UX = 一律 NOT_REQUIRED_FOR_MVP，且明确**不是**自动计划的 FUTURE phases——进入 mainline 前必须获得新的显式用户 scope 批准（Requirement 8/9；audit Req 9 列表逐项收录）。
6. ✅ **历史 vs current 区分保持**：A0-A5 实现单元记录、A5 CLOSED 块、v0.4 冻结基线、旧 roadmap planned/historical scope（含既有 A6 / A4+ future scope 边界表述）= 历史保留不改写；REQUIRED_BEFORE_A5_CLOSE 9 项原文不重写（byte-identical 验证，见 §7）；current MVP-required scope 权威表述 = 本文件 + PROJECT_STATE v0.5「MVP FROZEN」块 + Last Updated 新条目（Requirement 10/16）。
7. ✅ **角色契约抽象与 concrete mappings 区分成文**：Planner / Executor / Validator / Reviewer 抽象角色契约 + 当前 concrete mappings（Planner = ChatGPT / Executor = Hermes / Validator = WorkBuddy / Reviewer = Codex）= implementations 非永久身份要求——未来替换任一 concrete product 本身不重定义 AAF MVP（满足同一角色契约即可）；替换集中改动点（router.py ALLOWED_ROUTE_AGENTS / adapters.py ROLE_INSTRUCTIONS+CLI 发现+上游依赖表 / runner.py 按 route agent 赋 role）成文（Requirement 11/12/13）。
8. ✅ **MVP freeze criteria 与 post-freeze change policy 成文**（Requirement 14/15，见 §2）。
9. ✅ **零行为变化**：docs-only——未修改任何 runtime / code / test / model registry / economics / qualification 数据（Requirement 17；git 验证见 §7）；无功能删除、无未来能力放弃。
10. ✅ 一个 docs/state commit（parent 7eeaf83，未 amend）；no push（Requirement 18）。
11. ⏳ **WorkBuddy 独立验证 + Codex review = route 后续 legs（PENDING）**：本 executor leg 未执行、未声称（Requirement 19/20 为接受前置条件，按 route 阶段执行；经验教训 = A5-CLOSE-001-FIX-001：不得超前声称 route verdicts——本 record 已如实标注 PENDING）。

## 2. Freeze Decision

- **前置决策**：AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001（只读审计，Hermes，全程零变更）= 唯一决策 **MVP_EXIT_READY**——能力面无 MVP_MISSING；A6 最小子集 = 空；A4+ 不扩张；从当前状态到正式冻结只剩 docs / 仪式路径（无 runtime 能力缺口）。
- **本任务执行**：正式化 freeze closure record / 状态更新——产品定义 + 边界 + 退出条件 + 非 MVP 范围 + 角色契约 + freeze criteria + post-freeze policy 写入 PROJECT_STATE v0.5「MVP FROZEN」权威块（+ Last Updated 条目）、backlog（Last Updated + §7 Summary MVP-001 行）、README（版本表 + 角色映射注）；closure record = 本文件；一个 docs/state commit（parent 7eeaf83，未 amend，未 push）。
- **MVP Freeze criteria（Requirement 14 最小集 + audit F1-F6 收口，全部为真）**：
  1. A0-A5 accepted / synced（v0.4 FROZEN 基线 + A0-A5 = CLOSED / COMPLETE / SYNCED；origin/main = 7eeaf83，0/0）
  2. 标准 TASK intake works（TASK 契约 + parser + immutable snapshot，A0-A5 全程实证）
  3. Bridge task transfer works（v0.4 FROZEN，RW-008/RW-012/RW-003/RW-016 SOLVED）
  4. execution / validation / review / REPORT loop works（Hermes / WorkBuddy / Codex stages + REPORT + Copy Report）
  5. basic recovery works（--resume-from / soft+force cancel / dead-runner 检测 / state recovery）
  6. basic risk / model / cost / fallback safeguards work（risk contract / A3+A4 窄域 routing / A0 Paid Guard / A5 CLOSED fallback+Cost Gate）
  7. authoritative state consistent（PROJECT_STATE + backlog + README 本次收口为 MVP FROZEN 表述）
  8. repository synced（local == origin/main == 7eeaf83，ahead/behind 0/0）
  9. Planner handoff exists（Drive Emergency Planner Handoff〔TASK 上下文事实〕+ GitHub backup/2026-09-05-pre-mvp-freeze 恢复分支〔local + origin 实测存在，cd2e056〕+ repo handoffs〔docs/internal/handoffs/〕+ 本 closure record 即可作新 Planner 上下文）
  10. no open MVP-blocking issue（RW-013 OPEN = 文档纪律问题非运行缺陷；RW-009 PARTIAL = 恢复链未在 v0.5 全状态实练——audit 判定均 non-blocking；A5 Formalization UX 措辞张力由本 record 澄清，见 §4）
- **Post-freeze change policy（Requirement 15）**：v0.5 MVP freeze 之后，新 framework capability = **opt-in only**——必须先经用户显式 scope 批准才进入 mainline；不自动继续旧 roadmap future phases（A6 / A4+ / non-MVP 列表均不自动排程）。

## 3. v0.5 MVP capability boundary（= sufficient；audit 能力图 grounded）

| # | MVP 能力 | 判定（audit，grounded） |
|---|---|---|
| 1 | task intake / 标准 TASK | MVP_SUFFICIENT（TASK 契约 + parser + immutable snapshot + Risk 字段） |
| 2 | Bridge | MVP_SUFFICIENT（热键 intake / duplicate 状态卡片 / project binding / listener 自恢复） |
| 3 | routing | MVP_SUFFICIENT（Route 机器字段三态权威 + legacy heuristic；非法 fail-closed） |
| 4 | executor | MVP_SUFFICIENT（Hermes stage，A0 guard + A5 fallback 覆盖，resume 兼容） |
| 5 | validator | MVP_SUFFICIENT（WorkBuddy stage + 独立复核契约 + bounded transient retry） |
| 6 | reviewer | MVP_SUFFICIENT（Codex stage，按 Route 可选） |
| 7 | REPORT / planner handoff | MVP_SUFFICIENT（REPORT.md + result json 聚合 + Copy Report） |
| 8 | task state | MVP_SUFFICIENT（task.json lifecycle + runtime health） |
| 9 | recovery / resume | MVP_SUFFICIENT（--resume-from / soft+force cancel / dead-runner 检测） |
| 10 | risk routing | MVP_SUFFICIENT（Risk 显式 provenance + tier-floor；非 LOW 走人工显式） |
| 11 | model routing（窄域） | MVP_SUFFICIENT（A3 LOW Hermes FREE + A4 LOW/MEDIUM WorkBuddy economic + 默认 configured model） |
| 12 | cost guard | MVP_SUFFICIENT（A0 Paid Guard fail-closed task-scoped 一次性授权 + A5 Cost Gate 同 authority） |
| 13 | fallback | MVP_SUFFICIENT（A5 = CLOSED / COMPLETE / SYNCED：one-fallback + FREE runtime + paid gate + authorized paid runtime） |
| 14 | git / sync closure | MVP_SUFFICIENT（git_changed_files 观察 + origin/main 同步纪律 + 恢复资产） |
| 15 | role replaceability | MVP_SUFFICIENT（语义已按角色契约分离；映射 + 替换路径由本 freeze record 文档化闭合——零 runtime 变更） |

- **MVP_MISSING = 无**（audit 结论）。辅助能力（project boundary check / task archive / session rollover / duplicate protection / model observability / discovery）= 全部 MVP_SUFFICIENT。
- 本表不重开 A0-A5 实现 scope：A0-A5 = CLOSED / COMPLETE / SYNCED 历史不可变；v0.4 = FROZEN 基线。

## 4. 正式边界（freeze 后保持）

| 边界 | 内容 | 状态 |
|---|---|---|
| v0.5 MVP | 个人轻量 Agent 协作 / 调度 MVP（产品定义 / 主目标 / 能力边界 / freeze criteria 见 §1-§3 与 PROJECT_STATE「MVP FROZEN」块） | **FROZEN（freeze closure record 备妥；final route acceptance = PENDING——WorkBuddy / Codex legs 按 route 阶段执行）** |
| A6 | health scoring / quarantine / long-term availability tracking / automatic requalification / calibration / ongoing observation policy | NOT_REQUIRED_FOR_MVP（A6_FULL_SCOPE_NOT_REQUIRED_FOR_MVP；最小子集 = 空）；future scope 保持、非自动排程 |
| A4+ | HIGH / CRITICAL WorkBuddy economic routing（前置 prerequisite evidence 不存在）；Codex / multi-agent economic routing（前置 = 独立 scope/design） | NOT_REQUIRED_FOR_MVP；不扩张；既有 prerequisite 记录保持 |
| non-MVP 列表 | long-term memory system / self-learning / large DAG orchestration / agent marketplace / distributed workers / distributed queue / large dashboard / platform UI（含 Desktop Shell / Tray 扩展 RW-004/RW-010/RW-015、RW-014 遗留 Tray 停止项）/ plugin ecosystem / complex autonomous scheduling / complex long-term model scoring / large-scale subagent system / general-purpose Agent OS / platform expansion / 图形化 Cost Gate UX 对话框 | 一律 NOT_REQUIRED_FOR_MVP——**不是**自动 FUTURE phases；须用户日后显式重开 scope |
| A0-A5 | A0-A5 已接受实现 + closure 记录（A0 = CLOSED，A3/A4/A5 = CLOSED / COMPLETE / SYNCED） | 历史不可变；不重开 |
| v0.4 | FROZEN / RELEASE READY 基线（1d3771fe） | 冻结历史不变 |

- **角色契约（抽象，MVP 定义一部分）与 concrete mappings（implementation）**：Planner（输出 TASK / 验收 REPORT / 决定下一步）= ChatGPT；Executor（执行任务、产出结果）= Hermes；Validator（独立复核，不默认相信前序结果）= WorkBuddy；Reviewer（代码 / 架构 / 高风险只读审查）= Codex（按路由需要）。映射可替换——满足同一角色契约的产品替换任一角色**不**重定义 AAF MVP；替换集中改动点 = router.py ALLOWED_ROUTE_AGENTS / adapters.py ROLE_INSTRUCTIONS + CLI 发现 + 上游依赖表 / runner.py 按 route agent 赋 role。
- **历史 vs current 区分**：A0-A5 单元记录 / A5 CLOSED 块 / v0.4 冻结基线 / 旧 roadmap planned & historical scope = 历史不改写（REQUIRED_BEFORE_A5_CLOSE 9 项原文不重写）；current MVP-required scope = 本 record + PROJECT_STATE「MVP FROZEN」块。
- **A5 Formalization UX 措辞澄清（audit §未完成项建议，不重写 Formalization 块原文）**：PROJECT_STATE「A5 Scope Formalization」示例句曾将「图形化 Cost Gate UX」列入 A5 formal scope 措辞；A5 closure 权威 completion boundary = REQUIRED_BEFORE_A5_CLOSE 9 项（不含 UX 项）——本 record 明确该 UX 判 NOT_REQUIRED_FOR_MVP（freeze 边界之外），A5 不重开。

## 5. 变更清单（docs-only）

- `docs/internal/PROJECT_STATE.md`：
  - 头部 Last Updated 新增本任务条目（原 FINALIZE-001 条目降级为「此前更新」链首，历史不重写）；
  - v0.5 块新增「MVP FROZEN」权威条目块（产品定义 / 主目标 / 能力边界 sufficient / MVP_EXIT_READY / A6_FULL_SCOPE_NOT_REQUIRED_FOR_MVP / A4+ = NOT_REQUIRED_FOR_MVP / non-MVP 列表非自动 FUTURE phases / 角色契约 vs concrete mappings / freeze criteria / post-freeze opt-in policy / 历史 vs current 区分 / A5 UX 措辞澄清 / closure record）。
- `docs/internal/AAF_MASTER_BACKLOG.md`：
  - 头部 Last Updated 新增本任务条目（原 FINALIZE-001 条目顺延为「此前更新」链首，历史不重写）；
  - §7 Summary 新增 MVP-001 行（FROZEN / CLOSED (v0.5)）。
- `README.md`：
  - 版本表：v0.5 行 = PERSONAL MVP FROZEN；「v0.5+」过时句刷新为 A6 / A4+ / 其他新 capability 未启动 + opt-in only；
  - 角色表下加注：Executor/Validator/Reviewer mappings = replaceable implementations（满足同一角色契约不重定义 MVP）。
- 本 closure record（docs/internal/AAF-v0.5-MVP-FREEZE-CLOSE-001-REPORT.md，新增）
- **零** `.py` / registry / test / json / economics / qualification 文件变更（Requirement 17；git diff 验证见 §7）

## 6. 验收对照（Requirement 1-20）

- Req 1（先读权威文档再编辑）：PROJECT_STATE.md / AAF_MASTER_BACKLOG.md / README.md / v0.5 roadmap-status 材料 / audit evidence（.aaf/AAF-v0.5-MVP-BOUNDARY-EXIT-AUDIT-001/REPORT.md + hermes_result.md）全部只读 ✅
- Req 2（MVP 产品定义）：§1 item 2 + PROJECT_STATE「MVP FROZEN」块 ✅
- Req 3（primary MVP goal 成文）：同上（减 copy/paste 与 relay，保持 task -> execution -> validation -> review -> report -> planner 循环）✅
- Req 4（当前 MVP 能力边界 = sufficient，不重开 A0-A5）：§3 能力表 + 边界表 ✅
- Req 5（MVP_EXIT_READY）：§1 item 4 + 「MVP FROZEN」块 ✅
- Req 6（A6_FULL_SCOPE_NOT_REQUIRED_FOR_MVP）：§1 item 4 + 「MVP FROZEN」块 ✅
- Req 7（A4+ = NOT_REQUIRED_FOR_MVP）：§1 item 4 + 「MVP FROZEN」块 ✅
- Req 8（non-MVP 列表显式 bounded）：§4 边界表 + 「MVP FROZEN」块（audit Req 9 列表逐项收录）✅
- Req 9（non-MVP ≠ 自动 FUTURE phases，须显式用户 scope 批准）：§2 post-freeze policy + 「MVP FROZEN」块明确表述 ✅
- Req 10（历史 roadmap 保留 + 历史 vs current 区分）：§1 item 6 + §4 ✅
- Req 11（角色契约抽象）：§4 + 「MVP FROZEN」块（Planner / Executor / Validator / Reviewer 抽象定义）✅
- Req 12（concrete mappings = implementations 非永久身份）：README 角色注 + §4 ✅
- Req 13（替换 concrete product 不重定义 MVP）：README 角色注 + §4 + 「MVP FROZEN」块 ✅
- Req 14（minimal MVP freeze criteria）：§2 criteria 1-10 ✅
- Req 15（post-freeze change policy）：§2 ✅
- Req 16（保留 9 项 REQUIRED_BEFORE_A5_CLOSE / A0-A5 历史 / runtime 语义 / PRE_ALLOWED_UNTRACKED）：§7 验证（byte-identical + untracked 保持）✅
- Req 17（零 runtime / test / routing / economics / qualification 变更）：docs-only；git diff 验证 ✅
- Req 18（一个 docs/state commit，未 amend，未 push）：本 commit 满足 ✅
- Req 19（WorkBuddy 独立验证）：**PENDING——route 后续 leg**（不超前声称；按 A2-A5 closure 惯例单独执行）⏳
- Req 20（Codex review / APPROVE）：**PENDING——route 后续 leg**（同上；历史教训 A5-CLOSE-001-FIX-001：precheck/超前声称不构成 final APPROVE）⏳
- Unresolved Issues：无 executor-side unresolved（route legs PENDING = 流程未决项，非 runtime/functional defect；无 MVP-blocking issue 被识别）

## 7. 验证证据（Executor 实测）

- `git status`：baseline HEAD = `7eeaf830b882294fe44fec403eaf38cad2760321` = origin/main（ahead/behind 0/0）；本任务变更 = 3 个文档修改（docs/internal/PROJECT_STATE.md、docs/internal/AAF_MASTER_BACKLOG.md、README.md）+ 1 个新增 closure record（docs/internal/AAF-v0.5-MVP-FREEZE-CLOSE-001-REPORT.md）；untracked 仅既有 PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs`），未删除未 clean（编辑脚本暂存于 .aaf/ 下，随 .aaf/ untracked 保留不入 commit）
- `git diff --stat`：仅 3 个 markdown 文档修改 + 1 个新增 markdown record；无 `.py` / registry / test / json / economics / qualification 变更
- 一致性检查（全部通过）：
  1. PROJECT_STATE.md 头部 Last Updated 最外层条目 = 本任务（AAF-v0.5-MVP-FREEZE-CLOSE-001）；「MVP FROZEN」权威块位于 v0.5 段 A5 CLOSED 块之后；
  2. AAF_MASTER_BACKLOG.md 头部 Last Updated 最外层条目 = 本任务；§7 Summary 含 MVP-001 行；
  3. README.md 版本表含 v0.5 = PERSONAL MVP FROZEN 行；角色映射注存在；
  4. REQUIRED_BEFORE_A5_CLOSE 9 项原文未改写（PROJECT_STATE.md 内该短语出现次数与 baseline 一致，diff 未触及「A5 Scope Formalization」块）；
  5. A6 / A4+ future scope 边界（「Explicitly outside A5」/「A5 CLOSED」outside bullet）文本不变；
  6. 历史证据保持：A5 CLOSED 块 / A0-A5 单元记录 / Last Updated「此前更新」链 / v0.4 段 = 全部原样保留；
  7. EOL 保持会话起点状态（PROJECT_STATE.md = CRLF、AAF_MASTER_BACKLOG.md = LF、README.md = LF、本 record = CRLF——file 命令验证）；diff --check 无 whitespace 错误；
  8. 角色映射注与「MVP FROZEN」块均明确：concrete mappings = implementations、替换不重定义 MVP。
- 本任务为纯文档任务（Requirement 17），未新增/修改任何测试；无需运行测试套件（零代码变更，无回归面）——同 A3/A4/A5 close 先例

## 8. 后续（route legs，未执行）

> 本 §8 为流程占位，如实记录待执行 legs；不接受超前声称（A5-CLOSE-001-FIX-001 教训）。

- WorkBuddy 独立验证（Req 19 检查面）：MVP boundary 与 Audit evidence 一致 / 无 runtime 能力被虚假声称缺失 / 无 A6/A4+ scope 被静默保留为 mandatory MVP work / 抽象角色与 concrete mappings 区分 / 历史证据完整 / 无 runtime 文件变更——route 后续执行。
- Codex review（Req 20 检查面）：freeze 无 unsupported claims / 项目未被静默扩张 / post-freeze scope 需显式用户重开——route 后续执行。
- 若 route legs 产生 blocking finding：按惯例开 FIX；若通过：按 A2-A5 closure 惯例收口 final accepted 状态并 sync（另行任务，本 record 到时更新）。
