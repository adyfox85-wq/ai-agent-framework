# AAF-v0.5-A2-SHADOW-ROUTING-002 — Implementation Report

> Task: A2 Shadow Routing — Wire Hermes shadow observation（旁路观察接入，第二片）
> Executor: Hermes（AAF Executor stage）2026-08-31
> Status: **IMPLEMENTED**；A2 保持 **STARTED**（未进入 A3）；A1 保持 CLOSED / COMPLETE / SYNCED
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **Hermes shadow observation 已接入**（`ai_agent_framework/shadow_observation.py` +
   runner Hermes-stage 旁路 hook）：每次 Hermes 执行时计算并保存
   `shadow_observation.json`——「如果 Shadow Routing 有执行权，会选择谁」的
   可审计记录（Requirement 1/2）。**只接 Hermes stage**，WorkBuddy/Codex 不产生
   shadow artifact（runner 显式过滤 + 测试锁定）。
2. ✅ **actual execution authority 完全不变**（Requirement 5/6）：`adapters.run_agent`
   零修改；runner 仍以原始 `(agent, prompt, workspace)` 调用；shadow 路径不修改
   Hermes `-m` / provider override / Paid Guard / runner 命令 / fallback；
   `execution_affected=false` 固定语义 + 测试 + Fresh-runner N+1 三重复核。
3. ✅ **shadow path 零额外 provider/CLI/LLM 调用**（Requirement 5/8）：shadow 模块
   依赖图无 subprocess/网络/LLM（静态断言测试）；runner 集成测试证明
   `observe_stage` 调用次数 = stage 数（无新增 discovery），shadow 复用同一
   observation 对象；Fresh-runner 实际运行证明无额外探测。
4. ✅ **risk 缺省 fail-safe 为明确 no-decision**（Requirement 3）：当前 runtime 无
   已接入的 authoritative risk source（risk_contract 是 foundation-only，live 路径
   零调用——搜索证实）→ 生产 resolution 如实记录 `RISK_UNAVAILABLE` + 理由，
   **不发明 heuristic、不调用 LLM**。模块支持显式 risk 输入（未来权威 wiring /
   测试），完整路径经测试锁定。
5. ✅ **registry 诚实**（Requirement 4）：缺省 = A1 `baseline_registry()`（有证据
   契约，未验证维度 UNKNOWN）；不虚构真实模型资格/健康/capability——基线
   registry 上选择器如实返回 NO_SHADOW_CANDIDATE（测试锁定）。
6. ✅ **artifact 遵循 .aaf 约定**（Requirement 7）：`shadow_observation.json` 落
   output_dir（同 `model_observation.json` / `cost_guard.json` 约定），schema_version
   版本化、原子写、stage result 携带 `shadow_observation_ref` 引用（不复制内容）。
7. ✅ **focused tests 26 项**（Requirement 8 全矩阵 + 守卫），全量 non-GUI 零回归
   （基线 1538 + 26 = 1564 精确对账）。
8. ✅ **Fresh-runner N+1 通过**（本任务触及 runtime observation path）：真实
   child-process 边界 + 真实只读 config discovery，见 §9。
9. ✅ **A3-A6 anti-pullback**（Requirement 9）：未实现自动路由 / fallback / health /
   quarantine / 动态降级；CAP-003 实际路由保持 NOT IMPLEMENTED。

## 2. A2 Scope Boundary

本任务 = **A2 第二片（Hermes shadow observation wiring，observation-only）**：

- **In scope**：shadow observation 模块（build/save/load/validate）+ runner Hermes-stage
  旁路 hook + stage result 引用 + 26 项聚焦测试 + N+1 + 文档。
- **Out of scope（后续 A2 slice）**：实况 qualification 观测、候选 tier 证据化赋值、
  WorkBuddy/Codex shadow observation、风险分类接入 live 执行。
- **A2 boundary（Requirement 9）**：未实现 A3 自动路由；未进入 fallback / health /
  quarantine / 动态降级 / 基准循环 / Cost Gate UX / 观测-校准循环。

## 3. Reused Contracts（复用，零复制、零发明）

