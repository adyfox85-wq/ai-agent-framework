# AAF-v0.5-A5-CLOSE-001 — Close A5 Fallback / Escalation / Cost Gate Phase（Closure Record）

> Task: Close A5 fallback / escalation / Cost Gate phase（将 A5 从 STARTED / NOT CLOSED 正式更新为 CLOSED / COMPLETE，并记录权威 closure evidence；docs-only closure）
> Executor: Hermes（AAF Executor stage）2026-09-05
> Status: **A5 = CLOSED / COMPLETE（closure record / 状态更新已备妥——proposed closure record；final closure route acceptance = PENDING，见 §6）**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件，按 route 阶段执行）——**route 当前状态：WorkBuddy = PENDING / external 429；Codex = REQUEST_CHANGE from PRECHECK（final Codex closure 未执行）**
> Baseline: HEAD = origin/main = `e9056104213a9bc227e294a740d0467471362585`（AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001；local == origin/main，ahead/behind = 0/0；未 push）
> Snapshot: `.aaf/AAF-v0.5-A5-CLOSE-001/TASK.snapshot.md`（immutable execution snapshot）
> Fix: 2026-09-05 **AAF-v0.5-A5-CLOSE-001-FIX-001**（docs-only 状态收口）：按 Codex precheck（AAF-v0.5-A5-CLOSE-CODEX-PRECHECK-001 = REQUEST_CHANGE）唯一 blocker——closure documentation 超前声称 final WorkBuddy 独立验证 + Codex APPROVE 已完成——本 record 如实化为：A5 closure record 备妥（proposed closure record，依 audit A5_READY_TO_CLOSE 正式化）+ final closure route acceptance = PENDING（WorkBuddy 独立 closure validation 因外部 429 未完成 → 本任务 terminal WAITING；final Codex closure 未执行）；WorkBuddy closure verdict = PENDING / external 429；Codex 当前结果 = REQUEST_CHANGE from PRECHECK（precheck 不构成 final Codex APPROVE）；Unresolved 状态见 §6

## 1. 结论（先给结论）

1. 📋 **A5 closure record / 状态更新已备妥（docs-only，proposed closure record）**：
   A5 = **CLOSED / COMPLETE（record 状态）**——2026-09-05，AAF-v0.5-A5-CLOSE-001
   依已完成的 A5 Closure Audit（AAF-v0.5-A5-CLOSURE-AUDIT-001 = **A5_READY_TO_
   CLOSE**，REQUIRED_BEFORE_A5_CLOSE 9 项全部 SATISFIED，Hermes 审计 + WorkBuddy
   独立复核）正式化 closure record / 状态更新（docs-only）；**final closure route
   acceptance = PENDING**（final WorkBuddy 独立 closure validation 因外部 429
   未完成 → 本任务 terminal WAITING；final Codex closure 未执行——见 §6）；本
   record 为 proposed / formal closure record，不构成 final accepted / synced
   closure 状态（2026-09-05 FIX-001 如实化）。
2. ✅ **closure boundary 与正式化权威一致**：closure boundary = A5 Scope Formalization
   块（PROJECT_STATE.md v0.5「A5 Scope Formalization」块，唯一权威定义）——
   **bounded, auditable fallback / escalation / Cost Gate foundation**，
   REQUIRED_BEFORE_A5_CLOSE 9 项 closure requirements（原文不重写）全部由已接受的
   A5-001 / A5-002 / A5-003 / A5-004 交付实现并验证；A5 formal scope 内无 remaining
   gap。
3. ✅ **无完成 scope 重开**：A5 Scope Formalization / A5-001..004 / A5 Closure Audit
   的历史 artifacts / verdict 不可变、不重写；本任务不重新打开任何 A5 implementation
   gap，不新增实现。
4. ✅ **A5 整体 closure 与历史 A5-001..004 实现记录区分保持**：A5 整体状态 =
   CLOSED / COMPLETE（closure record 状态，proposed closure record——见上文
   item 1）；A5-001..004 各实现单元的历史记录（PROJECT_STATE A5 块各
   「A5 实现状态」bullet / 各单元 REPORT / Last Updated 嵌套条目 / backlog CAP-003
   行内 dated 叙述）作为历史证据保留，未改写任何执行事实。
