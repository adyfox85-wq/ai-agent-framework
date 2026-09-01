# AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001 — Implementation Report

> Task: A4 prerequisite slice 3 — Capture WorkBuddy economic metadata facts
> （从当前真实 WorkBuddy/CodeBuddy RemoteConfig 或等价 runtime source 中，以只读、可审计方式采集与模型经济性有关的事实：multiplier / promotion / validFrom / validUntil / source / observed_at / freshness）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **IMPLEMENTED**（prerequisite slice delivered）；A4 = 未启动（NOT STARTED，正式实现 scope 未开始）；A0-A3 = CLOSED / COMPLETE / SYNCED（不变）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **WorkBuddy 经济性元数据事实层已证据化**（Objective / Acceptance 1-2）：真实只读
   runtime probe（`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/economic_probe/`，
   observed_at=2026-09-02T02:10:30+08:00，codebuddy 2.141.0）找到并解析了当前
   WorkBuddy/CodeBuddy 实际使用的经济元数据源：
   - **主源** = WorkBuddy RemoteConfig 缓存 `~/.workbuddy/cache/acc-product-config-v3.json`
     （ACC_PRODUCT_CONFIG_V3 / genieVersion 5.4.5 / date=2026-08-29T17:16:22.337Z /
     commit=fa1d65ec13f3c977ec439ecc969279ed03cb09a1）→ `models[].credits` 乘数 +
     `modelPromotions[]`（kind=discount / discount.factor / schedule.validFrom /
     validUntil / daily 时段）；
   - **佐证** = CodeBuddy CLI 运行时 model catalog 缓存
     `~/.codebuddy/local_storage/entry_d43e96994f944cfb77961c2ea7d04605.info`
     （ts=2026-09-02T02:01:14+08:00，即 probe 前 9 分钟刷新）→ 逐模型 credits，
     与主源一致（唯一例外 minimax-m2.7：主源 x0.26 vs CLI catalog x0.19，记录在案、
     不按假设消解）。
2. ✅ **只捕获证据字段**（Requirement 2）：15 个 CLI 候选全部有 multiplier 事实；
   5 个显式促销事实（hy3/hy4-preview = 限时免费 factor 0 带 validFrom/validUntil
   窗口；glm-5.2/deepseek-v4-flash/deepseek-v4-pro = 夜间折扣 factor 0.5 仅 daily
   时段）；无 validFrom/validUntil 字段 → None；无显式促销条目 → promotion_status=None
   （credits x0.00 而无促销条目**不**推断免费）。
3. ✅ **最小表示 + 零路由消费**（Requirement 3/8）：新模块
   `ai_agent_framework/workbuddy_economics.py`（EconomicFact / parse_multiplier /
   classify_freshness / is_authoritative_cheap / cheapness_rank / facts_to_dict &
   facts_from_dict，schema_version=1，校验失败 ValueError fail closed）。经济事实
   **只存储**——adapters / shadow_routing / active_routing / runner / cost_guard /
   model_registry 源码级零 import（测试锁定），production WorkBuddy invocation 零修改
   （CodeBuddy Auto，精确 `[-p --output-format text -y]`，无 --model/--effort）。
4. ✅ **新鲜度显式 fail-closed**（Requirement 4/5）：FRESH 需要 validFrom+validUntil
   窗口覆盖参考时间；STALE = 过期/未生效；UNKNOWN = 时间戳缺失/单边/不可解析。
   `is_authoritative_cheap` 需 FRESH + 显式 free 促销 + multiplier==0.0 **三者同立**；
   STALE/UNKNOWN 的乘数绝不作为便宜/免费权威（`cheapness_rank` 保证 STALE/UNKNOWN
   永不 outrank 已知 FRESH 事实）。
5. ✅ **经济事实低于 capability/qualification gate**（Requirement 6/7）：FRESH FREE 的
   hy3/hy4-preview 仍 tier=None + qualification=unknown → is_usable_candidate False
   （selector LOW workbuddy 仍只选 deepseek-v4-flash，FRESH FREE 候选仍
   CAPABILITY_INSUFFICIENT）；deepseek-v4-flash 既有 T4 + QUALIFIED 零变化；其余 14
   候选保持 tier=None + qualification=unknown；registry 完全未改动。
6. ✅ **RemoteConfig 可解析但保守**（Requirement 10 不触发 fallback 场景，纪律仍保持）：
   实际找到了可解析的 RemoteConfig 缓存（acc-product-config-v3.json），parser 契约
   完全 grounded 于观察到的格式（`x0.17` / `x0.17 credits` credits 字符串、
   `discount.factor`、`schedule.validFrom/validUntil`）；无日期窗口/仅 daily 时段的
   促销诚实分类 UNKNOWN，不发明 validFrom/validUntil。
