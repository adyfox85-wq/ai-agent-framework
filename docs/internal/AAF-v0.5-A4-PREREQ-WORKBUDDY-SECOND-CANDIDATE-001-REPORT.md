# AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001 — Implementation Report

> Task: A4 economic routing 最后一个 prerequisite — Qualify one economically
> relevant WorkBuddy candidate（基于 fail-closed WorkBuddy economic facts 从 14
> 个未资格化候选中选择一个最值得验证的 candidate，并建立独立 capability +
> qualification evidence；只增加第二个 eligible WorkBuddy candidate，不实现
> active routing）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **IMPLEMENTED**（prerequisite slice delivered）；A4 = 未启动（NOT STARTED，正式实现 scope 未开始）；A0-A3 = CLOSED / COMPLETE / SYNCED（不变）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **第二个 WorkBuddy candidate（hy4-preview）已获得真实、可审计的 runtime
   qualification evidence**（Acceptance：第二个候选选择有可信 economic
   provenance；capability/qualification 只来自独立 runtime evidence）：candidate
   由**经济事实层 fail-closed probe-priority 选择器**确定性选出（新增
   `workbuddy_economics.select_probe_candidate`，纯函数、非 routing authority），
   隔离、可审计的 per-run CodeBuddy runtime probe
   （`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001/probe/`，
   observed_at=2026-09-02T03:01:44+08:00）全步骤成功：`codebuddy --version`=2.141.0、
   `--help` `--model` 帮助行仍文档化 hy4-preview（CLI 级接受）、`config get model`
   invocation 前后均空（CodeBuddy Auto 保持、probe 零配置修改）、真实 invocation
   `codebuddy -p --output-format text -y --model hy4-preview --no-session-persistence`
   完成受控 Risk: LOW validator-like task 并**精确**产出预期
   `AAF_STRUCTURED_RESULT_BEGIN` verdict 块（JSON 逐字段匹配：verdict=PASS /
   blocking_rework=false / blocking_provenance=structured / findings=[probe-ok] /
   warnings=[]），exit 0 / stderr 空 / 无 error signals / 无超时、协议错误、模型
   不可用、runtime failure（elapsed 8.4s）。
2. ✅ **候选选择 fail closed 且基于已有 economic fact layer**（Requirement 2/3）：
   选择器只消费 FRESH + trustworthy economics——hy4-preview =
   `RANK_AUTHORITATIVE_CHEAP`（FRESH + 显式免费促销 + multiplier 0.0 +
   promotion_factor 0.0，窗口 2026-08-28T00:00:00+08:00..2026-09-11T00:00:00+08:00）；
   与 hy3 同为权威免费时按**最早 valid_until** 确定性 tie-break（hy4-preview
   2026-09-11 < hy3 2026-10-01 = 免费窗口最早关闭者最优先验证）；其余 12 个未
   资格化候选 freshness=UNKNOWN（rank 2）**永不优先**；STALE / UNKNOWN / 字段缺失
   或矛盾（FIX-001 gate）绝不因「猜便宜」被优先；没有任何可信 FRESH 候选时返回
   `NO_TRUSTWORTHY_SECOND_CANDIDATE`（Requirement 4 语义）。选择只决定「先验证
   谁」，**不是 routing authority**（Requirement 2）。
3. ✅ **经济事实永不赋予 capability/qualification**（Requirement 11）：hy3 仍
   FRESH + authoritative cheap（rank 0）但 `tier=None + qualification=unknown` →
   `is_usable_candidate=False`；hy4-preview 的资格只来自独立 runtime probe
   evidence（qualification.evidence 只引用本任务 probe artifacts）。
4. ✅ **只赋最低被证据证明的 capability tier**（Requirement 7）：`capability_tier =
   T4`——受控 Risk: LOW validator-like probe 成功按既有 Risk Contract 只证明最低
   T4（`RISK_FLOORS[LOW].executor == "T4"` 且 `validator == "T4"`）；**T3/T2/T1/T0
   绝不推断**（专项测试锁定：MEDIUM/HIGH/CRITICAL 下 selector 仍
   `CAPABILITY_INSUFFICIENT`）。
