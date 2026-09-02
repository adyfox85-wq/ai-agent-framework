# AAF-v0.5-A4-SCOPE-FORMALIZATION-001 — Formalize A4 Completion Boundary（Decision / Closure-Boundary Record）

> Task: Formalize A4 completion boundary（补齐 A4 缺失的正式 completion boundary，消除「future A4 work」对 HIGH / CRITICAL / multi-agent scope 的歧义；docs-only scope decision）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **A4 = READY_TO_CLOSE**（不是 CLOSED / COMPLETE / SYNCED；正式关闭 = 独立 Planner-approved closure task）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件，按 route 阶段执行）
> Baseline: HEAD = origin/main = `8730d0be80a7b79d5edee8a11c1376589485c38d`（未 push）

## 1. 结论（先给结论）

1. ✅ **A4 completion boundary 已正式定义**（唯一权威定义 = PROJECT_STATE.md v0.5
   「A4 Scope Formalization」块）：**A4 = WorkBuddy economic active routing
   foundation for LOW + MEDIUM risk**。
2. ✅ **A4 closure requirements 全部满足**（见 §3）——由已接受的 A4-001（LOW，
   commit 6ca78d9）+ A4-002（MEDIUM，commit 8730d0b）交付实现并验证（含 FIX-001，
   commit dfe0e01）→ **A4 = READY_TO_CLOSE**。
3. ✅ **HIGH / CRITICAL / multi-agent（Codex）routing 正式划归 A4+ future scope**：
   NOT IMPLEMENTED、本任务未实现；仅保留能力与 prerequisite 记录，未发明 A4+
   架构（Requirement 5）。
4. ✅ **歧义措辞已限定**：「future A4 work」「future A4-A6 work」「A4 =
   WorkBuddy/economic/multi-agent routing」等可误读为「HIGH 是 A4 close 前置 /
   CRITICAL 隐含 required / Codex 因 phase 名必须在 A4 实现」的表述已修正或加注
   指向权威定义（Requirement 4）。
5. ✅ **零行为变化**：docs-only——未修改任何 runtime / code / test / model
   registry / economics / qualification 数据；未开始 A4+ / A5 / A6
   （Requirement 6/7）；无功能删除、无未来能力放弃。

## 2. Prior Ambiguity（此前歧义，记录不改写历史）

- 文档曾用「future A4 work」「future A4-A6 work」「A4 = WorkBuddy/economic/
  multi-agent routing」描述 A4 范围（如 A3-close 边界句、A4-001/A4-002 交付块尾、
  CAP-003 行），但没有正式定义：
  - 哪些能力 REQUIRED_BEFORE_A4_CLOSE；
  - 哪些能力属于后续 A4+；
  - A4 在什么条件下可以正式关闭。
- 可被误读为：HIGH 实现是 A4 关闭前置；CRITICAL 因 risk progression 隐含 required；
  Codex routing 必须因「A4」phase 名在 A4 内实现。本任务消除这三类误读。

## 3. Formal Decision（正式界定）

**A4 completion boundary（closure capability）**：A4 = WorkBuddy economic active
routing foundation for LOW + MEDIUM risk。

**A4 closure requirements**（全部满足，逐项映射已接受交付）：

| # | Requirement | 满足证据 |
|---|---|---|
| 1 | LOW WorkBuddy economic active routing implemented | A4-001（6ca78d9）+ FIX-001（dfe0e01） |
| 2 | MEDIUM WorkBuddy economic active routing implemented | A4-002（8730d0b），复用同一 workbuddy_routing 决策链 |
| 3 | capability/qualification precedes economics | A2 selector 复用：capability sufficiency → qualification/usability → economics gate 顺序 |
| 4 | trustworthy economics fail closed | FRESH/完整/一致 才进经济排序；STALE/UNKNOWN/incomplete/contradictory fail closed |
| 5 | >=2 economically trustworthy candidates required for active selection | 少于 2 → routing_applied=false → CodeBuddy Auto |
| 6 | per-run --model works when authority applies | invocation 精确 `[-p --output-format text -y --model <winner>]`，恰好一个 --model |
| 7 | otherwise CodeBuddy Auto | Auto 保持时 artifact 不声称 routed_model |
| 8 | no silent fallback | fallback_used 恒 false；失败如实 FRAMEWORK_ERROR |
| 9 | authoritative active-routing artifact exists | workbuddy_active_routing.json（原子写，写失败 fail closed） |

**A4 状态**：**READY_TO_CLOSE**（正式关闭 = 独立 Planner-approved closure task，
按 A2/A3 惯例经 WorkBuddy 独立验证 + Codex APPROVE 后由 Planner 关闭）。

**A4+ future scope（NOT IMPLEMENTED；本任务不实现；仅保留能力与 prerequisite 记录）**：

- **HIGH WorkBuddy routing** → A4+。Reason：当前真实 WorkBuddy 候选仅 T4 资格
  （LOW probe 证据），HIGH 需要 T2-or-better 候选；未来实现前需先具备
  **T2-or-better WorkBuddy 候选的 prerequisite qualification evidence**，
  active routing 才有意义（decision 3 记录）。
