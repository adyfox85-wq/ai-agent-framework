# AAF-v0.5-A0-PAID-GUARD-001 — Implementation Report

> Task: v0.5 A0 Hermes Paid Guard — Fail-Closed Task-Scoped Cost Authorization
> Executor: Hermes（AAF Executor stage）2026-08-29
> Status: IMPLEMENTED (A0) — **Codex 审查 = REQUEST_CHANGE → FIX-002 已修复全部三个 blocking fail-open 发现（见文末 §12 FIX-002 修订说明）**；正式 COMPLETE 判定留待 WorkBuddy 独立复验 + Codex re-review + Planner 确认
> 实现证据（Run N）：本文件 + 定向/全量测试 + 单测；运行时证据（Run N+1）：fresh-runner 9/9 场景（FIX-002）

> ⚠️ **FIX-002 修订**：本文 §2/§4/§5 中关于「0.0.0.0 视为本地」「AAF_COST_FREE_MODELS 为权威 FREE 元数据」「env 天然 per-run 一次性」的原始表述已被 FIX-002 推翻，以 §12 为准。

---

## 1. 结论（先给结论）

v0.5 A0 Hermes Paid Guard 已交付并通过全部验收点：

1. ✅ 远程付费/未知成本 Hermes 调用在**无精确 task-scoped 显式授权时 fail closed**——guard 在 Hermes subprocess 创建之前执行，Hermes 进程零创建（单测 run_agent 零调用 + fresh-runner marker 缺失双重证明）。
2. ✅ 已知本地/免费 Hermes 模型照常放行（LOCAL_FREE / 显式 FREE 元数据）。
3. ✅ 授权 = 精确 Task + Hermes stage + model（+provider）整串匹配；env per-run 一次性，不泄漏到后续/无关任务（S4/S5 fresh-runner 实证）。
4. ✅ 未知成本绝不视为免费（A0 分类默认 PAID_OR_UNKNOWN；COST_UNKNOWN fail closed）。
5. ✅ Hermes 全局 config 零修改（只读 `hermes config get model` fallback + AAF 自有 env 覆盖）。
6. ✅ 决策无网络请求、无额外 LLM 调用（本地 env / 只读 CLI config 查询；decision_ms 记录于 cost_guard.json）。
7. ✅ 聚焦回归测试通过：34 项定向 + 全量 non-GUI 1323 passed（1289 基线 + 34 新增，零下降；RW-029 环境 flake 隔离复跑通过）。
8. ✅ fresh-runner Run N+1 验证：6/6 场景全新 python 进程实测。
9. ✅ WorkBuddy / Codex / 完整 routing 未改动（除 guard 所需的最小区块：runner 钩子 + adapters 透传，均向后兼容）。
10. ✅ 本 REPORT 逐项列出实现文件 / 授权表示 / 成本分类 / blocked 行为 / 测试命令与结果 / blocked 零 spawn 证明 / fresh-runner 证据 / A1+ 限制 / git 状态。

---

## 2. 实现文件（最小集合）

