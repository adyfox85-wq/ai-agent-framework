# AAF-v0.5-A5-SCOPE-FORMALIZATION-001 — Formalize A5 fallback and Cost Gate completion boundary（Decision / Scope-Formalization Record）

> Task: Formalize A5 fallback / escalation / Cost Gate completion boundary（补齐 A5 缺失的正式 completion boundary，使后续 fallback / escalation / Cost Gate 实现有明确范围和关闭标准；docs-only scope decision，不实现任何 runtime 行为）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **A5 = READY_TO_START**（不是 CLOSED / COMPLETE / SYNCED，也未 STARTED；正式实现 = 独立 Planner-approved task）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件，按 route 阶段执行）
> Baseline: HEAD = origin/main = `639bea86ff35fcd2c2fb3cecb0f7ebed2f527761`（未 push）

## 1. 结论（先给结论）

1. ✅ **A5 completion boundary 已正式定义**（唯一权威定义 = PROJECT_STATE.md v0.5
   「A5 Scope Formalization」块）：**A5 = bounded, auditable fallback / escalation /
   Cost Gate foundation**（有界、可审计的 fallback / escalation / Cost Gate 基础）。
2. ✅ **REQUIRED_BEFORE_A5_CLOSE（9 项 closure requirements）已逐项正式界定**
   （见 §3）——全部为后续 A5 实现的关闭前置，本任务只界定、不实现。
3. ✅ **one-fallback rule / free fallback rule / paid escalation rule / 审计要求
   已正式化**（见 §3）——A5 实现不得 fallback chain/loop、不得绕过既有 Paid
   Guard / Cost Guard、不得静默 free→paid。
4. ✅ **A4+ / A6 显式 outside A5**：A6（health scoring / quarantine / long-term
   availability tracking / automatic requalification / calibration / ongoing
   observation policy）与 A4+（HIGH / CRITICAL WorkBuddy routing、broader
   Codex / multi-agent routing）保持独立、未进入（Requirement 3/4）。
5. ✅ **A5 = READY_TO_START**（Requirement 5/6）：未标记 CLOSED / COMPLETE；
   前置 blocker = A5 completion boundary 缺失（A5-READINESS-001 判定
   A5_NEEDS_SCOPE_FORMALIZATION）已由本界定消除，无剩余实现前置 blocker。
6. ✅ **零行为变化**：docs-only——未修改任何 runtime / code / test / model
   registry / economics / qualification / Paid Guard 实现；未开始 A5 实现、
   A4+、A6（Requirement 7/8）；无功能删除、无未来能力放弃。

## 2. Prior Ambiguity（此前歧义，记录不改写历史）

- A5-READINESS-001（read-only audit，Hermes final decision =
  A5_NEEDS_SCOPE_FORMALIZATION，WorkBuddy PASS_WITH_WARNING，Codex APPROVE）
  确认：每个权威文档只把 A5 描述为 **label + 示例列表**（「fallback /
  escalation / Cost Gate UX：automatic fallback、free→paid switching、user
  confirmation dialog、图形化 Cost Gate UX」——A3-CLOSE REPORT §4、A4-CLOSE
  REPORT §4、PROJECT_STATE A3/A4 边界句），**没有文档定义**：
  - A5 completion boundary / closure requirements；
  - 触发条件与 failure classification；
  - automatic model-level fallback 的次数上限（与 transport retry 的关系）；
  - free fallback 与 paid escalation 的资格与授权边界；
  - REQUIRED vs optional vs A6 / A4+ 的分离；
  - fallback/escalation 审计与最终模型 provenance 要求。
- 同 A4 在 AAF-v0.5-A4-SCOPE-FORMALIZATION-001 之前缺失 completion boundary
  的 gap 同型（docs/internal/AAF-v0.5-A4-SCOPE-FORMALIZATION-001-REPORT.md）。
- 可被误读的风险点：① 现有 WorkBuddy retry（workbuddy_retry.py / RW-027，
  同一 invocation 的 transport retry）被当成「已有 fallback 层」；② CAP-004
  Remaining Gap 的 free-to-free fallback / 图形化 Cost Gate UX 被当作泛化
  A1+ 事项而非有边界的 A5 scope；③ 「A5/A6 未进入、边界不变」被误读为
  completion boundary 已定义。本任务消除这三类歧义。

## 3. Formal Decision（正式界定）

**A5 completion boundary（formal scope）**：A5 = **bounded, auditable fallback /
escalation / Cost Gate foundation**。A3/A4 close 期示例列表（automatic
fallback、free→paid switching、user confirmation dialog、图形化 Cost Gate UX）
全部落在本正式 scope 内——是 A5 类能力的示例，不是开放标签。