7. ✅ **测试 + 回归全过**（§5）：29 项新增聚焦测试 + 全量 non-GUI 4-file-deselect =
   **1699 passed / 1 skipped / 38 deselected**（HEAD 0ebbbff 基线 1670 + 29 精确零
   回归，WorkBuddy 可复现排除约定：4 个真实桌面 E2E 文件 --deselect）。
8. ✅ **fresh-runner N+1 通过**（§6）：2/2 —— N1 LOW 全生命周期 SUCCESS（fake
   codebuddy argv 精确 Auto 无 --model/--effort）；N2 fresh-process economic
   artifact 可读（facts_from_dict 解析 economic_facts.json、freshness 与
   classify_freshness(observed_at) 一致）+ 路由权威零变化。
9. ✅ **状态更新最小化**（Requirement 11）：PROJECT_STATE.md / backlog 只记录本
   prerequisite slice；**A4 未标 STARTED**（正式实现 scope 未开始）。

## 2. Scope Boundary

本任务 = **A4 prerequisite slice 3**：只建立「经济性元数据事实层」。

- **In scope**：真实只读 runtime probe（WorkBuddy RemoteConfig 缓存 +
  CodeBuddy CLI catalog 缓存 + settings/config 零经济 key 复核）；经济事实
  表示（EconomicFact + 新鲜度分类 + fail-closed 便宜权威判定）；economic_facts.json
  observation artifact；测试 + 回归；fresh-runner N+1；文档。
- **Out of scope（A4 正式实现，未开始）**：economic routing、active `--model`
  selection、multiplier-based ordering、RemoteConfig routing consumption、effort
  selection、fallback。
- **边界（Boundaries 显式 anti-pullback）**：无 active --model routing；无 effort
  routing；无 automatic fallback；无 CodeBuddy Auto 替换；无 health/quarantine；无
  runtime requalification loop；无 Cost Gate UX；无 Hermes 变更；无 Codex routing；
  无 A5/A6。adapters / shadow_routing / active_routing / runner / cost_guard /
  model_registry 零代码修改。

## 3. Economic Evidence（只读，Requirement 1/2/10）

证据目录：`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/economic_probe/`
（capture_economics.py / capture_timestamps.py / dump_catalog_econ.py /
dump_product_config.py / scan_workbuddy_cache.py / generate_facts_artifact.py +
probe_transcript.txt + catalog_economic_snapshot.json +
product_config_economic_snapshot.json + product_config_dump.txt +
economic_facts.json；全部 untracked，与既有 .aaf 证据约定一致）。

| 事实 | 证据 | 结论 |
|---|---|---|
| 安装版本 | `codebuddy --version` → `2.141.0`（exit 0） | version=2.141.0（动态 probe） |
| 当前模型 config | `codebuddy config get model` → 空（exit 0） | **CodeBuddy Auto 保持**（probe 零配置修改）；`codebuddy config list` 无经济 key |
| 主源 RemoteConfig | `~/.workbuddy/cache/acc-product-config-v3.json`（mtime 2026-09-01T07:36:58+08:00；`date=2026-08-29T17:16:22.337Z`；`commit=fa1d65e`） | WorkBuddy RemoteConfig 缓存（ACC_PRODUCT_CONFIG_V3 / genieVersion 5.4.5 / deploymentType=SaaS / endpoint=copilot.tencent.com）——`models[48].credits` 乘数 + `modelPromotions[5]`（factor/schedule/validFrom/validUntil）+ `modelTiers`（订阅优先，非经济乘数，只作源事实） |
| 佐证 CLI catalog | `~/.codebuddy/local_storage/entry_d43e96994f944cfb77961c2ea7d04605.info`（ts=2026-09-02T02:01:14+08:00） | CodeBuddy CLI 运行时 model catalog（28 models）→ 逐模型 credits，与主源一致（minimax-m2.7 例外：x0.26 vs x0.19，记录在案） |
| settings 层 | `~/.codebuddy/settings.json` / `user-state.json` / `history.jsonl` / `local_storage` 全量经济 key 扫描 | 除上述 catalog 与 product config 外无其他经济元数据（statsig 缓存目录不存在） |
| 促销事实 | `modelPromotions[]` | hy3（限时免费 0x，validFrom=2026-07-06T00:00:00+08:00，validUntil=2026-10-01T00:00:00+08:00，priority 200）；hy4-preview（限时免费 0x，validFrom=2026-08-28T00:00:00+08:00，validUntil=2026-09-11T00:00:00+08:00，priority 200）；glm-5.2（夜间折扣 0.5x，daily 23:00–7:50 Asia/Shanghai，无日期窗口）；deepseek-v4-flash/-pro（夜间折扣 0.5x，daily 0:00–23:59 非高峰 5 折，无日期窗口） |
| 限制记录（Requirement 10） | probe_transcript / economic_facts.json limitations | 无 validFrom/validUntil 的候选（无促销或仅 daily 时段）→ freshness=UNKNOWN（fail closed）；credits x0.00 无促销条目 → 不推断免费；非 CLI 候选的 catalog 模型（fast-model / hy4-preview-x / deepseek-v4-flash-ioa 等）→ 只作源事实、无 baseline 事实（当前 runtime 不支持即不发明） |