| 文件 | 变更 | 说明 |
|---|---|---|
| `ai_agent_framework/cost_guard.py` | 新增 | A0 Paid Guard 核心模块（resolve → classify → authorize → decide；blocked 文本；纯本地零网络） |
| `ai_agent_framework/runner.py` | 修改（+16 行） | `run_agent` 调用前对 `agent=='hermes'` 求值 guard；写入 `cost_guard.json`；BLOCKED 时以 `FRAMEWORK_ERROR` 前缀文本短路（走既有失败链 → WAITING） |
| `ai_agent_framework/adapters.py` | 修改（+10 行） | `AAF_HERMES_MODEL`/`AAF_HERMES_PROVIDER` 设置时向 hermes args 追加 `-m`/`--provider`（guard 解析的 effective model == 实际调用模型；无覆盖时 args 与 v0.4 逐字节一致） |
| `tests/conftest.py` | 修改 | cost_guard hermetic 默认（resolution 固定本地免费模型 + 清除 guard env），保证既有 runner 集成测试零 CLI/零网络、guard 语义 ALLOWED_FREE |
| `tests/test_cost_guard.py` | 新增 | 34 项定向测试（A–F 全场景 + G 回归 + resolution/透传/blocked 文本/时序） |
| `tests/fresh_runner_wrapper.py` | 新增 | fresh-process runner 包装（仅把 fake bin 前置到 CLI discovery PATH；guard 逻辑零修改） |
| `tests/fake_hermes_cli.bat` | 新增 | fresh-runner fake Hermes（config probe → exit 1；chat → marker + 合法 structured result） |
| `tests/fake_codebuddy_cli.bat` | 新增 | fresh-runner fake CodeBuddy（WorkBuddy stage stub，合法 PASS verdict） |
| `tests/fresh_runner_cost_guard_validation.py` | 新增 | Run N+1 驱动（6 场景 × 全新 python 进程） |
| `docs/internal/AAF_MASTER_BACKLOG.md` | 修改 | CAP-004 = IMPLEMENTED (A0) + summary 行 + header 更新 |
| `docs/internal/PROJECT_STATE.md` | 修改 | 顶部新增 v0.5 Current Status 区块（v0.4 冻结区块不动） |
| `docs/internal/AAF-v0.5-A0-PAID-GUARD-001-REPORT.md` | 新增 | 本文件 |

未改动：Hermes / CodeBuddy / Codex 安装文件、Hermes 全局 config、v0.4 冻结文档正文、router/parser/lifecycle 既有语义。

## 3. Hermes stage 调用路径（Requirement 1）

唯一的 Hermes 进程创建点 = `adapters.run_agent()`（`adapters.py:483` 起，`subprocess.run([hermes, chat, --in, -q, -Q, --ignore-rules, --source, tool])`），唯一调用方 = `runner.run()` 的 agent 链循环。guard 钩子插在 `run_agent` 调用**之前**（`runner.py` agent 循环内），因此覆盖 100% Hermes 调用路径，且 `run_agent` 签名不变（既有 mock/调用兼容）。

## 4. 授权表示（Requirement 5；为什么最小）

**选择：单环境变量 + 整串精确匹配。**

```
AAF_COST_AUTH="<Task ID>|<stage>|<model>[|<provider>]"
```

- 解析出的 scope = `scope_string(task_id, stage, model, provider)`；授权匹配 = `auth == scope`（整串相等，无前缀/包含/模糊）。
- 为什么最小：不引入文件子系统/数据库/长生命周期 token/审批 UI。env 只存在于发起进程 → 天然**一次性（per-run）**；runner 无法自行持久化自授权（杜绝 self-authorization）；Task ID 在 scope 内 → **对其他任务天然失效**（S4 fresh-runner 实证：授权写别的 Task ID 即阻断）；stage 恒为 `hermes` → stage-scoped；model（+provider 已知时）精确 → model-scoped。
- 无效设计对照：无 `ALLOW_PAID=true` 全局开关；无 provider-wide 持久授权；前一 Task 的授权对后一 Task 无效（task_id 不匹配即 block）。
- 补充 env（同为 AAF 自有，不改 Hermes config）：
  - `AAF_HERMES_MODEL` / `AAF_HERMES_PROVIDER`：显式 pin effective model/provider，并**透传** `-m`/`--provider` 到实际 invocation（invocation-truth 不变量）。
  - `AAF_COST_FREE_MODELS`：显式权威 FREE 元数据（逗号分隔；条目 = 精确 model 或 `model@provider`）。缺省 = 无任何 FREE 声明。

## 5. 成本分类规则（Requirement 3；A0 刻意最小）

| cost_class | 判定 | 证据 |
|---|---|---|
| `LOCAL_FREE` | provider base_url 含 127.0.0.1 / localhost / 0.0.0.0；或 provider=ollama 且无 base_url（verified local Ollama；有非本机 base_url → 不视为 local，fail closed） | endpoint/provider 事实，非促销表 |
| `FREE` | 仅当 `AAF_COST_FREE_MODELS` 精确匹配（裸 model 或 model@provider） | 显式权威元数据；**绝不按模型名推断** |
| `PAID_OR_UNKNOWN` | 任何未能证明 FREE/LOCAL_FREE 的远程/API 模型（默认） | "UNKNOWN 不视为 FREE" |
| `COST_UNKNOWN`（内部） | effective model 无法解析（env 未设 + `hermes config get model` 失败/缺 CLI） | → BLOCKED（fail closed） |