5. ✅ **Qualification 证据完整**（Requirement 8）：`qualification.status =
   QUALIFIED`，`evidence` = 本任务 probe artifacts 引用
   （hy4_preview_qualification_probe.json + _transcript.txt），`observed_at =
   2026-09-02T03:01:44+08:00`（probe 真实完成时刻，非构造时间）。
6. ✅ **deepseek-v4-flash WorkBuddy 条目零变化**（Requirement 9）：仍 T4 +
   QUALIFIED，evidence 只引用 QUALIFICATION-001 probe，observed_at 原值
   2026-09-02T01:45:31+08:00 不变。
7. ✅ **其余 13 个未选中 candidates 保持 UNKNOWN**（Requirement 10）：
   `tier=None + qualification=unknown`（ineligible，专项测试逐项断言）。
8. ✅ **cost_class 保持 UNKNOWN**：不解析 multiplier/promotion 进路由权威；
   UNKNOWN 成本不反向提升能力或 qualification。
9. ✅ **production WorkBuddy invocation 零修改**（Requirement 12）：adapters 仍
   精确 `[-p --output-format text -y]`（CodeBuddy Auto），无 --model/--effort；
   fresh-runner N+1 中 fake codebuddy argv marker 精确证明；无 active routing。

## 2. 实际修改（commit 见 §6）

- `ai_agent_framework/workbuddy_economics.py`：新增 fail-closed probe-priority
  选择器 `select_probe_candidate(facts, now, exclude_ids=())` 与
  `NO_TRUSTWORTHY_SECOND_CANDIDATE` 语义哨兵（Requirement 3/4 的可判定编码）：
  rank 0（权威免费）→ 最早 valid_until；rank 1（FRESH discount 字段完整一致）→
  最低 multiplier；rank 2（STALE/UNKNOWN/无促销/字段缺失矛盾）永不参与；
  `now` 必须带时区（与 classify_freshness 同一显式参考时间契约）。经济模块仍
  零消费方（routing 代码源码级零 import，既有测试锁定）。
- `ai_agent_framework/model_registry.py`：新增
  `_EVID_A4_WORKBUDDY_SECOND_CANDIDATE_001_PROBE` + observed_at 常量；hy4-preview
  从 identity-only 生成器移出，改为独立资格化条目（capability_tier=CAP_TIER_T4 +
  qualification=QUALIFIED + cost_class=UNKNOWN / locality=UNKNOWN / provider=None）；
  identity-only 生成器排除集合改为 `("deepseek-v4-flash", "hy4-preview")`；
  deepseek-v4-flash 条目零变化；docstring 同步（第一个/第二个资格化候选）。
- `tests/test_a4_workbuddy_second_candidate.py`（新增，17 项）：选择只消费
  FRESH+trustworthy / rank-0 最早 valid_until tie-break / rank-1 最低 multiplier /
  STALE-UNKNOWN 永不优先 / 字段缺失矛盾 fail closed / exclude_ids /
  NO_TRUSTWORTHY_SECOND_CANDIDATE / 无时区 ValueError / 经济事实不直接使候选
  eligible（hy3 仍 ineligible）/ hy4-preview 资格只来自 probe evidence /
  LOW gate 两候选 eligible + selected 不变 / 不高估 tier / deepseek-v4-flash
  零变化 / 其余 13 候选 UNKNOWN / Auto 锚点不变 / production invocation 不变 /
  roundtrip 保留第二 qualification / key 集合不变。
- 既有测试同步：`test_a4_workbuddy_qualification.py`（14→13 未资格化；eligible
  集合 = 两个；docstring）、`test_a4_workbuddy_discovery.py`（QUALIFIED 集合加
  hy4-preview，UNQUALIFIED 自动派生 13）、`test_a4_workbuddy_economics.py` +
  `test_a4_workbuddy_economics_fix001.py`（FRESH FREE ineligible 断言改为仅 hy3；
  selector eligible 断言 = 两个）、`test_model_registry.py`（baseline 无发明
  tier/health 例外集加 hy4-preview）。