5. ✅ **A6 / A4+ future scope 保持 outside、未进入**：A6（health scoring /
   quarantine / long-term availability tracking / automatic requalification /
   calibration / ongoing observation policy）与 A4+（HIGH / CRITICAL WorkBuddy
   routing、broader Codex / multi-agent routing）= future scope NOT IMPLEMENTED，
   本任务不实现、不标记实现、未把其责任并入 A5 closure。
6. ✅ **零行为变化**：docs-only——未修改任何 runtime / code / test / model registry /
   economics / qualification 数据（Requirement 11）；无功能删除、无未来能力放弃。
7. ✅ 未 push（Requirement 10：no push，review 后同步）。
8. ⏳ **final closure route = PENDING（2026-09-05 FIX-001 如实化）**：WorkBuddy 独立
   closure validation 因外部 429（WorkBuddyRetriesExhausted）未完成 → 本任务
   terminal WAITING；Codex precheck（AAF-v0.5-A5-CLOSE-CODEX-PRECHECK-001）=
   REQUEST_CHANGE——唯一 blocker = 超前验证状态表述（已由 FIX-001 收口），precheck
   不构成 final Codex APPROVE；final Codex closure 待 WorkBuddy validation 完成后
   执行（route 详情见 §6）。

## 2. Closure Decision

- **前置决策**：AAF-v0.5-A5-CLOSURE-AUDIT-001（只读审计，Hermes -> WorkBuddy）=
  权威判定 **A5_READY_TO_CLOSE**——9 项 REQUIRED_BEFORE_A5_CLOSE 逐项 SATISFIED
  （证据含源码位置核对：fallback_contract.py / fallback_runtime.py /
  fallback_paid_gate.py / runner.py 语义 + 测试矩阵）；audit 未识别 A5 runtime
  defect；final closure acceptance 留待独立 route closure task（本任务）的
  WorkBuddy 独立验证 + Codex closure（当前 PENDING，见 §6）。
- **本任务执行（2026-09-05 FIX-001 如实化）**：备妥 A5 closure record / 状态更新
  ——A5 = STARTED / NOT CLOSED → **CLOSED / COMPLETE（proposed closure record，
  docs-only closure record，2026-09-05 AAF-v0.5-A5-CLOSE-001）**；**final closure
  route acceptance = PENDING**（非 final accepted / synced closure 状态）。
- **验收交付映射**（closure requirements 满足证据，全部为已接受 + 已同步工作）：
  - A5 Scope Formalization（completion boundary 权威化 + 9 项 requirements）= `f6c577d`
    （+ FIX-003 `cc404c1` READY_TO_START token 收口）
  - A5-001（fallback decision + audit contract foundation）= `5255d8b`（APPROVED + SYNCED）
  - A5-002（FREE/LOCAL_FREE fallback runtime）= `a0ac326` + FIX-001 `8b3c24b` +
    FIX-002 `b082fef`（APPROVED + SYNCED）
  - A5-003（paid escalation Cost Gate）= `32c4bbe` + FIX-001 `4c2ebf9` +
    FIX-002 `927d965`（APPROVED + SYNCED）
  - A5-004（authorized paid fallback runtime）= `e905610`（APPROVED，本任务 baseline HEAD）
  - A5 Closure Audit（A5_READY_TO_CLOSE）= `.aaf/AAF-v0.5-A5-CLOSURE-AUDIT-001/REPORT.md`
- 本任务不重新打开任何 A5 implementation gap；历史 artifacts / verdict 不可变、不重写。

## 3. 关闭的 A5 closure capability（formal scope，已交付并验证）