解析顺序：`AAF_HERMES_MODEL` env → `hermes config get model` 只读查询（与 v0.4 model_observation 同款发现；无网络/无推理）→ 两者皆失败 = COST_UNKNOWN。

## 6. Blocked 行为（Requirement 4/6/7/12）

- guard 在 Hermes subprocess 创建**之前**求值（Requirement 7）。
- `BLOCKED_COST_APPROVAL` 时：不调用 `run_agent`（Hermes 零 spawn）；写入 `cost_guard.json`（机器可读：task_id/stage/decision/cost_class/model/provider/required_scope/authorization_present/authorization_matched/decision_ms/timestamp/notes）；`hermes_result.md` = 以 `FRAMEWORK_ERROR\nCOST_APPROVAL_REQUIRED` 开头的 blocked 文本 → 走既有失败链（`_result_is_valid=False` → 链中断 → 任务 WAITING + integrity note；resume 不会把 blocked 结果当已完成 hermes 结果复用）。
- 人读 blocked 文本完整给出：Task ID / Stage / Effective model / Provider / Cost status / Decision / 阻断原因（中文）/ 所需精确授权（`set AAF_COST_AUTH="..."`）。
- fail closed（Requirement 12）：缺失/损坏/歧义的 cost 元数据或授权 → 一律 BLOCKED，绝不静默放行远程未知成本调用。
- 恢复路径：设置 `AAF_COST_AUTH`（或改用本地模型）后重新提交任务（新 execution）。注：blocked 终态为 WAITING（terminal），resume-from 已终态目录由既有 v0.4 lifecycle 拒绝重开（TerminalAlreadyCommitted），属既有语义，不在本任务变更范围。

## 7. 测试与命令/结果（Requirement 14）

```
python -m pytest tests/test_cost_guard.py -q          → 34 passed in ~0.7s
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_e_e2e.py
  → 1303 passed, 1 skipped, 29 deselected（+3 线程型文件单独 20 passed；合计 1323 = 1289 基线 + 34 新增）
python -m pytest tests/test_phase_e_cancel_ui_e2e.py tests/test_phase_e_force_e2e.py \
  tests/test_phase_e_e2e.py -q                        → 20 passed
```

合计 **1323 passed / 1 skipped**（1289 v0.4 基线 + 34 新增，零下降）。说明：全量单进程连跑在本机触发既有 RW-029（Windows 0x80000003 测试环境观察，已登记 NON-BLOCKING，且与本次变更无关——崩溃位于 bridge launcher 线程测试）；上述分块复跑覆盖全部 1323 项且该 3 个线程型文件单独全过。定向覆盖矩阵：

- A local/free → ALLOWED_FREE（unit + runner 集成 + fresh S2）
- B paid 无授权 → BLOCKED_COST_APPROVAL + **run_agent 零调用**（unit + runner 集成 + fresh S1）
- C 精确 task/stage/model 授权 → ALLOWED_AUTHORIZED_PAID（unit + runner 集成 + fresh S3）
- D 其他 Task 授权 → BLOCKED（unit + runner 集成 + fresh S4）
- E 其他 model 授权 → BLOCKED（unit + runner 集成 + fresh S5）
- F 缺失/歧义 model → fail closed（COST_UNKNOWN）（unit + runner 集成 + fresh S6）
- G 既有 runner 行为回归：全量 1323 通过；默认 hermetic 下 hermes→workbuddy 链照常（`test_g_free_local_hermes_reaches_invocation_regression` 等）
- 附加：分类规则 7 项、scope/匹配 2 项、resolution 4 项、blocked 文本 1 项、透传 2 项、时序 1 项、resume 边界 1 项

## 8. Blocked 案例 Hermes 未 spawn 的证明（Requirement 8）