| 契约 | 消费方式 |
|---|---|
| `shadow_routing.select_shadow_candidate` / `decision_to_dict`（A2-001） | 显式 risk 路径的决策计算（risk 缺省时不调用，避免伪输入） |
| `model_registry.baseline_registry` / `RegistryEntry`（A1） | 缺省 registry（有证据基线；未验证 = UNKNOWN） |
| `risk_contract.RISK_CLASSES` / `ROLE_EXECUTOR`（A1） | 输入校验 + 角色词汇 |
| `model_observation` 观测记录（v0.4 TASK-010 authority） | actual model/provider 的事实来源（调用方传入的 observation dict，本模块零 discovery） |
| `cost_guard.ENV_MODEL` / `ENV_PROVIDER`（A0） | 只读 env 事实：显式覆盖存在时它才是实际 invocation 模型（adapters 透传 -m/--provider） |
| `.aaf` artifact 约定（model_observation 同款） | 文件名 / schema_version / 原子写 / stage ref |

## 4. Shadow Observation Contract

`observe_shadow_stage(output_dir, agent, observation=None, risk_class=None, risk_source=None, registry=None)` → record dict（非阻塞；任何失败 → None）。

`shadow_observation.json` 字段（Requirement 2 全项）：

- `schema_version: 1` / `authority`（non-authoritative 语义声明）
- `stage_agent: "hermes"` / `role: "executor"`
- **`authoritative: false` / `execution_affected: false`**（固定语义；validate 拒绝 True）
- `generated_at` / `observation_ref`（→ model_observation.json 单一 authority）
- **actual model/provider**：`actual_model` / `actual_provider` / `actual_model_source`
  （env 覆盖优先——它是 invocation truth；否则观测值；观测失败 → 如实 UNKNOWN）
- **risk 及其来源**：`risk_class`（null = 不可用）/ `risk_source`（`RISK_UNAVAILABLE`）/
  `risk_source_detail`（理由，可审计）
- **registry/source 信息**：`registry_source` / `registry_entry_count`
- **shadow decision 或明确 no-decision reason**：`decision`（decision_to_dict）/
  `no_decision_reason`（`RISK_UNAVAILABLE: ...` 或 `NO_SHADOW_CANDIDATE: ...`）
- **selected candidate（如有）**：`selected_candidate`
- **actual vs shadow 一致性**：`actual_vs_shadow` = SAME / DIFFERENT /
  NO_SHADOW_DECISION / ACTUAL_UNKNOWN（确定性比较）
- `notes`（诚实记录：env 覆盖、观测缺失、no-decision 原因等）

校验 `validate_shadow_observation`：必需字段齐全 + authoritative/execution_affected
必须为 False（契约违规 → ValueError，fail closed）。

## 5. Risk Resolution（Requirement 3，诚实路径）

`resolve_stage_risk(agent)` 是唯一 resolution 点：**当前 runtime 没有已接入的
authoritative risk source**（`risk_contract` 仅被 `shadow_routing` 与测试 import，
live 执行路径零调用——A1 声明「本任务不把分类接入 live 执行」）。因此生产路径
固定返回 `(None, RISK_UNAVAILABLE, reason)`：

- 不发明 heuristic（没有任何 risk 猜测被填入——`risk_class` 保持 null）；
- 不额外调用 LLM（风险分类零 LLM）；
- artifact 明确记录 `RISK_UNAVAILABLE` + no-decision（fail-safe）。

调用方（未来权威 wiring / 测试）可显式传 `risk_class` + `risk_source`，此时按
A1/A2 契约计算完整 shadow decision——功能完整，但生产路径在 risk 不可证明时
保持 no-decision。未知 risk_class / 缺 risk_source → ValueError（fail closed）。

## 6. Registry Honesty（Requirement 4）

- 缺省 registry = `model_registry.baseline_registry()`（A1 契约；5 个真实条目全部
  tier=None + qualification UNKNOWN——有证据的 UNKNOWN，不是虚构）。
- 显式 risk + 基线 registry → 选择器如实返回 `NO_SHADOW_CANDIDATE`（不把
  FREE/本地条目提升为候选；测试 `test_baseline_registry_no_eligible_candidate_no_shadow_candidate`）。