- **CRITICAL WorkBuddy routing** → A4+。Reason：CRITICAL 需要 T1 floor 候选，
  当前 authority 无任何 T1/T0 证据；**从未是 A4 closure requirement**——本界定
  正式声明，避免 risk progression 隐含误读（decision 4 记录）。
- **multi-agent / Codex routing** → A4+。Reason：当前 authority（A1 registry /
  A2 selector / A3 active routing / A4 WorkBuddy routing）尚未定义 Codex
  candidate discovery、capability/qualification model、economic metadata source、
  per-run model-routing contract；未来实现前需**独立 scope/design prerequisite**
  （decision 5 记录）。
- **Hermes broader routing**：在 A4 closure 之外；A3 = CLOSED / COMPLETE / SYNCED
  不重开（decision 6 记录）。

**边界保持（decision 7）**：fallback / escalation / Cost Gate UX = A5；
health / quarantine / runtime requalification / observation / calibration = A6
（A5/A6 未进入、不变）。

## 4. Reason for Moving HIGH / CRITICAL / multi-agent to A4+（理由摘要）

1. A4-001/A4-002 已接受的实现只覆盖 LOW + MEDIUM WorkBuddy economic active
   routing；HIGH / CRITICAL / Codex 从未实现、从未验收——把它们留在 A4 closure
   词汇内会让「A4 关闭」悬置在未实现能力上，边界不可判定。
2. HIGH / CRITICAL 的 active routing 依赖更高 tier 候选的 qualification
   evidence（当前 registry 无 T1/T0 证据、WorkBuddy 候选最高仅 T4/T2 类 LOW 级
   证据），没有 evidence 前实现 active routing 无意义且违反 A1/A2 的
   evidence-only / fail-closed 纪律。
3. Codex / multi-agent routing 缺少 authority 级定义（discovery / capability /
   economics / per-run contract 四要素均未建立），把它绑进 A4 会让 scope 在无
   设计前置时膨胀；按项目惯例（A2+ / A4+ 前缀）划归 A4+ future scope，以独立
   scope/design prerequisite 为前提。

## 5. 变更清单（docs-only）

- `docs/internal/PROJECT_STATE.md`：头部 Last Updated 新增本任务条目（原 A4-002
  条目顺延为「此前更新」链首）；§0 v0.5 块新增「A4 Scope Formalization」权威块
  （completion boundary / 9 项 closure requirements / READY_TO_CLOSE / A4+ future
  scope / A5-A6 边界）；stale 措辞限定 4 处——「Next mainline」A3-close 边界句
  （A4 = WorkBuddy/economic/multi-agent routing、均 NOT IMPLEMENTED）、A3 Status
  块边界句、A4-001 交付块尾「仍为未来 A4 工作」、A4-002 交付块尾「仍未来 A4 工作」。
- `docs/internal/AAF_MASTER_BACKLOG.md`：头部 Last Updated 新增本任务条目；
  CAP-003 全套行更新（title / Status / Current Implementation 尾 + A3-close 期
  内句 / Remaining Gap / Do Not Forget——LOW + MEDIUM WorkBuddy economic active
  routing = IMPLEMENTED、A4 = READY_TO_CLOSE、HIGH/CRITICAL/multi-agent = A4+
  future scope、A5/A6 边界不变）；RW-027 Related、CAP-002 Current Implementation
  尾句、CAP-004 Do Not Forget、§7 Summary CAP-003 行同步精确化。
- 本 decision record（docs/internal/AAF-v0.5-A4-SCOPE-FORMALIZATION-001-REPORT.md）
- **零** `.py` / registry / test / economics / qualification 文件变更
  （Requirement 6；git diff 验证见 §7）

## 6. 验收对照

- A4 completion boundary 显式（PROJECT_STATE v0.5「A4 Scope Formalization」块 +
  本 record §3）✅
- LOW + MEDIUM = 定义的 A4 closure capability ✅
- HIGH / CRITICAL 保留在 A4+ future scope（含 HIGH 的 T2-or-better qualification
  prerequisite 记录）✅
- multi-agent / Codex routing 保留在 A4+ future scope（含 scope/design 前置记录）✅
- A5 / A6 边界不变 ✅
- 零 code/runtime/test 行为变化（docs-only）✅
- 无功能静默删除（无功能删除、无未来能力放弃，显式声明）✅
- A4 状态 = READY_TO_CLOSE（不是 CLOSED / COMPLETE / SYNCED）✅
- WorkBuddy 独立验证：route 阶段执行，verdict 记录于本任务 REPORT
- Codex APPROVE：route 阶段执行
- Unresolved Issues = None
- 未 push（Requirement：no push）

## 7. 验证证据（Executor 实测）

- `git status`：tracked 变更仅 docs/internal/ 下 3 个本任务文件；untracked 仅
  既有 PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、
  `scripts/start_bridge_hidden.vbs`）
- `git diff --stat`：仅 2 个 markdown 文档修改 + 1 个新增 markdown record；无
  `.py` / registry / test / json 变更
- 本任务为纯文档任务（Requirement 1/2/3/4），未新增/修改任何测试；无需运行
  测试套件（零代码变更，无回归面）
- baseline HEAD = `8730d0be80a7b79d5edee8a11c1376589485c38d` 记录于本任务
  Context；origin/main = same