## 4. 捕获的经济事实（provenance 完整，Requirement 2）

15 个 CLI 候选（model_id → multiplier → promotion → freshness@observed_at）：

| model_id | multiplier | promotion_status | validFrom / validUntil | freshness |
|---|---|---|---|---|
| hy4-preview | 0.0 | free | 2026-08-28 → 2026-09-11 | **FRESH** |
| hy3 | 0.0 | free | 2026-07-06 → 2026-10-01 | **FRESH** |
| hy3-x | 0.05 | None | — | UNKNOWN |
| glm-5.3 | 0.79 | None | — | UNKNOWN |
| glm-5.3-flash | 0.06 | None | — | UNKNOWN |
| glm-5.2 | 0.79 | discount (0.5x) | daily-only → 无窗口 | UNKNOWN |
| glm-5.1 | 0.79 | None | — | UNKNOWN |
| glm-5v-turbo | 0.71 | None | — | UNKNOWN |
| minimax-m3 | 0.25 | None | — | UNKNOWN |
| minimax-m2.7 | 0.26 | None | — | UNKNOWN（主源 x0.26 vs CLI catalog x0.19 差异记录在案） |
| kimi-k3-1 | 1.62 | None | — | UNKNOWN |
| kimi-k2.7 | 0.57 | None | — | UNKNOWN |
| kimi-k2.6 | 0.52 | None | — | UNKNOWN |
| deepseek-v4-pro | 0.51 | discount (0.5x) | daily-only → 无窗口 | UNKNOWN |
| deepseek-v4-flash | 0.17 | discount (0.5x) | daily-only → 无窗口 | UNKNOWN |

- source = `.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/economic_probe/`
  （evidence 常量 `_EVID_A4_WORKBUDDY_ECONOMICS_001`，含主源/佐证/observed_at/版本）；
- source_version = WorkBuddy RemoteConfig 缓存版本（genieVersion 5.4.5 / date /
  commit + 缓存 mtime）；
- observed_at = 2026-09-02T02:10:30+08:00（probe 完成时刻，全部 15 事实同值）；
- freshness 不存储于事实本身，由 `classify_freshness(fact, now)` 对显式参考时间
  计算并写入 observation 文档（`freshness_reference_time` 显式），保证可复现。

## 5. 代码 / 测试变更

- `ai_agent_framework/workbuddy_economics.py`（新增，事实层模块）：
  - 常量：`ECON_FRESH/STALE/UNKNOWN`、`PROMO_STATUS_FREE/DISCOUNT`、
    `RANK_AUTHORITATIVE_CHEAP/FRESH_DISCOUNT/UNKNOWN_OR_STALE`、
    `WORKBUDDY_CANDIDATE_IDS`（15，与 discovery 同一证据链）、
    `_EVID_A4_WORKBUDDY_ECONOMICS_001`（完整 provenance）、`_ECON_OBSERVED_AT`；
  - `parse_multiplier(raw)`：解析 observed 格式（`x0.17` / `x0.17 credits`），
    失败 → None（fail closed，不发明）；
  - `classify_freshness(fact, now)`：确定性三态（FRESH/STALE/UNKNOWN；naive now →
    ValueError；不可解析/单边时间戳 → UNKNOWN）；
  - `is_authoritative_cheap(fact, now)`：FRESH + 显式 free + multiplier==0.0 三者
    同立才 True（STALE/UNKNOWN/折扣/不一致一律 False）；
  - `cheapness_rank(fact, now)`：0=权威免费 / 1=FRESH 折扣 / 2=其余——STALE/UNKNOWN
    永不 outrank 已知 FRESH（Requirement 5 可判定编码）；
  - `EconomicFact` dataclass（frozen，校验 fail-closed：model_id 非空 / multiplier
    ≥0 / promotion_status ∈ {free, discount, None} / factor ∈ [0,1] / validFrom/
    validUntil ISO 8601 带时区）；
  - `fact_to_dict / fact_from_dict / facts_to_dict / facts_from_dict`
    （schema_version=1；freshness 派生字段——存储时不信任已存 freshness，永远对
    参考时间重算）；
  - `baseline_economic_facts()`：15 候选基线事实（只填证据字段）。