**当前实现事实（boundary 依据，零变化）**：当前没有 model-level fallback；
现有 WorkBuddy retry 只是同一 invocation 的 transport retry（同模型同 args，
绝不换模型/provider/付费层级）；Paid Guard（A0）保持 fail-closed、task-scoped、
one-time authorization；A3/A4 no-silent-fallback 契约保持（fallback_attempted /
fallback_used 恒 false）。

**REQUIRED_BEFORE_A5_CLOSE（A5 closure requirements——A5 实现必须全部满足
后方可正式关闭；本任务只界定、不实现）**：

| # | Requirement（REQUIRED_BEFORE_A5_CLOSE） | 正式语义 |
|---|---|---|
| 1 | fallback trigger / failure classification 明确 | 最小 failure classes 见下；无分类不得触发 fallback |
| 2 | 每个受影响 stage 最多 1 次 automatic model-level fallback | one-fallback rule；无第二次换模型尝试 |
| 3 | transport retry 与 model fallback 必须分开 | 不同层、不同 authority、分别审计（RW-027 ≠ A5 fallback） |
| 4 | qualified candidate 存在时允许 free/local → free/local fallback | 免费候选间回退限于已合格者 |
| 5 | capability/qualification 必须先于 cost | 沿用 A1/A2 gate 顺序与词汇，不创建第二套 eligibility 判定 |
| 6 | 无安全 fallback 时 fail closed | 如实 FRAMEWORK_ERROR / 明确 no-fallback reason；绝不静默换模型或退回 Auto |
| 7 | free → paid 不得静默发生 | 必须经现有 Paid Guard / Cost Guard authority（task-scoped one-time authorization，fail closed） |
| 8 | fallback 不得静默跨越 role / risk / capability boundary | 跨界 = 显式决策 + 显式记录，绝不静默 |
| 9 | 所有 fallback / escalation decision 可审计，并保留最终实际模型 provenance | 见下方 audit artifact 最小字段 |

**Minimum failure classes（fallback trigger 分类基线）**：transport/runtime
failure；model unavailable / invocation failure；capability/qualification
insufficiency；quality/validation failure；paid escalation required。

**Automatic fallback rule（one-fallback rule）**：每 affected stage 最多 1 次
model-level fallback；existing same-model transport retry（RW-027 层）不计入
该 1 次预算；**A5 不允许 fallback chain / loop**（无 A→B→C 链式回退、无循环）。

**Free fallback rule**：只有已满足该 role/risk/capability 要求且已 QUALIFIED
的其他候选才可作为 fallback（A1 is_usable_candidate 语义原样适用）；**FREE
仅表示价格，不代表 qualification**。

**Paid escalation rule**：**不建立第二套付费授权系统**；任何 paid escalation
必须继续服从现有 task-scoped Paid Guard / Cost Guard（A0），并保持 fail
closed（A5 只消费该 authority，不绕过、不复制、不扩大授权范围）。

**Auditability（Required authoritative audit artifact 最小字段）**：stage /
role / risk；original model / provider；trigger / failure class；fallback
candidate；fallback attempted / used；paid escalation required；authorization
outcome（when applicable）；final actual model / provider；evidence that no
silent fallback occurred。

**A5 状态**：**READY_TO_START**（**不是** CLOSED / COMPLETE / SYNCED，也未
STARTED——本任务为 docs-only scope decision，未开始任何 A5 实现；前置 blocker
= A5 completion boundary 缺失（A5-READINESS-001 判定 A5_NEEDS_SCOPE_
FORMALIZATION）已消除，无剩余实现前置 blocker；正式实现启动 = 独立
Planner-approved task，按项目惯例经 WorkBuddy 独立验证 + Codex APPROVE）。

**Explicitly outside A5（A5 closure 不含以下任何项；本任务不实现、不进入）**：

- **A6**：health scoring / quarantine / long-term availability tracking /
  automatic requalification / calibration / ongoing observation policy。
- **A4+**：HIGH / CRITICAL WorkBuddy routing；broader Codex / multi-agent
  routing（既有 prerequisite 记录保持）。
- **A0-A4 不重开**：A0 Paid Guard、A3 Hermes LOW FREE routing、A4 WorkBuddy
  LOW + MEDIUM economic routing 已关闭，历史不可变。

## 4. Reason（理由摘要）

1. A5-READINESS-001 的独立 audit 已证明 A5 只有 label + 示例列表、无
   completion boundary——与 A4 正式化前同型；不正式化则后续 fallback 实现
   无法判定完成、无法约束范围（scope 膨胀风险：任何「换模型重试」都可能被
   当作 A5）。