- 绝不为了产生结果而虚构真实模型资格 / 健康状态 / capability。

## 7. Execution Isolation（Requirement 5/6/9）

- `shadow_observation.py` 依赖图 = stdlib(json/os/datetime/pathlib/typing) +
  model_registry + risk_contract + shadow_routing + cost_guard（仅 ENV_* 常量）；
  **无 subprocess / urllib / requests / http / socket / openai / anthropic / llm**
  （静态断言测试）。唯一 I/O = 写 artifact JSON。
- 无副作用 API（无 apply/switch/invoke/activate/fallback/poll/route…；静态断言测试）。
- 不 import 任何 live 执行模块（runner/adapters/report/lifecycle…；静态断言测试）；
  runner 是唯一合法 wiring 点（Hermes-only、mo_enabled 门控、双保险非阻塞）。
- `AAF_MODEL_OBSERVATION=0` → 整层关闭，无 shadow artifact、无 ref（与接入前
  行为完全一致；测试 `test_runner_telemetry_disabled_no_shadow_artifact`）。
- 未触碰：Hermes `-m` / provider override / Paid Guard / runner 命令 / fallback /
  active Route / live invocation。REPORT 不新增平行段（保持紧凑摘要）。

## 8. Tests（Requirement 8 全矩阵 + 守卫；26 项）

`tests/test_shadow_observation.py`：

| Requirement 8 项 | 测试 |
|---|---|
| 有完整 risk/registry → 产生 shadow decision | `test_full_risk_registry_produces_shadow_decision` / `test_decision_is_serialized_shadow_routing_dict` |
| risk 不可用 → 明确 no-decision | `test_risk_unavailable_explicit_no_decision` / `test_resolve_stage_risk_is_honest_unavailable` / `test_unknown_risk_class_fail_closed` / `test_explicit_risk_requires_source` |
| 无合格 candidate → 明确 NO_SHADOW_CANDIDATE | `test_baseline_registry_no_eligible_candidate_no_shadow_candidate` / `test_no_eligible_candidate_explicit_no_candidate` |
| actual 与 shadow 可不同但不影响执行 | `test_actual_differs_from_shadow_no_execution_effect` / `test_actual_matches_shadow_same` / `test_actual_unknown_vs_shadow` / `test_env_override_used_as_actual_fact` |
| shadow path 不产生额外 provider 调用 | `test_shadow_module_has_no_subprocess_network_llm_dependency` / `test_shadow_observation_never_calls_discovery` / `test_runner_shadow_path_reuses_observation_no_new_probes` |

守卫：
- artifact I/O：原子写 roundtrip / 损坏容错 / validate 拒绝 True 权威标记 /
  observe 非阻塞（保存失败 → None 且不落盘）。
- 静态隔离：无 I/O 依赖 / 无副作用 API / 不 import live 模块 / 常量锁定 hermes。
- Runner 集成：full route 只写一次 artifact（stage_agent=hermes）、workbuddy/codex
  stage 无 shadow ref、REPORT 无平行段、hermes-only route、telemetry 关闭无
  artifact、invocation 签名不变（Requirement 6）。

命令与结果：

```
python -m pytest tests/test_shadow_observation.py -q          → 26 passed
python -m pytest tests/test_shadow_routing.py tests/test_runner.py \
  tests/test_adapters.py tests/test_model_observation.py \
  tests/test_model_registry.py tests/test_risk_contract.py -q → 237 passed
分块全量 non-GUI（canonical 命令）                            → 1564 passed, 1 skipped, 29 deselected
基线复跑（同一命令，git stash 至 e17a7f3）                    → 1538 passed, 1 skipped, 29 deselected
对账                                                           → 1538 + 26 = 1564，零回归（精确）
```

## 9. Fresh-runner Run N+1（Requirement 8 Fresh Runner；真实 child-process 边界）

本任务触及 runtime observation path → 执行全新 N+1：

`.aaf/AAF-v0.5-A2-SHADOW-ROUTING-002/fresh-runner-validation/N1-shadow-observation/`
（`fakebin/hermes.bat` 只拦截 `hermes chat`；config/version/help 探测走**真实
hermes CLI 只读命令**；fresh 进程 + 真实 subprocess 边界——`fresh_runner_wrapper.py`
同 A0 约定）。

