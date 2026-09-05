# AAF-v0.5-PH1-PORTABILITY-CLOSE-001 — Close v0.5 PH-1 planner / role portability hardening（PH-1 Closure Report）

> Task: 基于已完成并同步的 Planner Bootstrap / Role Contracts 与 AAF-v0.5-PH1-ROLE-REPLACEMENT-GAP-AUDIT-001 的只读源码审计结论，正式收口 v0.5 Portability Hardening / PH-1
> Executor: Hermes（AAF Executor stage）2026-09-05
> Status: **PH-1 = CLOSED / COMPLETE（closure record 备妥——本 executor leg = 权威状态更新 + closure record + 一个 docs commit；final route acceptance = PENDING——WorkBuddy 独立验证 + Codex review 按 route 阶段执行，未超前声称 route verdicts）**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex review 为接受前置条件，按 route 阶段执行）——route 当前状态：**Hermes executor leg = COMPLETED（本 record + 一个 docs commit）；WorkBuddy = PENDING；Codex = PENDING（见 §6）**
> Current Authority（TASK 给定 + 本 executor 实测）：main == origin/main == `ac6c489bf63441e6f2572f5a704ee291102ad99e`（ahead/behind = 0/0）；START_HERE_FOR_NEW_PLANNER.md / docs/internal/AAF_ROLE_CONTRACTS.md 存在且已同步；Planner Bootstrap / Role Contracts route legs 已接受——WorkBuddy = PASS_WITH_WARNING（非阻断）+ Codex = APPROVE（证据：.aaf/AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001/REPORT.md / workbuddy_result.md / codex_result.md；ac6c489 已由 AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-SYNC-001 同步 origin/main）；Gap Audit = AAF-v0.5-PH1-ROLE-REPLACEMENT-GAP-AUDIT-001（只读审计，决策 = **PH1_RUNTIME_GAPS_NOT_BLOCKING**）；Unresolved Issues = None
> Snapshot: `.aaf/AAF-v0.5-PH1-PORTABILITY-CLOSE-001/TASK.snapshot.md`（immutable execution snapshot，Task Hash 见该文件 + context_manifest；Runner 已冻结）

## 1. 结论（先给结论）

1. ✅ **PH-1 = CLOSED / COMPLETE（docs-only 收口）**：本 executor leg 完成全部 docs/state 交付物——权威
   状态更新（PROJECT_STATE.md / AAF_MASTER_BACKLOG.md / START_HERE_FOR_NEW_PLANNER.md）+ 本 closure
   record + 一个 docs commit。**零 runtime / code / test / registry / economics / qualification 行为变化**；
   未新增任何 runtime 能力；未实现 plugin system；未把 FUTURE_CONVENIENCE_ONLY 项升级为当前 blocker。
2. ✅ **决策记录 = PH1_RUNTIME_GAPS_NOT_BLOCKING**（Gap Audit 唯一决策，Requirement 3）：3 项
   PORTABILITY_GAP（GAP-PH1-01/02/03）经只读源码审计全部属实且描述准确（代码证据行号在 HEAD ac6c489 下
   仍精确匹配），但**没有任何一项阻塞实际角色替换**；无需 runtime hardening 即可收口。
3. ✅ **替换分类记录（Requirement 4/5）**：Planner = **CONTRACT_REPLACEABLE_NOW**（框架外角色，今天即可被
   新 ChatGPT / DeepSeek / Gemini / 其他 LLM / Agent 零 runtime 变更接任，条件是满足 Planner Contract）；
   Executor = **REPLACEABLE_WITH_ADAPTER**（当前实现 Hermes）；Validator = **REPLACEABLE_WITH_ADAPTER**
   （当前实现 WorkBuddy）；Reviewer = **REPLACEABLE_WITH_ADAPTER**（当前实现 Codex）——三者今天不能零改动
   替换，替换 = 集中单点 adapter 编辑（router.py 白名单 / adapters.py ROLE_INSTRUCTIONS + CLI 分支 + 上游
   依赖表 / runner.py 模型层分支）+ 全量回归 + fresh-runner 验证（契约文档 §6-§8）。
4. ✅ **3 项 PORTABILITY_GAP 定义原文保留（Requirement 6）**：未删除、未弱化、未改写（AAF_ROLE_CONTRACTS.md
   §9/§11 与 PROJECT_STATE 相关表述零改动）；仍登记为 non-blocking portability gaps。
5. ✅ **non-blocking gap ≠ required runtime work（Requirement 7/8）**：显式区分——3 项 gap 为「替换时才
   暴露 / fail-safe 行为正确 / resume 路径存在」的 portability 登记项；**无任何 PH-1 runtime 实现任务是
   必需的**；静态 role→adapter 注册表 / 重构 = FUTURE_CONVENIENCE_ONLY，非当前必需、不得当作当前必需工作。