2. transport retry（RW-027，已 SOLVED）与 model-level fallback 是不同层——
   不显式分离，后续实现可能把 retry 预算与 fallback 预算混算、或把 retry
   误报为 fallback，破坏 one-fallback rule 与审计语义。
3. free→paid / escalation 的授权 authority 已由 A0 Paid Guard 定义（fail
   closed、task-scoped、one-time）；A5 若建立第二套付费授权即违反 A0 closure
   boundary 与 no-silent-paid-fallback 纪律。
4. A6（health/quarantine/自动再资格化/校准）与 A4+（HIGH/CRITICAL/Codex
   routing）已有独立归属与 prerequisite——绑入 A5 会让 scope 在无前置时膨胀。

## 5. 变更清单（docs-only）

- `docs/internal/PROJECT_STATE.md`：头部 Last Updated 新增本任务条目（原
  A4-CLOSE-001 条目顺延为「此前更新」链首）；「Next mainline」A4 边界句 A5
  提及处加注（A5 completion boundary / READY_TO_START 指针）；A4 CLOSED 块
  「A5/A6 保持 NOT STARTED、未进入（边界不变）」后新增 A5 状态更新注记
  （READY_TO_START + 「边界不变」指 phase 归属与实现状态，不改写历史块）；
  §0 v0.5 块新增「A5 Scope Formalization」权威块（formal purpose /
  REQUIRED_BEFORE_A5_CLOSE 9 项 / minimum failure classes / one-fallback
  rule / free fallback rule / paid escalation rule / audit artifact 字段 /
  READY_TO_START / A6 + A4+ outside / 措辞收口）。
- `docs/internal/AAF_MASTER_BACKLOG.md`：头部 Last Updated 新增本任务条目；
  CAP-003 全套行更新（title / Status / Current Implementation 尾 / Remaining
  Gap / Do Not Forget——A5 = READY_TO_START、completion boundary 见
  PROJECT_STATE「A5 Scope Formalization」块、A5 实现 NOT STARTED）；RW-027
  Related + Remaining Gap（transport retry ≠ A5 model-level fallback 分层
  分离，retry 不计入 one-fallback 预算）；CAP-004 Remaining Gap + Do Not
  Forget（free-to-free fallback / 图形化 Cost Gate UX = A5 formal scope，
  消费既有 Paid Guard / Cost Guard、不建第二套付费授权）；§7 Summary CAP-003
  行同步。
- 本 decision record（docs/internal/AAF-v0.5-A5-SCOPE-FORMALIZATION-001-REPORT.md）
- **零** `.py` / registry / test / economics / qualification / Paid Guard
  文件变更（Requirement 7；git diff 验证见 §7）

## 6. 验收对照

- A5 completion boundary 显式且内部一致（PROJECT_STATE v0.5「A5 Scope
  Formalization」块 + 本 record §3）✅
- REQUIRED_BEFORE_A5_CLOSE 与 future / optional / A4+ / A6 scope 明确分离 ✅
- one-fallback rule / free fallback rule / paid escalation rule / 审计要求
  全部保留（规则完整编入权威块与本 record）✅
- A4+ / A6 保持独立、未进入；A0-A4 未重开 ✅
- 零 runtime / code / test / registry / economics / qualification / Paid
  Guard 行为变化（docs-only）✅
- 无功能静默删除（无功能删除、无未来能力放弃，显式声明）✅
- A5 = READY_TO_START（不是 CLOSED / COMPLETE / STARTED；实现未开始）✅
- WorkBuddy 独立验证：route 阶段执行，verdict 记录于本任务 REPORT
- Codex APPROVE：route 阶段执行
- Unresolved Issues = None
- 未 push（Requirement：no push）

## 7. 验证证据（Executor 实测）

- `git status`：tracked 变更仅 docs/internal/ 下 3 个本任务文件；untracked 仅
  既有 PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、
  `scripts/start_bridge_hidden.vbs`）+ 本任务临时脚本（已删除，不入库）
- `git diff --stat`：仅 2 个 markdown 文档修改 + 1 个新增 markdown record；无
  `.py` / registry / test / json / cost_guard 变更
- 本任务为纯文档任务（Requirement 1/2/3），未新增/修改任何测试；无需运行
  测试套件（零代码变更，无回归面）
- baseline HEAD = `639bea86ff35fcd2c2fb3cecb0f7ebed2f527761` 记录于本任务
  Context；origin/main = same（ahead/behind = 0/0）
