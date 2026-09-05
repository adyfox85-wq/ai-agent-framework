# AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001 — Formalize Planner bootstrap and replaceable role contracts（PH-1 Report）

> Task: 在已冻结的 v0.5 PERSONAL MVP 上增加最小 portability hardening（docs-only）：建立新 Planner 仓库接管入口 + 正式定义 Planner / Executor / Validator / Reviewer 四角色最小兼容契约与 Agent 替换流程
> Executor: Hermes（AAF Executor stage）2026-09-05
> Status: **PH-1 = STARTED（docs-only deliverable 备妥——本 executor leg = 三个新文档 + 三个权威状态文档更新 + 一个 docs commit；final route acceptance = PENDING——WorkBuddy 独立验证 + Codex review 按 route 阶段执行，未超前声称 route verdicts）**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex review 为接受前置条件，按 route 阶段执行）——route 当前状态：**Hermes executor leg = COMPLETED（本 record + 一个 docs commit）；WorkBuddy = PENDING；Codex = PENDING（见 §6）**
> Baseline: HEAD = origin/main = `0c5dfadda6e952adda5ce072c22896dcd765a091`（AAF-v0.5-MVP-FREEZE-CLOSE-001；local == origin/main，ahead/behind = 0/0；v0.5 PERSONAL MVP = FROZEN / CLOSED / COMPLETE / SYNCED；恢复分支 backup/2026-09-05-v0.5-mvp-frozen 同 commit）
> Snapshot: `.aaf/AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001/TASK.snapshot.md`（immutable execution snapshot，Task Hash 见该文件 + context_manifest；Runner 已冻结）

## 1. 结论（先给结论）

1. ✅ **PH-1 = STARTED（用户显式批准的 v0.5 Portability Hardening）**：本 executor leg 完成全部 docs-only
   交付物——新 Planner 接管入口 + 四角色最小兼容契约 + 替换评估 / 分类 / 最小替换流程 / PORTABILITY_GAP
   登记 + 权威状态更新。**零 runtime / code / test / registry / economics / qualification 行为变化**。
2. ✅ **仓库入口已建立**：`START_HERE_FOR_NEW_PLANNER.md`（根目录）——新 Planner 不需要任何旧聊天历史即可
   理解 AAF / 当前冻结状态 / 角色与映射 / 权威文件读取顺序 / TASK 生成（AAF_TASK_BEGIN/END）/ Bridge
   intake / REPORT 返回 authority / SUCCESS / WAITING / REQUEST_CHANGE / FAILED 语义 / WAITING 不原样重跑 /
   安全与 frozen scope 规则 / 角色替换诚实评估 / 恢复点与 handoff 资产（Requirement 3/4）。
3. ✅ **四角色正式契约**：`docs/internal/AAF_ROLE_CONTRACTS.md`（新增 durable contract）——Planner /
   Executor / Validator / Reviewer 各自 A=REQUIRED / B=OPTIONAL / C=current implementation /
   D=replacement compatibility requirements；concrete mappings（ChatGPT / Hermes / WorkBuddy / Codex）
   与角色身份显式区分；"替换任一 concrete 产品不重定义 AAF"显式成文（Requirement 5-12）。
4. ✅ **runtime 分类与替换评估（诚实，不过度声称）**：Planner = **CONTRACT_REPLACEABLE_NOW**（今天可被
   DeepSeek / 其他 LLM 零 runtime 变更替换）；Executor / Validator / Reviewer = **REPLACEABLE_WITH_ADAPTER**
   （Hermes / WorkBuddy / Codex 今天**不能零改动替换**，替换 = 集中单点 adapter 编辑 + 全量回归）；
   **CURRENTLY_HARD_CODED = 无**（有代码证据，见契约文档 §6-§7；"无 hard-coded" ≠ 即插即用，已显式声明
   边界）（Requirement 13/14）。
