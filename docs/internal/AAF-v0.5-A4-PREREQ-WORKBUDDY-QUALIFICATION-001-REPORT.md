# AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001 — Implementation Report

> Task: A4 prerequisite slice 2 — Qualify one WorkBuddy model candidate
> （建立 A4 所需的第一条 WorkBuddy per-model capability + qualification 真实证据链；
> 仅验证一个候选：deepseek-v4-flash）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **IMPLEMENTED**（prerequisite slice delivered）；A4 = 未启动（NOT STARTED，正式实现 scope 未开始）；A0-A3 = CLOSED / COMPLETE / SYNCED（不变）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **deepseek-v4-flash WorkBuddy candidate 已获得真实、可审计的 runtime
   qualification evidence**（Objective / Acceptance 1）：隔离、可审计的 per-run
   CodeBuddy runtime probe（`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/probe/`，
   observed_at=2026-09-02T01:45:31+08:00）全步骤成功：
   `codebuddy --version`=2.141.0、`--help` `--model` 帮助行仍文档化该 model ID
   （CLI 级接受）、`config get model` invocation 前后均空（CodeBuddy Auto 保持、
   probe 零配置修改）、真实 invocation `codebuddy -p --output-format text -y
   --model deepseek-v4-flash --no-session-persistence` 完成受控 Risk: LOW
   validator-like task 并**精确**产出预期 `AAF_STRUCTURED_RESULT_BEGIN` verdict 块
   （JSON 逐字段匹配：verdict=PASS / blocking_rework=false /
   blocking_provenance=structured / findings=[probe-ok] / warnings=[]），exit 0 /
   stderr 空 / 无 error signals / 无超时、协议错误、模型不可用、runtime failure。
2. ✅ **只赋最低被证据证明的 capability tier**（Requirement 4 / Acceptance 2）：
   `capability_tier = T4`——受控 Risk: LOW validator-like probe 成功按既有 Risk
   Contract 只证明最低 T4（`RISK_FLOORS[LOW].executor == "T4"` 且 `validator ==
   "T4"`）；**T3/T2/T1/T0 绝不推断**（专项测试锁定：MEDIUM/HIGH/CRITICAL 下
   selector 仍 `CAPABILITY_INSUFFICIENT`，HIGH reviewer 允许集合 {T1,T2} 不含 T4）。
3. ✅ **Qualification 证据完整**（Requirement 5）：
   `qualification.status = QUALIFIED`，`evidence` = 实际 probe artifacts 引用
   （deepseek_v4_flash_qualification_probe.json + _transcript.txt），
   `observed_at = 2026-09-02T01:45:31+08:00`（probe 真实完成时刻，非构造时间）。
4. ✅ **Registry 变更限定到该候选**（Requirement 8）：仅 `deepseek-v4-flash`
   WorkBuddy 条目被资格化；其余 14 个 WorkBuddy candidates 保持
   `tier=None + qualification=unknown`（ineligible，专项测试逐项断言）。
5. ✅ **cost_class 保持 UNKNOWN**（Requirement 9）：不解析 multiplier / promotion /
   RemoteConfig economic metadata；UNKNOWN 成本不反向提升能力或 qualification
   （economic_rank=2 不变；专项测试含 cost 替换对抗断言）。
6. ✅ **独立 authority**（Requirement 6）：Hermes 侧同名模型
   （`deepseek-v4-flash@deepseek`，A2-004 已接受证据 = T2）**不是**本条目
   qualification authority——WorkBuddy 资格只来自本 probe 的独立 runtime
   evidence（evidence 常量 + 测试双重锁定：qualification.evidence 引用
   QUALIFICATION-001 probe，不含 003-FIX-001/A2-004 引用；Hermes 条目零变化）。
7. ✅ **production WorkBuddy invocation 零修改**（Requirement 7 / Acceptance 4）：
   adapters `_workbuddy_invocation` args 精确 = `[exe, -p, --output-format, text,
   -y]`，无 `--model` / `--effort`；`agent:workbuddy`（model=None）Auto 锚点保持
   全 UNKNOWN；fresh-runner N+1 用 fake codebuddy 落盘 argv 证据证明真实 runner
   的 WorkBuddy stage 调用仍精确 Auto 形状。
8. ✅ **eligibility gate 行为正确**（Requirement 10）：LOW executor/validator 下
   `deepseek-v4-flash` 通过 capability/qualification gate（`is_usable_candidate`
   True + selector eligible/selected）；MEDIUM/HIGH/CRITICAL 仍排除；hermes/codex
   stage `ROLE_NOT_APPLICABLE` 零变化；其余候选 ineligible。
9. ✅ **测试 + 回归 + fresh-runner N+1 全过**（§5）：16 项新增聚焦测试（parametrize
   展开 18 项）+ 既有 discovery/registry 测试同步 + fresh-runner N+1 3/3（N1 LOW
   全链 SUCCESS + fake codebuddy argv 精确 Auto 无 --model；N2 HIGH control 同；
   N3 fresh-process eligibility-only PASS）。
