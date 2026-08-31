# AAF-v0.5-A2PLUS-RW030-001 — Implementation Report

> Task: RW-030 minimal prerequisite slice — Qualify one local-free Hermes candidate
> （对 qwen3:4b@custom 做真实、受控、非权威的 runtime qualification，并仅按实际证据更新其 capability + qualification）
> Executor: Hermes（AAF Executor stage）2026-08-31
> Status: **IMPLEMENTED**；A2 = CLOSED / COMPLETE / SYNCED（不变）；A3 = 未启动（CAP-003 NOT IMPLEMENTED）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **qwen3:4b@custom 真实 runtime qualification 完成**（Objective）：用隔离、可审计、
   non-authoritative 的真实本地 runtime probe（`.aaf/AAF-v0.5-A2PLUS-RW030-001/probe/`）
   证明——端点实际可达、qwen3:4b 身份与配置匹配、受控 `Risk: LOW` executor-like task
   完成并产生预期结构化结果、无超时/协议错误/执行失败。registry 按证据保守更新：
   `capability_tier = T4` + `qualification.status = QUALIFIED`（evidence 引用 probe
   artifacts、observed_at = 2026-08-31T23:19:13+08:00 真实观测时间戳）。
2. ✅ **A3 获得第一个真实可用的 LOCAL_FREE Hermes candidate**：LOW Hermes shadow 决策
   现产生真实 hypothetical candidate——`eligible = [deepseek-v4-flash@deepseek,
   qwen3:4b@custom]`、`selected = qwen3:4b@custom`（LOCAL_FREE 经济 rank 0 < deepseek
   UNKNOWN rank 2，`lowest_known_economic_cost`）；此前 LOW 场景只有 deepseek 一个
   eligible（remote/UNKNOWN 成本），现本地 FREE 候选成立。
3. ✅ **capability 保守赋值**（Requirement 4）：LOW probe 成功只证明最低 T4（
   `RISK_FLOORS[LOW].executor == "T4"`）；**不推断 T3/T2/T1/T0**（测试锁定：MEDIUM /
   HIGH / CRITICAL 均不因本次 LOW probe 提升）。
4. ✅ **FREE ≠ qualified 纪律保持**（Requirement 5）：QUALIFIED 来自真实 probe 证据而非
   LOCAL_FREE 成本；qwen2.5vl:3b@custom（同为 LOCAL_FREE）无独立证据 → 保持 UNKNOWN。
5. ✅ **复用 RuntimeQualification**（Requirement 6）：未创建第二套 qualification/health
   状态系统；probe 证据经既有 `RuntimeQualification(status, evidence, observed_at)`
   消费。
6. ✅ **既有状态零改动**（Requirement 7）：deepseek-v4-flash@deepseek 既有
   T2+QUALIFIED 不变；qwen2.5vl:3b 保持 UNKNOWN；LOCAL_FREE / LOCAL 维度不变。
7. ✅ **Shadow / actual execution invariants 保持**（Requirement 8）：`authoritative=false`
   / `execution_affected=false` 固定语义 + validate fail-closed 保持；actual Hermes
   model/provider（deepseek-v4-flash@deepseek）不变；selector / shadow observation /
   runner / adapters / cost_guard 零代码修改（只消费更新后的 registry 数据）。
8. ✅ **零越界**（Requirement 9）：未实现 health polling / dynamic quarantine /
   automatic promotion loop / automatic fallback / A3 routing / WorkBuddy-Codex
   economic routing。
9. ✅ **测试 + 回归 + fresh-runner N+1 全过**（§6/§7/§9）：5 项新增聚焦测试（净 +5），
   全量 non-GUI 4-file-deselect = **1602 passed / 1 skipped / 38 deselected**
   （HEAD 1597 + 5 精确零回归，与 A2-004 同一排除约定）；fresh-runner N+1 证明
   LOW TASK 全链行为（actual 仍 deepseek、shadow 选 qwen3、LOCAL_FREE 偏好生效、
   actual 执行未被改变、REPORT/lifecycle 正常）。

