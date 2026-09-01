# AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001 — Implementation Report

> Task: A4 prerequisite slice — Discover WorkBuddy model candidates
> （从当前真实 CodeBuddy/WorkBuddy runtime 发现可选 model IDs，并以可审计、非权威方式写入 registry identity facts）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **IMPLEMENTED**（prerequisite slice delivered）；A4 = 未启动（NOT STARTED，正式实现 scope 未开始）；A0-A3 = CLOSED / COMPLETE / SYNCED（不变）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **WorkBuddy 具体候选身份已证据化**（Objective / Acceptance 1）：当前真实 runtime
   只读 probe（`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001/discovery/`，
   observed_at=2026-09-02T01:23:05+08:00）证明 `codebuddy --help`（v2.141.0）的
   `--model` 帮助行文档化 **15 个当前支持的 model IDs**；全部以 identity-only
   registry 条目写入 baseline（`model_registry.baseline_entries()`），每条带
   evidence 引用（版本 + observed_at + 来源命令）。WorkBuddy 不再只有匿名
   `model=None` 单一事实。
2. ✅ **只收录当前 runtime 支持的 ID**（Requirement 2）：`hy4-preview-x` 曾出现在
   2026-08-29 帮助快照（tests 内 mock fixture）但当前 runtime 帮助文本已不列出
   → **不收录**（当前 runtime 不支持即不发明）。
3. ✅ **候选事实全部保守**（Requirement 5）：每个候选 `capability_tier=None` /
   `qualification=unknown` / `cost_class=UNKNOWN` / `locality=unknown` /
   `provider=None`（CLI 不暴露底层 provider）——发现身份 ≠ 任何能力/资格/成本证据；
   `is_usable_candidate` fail closed，**无候选因 ID 被发现而 eligible**。
4. ✅ **selector 可枚举 WorkBuddy 候选但不可用**（Requirement 8 / Acceptance 2-3）：
   `select_shadow_candidate(..., stage_agent="workbuddy", ...)` 的
   `candidates_considered` 含全部 15 候选 + `agent:workbuddy` 锚点；因 tier=None
   全部以 `CAPABILITY_INSUFFICIENT` 排除 → `eligible=()` / `selected=None` /
   `NO_SHADOW_CANDIDATE`。对 hermes / codex stage 候选以 `ROLE_NOT_APPLICABLE`
   排除——既有 Hermes/Codex 选择语义零变化。
5. ✅ **FREE/cheap/promo 零推断**（Requirement 8 / Acceptance 3）：全部候选
   `cost_class=UNKNOWN`（economic rank 2，永不因成本获胜）、不在
   `FREE_OF_COST_CLASSES`；无成本、无 multiplier、无 promotion 数据进入任何判定。
6. ✅ **CodeBuddy Auto 调用不变**（Requirement 6 / Acceptance 4）：
   `adapters._workbuddy_invocation` args 精确 = `[exe, -p, --output-format, text,
   -y]`，零 `--model` / `--effort` / provider 变更；测试锁定（含 run_agent 全链）。
7. ✅ **RemoteConfig 只登记源事实**（Requirement 7）：当前 runtime 不可观测
   （`--help` 无 remote economic-config 命令/flag；`~/.codebuddy/settings.json`
   无 model/effort/remote/promo/multiplier key）→ 只记录「不可观测」源事实；
   不解析 multiplier/promotion，不进路由权威。
8. ✅ **测试 + 回归全过**（§5）：13 项新增聚焦测试 + 全量 non-GUI 4-file-deselect =
   **1650 passed / 1 skipped / 40 deselected**（HEAD 0a496e3 基线 1637 + 13 新增，
   精确零回归，与 A3-FIX-001 同一排除约定）。
9. ✅ **状态更新最小化**（Requirement 9）：PROJECT_STATE.md / backlog 只标记本
   prerequisite slice 已交付；**A4 未标 STARTED**（正式实现 scope 未开始）。

## 2. Scope Boundary

本任务 = **A4 prerequisite slice**：只解决「有哪些候选」的 identity 事实层。

- **In scope**：真实只读 runtime discovery（`codebuddy --version` / `--help` /
  `config get model` / settings.json 只读扫描）；registry identity-only 候选条目
  （15 个，带 provenance）；selector 可枚举性验证；调用不变验证；测试 + 回归；文档。
- **Out of scope（A4 正式实现，未开始）**：capability/qualification、economic
  routing、active `--model` selection、multiplier-based ordering、RemoteConfig
  routing consumption、effort selection、fallback。
- **边界（Boundaries 显式 anti-pullback）**：无 capability promotion；无
  qualification；无 multiplier 排序；无 RemoteConfig 消费；无 active WorkBuddy
  routing；无 effort selection；无 Hermes 变更；无 Codex routing；无 A5/A6；
  无 health/quarantine/calibration。adapters 调用零修改。

## 3. Discovery Evidence（只读，Requirement 1/2/3/7）

证据目录：`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001/discovery/`
（capture_evidence.py + codebuddy_version.txt + codebuddy_help.txt +
discovery_facts.json；全部 untracked，与既有 .aaf 证据约定一致）。