5. ✅ **最小安全替换流程 + PORTABILITY_GAP + PH-1 gap table**：每角色最小替换流程（登记授权 → 契约核对 →
   备份 → 单点编辑 → 全量回归 + fresh-runner → 收口）；3 项有代码证据的 concrete gap（GAP-PH1-01/02/03，
   全部 non-blocking，最小未来修复方向成文；本任务未实现任何修复）（Requirement 15/17/18）。
6. ✅ **未构建 plugin ecosystem / 动态 adapter 加载 / marketplace**（Requirement 16/21 显式遵守，见契约文档 §10）。
7. ✅ **权威状态已更新**：PROJECT_STATE.md（Last Updated 新条目 + v0.5 块 PH-1 条目）、AAF_MASTER_BACKLOG.md
   （Last Updated 新条目 + §7 Summary PH-001 行）、README.md（新 Planner 入口指针）——显式记录：
   Portability Hardening 由用户重开（PH-1 显式 scope 批准）、PH-1 started、frozen MVP intact、
   本 hardening 不重开 A6/A4+、无旧 roadmap phase 自动激活（post-freeze opt-in 不变）（Requirement 19）。
8. ✅ **既有 MVP freeze 记录与历史证据全部保留**：「MVP FROZEN」块 / A0-A5 / A5 CLOSED / v0.4 冻结基线 /
   REQUIRED_BEFORE_A5_CLOSE 9 项原文 / Last Updated 历史链 = 未改写（Requirement 20；git diff 验证见 §5）。
9. ✅ **docs/state-only**：零 runtime / source / test / router / adapter 行为变化；恰好一个 docs commit，
   未 amend，未 push（Requirement 21/22）。
10. ⏳ **WorkBuddy 独立验证 + Codex review = route 后续 legs（PENDING）**：本 executor leg 未执行、未声称
    （Requirement 23/24 为接受前置条件；经验教训 = A5-CLOSE-001-FIX-001：不得超前声称 route verdicts）。

## 2. Scope Authority（本任务边界）

- ✅ 属于：用户明确批准的 **v0.5 Portability Hardening / PH-1**（TASK 内嵌 scope authority）。
- ❌ 不是：v0.6；A6（health scoring / quarantine / requalification / calibration）；
  A4+（HIGH/CRITICAL WorkBuddy、Codex/multi-agent economic routing）；plugin system；agent
  marketplace；memory system；general Agent OS / platform expansion。
- 本任务未启动任何上述 scope；未重开 A0-A5；未改变任何 runtime 语义。

## 3. 变更清单（docs-only）

- 新增 `START_HERE_FOR_NEW_PLANNER.md`（仓库根目录；新 Planner 接管入口，Requirement 3/4）
- 新增 `docs/internal/AAF_ROLE_CONTRACTS.md`（durable 角色契约：四角色 A/B/C/D + mapping + 分类证据 +
  替换评估 + 最小替换流程 + PORTABILITY_GAP + gap table，Requirement 5-18）
- 新增 `docs/internal/AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001-REPORT.md`（本 record）
- 修改 `docs/internal/PROJECT_STATE.md`：Last Updated 新条目（原 FREEZE-CLOSE-001 条目降级为「此前更新」
  链首，历史不重写）+ v0.5 块「MVP FROZEN」块后新增 PH-1 条目块（Requirement 19）
- 修改 `docs/internal/AAF_MASTER_BACKLOG.md`：Last Updated 新条目 + §7 Summary 新增 PH-001 行
- 修改 `README.md`：角色/顶部区域新增新 Planner 入口指针（指向 START_HERE_FOR_NEW_PLANNER.md）
- **零** `.py` / registry / test / json / economics / qualification 文件变更（Requirement 21；git 验证见 §5）

## 4. 验收对照（Requirement 1-24）