## 2. Scope Boundary

本任务 = **A2+（RW-030）最小 prerequisite slice**：只资格化 qwen3:4b@custom，确定 A3
能否获得至少一个真实可用的 FREE Hermes candidate。

- **In scope**：对 qwen3:4b@custom 做隔离非权威真实 runtime probe（本地 Ollama 端点）；
  `model_registry.baseline_entries()` 中 qwen3:4b@custom 单一条目按证据填入 T4 +
  QUALIFIED（evidence + 真实 observed_at）；相应测试更新与新增；fresh-runner N+1；文档。
- **Out of scope（后续 A2+ slice）**：qwen2.5vl:3b 等其他本地候选的资格化；实况
  qualification 观测机制（health polling / quarantine / promotion / fallback）；
  WorkBuddy/Codex shadow observation；A3 actual routing。
- **边界（Requirement 9 显式 anti-pullback）**：未实现 health polling / dynamic
  quarantine / automatic promotion loop / automatic fallback / A3 routing /
  WorkBuddy-Codex economic routing；无 active routing；A3 = 未启动（CAP-003
  NOT IMPLEMENTED）。

## 3. Reused Contracts（复用，零复制、零发明）

| 契约 | 消费方式 |
|---|---|
| `RuntimeQualification` + `evidence` + `observed_at`（A1 model_registry） | 既有 qualification 机制原样使用——**未发明第二套 qualification 机制** |
| `risk_contract.RISK_FLOORS[LOW].executor == "T4"`（A1） | 证据→tier 的映射依据：LOW probe 成功 = 最低已证 T4（不推断更强） |
| `is_usable_candidate` / `tier_satisfies`（A1） | selector 原样消费更新后的条目（零修改） |
| `shadow_routing.select_shadow_candidate` / `shadow_observation`（A2-001/002/003） | 零代码修改，仅 registry 数据变化改变决策输出 |
| `cost_guard`（A0）/ `model_observation`（v0.4 TASK-010） | 零修改；probe 只读复用本地端点事实与 config 身份事实 |
| 真实 probe 证据 artifacts | `.aaf/AAF-v0.5-A2PLUS-RW030-001/probe/`（脚本 + JSON 证据 + 原始 transcript） |

## 4. Implementation（实现明细）

### 4.1 Qualification probe（隔离 / 可审计 / non-authoritative）

probe 脚本与全部原始输出位于 `.aaf/AAF-v0.5-A2PLUS-RW030-001/probe/`：

- `qwen3_qualification_probe.py` —— 独立一次性证据生成脚本（stdlib only；不被任何
  framework 模块 import；无 live 路径执行它）。
- `qwen3_qualification_probe.json` —— 结构化证据 artifact（每步原始结果 + 判定 +
  qualification 结论）。
- `qwen3_probe_transcript.txt` —— 原始 transcript（可复核）。

probe 步骤与结果（全部真实运行时证据，observed_at = 2026-08-31T23:19:13+08:00）：

1. `GET /api/tags`（http://127.0.0.1:11434）——**端点可达**；`qwen3:4b` 存在：
   digest `359d7dd4…`、parameter_size 4.0B、quantization Q4_K_M、capabilities
   `completion/tools/thinking`。
2. `POST /api/show {model: qwen3:4b}`——身份细节：family=qwen3、4.0B、Q4_K_M、
   capabilities 同上（Ollama /api/show 不回显 model 名，身份校验 = tags 条目 +
   family/参数一致）。
3. 只读 config 身份匹配——`hermes config get auxiliary`（exit 0）：compression /
   title_generation / web_extract / summarization 四个槽位 = `qwen3:4b` +
   `provider: custom` + `base_url: http://127.0.0.1:11434/v1`（与 registry 条目
   qwen3:4b@custom 完全一致）；`hermes config get model` 记录主模型仍为
   `deepseek-v4-flash` / provider `deepseek`——**probe 未改变任何执行事实**。