6. ✅ **更换 Planner 不依赖旧 ChatGPT 对话历史（Requirement 9/10）**：新 Planner 从仓库权威 bootstrap——
   START_HERE_FOR_NEW_PLANNER.md（§3 恢复顺序）+ PROJECT_STATE 顶部 + AAF_MASTER_BACKLOG + AAF_ROLE_CONTRACTS
   + 最近 `.aaf/<Task ID>/REPORT.md` / handoff；**AAF 不托管在 ChatGPT 内**（Bridge = 本机程序，Planner 永远
   在框架外经 TASK 文本参与）。
7. ✅ **替换路径高层记录（Requirement 11）**：role contract（满足角色契约 A + D 列）-> bounded adapter
   integration（集中单点编辑，集中且位置可枚举）-> compatibility verification（全量 pytest 零回归 +
   fresh-runner N+1 正反场景 + 真实小 TASK 全链）-> 沿用既有 AAF TASK / stage / REPORT authority。
8. ✅ **current mappings 保留为 current implementations only（Requirement 12）**：ChatGPT / Hermes /
   WorkBuddy / Codex 继续作为当前实现记录；替换任一 concrete 产品不重定义 AAF（满足同一角色契约即可）。
9. ✅ **out of scope 显式保持（Requirement 13）**：plugin marketplace / dynamic arbitrary Agent discovery /
   dynamic package installation / 大型通用 Agent registry / Agent OS-platform expansion / Memory system /
   DAG engine / A6 / A4+——全部未启动（v0.5 non-MVP 列表，进入 mainline 前须用户显式 scope 批准）。
10. ✅ **Portability Hardening 整体状态（Requirement 14/15）**：PH-1 = **CLOSED / COMPLETE**；PH-2 = **NOT
    STARTED**；PH-3 = **NOT STARTED**；本任务**未启动** PH-2 / PH-3，未重开 A6 / A4+，frozen MVP 保持 intact。
11. ✅ **权威状态已更新**：PROJECT_STATE.md（Last Updated 新条目 + v0.5 块「PH-1 Portability Hardening
    CLOSE」条目块）、AAF_MASTER_BACKLOG.md（Last Updated 新条目 + §7 Summary PH-001 行转 CLOSED /
    COMPLETE）、START_HERE_FOR_NEW_PLANNER.md（头部更新链 + §0 当前状态句刷新：PH-1 = CLOSED / COMPLETE、
    PH-2/PH-3 = NOT STARTED、当前无进行中 PH 任务）（Requirement 2）。
12. ✅ **docs/state-only + 恰好一个 docs commit（Requirement 16/17）**：零 runtime/source/test/router/
    adapter 修改；一个 commit，未 amend，未 push；PRE_ALLOWED_UNTRACKED 保留（Requirement 18）。
13. ⏳ **WorkBuddy 独立验证 + Codex review = route 后续 legs（PENDING）**（Requirement 19/20）：本 executor
    leg 未执行、未声称（经验教训 = A5-CLOSE-001-FIX-001：不得超前声称 route verdicts）。

## 2. Scope Authority（本任务边界）

- ✅ 属于：**v0.5 Portability Hardening / PH-1 正式收口**（docs/state closure；TASK 内嵌 scope authority；
  Planner Bootstrap / Role Contracts 已接受 + Gap Audit = PH1_RUNTIME_GAPS_NOT_BLOCKING 为收口依据）。
- ✅ 记录（不实现）：Planner / Executor / Validator / Reviewer 替换分类、3 项 PORTABILITY_GAP 的
  non-blocking 定性、替换路径高层、PH-2/PH-3 = NOT STARTED。
- ❌ 不是：v0.6；A6（health scoring / quarantine / requalification / calibration）；A4+（HIGH/CRITICAL
  WorkBuddy、Codex/multi-agent economic routing）；plugin system；agent marketplace；memory system；
  general Agent OS / platform expansion；静态 role→adapter 注册表 / 重构（FUTURE_CONVENIENCE_ONLY）。
- 本任务未启动任何上述 scope；未重开 A0-A5；未改变任何 runtime 语义；未实现任何 runtime hardening。

## 3. 变更清单（docs-only）

- 修改 `docs/internal/PROJECT_STATE.md`：Last Updated 新条目（PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001
  条目降级为「此前更新」链下一条，原文零改写）+ v0.5 段「PH-1 Portability Hardening」条目块后新增
  「PH-1 Portability Hardening CLOSE」条目块（PH-1 = CLOSED / COMPLETE / 决策 / 分类 / gap 保留 /
  无 runtime 任务 / PH-2·PH-3 = NOT STARTED / out of scope / closure record 指针）