- **单元/集成层**：`test_b_blocked_paid_hermes_never_spawned` 记录 `run_agent` 调用序列 `calls == []`（Hermes 的唯一进程创建入口从未被调用），且 `hermes_result.md` 内容 = blocked 文本（非任何 Hermes 输出）。
- **fresh-runner 层（更强）**：`fake_hermes_cli.bat` 被真实 child process 拉起时会写 marker 文件；S1/S4/S5/S6 四个 blocked 场景 **marker 均不存在**（`hermes_marker_exists: false`），即真实的 hermes child process 从未被创建；S2/S3 放行场景 marker 存在（`hermes_marker_exists: true`），证明放行路径确实到达了进程创建边界。

## 9. Fresh-runner Run N+1 验证证据（Requirement 15 / Acceptance 8）

驱动：`python tests/fresh_runner_cost_guard_validation.py` → **RESULT: 6/6 scenarios passed**（每个场景 = 全新 python 进程运行本仓库 post-change runner 代码，仅 discovery PATH 前置 fake bin；guard 逻辑零修改）。运行时证据存于 `.aaf/AAF-v0.5-A0-PAID-GUARD-001/fresh-runner-validation/<scenario>/scenario_record.json`（.aaf 为运行证据区，不入库）：

| 场景 | run.status | guard.decision | cost_class | hermes marker |
|---|---|---|---|---|
| S1 paid 无授权 | WAITING | BLOCKED_COST_APPROVAL | PAID_OR_UNKNOWN | 缺失（未 spawn） |
| S2 local/free（ollama） | SUCCESS | ALLOWED_FREE | LOCAL_FREE | 存在（达 invocation 边界） |
| S3 paid + 精确授权 | SUCCESS | ALLOWED_AUTHORIZED_PAID | PAID_OR_UNKNOWN | 存在 |
| S4 其他 Task 授权 | WAITING | BLOCKED_COST_APPROVAL | PAID_OR_UNKNOWN | 缺失 |
| S5 其他 model 授权 | WAITING | BLOCKED_COST_APPROVAL | PAID_OR_UNKNOWN | 缺失 |
| S6 无法解析（config probe 失败） | WAITING | BLOCKED_COST_APPROVAL | COST_UNKNOWN | 缺失 |

self-hosting 边界：本任务由当前 Run N（实现前启动的 runner 进程）执行实现，故本 REPORT 的运行时结论以 Run N+1 fresh 进程证据为准（requirement 15 明示）。

## 10. 已知限制 / A1+ 延期（Requirement 10 / Acceptance 9）

显式不实现（A1+ 范围，本任务零代码）：自动免费模型选择、Hermes candidate Tier registry、Selection Engine / Shadow Routing、WorkBuddy RemoteConfig 解析、WorkBuddy 经济路由、free-to-free fallback、模型能力学习、精确 RMB/token 计价、PAID_LOW/MEDIUM/HIGH、Codex 成本优化、图形化 Cost Gate UX（当前仅最小 blocked-state 文本）、动态 stage 移除、v0.5 Timing/Hotkey/Icon/Productization 项。

已知边界/注意：
- 授权为 env per-run 一次性：blocked 任务的恢复 = 设置授权后重新提交（新 execution）；已终态 WAITING 目录 resume-from 由 v0.4 lifecycle 拒绝（既有语义）。
- `hermes config get model` 只读查询是 resolution fallback（与 v0.4 model_observation 同款只读发现；无网络、无推理）；若需完全离线确定性，用 `AAF_HERMES_MODEL` pin。
- WorkBuddy/Codex stage 不在 A0 保护范围（TASK 明示）。
- 对后续真实任务的影响（预期行为）：Hermes 默认模型 deepseek-v4-flash（remote API）在无 `AAF_COST_AUTH` 时会 fail closed——这是本任务的目的；运行前设置精确授权或使用本地模型即可。

## 11. Git / 状态

- git status：实现前基线 = main @ 5bdefa6（v0.4 freeze metadata）；本次变更仅新增/修改上述实现文件（`.aaf/` 运行时证据保持 untracked，按 RW-017 现状不清理不提交）。
- commit：`3a0f72595de4832c887cb45466c67b2f60a959f6`（feat(v0.5-A0): Hermes Paid Guard — fail-closed task-scoped cost authorization，TASK: AAF-v0.5-A0-PAID-GUARD-001）。
- Remote Sync：**SYNCED**（`git push origin main` 成功：`5bdefa6..3a0f725 main -> main`；ahead-behind 0/0）。