4. 受控 `Risk: LOW` executor-like task——`POST /v1/chat/completions`（model=
   qwen3:4b，temperature 0，think=false 以让最终 content 承载结构化结果，max_tokens
   4096）：HTTP 200、`finish_reason=stop`、`response model=qwen3:4b`、内容为
   `AAF_STRUCTURED_RESULT_BEGIN {"status":"SUCCESS","commit":null,"changed_files":
   ["probe-ok"],"warnings":[]} AAF_STRUCTURED_RESULT_END`（与预期逐字段精确匹配）；
   耗时 45.8s；usage prompt_tokens=180 / completion_tokens=3778；无超时/协议错误。

probe 判定（全部必需条件满足 → QUALIFIED）：端点可达 ✓、身份与配置匹配 ✓、LOW
executor-like task 完成且结构化结果符合预期 ✓、无超时/协议错误/明显执行失败 ✓、
零外部/付费 provider 调用（`external_provider_calls: 0`）✓、零 Hermes 配置修改 ✓。
首次运行实测发现两个真实行为并修正 probe（均为 probe 自身的适配，非伪造证据）：
/api/show 是 POST 而非 GET（405 → 修正）；qwen3 是 thinking-capable 模型，默认
thinking 消耗全部 max_tokens 导致 content 为空 / finish_reason=length（→ think=false
+ max_tokens 4096 后 content 干净、finish=stop）。失败尝试的诚实记录保留在
probe.log。

### 4.2 Registry 更新（`ai_agent_framework/model_registry.py` —— 唯一生产文件改动）

1. 新增证据锚点常量 `_EVID_RW030_001_PROBE`：指向真实 probe artifacts（.aaf/
   AAF-v0.5-A2PLUS-RW030-001/probe/；端点可达 / 身份匹配 / LOW task 结构化结果 /
   observed_at 真实时间戳 / 零外部调用 / 零配置修改；只证明最低 T4）。
2. 新增 `_EVID_RW030_001_OBSERVED_AT = "2026-08-31T23:19:13+08:00"`：probe 证据被
   接受的真实运行时时间戳（probe artifact observed_at）——**不是本次构造的当前时间**。
3. `qwen3:4b@custom` 条目更新：
   - `capability_tier: None -> CAP_TIER_T4`（LOW probe 成功只证明「至少 T4」=
     LOW executor floor；不推断 T3/T2/T1/T0）
   - `qualification: RuntimeQualification(status=QUALIFIED,
     evidence=(_EVID_RW030_001_PROBE,), observed_at=_EVID_RW030_001_OBSERVED_AT)`
   - 条目级 `evidence` 追加 `_EVID_RW030_001_PROBE`（保留既有 CAP-002 probe 证据）
   - notes 更新：T4+QUALIFIED 仅来自隔离非权威真实 probe；accepted evidence
     snapshot — 不表示永久健康、不产生动态 health/quarantine 行为；T3/T2/T1/T0
     未证明
   - **cost_class 保持 LOCAL_FREE**；locality / applicable_agents 不变
4. `baseline_entries()` docstring 更新：证据支持的例外改为两条（deepseek = A2-004
   执行证据 T2；qwen3:4b = RW-030-001 probe 证据 T4），互不推导。

其它生产文件（selector / shadow observation / runner / adapters / cost_guard /
model_observation）**零修改**。

## 5. Test Matrix（5 项新增聚焦测试，净 +5）

