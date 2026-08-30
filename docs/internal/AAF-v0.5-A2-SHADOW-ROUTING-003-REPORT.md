# AAF-v0.5-A2-SHADOW-ROUTING-003 — Implementation Report

> Task: A2 Shadow Routing — Establish explicit task-risk provenance（第三片：TASK 显式 Risk → shadow observation）
> Executor: Hermes（AAF Executor stage）2026-08-31
> Status: **IMPLEMENTED**；A2 保持 **STARTED**（Shadow-only，未进入 A3）；A1 保持 CLOSED / COMPLETE / SYNCED
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **task risk 有唯一、显式、结构化 provenance**（Requirement 1/2）：TASK contract
   新增可选顶层字段 `Risk: LOW|MEDIUM|HIGH|CRITICAL`——唯一词汇 authority = A1
   `risk_contract.RISK_CLASSES`（复用，**不创建第二套 risk authority**）；Planner
   显式声明，不做大小写猜测 / 同义词映射 / 正文推断（测试锁定）。
2. ✅ **missing Risk 安全向后兼容**（Requirement 2）：旧格式 TASK 无 Risk 字段 →
   校验通过、任务正常执行，Hermes shadow risk = 明确的 `RISK_UNAVAILABLE`
   （missing ≠ LOW，测试锁定）。
3. ✅ **invalid Risk 不被静默接受**（Requirement 2）：字段存在但值非法（大小写 /
   同义词 / 非词汇）→ 双层 fail-closed——framework `task_validation`（正式校验）
   与 bridge `task_io`（早期 UX Guard）各自明确报错；runner 在 Validation 阶段
   fail-closed（Hermes 零执行，测试锁定）。
4. ✅ **Risk 进入既有 immutable provenance / runtime metadata 链**（Requirement 3）：
   `TASK.snapshot.md` 冻结保留 Risk（execution authority）→ `context_manifest.json`
   task hash = snapshot 原文 SHA-256 → runner Hermes stage 只读解析 → `shadow_observation.json`
   `risk_class`/`risk_source` → stage result `shadow_observation_ref`。**无平行状态文件**。
5. ✅ **Hermes shadow observation 消费结构化 risk**（Requirement 4）：有显式有效
   Risk → `risk_source` 固定标记 task/planner provenance（`TASK_RISK_SOURCE`），
   并允许调用现有 A2-001 selector 产生真实 hypothetical decision；缺失 → 继续
   `RISK_UNAVAILABLE`；绝不从 prose / Task Name / Route / 文件路径推断。
6. ✅ **actual execution authority 完全不变**（Requirement 5/6）：`adapters.run_agent`
   零修改；runner 仍以原始 `(agent, prompt, workspace)` 调用；零新增
   provider/CLI/LLM 调用；Paid Guard 未修改；未进入自动路由；`authoritative=false`
   / `execution_affected=false` 固定语义 + validate fail-closed + 测试 + N+1 三重复核。
7. ✅ **focused tests 28 项**（Requirement 7 全矩阵 + 守卫），全量 non-GUI 零回归
   （同 invocation 基线 1577 + 28 = 1605 精确对账）。
8. ✅ **Fresh-runner N+1 通过**（本任务修改 intake/runtime metadata path）：显式
   `Risk: HIGH` 的 TASK 全链验证，见 §9。
9. ✅ **最小文档更新**（Requirement 8）：`templates/TASK.md` + PROJECT_STATE +
   backlog 明确「Planner explicit Risk = structured provenance；missing ≠ LOW；
   A2 仍为 Shadow-only」。

## 2. A2 Scope Boundary

本任务 = **A2 第三片（explicit task-risk provenance，observation-only）**：

- **In scope**：TASK contract `Risk` 可选字段（task_validation + bridge/task_io +
  templates）+ runner Hermes-stage 只读解析透传 + shadow_observation provenance
  常量 + 28 项聚焦测试 + N+1 + 文档。
- **Out of scope（后续 A2 slice）**：实况 qualification 观测、候选 tier 证据化赋值、
  WorkBuddy/Codex shadow observation、runtime 风险分类接入。
- **A2 boundary（Requirement Boundaries）**：未实现自动风险分类、无 LLM risk
  classifier、未扩 WorkBuddy/Codex shadow routing、未进入 A3 自动模型选择、未实现
  fallback / health polling / quarantine。

## 3. Reused Contracts（复用，零复制、零发明）