---

## 12. FIX-002 修订说明（TASK: AAF-v0.5-A0-PAID-GUARD-001-FIX-002，2026-08-29）

Codex 最终审查（codex_result.md）对父任务给出 REQUEST_CHANGE，三个 blocking 发现全部属于 A0，
FIX-002 一次性关闭（未扩张到 A1）：

### 12.1 阻断 #1：本地端点判定从 substring 改为 hostname/IP 严格语义（fail-closed）

- 原实现：`any(h in base_url for h in ("127.0.0.1","localhost","0.0.0.0"))` ——
  `https://localhost.evil.example/v1`、`https://api.example/127.0.0.1/v1`、
  `https://notlocalhost.example/v1` 均被误判 LOCAL_FREE（可复现 fail-open）。
- 新实现：`cost_guard._endpoint_is_local()` 用 `urllib.parse.urlsplit` 解析真实 hostname：
  - LOCAL_FREE 仅当 hostname == exact `localhost`（大小写不敏感）或为合法 IP 且
    `ipaddress.is_loopback` 为真（IPv4 127.0.0.0/8 全段、IPv6 `::1`、IPv4-mapped loopback）。
  - 一律拒绝：非 http(s) scheme、无 hostname、非法 port、非 exact localhost 域名
    （localhost.evil.example / notlocalhost.example / 127.0.0.1.evil.com）、合法但非 loopback 的 IP
    （含 0.0.0.0 bind 通配地址 —— 无既有架构安全理由，fail closed）、path/query 中的本地字样、
    畸形/歧义 endpoint（无法安全建立真实 hostname）。
  - ollama 语义保留：provider=ollama 且无 base_url → LOCAL_FREE（verified local Ollama）；
    有 base_url 时一律走端点判定。

### 12.2 阻断 #2：移除 AAF_COST_FREE_MODELS 权威 FREE 路径

- 原实现：进程环境变量 `AAF_COST_FREE_MODELS` 被当作权威 FREE 元数据，`paid-model` 可无授权
  变为 ALLOWED_FREE（跨任务模型级全局 bypass）。
- 新实现：A0 没有任何远程 FREE 权威 —— `classify_cost` 不再接受 FREE 元数据参数；
  `COST_FREE` 分类被移除；`AAF_COST_FREE_MODELS` 若被设置，仅在 cost_guard.json 的 notes 中
  记录「IGNORED：A0 无可信远程 FREE registry，用户可控 env 元数据不是权威 FREE 证据」。
  远程/API 模型一律 PAID_OR_UNKNOWN（需精确一次性授权）；本地路径（LOCAL_FREE）不受影响。
  A1 Registry 不在本 FIX 内实现（不得用另一个同等不可信的 bypass 替换）。

### 12.3 阻断 #3：授权改为准入即消费的真一次性（replay 拒绝，fail-closed）

- 原实现：`AAF_COST_AUTH` 只读比较、永不消费；同 Task/stage/model 的后续 execution 可重复放行。
- 新实现：`evaluate()` 在准入边界消费授权 ——
  - in-process 集合 `_CONSUMED_AUTHS`：同进程内重复/再入 evaluate → 第二次 BLOCKED；
  - 执行目录内消费记录 `cost_auth_consumed.json`（sha256 指纹 + scope + 时间戳）：
    跨进程 resume/re-entry 同一 execution 上下文 → BLOCKED（replay 拒绝）；
  - 消费状态不确定（marker 不可读/损坏）→ fail closed（视为已消费）；
  - 消费持久化失败 → fail closed（BLOCKED，不静默放行）；
  - 未匹配的授权不产生任何消费记录（不误锁后续正确授权）；
  - scope 语义不变：Task ID + stage + model（+provider）整串精确匹配；无关 Task/model/stage 仍 blocked。
  - runner 传入 `state_dir=output_dir`（execution 目录），消费发生在 run_agent 之前
    （Hermes subprocess 创建之前）。