| 验收点 | 测试 | 文件 |
|---|---|---|
| qwen3 T4 保守赋值 + QUALIFIED 证据 + 真实 observed_at + LOCAL_FREE/LOCAL 保持 | `test_baseline_qwen3_t4_evidence_backed`（tier==T4 且 !=T3/T2/T1/T0；evidence 含 probe 路径 / Risk: LOW / 127.0.0.1:11434 / probe-ok / NOT inferred；observed_at == 2026-08-31T23:19:13+08:00；is_usable_candidate True） | test_model_registry.py |
| FREE ≠ qualified 纪律 + 不扩散 | `test_baseline_qwen3_free_does_not_qualify_others`（qwen3 LOCAL_FREE+QUALIFIED 是 probe 证据而非成本；qwen2.5vl 同 LOCAL_FREE 仍 UNKNOWN 不可用） | test_model_registry.py |
| LOW shadow 决策产生真实 LOCAL_FREE candidate | `test_baseline_registry_low_selects_qwen3_local_free`（eligible=[deepseek, qwen3]、selected=qwen3:4b@custom、lowest_known_economic_cost / cost 维度）+ `test_baseline_registry_low_shadow_selects_qwen3_local_free`（shadow observation 级：actual deepseek 不变、actual_vs_shadow=DIFFERENT、非权威）+ `test_runner_low_risk_shadow_selects_qwen3_local_free`（runner 级：恰一次 hermes 调用、三位置参数形态不变） | test_shadow_routing.py / test_shadow_observation.py / test_task_risk_provenance.py |
| HIGH/MEDIUM/CRITICAL 不因 LOW probe 提升 | `test_baseline_registry_medium_high_still_select_deepseek`（qwen3 T4 不足 T3/T2 → CAPABILITY_INSUFFICIENT）+ `test_baseline_registry_critical_no_t1_t0_inference`（deepseek T2 + qwen3 T4 均不足 T1 → NO_SHADOW_CANDIDATE） | test_shadow_routing.py |
| 其它候选保持 UNKNOWN / 既有断言更新 | `test_baseline_other_candidates_remain_unknown`（qwen2.5vl 移出「保持 unknown」循环 → 专项断言仍 UNKNOWN；workbuddy/codex 不变）+ `test_baseline_no_invented_tiers_or_health`（qwen3 纳入证据例外集合） | test_model_registry.py |

定向 4 文件：**177 passed**。相关回归（test_runner / test_cost_guard /
test_risk_contract / test_model_observation / test_router / test_aggregation_rw022）：
**192 passed**。全量 non-GUI 对账见 §7。

## 6. Static Isolation（隔离守卫延续）

- `shadow_routing` / `shadow_observation` / `runner` / `adapters` / `cost_guard`
  源码零修改 → 既有静态隔离断言（零 I/O / 零 LLM / 零副作用 API / live 模块零
  import）原样通过。
- `model_registry` 依赖图不变（stdlib + model_observation）；新增改动只含常量与
  数据字段，无新 import、无网络/子进程依赖（既有静态断言保持）。
- probe 脚本位于 .aaf 证据目录，不被任何 framework 模块 import（一次性证据生成器）。

## 7. Boundaries Compliance（零越界）

- **零自动路由**：无任何 live 路径新增消费；shadow 仍非权威（authoritative=false）。
- **零 runtime qualification learning / 自动提升 / 健康轮询 / 动态隔离 / fallback**：
  QUALIFIED 是静态 accepted-evidence 快照（与 A2-004 deepseek 同一语义）；无新机制、
  无新状态文件、无第二套 qualification 系统。
- **零 A3**：CAP-003（actual model routing）保持 NOT IMPLEMENTED；本任务未把任何
  Hermes executor 切换到 qwen3（probe 是独立脚本，只读 config + 本地端点）。
- **零本地模型越权提升**：qwen2.5vl:3b 无独立证据 → 保持 UNKNOWN。
- **A2+ 边界**：本 slice 只处理 qwen3:4b@custom；A2 = CLOSED / COMPLETE / SYNCED 不变。
- 全量 non-GUI 对账（与 A2-004 同一 4-file-deselect 约定，规避已知 pre-existing
  launcher-GC 0x80000003 崩溃）：HEAD = **1597 passed / 1 skipped / 38 deselected**；
  本分支 = **1602 passed / 1 skipped / 38 deselected**（1597 + 5 新增，零回归，
  精确对账；stash 反证 HEAD 基线同命令复跑确认）。