| 契约 | 消费方式 |
|---|---|
| `risk_contract.RISK_CLASSES`（A1） | `Risk` 字段唯一合法词汇（task_validation + bridge 同一 authority，无第二套词汇） |
| `shadow_observation.build_shadow_observation(risk_class, risk_source, ...)`（A2-002） | 显式 risk 消费点：risk_source 标记 task/planner provenance，调用 A2-001 selector |
| `shadow_routing.select_shadow_candidate`（A2-001） | 有显式 risk 时计算真实 hypothetical decision |
| `task_validation.parse_task_fields` / `OPTIONAL_FIELDS`（RW-008 既有 parser） | 顶层字段解析（Risk 加入 OPTIONAL_FIELDS，解析逻辑零改动） |
| `bridge/task_io`（早期 UX Guard） | 与正式校验同语义的 intake 校验（Risk 解析/拒绝） |
| immutable `TASK.snapshot.md` + `context_manifest.json`（FIX-004 既有 authority） | Risk 的 provenance 载体（冻结 + SHA-256，不另造状态文件） |

## 4. Implementation（实现明细）

### 4.1 `ai_agent_framework/task_validation.py`

- `OPTIONAL_FIELDS` 增加 `"Risk"`（可选顶层字段；缺失 = 向后兼容）。
- `from .risk_contract import RISK_CLASSES`——唯一词汇 authority。
- `validate_task_text`：字段存在且值不在 `RISK_CLASSES` → 明确错误
  「非法 Risk 字段: <value>（只接受 LOW, MEDIUM, HIGH, CRITICAL；…不做大小写/
  同义词猜测）」（fail-closed，不静默降级）。

### 4.2 `bridge/task_io.py`（早期 UX Guard，与正式校验双层一致）

- `SINGLE_LINE_FIELDS` 增加 `"risk": "risk"`（`Risk: HIGH` 单行解析）。
- `validate_task_text`：非法值 → 同样明确错误（Planner 在 GUI 入口即被拦截）。

### 4.3 `ai_agent_framework/shadow_observation.py`

- 新增 `TASK_RISK_SOURCE` 常量——固定 provenance 描述：「TASK.Risk field —
  planner-declared explicit risk in the immutable TASK.snapshot.md (validated
  against risk_contract.RISK_CLASSES; no inference from prose/name/route/path)」。
- 消费路径（`risk_class`/`risk_source` → selector）为 A2-002 既有能力，零改动。

### 4.4 `ai_agent_framework/runner.py`（Hermes stage 唯一 wiring 点）

- Hermes stage 内：`task_risk = parse_task_fields(task).get('Risk') or None`，
  非空时以 `risk_class=task_risk, risk_source=TASK_RISK_SOURCE` 调用
  `observe_shadow_stage`；缺失 → 不传（保持 RISK_UNAVAILABLE）。
- snapshot 已通过 `validate_task_text`（非法值在 Validation 阶段 fail-closed），
  故此处解析到的值必然合法或为空；双 try/except 非阻塞不变；`run_agent` 调用
  形态零变化。

### 4.5 `templates/TASK.md`

- 新增可选 `Risk:` 字段说明（LOW|MEDIUM|HIGH|CRITICAL；缺失 = 向后兼容且
  shadow risk = RISK_UNAVAILABLE，missing ≠ LOW；非法值严格拒绝；Planner 显式
  Risk = structured provenance）。空模板字段解析为空字符串（向后兼容）。

## 5. Test Matrix（Requirement 7 全矩阵，28 项）

`tests/test_task_risk_provenance.py`：

| # | 覆盖 | 断言 |
|---|---|---|
| 1–4 | LOW/MEDIUM/HIGH/CRITICAL 合法值 | parse + framework/bridge 校验通过；bridge parse 同值 |
| 5–8 | 合法值 → shadow consumption | `build_shadow_observation` risk_class=值、risk_source=TASK_RISK_SOURCE、selector 被调用（decision 存在） |
| 9 | 缺失 Risk 旧 TASK 向后兼容 | validate 通过；parse 为空 |
| 10 | 缺失 → runner shadow RISK_UNAVAILABLE | risk_class=None、risk_source=RISK_UNAVAILABLE、decision=None |
| 11–15 | 非法 Risk 严格拒绝（low/Low/EXTREME/HIGH risk/5） | framework + bridge 均报「非法 Risk」 |
| 16 | 非法 → runner Validation fail-closed | TaskValidationError；Hermes 零执行、无 artifact |
| 17 | `MEDIUM ` 尾随空白 | strip 后合法（空白不算非法值） |
| 18 | immutable snapshot/provenance 保留 risk | snapshot 含 `Risk: HIGH`；manifest hash == sha256(snapshot) |
| 19–22 | runner 集成：4 类 risk 均使用值 + 正确 source | shadow_observation.json risk_class/risk_source；stage result ref |
| 23 | 缺字段 → RISK_UNAVAILABLE（prose 有 risk 字样） | 同 10 |
| 24 | 不从 prose/name/route 推断 | 「CRITICAL HIGH-risk MEDIUM」Task Name + prose 词汇 → parse 空 + RISK_UNAVAILABLE |
| 25 | actual execution 不受影响 | `run_agent(agent, prompt, workspace)` 三参数形态 + prompt 内容不变 |
| 26 | shadow 零额外 provider 调用 | observe_stage 次数 = stage 数；shadow 复用同一 observation 对象 |
| 27 | 顶层 preamble 重复声明 Risk | 双层 fail-closed「Risk 字段重复声明」（不得 first/last wins） |
| 28 | 生产回归：Requirements 正文 `Risk: LOW\|MEDIUM\|HIGH\|CRITICAL`（本任务 snapshot 实证） | prose 行不被当字段（parse 空）；校验通过；shadow = RISK_UNAVAILABLE |