| 事实 | 证据 | 结论 |
|---|---|---|
| 安装版本 | `codebuddy --version` → `2.141.0`（exit 0） | version=2.141.0（动态 probe，非硬编码） |
| 当前模型 config | `codebuddy config get model` → 空（exit 0） | 当前模型不由用户 config 暴露 → **CodeBuddy Auto**（CLI default / last-used），config 非权威 |
| 支持模型目录 | `codebuddy --help` `--model` 帮助行 "Currently supported: (...)"（help 全文 12149 bytes 存档） | **15 个 model IDs**（见 §4） |
| 用户 settings | `~/.codebuddy/settings.json` → 仅 trustedDirectories；无 model/effort/remote/promo/multiplier key | 无经济/模型覆盖配置 |
| RemoteConfig | `--help` 无 remote economic-config 命令/flag；settings 无相关 key | **当前 runtime 不可观测** → 只登记源事实（existence 不可本地观测；无版本/freshness 可得），不解析 |

## 4. 发现的候选（provenance 完整，Requirement 3）

model_id（15）：`hy4-preview`、`hy3`、`hy3-x`、`glm-5.3`、`glm-5.3-flash`、
`glm-5.2`、`glm-5.1`、`glm-5v-turbo`、`minimax-m3`、`minimax-m2.7`、
`kimi-k3-1`、`kimi-k2.7`、`kimi-k2.6`、`deepseek-v4-pro`、`deepseek-v4-flash`。

- **provider / agent identity**：agent = workbuddy（`applicable_agents=("workbuddy",)`）；
  底层 provider **未暴露**（CLI 不提供）→ `provider=None`。
- **discovery source**：`codebuddy --help` `--model` 帮助行（version-level static
  metadata；refresh = 重新 `--help`，非 AAF 硬编码永久事实）。
- **observed_at**：2026-09-02T01:23:05+08:00（真实 probe 完成时间）。
- 不收录：`hy4-preview-x`（2026-08-29 帮助快照存在，当前 runtime 已不列出）。

registry 表示（Requirement 4，最小扩展）：同一 `RegistryEntry` schema、零新字段；
`agent:workbuddy`（model=None）保留为「当前 Auto 调用」锚点，其下新增 15 个
identity-only 条目（key = model ID，因 provider=None 无 `@provider` 后缀；
`deepseek-v4-flash` 与 Hermes 条目 `deepseek-v4-flash@deepseek` 不同 key，无冲突）。

## 5. 代码 / 测试变更

- `ai_agent_framework/model_registry.py`：
  - 新增 `_EVID_A4_WORKBUDDY_MODEL_LIST`（完整 provenance 证据常量）+
    `_WORKBUDDY_CLI_DOCUMENTED_MODEL_IDS`（15 个 ID，当前证据快照）；
  - `baseline_entries()`：WorkBuddy Auto 条目 notes 更新（Auto 锚点语义 +
    RemoteConfig 源事实）；新增 15 个 identity-only 候选条目（comprehension，
    capability/qualification/cost/locality 全 UNKNOWN）。
  - 零 schema 变更、零新模块、纯数据层（保持无 subprocess/网络依赖测试）。
- `tests/test_model_registry.py`：`test_baseline_keys_unique_and_stable` 期望集合
  扩展为 20 个 key（5 既有 + 15 候选）——唯一因 registry 内容变化的既有断言。
- `tests/test_a4_workbuddy_discovery.py`（新增，13 项）：
  1. 候选存在性 + 精确集合；2. identity-only 字段全保守（tier=None / qual=unknown /
     cost=UNKNOWN / locality=unknown / provider=None / is_usable_candidate=False）；
  3. registry 候选集合 == CLI `--model` 帮助行解析结果（同一发现语义）；
  4. Auto 锚点保持 model=None；5. 零 FREE/cheap/promo 推断（UNKNOWN 成本 rank 2）；
  6. selector workbuddy stage 全候选可见但零 eligible（NO_SHADOW_CANDIDATE，
     LOW/MEDIUM/HIGH 参数化）；7. hermes stage 不受影响（ROLE_NOT_APPLICABLE +
     既有 selected 语义不变）；8. codex stage 不受影响；9. registry 序列化
     round-trip 保留候选；10. `_workbuddy_invocation` args 精确无 `--model/--effort`；
     11. `run_agent('workbuddy', ...)` 全链 Popen args 无 model/provider 覆盖。

命令与结果：

```
python -m pytest tests/test_a4_workbuddy_discovery.py tests/test_model_registry.py \
  tests/test_shadow_routing.py tests/test_adapters.py tests/test_active_routing.py -q
  → 170 passed（~2.5s）
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_e_e2e.py \
  --deselect tests/test_bridge_launcher.py
  → 1650 passed, 1 skipped, 40 deselected（69.2s）
```

对账：HEAD（0a496e3）基线 = 1637 passed / 1 skipped / 40 deselected（A3-FIX-001
stash 反证 1631 + 6 新增后 9530328/0a496e3 为 docs-only，测试数不变）；
本分支 = 1637 既有 + 13 新增 = **1650**，精确零回归。

## 6. A4-A6 Anti-Pullback

本任务未实现：WorkBuddy/economic/multi-agent routing、capability/qualification、
multiplier 排序、RemoteConfig 路由消费、active `--model` selection、effort
selection、fallback、Cost Gate UX（A5）、observation/calibration/runtime
requalification（A6）、health/quarantine。A4 保持 **NOT STARTED**（本 slice 只是
prerequisite 事实层）。

## 7. Git 状态

- 基线：main @ `0a496e3`（= origin/main；tracked working tree 在任务开始前 CLEAN，
  仅 3 个 PRE_ALLOWED_UNTRACKED 常驻项：.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）。
- 本任务 commit：本地 main 新增（见 structured result `commit` 字段）；
  **未 push**（review 后同步，与 A0-A3 惯例一致）。
- 新证据 artifact 位于 `.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001/`
  （untracked，与既有 .aaf 证据约定一致）。