## 8. Changed Files

- `ai_agent_framework/model_registry.py`（唯一生产改动：证据锚点 + qwen3:4b 条目 T4/QUALIFIED）
- `tests/test_model_registry.py`（2 项新增 + 2 项语义更新）
- `tests/test_shadow_routing.py`（1 项新增 + 1 项替换为 2 项 + 1 项扩展断言）
- `tests/test_shadow_observation.py`（1 项新增）
- `tests/test_task_risk_provenance.py`（1 项 runner 级新增）
- `docs/internal/AAF-v0.5-A2PLUS-RW030-001-REPORT.md`（本文件）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`（状态同步）
- 证据 artifacts（untracked，与 003-FIX-001 同一存放约定）：
  `.aaf/AAF-v0.5-A2PLUS-RW030-001/probe/`（脚本 + JSON + transcript + log）与
  `.aaf/AAF-v0.5-A2PLUS-RW030-001/fresh-runner-validation/`（N+1 产物）

## 9. Fresh-runner N+1（N1-low-hermes）

证据目录：`.aaf/AAF-v0.5-A2PLUS-RW030-001/fresh-runner-validation/N1-low-hermes/`
（fakebin hermes.bat/codebuddy.bat/codex.bat + TASK.md + out2/ + marker_*.txt +
run2_stdout.log；scenario_record.json 在上级目录）。

- 运行：`python tests/fresh_runner_wrapper.py <abs>TASK.md --workspace <abs ws>
  --output <abs out2>`（env：AAF_TEST_FAKE_BIN / AAF_HERMES_MODEL=deepseek-v4-flash /
  AAF_HERMES_PROVIDER=deepseek / AAF_COST_AUTH=…|hermes|deepseek-v4-flash|deepseek）
- **exit 0**；run.json `status=SUCCESS`、terminal_generation=1；REPORT `Current Status SUCCESS`
- 真实子进程证据：marker_hermes.txt（chat --in）/ marker_codebuddy.txt（-p）/
  marker_codex.txt（exec）——三个 route agent 全部真实拉起
- **Risk: LOW TASK 被正常读取**：shadow_observation.json `risk_class=LOW`、
  risk_source = TASK_RISK_SOURCE（task/planner provenance）
- **actual Hermes 仍使用当前既定 model/provider**：`actual_model=deepseek-v4-flash /
  actual_provider=deepseek`（invocation_env_override）
- **qwen3:4b@custom 为 eligible 且被选中**：`eligible=[deepseek-v4-flash@deepseek,
  qwen3:4b@custom]`、`selected=qwen3:4b@custom`、selection_reason=
  lowest_known_economic_cost（**LOCAL_FREE 经济偏好正常生效**：rank 0 < deepseek
  UNKNOWN rank 2）
- **actual execution 未被 shadow 改变**：actual_vs_shadow=DIFFERENT（expected：
  shadow 是 hypothetical，actual 仍 deepseek）；**authoritative=false /
  execution_affected=false**；fakebin 只见 3 个 route agent 调用 + 只读
  config/version probe（零额外 provider/model 调用）
- cost_guard.json = ALLOWED_AUTHORIZED_PAID（authorization_matched=true，exact scope）
- REPORT/lifecycle 正常（REPORT.md Current Status SUCCESS）

## 10. Unresolved Issues

None。

## 11. Remote Sync / 交付状态

- 本提交 = 未 push（review 通过后同步，与 A2-001/002/003/004 惯例一致）。
- A2 = CLOSED / COMPLETE / SYNCED（不变）；A2+ 首片 = 本任务（IMPLEMENTED，待
  WorkBuddy 独立验证 + Codex APPROVE 后由 Planner 确认）；A3 未启动。
- WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件（route 阶段执行）。