| # | Requirement（REQUIRED_BEFORE_A5_CLOSE 原文，不重写） | 满足证据（已接受交付） |
|---|---|---|
| 1 | fallback trigger / failure classification 明确 | A5-001 `fallback_contract.py`（8 类 failure taxonomy ⊇ 5 minimum classes，TRIGGER_CAPABLE/BLOCKED/PAID_ESCALATION 分区，class↔decision 双向契约）+ A5-002 runtime evidence-based `classify_failure` |
| 2 | 每 affected stage 最多 1 次 automatic model-level fallback | A5-001 one-fallback budget（`MAX_AUTOMATIC_FALLBACKS_PER_STAGE=1` 编入 schema + validator 强制）；A5-002 FREE attempt 至多一次；A5-004 paid invocation 与 FREE 共享同一 one-attempt budget（count_used==0 才准入）；无 chain/loop |
| 3 | transport retry 与 model fallback 必须分开（不同层、不同 authority、分别审计） | A5-001 `transport_retry_count` 独立字段、不计入 budget（RW-027 transport retry 分层分离）；A5-002/003/004 runtime 只在原始 invocation 失败后触发 |
| 4 | qualified candidate 存在时允许 free/local -> free/local fallback | A5-002 FREE/LOCAL_FREE automatic fallback runtime（仅 A0 Paid Guard `ALLOWED_FREE` 准入；A1/A2 qualification/capability 闸复用） |
| 5 | capability/qualification 必须先于 cost（沿用 A1/A2 gate 顺序与词汇，不建第二套 eligibility） | A5-001 decision contract 复用 A2 selector 候选资格（A1 registry/risk 闸）；A5-003/004 paid candidate 资格 = A1/A2 过闸 + distinct from original + budget 未耗尽 |
| 6 | 无安全 fallback 时 fail closed（如实 FRAMEWORK_ERROR / 明确 no-fallback reason；绝不静默换模型、绝不静默退回 Auto） | A5-002/003/004 全部 fail-closed 分支（no-candidate / gate BLOCKED / FAIL_CLOSED / malformed → 零 invocation、原始失败保留、WAITING）；audit closure 失败 → 输出不被接受 + audit_closure_error surface（A5-002 FIX-001/FIX-002、A5-004 Req 10） |
| 7 | free -> paid 不得静默发生；paid escalation 必须经过现有 Paid Guard / Cost Guard authority（task-scoped one-time authorization，fail closed） | A5-003 paid escalation Cost Gate（既有 A0 Paid Guard 唯一付费授权 authority；AUTHORIZED / BLOCKED / FAIL_CLOSED；exact task/stage/model/provider scope；FIX-001/FIX-002）；A5-004 仅 gate AUTHORIZED + 复验后恰一次 paid invocation；零第二付费授权系统、A0 replay 拒绝保持 |
| 8 | fallback 不得静默跨越 role / risk / capability boundary | 候选资格复用 A2 selector（role 适用 / capability sufficiency / qualification）；A5-004 调用前以既有 A0/A5 authorities 复验（gate record validator + task/stage 归属 + candidate ∈ contract eligible 集 + distinct from original） |
| 9 | 所有 fallback / escalation decision 可审计，并保留最终实际模型 provenance | A5-001 authoritative audit record schema；A5-002 `fallback_runtime.json`（decision_kind=fallback_runtime_audit）；A5-003 `paid_escalation_gate.json`；A5-004 `paid_fallback_runtime.json`（decision_kind=paid_fallback_runtime_audit）——全部 validate fail-closed，含 no-silent-fallback / no-silent-paid evidence 与 final actual model/provider |

- 能力链：`fallback-eligible 失败 -> failure classification -> 有合格 FREE 候选
  （ALLOWED_FREE）则恰一次 FREE fallback；无 FREE 候选 -> A0 Paid Guard exact-scope
  authorization 判断（AUTHORIZED/BLOCKED/FAIL_CLOSED）-> AUTHORIZED 时恰一次 paid
  fallback invocation -> 权威 audit 组装/校验/持久化成功才接受输出；任何 fail-closed
  分支零第二模型 + 原始失败保留`。
- A5 formal scope 内 **无 remaining gap**（依 Formalization 界定的 9 项 closure
  requirements 逐项核对，见上表；A5 Closure Audit 独立复核确认）。