- fresh-runner 脚本：新增 `tests/fresh_runner_a4_wb_second_candidate_validation.py`
  + `tests/fresh_runner_a4_wb_second_candidate_eligibility_check.py`；同步
  `tests/fresh_runner_a4_wb_qual_eligibility_check.py`（UNQUALIFIED 13）与
  `tests/fresh_runner_a4_wb_econ_artifact_check.py` /
  `tests/fresh_runner_a4_wb_econ_fix001_failclosed_check.py`（selector eligible
  断言随新资格化候选同步，仍证明 economics 不驱动选择）。
- 证据 artifact（不提交）：`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001/`
  probe/（hy4_preview_qualification_probe.py + .json + _transcript.txt + probe.log）、
  fresh-runner-validation/、scratch_select_check.py、scratch_registry_check.py。
- 文档：`docs/internal/PROJECT_STATE.md`、`docs/internal/AAF_MASTER_BACKLOG.md`
  （CAP-002）、本 REPORT。

## 3. 测试

- 聚焦（6 文件 167 项全过）：新增 17 项 + 同步后的 qualification/discovery/
  economics/fix001/registry 测试。
- 全量 non-GUI 4-file-deselect（既有 launcher-GC 崩溃约定）：
  **1743 passed / 1 skipped / 38 deselected** = HEAD d7ab18a 基线 1726 + 17
  精确零回归（67s）。
- fresh-runner N+1（本任务）：**3/3** — N1（Risk: LOW 全生命周期 SUCCESS；fake
  codebuddy argv 精确 = `-p --output-format text -y`，零 --model/--effort）；
  N2（Risk: HIGH control 同，configured deepseek 授权消费）；N3（fresh-process
  eligibility check：**registry 中存在两个独立 eligible LOW WorkBuddy
  candidates**（deepseek-v4-flash + hy4-preview，均 T4+QUALIFIED）；MEDIUM/HIGH/
  CRITICAL 仍 NO_SHADOW_CANDIDATE；其余 13 候选 ineligible；invocation 零 --model；
  select_probe_candidate 仍 fail closed）。
- 既有 fresh-runner 驱动复跑全绿：QUALIFICATION-001 N+1 3/3、
  ECONOMICS-FIX-001 N+1 4/4（断言已随新 registry 状态同步）。

## 4. 边界遵守（Boundaries）

无 active WorkBuddy routing、无 multiplier routing wiring、无 effort selection、
无 fallback、无 health/quarantine、无 runtime requalification loop、无 Hermes
changes（A3 行为不变）、无 Codex routing、无 A5/A6。选择器只存在于经济事实层
（probe-priority 决策），任何路由代码零 import 该模块。

## 5. 问题 / 未完成项

- Unresolved Issues = None。
- 继承父任务两条已记录在案项（非本任务引入）：minimax-m2.7 双源 multiplier
  差异（x0.26 vs x0.19）；daily-only 促销无日期窗口 → freshness=UNKNOWN
  （均为设计内 fail-closed 行为）。
- 时效性注记：hy4-preview 免费窗口 2026-09-11 结束、hy3 至 2026-10-01——
  "authoritative cheap" 仅对显式参考时间成立；未来 A4 消费方必须逐次重算
  freshness，不得缓存 rank（本次 probe 在窗口内完成，证据时间戳真实）。

## 6. 提交

- commit：见 §1 顶部 Executor 最终报告（本任务一个提交，未 push，review 后同步）。
- 工作树：仅 3 个 PRE_ALLOWED_UNTRACKED 常驻项（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）。

## 7. A4 状态

**A4 = NOT STARTED**（本任务只是 prerequisite 事实/证据层；正式 A4 实现 scope
未开始）。