10. ✅ **状态更新最小化**：PROJECT_STATE.md / backlog 只标记本 prerequisite slice
    已交付；**A4 保持 NOT STARTED**（正式实现 scope 未开始）；no push。

## 2. Scope Boundary

本任务 = **A4 prerequisite slice 2**：只建立一条 WorkBuddy per-model capability +
qualification 真实证据链（deepseek-v4-flash）。

- **In scope**：隔离可审计 per-run CodeBuddy runtime probe（显式 `--model
  deepseek-v4-flash`，probe-only）；该候选保守 tier + qualification 写入 registry；
  eligibility gate 行为验证；调用不变验证；fresh-runner N+1；测试 + 回归；文档。
- **Out of scope（A4 正式实现，未开始）**：economic routing、active `--model`
  selection（production）、multiplier-based ordering、RemoteConfig routing
  consumption、effort selection、fallback、multi-agent routing。
- **边界（Boundaries 显式 anti-pullback）**：no active WorkBuddy routing；no
  economic multiplier parsing；no RemoteConfig routing authority；no effort
  selection；no fallback；no Hermes routing changes；no Codex routing；no A5/A6；
  no health/quarantine/calibration。adapters 调用零修改。其余 14 个 WorkBuddy
  candidates 零变更。

## 3. Probe Evidence（真实 runtime，Requirement 2/3）

证据目录：`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/probe/`
（deepseek_v4_flash_qualification_probe.py + deepseek_v4_flash_qualification_probe.json
+ deepseek_v4_flash_probe_transcript.txt + probe.log + smoke_shape_check.json +
smoke_shape_check.py；全部 untracked，与既有 .aaf 证据约定一致）。

| 步骤 | 命令 / 观测 | 结果 |
|---|---|---|
| 1. runtime 身份 | `codebuddy --version` | exit 0，`2.141.0`（与 discovery 证据一致） |
| 2. CLI 级接受 model ID | `codebuddy --help`（解析 `--model` 帮助行） | exit 0，`deepseek-v4-flash` ∈ parsed_model_ids（15 个 ID 与 discovery 完全一致） |
| 3. Auto 前置保持 | `codebuddy config get model`（只读，pre） | exit 0，空 → CodeBuddy Auto |
| 4. **真实 invocation** | `codebuddy -p --output-format text -y --model deepseek-v4-flash --no-session-persistence`（stdin 受控 Risk: LOW validator-like task） | exit 0 / stderr 空 / 无 error signals / elapsed 5.313s / `AAF_STRUCTURED_RESULT_BEGIN {verdict:PASS,...} AAF_STRUCTURED_RESULT_END` JSON 精确匹配 / 无超时无协议错误无模型不可用 |
| 5. Auto 后置保持 | `codebuddy config get model`（只读，post） | exit 0，空 → probe 零配置修改 |

- `--no-session-persistence` 为 **probe-only 隔离 flag**（session 不落盘）；production
  adapter invocation（`[-p --output-format text -y]` + stdin）零修改。
- 可观测性诚实声明（记入 probe artifact）：CodeBuddy CLI `--model` = "Model for
  the current session"；text 输出模式不回显已解析的 model id——runtime 可观测性
  以「flag 被接受 + 无 invalid-model 错误 + 任务完成且内容正确」为限，不做超出
  证据的断言。
- 判定：全部必需条件满足 → **QUALIFIED**，capability_tier=T4（最低已证），
  observed_at=2026-09-02T01:45:31+08:00（probe 真实完成时刻）。
- 过程记录：首次 probe 因脚本 bug（subprocess env 整体替换导致 Windows 子进程
  PATH 清空，exit=0xC0000409）如实失败（evidence 记录 NOT_QUALIFIED 语义，零
  伪造）；修复（env 继承 os.environ）后重跑成功——两次运行均有 artifact 可审计，
  符合「失败如实记录、不得强行提升」纪律。

## 4. Registry 变更（Requirement 8/9，单一候选）

`ai_agent_framework/model_registry.py`：

- 新增 `_EVID_A4_WORKBUDDY_QUALIFICATION_001_PROBE`（完整 provenance：task id /
  observed_at / artifact 文件名 / 全步骤事实 / tier 规则 / 独立 authority 声明）
  与 `_EVID_A4_WORKBUDDY_QUALIFICATION_001_OBSERVED_AT = "2026-09-02T01:45:31+08:00"`。
- `baseline_entries()`：deepseek-v4-flash 从 identity-only comprehension 中移出，
  改为**独立资格化条目**：`capability_tier=T4`（LOW probe floor，不推断更高）、
  `qualification=QUALIFIED`（evidence + 真实 observed_at）、`cost_class=UNKNOWN` /
  `locality=UNKNOWN` / `provider=None` 保持、notes 明确「Hermes 同名证据非
  authority」「production invocation 零修改」。其余 14 个候选的 comprehension 加
  `if mid != "deepseek-v4-flash"`，条目内容零变化。
- 零 schema 变更、零新模块、key 集合不变（`deepseek-v4-flash` 与 Hermes 条目
  `deepseek-v4-flash@deepseek` 不同 key，无冲突）。