## 4. 正式边界（关闭后保持）

| 边界 | 内容 | 状态 |
|---|---|---|
| A5 | fallback / escalation / Cost Gate foundation（closure boundary = PROJECT_STATE v0.5「A5 Scope Formalization」块，唯一权威定义；9 项 REQUIRED_BEFORE_A5_CLOSE 原文不重写） | **CLOSED / COMPLETE（closure record 备妥，proposed closure record；final closure route acceptance = PENDING——2026-09-05 AAF-v0.5-A5-CLOSE-001，FIX-001 如实化）** |
| A6 | health scoring / quarantine / long-term availability tracking / automatic requalification / calibration / ongoing observation policy | future scope；NOT IMPLEMENTED；未进入（A5 closure 之外） |
| A4+ | HIGH / CRITICAL WorkBuddy routing（HIGH 前置 = T2-or-better WorkBuddy 候选 prerequisite qualification evidence）；broader Codex / multi-agent routing（前置 = 独立 scope/design） | future scope；NOT IMPLEMENTED；未进入（A5 closure 之外） |
| A0-A4 | A0 Paid Guard / A3 Hermes LOW FREE routing / A4 WorkBuddy LOW + MEDIUM economic routing | CLOSED / COMPLETE 历史不可变；不重开 |

- Hermes broader routing 在 A5 closure 之外（A3 = CLOSED / COMPLETE / SYNCED，不重开）。
- A5-004 语义收口保持：free→paid 必经既有 Paid Guard / Cost Guard 唯一授权 authority
  （task-scoped one-time authorization，fail closed），A5 不建第二套付费授权系统。

## 5. 变更清单（docs-only）

- `docs/internal/PROJECT_STATE.md`：
  - 头部 Last Updated 新增本任务条目（原 A5-004（PAID-FALLBACK-RUNTIME-001）条目顺延为
    「此前更新」链首，历史不重写）；
  - 「A5 Scope Formalization」权威块新增 2026-09-05 状态 bullet（A5 = CLOSED /
    COMPLETE——completion boundary / 9 项 requirements 保持唯一权威定义不变；上方各
    「A5 实现状态」bullet 的 STARTED / NOT CLOSED = 各实现单元任务时点历史状态记录）；
  - v0.5 块新增「A5 CLOSED」权威条目块（closure 判定 / 交付能力（A5-001..004）/
    A6 + A4+ future scope 保持 outside / A5 整体 closure 与历史实现单元记录区分保持 /
    closure record）；
  - Next mainline 阶段状态图 A5 边界句加注 A5 = CLOSED / COMPLETE（2026-09-05）。
- `docs/internal/AAF_MASTER_BACKLOG.md`：
  - 头部 Last Updated 新增本任务条目（A5 = CLOSED / COMPLETE，9 项 closure
    requirements 满足映射 A5-001..004）；
  - CAP-003 title / Status / Current Implementation / Remaining Gap / Do Not Forget
    + RW-027 Related + CAP-004 Do Not Forget + §7 Summary CAP-003 行：A5 状态结论
    全部同步为 CLOSED / COMPLETE（实现单元 dated 历史叙述保留；A6 = NOT STARTED、
    A4+ = future scope NOT IMPLEMENTED 保持）。
- 本 closure record（docs/internal/AAF-v0.5-A5-CLOSE-001-REPORT.md）
- **零** `.py` / registry / test / json / economics / qualification 文件变更
  （Requirement 11；git diff 验证见 §7）

## 6. 验收对照

- A5 = CLOSED / COMPLETE（closure record 备妥，proposed closure record）✅
  （PROJECT_STATE.md v0.5「A5 CLOSED」块 + 本 record §2/§4；final closure route
  acceptance = PENDING，见下）
- closure boundary 与正式化权威一致（PROJECT_STATE「A5 Scope Formalization」块，
  bounded auditable fallback / escalation / Cost Gate foundation，9 项原文不重写）✅