- 恢复语义（fail-closed 的必然结果）：同一 execution 目录内、同 scope 的授权消费后不可再准入；
  恢复 = 新 execution（新目录）重新提交并重新设置授权。blocked 文本已如实说明。

### 12.4 新增/修订测试（Requirement 7 对抗矩阵）

- `tests/test_cost_guard_fix002.py`（新增 20 项）：伪装本地 URL 全矩阵（localhost.evil.example /
  notlocalhost.example / path/query 内嵌 127.0.0.1 与 localhost / 127.0.0.1.evil.example /
  0.0.0.0 / 8.8.8.8 / userinfo 伪装 / ollama+伪装 URL）、畸形/歧义 endpoint fail-closed
  （无 scheme / 无 hostname / 非法 port / 非 http(s) / 非法 IPv6）、exact localhost 与 loopback
  IP 变体（127.0.0.0/8、::1、长写、IPv4-mapped）、FREE env 声明远程付费模型仍 BLOCKED +
  IGNORED note、本地路径不受 FREE env 干扰、一次性授权（首准入 allowed / 同值 replay blocked /
  fresh-process 等价 replay blocked / 消费后任何值不可再准入 / 消费状态不确定 fail closed /
  未匹配不消费 / 畸形授权 blocked / runner 集成 replay blocked / blocked 文本含一次性说明）。
- `tests/test_cost_guard.py` 修订：移除 FREE 元数据分类测试（COST_FREE 已删除），
  `AAF_COST_FREE_MODELS` 声明付费模型 → BLOCKED + IGNORED note；其余 A–G 矩阵保持。
- fresh-runner 新增对抗场景 S7（config probe 返回 `base_url=https://localhost.evil.example/v1`
  → BLOCKED + PAID_OR_UNKNOWN + hermes 未 spawn）、S8（FREE env 声明付费模型 → BLOCKED +
  IGNORED + hermes 未 spawn）、S9（授权已消费后同一 execution 上下文再准入 → BLOCKED +
  authorization_consumed=true + hermes 未 spawn）。

### 12.5 FIX-002 验证证据

- 定向：`python -m pytest tests/test_cost_guard.py tests/test_cost_guard_fix002.py -q` → **52 passed**（原 34 项 A–G 矩阵修订 + 20 项 FIX-002 对抗新增）。
- 全量 non-GUI 回归：分块复跑（单进程连跑触发既有 RW-029 环境 flake，与父任务同款处理）——
  `pytest -q --deselect <3 个线程型文件>` → **1321 passed / 1 skipped / 29 deselected**；
  3 个线程型文件单独 → **20 passed**；合计 **1341 passed + 1 skipped**（1289 v0.4 基线 + 52 定向，零下降）。
- fresh-runner Run N+1（FIX-002 代码 + 全新 python 进程跑真实 runner）：**9/9 场景 passed**
  （S1–S6 原 6 场景保持 + S7 伪装本地 URL / S8 FREE env 声明 / S9 授权 replay 三个对抗场景新增）；
  运行时证据存于 `.aaf/AAF-v0.5-A0-PAID-GUARD-001-FIX-002/fresh-runner-validation/`（不提交）：
  - S7：`base_url=https://localhost.evil.example/v1` → BLOCKED_COST_APPROVAL / PAID_OR_UNKNOWN
    （evidence 明示 hostname 非 exact localhost、substring 不作为证据）/ hermes 未 spawn；
  - S8：`AAF_COST_FREE_MODELS=deepseek-v4-flash@deepseek,...` → BLOCKED / PAID_OR_UNKNOWN
    / notes 记录 IGNORED / hermes 未 spawn；
  - S9：授权已消费后同一 execution 上下文再准入 → BLOCKED / authorization_consumed=true
    / consumption marker 存在 / hermes 未 spawn。
- 提交：`fa1adaa`（feat 修复，2026-08-29，TASK: AAF-v0.5-A0-PAID-GUARD-001-FIX-002）；Remote Sync：**SYNCED**（`git push origin main`：`5037eb4..fa1adaa main -> main`；ahead-behind 0/0）。
- 状态：A0 修复完成；**Codex re-review 通过前 A0 不得标记 CLOSED**；A1 未启动。