- 修改 `docs/internal/AAF_MASTER_BACKLOG.md`：Last Updated 新条目 + §7 Summary PH-001 行状态转
  CLOSED / COMPLETE（标题补 closure record + Gap Audit 指针）
- 修改 `START_HERE_FOR_NEW_PLANNER.md`：头部更新链追加 CLOSE-001 条目（PH-1 = CLOSED / COMPLETE、
  PH-2/PH-3 = NOT STARTED）+ §0 任务记录行补 PH-1 收口记录指针 + §0「当前状态」句刷新（当前正进行 =
  PH-1 → PH-1 已收口、无进行中 PH 任务）
- 新增 `docs/internal/AAF-v0.5-PH1-PORTABILITY-CLOSE-001-REPORT.md`（本 closure record）
- **零** `.py` / registry / test / json / economics / qualification 文件变更（Requirement 16；git 验证见 §5）；
  AAF_ROLE_CONTRACTS.md 零改动（3 项 PORTABILITY_GAP 定义原文保留——Requirement 6）

## 4. 验收对照（Requirement 1-20）

- Req 1（先读再编辑）：START_HERE_FOR_NEW_PLANNER.md（全文）/ docs/internal/AAF_ROLE_CONTRACTS.md（全文）/
  docs/internal/PROJECT_STATE.md（顶部 Last Updated 链 + v0.5 段全文相关区）/ docs/internal/
  AAF_MASTER_BACKLOG.md（顶部 + §7 Summary）/ docs/internal/AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-
  001-REPORT.md（全文）/ Gap Audit 产物 = .aaf/AAF-v0.5-PH1-ROLE-REPLACEMENT-GAP-AUDIT-001/REPORT.md（+
  hermes_result.md 截断区以 artifact 为准）/ bootstrap route legs 产物（.aaf/AAF-v0.5-PH1-PLANNER-
  BOOTSTRAP-ROLE-CONTRACTS-001/REPORT.md + workbuddy_result.md + codex_result.md）全部只读 ✅
- Req 2（权威状态标记 PH-1 = CLOSED / COMPLETE）：PROJECT_STATE Last Updated + v0.5 块 CLOSE 条目 +
  backlog Last Updated + §7 PH-001 行 + START_HERE 状态句 ✅
- Req 3（记录 PH1_RUNTIME_GAPS_NOT_BLOCKING）：本 record §1.2 + PROJECT_STATE CLOSE 条目 + backlog 条目 ✅
- Req 4（Planner = CONTRACT_REPLACEABLE_NOW）：本 record §1.3 + PROJECT_STATE CLOSE 条目 ✅
- Req 5（Executor / Validator / Reviewer = REPLACEABLE_WITH_ADAPTER）：同上 ✅
- Req 6（3 项 PORTABILITY_GAP 定义原文保留）：AAF_ROLE_CONTRACTS.md §9/§11 零改动（git diff 无该文件）✅
- Req 7（non-blocking gap ≠ required runtime work）：本 record §1.5 + PROJECT_STATE CLOSE 条目显式区分 ✅
- Req 8（无 PH-1 runtime 实现任务）：同上显式成文 ✅
- Req 9（更换 Planner 不要求恢复旧 ChatGPT 对话历史）：本 record §1.6 + PROJECT_STATE CLOSE 条目 +
  START_HERE §0（既有 + 刷新句）✅
- Req 10（AAF 不托管在 ChatGPT 内）：同上 ✅
- Req 11（替换路径高层）：本 record §1.7 + PROJECT_STATE CLOSE 条目 ✅
- Req 12（ChatGPT / Hermes / WorkBuddy / Codex = current implementations only）：本 record §1.8 +
  PROJECT_STATE CLOSE 条目；既有映射记录（契约文档 §1 / START_HERE §1）零改动 ✅
- Req 13（out of scope：plugin marketplace / 动态 Agent 发现 / 动态包安装 / 大型 registry / Agent OS /
  Memory / DAG / A6 / A4+）：本 record §1.9/§2 + PROJECT_STATE CLOSE 条目 ✅
- Req 14（PH-1 = CLOSED / COMPLETE；PH-2 = NOT STARTED；PH-3 = NOT STARTED）：本 record §1.10 +
  PROJECT_STATE CLOSE 条目 + backlog 条目 + START_HERE 状态句 ✅
- Req 15（不启动 PH-2/PH-3）：本任务零实现、零启动 ✅
- Req 16（不修改 runtime/source/test/router/adapter 行为）：git diff name-only = 3 修改 + 1 新增 markdown，
  零 `.py`/test/registry/json ✅