- 无完成 scope 重开（A5-001..004 / Formalization / Closure Audit 历史不改写；A0-A4
  不重开）✅
- A5 整体 closure 与历史 A5-001..004 实现记录区分保持 ✅
- A6（health/quarantine/requalification/calibration）与 A4+（HIGH/CRITICAL
  WorkBuddy、Codex/multi-agent routing）future scope 保持 NOT IMPLEMENTED、未进入 ✅
- closure evidence grounded：A5 Scope Formalization + A5-001..004 + A5 Closure Audit
  （A5_READY_TO_CLOSE）✅
- docs-only（零 runtime/code/test/registry/economics/qualification 变更）✅
- WorkBuddy 独立验证（final closure）：**PENDING / external 429**——CLOSE-001
  route WorkBuddy leg = WorkBuddyRetriesExhausted（RETRIES_EXHAUSTED：attempt 1/2
  empty output exit=0；stderr tail = 429 频率限制，2026-09-05 05:14 UTC+8 重置）
  → 本任务 terminal WAITING；无 WorkBuddy closure verdict 可用
- Codex（final closure）：**PENDING**——当前可用结果 = Codex precheck
  （AAF-v0.5-A5-CLOSE-CODEX-PRECHECK-001）= **REQUEST_CHANGE**，唯一 blocker =
  closure documentation 超前验证状态表述（已由 AAF-v0.5-A5-CLOSE-001-FIX-001
  收口）；precheck 不构成 final Codex APPROVE；final Codex closure 待 WorkBuddy
  validation 完成后执行
- Unresolved Issues（closure-process 未决项）：**final WorkBuddy 独立 closure
  validation + final Codex closure = PENDING**（见上）——与 runtime/functional
  defect 区分：**无 A5 runtime defect 当前被识别**（closure audit + Codex precheck
  均未发现 runtime 缺陷）；closure route 完成后按惯例复查
- 一个 closure commit（parent e905610，未 amend）；未 push

## 7. 验证证据（Executor 实测）

- `git status`：baseline HEAD = `e9056104213a9bc227e294a740d0467471362585` =
  origin/main（ahead/behind 0/0）；本任务变更仅 docs/internal/ 下 3 个文件（2 修改 +
  1 新增 closure record）；untracked 仅既有 PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、
  `AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs`），未删除未 clean
- `git diff --stat`：仅 2 个 markdown 文档修改 + 1 个新增 markdown record；无 `.py` /
  registry / test / json / economics / qualification 变更
- 聚焦文档/状态一致性检查（本任务自带检查脚本，全部通过）：
  1. PROJECT_STATE.md 与 AAF_MASTER_BACKLOG.md 均含权威「A5 = CLOSED / COMPLETE +
     2026-09-05 AAF-v0.5-A5-CLOSE-001」记录（头部 Last Updated 最外层条目 = 本任务）；
  2. A5 Scope Formalization 块 REQUIRED_BEFORE_A5_CLOSE 9 项原文（items 1–9）逐项存在、
     未改写；「Explicitly outside A5」A6/A4+ 边界文本不变；
  3. 结论位置无残留 stale current-state 表述（terminal「NOT CLOSED / COMPLETE」
     结论已在 CAP-003/CAP-004 各行翻转/被新结论取代；剩余 STARTED / NOT CLOSED
     出现位置均为 dated 历史记录：A5 实现状态 bullet、头部嵌套「此前更新」条目、
     单元 REPORT）；
  4. 历史证据保持：A5-001..004 与 CLOSURE-AUDIT-001 任务记录在 PROJECT_STATE（A5 块
     bullets + 嵌套条目）与 backlog（CAP-003/004 行内 dated 叙述）中全部保留；
  5. 两个文件 UTF-8 / CRLF 保持原状（git diff 行数 = 期望插入行数，无整文件行尾改动）
- 本任务为纯文档任务（Requirement 11），未新增/修改任何测试；无需运行测试套件
  （零代码变更，无回归面）——同 A3-CLOSE-001 / A4-CLOSE-001 / SCOPE-FORMALIZATION-001
  先例