- Req 1（先读权威文档再编辑）：README.md / PROJECT_STATE.md / AAF_MASTER_BACKLOG.md /
  AAF_TASK_EXECUTION_POLICY.md / runner.py / adapters.py / router.py / bridge/intake.py / report.py /
  verdict_parser.py / templates/TASK.md / MVP freeze closure 材料（closure record + 「MVP FROZEN」块）全部只读 ✅
- Req 2（先验证实际架构再作 portability 声明）：分类与替换评估全部带代码证据（router.py:37 白名单 /
  adapters.py:23-27 ROLE_INSTRUCTIONS / adapters.py:486-543 run_agent CLI 分支 / adapters.py:215-226
  上游依赖表 / runner.py:509-681 模型层分支 / adapters.py:428-445 codex fallback）；无即插即用声称 ✅
- Req 3（仓库根入口 START_HERE_FOR_NEW_PLANNER.md）：已创建（根目录）✅
- Req 4（START_HERE 内容 22 项）：what AAF is / 冻结版本状态 / AAF 不在 ChatGPT 内 / git 仓库 = authority /
  Planner replaceable / 四抽象角色 / concrete mappings / 恢复上下文顺序 / 权威文件顺序 / TASK 生成 /
  AAF_TASK_BEGIN/END 要求 / Bridge intake / REPORT 返回 authority / SUCCESS/WAITING/REQUEST_CHANGE/FAILED /
  exit 0 ≠ 验收 / WAITING 不原样重跑 / report 后继续 / 安全 scope 规则 / frozen MVP + opt-in /
  角色替换方式 / recovery 资产位置 = 全部成文 ✅
- Req 5-10（四角色契约 + A/B/C/D）：AAF_ROLE_CONTRACTS.md §2-§5；Planner（输入 = user objective +
  authoritative state + latest REPORT；输出 = valid AAF TASK；职责 = planning/scope control/acceptance
  interpretation/next-task generation/不执行冒充）✅；Executor（immutable Task authority / assigned scope /
  evidence / structured stage result / execution authority 语义 / blocker 如实）✅；Validator（独立 inspect /
  不信 summary / 显式 nonblocking-blocking verdict / warning vs rework 区分）✅；Reviewer（独立审查 /
  APPROVE/REQUEST_CHANGE authority / 不静默修改 / blocker 显式）✅
- Req 11/12（mappings + 替换不重定义 AAF）：契约文档 §1 + START_HERE §1 显式成文 ✅
- Req 13（分类 + 证据）：契约文档 §6 表（每行代码证据）✅
- Req 14（DeepSeek / Hermes / WorkBuddy / Codex 今日替换评估）：契约文档 §7（诚实、不过度声称）✅
- Req 15（最小安全替换流程）：契约文档 §8 ✅
- Req 16（不建 plugin / dynamic loading / marketplace）：契约文档 §10 显式 out of scope；本任务零实现 ✅
- Req 17/18（PORTABILITY_GAP + PH-1 gap table）：契约文档 §9/§11（3 项 concrete、代码证据、non-blocking）✅
- Req 19（权威状态记录 PH-1 重开/started/MVP intact/不重开 A6/A4+/无自动 roadmap phase）：PROJECT_STATE
  Last Updated + v0.5 块 PH-1 条目 + backlog Last Updated ✅
- Req 20（MVP freeze 记录与历史证据保留）：§5 验证（byte-identical 抽查 + diff 范围）✅
- Req 21（docs/state-only）：git diff 验证（仅 3 修改 + 3 新增 markdown）✅
- Req 22（恰好一个 docs commit / 不 amend / 不 push）：本 commit 满足 ✅
- Req 23（WorkBuddy 独立验证）：**PENDING——route 后续 leg**（检查面 = bootstrap 对新 Planner 足够 /
  契约匹配 runtime 证据 / 无 unsupported plug-and-play 声称 / gap 分类准确 / frozen MVP 边界保持 /
  无 runtime 文件变更）⏳