## 5. 代码 / 测试变更

- `tests/test_a4_workbuddy_qualification.py`（新增，16 项函数 / parametrize 展开 18 项）：
  1. 候选资格化状态（T4 + QUALIFIED + is_usable_candidate True）；2. 证据引用 +
    observed_at 真实；3. **独立 authority**（不含 Hermes 证据引用）；4. 不高估
    tier（T4 ≠ T0-T3；tier_satisfies 对 MEDIUM/HIGH floor False）；5. cost UNKNOWN
    不反向提升（含 cost 替换对抗断言）；6. 其余 14 候选逐项仍 UNKNOWN + ineligible；
    7. Auto 锚点不变；8. LOW executor gate 通过（eligible + selected）；9. LOW
    validator gate 通过；10. MEDIUM/HIGH/CRITICAL 仍 CAPABILITY_INSUFFICIENT；
    11. HIGH reviewer 不允许（{T1,T2}）；12. hermes stage ROLE_NOT_APPLICABLE +
    既有选择不变；13. Hermes 同名条目零变化；14. production invocation 无
    --model/--effort；15. round-trip 保留 + key 集合不变。
- `tests/test_a4_workbuddy_discovery.py`（同步）：identity-only 断言限定到 14 个
  未资格化候选；selector 测试按 LOW（deepseek-v4-flash eligible）/ MEDIUM/HIGH
  （全排除）分支；round-trip 测试断言资格化候选 usable。
- `tests/test_model_registry.py`：`test_baseline_no_invented_tiers_or_health`
  跳过集合加入 WorkBuddy 候选 `deepseek-v4-flash`（有独立已接受 probe 证据）；
  `test_baseline_keys_unique_and_stable` 不变（20 key 不变）。
- `tests/fresh_runner_a4_wb_qualification_validation.py`（新增，fresh-runner N+1
  驱动）+ `tests/fresh_runner_a4_wb_qual_eligibility_check.py`（fresh-process
  eligibility check）：见 §6。

命令与结果：

```
python -m pytest tests/test_a4_workbuddy_qualification.py tests/test_a4_workbuddy_discovery.py \
  tests/test_model_registry.py tests/test_shadow_routing.py tests/test_adapters.py \
  tests/test_active_routing.py -q
  → 188 passed（~2s）
python tests/fresh_runner_a4_wb_qualification_validation.py
  → fresh-runner A4-WB-QUALIFICATION N+1: failures=0（N1/N2/N3 全 PASS）
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_e_e2e.py \
  --deselect tests/test_bridge_launcher.py
  → 1668 passed / 1 skipped / 40 deselected（68.4s）= HEAD d9b6cdc 基线 1650 +
     18 新增（16 项测试函数，parametrize 展开 18 项），精确零回归
```

## 6. Fresh-Runner N+1（TASK Fresh Runner 要求）

证据：`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/fresh-runner-validation/`
（scenario_record.json + N1-low/ + N2-high-control/，untracked）。

- **N1（Risk: LOW）**：全新 python 进程跑真实 runner 全生命周期（fake
  hermes/codebuddy/codex 真实 child process）；run.json status=SUCCESS、
  workbuddy_result.json verdict=PASS、codex_result.json verdict=APPROVE、
  REPORT.md + context_manifest.json 存在（lifecycle 正常）；fake codebuddy 落盘
  argv 证据 = `-p --output-format text -y`——**production WorkBuddy stage 仍使用
  当前 Auto invocation，registry qualification 未自动添加 --model**。
- **N2（Risk: HIGH, control）**：不路由（configured deepseek-v4-flash@deepseek，
  paid 授权消费）；fake codebuddy argv 仍精确 Auto 形状——qualification 数据不
  影响实际 routing authority。
- **N3（fresh-process eligibility-only）**：全新 python 进程验证 deepseek-v4-flash
  经 eligibility gate（LOW selector eligible）、MEDIUM/HIGH 仍 NO_SHADOW_CANDIDATE、
  其余 14 候选 ineligible、`adapters._workbuddy_invocation` 零 --model/--effort——
  **新 qualification 数据仅影响候选 eligibility，不影响实际 routing authority**。

## 7. A4-A6 Anti-Pullback

本任务未实现：WorkBuddy/economic/multi-agent routing、multiplier 排序、RemoteConfig
路由消费、production active `--model` selection、effort selection、fallback、
Cost Gate UX（A5）、observation/calibration/runtime requalification（A6）、
health/quarantine。A4 保持 **NOT STARTED**（本 slice 只是 prerequisite 证据层）。

## 8. Git 状态

- 基线：main @ `d9b6cdc`（= origin/main；tracked working tree 在任务开始前 CLEAN，
  仅 3 个 PRE_ALLOWED_UNTRACKED 常驻项：.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）。
- 本任务 commit：本地 main 新增（见 structured result `commit` 字段）；**未 push**
  （review 后同步，与 A0-A3 惯例一致）。
- 新证据 artifact 位于 `.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/`
  （untracked，与既有 .aaf 证据约定一致）。