回归：同 invocation 全量 non-GUI（`--ignore=tests/test_phase_e_cancel_ui_e2e.py`
预存在 launcher-GC 崩溃文件，A2-002 同惯例）→ **1605 passed / 1 skipped /
9 deselected**；去掉本任务 28 项后基线 **1577 passed**（1577 + 28 = 1605 精确
对账，零回归）。既有 shadow/validation/intake 定向套件 197 项全绿。

## 6. Static Isolation（隔离守卫延续）

- shadow 模块依赖图仍无 subprocess/网络/LLM（既有静态断言继续通过；本任务只加
  字符串常量）。
- runner 是本任务唯一 wiring 点；`run_agent` 调用形态不变（测试 25/26 锁定）。
- bridge 增加 `ai_agent_framework.risk_contract` import（与 duplicate.py/handoff.py
  既有耦合一致；同源词汇，非新 authority）。

## 7. Boundaries Compliance（零越界）

- 无自动风险分类 / 无 LLM risk classifier（风险由 Planner 显式提供）。
- WorkBuddy/Codex shadow routing 未扩展（runner 仍 `agent == 'hermes'` 限定）。
- A3 自动模型选择未进入；无 fallback / health polling / quarantine。
- Paid Guard、adapters、router、cost_guard、report、lifecycle 零修改。

## 8. Changed Files

- `ai_agent_framework/task_validation.py`（Risk 可选字段 + 严格校验）
- `ai_agent_framework/shadow_observation.py`（TASK_RISK_SOURCE 常量）
- `ai_agent_framework/runner.py`（Hermes stage 解析透传 Risk）
- `bridge/task_io.py`（intake 解析 + 校验）
- `templates/TASK.md`（contract 文档）
- `tests/test_task_risk_provenance.py`（28 项定向测试）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`（living state）
- 本 REPORT + N+1 证据目录（`.aaf/AAF-v0.5-A2-SHADOW-ROUTING-003/fresh-runner-validation/N1-task-risk/`）

## 9. Fresh-runner N+1（N1-task-risk）

命令（fresh process，真实 child 边界）：
`python tests/fresh_runner_wrapper.py <N1 TASK.md> --workspace <ws> --output <out>`
env：`AAF_HERMES_MODEL=deepseek-v4-flash` / `AAF_HERMES_PROVIDER=deepseek` /
`AAF_COST_AUTH=<N1 scope>` / `AAF_TEST_FAKE_BIN=fakebin`（fakebin 只拦 `hermes chat`，
config/version/help 探测走真实 CLI 形态；A0 先例）。

结果（证据目录 `D:\AdyAI\ai-agent-framework\.aaf\AAF-v0.5-A2-SHADOW-ROUTING-003\fresh-runner-validation\N1-task-risk\`，
`scenario_record.json` 全文 + `verify_evidence.py`）：

| N+1 验收点 | 证据 |
|---|---|
| 带显式 Risk 的新 TASK 被 fresh runner 正确读取 | `shadow_observation.json` risk_class=`HIGH` |
| immutable snapshot 保留 Risk | `out/TASK.snapshot.md` 含 `Risk: HIGH`；`context_manifest.json` task hash == sha256(snapshot)（True） |
| shadow_observation.json 使用该 risk 和正确 provenance | risk_source = `TASK_RISK_SOURCE`（task/planner provenance 全文） |
| shadow 基于有效 risk 产生真实 hypothetical decision | selector 调用（HIGH → required_floor=T2，5 candidates，全按 role/capability 契约排除 → 显式 NO_SHADOW_CANDIDATE，不虚构资格） |
| actual Hermes model/provider 与 shadow decision 无关 | actual_model=deepseek-v4-flash / actual_provider=deepseek（source=config + env override 事实）；marker 证明真实 child 跑 `hermes chat --in`；guard 精确消费原 scope |
| authoritative=false / execution_affected=false | artifact 字段 = false（validate fail-closed） |
| REPORT/lifecycle 正常 | REPORT Current Status=SUCCESS；run.json SUCCESS、terminal_generation=1；REPORT 无平行 shadow 段 |

## 10. Unresolved Issues

None identified.

## 11. Remote Sync / 交付状态

- 本提交未 push（与 A1/A2-001/A2-002 惯例一致：review 通过后同步）。
- A2 保持 **STARTED**；A1 保持 CLOSED / COMPLETE / SYNCED。
- CAP-003（实际 Model Routing）仍 **NOT IMPLEMENTED**。