N+1 至少证明（全部满足）：

| 证明项 | 证据 |
|---|---|
| Hermes 真实执行仍使用原 model/provider | cost_guard.json `ALLOWED_AUTHORIZED_PAID` + cost_auth_consumed.json 精确 scope `AAF-v0.5-A2-SHADOW-ROUTING-002-N1\|hermes\|deepseek-v4-flash\|deepseek`（准入边界即原模型）；model_observation.json 真实 `hermes config get model` → deepseek-v4-flash@deepseek（真实 config 与 env 覆盖一致） |
| shadow artifact 成功生成 | out/shadow_observation.json（schema_version=1，全字段） |
| artifact 标记 non-authoritative | `authoritative: false` / `execution_affected: false` |
| shadow candidate 未影响真实 invocation | marker.txt `SPAWNED / ARG1: chat / ARG2: --in`（真实 child 进程以原 subcommand 形态运行）；guard scope 原样；adapters 命令构建零修改；N+1 未新增任何探测 |
| REPORT/lifecycle 正常 | run.json SUCCESS / REPORT.md `## Current Status SUCCESS` + Model Observation 段 / route=hermes |

risk 无权威来源 → artifact 如实 `RISK_UNAVAILABLE` no-decision（fail-safe）；
registry = A1 基线 5 条目（UNKNOWN，不虚构）。

注：`out-v1/`（第一次成功运行，argv 探测实验版 fake）与 `out-relative-path-blocked/`
（演示 cost-guard FIX-006 绝对路径守卫）为中间产物，保留作过程证据；最终证据以
`out/` + `scenario_record.json` 为准。argv 全量文本无法经 cmd.exe 回显（prompt 含
换行/引号是 cmd 已知限制，不影响真实 exe 调用——真实 hermes 是 exe，参数由
CRT CommandLineToArgvW 正确解析）；argv 形态证据 = guard scope + 真实 config +
adapters 单元测试（A0 同款先例）。

## 10. Git 状态

- 基线：main @ `e17a7f36aa40d0ff85d46843e3bb156612b547ff`（= origin/main）
- 本任务 commit：本地 main 新增（见 structured result `commit` 字段）；**未 push**
  （review 后同步，与 A1/A2-001 惯例一致）。
- 变更文件：`ai_agent_framework/shadow_observation.py`（新增）、
  `ai_agent_framework/runner.py`（Hermes-stage hook）、
  `tests/test_shadow_observation.py`（新增 26 项）、
  `docs/internal/AAF-v0.5-A2-SHADOW-ROUTING-002-REPORT.md`（本报告）。
- PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`scripts/start_bridge_hidden.vbs`、
  `AAF_TASK004_PROCESS_CHECK.txt`）未删除、未 clean。
- 无 reset / rebase / amend / force push。

## 11. 验证状态 / 已知限制

- WorkBuddy 独立验证 + Codex 审查由 route 阶段（hermes → workbuddy → codex）执行并
  记录；若发现 blocking 按惯例开 FIX。
- 已知限制（如实）：生产路径 risk 不可证明 → shadow observation 始终
  RISK_UNAVAILABLE no-decision（功能完整，等待权威 risk wiring）；基线 registry
  无 verified candidate facts（真实模型 tier/qualification 仍 UNKNOWN）；N+1 argv
  全量文本不经 cmd 回显（见 §9 注）。

## 12. Next Smallest A2 Slice

按最小增量排序的候选（Planner 决定，本任务不启动）：

1. **实况 qualification 观测**：为 registry 提供基于真实运行证据的 qualification
   填充（只读 probe，证据化，仍不激活路由）。
2. **候选 tier 证据化赋值**：对真实 Hermes FREE/本地模型做有证据的 capability
   观测/校准后再赋值（当前保持 UNKNOWN，不发明）。
3. **权威 risk wiring**：把风险分类接入 live 执行（A1 契约消费）后，shadow
   observation 自动产生完整 decision（模块已支持显式 risk 输入）。