- `tests/test_a4_workbuddy_economics.py`（新增，29 项）：baseline 覆盖与 provenance /
  multiplier 值对主源逐项核对 / 显式促销条目纪律（x0.00 无促销不推断免费）/
  parse_multiplier 格式与 fail-closed / FRESH-STALE-UNKNOWN 确定性分类 /
  参考时间必须 tz-aware / STALE·UNKNOWN·无促销·不一致·折扣 均非权威便宜 /
  唯一权威免费组合（FRESH+free+0.0）/ cheapness_rank 排序不变量 /
  FRESH FREE 候选仍 ineligible（capability gate 先于经济）/
  qualified 候选 registry 维度零变化 / selector 零变化 /
  经济模块不被 routing 代码 import（源码级断言）/ production invocation 不变 /
  round-trip 保留 provenance / 未知 schema_version fail closed / 构造校验 fail closed。
- `tests/fresh_runner_a4_wb_econ_validation.py`（新增，fresh-runner N+1 driver）。
- `tests/fresh_runner_a4_wb_econ_artifact_check.py`（新增，fresh-process artifact +
  authority 检查）。
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`：
  Last Updated + A4 Economics Delivered 段 + CAP-002 Current Implementation。
- `docs/internal/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-REPORT.md`（本文件）。

命令与结果：

```
python -m pytest tests/test_a4_workbuddy_economics.py -q
  → 29 passed（~0.1s）
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_e2e.py --deselect tests/test_phase_e_force_e2e.py \
  --deselect tests/test_phase_f_e2e.py
  → 1699 passed, 1 skipped, 38 deselected（~67s）
python -m pytest -q --ignore=tests/test_a4_workbuddy_economics.py <同上 4 个 deselect>
  → 1670 passed, 1 skipped, 38 deselected（HEAD 基线复现）
```

对账：HEAD（0ebbbff）基线 = 1670 passed / 1 skipped / 38 deselected（WorkBuddy
可复现排除约定；本 commit 只新增 1 个测试文件，未改任何既有测试）→ 本分支 =
1670 既有 + 29 新增 = **1699**，精确零回归。

## 6. Fresh-Runner N+1（Requirement Fresh Runner）

证据：`.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/fresh-runner-validation/`
（scenario_record.json + N1-low/ + N2-artifact-authority-fresh-process 输出）。

- **N1（Risk: LOW 全生命周期）**：fresh runner 进程 + fake hermes/codebuddy/codex
  .bat（真实 child process）→ run.json status=SUCCESS、workbuddy verdict=PASS、
  codex verdict=APPROVE、REPORT.md + context_manifest.json 生成；
  **fake codebuddy marker ARGS 精确 = `-p --output-format text -y`**
  （无 --model/--effort，CodeBuddy Auto 保持）。
- **N2（fresh-process artifact + authority）**：全新 python 进程 →
  economic_facts.json 存在且 facts_from_dict 可解析（15 候选齐全）；
  每条事实的 stored freshness == classify_freshness(fact, observed_at)（可复现）；
  hy3/hy4-preview=FRESH + authoritative cheap；deepseek-v4-flash=UNKNOWN 非 cheap；
  LOW workbuddy selector 仍只选 deepseek-v4-flash（FRESH FREE 候选仍
  CAPABILITY_INSUFFICIENT）；`_workbuddy_invocation` 仍精确 Auto 形状。

## 7. A4-A6 Anti-Pullback

本任务未实现：WorkBuddy/economic/multi-agent routing、active `--model` selection、
multiplier-based ordering、RemoteConfig routing consumption、effort selection、
fallback、Cost Gate UX（A5）、observation/calibration/runtime requalification
（A6）、health/quarantine。A4 保持 **NOT STARTED**（本 slice 只是 prerequisite
事实层；正式实现 scope 未开始）。

## 8. Git 状态

- 基线：main @ `0ebbbff7cae145e3455051ff6ee2c8522f936710`（= origin/main；
  tracked working tree 在任务开始前 CLEAN，仅 3 个 PRE_ALLOWED_UNTRACKED 常驻项：
  .aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs）。
- 本任务 commit：本地 main 新增（见 structured result `commit` 字段）；
  **未 push**（review 后同步，与 A0-A3 惯例一致）。
- 新证据 artifact 位于 `.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/`
  （untracked，与既有 .aaf 证据约定一致）。