- Req 17（恰好一个 docs commit / 不 amend / 不 push）：本 commit 满足（§5）✅
- Req 18（PRE_ALLOWED_UNTRACKED 保留）：.aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs
  保持 untracked 未动（编辑脚本存 .aaf/ 下，随 untracked 保留不入 commit）✅
- Req 19（WorkBuddy 独立验证：closure 与 Gap Audit 证据一致 / 无即插即用虚假声称 / Planner bootstrap 不依赖
  当前对话 / 3 gap 表述准确 / 无 runtime 变更 / PH-2·PH-3 未静默启动）：**PENDING——route 后续 leg** ⏳
- Req 20（Codex 独立 review：PH-1 closure 技术可信 / 无多余 runtime 实现强制 / 替换声称有界 / 无
  plugin/platform scope creep / APPROVE）：**PENDING——route 后续 leg** ⏳
- Unresolved Issues：无 executor-side unresolved（route legs PENDING = 流程未决项，非 runtime/functional
  defect；无 MVP-blocking issue 被识别）

## 5. 验证证据（Executor 实测）

- `git status` / `git rev-parse HEAD`：baseline HEAD = `ac6c489bf63441e6f2572f5a704ee291102ad99e` =
  origin/main（ahead/behind 0/0）；本任务变更 = 3 个文档修改（docs/internal/PROJECT_STATE.md、docs/internal/
  AAF_MASTER_BACKLOG.md、START_HERE_FOR_NEW_PLANNER.md）+ 1 个新增文档（docs/internal/AAF-v0.5-PH1-
  PORTABILITY-CLOSE-001-REPORT.md）；untracked 仅既有 PRE_ALLOWED_UNTRACKED 常驻项，未删除未 clean
- `git diff --stat` / `name-only`：仅 markdown 文档；无 `.py` / registry / test / json / economics /
  qualification 变更；`git diff --check` 无 whitespace 错误
- numstat：全 0 deletions（PROJECT_STATE / backlog / START_HERE 变更 = 纯插入 + backlog §7 单行状态行
  replace + START_HERE 单句 replace，无历史行删除）——「MVP FROZEN」块 / A5 CLOSED 块 / A0-A5 / v0.4 冻结
  基线 / REQUIRED_BEFORE_A5_CLOSE 9 项原文 / Last Updated 历史链 / AAF_ROLE_CONTRACTS.md §9·§11 gap 表 =
  零改写
- 一致性检查（全部通过）：
  1. PROJECT_STATE Last Updated 最外层条目 = 本任务；v0.5 段 PH-1 条目块之后新增 CLOSE 条目块；
  2. AAF_MASTER_BACKLOG Last Updated 最外层条目 = 本任务；§7 Summary PH-001 行 = CLOSED / COMPLETE；
  3. START_HERE §0 当前状态句 = PH-1 CLOSED / COMPLETE、PH-2/PH-3 NOT STARTED、无进行中 PH 任务；
  4. EOL 保持既有惯例：PROJECT_STATE.md = CRLF、AAF_MASTER_BACKLOG.md = LF、START_HERE = CRLF、
     新 record = CRLF（python 逐字节计数验证）；
  5. 3 项 PORTABILITY_GAP 定义（GAP-PH1-01/02/03）逐字保留（AAF_ROLE_CONTRACTS.md 未列入 diff）；
  6. 无「任意 Agent 即插即用」类 unsupported claim（本 record 全部替换声明带分类 + 边界）
- 本任务为纯文档任务（Requirement 16），未新增/修改任何测试；无需运行测试套件（零代码变更，无回归面）
  ——同 A3/A4/A5 close / freeze-close / PH-1 bootstrap 先例

## 6. 后续（route legs，未执行）

> 本 §6 为流程占位，如实记录待执行 legs；不接受超前声称（A5-CLOSE-001-FIX-001 教训）。

- WorkBuddy 独立验证（Req 19 检查面）：closure 记录与 Gap Audit 证据（PH1_RUNTIME_GAPS_NOT_BLOCKING）一致 /
  无 universal plug-and-play 虚假声称 / Planner bootstrap 确实不依赖当前对话（仓库权威可独立恢复上下文）/
  3 项 gap 表述仍然准确（未删除未弱化）/ 零 runtime 文件变更 / PH-2·PH-3 未静默启动——route 后续执行。
- Codex review（Req 20 检查面）：PH-1 closure 技术可信 / 无多余 runtime 实现仍被强制 / 角色替换声称有界
  （REPLACEABLE_WITH_ADAPTER ≠ 即插即用）/ 无 plugin/platform scope creep / APPROVE——route 后续执行。
- 若 route legs 产生 blocking finding：按惯例开 FIX；若通过：按 A2-A5 / MVP-freeze closure 惯例收口 final
  accepted 状态并 sync（另行任务，届时更新权威状态记录）。