- Req 24（Codex 独立 review / APPROVE）：**PENDING——route 后续 leg**（检查面 = role 抽象技术上可信 /
  替换声称 grounded / 不依赖本 ChatGPT 对话 / 无 plugin/platform scope 扩张；历史教训 A5-CLOSE-001-FIX-001：
  precheck/超前声称不构成 final APPROVE）⏳
- Unresolved Issues：无 executor-side unresolved（route legs PENDING = 流程未决项，非 runtime/functional
  defect；无 MVP-blocking issue 被识别）

## 5. 验证证据（Executor 实测）

- `git status`：baseline HEAD = `0c5dfadda6e952adda5ce072c22896dcd765a091` = origin/main（ahead/behind
  0/0）；本任务变更 = 3 个文档修改（docs/internal/PROJECT_STATE.md、docs/internal/AAF_MASTER_BACKLOG.md、
  README.md）+ 3 个新增文档（START_HERE_FOR_NEW_PLANNER.md、docs/internal/AAF_ROLE_CONTRACTS.md、
  docs/internal/AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001-REPORT.md）；untracked 仅既有
  PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs`），
  未删除未 clean（编辑脚本暂存于 .aaf/ 下，随 .aaf/ untracked 保留不入 commit）
- `git diff --stat`：仅 markdown 文档；无 `.py` / registry / test / json / economics / qualification 变更
- 一致性检查（全部通过）：
  1. PROJECT_STATE.md Last Updated 最外层条目 = 本任务（AAF-v0.5-PH1-...）；PH-1 条目块位于 v0.5 段
     「MVP FROZEN」块之后；FREEZE-CLOSE-001 条目降级为「此前更新」链首（原文未改写）；
  2. AAF_MASTER_BACKLOG.md Last Updated 最外层条目 = 本任务；§7 Summary 含 PH-001 行；
  3. README.md 含 START_HERE 入口指针；
  4. 「MVP FROZEN」权威块 / A5 CLOSED 块 / A0-A5 单元记录 / v0.4 冻结基线 / Last Updated 历史链 = 全部原样保留
     （git diff 只触及新增插入点，未删除任何历史行——逐行 diff 核对）；
  5. REQUIRED_BEFORE_A5_CLOSE 9 项原文未改写（PROJECT_STATE.md 内短语出现次数与 baseline 一致）；
  6. EOL 保持既有惯例：PROJECT_STATE.md = CRLF、AAF_MASTER_BACKLOG.md = LF、README.md = LF、
     新文档 = CRLF（file 命令验证）；diff --check 无 whitespace 错误；
  7. 分类表与替换评估全部显式带代码证据路径；无"任意 Agent 即插即用"类 unsupported claim
- 本任务为纯文档任务（Requirement 21），未新增/修改任何测试；无需运行测试套件（零代码变更，无回归面）
  ——同 A3/A4/A5 close / freeze-close 先例

## 6. 后续（route legs，未执行）

> 本 §6 为流程占位，如实记录待执行 legs；不接受超前声称（A5-CLOSE-001-FIX-001 教训）。

- WorkBuddy 独立验证（Req 23 检查面）：START_HERE bootstrap 是否足够让新 Planner 理解如何进入工作流 /
  角色契约是否与实际 runtime 证据一致 / 是否有 unsupported plug-and-play claim / gap 分类是否准确 /
  frozen MVP 边界是否保持 / 是否零 runtime 文件变更——route 后续执行。
- Codex review（Req 24 检查面）：role 抽象技术上是否可信 / 替换声称是否 grounded / portability 指令是否
  依赖当前 ChatGPT 对话 / 是否无 plugin/platform 架构 scope 扩张——route 后续执行。
- 若 route legs 产生 blocking finding：按惯例开 FIX；若通过：按 A2-A5 closure 惯例收口 final accepted
  状态并 sync（另行任务，本 record 到时更新）。
