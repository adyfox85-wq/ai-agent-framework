# AAF_MASTER_BACKLOG.md

> Project: AI Agent Framework
> Document Type: **Living Long-Term Backlog / 长期问题与恢复登记**
> Established: 2026-08-27（AAF-MAINT-001-FIX-002）
> Last Updated: 2026-08-31（AAF-v0.5-A2-SHADOW-ROUTING-004 — evidence-backed Hermes registry qualification：deepseek-v4-flash@deepseek 用已接受的 003-FIX-001 真实运行证据（Risk: HIGH 任务实际以该模型执行至 Codex APPROVE，commit 5911d39）填入 capability_tier=T2（HIGH executor floor，只证明至少 T2，不推断 T1/T0）+ qualification=QUALIFIED（accepted evidence snapshot：evidence 引用具体已接受 artifacts、observed_at=2026-08-31T08:16:23 真实接受时间戳；不表示永久健康、无动态 health/quarantine）；cost_class 保持 UNKNOWN；其它候选零改动（本地/free 模型无独立证据不提升）；selector / shadow observation 零代码修改；actual 执行不变；authoritative=false / execution_affected=false 保持；HIGH Hermes shadow 产生真实 hypothetical candidate（blocker 解除）；8 项新增聚焦测试 + 全量 non-GUI 零回归（1611+8）+ fresh-runner N+1 通过；A2 = STARTED（Shadow-only）。此前更新：2026-08-31（AAF-v0.5-A2-SHADOW-ROUTING-003 — explicit task-risk provenance：TASK contract 新增可选顶层 `Risk: LOW|MEDIUM|HIGH|CRITICAL`（唯一词汇 = risk_contract.RISK_CLASSES）；Planner 显式 Risk = structured provenance——缺失 → 向后兼容（shadow risk = RISK_UNAVAILABLE，missing ≠ LOW）、非法 → 双层校验严格拒绝；runner Hermes stage 从 immutable snapshot 解析 Risk 透传 shadow observation（risk_source = task/planner provenance）并允许现有 selector 产生真实 hypothetical decision；prose/name/route/path 零推断；authoritative=false / execution_affected=false 保持；A2 = STARTED（Shadow-only）。此前更新：2026-08-31（AAF-v0.5-A2-SHADOW-ROUTING-001 — A2 Shadow Routing 首片交付：deterministic shadow-selection engine（`ai_agent_framework/shadow_routing.py`，纯函数、零 I/O/LLM）——假设性 / 非权威 / 零执行影响（live 模块零 import，隔离测试锁定）；消费 A1 Registry + Risk 契约原样复用（tier_satisfies / is_usable_candidate / FREE_OF_COST_CLASSES / floor_for / reviewer_allowed）；能力充分性先于成本、FREE ≠ qualification、UNKNOWN 成本保守规则（已知成本 > UNKNOWN）、显式 NO_SHADOW_CANDIDATE、输入顺序无关确定性；reviewer 语义与 schema_version 严格性零回归；47 项定向测试 + 全量 non-GUI 零回归；A2 = STARTED（未 COMPLETE）；CAP-003（实际路由）仍 NOT IMPLEMENTED。此前更新：2026-08-31（AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001 — structured-result 协议纠正 + A1 closure 复核：只读诊断从仓库实现确认 structured-result 架构（producer = `adapters._structured_contract_block` 注入 Hermes prompt；Hermes raw schema = status/commit/changed_files/warnings，**无 commit_changed**；归一化权威 = `<agent>_result.json`，commit/commit_changed/changed_files 全部 Framework git 观察派生）；正式政策新增 AAF_TASK_EXECUTION_POLICY §5.2（raw vs normalized authority hierarchy + corrected acceptance rules：不得要求抑制 Framework 必输出块、raw 缺非契约字段 ≠ provenance failure、冲突时 Framework 归一化事实权威）；历史 FIX-003/FIX-004 artifacts 与 verdict 不可变不重写（TASK 层协议假设有误，reviewer 判断无错）；closure-loop 教训登记 RW-032；A1 在纠正后的验收语义下复核无新 blocker → **A1 = CLOSED / COMPLETE 保持**，Next mainline = A2 Shadow Routing 不变；文档-only 提交，未 push（review 后同步））。此前更新：2026-08-30（AAF-v0.5-A1-CLOSURE-AUDIT-001-FIX-001 — A1/A2 边界裁决 + A1 正式关闭：四项曾列 "A1 remaining slices"（Selection Engine / Shadow Routing / Hermes candidate tier 赋值 / 运行时 qualification 观测）经逐项裁决全部归类 A2+——Shadow Routing = A2（显式）、运行时 qualification 观测 = A2+（显式，见本文件 RW-030）、Selection Engine / Hermes candidate tier 赋值 = A2+（推断）；A1 正式 scope（Registry + Risk 契约，见 RW-030 Current Implementation）无剩余 blocker → **A1 = CLOSED / COMPLETE**，Next mainline = v0.5 -> A2 Shadow Routing（未启动）；PROJECT_STATE / A1 REPORT / CAP-004 已同步裁决；零代码修改、无 push（review 后同步））。此前更新：2026-08-30（AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001 — Windows helper 子进程 console 闪现修复收口：确认的 git/helper/model-observation flash 来源（`context_packet.py` 6 处 git 调用、`git_status._git()`、`model_observation._run_readonly()`）统一复用既有 `no_console_kwargs()`（CREATE_NO_WINDOW），子进程语义零变化（13+/0-）；`status_window.py` explorer 经检查不改（GUI-subsystem 无 console 路径）；10 项聚焦测试 + 定向 443 passed + 全量 non-GUI 零回归 + fresh-runner Run N+1 通过；登记 backlog **RW-031** = CLOSED（原始证据级别：confirmed Windows subprocess console-visibility omission，cosmetic/UX only，非功能正确性失败）；未 push（review 后同步）；返回点 = v0.5 -> A1 Registry + Risk）。此前更新：2026-08-30（AAF-v0.5-A1-REGISTRY-RISK-001 — A1 Registry + Risk foundation 交付：新增 `ai_agent_framework/model_registry.py`（model registry 契约：身份 / 适用 agent / capability tier / cost 分类（复用 model_observation.COST_CLASSES）/ locality / runtime qualification 独立维度；`is_usable_candidate` 仅由 tier + qualification 判定，FREE 绝不隐含 qualified）+ `ai_agent_framework/risk_contract.py`（LOW/MEDIUM/HIGH/CRITICAL + 初始 tier-floor 映射 + 自托管权威区域至少 HIGH + 分类纯逻辑零 LLM）；Hermes FREE-model 可用性/稳定性用户观察登记为本文件 **RW-030**（user-observed runtime constraint，非普遍断言、非永久健康结论）；A1 = STARTED（foundation slice delivered，remaining planned slices 未完成，A1 未 full closed）；基线 registry 只填证据事实，未验证一律 UNKNOWN；无自动路由激活、无 A2-A6 实现、cost_guard/runner/router 零修改；测试 58 项新增 + 全量 non-GUI 1453 passed / 1 skipped 零回归）。此前更新：2026-08-30（AAF-v0.5-A0-PAID-GUARD-001-CLOSE-001 — A0 Paid Guard 正式关闭：FIX-006 = APPROVED / COMPLETE（Codex APPROVE，blocking_rework=false，blocking_provenance=structured，commit b1e8bf2）；A0 = CLOSED / COMPLETE；工作树对账——tracked working tree CLEAN（0 tracked 修改），「dirty」观察 = 3 个 PRE_ALLOWED_UNTRACKED untracked 常驻项（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs），未删除未 clean；Next mainline = A1 Registry + Risk，A1 未启动；Hermes free-model 可用性/稳定性为后续路由的 runtime qualification concern，不假定 FREE=healthy；closure 变更仅文档（A0 REPORT §13 / PROJECT_STATE / 本文件 CAP-004），cost_guard 零修改、未 push（ahead 6/0，review 通过后同步）。此前更新：2026-08-30（AAF-v0.5-A0-PAID-GUARD-001-FIX-006 — Codex BLOCKING（FIX-005 review）最终收口：持久化 state_dir fail-open class——`_claim_auth` 只拒绝 None、`state_dir=""` 经 `Path("")` 解析为相对 CWD 的 marker（不同 CWD 独立进程各自可 winner）→ 新增 `_state_dir_validation_error()`：paid admission 的持久化 state_dir 必须为**显式提供的、非空的、绝对路径**，None / 空串 / 纯空白 / `Path("")` CWD fallback / `"."` / 相对路径 / 畸形（NUL）/ 类型非法一律 fail closed 且**零 marker 创建（含 CWD）**；校验先于一切消费检查与文件系统写入；mkdir/open 兜底 `(OSError, ValueError)`；FIX-003 原子性 / FIX-002 端点安全 / runner 恒传绝对 output_dir / LOCAL_FREE 全部保持；新增 24 项聚焦测试（空/空白/Path("")/./相对/bytes/int/NUL blocked + CWD 零 marker、6 进程不同 CWD invalid state 零 winner + 各 CWD 零写入、共享绝对 state_dir 恰一 winner、顺序 replay、绝对路径是文件/中间组件是文件/marker 被目录占用 fail closed、runner 级相对 output_dir → WAITING + Hermes 零 spawn + 无 marker、LOCAL_FREE 不受影响、FIX-002 endpoint 抽样）+ fresh-runner Run N+1 7/7（S1–S7，含真实 runner 相对 output 边界零 spawn）；既有驱动复跑 FIX-005 6/6、FIX-003 5/5、FIX-002 9/9 保持绿色；定向 106 passed、分块全量 non-GUI 1395 passed / 1 skipped 零回归（RW-029 flake 惯例隔离）。此前更新：2026-08-30（AAF-v0.5-A0-PAID-GUARD-001-FIX-005 — Codex BLOCKING（FIX-003 review）最终收口：paid admission 无持久化 filesystem authority → fail closed——`_claim_auth(state_dir=None)` 直接失败（`_STATE_DIR_REQUIRED_ERR`：filesystem exclusive-create 是唯一跨进程准入权威，`_CONSUMED_AUTHS` 永远只是非权威拒绝快路径、绝不放行）；paid admission 序列 = 精确匹配 → 有效持久化 state_dir → 原子 exclusive-create claim → ALLOWED_AUTHORIZED_PAID，任何前置失败 → BLOCKED；FIX-003 原子性 / FIX-002 端点安全全部保持；移除 3 项「state_dir=None 可产生一个 paid winner」旧断言，新增 17 项 A–H 聚焦测试（单次 / 8 线程 / 6 独立进程 state_dir=None → 零 winner、共享 state_dir 恰一 winner、顺序 replay、state_dir 是文件 / marker 被目录占用 / runner 级 persistence 不确定 fail closed + Hermes 零 spawn、LOCAL_FREE 保持、paid 无授权 blocked、FIX-002 endpoint 对抗抽样）+ fresh-runner Run N+1 6/6，FIX-003 驱动 5/5、FIX-002 驱动 9/9 复跑保持绿色；定向 82 passed、分块全量 non-GUI 复跑零回归。此前更新：2026-08-30（AAF-v0.5-A0-PAID-GUARD-001-FIX-003 — Codex BLOCKING #3 最终收口：授权消费原子化——check-then-consume 移除，`cost_guard._claim_auth()` 单一原子操作（filesystem exclusive-create `open(...,"x")` 为跨进程权威，marker 已占用 / 无法持久化 → fail closed；`_CONSUMED_AUTHS` 降级为非权威只拒绝快路径 + `_CONSUMED_LOCK`；消费记录不再落盘授权原文，sha256 指纹即可等值判定）；13 项并发/对抗测试（线程 barrier 8 线程恰 1 winner、6 独立进程恰 1 claim 成功 + fresh replay blocked、顺序 replay、不同 scope 不消费、marker 被目录占用 / state_dir 是文件 fail closed、旧格式 marker 兼容拒绝、runner 级 replay 零 Hermes 调用）+ fresh-runner Run N+1 5/5（进程 contention 1 winner / 5 blocked、replay 达真实 runner 边界零 spawn、LOCAL_FREE 放行、paid 无授权 blocked、顺序 replay）；定向 65 passed、分块全量 1354 passed / 0 failed（单进程连跑 RW-029 0x80000003 既有 flake 隔离复跑通过）。此前更新：2026-08-29（AAF-v0.5-A0-PAID-GUARD-001-FIX-002 — Codex REQUEST_CHANGE 三个 blocking fail-open 修复：本地端点判定改 hostname/IP 严格语义（substring 匹配移除，localhost.evil.example / path-embedded 127.0.0.1 / 0.0.0.0 等一律 fail closed）；`AAF_COST_FREE_MODELS` 不再作为权威 FREE 来源（A0 无远程 FREE registry，设置即忽略并记录诊断 note）；`AAF_COST_AUTH` 改为准入即消费的真一次性（in-process 集合 + 执行目录 `cost_auth_consumed.json`，replay 拒绝、消费状态不确定 fail closed）；新增对抗回归测试（test_cost_guard_fix002.py）+ fresh-runner S7/S8/S9 对抗场景。此前更新：2026-08-29（AAF-v0.5-A0-PAID-GUARD-001 — v0.5 A0 Hermes Paid Guard 交付：fail-closed task-scoped 成本授权——Hermes stage subprocess 创建前 guard（`ai_agent_framework/cost_guard.py`）：effective model 解析（`AAF_HERMES_MODEL`/`AAF_HERMES_PROVIDER` env 优先 + `hermes config get model` 只读 fallback；零网络/零 LLM）、A0 最小成本分类（LOCAL_FREE / 仅显式元数据的 FREE / 其余 PAID_OR_UNKNOWN / 无法解析 COST_UNKNOWN fail closed）、一次性 task-scoped 授权（`AAF_COST_AUTH="<Task ID>|<stage>|<model>[|<provider>]"` 整串精确匹配，env per-run 不泄漏）、机器可读决策（ALLOWED_FREE / ALLOWED_AUTHORIZED_PAID / BLOCKED_COST_APPROVAL，`cost_guard.json` 含 decision_ms）；blocked → Hermes 进程零创建 + 任务 WAITING（COST_APPROVAL_REQUIRED）+ 人读 blocked 信息完整（Task ID/stage/model/provider/cost/原因/所需 scope）；Hermes 全局 config 零修改；`AAF_HERMES_MODEL`/`AAF_HERMES_PROVIDER` 透传 `-m`/`--provider`（无覆盖时 args 与 v0.4 一致）；34 项定向测试 + 全量 non-GUI 1323 passed（1289 基线 + 34 新增，零下降；RW-029 0x80000003 环境 flake 隔离复跑通过）+ fresh-runner Run N+1 6/6 场景（blocked 零 spawn / local-free 达 invocation 边界 / 精确授权放行 / 其他 Task 与 model 授权阻断 / unresolved fail closed）；CAP-004 = IMPLEMENTED (A0)；完整 Model Routing（CAP-003）仍 NOT IMPLEMENTED（A1+ 范围））
> 2026-08-29（AAF-v0.4-TASK-011-FIX-002 — WorkBuddy Windows Tree Cleanup Safety Fix：关闭 Codex 确认的最后一个 blocking defect——Windows 上 cleanup 成功必须基于足够强的 process-tree evidence（taskkill /T /F 实际尝试且成功 + 顶层确认退出 + reap 完成/明确分类），只 kill 顶层成功（或只观察顶层 poll() != None）**不是** safe cleanup；tree 未确认 → cleanup failure fail closed、绝不 retry、child PID 保持注册（Registry Gate）；`AAF_WORKBUDDY_CLEANUP_RESERVE` 钳制到 `MIN_SAFE_CLEANUP_RESERVE=60s` 安全下限（reserve=0/过低值不得关闭 tree safety）+ orchestrator admission 二次兜底（effective reserve）；attempt admission control：剩余 budget ≤ safe cleanup reserve + minimum useful attempt runtime 时不启动 attempt（cleanup budget 在 attempt 启动前保留，不是 deadline 耗尽后才发现没时间安全 kill tree）；deadline 耗尽 → taskkill skipped → 顶层 kill 成功 ≠ tree confirmed → fail closed；taskkill 成功 + 顶层确认退出 = tree confirmed（retry 允许）；telemetry 新增 cleanup_tree_confirmed / taskkill_attempted / taskkill_success / cleanup_reserve_effective；非 Windows 语义保持（kill 确认即安全，平台差异显式）；59 项 workbuddy 定向测试 + 全量 non-GUI 1289 passed / 1 skipped / 9 deselected；此前更新：AAF-v0.4-TASK-011-FIX-001 — WorkBuddy Confirmed Cleanup and Hard Stage Budget Fix：关闭 Codex 确认的两个 blocking reliability gap——① **confirmed-dead-before-retry**：timeout 清理不再无条件在 finally 注销 child；`_terminate_and_reap` 返回结构化 `CleanupResult`（terminated_confirmed / reaped_confirmed / method / failure_reason），final liveness check 必须观察到 poll() 非 None（成功 ≠ “kill() 被调用”）；Windows taskkill /PID /T /F 整树杀保留；终止未确认 → `WorkBuddyCleanupError`（outcome=CLEANUP_FAILURE）fail closed、绝不 retry、child PID 保持注册（Registry Gate 跨清理失败仍有效，任何后续 run 在 spawn 前被拦截——绝不 alive child + 无 registry + retry）；终止确认但 reap 失败 → 按真实资源安全语义如实分类（进程已死无并发风险 → retryable + cleanup_confirmed=False evidence）；② **single absolute stage deadline**：`stage_deadline = stage_start + overall_stage_budget` 为唯一绝对墙钟上限，attempt / backoff / taskkill wait / kill grace / communicate reap 全部从同一 deadline 派生并被裁剪（无独立全尺寸等待、无 deadline 后固定 30s+5s+5s）；新增 cleanup_reserve（默认 60s，env `AAF_WORKBUDDY_CLEANUP_RESERVE`）——attempt timeout ≤ remaining − reserve，保证 timeout 后仍有界清理窗口（不因清理超出 budget）；budget 下限 ≥ per_attempt_timeout + reserve；剩余安全 budget 不足 → 不启动下一次 attempt（retry_suppressed_reason 显式诊断）；telemetry 扩展 cleanup_confirmed / cleanup_failure / cleanup_method / cleanup_reason / stage_deadline_monotonic / cleanup_reserve / retry_suppressed_reason（REPORT 保持紧凑）；新增 12 项定向测试（22A taskkill+kill 失败进程存活→无 retry+fail closed+不注销 / 22B taskkill 失败但 kill 确认→retry 允许 / 22C 确认终止后 reap 失败→如实分类 / 22D+22E registry 保留 unsafe child + 下一 run Registry Gate 拦截 / 23A attempt+cleanup+backoff 消费同一 deadline / 23B cleanup 等待裁剪到剩余 deadline / 23C 安全 budget 不足不启动第二次 / 23D elapsed 尊重 budget / 23E reserve 限制首次 attempt / policy reserve 默认与 env / 24 telemetry cleanup+deadline 字段 + FAIL verdict 不 retry）；既有 retry 矩阵（empty→success / timeout confirmed-clean→success / 全 empty 有界失败 / 全 timeout 有界失败 / FAIL 不 retry / permanent 快速失败 / telemetry / 同 invocation）+ CLOSURE-002/003 回归保持；顺带修复 backoff elapsed 测试的 Windows 定时器相位 flake（sleep 可提前 ~13ms 返回，断言改显式容差）；全量 non-GUI 1277 passed（1265 基线 + 12 新增，零下降）。此前更新：2026-08-29（AAF-v0.4-TASK-011 — WorkBuddy Stage Reliability / Bounded Transient Retry：RW-027 SOLVED——WorkBuddy stage 增加有界同 invocation transient retry（只基于真实 CLI evidence 分类：TimeoutExpired / exit=0+空输出 / gateway placeholder-only stderr 为 RETRYABLE_TRANSIENT；missing executable / 非零退出无 transient evidence 为 NON_RETRYABLE 快速失败不重试），per-attempt timeout 默认 900s（实测成功 stage ~556s）替代统一 3600s，overall stage budget 硬上限（默认公式 attempts×timeout+backoff），bounded backoff 默认 30s，timeout → Windows taskkill /T /F 树杀 + 有界等待 + 管道排空（无 orphan/zombie/pipe leak/并发 child），有效输出（含业务 FAIL verdict）立即停止 retry 且 verdict 归 Framework authority，retries 用尽 → fail closed（FRAMEWORK_ERROR 带完整 attempt 历史 → Codex 不运行 → WAITING），attempt telemetry 机器 artifact（workbuddy_attempts.json）+ stage result execution_retries 摘要 + REPORT 紧凑 attempts=N；Hermes/Codex 不自动获得 retry，AAF_WORKBUDDY_RETRY=0 可整体关闭；新增 42 项测试（矩阵 A–K + CLOSURE-002/003 双 incident regression + 真实 python child 超时清理 + runner/Codex gating 集成）；全量 non-GUI 1265 passed；RW-028 登记为 OBSERVATION（pythonw early validation 失败 UI 仅 exit=2，TaskValidationError 不可见——仅登记不实现）。此前更新：2026-08-29（AAF-v0.4-TASK-010-FIX-001 — Model Observation Evidence Accuracy and Test Isolation Fix：修正 CodeBuddy installed-version evidence（2.137.1 为无证据手写值；改为 `codebuddy --version` 动态探测 → 2026-08-29 实测 2.141.0，与 WorkBuddy 独立 probe 一致；`--version` 探测失败（如 native module LoadLibrary）→ version=UNKNOWN + discovery_status=FAILED 带失败原因，非阻塞；model_observation.py 零硬编码版本号，observations 新增 version / version_source / version_evidence 字段，REPORT 紧凑行新增 version=）；删除 Codex 无证据的 `model_options.*` 推断（CLI 只证明通用 `-c <dotted.path>=value` → reasoning_effort capability = NOT_EXPOSED_BY_CURRENT_CLI，不得根据通用 -c 猜配置路径）；测试隔离（RW-026）：FIX-UI-A-001 真实桌面 modal 根因定位 = tests/test_phase_f_fix_001_ui.py 驱动真实 Tk 窗口 + 无结构性排除；pytest.ini 新增 gui_e2e marker + `addopts = -m "not gui_e2e"` 结构性排除；该文件标记 gui_e2e（manual 运行 `pytest -m gui_e2e tests/test_phase_f_fix_001_ui.py`）；新增 tests/test_bridge_ui_headless.py 7 项 headless 等价覆盖（headless 对话框 stub + 进程内剪贴板 + tmp config/registry；驱动真实 Bridge 主链路；零真实窗口/零真实剪贴板/无人值守）；热键冲突路径确认已隔离（RW-012：StubRoot + fake HotkeyListener + patched ui.show_error）；model observation 定向测试 30→37（7 新增）；此前更新：2026-08-29（AAF-v0.4-TASK-010 — Model Observability and Discovery Foundation：新增只读基础能力组（见本 backlog §5：CAP-001 Model Observability = IMPLEMENTED（FIX-001 evidence correction 后待 Codex APPROVE 正式确认）/ CAP-002 Model Discovery = IMPLEMENTED（以真实 Agent 接口为限；同上待确认）/ CAP-003 Future Model Routing = NOT IMPLEMENTED——仅登记未来 policy，未实现 Cost Gate / Routing / 自动切换）。`ai_agent_framework/model_observation.py` 建立最小 model observation schema（agent/provider/model/model_source/reasoning_effort/cost_class/cost_metadata/cost_multiplier/discovered_at/discovery_status + capabilities/notes）；`model_observation.json`（output_dir）为 model observation 单一 machine authority（schema_version=1，refreshable；动态元数据原则：模型/免费状态/积分倍率可变化，一次发现不当永久事实）；runner 每 stage 记录 stage_timing（started/finished/elapsed，monotonic）并做只读 discovery（无付费推理 / 无配置修改），`<agent>_result.json` 只携带 authority 引用（无重复 truth source）；REPORT 只输出每 agent 一行的紧凑 Model Observation 摘要（Context Compaction，详细数据 lazy 在 artifact）；`AAF_MODEL_OBSERVATION=0` 整层关闭（行为与引入前一致）；discovery 全链路非阻塞（safe_discover_agent + observe_stage + runner 级 try/except 双保险：任何失败 → UNKNOWN/FAILED 记录，绝不影响 Agent 执行 / 不升级 TASK FAILED）；真实环境只读 probe 证据（TASK-010 报告 Requirement 21）：Hermes v0.20.5（`hermes config get model` → default=deepseek-v4-flash / provider=deepseek / reasoning_effort=medium；`hermes config get auxiliary` → auxiliary.vision=qwen2.5vl:3b、compression/web_extract/title_generation/summarization=qwen3:4b，全部 provider=custom + 本地 Ollama base_url http://127.0.0.1:11434/v1 → 本地模型可发现；auxiliary.vision 分类为 model slot；ComfyUI 不在 Hermes text-model registry → 外部 image-generation capability/tool，不硬塞 LLM model list；`hermes model` 交互式 picker，无非交互 list 子命令）、CodeBuddy 2.141.0（2026-08-29 `codebuddy --version` 动态 probe，FIX-001 修正 TASK-010 手写 2.137.1 无证据值；`codebuddy config get model` 为空 → 当前模型不由用户 config 暴露 → UNKNOWN；`--model` 显式选择 + `--effort` reasoning + `--help` 文本文档化模型 ID（版本级静态元数据）；积分/免费状态 CLI 不暴露 → UNKNOWN / EXTERNAL_DYNAMIC_METADATA_REQUIRED）、codex-cli 0.150.0-alpha.12.2（~/.codex/config.toml 无 model key → 当前/default 模型 server-side 决定、本地不可枚举（documented discoverability limitation）；`codex exec -m/--model` 显式选择存在；无专用 reasoning-effort flag（通用 `-c <dotted.path>=value` 覆盖机制存在但不构成具体 reasoning key 证据 → reasoning_effort capability = NOT_EXPOSED_BY_CURRENT_CLI；FIX-001 删除无证据的 model_options.* 断言）；无命令枚举 server-side model catalog）；cost_class 如实分类：API provider（base_url 空）→ UNKNOWN（不硬编码 PAID / 无促销状态），local base_url（127.0.0.1）→ LOCAL_FREE（带 provider config evidence）；新增 30 项定向测试 `tests/test_model_observation.py`（A schema 序列化 / B UNKNOWN 非阻塞 / C discovery 失败非阻塞 / D cost UNKNOWN 不发明 / E secrets 不持久化 / F stage elapsed / G REPORT 紧凑段 / H artifact 详细 metadata + 动态刷新覆盖 / I telemetry 关闭与失败下执行不变 / 20 三 agent 真实 CLI 输出形态 mock）+ `tests/conftest.py` hermetic discovery（测试默认零真实 CLI 调用）；此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-005 — RW-012 shutdown/recovery 单一 lifecycle authority（TOCTOU 收口）：shutdown intent 发布（`shutdown()` / `_exit_aaf()` / `_restart_bridge()`）与 listener lifecycle transition 共用同一个 `_lifecycle_lock`——`_shutting_down=True` 在锁内先于 stop 发布（Popen 失败在同一 authority 下回滚）；`_run_lifecycle_transition()` 取得 authority 后在锁内重新验证 shutdown，关闭 Codex FIX-004 唯一 blocking finding「pre-lock check False → 等待锁 → shutdown 发布 → 取得锁后仍 rearm/创建 replacement」的精确 check-then-wait 竞态（等待锁期间 shutdown 已发布的 recovery 观察到 True → 不 cleanup / 不 rearm / 不 begin_attempt / 不创建）；`_apply_hotkey_locked`（唯一 listener creation authority）锁内以 shutdown 守卫拒绝 config reload / 外部触发在 shutdown 后的任何创建（不 restart / 不复活）；`_clear_pending_ownership_locked` 的 rearm 只在非 shutdown 时发生（shutdown 期间 delayed-exit cleanup 只做 ownership bookkeeping、绝不 rearm / 不开启新 epoch）；无递归锁死（shutdown 阻塞等待 authority，transition 完成后接管）；新增 13 项定向回归（精确 Codex TOCTOU 真实线程 + 确定性门闩 / reverse interleaving / delayed-exit during shutdown / config reload during shutdown / poll during shutdown / shutdown 发布顺序可观察 / _exit_aaf 确认-取消 / _restart_bridge 成功-失败回滚 / 唯一 authority 锁内守卫 / 并发无死锁 / 非 shutdown 正常路径无回归），TOCTOU 与 reverse 测试对未修复代码确定性 FAIL（scratch 反证）；RW-012 定向 111 项 + 全量 non-GUI（排除真实 UI 文件 test_phase_f_fix_001_ui.py，任务禁止真实剪贴板/项目切换确认窗）通过；RW-008 无回归（parser 零改动）。此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-004 — RW-012 atomic recovery transition consolidation：delayed-exit recovery 收敛为单一锁内 lifecycle transition——`Bridge._run_lifecycle_transition()` 在同一个 `_lifecycle_lock` 临界区内完成 old pending 确认退出 → 锁内 identity 重验证 → clear old ownership → rearm 恰好一次 → eligibility 判定 → reserve attempt → exactly one replacement（`_apply_hotkey_locked`），关闭 FIX-003 遗留的「cleanup 释放锁 → 锁外 eligibility → 再获取锁创建」多段 ownership transition 与 exposed gap（listener=None/pending=None/rearmed 但未 reserved/owned 只在锁内瞬时存在，任何其他 trigger 锁外不可见、非阻塞获取失败即合并）；`_apply_hotkey` 拆为 public（获取锁）+ `_apply_hotkey_locked`（假定持锁，唯一 listener replace/start authority，config reload / health recovery / delayed cleanup / restart-failure 全部汇入），无递归锁死（持锁内再触发 = coalesce）；rearm 仍只随真实 delayed-exit ownership release 发生（epoch 不因 None/DEGRADED/poll 自增）；新增 13 项定向测试（单一锁内 transition 无 gap / 精确 Codex interleaving 真实线程：第二 trigger 无独立 authority + stale cleanup 不清 replacement / exhaustion→delayed exit 恰一次 rearm 单 epoch / failed new epoch bounded / healthy 终态不无谓 restart / config reload 同 hotkey 不 restart / listener=None 不 rearm / 冲突可观察有界无 modal / shutdown 不复活 / readiness 回归 / stop-before-replace + fail safe），scratch 反证：旧设计同一交错产生 duplicate replacement（2 次创建），新设计 exactly one；RW-012 定向 98 项 + 全量 non-GUI 1182 passed；RW-008 无回归（parser 零改动）。此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-003 — RW-012 atomic delayed-exit recovery：`_poll_health` delayed-exit check-and-clear 收进 `_lifecycle_lock` 保护的原子单元（`_delayed_exit_cleanup`，锁内 identity 重验证才清理，关闭 FIX-002 遗留 TOCTOU：lock 外 check → 锁内建新 → lock 外 clear 清掉 replacement 的合法交错）；recovery budget exhausted 后旧 listener 迟延退出 → `HotkeyRecovery.rearm()` 开启一次新的有界 recovery epoch（epoch+1，真实 lifecycle 状态变化才 rearm，失败仍受 max_failures/backoff 约束，无 per-poll 无限重置、无 tight loop）；identity-safe clear（pending/listener 双身份校验，stale cleanup 绝不清 replacement）；所有 ownership transition 统一锁内；shutdown 不 rearm 不复活；新增 15 项定向测试（含 Codex 精确 race 真实双线程复现 + scratch 反证旧实现确定性 FAIL），RW-012 定向 84 项 + 全量 non-GUI 1169 passed，RW-008 无回归。此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-002 — RW-012 listener ownership retention + readiness truth：关闭 FIX-001 遗留的最后两个同根 lifecycle blocker（Codex REQUEST_CHANGE）——① **ownership retention**：`_stop_listener` 只在 stop 确认退出（stop()==true / 线程已确认 not alive）后才清空 `self.listener`；stop 超时（旧线程仍可能存活）保留 reference 并记入 `_pending_stop`（DEGRADED / recovery pending 可观察），跨 recovery cycle 不启动 replacement、不伪装 healthy、无 orphan 窗口（one-listener ownership invariant 跨 cycle 成立）；`_poll_health` 增加 pending 旧 listener 迟延退出独立检测（退出确认后必清理引用，随后按正常恢复策略启动 exactly one replacement，不永久卡死）；`_try_recover_hotkey` 异常路径不再盲目清空仍存活的引用；② **wait_ready authority**：`wait_ready` 返回值参与 start success 判定——初始化超时（线程可能仍 alive 但未 ready）不 reset recovery/backoff、不报告 healthy，进入 DEGRADED 恢复流程；wait_ready=true+error 仍按注册失败处理；健康判定新增 `is_ready()` 维度（alive != ready != healthy）；新增 14 项定向测试（stop timeout 跨 cycle 1/2/3、delayed exit 单 replacement、readiness A–D、ownership A–H、bounded recovery）；RW-012 定向 52 项 + 全量 non-GUI 1145 passed（1131 基线 + 14 新增，零下降）+ 真实 E2E 9 项全过；RW-008 无回归；Remote Sync 0/0）
> 2026-08-29（AAF-v0.4-TASK-009-FIX-001 — RW-012 listener-owned lifecycle 修复：registration/unregistration 归 listener 线程（thread-owned unregister）、显式 stop 契约（request_stop + 有界 join，WM_QUIT 唤醒真实消息循环）、stop-before-replace（旧 listener 确认退出后才创建新 listener）、旧 listener 超时 fail safe（不创建 duplicate replacement）、并发 lifecycle transition 单一 owner（_lifecycle_lock）、intentional shutdown（Exit/Ctrl+C）走 stop 契约不恢复不复活；Bridge 主线程不再直接 UnregisterHotKey；新增真实线程级所有权测试（register/unregister 线程身份断言，非仅 mock 调用），RW-012 定向 38 项 + 全量 non-GUI 1131 passed（1114 基线 + 17 新增）；RW-008 无回归；Remote Sync 0/0）
> 2026-08-29（AAF-v0.4-TASK-009 — Bridge Reliability Final Closure：RW-012 hotkey listener 自恢复 SOLVED——Bridge 唯一 owner + HotkeyRecovery 有界 backoff（15/30/60s，连续 3 次失败停止自动恢复），listener 意外失活自动重建（不重启 Bridge），主动退出（Exit/Restart）期间不恢复、退出不复活，失败经 Tray 图标/Tooltip/状态窗口/log 可见，21 项定向测试；RW-008 最终 closure = SOLVED（正式 Compact TASK contract 全支持：LF/CRLF/BOM/独立行 marker/多行 Acceptance/后续 section/EOF/duplicate fail-closed/missing-empty reject/Route fail-closed，exact TASK-009 production fixture 通过；U+3000 / 富文本 / 「Acceptance Criteria」旧别名 = LEGACY / NON-CONTRACT / OBSERVATION，不扩张 parser）；RW-021 necessity check = 不同 lifecycle owner / 不同根因 / 非最小改动 → DEFERRED/OPEN P2，v0.4 freeze 显式 non-blocking；RW-024 观察确认（无二次 modal 回归，未跑 ToDesk-sensitive E2E）；全量 non-GUI 测试通过；Remote Sync 0/0）
> 2026-08-28（AAF-v0.4-TASK-008-FIX-001 — RW-024 收尾对齐：复制成功反馈临时化——「已复制 ✓」1.5s 后自动恢复「复制报告」，重复复制刷新 after 计时器，窗口提前关闭时回调安全（不抛异常、不重建窗口）；backlog Current Implementation / Remaining Gap / Decision 对齐完成态、Remaining Gap=NONE，不再保留「只登记，不实现」登记态；新增计时恢复/重复刷新/关闭安全/backlog 一致性测试；此前更新：AAF-v0.4-TASK-008 — RW-024 Completion Dialog Copy UX：完成窗口单窗改造——点击「复制报告」不再弹第二「报告已复制」modal、不再关闭主窗，窗内就地反馈（按钮变「已复制 ✓」/「复制失败」），仅「关闭」退出；`_copy_last_report` 返回 bool、handoff 构建与剪贴板写逻辑不变；新增 9 项 mocked/unit-level Tk 测试（成功/重复/关闭/失败全路径 + Bridge 复制逻辑回归）；RW-024 OPEN → SOLVED；此前更新：AAF-v0.4-TASK-006-FIX-001 — Phase F Atomic Config Persistence + Real UX Closure：Codex 两个 blocker 关闭轮——① config.save_config 统一 atomic contract（同目录 tmp + flush/fsync + os.replace；失败清理 tmp 抛 ConfigError，旧 config 字节级保留；update_project 复用，无 write_text 旁路）；② 真实 Bridge/UI 交互 harness（真实 Tk 确认窗/状态卡片 + 真实按钮 invoke + 真实剪贴板）覆盖 Known 切换确认并执行 / 拒绝零写入 / Unknown 确认前不执行 / Invalid fail closed / Duplicate running 卡片无第二 runner / Duplicate terminal 卡片不覆盖 / RUNNING 跨 workspace 拒绝 / restart 恢复；真实 UI 验收修复 duplicate 卡片 [打开 REPORT] 死按钮（闭包捕获 report_path）；780 passed（760 基线 + 20 新增：11 原子 + 9 真实 UI，全量两次连跑零失败）；UX evidence 存 `.aaf/AAF-v0.4-TASK-006-FIX-001/UX_EVIDENCE.md`；RW-003 / RW-016 SOLVED 状态按实际证据保持（FIX-001 不改写 backlog 判定）；Phase F 正式 COMPLETE 留待 WorkBuddy 独立验证 + Codex 复审后由 Planner 确认；此前更新：AAF-v0.4-TASK-006 — Phase F Project Switching and Duplicate Task UX：RW-003 由 OPEN → SOLVED（Bridge 从 canonical TASK Workspace 识别 + 已知/陌生 workspace 显式确认切换 + recent_projects 持久化 + running/duplicate 保护，设计 §9 全量落地）；RW-016 由 OPEN → SOLVED（duplicate 状态卡片：running/completed/abnormal/unknown 分类 + 中文展示 + 不覆盖 artifacts，设计 §10 全量落地）；RW-006 由 OPEN → SOLVED（状态校正：Phase C/D/E 已交付状态窗口 + 进度估算 + stuck 提示 + 停止入口 + Phase F 项目切换，Remaining Gap 全部闭合，仅按真实交付证据校正状态，不重新开发）；RW-009 / RW-014 仅状态核对保持 PARTIAL（无新交付，未扩大 scope）；760 passed（688 基线 + 72 新增：Phase F 63 单元 + 9 真实 Windows E2E）；Phase F 实现 + 测试 + E2E 完成，正式 COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 审查；此前更新：AAF-v0.4-TASK-005-C-FIX-001 — Cancel Timestamp Timezone Compatibility Fix：canonical UTC/aware elapsed contract 统一 cancel elapsed 计算，关闭 Codex 唯一 timezone blocker；688 passed；Phase E = COMPLETE / Phase F = NOT STARTED；此前更新：AAF-v0.4-TASK-005-C — RW-014 由 OPEN → PARTIAL（Phase E 交付主体：状态窗口停止/强制停止 UX；剩余 Tray 菜单停止项按 §12.2 登记为后续阶段范围边界）；Phase E = COMPLETE / Phase F = NOT STARTED；此前更新：AAF-v0.4-TASK-005-B-FIX-001 — §5.4 更新：Obsidian Conversation Handoff Pilot 验证完成，PILOT / EXPERIMENTAL → **VERIFIED**）
> Location: `docs/internal/AAF_MASTER_BACKLOG.md`

## Purpose

集中登记 AI Agent Framework 全部已确认的真实使用问题、观察项、防漂移
验证缺口、会话承接缺口、历史待恢复优化项与恢复/耐久性规则。

目标：即使任何 ChatGPT Project / conversation 丢失，只要保留
GitHub / 本地 repo / Obsidian 镜像，就不会遗忘后续仍需处理的事项。

## Long-Term Maintenance Rules（长期维护规则）

```
Authoritative Source:
  AI Agent Framework repository（本仓库，含 docs/internal/ 与 git history）

Obsidian:
  用于阅读、搜索和恢复的镜像（MIRROR ONLY，非独立权威源）

ChatGPT Project / Conversation:
  用于规划和协作，但不能作为唯一长期知识来源
```

## Status Vocabulary

仅使用以下状态：

```
OPEN
PARTIAL
OBSERVATION
SOLVED
RECOVERY_PENDING
DEFERRED
```

## Priority Vocabulary

仅使用以下优先级：

```
P0
P1
P2
P3
```

---

# 1. Real-World Usage / Usability Issues（RW）

## RW-001 — Bridge 提示音与弹窗视觉体验

| 字段 | 内容 |
|---|---|
| ID | RW-001 |
| Title | Bridge 提示音与弹窗视觉体验 |
| Category | Real-world usage / UX |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 真实使用观察 |
| Current Implementation | 现状：有提示音与确认/完成弹窗，但体验一般 |
| Remaining Gap | - 当前提示音体验一般<br>- 当前确认/完成弹窗较基础 |
| Decision | 后续与 Desktop/Tray UI 一起考虑；当前不单独开发 |
| Target | 与 Tray / Desktop UI 合并优化提示音与弹窗体验 |
| Do Not Forget | 属于体验优化，不是功能缺陷；不因美观单独重构 Bridge |

---

## RW-002 — 新用户 onboarding / 产品定位

| 字段 | 内容 |
|---|---|
| ID | RW-002 |
| Title | 新用户 onboarding / 产品定位 |
| Category | Real-world usage / Documentation |
| Status | PARTIAL |
| Priority | P2 |
| Evidence / Origin | 新用户上手路径观察 |
| Current Implementation | README / QUICKSTART / TROUBLESHOOTING 已完成主要工作（commit d97ab38） |
| Remaining Gap | 持续验证：陌生用户是否能仅凭仓库上手 |
| Decision | AAF 当前应描述为**本地 Multi-Agent Orchestration Framework / Tool**：<br>- 不是单纯 Meta Skill<br>- 不是 SaaS、IDE 或 ChatGPT 替代品<br>- 继续观察陌生用户上手情况 |
| Target | 新用户仅凭仓库可理解定位并完成 Quick Start |
| Do Not Forget | 产品定位说明要持续与 README 保持一致，防止表述漂移 |

---

## RW-003 — Bridge 自动识别与切换项目

| 字段 | 内容 |
|---|---|
| ID | RW-003 |
| Title | Bridge 自动识别与切换项目 |
| Category | Real-world usage / Bridge |
| Status | **SOLVED**（Phase F / AAF-v0.4-TASK-006 交付，2026-08-28；FIX-001 原子持久化 + 真实 UX 证据轮，2026-08-28） |
| Priority | P1 |
| Evidence / Origin | 真实事件：从 H5 workspace 切换回 AAF workspace 时，Bridge 因 current_workspace 不一致拒绝任务，需要人工修改 config 才能继续 |
| Current Implementation | Phase F（2026-08-28，AAF-v0.4-TASK-006）已交付：Bridge 从 canonical TASK Workspace 字段识别目标 workspace（不依赖聊天上下文/猜测路径）；workspace 分类驱动提交流程——SAME 正常继续无额外确认 / KNOWN（recent_projects 命中）显式确认后切换 / UNKNOWN（首次出现）fail-safe 暂停 + 明确确认 / INVALID（路径不存在、非目录、malformed、无权限、安全校验失败）fail closed 拒绝并给出明确原因；切换持久化唯一入口 = `config.update_project`（current_project / current_workspace + recent_projects 上限 5 条按 last_used 倒序）；RUNNING 任务时拒绝跨 workspace 切换；确认窗中文优先（当前项目 / 目标项目 / Workspace / Task ID / 将修改 AAF Bridge 项目设置说明）；restart 后 current project 从 config 正确恢复。设计 §9 全量落地。 |
| Remaining Gap | 无（设计 §9.2.3 的「从最近项目选择」下拉为可选增强，第一版仅确认窗——按设计原文「可选，若实现成本低」处理，未实现不构成缺口） |
| Decision | Phase F 已交付；用户不再需要手工编辑 config.json |
| Target | Bridge 能自动识别 TASK 指定的 workspace，并在切换前明确确认 ✅ |
| Do Not Forget | **不静默执行陌生路径**；切换必须显式确认，安全优先 ✅（UNKNOWN 必须确认后才允许加入/切换；reject 时不写任何文件） |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md` §9（Phase F 实现） |

---

## RW-004 — Bridge 启动方式与 Windows Tray

| 字段 | 内容 |
|---|---|
| ID | RW-004 |
| Title | Bridge 启动方式与 Windows Tray |
| Category | Real-world usage / Bridge lifecycle |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | 真实使用观察：电脑重启后 Bridge 当前不会自动恢复运行，Ctrl+Alt+A 因 Bridge 尚未启动而没有响应，用户需要重新启动 Bridge（曾需手工启动 python module；Terminal 关闭后 Bridge 停止） |
| Current Implementation | Phase B（AAF-v0.4-TASK-002，commit 6a9814d，2026-08-27 真实 Windows 验收 PASS）已交付：pythonw 无控制台后台启动（scripts/start_bridge.pyw）+ Tray skeleton（打开状态 / 重启 Bridge / 退出 AAF，ctypes Shell_NotifyIconW 零第三方依赖）+ 单实例 mutex + restart 交接。普通使用不再依赖持续打开 PowerShell / Terminal。仍无开机自动启动。 |
| Remaining Gap | 候选方向（Phase B 已覆盖项不再列为缺口）：<br>- 开机自动启动（autostart，未实现）<br>- Current Project 切换 / Open Status 增强 / Open Logs 文件级运行日志（未实现）<br>- 健康自恢复（见 RW-012，未实现） |
| Decision | 当前不实现（登记待办） |
| Target | Bridge 能由桌面壳层或后台机制管理，常驻可管理（Tray / 后台启动 / 状态入口）；普通使用时不依赖持续打开 PowerShell / Terminal 窗口 |
| Do Not Forget | 与 RW-006 / RW-010 相关联；不做成大型独立应用 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

---

## RW-005 — Framework 执行速度与阶段耗时

| 字段 | 内容 |
|---|---|
| ID | RW-005 |
| Title | Framework 执行速度与阶段耗时 |
| Category | Observation / Performance |
| Status | OBSERVATION |
| Priority | P2 |
| Evidence / Origin | 真实 TASK-011 体感比手工流程慢 |
| Current Implementation | 各阶段（Validation / Boundary / Hermes / WorkBuddy / Codex / REPORT）已有既有执行链，但无阶段耗时可观测数据 |
| Remaining Gap | 先记录并测量各阶段耗时：<br>- Validation<br>- Boundary<br>- Hermes<br>- WorkBuddy<br>- Codex<br>- REPORT |
| Decision | 先增加可观测性，再判断性能优化；**不能为了提速直接删除质量保障阶段** |
| Target | 各阶段耗时可观测、可对比 |
| Do Not Forget | 提速不得以牺牲质量保障阶段为代价 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

---

## RW-006 — Runtime 状态可视化

| 字段 | 内容 |
|---|---|
| ID | RW-006 |
| Title | Runtime 状态可视化 |
| Category | Observation / Tooling |
| Status | **SOLVED**（状态校正，2026-08-28：Phase C/D/E/F 已按真实交付证据闭合全部 Remaining Gap；仅校正状态，不重新开发） |
| Priority | P1 |
| Evidence / Origin | 真实使用中无法直观看到任务当前处于哪个阶段，运行时存在明显"黑盒感"：<br>- 当前到底执行到哪一步<br>- 当前 Agent 是谁<br>- 还要多久<br>- 是否仍有活动<br>- 是否卡住<br><br>用户明确希望：可视化阶段流程、小进度条、百分比、最近活动、当前状态、停止按钮。<br>目标体验：**"看得到 → 看得懂 → 控得住"**。 |
| Current Implementation | Phase C（AAF-v0.4-TASK-003）：正式状态窗口 `bridge/status_window.py`——当前项目 / Bridge 状态 / 热键 / Workspace / 当前任务（ID/Name/Stage/Agent/elapsed/last activity/result）/ 六阶段条，中文优先只读观察。Phase D（AAF-v0.4-TASK-004）：整体进度估算条（`bridge/progress.py` 静态权重 5/5/45/20/20/5 + 收敛规则，明确标注"估算"）+ suspected-stuck 提示（`bridge/stuck.py`，只提示不自动终止）。Phase E（AAF-v0.4-TASK-005-A/B/C）：状态窗口「停止当前任务」soft cancel + 「强制停止」二次确认 + Cancel UI 状态机 + elapsed 时间显示。Phase F（AAF-v0.4-TASK-006）：项目切换确认窗 + duplicate 状态卡片（均中文优先）。Remaining Gap 原列表全部闭合；Do Not Forget（看得到/看得懂/控得住、进度标注估算、拒绝大而全 Web Dashboard）全部遵守。 |
| Remaining Gap | 无（进度条百分比为估算值——按设计事实与估算分离原则，不伪装精确真实时间；此为设计约束而非缺口） |
| Decision | 建议未来与 Tray / Desktop UI 合并，而不是建设大型 Web Dashboard。<br><br>**阶段状态是可靠事实**，例如：<br>Validation ✓<br>Boundary ✓<br>Hermes ✓<br>WorkBuddy ▶<br>Codex ○<br>REPORT ○<br><br>**百分比属于 estimated progress，不能伪装成精确真实剩余时间。**<br><br>第一版允许使用静态阶段权重（仅为未来实现候选，本任务不实现算法）：<br>Validation 5<br>Boundary 5<br>Hermes 45<br>WorkBuddy 20<br>Codex 20<br>REPORT 5<br><br>长期可根据真实阶段耗时统计校准权重（与 RW-005 联动）。 |
| Target | 单窗口可读的运行时状态：当前项目 / TASK / Agent / 阶段 / 进度 一眼可见 |
| Do Not Forget | 核心体验目标：<br>**看得到** → 当前项目 / TASK / Agent / 阶段 / 进度<br>**看得懂** → 中文状态 / 最近活动 / 错误 / 是否疑似卡住<br>**控得住** → Stop Task / Restart Bridge / Project Switch / Open Logs<br><br>进度百分比必须明确标注为估算值。<br>拒绝大而全的 Web Dashboard；保持轻量。 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

---

## RW-007 — Agent executable discovery reliability

| 字段 | 内容 |
|---|---|
| ID | RW-007 |
| Title | Agent executable discovery reliability |
| Category | Real-world usage / Environment |
| Status | PARTIAL |
| Priority | P2 |
| Evidence / Origin | 真实事件：Codex 升级后安装 hash 目录变化导致 command discovery 失败（TASK-011 中 `MISSING_COMMAND: codex`） |
| Current Implementation | 已通过 commit **7cbf594** 处理当前 OpenAI Codex hash-directory upgrade 场景（registry PATH 优先 + hash 目录 fallback，仅针对 codex） |
| Remaining Gap | Hermes / WorkBuddy 当前主要依赖 PATH，尚未出现同类真实故障；继续 Observation |
| Decision | 不提前建设大型通用 executable manager |
| Target | 三个 Agent executable 在当前环境可稳定发现 |
| Do Not Forget | fallback 仅针对已出现真实故障的 codex；不扩为通用 manager |

---

## RW-008 — TASK / Bridge parser compatibility

| 字段 | 内容 |
|---|---|
| ID | RW-008 |
| Title | TASK / Bridge parser compatibility |
| Category | Real-world usage / Parser |
| Status | SOLVED (v0.4) |
| Priority | P1 |
| Evidence / Origin | 真实问题：最初 TASK 中以下单行字段出现换行格式时 Bridge 校验失败：Task ID / Task Name / Workspace。另：Planner 富文本 / Markdown 转义曾造成 marker 和文本格式风险。2026-08-19 生产复现：Planner 生成的标准 Compact TASK（Acceptance 为 20 项编号列表，后续还有 Expected Final Result / Route / Route Hint）被 Bridge 判「缺少必填字段: Acceptance」，但 Acceptance 实际存在。2026-08-29 生产再复现（TASK-009）：61e3a05 CRLF 修复后仍报「缺少必填字段: Acceptance」 |
| Current Implementation | 两轮修复（2026-08-19 + 2026-08-29）：<br>① 61e3a05：`parse_task` / `parse_task_fields` 解析前统一归一化行尾（CRLF → LF）；两层校验新增 Acceptance 唯一性 fail-closed；新增 `tests/test_rw008_intake_crlf.py`（11 tests）<br>② marker extraction 修复（本次）：`bridge/task_io.py::extract_task_body` 由裸子串 `BEGIN + (.*?) + END` 改为**独立行锚定** `^AAF_TASK_BEGIN$ ... ^AAF_TASK_END$`（MULTILINE，兼容 CRLF `\r?` 与 BOM `\ufeff?`）。原实现从第一个 `AAF_TASK_END` 子串截断——TASK-009 正文 Requirements 写有「AAF_TASK_BEGIN / AAF_TASK_END authority」被误当结束标记，Acceptance/Route 全部丢弃（61e3a05 不涉及此路径，故重启后仍复现）。新增 `tests/test_rw008_production_intake.py`（7 tests）+ `fixtures/TASK-009-production.md`（真实生产输入 exact fixture） |
| Remaining Gap | 剩余项均为 **LEGACY / NON-CONTRACT / OBSERVATION**（按正式 Compact TASK contract 分类，不构成 v0.4 blocker）：<br>- 全角空格（U+3000）行首缩进字段标题 → 解析失败（已实测复现，非 contract，deferred observation）<br>- Planner 富文本 / Markdown 转义风险（原 Evidence，未具体复现，deferred observation）<br>- `Acceptance Criteria` 旧别名仅在 task_validation 支持，`bridge/task_io` 层未支持（LEGACY，正式 contract 为 `Acceptance`） |
| Decision | 正式 Compact TASK contract 已完整支持（LF/CRLF/BOM/独立行 marker/多行 Acceptance/后续 section/EOF/duplicate fail-closed/missing-empty reject/Route fail-closed）。RW-008 = SOLVED for v0.4；剩余 legacy/non-contract 兼容性仅登记 observation，不做 parser 扩张 |
| Target | parser 兼容多种合理排版（含全角空格、富文本转义），且不受 Markdown 转义影响 |
| Do Not Forget | 代码层 exact production regression 已通过（TASK-009 原文 fixture 校验 True）；真实 Bridge 投递由用户最终确认。剩余 U+3000 / 富文本 / 旧别名仅为 observation，不得为关 backlog 而扩张 parser |

---

## RW-009 — ChatGPT Project / Conversation disaster recovery

| 字段 | 内容 |
|---|---|
| ID | RW-009 |
| Title | ChatGPT Project / Conversation disaster recovery |
| Category | Durability / Recovery |
| Status | PARTIAL |
| Priority | P0 |
| Evidence / Origin | 长期维护原则：AAF 后续维护不能依赖某一个永久存在的 ChatGPT Project 或历史 conversation |
| Current Implementation | 已有恢复资产雏形：README、PROJECT_STATE、closing handoffs；本任务新增 Master Backlog |
| Remaining Gap | 完整 Recovery flow 需持续演练并保持资产最新：<br><br>GitHub / local repo<br>→ README<br>→ PROJECT_STATE<br>→ AAF_MASTER_BACKLOG<br>→ latest closing handoff<br>→ 创建新的 ChatGPT Project / Planner conversation<br>→ 继续维护 |
| Decision | 即使旧 ChatGPT Project 或 conversation 不存在，Framework 仍能恢复到可继续升级的状态 |
| Target | 零 ChatGPT 依赖的恢复链验证通过 |
| Do Not Forget | ChatGPT 是规划/协作界面，不是唯一长期知识来源 |

---

## RW-010 — Desktop App / Windows Program Packaging

| 字段 | 内容 |
|---|---|
| ID | RW-010 |
| Title | Desktop App / Windows Program Packaging |
| Category | Future capability / Packaging |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 长期候选方向（与 RW-004 / RW-006 / RW-014 / RW-015 相关联，见 Desktop / Runtime UX Cluster） |
| Current Implementation | 无桌面壳层；Bridge 以 python module 运行 |
| Remaining Gap | 长期候选：<br>- Tray<br>- Status Window<br>- Project selector<br>- Settings<br>- Start / Stop / Restart Bridge |
| Decision | 原则：**Desktop App ≠ 重写 AAF**。复用现有 Framework Core，增加小型桌面壳层。目标架构：<br><br>AAF Core<br>↓<br>Desktop Shell / Tray<br><br>核心执行逻辑保持独立，UI 只负责操作、状态和生命周期入口。<br>**明确不扩展到**：<br>- SaaS<br>- 多用户后台<br>- 云端管理平台<br>- Agent marketplace<br>- 无限自主循环 |
| Target | 轻量桌面壳层，不改变 Framework Core 边界 |
| Do Not Forget | 小而本地；禁止膨胀为平台 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

---

## RW-011 — Router local constraint classification incident

| 字段 | 内容 |
|---|---|
| ID | RW-011 |
| Title | Router local constraint classification incident |
| Category | Incident / Router |
| Status | SOLVED |
| Priority | P1 |
| Evidence / Origin | AAF-MAINT-001 因局部范围限制被错误路由（局部禁止修改产品代码的约束被误判为任务级 review 模式），Hermes 未执行；route 被错误定为复核类（非执行类），实际执行动作（创建 backlog / 更新 PROJECT_STATE / commit+push）全部被压制 |
| Current Implementation | 已修复：commit **457df93**（execution intent 与局部限制能够区分；206 tests passed；WorkBuddy APPROVE；Codex APPROVE；Remote Sync SUCCESS）。详见 `docs/internal/AAF-HOTFIX-ROUTER-READONLY.md` |
| Remaining Gap | 无（该 incident 已解决）；相关语义隔离问题见 RW-013 |
| Decision | **要求保留该事故历史，不因为已经解决而删除** |
| Target | 同类局部约束不再触发错误路由（已达成） |
| Do Not Forget | `.aaf/AAF-MAINT-001/` 保留为真实事故证据；不删除、不覆盖 |

---

## RW-012 — Bridge hotkey listener runtime reliability

| 字段 | 内容 |
|---|---|
| ID | RW-012 |
| Title | Bridge hotkey listener runtime reliability |
| Category | Real-world usage / Bridge |
| Status | SOLVED (v0.4) |
| Priority | P1 |
| Evidence / Origin | 真实使用至少两次出现：<br>- Bridge 进程看似仍存在<br>- Ctrl+Alt+A 无响应<br>- 重启 Bridge 后恢复<br><br>另一次电脑重启后无响应属于 Bridge 尚未配置自动启动（见 RW-004），是**不同场景**，应分别说明 |
| Current Implementation | Phase B（AAF-v0.4-TASK-002，commit 6a9814d）已新增 hotkey health 判定：`classify_bridge_health()`（listener registered + loop alive → OK / DEGRADED），每 5s 轮询，Tray 图标 / Tooltip 反映健康（IDI_APPLICATION ↔ IDI_WARNING）；FIX-001 真实 GUI 验收中健康显示正常（含 1409 冲突路径行为正确）。<br>**RW-012 收口（AAF-v0.4-TASK-009，2026-08-29）：listener 自恢复已实现**——Bridge 唯一 lifecycle owner：`HotkeyRecovery` 策略（纯逻辑，可单测）+ `Bridge._poll_health` 检测 DEGRADED（线程退出 / 注册失败 / 未注册）后仅重建 listener（`_apply_hotkey(show_error=False)`，不重启 Bridge）；有界 backoff（15s/30s/60s，连续 3 次失败停止自动恢复，无 tight loop）；恢复进行中重复触发 coalesce（无重复 listener / 无重复热键注册，重建前先注销旧热键）；主动退出（Exit 确认 / Restart 交接）期间 `shutting_down` 阻止恢复、退出不复活；恢复失败经 Tray 图标 / Tooltip / 状态窗口（`_current_health` 并入恢复说明）可观察；新增 `tests/test_rw012_listener_recovery.py`（21 项，全部非 GUI）。<br>**RW-012 FIX-001（AAF-v0.4-TASK-009-FIX-001，2026-08-29）：listener-owned lifecycle 修复**——Codex 确认的 lifecycle ownership defect 已闭合：① registration 归 listener 线程所有，注销（UnregisterHotKey）改由 listener 线程在 run() finally 中执行（**thread-owned unregister**），Bridge 主线程不再直接 UnregisterHotKey（`_apply_hotkey` / Restart / Exit 的 main-thread 注销路径全部删除）；② HotkeyListener 新增显式 **stop 契约**：`request_stop()`（停止标志 + PostThreadMessageW WM_QUIT 唤醒真实消息循环）+ `stop(timeout)`（**有界 join**，返回是否已确认线程退出），不依赖 daemon 线程自然消失；③ **stop-before-replace**：`_apply_hotkey` 先请求旧 listener 停止并确认线程退出，才创建新 listener；旧 listener 超时未退出 → fail safe（不创建 duplicate replacement、log warning、保持 DEGRADED 可恢复）；④ `_lifecycle_lock` 并发 guard：同一时刻单一 lifecycle transition owner，并发触发合并（one-listener invariant）；⑤ intentional shutdown（Exit / Ctrl+C）走 `Bridge.shutdown()` → stop 契约收尾，不恢复不复活；⑥ 验证执行上下文而非仅 mock 调用：新增真实线程级测试 `tests/test_rw012_listener_ownership.py`（register/unregister 线程身份断言 + 真实消息循环 WM_QUIT 唤醒 + 有界 stop），RW-012 定向 38 项；全量 non-GUI 1131 passed（1114 基线 + 17 新增，零下降）。<br>**RW-012 FIX-002（AAF-v0.4-TASK-009-FIX-002，2026-08-29）：listener ownership retention + readiness truth**——关闭 FIX-001 遗留的最后两个同根 lifecycle blocker（Codex REQUEST_CHANGE）：① **ownership retention**：`_stop_listener` 不再在 stop(timeout) 确认前清空 `self.listener`——只在 stop()==true / 线程已确认 not alive 后才解绑；stop 超时保留引用并记入 `_pending_stop`（DEGRADED / recovery pending 可观察），跨 recovery cycle 持续针对同一个旧 listener 处理，不启动 replacement、不伪装 healthy、无 orphan 窗口（one-listener ownership invariant 跨 cycle 成立）；`_poll_health` 增加 pending 旧 listener 迟延退出独立检测（退出确认后必清理引用，随后按正常恢复策略启动 exactly one replacement，不永久卡死）；`_try_recover_hotkey` 异常路径不再盲目清空仍存活的引用（orphan prevention）；② **wait_ready authority**：`wait_ready(LISTENER_READY_TIMEOUT)` 返回值参与 start success 判定——初始化超时（线程可能仍 alive 但未 ready）不 reset recovery/backoff、不报告 healthy，进入 DEGRADED 恢复流程；wait_ready=true+error 仍按注册失败处理（不 healthy）；健康判定新增非阻塞 `HotkeyListener.is_ready()` 维度（alive != ready != healthy）；新增 14 项定向测试 `tests/test_rw012_listener_ownership_fix002.py`（stop timeout 跨 cycle 1/2/3、delayed exit 单 replacement、readiness A–D、ownership A–H、bounded recovery、config reload 等旧退出、shutdown 不复活）；RW-012 定向 52 项 + 全量 non-GUI 1145 passed（1131 基线 + 14 新增，零下降）+ 真实 E2E 9 项全过；RW-008 无回归。<br>**RW-012 FIX-003（AAF-v0.4-TASK-009-FIX-003，2026-08-29）：atomic delayed-exit recovery（单一 lifecycle authority）**——关闭 FIX-002 遗留的最后两个同根 lifecycle blocker（Codex 确认）：① **TOCTOU 关闭**：`_poll_health` 的 delayed-exit check-and-clear 收进受 `_lifecycle_lock` 保护的原子单元 `_delayed_exit_cleanup()`——check（pending 存在且已退出）→ 锁内 identity 重验证（`_pending_stop is old` / `self.listener is old` / not alive）→ 才清理；「lock 外 check → 锁内另一路创建 replacement → lock 外 clear 清掉新 listener reference」的合法交错不再存在（Codex 精确 race 用真实双线程 barrier 多轮复现，两种调度顺序下恰好一个活跃 listener、无 orphan、无 duplicate）；② **exhausted recovery re-arm**：recovery budget exhausted（`_stopped`）后旧 listener 才迟延退出 → `HotkeyRecovery.rearm()` 开启一次新的**有界** recovery epoch（epoch+1，`_stopped`/backoff/失败计数复位）——旧 ownership blocker 确认退出是真实 lifecycle 状态变化，不是无限 retry；replacement 失败仍受 max_failures/backoff 约束，epoch 只随真实 delayed-exit 事件增长（无 per-poll 无限重置、无 tight loop）；③ **identity-safe clear**：`_clear_pending_ownership_locked` 双身份校验（pending 与 listener 必须同一 old 对象），stale cleanup 针对 old=A 时 `self.listener is B` 绝不清掉 replacement（Req 12 精确回归）；④ 所有 `self.listener` / `_pending_stop` / ownership-clear / rearm transition 统一在 `_lifecycle_lock` 内（`_apply_hotkey` / `_delayed_exit_cleanup` / `_try_recover_hotkey` 异常路径 / shutdown / restart），单一 transition authority；⑤ shutdown 不 rearm、不复活；config reload 与 recovery 共用同一 guard。新增 15 项定向测试 `tests/test_rw012_atomic_delayed_exit_fix003.py`（A 锁内 cleanup / B Codex 精确 race / C 双身份校验 / D stale clear 不清 replacement / E exhausted+old 存活无 replacement / F old 退出后恰一次 rearm / G 无 infinite rearm / H Req10 全场景单 replacement / I 失败仍 bounded / J 并发 config+recovery 单 listener / K shutdown 无 rearm 无重启 / L readiness 回归 + rearm 单元语义）；并用 scratch 反证：把旧 unlocked cleanup / 无 rearm clear 注入后对应测试确定性 FAIL（测试真实模拟 check/transition 顺序，非仅测锁获取失败）；RW-012 定向 84 项 + 全量 non-GUI 1169 passed（1154 基线 + 15 新增，零下降）；RW-008 无回归（18 passed，parser 零改动）。<br>**RW-012 FIX-004（AAF-v0.4-TASK-009-FIX-004，2026-08-29）：atomic recovery transition consolidation（单一锁内 lifecycle transition）**——关闭 Codex 确认的 FIX-003 遗留 blocker：delayed-exit recovery 从「cleanup 锁内 → 释放锁 → 锁外 eligibility → 再获取锁创建 replacement」的多段 ownership transition 收敛为**单一锁内 lifecycle transition**：`Bridge._run_lifecycle_transition()` 在同一个 `_lifecycle_lock` 临界区内完成 old pending 确认退出 → 锁内 identity 重验证（pending/listener 双身份 + not alive）→ clear old ownership → rearm 恰好一次 → eligibility 判定 → reserve attempt（begin_attempt）→ exactly one replacement（`_apply_hotkey_locked`）——`listener=None / pending=None / rearmed 但未 reserved/owned` 的可竞争中间态只在锁内瞬时存在，任何其他 lifecycle trigger 在锁外不可见、非阻塞获取锁失败即合并（无 exposed ownership gap）；`_apply_hotkey` 拆为 public（获取锁）+ `_apply_hotkey_locked`（假定持锁，**唯一 listener replace/start transition owner**——config reload / health recovery / delayed cleanup / restart-failure / 外部入口全部汇入同一 authority，无第二套 creation 逻辑，持锁内再触发 = coalesce，无递归锁死）；rearm 仍只随真实 delayed-exit ownership release 发生（epoch 不因 listener=None / DEGRADED / 每 poll 自增）；shutdown 不 cleanup / 不 rearm / 不创建；healthy listener 不无谓 restart（config reload 同 hotkey 不重启）。新增 13 项定向测试 `tests/test_rw012_atomic_recovery_fix004.py`（① 单一锁内 transition 无 gap（工厂钩子证明锁全程持有 + 同线程再触发合并）② 精确 Codex interleaving 真实线程：transition 持锁期间第二 trigger（config reload 路径）无独立 creation authority + stale cleanup 阻塞锁上、锁内重验后不清 replacement ③ exhaustion→delayed exit 恰一次 rearm / 单 epoch / 多 poll 不增长 ④ failed new epoch bounded / backoff / 无 per-poll 预算重置 ⑤ healthy 终态（引用正确 / pending=None / ready / 无 error / 不无谓 restart）⑥ config reload 同 hotkey 不 restart ⑦ listener=None 有界尝试但 epoch 不增长 ⑧ 冲突可观察 / bounded / 无 duplicate / 恢复路径无 modal（不把文案当 external conflict 证明）⑨ shutdown 不复活 ⑩ readiness truth 回归 ⑪ public apply 持锁 coalesce ⑫ transition 内 stop-before-replace ⑬ stop 失败 fail safe 保留 ownership）；scratch 反证（`.aaf/scratch_fix004_counterproof.py`）：同一 delayed-exit + interleave 交错下，旧设计产生 **2 次创建（duplicate replacement）**，新设计 **exactly one** —— 新测试对旧设计确定性 FAIL；RW-012 定向 98 项 + 全量 non-GUI 1182 passed；RW-008 无回归（parser 零改动）。<br>**RW-012 FIX-005（AAF-v0.4-TASK-009-FIX-005，2026-08-29）：shutdown/recovery 单一 lifecycle authority（TOCTOU 收口）**——关闭 Codex FIX-004 唯一 blocking finding（`_run_lifecycle_transition` lock 外检查 shutdown、lock 内不重验证 → 等待锁期间 shutdown 发布后仍可能 rearm/创建 replacement）：① shutdown intent 发布（`shutdown()` / `_exit_aaf()` / `_restart_bridge()`）全部收敛到 `_lifecycle_lock` 内（`_shutting_down=True` 先于 stop 发布；`_restart_bridge` Popen 失败在同一 authority 下回滚并恢复热键）；② transition 取得 authority 后锁内重新验证 shutdown——pre-lock check False → 等待锁 → shutdown 发布 → 取得锁的 recovery 观察到 True → 不 cleanup / 不 rearm / 不 begin_attempt / 不创建（精确 check-then-wait 竞态关闭）；③ `_apply_hotkey_locked`（唯一 listener creation authority）锁内以 shutdown 守卫拒绝 config reload / 外部触发在 shutdown 后的任何创建（config reload during shutdown 不 restart / 不复活）；④ `_clear_pending_ownership_locked` 的 rearm 只在非 shutdown 时发生（shutdown 期间 delayed-exit cleanup 只做 ownership bookkeeping、epoch 不变、绝不 rearm）；无递归锁死（shutdown 阻塞等待 authority，transition 完成后接管，reverse ordering 由 shutdown 安全接管）；新增 `tests/test_rw012_shutdown_atomicity_fix005.py`（13 项：精确 Codex TOCTOU 真实线程 + 确定性门闩 / reverse interleaving / delayed-exit during shutdown / config reload during shutdown / poll during shutdown / shutdown 发布顺序可观察 / _exit_aaf 确认-取消 / _restart_bridge 成功-失败回滚 / 唯一 authority 锁内守卫 / 并发无死锁 / 非 shutdown 正常路径无回归），TOCTOU 与 reverse 测试对未修复代码确定性 FAIL（stash 反证）；RW-012 定向 111 项 + 全量 non-GUI（排除真实 UI 文件 test_phase_f_fix_001_ui.py——任务禁止真实剪贴板/项目切换确认窗）passed；RW-008 无回归（parser 零改动）。 |
| Remaining Gap | **NONE**（RW-012 收口 + FIX-001 lifecycle 修复 + FIX-002 ownership retention/readiness truth + FIX-003 atomic delayed-exit recovery + FIX-004 atomic recovery transition consolidation：listener 自恢复已实现，Bridge 唯一 owner 有界 backoff，连续 3 次失败停止自动恢复；registration/unregistration 归 listener 线程（thread-owned unregister）、显式 stop 契约 + 有界 join、stop-before-replace、**跨 recovery cycle 的 one-listener ownership invariant**（旧 listener 未确认退出前保留引用、不启动 replacement、无 orphan、wait_ready 返回值参与 start success 判定、alive != ready）有真实线程级 + 跨 cycle 测试证据；**delayed-exit cleanup 受 lifecycle lock 保护的原子单元 + identity-safe clear（stale cleanup 绝不清 replacement，Codex 精确 TOCTOU race 双线程复现关闭）+ exhausted recovery 在真实 ownership release 后 rearm 一次新有界 epoch（epoch 计数可观测，无 per-poll 无限重置、无 tight loop）**；**FIX-004 后 cleanup/rearm/eligibility/reserve/replacement 收敛为单一锁内 lifecycle transition（`_run_lifecycle_transition`），`_apply_hotkey_locked` 为唯一 listener replace/start authority（config reload / health recovery / delayed cleanup / restart-failure 全部汇入），无 exposed ownership gap、无递归锁死、无 per-poll rearm、stale cleanup 绝不清 replacement（精确 Codex interleaving 真实线程测试 + scratch 反证旧设计 duplicate）**；**FIX-005 后 shutdown intent 发布（shutdown/_exit_aaf/_restart_bridge）与 listener lifecycle transition 共用同一 `_lifecycle_lock`（锁内发布、Popen 失败锁内回滚）、transition 取得 authority 后锁内重验证 shutdown（精确 Codex check-then-wait TOCTOU 关闭：等待锁期间 shutdown 发布的 recovery 不 cleanup / 不 rearm / 不 begin_attempt / 不创建）、唯一 creation authority（`_apply_hotkey_locked`）锁内 shutdown 守卫（config reload during shutdown 不 restart / 不复活）、shutdown 期间 delayed-exit cleanup 只做 ownership bookkeeping 不 rearm（epoch 不变）**；hotkey health OK/DEGRADED + Tray 反映 + 恢复状态可见；restart UX / singleton awareness 已由 Phase B 提供；剩余仅登记 observation：恢复停止后需人工处理热键占用，属有界安全设计，不是缺口） |
| Decision | 已实现（AAF-v0.4-TASK-009 收口 + FIX-001 lifecycle 修复 + FIX-002 ownership retention/readiness truth + FIX-003 atomic delayed-exit recovery + FIX-004 atomic recovery transition consolidation，2026-08-29）：listener 意外失活自动重建（不重启 Bridge），有界重试 + 主动退出安全 + 失败可见；FIX-001 后 registration/unregistration 归 listener 线程、stop-before-replace、one-listener invariant 有真实线程级证据；FIX-002 后 stop 超时保留 ownership reference（_pending_stop）、跨 recovery cycle 不启动 replacement、delayed exit 后恰一 replacement、wait_ready false/error 不视为 healthy；FIX-003 后 delayed-exit cleanup 为 lifecycle lock 内原子单元（锁内 identity 重验证，stale cleanup 绝不清 replacement，Codex 精确 TOCTOU race 双线程复现关闭）、exhausted recovery 在真实 ownership release 后 rearm 一次新有界 epoch（无 per-poll 无限重置、无 tight loop）、shutdown 不 rearm 不复活；FIX-004 后 delayed-exit recovery 收敛为单一锁内 lifecycle transition（`_run_lifecycle_transition`：cleanup→rearm→eligibility→reserve→exactly one replacement 同一 `_lifecycle_lock` 临界区，`_apply_hotkey_locked` 为唯一 listener replace/start authority，无 exposed ownership gap、无递归锁死、无 per-poll rearm、config reload 与 recovery 共用同一 authority、healthy listener 不无谓 restart，Codex 精确 interleaving 真实线程测试 + scratch 反证旧设计 duplicate）；FIX-005 后 shutdown 与 recovery 共用同一 lifecycle authority（Codex FIX-004 唯一 blocking finding 关闭：shutdown intent 在锁内发布（Popen 失败锁内回滚）、transition 锁内重验证 shutdown（精确 check-then-wait TOCTOU）、reverse ordering 由 shutdown 安全接管、delayed-exit / config-reload / poll during shutdown 均不 rearm / 不创建、shutdown 期间 delayed-exit cleanup 只 bookkeeping 不 rearm（epoch 不变）、无递归锁死、唯一 creation authority 保持、新增 13 项定向回归含真实线程反证）；RW-012 = SOLVED for v0.4（WorkBuddy 验证 + Codex 确认全部成立后由 Planner 最终裁定） |
| Target | listener 可自检、可自恢复、重启 UX 顺畅 |
| Do Not Forget | **Bridge process 存活不能单独证明 hotkey listener 健康**；恢复必须单一 owner、有界、退出期间禁止（均已实现） |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

---

## RW-013 — Router self-triggering reference trap

| 字段 | 内容 |
|---|---|
| ID | RW-013 |
| Title | Router self-triggering reference trap |
| Category | Incident / Router |
| Status | OPEN |
| Priority | P1 |
| Evidence / Origin | AAF-MAINT-001-FIX-001 为描述前一次 Router incident（RW-011），在 Background 中引用 Router 自己用于分类的特殊短语，导致当前 Router 再次根据全文命中 review route，Hermes 第二次被跳过 |
| Current Implementation | Runtime Diagnose 已确认：<br>- current source loaded（Router source 正确）<br>- no stale route（route.json 非 stale）<br>- no wrong import（import path 正确）<br>- no routing truncation（TASK 在 routing 前未截断）<br>- Direct Probe reproduced the same route（与 stored route.json 一致）<br><br>根因属于 self-triggering reference trap：当前 Router 基于全文 keyword/signal 判断，任务中"讨论规则本身"和"真正发出规则要求"没有语义隔离 |
| Remaining Gap | 当前 Router 基于全文 keyword/signal 判断，"讨论规则本身"和"真正发出规则要求"没有语义隔离 |
| Decision | **本任务只登记，不修改 Router**（Framework runtime implementation 保持现状） |
| Target | Future candidate：评估结构化字段优先、section-aware routing、或其他不会被引用文本自触发的方案 |
| Do Not Forget | - 本任务及后续登记文档**不原样引用任何 Router 触发短语**，防止再次自我触发<br>- `.aaf/AAF-MAINT-001-FIX-001/` 保留为真实事故证据 |

---

## RW-014 — Task Stop / Cancel Capability

| 字段 | 内容 |
|---|---|
| ID | RW-014 |
| Title | Task Stop / Cancel Capability |
| Category | Runtime UX / Lifecycle Control |
| Status | PARTIAL（Phase E 已交付主体；剩余：Tray 菜单停止项（设计 §12.2，不在 005-C 范围）留待后续阶段） |
| Priority | P1 |
| Evidence / Origin | 真实执行 AAF 任务过程中，用户发现 Execute 后若需要中断当前任务，现有产品没有明确的 Stop / Cancel 操作入口。当前只能借助外部进程管理方式处理，这对日常用户不友好，也容易造成状态与实际进程不一致 |
| Current Implementation | Phase E（2026-08-28，TASK-005-A + 005-B + 005-B-FIX-001 + 005-C + 005-C-FIX-001）已交付：soft cancel（cancel.request 契约 + 检查点收敛 + CANCELLED 终态）、force cancel（verified ownership 进程树终止 + 结构化 evidence + Core recovery finalizer）、状态窗口「停止当前任务」+ 二次确认「强制停止」+ 停止状态机（正在运行/请求停止/正在取消/已取消/已完成/无法安全停止）。Stop Current Task 与 Exit AAF 明确分离。005-C-FIX-001：canonical UTC/aware elapsed contract 关闭 Codex 唯一 timezone blocker（合法 offset-aware timestamp 不再破坏 Cancel UI / force eligibility）。 |
| Remaining Gap | - Tray 菜单「停止当前任务」项（设计 §12.2 Tray 菜单含停止项；005-C 范围仅为状态窗口，Tray 项留待后续阶段）<br>- 其余（runner 停止 / agent chain 停止 / 不影响 Bridge / 不误伤独立会话 / 保留证据 / 明确 lifecycle 终态 / UI 停止入口 / 防重复点击 / 确认步骤 / 区分正常取消·失败·异常终止）已在 Phase E 全部闭合（见 PROJECT_STATE.md Phase E 段落与冻结设计 §6/§6A/§6B） |
| Decision | Phase E 已按冻结设计 §6/§6A/§6B 交付（非粗暴 kill-process 按钮）；Tray 停止项按 §12.2 登记为后续阶段范围边界，不自动实现 |
| Target | 未来 Desktop Shell / Runtime UX implementation phase（Tray 停止项） |
| Do Not Forget | 用户需要的是"安全停止当前 TASK"，而不是"关闭整个 AAF"——Stop Current Task 与 Exit AAF 必须明确区分 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（§6 / §6A / §6B / §12.2） |

---

## RW-015 — Chinese-first Desktop / Tray User Interface

| 字段 | 内容 |
|---|---|
| ID | RW-015 |
| Title | Chinese-first Desktop / Tray User Interface |
| Category | Desktop UX |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | 用户明确提出：未来 AAF 如果形成桌面小程序、Tray 或 Status Window，面向人的界面最好默认使用中文 |
| Current Implementation | AAF 当前仍以 CLI、Bridge 弹窗、Markdown 报告和技术状态字段为主，尚未形成统一桌面 UI |
| Remaining Gap | 未来用户界面需要定义：<br>- 中文按钮<br>- 中文状态描述<br>- 中文错误提示<br>- 中文设置项<br>- 中文项目切换<br>- 中文任务控制<br>- 中文运行进度<br><br>底层技术字段允许继续保留：<br>SUCCESS / WAITING / FAILED / FRAMEWORK_ERROR / Hermes / WorkBuddy / Codex<br>但面向用户时应提供清晰中文表达 |
| Decision | Chinese-first。当前不因为国际化需求增加复杂语言系统。未来如确有公开用户需求，再评估中英文切换 |
| Target | Desktop Shell / Tray UX phase |
| Do Not Forget | 日志和内部协议可以继续英文，用户操作界面优先中文 |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（AAF-DESIGN-001：Desktop Shell 最小设计完成，实现未开始） |

---

## RW-016 — Duplicate Task Status UX

| 字段 | 内容 |
|---|---|
| ID | RW-016 |
| Title | Duplicate Task Status UX |
| Category | Runtime UX / Bridge |
| Status | **SOLVED**（Phase F / AAF-v0.4-TASK-006 交付，2026-08-28；FIX-001 原子持久化 + 真实 UX 证据轮，2026-08-28） |
| Priority | P1 |
| Evidence / Origin | 真实使用：AAF-MAINT-002 实际已经执行完成，用户再次按 Ctrl+Alt+A 提交相同 Task ID 时只收到 TASK_ALREADY_EXISTS。用户无法从弹窗判断任务到底是 RUNNING / WAITING / SUCCESS / FAILED / stale；也没有查看任务 / 查看状态 / 打开 REPORT 的入口。 |
| Current Implementation | Phase F（2026-08-28，AAF-v0.4-TASK-006）已交付：duplicate protection 原样保留（canonical TASK.md 落盘路径存在即 duplicate，与 save_task 同一判定，未放宽 execution authority）；duplicate 触发时展示中文状态卡片——至少区分 running（同 Task ID 正在运行：不启动第二 runner）/ completed（已完成 SUCCESS/WAITING/FAILED/CANCELLED：明确说明需新 Task ID）/ abnormal（已存在但状态异常：残留 RUNNING/CREATED 等）/ unknown（状态未知：无 task.json）；卡片显示 Task ID / 当前状态（中文映射 + 英文原值）/ 当前阶段 / 最近活动 / 结果 / REPORT 路径，提供 [查看状态] / [打开 REPORT]（归档任务自动定位）/ [关闭]；RUNNING 卡片不提供 [打开 REPORT]（REPORT 未生成）；不覆盖任何历史 artifacts；RUNNING 任务时拒绝跨 workspace 切换。设计 §10 全量落地。 |
| Remaining Gap | 无（§10.3 的 Resume 按钮按设计原文「第一版可只显示提示该任务需重新提交」处理——未实现 Resume 按钮不构成缺口；`--resume-from` 既有 CLI 保留不动） |
| Decision | Phase F 已交付；用户无需打开 .aaf 文件夹猜任务状态 |
| Target | 用户不需要打开 .aaf 文件夹猜任务状态 ✅ |
| Do Not Forget | TASK_ALREADY_EXISTS 本身不是错误；真正 UX 缺口是"只告诉存在，不告诉现在是什么状态" ✅（现在卡片给出状态/阶段/最近活动/REPORT 入口） |
| Design Reference | `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md` §10（Phase F 实现） |

---

## RW-017 — .aaf Runtime Artifact Git Ignore Consistency

| 字段 | 内容 |
|---|---|
| ID | RW-017 |
| Title | .aaf Runtime Artifact Git Ignore Consistency |
| Category | Repository hygiene / Runtime artifacts |
| Status | OBSERVATION |
| Priority | P3 |
| Evidence / Origin | 真实执行中 git status 长期显示 .aaf/ 为 untracked。 |
| Current Implementation | 当前 .gitignore 存在 .aaf-*/ 模式，但该模式不覆盖实际 runtime 目录 .aaf/。 |
| Remaining Gap | 评估是否应明确忽略 .aaf/，同时确认是否有任何 .aaf artifact 需要长期保留在 repo。 |
| Decision | 当前只登记，不修改 .gitignore。 |
| Target | 未来明确 runtime artifact 与 repository history 的边界。 |
| Do Not Forget | .aaf 中包含真实运行证据，不能在未确认 archive / recovery 策略前直接清理或删除。 |

---

## RW-018 — GitHub Push / Proxy Environment Reliability

| 字段 | 内容 |
|---|---|
| ID | RW-018 |
| Title | GitHub Push / Proxy Environment Reliability |
| Category | Environment / Git Operations |
| Status | OBSERVATION |
| Priority | P3 |
| Evidence / Origin | 真实维护任务中 git push 曾出现直连 GitHub TLS EOF；使用本机 Clash SOCKS5 临时代理（socks5h://127.0.0.1:7897）后 push 成功。<br><br>2026-08-27 复现（AAF-MAINT-003）：直连 TLS EOF 再次出现；本次 socks5h://127.0.0.1:7897 模式不通（curl 000），同端口 HTTP 代理模式 http://127.0.0.1:7897 可用并 push 成功。 |
| Current Implementation | AAF Core 不管理 Git 网络代理。Git push 由执行环境完成。 |
| Remaining Gap | 观察该问题是否重复发生。 |
| Decision | 当前不把代理配置写入 Framework Core。如未来频繁复现，再考虑：documentation / environment preflight / clearer push failure guidance。 |
| Target | Git push 失败时能明确区分 Framework 故障与外部网络环境故障。 |
| Do Not Forget | 网络代理属于环境层，不要因为单次 TLS 问题扩大 AAF Core scope。 |

---

## RW-019 — Agent Review Execution Evidence Consistency

| 字段 | 内容 |
|---|---|
| ID | RW-019 |
| Title | Agent Review Execution Evidence Consistency |
| Category | Agent execution / Observability |
| Status | OBSERVATION |
| Priority | P2 |
| Evidence / Origin | AAF-MAINT-002 Hermes 报告曾描述"本机未安装 Codex CLI"，但 Framework 最终 REPORT / Agent Results 中存在真实 Codex Reviewer APPROVE。两种表述并存，环境描述不一致。 |
| Current Implementation | 最终 Framework REPORT 能保存各 Agent 结果，但不同执行者的环境描述可能不一致。 |
| Remaining Gap | 未来需要更清楚地区分：<br>- Agent CLI discovered<br>- Agent actually launched<br>- fallback / inline audit<br>- independent reviewer result<br>- environment where the check occurred |
| Decision | 当前只登记。不要据此开发 universal executable manager。 |
| Target | 用户和 Planner 能从 REPORT 判断："哪个 Agent 真正独立执行过，在哪个环境执行，是否使用 fallback。" |
| Do Not Forget | "报告里有 Codex 内容"和"本机 Codex CLI 独立执行成功"不是完全相同的事实，未来应避免模糊表述。 |

---

## RW-020 — Dead Runner / Orphaned RUNNING State Detection

| 字段 | 内容 |
|---|---|
| ID | RW-020 |
| Title | Dead Runner / Orphaned RUNNING State Detection |
| Category | Runtime Reliability / Runtime Observability |
| Status | **SOLVED**（Runtime Integrity batch / AAF-v0.4-TASK-007 交付，2026-08-28：`ai_agent_framework/runtime_health.py` 只读 liveness 判定——Lifecycle State 与 Runtime Health 严格分离；组合信号死判（runner 进程缺失/身份不可证明 + last_activity stale + 期望阶段产物缺失 → SUSPICIOUS_DEAD「任务可能已异常中断」）；单一 PID / 单一时间阈值不判死；PID reuse fail-safe；canonical terminal wins；recovery 流程保护；Status Window 中文警告横幅 + [查看诊断]（含既有 resume-from 恢复路径提示）；30 项单元回归 + 6 项真实 runner 运行时练习 + 3 项 UI 集成；CLI `python -m ai_agent_framework.runtime_health --output <dir>`；真实任务实况验证 HEALTHY（TASK-007 自身 runner，creation time + 命令行 identity 通过）。UI 无 terminal authority——只产生 health/warning/diagnostics，Terminal authority 保持 Core / Lifecycle） |
| Priority | P1 |
| Evidence / Origin | AAF-v0.4-TASK-001-FIX-003 real incident, 2026-08-27。任务进入 WORKBUDDY 阶段后（Hermes 已完成）：task.status=RUNNING、stage=WORKBUDDY、agent=workbuddy、last_activity_at 停止更新、workbuddy_result.md 从未生成、WorkBuddy 进程已不存在、Framework runner 进程已不存在、Bridge 进程已不存在、REPORT.md 未生成；task.json 长时间保持 RUNNING / WORKBUDDY，用户无任何提示只能继续等待。<br><br>后续通过 Framework resume 恢复：复用 Hermes result → WorkBuddy PASS → Codex APPROVE → REPORT → SUCCESS / COMPLETED。恢复机制有效，但 **Dead Runner Detection 缺失**。<br><br>2026-08-27 再次真实复现（AAF-v0.4-TASK-004 Phase D）：实现与 E2E 全部完成后（.aaf/AAF-v0.4-TASK-004/REPORT.md 已生成，mtime 2026-08-27 20:03:04），canonical task.json 仍残留 RUNNING / HERMES（started_at = last_activity_at = updated_at = 2026-08-27T19:07:15，不再推进）；2026-08-27 20:18:33 process check（AAF_TASK004_PROCESS_CHECK.txt）：无任何相关 TASK-004 runner 进程、Bridge 进程亦不存在；canonical RUNNING 未被自动对账 / 回收（该 run 的 runner 进程在 E2E 前由 cleanup.py 清理，task.json 只读保留未改）。<br><br>Phase D UI suspected-stuck（bridge/stuck.py，仅观察提示）**不解决 RW-020**：它只提示「任务可能已停滞」，不做 ownership / process liveness 检测、不做 canonical 对账；RW-020 完整协议（liveness 跟踪、staleness + artifact expectation、Resume / Diagnostics / Resolve UX）仍未实现。 |
| Problem | RUNNING 目前只表达 lifecycle state，不能证明 execution owner / runner / 当前 agent 仍存活。 |
| Desired Behavior | 未来 AAF Runtime Health / Desktop Shell 应区分 **Lifecycle State** 与 **Runtime Health**。至少检测可疑组合：task.status=RUNNING + runner ownership/process missing + 当前 agent process missing + last_activity_at stale + expected result artifact missing，并提示「任务可能已异常中断」。潜在用户动作：Resume Task / View Diagnostics / Resolve or Mark Failed（通过权威 lifecycle 路径）。 |
| Important Boundary | Runtime Health detection **不得**允许 Desktop Shell / UI 独立写入权威 terminal task state。例：canonical lifecycle=RUNNING、runtime health=PROCESS_MISSING / STALE、UI=warning only；Terminal authority 保持 Core / Lifecycle（遵循既有 Safe Cancel / recovery 架构）。 |
| Current Implementation | 无 runtime health 检测；RUNNING 无 liveness 语义。 |
| Remaining Gap | - runner ownership / process liveness tracking<br>- agent process liveness<br>- last_activity_at staleness threshold<br>- expected artifact expectation (result file) check<br>- 「任务可能已异常中断」warning 呈现<br>- Resume / Diagnostics / Resolve UX（warning only，不改 terminal authority） |
| Decision | 当前只登记（本维护任务不实现）。近期待办 P1。 |
| Target | Desktop Shell（或等价 Runtime Health 层）能区分 lifecycle 与 health；stale / dead runner 能预警；恢复走既有 resume / authoritative lifecycle。 |
| Related | RW-005（阶段耗时）、RW-006（Runtime 状态可视化）、RW-012（hotkey listener runtime reliability）、RW-014（Task Stop / Cancel） |
| Do Not Forget | **RUNNING ≠ alive**。运行时健康与生命周期终态权威必须分离；UI 只能 warning，不能写终态。 |

---

## RW-021 — Bridge Restart / Exit Completion Notification Continuity

| 字段 | 内容 |
|---|---|
| ID | RW-021 |
| Title | Bridge Restart / Exit Completion Notification Continuity |
| Category | Bridge lifecycle / Runtime UX / Completion notification |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | AAF-v0.4-TASK-002-FIX-001 real Windows validation, 2026-08-27。真实验收中主动执行了 Bridge Restart / Exit / restart：Framework runner / validation task 可以继续运行并最终生成 SUCCESS REPORT，但启动该 task 的原 Bridge instance 被 Restart / Exit 后，新 Bridge instance 不会自动恢复原 launcher wait-thread / completion callback，用户没有收到原有「任务完成」提示 / Planner Handoff copy action，只能手工发现 REPORT.md。<br><br>2026-08-27 再次复现（AAF-v0.4-TASK-003）：Phase C E2E 过程中 Bridge 被正常切换/重启后，runner / task 最终完成并产生 REPORT，但用户未收到 completion notification / Planner Handoff copy action（与既有登记一致，仅补充事实，未重复新建 issue）。<br><br>2026-08-27 第三次真实复现（AAF-v0.4-TASK-004 Phase D）：Phase D 真实 Windows E2E 全链路完成后，最终 REPORT 已成功生成（.aaf/AAF-v0.4-TASK-004/REPORT.md，SUCCESS，mtime 20:03:04），但 E2E 流程中 Bridge 经历 Exit / Restart，用户未收到最终 completion window / Planner Handoff copy action，只能从文件系统手工取回 REPORT.md（与既有登记一致，仅补充事实，未重复新建 issue）。 |
| Scenario | Bridge instance A 启动 Framework task → Framework runner 独立继续运行 → Bridge A 被 Restart / Exit → Bridge instance B 启动 → runner 最终正常完成并生成 REPORT → Bridge B 不持有原 launcher completion callback → 用户没有收到完成通知 / Planner Handoff copy action |
| Current Implementation | Launcher completion callback / wait-thread 属原 Bridge process 内存；Bridge restart 后新 instance 不会重新关联旧 in-flight runner。 |
| Problem | Framework execution success 和用户 completion notification 是两个不同事实：REPORT 已成功生成 ≠ 用户一定收到完成提示。任务产物完整（canonical task / REPORT 最终 SUCCESS），但用户侧 notification continuity 丢失。 |
| Not RW-020 | RW-020 = RUNNING 状态残留，但 runner / agent 已死亡（Dead Runner / Orphaned RUNNING）。本问题 = runner 仍然存活并成功完成，但 Bridge 换代后 completion notification continuity 丢失。两者是不同的失败模式，不合并、不互相覆盖。 |
| Important Boundary | 这不是 task lifecycle corruption：canonical task / REPORT 可以最终 SUCCESS，缺失的是 Bridge-side observation / reattachment / notification continuity。不允许 UI 自行修改 canonical terminal state。 |
| Remaining Gap | - Bridge restart 后发现 in-flight task<br>- 完成后恢复 notification<br>- Planner Handoff / REPORT availability 提示<br>- 与未来 launch ownership / persistent registry 架构保持一致（设计 §6B.11–§6B.16 Bridge launch registry / §15 Phase E）<br>- 不重复实现 Core lifecycle |
| Decision | 当前只登记。不重开 Phase B。不得在本任务实现 reattachment。<br>**AAF-v0.4-TASK-009 necessity check（2026-08-29）**：A. 仍可复现/当前（真实复现 3 次，未修复）；B. 与 RW-012 **不同 lifecycle owner / 不同根因**（RW-012 = listener 线程健康；本项 = launcher 内存 wait-thread completion callback 跨 Bridge 换代丢失）；C. **非最小改动**（需新 reattachment / notification recovery 机制，被 TASK-009 明确禁止）。→ **DEFERRED / OPEN P2，v0.4 freeze 显式 non-blocking**。<br>**AAF-v0.4-FINAL-ACCEPTANCE-002（2026-08-29）**：确认 DEFERRED / OPEN P2 分类，无新 blocking evidence，v0.4 non-blocking。 |
| Target | Bridge 换代（Restart / Exit / relaunch）后仍能发现 in-flight task，并在其完成后恢复 completion notification / Planner Handoff / REPORT availability 提示。 |
| Related | RW-020（明确区分，见上）、RW-014（Task Stop / Cancel）、RW-016（Duplicate Task Status UX）；设计文档 `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md` §6B（launch registry / ownership 恢复协议）、§7（Bridge Background Runtime）、§15（Phase E Safe Cancel Lifecycle）——仅引用未来架构关系，不提前实现 Phase E |
| Do Not Forget | Framework execution success 和用户 completion notification 是两个不同事实。REPORT 已成功生成 ≠ 用户一定收到完成提示。 |

---

## RW-022 — Framework Final Status Aggregation: PASS_WITH_WARNING + APPROVE + Blocking NONE → WAITING

| 字段 | 内容 |
|---|---|
| ID | RW-022 |
| Title | Framework Final Status Aggregation: PASS_WITH_WARNING + APPROVE + Blocking NONE → WAITING |
| Category | Framework lifecycle / Report aggregation / Planner handoff semantics |
| Status | **SOLVED**（Runtime Integrity batch / AAF-v0.4-TASK-007 交付，2026-08-28：`_aggregate_status` / `build_report` 聚合改为 structured-first——`<agent>_result.json` 的 `blocking_rework`（Agent 显式声明）优先于 narrative 关键词猜测；narrative fallback 保留且 fail-safe（空结果 / FRAMEWORK_ERROR / FAILED / FAIL / REQUEST_CHANGE 仍阻断，不 fail-open）；`verdict_blocked` FAILED 分支增加 reviewer 通过结论逃逸（PASS_WITH_WARNING / APPROVE 正文的历史 FAILED 引用不再误阻断）；20 项聚合回归（A–G 全场景）+ 真实 runner 运行时验证：PASS_WITH_WARNING + APPROVE + blocking NONE → REPORT Current Status = SUCCESS 且 warning 内容保留；真阻断（REQUEST_CHANGE / 缺失 / FRAMEWORK_ERROR）→ WAITING 不变；历史 REPORT 不重写——只修未来聚合行为）。<br><br>FIX-001（AAF-v0.4-TASK-007-FIX-001，2026-08-28：关闭 Codex 三个同根 blocker）——① blocking provenance：`<agent>_result.json` 新增 `blocking_provenance`（structured / framework / narrative），narrative keyword 推断不再伪装成 structured authoritative fact（权威路径仅 COMPLETE + provenance=structured；旧 artifact 缺字段按 agent 推断：reviewer COMPLETE → structured、hermes → narrative，防 narrative 洗白）；② fail-closed aggregation 优先级：Framework hard failure（required result 缺失/空、FRAMEWORK_ERROR、invalid structured blocking data（blocking_rework 非 bool））> explicit blocking structured verdict > explicit non-blocking structured verdict > legacy fallback；COMPLETE 标签不得覆盖 execution validity；③ Hermes narrative 技术性 FAILED/failure/error 词语不再误判 WAITING——只认显式失败判定形态（`**Result: FAILED**` / 行首 `FAILED:`/`FAIL:`/`REQUEST_CHANGE:`）；legacy narrative-only 保持 backward compatible 且不 fail-open；新增 28 项回归测试（Req A–H 真实组合 + provenance 完整性）；867 passed（839 基线 + 28 新增，零下降）；RW-020 保持 SOLVED 零改动）。<br><br>FIX-002（AAF-v0.4-TASK-007-FIX-002，2026-08-28：Fresh-Process Provenance Closure）——① provenance authority 改为 schema 驱动 / explicit field：reviewer 结构化块新增可选 `blocking_provenance`（structured/framework/narrative），structured authority 只来自**显式声明**的合法值；`blocking_rework` key 存在性 / COMPLETE 标签不再推断 structured（build_stage_result 与 read_structured_blocking 同步移除旧推断；legacy 缺字段 → narrative，backward compat，不 laundering）；② invalid provenance（类型/值非法）→ invalid structured result → fail closed（blocking_rework=True / provenance=framework / MALFORMED；schema 放行、build_stage_result 统一判定，避免 schema 静默降级）；③ `git_changed_files` 过滤 PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs`，`-uall` 逐文件判定），stage changed_files 不再被 untracked 污染（Req 8）；④ reviewer prompt 契约显式要求声明 blocking_provenance（adapters._structured_contract_block）；⑤ 优先级保持：Framework hard failure > explicit structured blocking > explicit structured non-blocking > legacy narrative fallback；FRAMEWORK_ERROR / 缺失 / 空 / invalid structured → fail closed 不变；Hermes 技术性 FAILED → non-blocking 不变；PASS_WITH_WARNING + APPROVE + no blocking → SUCCESS 不变；⑥ fresh-process 验证：全新 python 进程 16 项 A–H 场景矩阵全 PASS + Parent（FIX-001）历史 artifacts SHA-256 基线复核零改写（基线记录 `.aaf/AAF-v0.4-TASK-007-FIX-002/parent_hashes_record.txt`）；886 passed（867 基线 + 19 新增：18 项 FIX-002 A–H/单元 + 1 项 key-existence 语义回归，零下降）；RW-020 零改动无回归；self-hosting observation（Req 10）已登记：runner process 用启动时加载的旧代码生成同一 TASK 的后续 runtime artifacts（本任务 runner 启动早于本次 commit），新实现以 fresh-process 证据验证，不开发 hot reload；RW-022 = SOLVED / AAF-v0.4-TASK-007 = CLOSED / Runtime Integrity = CLOSED 正式判定留待 WorkBuddy no blocking rework + Codex APPROVE + Remote Sync SYNCED 后由 Planner 确认） |
| Priority | P1 |
| Evidence / Origin | AAF-v0.4-TASK-003 real execution, 2026-08-27。最终 REPORT 顶部 Current Status = WAITING，但：Hermes implementation SUCCESS、Tests 284 passed、WorkBuddy PASS_WITH_WARNING（blocking rework: NONE）、Codex APPROVE（Blocking Issues: NONE）、Scope Leakage: NONE、Remote Sync: SYNCED、Codex Recommended Phase C Status = COMPLETE。<br><br>同类顶部 WAITING 先前已出现于 AAF-v0.4-TASK-002（Phase B）REPORT（当时 Codex closure review 在 REPORT 生成时点尚未完成，属可解释实例）；Phase C 为更干净的反例：全部 Agent 均已完成且无 blocking，顶部仍聚合为 WAITING。 |
| Observed Behavior | - Hermes implementation success（284 passed）<br>- WorkBuddy PASS_WITH_WARNING（无 blocking rework）<br>- Codex APPROVE / Blocking Issues NONE<br>- Scope Leakage NONE / Remote Sync SYNCED<br>- 但最终 REPORT 顶部 Current Status = WAITING |
| Problem | Framework final status aggregation 疑似把 warning / unresolved 文本段当作 blocking 处理：即使 reviewer 明确报告 no blocking rework / no blocking issues，只要存在非阻断 warning 文本，顶部状态仍被聚合为 WAITING。WAITING 因此无法表达「确实需要后续处理」与「有非阻断 warning 的 SUCCESS」的区别，会误导 Planner / user 认为需要干预。 |
| Desired Behavior | Final task status aggregation 应区分：<br>A. Blocking rework：FAIL / REQUEST_CHANGE / unresolved blocking issue / execution failure<br>B. Non-blocking warning：PASS_WITH_WARNING / informational warning / recommendation / documentation blemish<br>当最终 reviewer 明确 APPROVE 且 blocking issues = NONE 时，非阻断 warning 不应自动强制顶部 WAITING。目标：Planner / user 能区分「SUCCESS with warnings」与「WAITING（确实需要后续处理）」。 |
| Important Boundary | 本登记不修改 lifecycle semantics、不修改 task terminal state、不重写历史 REPORT；aggregation fix 属 Framework Core 变更，须由 Planner 立项，不在此登记任务中实现。 |
| Current Implementation | 无；最终 REPORT 顶部状态由 Framework aggregation 生成，当前将非阻断 warning 亦聚合为 WAITING。 |
| Remaining Gap | Framework REPORT aggregation 层需区分 blocking / non-blocking 类别，并据此决定顶部状态（属 Framework Core 变更）。 |
| Decision | 当前只登记（本 closure sync 任务不实现 aggregation fix）。 |
| Target | 最终 REPORT 顶部状态：SUCCESS（含 PASS_WITH_WARNING 且无 blocking）≠ WAITING（确实需要后续处理）。WAITING 应表达「需要后续处理 / 尚未闭环」，而不是「存在任意 warning 文本」。 |
| Related | RW-019（Agent review evidence consistency）、RW-021（completion notification continuity，同为 REPORT 生成 ≠ 用户闭环的语义区分）；AAF-v0.4-TASK-002（Phase B）为同现象早期实例 |
| Do Not Forget | 本次顶部 WAITING 不是 Phase C implementation failure；不得据此重开 Phase C、不得改写历史 REPORT、不得手动改写 task terminal state。 |

---

## RW-023 — E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop

| 字段 | 内容 |
|---|---|
| ID | RW-023 |
| Title | E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop |
| Category | Validation orchestration / GUI automation / test harness |
| Status | OPEN |
| Priority | P2 |
| Evidence / Origin | AAF-v0.4-TASK-004（Phase D）真实 Windows E2E，2026-08-27（.aaf/AAF-v0.4-TASK-004/e2e_phase_d.py）。GUI E2E 使用**固定** validation Task ID：`AAF-v0.4-TASK-004-E2E`（脚本常量 TASK_ID，第 46 行）。重复 validation 时驱动自身预删 active task 文件与证据目录（`TASK_FILE.unlink()` + `shutil.rmtree(OUT_DIR)`，注释明确为「清理陈旧产物…避免 TASK_ALREADY_EXISTS / 误报」）；热键触发走 attempt 1..3 重试循环，并对「任务已在执行」（duplicate guard 弹窗）等 blocker 弹窗反复关闭后重试。本次运行 attempt=1 即成功（未出现真实 destructive loop），但代码路径完整具备：固定 ID 复用 → duplicate guard 正确拒绝 → automation 仍可能继续重开 Bridge 菜单 / 状态窗口 / 重试热键 → 用户看到鼠标 / 焦点被抢占；同时 `rmtree(OUT_DIR)` 使同一 E2E task 的旧证据被覆盖（.aaf/AAF-v0.4-TASK-004-E2E/ 仅保留最后一次运行产物），artifact / report provenance 混淆。 |
| Problem | GUI E2E 使用固定 validation Task ID，重复验证时：duplicate guard 正确拒绝重复（预期行为），但 automation 可能继续 GUI loop（重开 Bridge menu / status window / re-trigger hotkey）；用户看到 mouse/focus hijacking；artifact/report provenance 变得模糊；同一 E2E task 证据可能被覆盖 / 重写。 |
| Desired Behavior | 每次 GUI E2E 应：使用**唯一** validation Task ID（如时间戳 / 运行号后缀），或检测到已完成 validation 后**安全跳过**；automation 必须有明确终止条件；duplicate rejection 后不得继续 GUI loop。 |
| Current Implementation | Phase D E2E 脚本 e2e_phase_d.py 当前用固定 ID + 预删陈旧产物 + 有限重试（attempt ≤ 3）规避；无唯一 ID 机制、无「已完成则跳过」机制。 |
| Remaining Gap | - 唯一 validation Task ID 生成<br>- 已完成 validation 检测与安全跳过<br>- automation 明确终止条件<br>- duplicate rejection 后停止 GUI loop |
| Decision | 本任务只登记，不实现修复（E2E orchestration 属 test harness 改进，须由 Planner 立项）。 |
| Target | 重复 GUI E2E 验证不会产生 duplicate trigger / GUI loop / 证据覆盖。 |
| Related | RW-016（Duplicate Task Status UX——面向最终用户的 duplicate 提示状态缺口，属产品 UX，非测试 harness 编排，不合并）；RW-019（Agent review execution evidence consistency——重复验证证据 provenance 的相邻观察）。 |
| Do Not Forget | duplicate guard 本身正确拒绝是**预期行为**；问题在 harness 复用固定 ID + 无终止条件导致的 loop 与证据覆盖，不在 Framework lifecycle。 |

---

## RW-024 — Completion Dialog Copy Report UX（复制报告二次弹窗 + Z 序问题）

| 字段 | 内容 |
|---|---|
| ID | RW-024 |
| Title | Completion Dialog Copy Report UX（复制报告后二次弹窗 + Z 序问题） |
| Category | Runtime UX / Bridge / Completion dialog |
| Priority | P2 |
| Evidence / Origin | 用户明确反馈（2026-08-27，Phase D 期间）。**历史行为**（bridge/main.py `_copy_last_report()`）：任务完成 → 弹出第一个完成窗口 → 点击「复制报告」→ `ui.show_info("报告已复制", …)` 再弹出第二个提示窗口 → 第二窗口可能落在第一个窗口后面 → 点确定后两个窗口一起关闭。该行为已由 AAF-v0.4-TASK-008（2026-08-28）修复。 |
| Problem | 完成通知被拆成两个 modal：复制动作触发第二个弹窗，与主完成窗口存在 Z 序竞争；用户看到两个窗口叠在一起，点确定后两个一起关闭。 |
| Desired Behavior | 任务完成 → 只保留一个完成窗口。按钮：[复制报告] [关闭]。点击「复制报告」：复制到剪贴板、不弹第二个 modal、不关闭主完成窗口、可在原窗口显示轻量反馈「已复制 ✓」、可重复复制；只有主动点击「关闭」才关闭完成窗口。 |
| Current Implementation | （2026-08-28 完成态）单完成窗口：`show_finished` 内 [复制报告] [关闭]。点击「复制报告」→ `_copy_last_report()` 构建 handoff + 写剪贴板（返回 bool）→ 窗内就地反馈：成功时按钮临时变「已复制 ✓」，`COPY_FEEDBACK_MS`（1500ms）后经 Tk `after()` 自动恢复「复制报告」（重复复制刷新计时器；窗口已关闭时回调安全跳过）；失败时窗内显示「复制失败」；全程不弹第二 modal、主窗口保持打开；仅「关闭」/WM_DELETE_WINDOW 显式退出。 |
| Remaining Gap | **NONE**（RW-024 无 blocking gap；原「单窗 UX 改造：合并按钮、就地反馈、关闭语义唯一」为登记期历史待办，已由 TASK-008 / TASK-008-FIX-001 完成）。 |
| Decision | 实施完成：采用单窗 + 窗内临时反馈方案（AAF-v0.4-TASK-008 主体实现，TASK-008-FIX-001 补「已复制 ✓」临时恢复语义并将 backlog 对齐完成态）；不再保留「只登记，不实现」登记态。 |
| Status | **SOLVED**（AAF-v0.4-TASK-008 交付，2026-08-28：完成窗口单窗 UX——`show_finished` 点击「复制报告」只执行复制并在窗内就地反馈（按钮变「已复制 ✓」/ 窗内「复制失败」），不再弹第二 modal、不关闭主窗，仅「关闭」/窗口关闭按钮退出；`_copy_last_report` 返回 bool，handoff 构建与剪贴板写逻辑不变；新增 9 项 mocked/unit-level Tk 测试覆盖成功/重复/关闭/失败全路径 + Bridge 复制逻辑回归；FIX-001 收尾（2026-08-28）：成功反馈临时化——「已复制 ✓」1.5s 后自动恢复「复制报告」，重复复制刷新 after 计时器，窗口提前关闭时回调安全（winfo_exists 守卫，不抛异常、不重建窗口）；backlog Current Implementation / Remaining Gap / Decision 对齐完成态；新增计时恢复/重复刷新/关闭安全/backlog 一致性测试） |
| Target | 完成通知单窗口：复制不弹新 modal、不关主窗、原地轻量反馈；仅「关闭」按钮关闭。 |
| Related | 与 RW-021（completion notification continuity——Bridge 换代后「通知是否送达」的连续性缺口）**明确区分**：RW-024 是「通知窗口自身交互」的 UX 缺陷；与 RW-023（E2E orchestration）无关；与 RW-016（duplicate 状态 UX）无关。 |
| Do Not Forget | 不合并到 RW-021 / RW-016 / RW-023；属独立 completion dialog UX 条目。 |

---

## RW-025 — Session Continuity Clock Flake（test_first_rollover_generates_files 秒级时钟边界）

| 字段 | 内容 |
|---|---|
| ID | RW-025 |
| Title | Session Continuity Clock Flake（test_first_rollover_generates_files 秒级时钟边界） |
| Category | Tests / Session Continuity |
| Status | OPEN |
| Priority | P3 |
| Evidence / Origin | AAF-MAINT-CONTEXT-001 全量跑测观察（2026-08-28）：`tests/test_session_continuity.py::test_first_rollover_generates_files` 偶发失败——`session_id()` 使用 `datetime.now()`，两次调用落在不同秒即失败；全量连跑 3 次仅 1 次出现，隔离复跑通过；该文件未被 AAF-MAINT-CONTEXT-001 / FIX-001 改动 |
| Problem | 秒级时钟边界 flake：同一测试内两次取当前时间跨秒 → 断言失败；属测试环境问题，非产品缺陷 |
| Current Implementation | 无（未修复；本任务明确不处理，仅登记） |
| Remaining Gap | 需要 freeze / monotonic 时钟或跨秒容错断言 |
| Decision | 仅登记为后续维护项，不实现（AAF-MAINT-CONTEXT-001-FIX-001 范围外） |
| Target | 后续维护任务引入确定性时间（freeze / monotonic）后关闭 |
| Do Not Forget | 修复时不得改变 session rollover 语义；与产品行为无关，纯测试时钟边界 |

---

## RW-026 — Automated pytest 弹出真实桌面 Bridge modal（FIX-UI-A-001；GUI E2E 未结构性排除）

| 字段 | 内容 |
|---|---|
| ID | RW-026 |
| Title | Automated pytest 弹出真实桌面 Bridge modal（FIX-UI-A-001；GUI E2E 未被普通 automated suite 结构性排除） |
| Category | Tests / GUI automation / test isolation |
| Status | **SOLVED**（AAF-v0.4-TASK-010-FIX-001 交付，2026-08-29） |
| Priority | P1 |
| Evidence / Origin | AAF-v0.4-TASK-010 全量 pytest 运行期间（2026-08-29），真实桌面弹出「任务已存在 — AAF Bridge」modal（Task ID: FIX-UI-A-001，REPORT 路径位于 C:\\Users\\Admin\\AppData\\Local\\Temp\\pytest-of-Admin\\pytest-742\\…），等待人工关闭。根因定位：① tests/test_phase_f_fix_001_ui.py 故意驱动真实桌面窗口（真实 Tk Toplevel + grab_set + wait_window + 真实剪贴板 + 真实按钮 invoke，TASK-006-FIX-001 设计如此）；② 仓库无 pytest 配置文件，普通 automated suite **无结构性排除机制**（TASK-009-FIX-005 曾人工排除该文件，TASK-010 未排除 → 全量跑时真实弹窗）；③ harness（_find_window）只处理预期窗口标题，状态偏差（如 duplicate 卡片「任务已存在」代替切换确认窗）时 poll 超时、断言失败、真实窗口滞留桌面等待人工关闭 |
| Problem | 普通 automated/unit/integration 测试弹出真实需要人工点击的 modal（task exists dialog / project switch confirmation / messagebox / Tk Toplevel requiring user action）；测试失败时窗口无人关闭、阻塞真实用户桌面；真实剪贴板被测试改写 |
| Desired Behavior | 所有普通 automated 测试零真实桌面 modal、零真实剪贴板；真实窗口测试明确归类为 manual/GUI E2E 并从默认 suite 排除；pytest 临时状态与真实 Bridge 用户状态隔离；无人值守执行不被阻塞 |
| Current Implementation | （2026-08-29 完成态）① pytest.ini 登记 `gui_e2e` marker + `addopts = -m "not gui_e2e"`：默认 suite 结构性排除真实窗口测试；② tests/test_phase_f_fix_001_ui.py 标记 `pytestmark = pytest.mark.gui_e2e`（docstring 注明手动运行方式 `pytest -m gui_e2e tests/test_phase_f_fix_001_ui.py`）；③ 新增 tests/test_bridge_ui_headless.py（7 项）：headless 对话框 stub + 进程内剪贴板 + tmp config/registry，驱动真实 `Bridge._handle_hotkey → _process_clipboard → intake → apply → launcher` 主链路，覆盖已知切换确认/拒绝/无效拒绝/duplicate RUNNING/TERMINAL/跨 workspace 拒绝/热键冲突零 modal；④ 热键冲突路径确认已隔离（RW-012 测试用 StubRoot + fake HotkeyListener 工厂 + patched ui.show_error，断言 shown==[]，零真实 RegisterHotKey/零真实 messagebox） |
| Remaining Gap | NONE（FIX-UI-A-001 类：默认 suite 零真实 modal；manual GUI E2E 文件保留但明确排除）。未来新增真实窗口测试必须打 gui_e2e 标记或提供 headless 等价覆盖 |
| Decision | 采用「结构性排除 + headless 等价覆盖」：不为测试修改产品行为语义（产品 UI 弹窗不变）；真实窗口验收测试保留为 manual/GUI E2E |
| Target | 任何 pytest 运行（含无人值守 CI/全量）不再弹出需要人工关闭的真实桌面窗口 |
| Related | RW-023（Phase D E2E 脚本固定 Task ID 复用 —— 同类「E2E 自动化 vs 真实 GUI」边界，但属独立 orchestration 脚本，不合并）；RW-016（duplicate 状态 UX，产品功能，不合并） |
| Do Not Forget | 不得把产品 UI 弹窗行为改为「测试模式」；隔离只发生在测试层（stub/headless/marker） |

---

## RW-027 — WorkBuddy Stage Reliability / Bounded Transient Retry（gateway/CLI transient 失败一次即终止整条 task）

| 字段 | 内容 |
|---|---|
| ID | RW-027 |
| Title | WorkBuddy Stage Reliability / Bounded Transient Retry |
| Category | Framework execution reliability / WorkBuddy transport layer |
| Status | **SOLVED**（AAF-v0.4-TASK-011 交付 + FIX-001 收口 + **FIX-002 关闭最后一个 blocking defect**，2026-08-29；confirmed-dead-before-retry + single absolute stage deadline + **Windows tree cleanup authority + safe cleanup reserve minimum + attempt admission control** 全量落地、implementation + 测试通过（1289 passed / 1 skipped / 9 deselected）；独立 WorkBuddy 验证 + Codex 审查通过；Final Acceptance PASS（AAF-v0.4-FINAL-ACCEPTANCE-002，2026-08-29）确认 SOLVED 状态） |
| Priority | P1 |
| Evidence / Origin | freeze 前连续真实复现：CLOSURE-002（codebuddy exit=0 + 空 stdout + stderr「Empty stream: upstream gateway sent only placeholder chunks without any model output (chunks=1, bytes=748)」，Framework 正确 FRAMEWORK_ERROR，Codex 未运行，任务停 WAITING）；CLOSURE-003（codebuddy 单次 subprocess.run(timeout=3600) 挂死至 TimeoutExpired，真实 1 小时等待）。根因：WorkBuddy stage 只有单次 subprocess.run(timeout=3600)，无 transient recovery 层 |
| Problem | 一次 gateway/CLI transient failure（placeholder-only 输出 / 超时）直接终止整条 Framework task：required validator 无有效结果 → Codex 不运行 → 无人值守任务停在 WAITING；且固定 3600s 硬等待造成长静默 |
| Current Implementation | （2026-08-29 FIX-001 完成态）`ai_agent_framework/workbuddy_retry.py`：① failure classification 只基于真实 CLI evidence——RETRYABLE_TRANSIENT = TimeoutExpired / exit=0+空输出 / stderr 含 gateway placeholder-only 证据；NON_RETRYABLE = missing executable / 非零退出无 transient evidence（auth/config/CLI fatal）/ spawn 失败 / **cleanup failure（terminated_confirmed=False → `WorkBuddyCleanupError` fail closed，绝不降级为 TimeoutExpired 重试）**；② WorkBuddy-only bounded retry：initial + 1 retry（`AAF_WORKBUDDY_MAX_ATTEMPTS` 可配），每次 attempt 复用同一 invocation（same agent / same current model & default config / same prompt / same workspace / same role，绝不换模型/provider/付费层级）；③ per-attempt timeout 默认 900s（实测成功 stage ~556s，留余量；`AAF_WORKBUDDY_TIMEOUT` 可配）替代统一 3600s；④ **single absolute stage deadline**：`stage_deadline = stage_start + overall_stage_budget`（`AAF_WORKBUDDY_STAGE_BUDGET` 可配），attempt / backoff / taskkill wait / kill grace / communicate reap 全部从同一 deadline 派生并被裁剪；⑤ bounded backoff 默认 30s（`AAF_WORKBUDDY_BACKOFF` 可配）；⑥ timeout → Windows `taskkill /PID /T /F` 整树杀 + final liveness check（必须观察到 poll() 非 None）+ 有界管道排空，返回结构化 `CleanupResult`（terminated_confirmed / reaped_confirmed / method / failure_reason）；**confirmed-dead-before-retry**：终止确认才注销 registry（不再无条件 finally 注销），未确认 → child 保持注册 + fail closed（Registry Gate 防任何后续 spawn，绝不并发双 CodeBuddy）；**cleanup_reserve**（默认 60s，`AAF_WORKBUDDY_CLEANUP_RESERVE` 可配）保证 attempt timeout ≤ remaining − reserve（有界清理窗口，不因清理超出 budget）；⑦ 有效输出（含业务 FAIL verdict）立即停止 retry，verdict 归 Framework authority（structured result / blocking provenance / fail-closed 语义不变）；⑧ retries 用尽 / budget 不足 → `WorkBuddyRetriesExhausted`（fail closed → FRAMEWORK_ERROR 带完整 attempt 历史 → Codex 不运行 → WAITING）；⑨ attempt telemetry（`workbuddy_attempts.json` machine artifact：attempt_count / 每 attempt 状态/类别/原因/超时/退出码/耗时/stderr tail / **cleanup_confirmed / cleanup_failure / cleanup_method / cleanup_reason** / stage 总墙钟 / **stage_deadline_monotonic / cleanup_reserve / retry_suppressed_reason**）+ stage result `execution_retries` 摘要 + REPORT Model Observation 行 `attempts=N`（仅 retried 时）；⑩ 测试全 mocked/fake CLI（零真实 gateway/积分消耗），矩阵 A–K + CLOSURE-002/003 双 incident regression + FIX-001 清理失败/硬 budget 定向 12 项（22A–E / 23A–E / 24）+ 真实 python child 超时清理（Windows tasklist 验证无 orphan）+ runner 集成（Codex gating 正负）共 54 项新测试；全量 non-GUI 1289 passed / 1 skipped / 9 deselected（FIX-002 后全量复跑验证）；**FIX-002（2026-08-29）Windows tree cleanup authority**：⑪ **Windows 上 cleanup 成功必须基于足够强的 process-tree evidence**——taskkill /T /F 实际尝试且成功（或等价强证据）+ 顶层确认退出 + reap 完成/明确分类；只 kill 顶层成功（或只观察顶层 poll() != None）**不是** safe cleanup（no fake tree success）；tree 未确认 → cleanup safety=UNKNOWN/FAILED → `WorkBuddyCleanupError` fail closed、绝不 retry、child PID 保持注册（Registry Gate）；⑫ **safe cleanup reserve minimum（Option B: clamp）**：`MIN_SAFE_CLEANUP_RESERVE=60s` 硬下限，`load_workbuddy_policy` 把 `AAF_WORKBUDDY_CLEANUP_RESERVE=0/过低值` 钳制到 60s（用户配置不得关闭 tree safety）+ orchestrator admission 二次兜底 `effective_reserve = max(cleanup_reserve, MIN_SAFE_CLEANUP_RESERVE)`（直接构造 policy 传低值也无法破坏）；⑬ **attempt admission control**：每次 attempt 启动前确认 remaining budget > effective safe cleanup reserve + minimum useful attempt runtime（`MIN_ATTEMPT_RUNTIME`），不足 → 不启动、fail closed（cleanup budget 在 attempt 启动前就保留，不是 deadline 耗尽后才发现没时间安全 kill tree）；⑭ deadline 耗尽 → taskkill 无窗口（skipped）→ 顶层 kill 成功 ≠ tree confirmed → cleanup failure fail closed；taskkill 失败 + fallback kill 顶层成功同样 ≠ tree confirmed（无 retry）；taskkill 成功 + 顶层确认退出 = tree confirmed（retry 允许）；⑮ telemetry 新增 `cleanup_tree_confirmed / taskkill_attempted / taskkill_success / cleanup_reserve_effective`；⑯ 非 Windows 语义保持（kill 确认即安全；平台差异显式） |
| Remaining Gap | NONE（transport retry 层完成）。注意：自动切换模型 / 更贵模型 / Cost Gate / Model Routing 均 NOT IMPLEMENTED（属未来 Model Routing 阶段，本任务明确禁止） |
| Decision | 采用「WorkBuddy-only 有界同 invocation transient retry + 进程清理 + telemetry」；Hermes/Codex 不自动获得 retry（`AAF_WORKBUDDY_RETRY=0` 可整体关闭） |
| Target | 一次 gateway/CLI transient failure 不再直接终止整条 task；总墙钟有最终上限；重复失败可诊断 |
| Related | RW-007（Agent executable discovery reliability——MISSING_COMMAND 仍永久失败不重试）；CAP-003（Future Model Routing，NOT IMPLEMENTED） |
| Do Not Forget | retry 属于 transport execution 层；业务 FAIL 绝不触发「再回答一次」；任何时刻最多一个 CodeBuddy 进程 |

---

## RW-028 — pythonw 早期校验失败 UI 只显示 exit=2（TaskValidationError 不可见）

| 字段 | 内容 |
|---|---|
| ID | RW-028 |
| Title | pythonw 早期 validation failure UI 仅显示 enter=2，具体 TaskValidationError 不可见 |
| Category | Real-world usage / UX（诊断可观察性） |
| Status | OBSERVATION（仅登记，不实现——AAF-v0.4-TASK-011 Requirement 24 明确不扩大 scope） |
| Priority | P2 |
| Evidence / Origin | AAF-v0.4-TASK-010-CLOSURE-001：TASK 文本误含两个显式 Route 字段触发 task_validation fail-closed，runner 在 validation 阶段以 exit=2 退出；Bridge pythonw 环境只显示 enter=2，具体 TaskValidationError 原因（duplicate Route）不可见，需人工读日志 |
| Problem | 早期 validation 失败（exit=2）在 GUI 宿主中不可诊断；用户不知道 TASK 哪里写错 |
| Current Implementation | 无（本任务不实现该 UX） |
| Remaining Gap | 需要把 validation 失败原因（TaskValidationError 文本）带到 Bridge UI/通知 |
| Decision | 登记为后续 UX 改进项；不得扩大当前 TASK-011 scope 去实现。<br>**AAF-v0.4-FINAL-ACCEPTANCE-002（2026-08-29）**：确认分类 = DEFERRED P2 diagnostics UX / non-blocking（validation fail-closed 正确性已确认，缺口仅为 TaskValidationError 可见性）。 |
| Target | 后续 UX 任务：validation 失败时 UI 显示具体错误（如 duplicate Route / missing field） |
| Do Not Forget | 该事项持续记录在 Final Acceptance checklist；实现时不得改变 validation fail-closed 语义 |

---

## RW-029 — Windows 全量 pytest 环境 0x80000003 观察（test-environment observation）

| 字段 | 内容 |
|---|---|
| ID | RW-029 |
| Title | Windows 全量 pytest 环境偶发 0x80000003（测试环境观察，非产品 runtime 缺陷） |
| Category | Tests / Test environment observation |
| Status | **OBSERVATION**（AAF-v0.4-FINAL-ACCEPTANCE-002 分类：DEFERRED / NON-BLOCKING test-env observation，2026-08-29） |
| Priority | P3 |
| Evidence / Origin | 2026-08-29 Windows 全量 pytest 环境（既有 non-GUI pytest / Bridge 残留线程环境）曾出现 0x80000003。隔离证据未指向本次变更；当前无证据证明正常生产 AAF runtime 必然受影响。 |
| Problem | 测试环境层面偶发 0x80000003（残留线程 / 调试器干扰 / 环境因素候选）；不是 Framework implementation regression |
| Current Implementation | 无（未修复；仅登记） |
| Remaining Gap | 需在测试环境层面定位（残留线程 / Windows 调试器 / 其他环境因素），不属于产品 runtime 缺陷 |
| Decision | 只登记为 DEFERRED / NON-BLOCKING observation；不扩大 v0.4 freeze scope。除非 repository 证据表明产品 runtime 受影响，否则不升级、不因该观察重开 v0.4 或启动新开发线 |
| Target | 后续维护任务在测试环境层面调查（如线程残留 / 调试器干扰 / 全量 suite 隔离） |
| Do Not Forget | 该观察不构成 v0.4 correctness blocker；与 RW-025（时钟 flake）同类：测试环境观察 ≠ 产品缺陷 |

---

## RW-030 — Hermes FREE 标记模型不可用/不稳定（user-observed runtime constraint）

| 字段 | 内容 |
|---|---|
| ID | RW-030 |
| Title | Hermes FREE 标记模型的可用性/稳定性（user-observed runtime constraint；非普遍断言、非永久模型健康结论） |
| Category | Real-world usage / Model runtime observation |
| Status | **OBSERVATION**（2026-08-30，AAF-v0.5-A1-REGISTRY-RISK-001 登记） |
| Priority | P1 |
| Evidence / Origin | **用户观察（user-observed / runtime constraint）**：真实 Hermes v0.20.5 安装/使用过程中观察到——部分标记为 FREE 的模型实际无法使用；部分可用的 FREE 模型可能不稳定。证据级别说明：这是当前环境下的用户使用观察，**不是**「所有 Hermes 免费模型都坏」的普遍断言，也**不是**任何具体模型的永久健康判定；不据此给任何模型写死 health/availability 结论 |
| Problem | FREE 只是价格/成本属性；「标记 FREE」不能自动证明 available / stable / healthy / qualified / sufficient。若路由逻辑把 FREE 当作可用证据，会选中实际不可用或不稳定的候选 |
| Current Implementation | A1 model registry 契约（`ai_agent_framework/model_registry.py`）将 cost_class 与 runtime_qualification 严格分离（独立维度）；`is_usable_candidate` 仅由 capability_tier + qualification 判定，**绝不从 FREE 推导**；基线条目 qualification 全部显式 UNKNOWN（无健康轮询 / 无动态隔离——A1 范围外）。本观察同时登记于 PROJECT_STATE.md §0 v0.5 块 |
| Remaining Gap | 真实运行时 qualification 观测需 A2+（shadow / 实况观测）填充；当前无健康轮询、无自动隔离、无 fallback（均属 A2/A3 范围） |
| Decision | 登记为 OBSERVATION；路由层（A2/A3）消费 registry 时必须把 FREE（成本维度）与 qualification（运行时维度）分开：FREE ≠ healthy，UNKNOWN ≠ free |
| Target | 未来路由对 Hermes FREE 候选先做运行时 qualification 验证，再按能力/成本优先级选择 |
| Do Not Forget | **FREE ≠ healthy；unknown ≠ free**；不得把本观察升级为对任何具体模型的永久健康 verdict，也不得反向断言「所有 FREE 都不可用」 |

---

## RW-031 — Framework helper 子进程瞬时 Windows console 窗口闪现（confirmed console-visibility omission）

| 字段 | 内容 |
|---|---|
| ID | RW-031 |
| Title | AAF helper 只读 subprocess 调用未带既有 no-console 策略 → 瞬时可见 Windows console 窗口（cosmetic/UX only；非功能正确性失败） |
| Category | Runtime / UX observation（Windows subprocess console visibility） |
| Status | **CLOSED**（2026-08-30，AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001 修复并登记；按原始证据级别：confirmed Windows subprocess console-visibility omission） |
| Priority | P2 |
| Evidence / Origin | Hermes 只读诊断确认：AAF 正常执行期间可出现 1–5 个短暂可见 Windows console 窗口；根因 = 若干 helper 只读 `subprocess.run` 调用未带既有 no-console 配置（Bridge / runner / agent 主启动路径已有 `no_console_kwargs()` / `CREATE_NO_WINDOW`）。诊断同时确认：无 rogue AAF scheduled task、无 AAF Startup 条目、bridge.main 进程数 = shim + real process（非重复 Bridge 实例）、无当前功能 / lifecycle-authority 失败 |
| Problem | 从 GUI 宿主（pythonw / Tray Bridge）发起 console-subsystem 子进程（git.exe / hermes.exe / codebuddy.exe / codex.exe）时未传 `CREATE_NO_WINDOW` → 子进程短暂可见黑色 console 窗口（UX 干扰；命令输出仍被 capture，功能无影响） |
| Current Implementation | 全部确认调用点已复用 `subprocess_utils.no_console_kwargs()`（Windows: `CREATE_NO_WINDOW`；非 Windows: `{}`）：`context_packet.py` 6 处 git 调用（git_head / git_changed_files / _porcelain_all / remote_sync_state）、`git_status.py::_git()`（全部 helper git 调用）、`model_observation.py::_run_readonly()`（Hermes / CodeBuddy / Codex 全部 CLI 观测：--version / --help / config get model / config get auxiliary / exec --help）；子进程语义零变化（diff = 13 行插入 / 0 删除，仅追加 kwargs）；`bridge/status_window.py` explorer 调用经检查不改（explorer.exe 为 GUI-subsystem，无 console 创建路径，不为一致性而改）；10 项聚焦测试 + 定向 443 passed + 全量 non-GUI 零回归 + fresh-runner Run N+1 通过（详见 docs/internal/AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001-REPORT.md） |
| Remaining Gap | 无（helper 调用点全量审计完成，见 REPORT §5 逐点核对表）；未来新增任何非交互 console subprocess 调用时须沿用同一 `no_console_kwargs()` 策略 |
| Decision | CLOSED（2026-08-30）。按原始证据级别登记为 cosmetic/UX 观察——**不得**描述为功能正确性失败；修复只改变 console 可见性，不改变任何既有子进程语义 |
| Target | 已达成：确认的 git / helper / model-observation flash 来源全部带上 `CREATE_NO_WINDOW`，既有策略复用无第二策略 |
| Do Not Forget | 新增非交互 console subprocess 调用必须带 `**no_console_kwargs()`；本观察只证明 console-visibility 修复，不隐含任何功能行为变化 |

---

## RW-032 — 重复 closure-loop 教训：机器输出 mismatch 先验证 producer / schema / authority（structured-result 协议纠正）

| 字段 | 内容 |
|---|---|
| ID | RW-032 |
| Title | 同一 machine-output 形态反复出现 FIX 任务之前，必须先验证 producer、schema 与 authority layer（structured-result 协议纠正教训） |
| Category | Process lesson / 协议语义登记（non-code，无实现） |
| Status | **OBSERVATION / LESSON**（2026-08-31，AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001 登记；正式验收政策见 AAF_TASK_EXECUTION_POLICY §5.2） |
| Priority | P2 |
| Evidence / Origin | A1 closure 链 FIX-003 / FIX-004 连续两轮因「Hermes raw 结构化块缺 `commit_changed`」及「不应手动输出 AAF_STRUCTURED_RESULT 块」而 REQUEST_CHANGE；只读协议诊断（PROTOCOL-CORRECTION-001）确认：`commit_changed` 本就不在 Hermes raw 契约（`context_packet._STRUCTURED_SCHEMAS["hermes"]`，required=status，optional=commit/changed_files/warnings/findings），且 `AAF_STRUCTURED_RESULT` 是 adapter contract（`adapters._structured_contract_block`，注入点 `adapters.py:302`）要求的 Framework 必输出块——两轮 FIX 的前提假设与实际 Framework 实现不符 |
| Lesson | 为同一机器输出 mismatch 创建重复 FIX 任务之前：① **producer**——该输出由谁注入 / 谁要求（Framework adapter contract vs agent 自选）；② **schema**——该层契约实际字段集（raw agent schema ≠ 归一化 stage-result schema）；③ **authority layer**——raw agent 块 vs `<agent>_result.json` 谁裁决 lifecycle / provenance。三层验证后再开 FIX，避免在错误前提上重复闭环 |
| Decision | 登记为 process lesson（2026-08-31）。正式验收语义已写入 AAF_TASK_EXECUTION_POLICY §5.2；本条目不展开为流程改造（保持 concise） |

---

## 1.1 Desktop Shell Principle（桌面壳层设计原则）

> 本原则**不是新的产品功能条目**，
> 用于约束 RW-004、RW-006、RW-010、RW-012、RW-014、RW-015、RW-016 的未来实现。

Future AAF Desktop Shell 的定位是：

```
现有 AAF Core
+
轻量 Windows 操作与状态外壳
```

它未来可以承担：

- Bridge 后台运行入口
- Current Project
- Current Task
- 当前执行阶段
- elapsed time
- last activity
- agent 状态
- error / stuck 状态
- Stop / Cancel Current Task
- Restart Bridge
- Project switch
- Open Logs
- Settings
- Exit AAF

但 Desktop Shell 不替代：

- Router
- Runner
- Lifecycle
- Boundary
- Session
- Agent adapters
- TASK / REPORT protocol

### 1.1.1 防漂移边界（Anti-Drift Boundary）

未来桌面化**不能自动扩展**为：

- SaaS
- Web management platform
- multi-user backend
- account system
- cloud synchronization platform
- Agent marketplace
- plugin marketplace
- remote team control center
- autonomous infinite Agent loop

除非未来出现独立、明确的新决策。

### 1.1.2 目标架构（Target Architecture）

```
AAF Core
↓
Desktop Shell / Tray
```

核心执行逻辑保持独立，
UI 只负责操作、状态和生命周期入口。
Desktop App ≠ 重写 AAF。

---

## 1.2 Desktop / Runtime UX Cluster（问题簇）

包含以下独立条目：

- RW-004 — Bridge 后台启动 / Tray
- RW-006 — Runtime 状态可视化
- RW-010 — Desktop App / Windows Program Packaging
- RW-012 — Hotkey listener runtime reliability
- RW-014 — Task Stop / Cancel Capability
- RW-015 — Chinese-first Desktop UI
- RW-016 — Duplicate Task Status UX

各条目**保留各自独立 ID**。
Cluster 只是帮助未来统一设计，
**不能把各问题合并**后丢失原有 Evidence / Status / Priority。

---

# 2. Anti-Drift（BND）

## BND-001 — Planner-layer Anti-Drift Validation

| 字段 | 内容 |
|---|---|
| ID | BND-001 |
| Title | Planner-layer Anti-Drift Validation |
| Category | Anti-Drift / Governance |
| Status | PARTIAL |
| Priority | P2 |
| Evidence / Origin | 防漂移原则：suggestion 不得自动成为 requirement |
| Current Implementation | v0.3 Framework 层已有：<br>- PROJECT_SCOPE<br>- Boundary Check<br>- warning-first<br>- suggestion 不自动成为项目要求<br>- 不自动扩大 scope<br>- 不自动写 backlog<br>- 不自动产生下一 TASK |
| Remaining Gap | ChatGPT Planner 长期对话中仍需验证：<br>- context compression<br>- weighting change<br>- accumulated requirements<br>- model tendency<br><br>是否会导致：<br>- 思路漂移<br>- scope creep<br>- 历史决定遗忘<br>- suggestion 被误升级成 requirement |
| Decision | 必须明确：**Framework 层完成，不等于 Planner conversation 层已经完全解决** |
| Target | Planner 长期对话中思路漂移与 scope creep 可被识别并控制 |
| Do Not Forget | Framework 层机制不能替代 Planner 层验证；持续观察 |

---

# 3. Session Continuity（CTX）

## CTX-001 — Context Length / Conversation Rollover UX

| 字段 | 内容 |
|---|---|
| ID | CTX-001 |
| Title | Context Length / Conversation Rollover UX |
| Category | Session continuity / UX |
| Status | PARTIAL |
| Priority | P1 |
| Evidence / Origin | 真实需求：ChatGPT conversation 过长需要无遗失承接 |
| Current Implementation | v0.3 已有：<br>- explicit rollover<br>- SESSION_SUMMARY.md<br>- NEXT_SESSION_START.md<br>- bounded recent context |
| Remaining Gap | 用户真正希望实现：<br>1. ChatGPT conversation 接近过长时获得提醒；<br>2. 整理当前阶段状态；<br>3. 生成完整承接材料；<br>4. 引导进入新的 conversation；<br>5. 新 conversation 可直接继续；<br>6. 不遗失：<br>   - 当前状态<br>   - 已完成 TASK<br>   - 未完成问题<br>   - 边界<br>   - 决策<br>   - 下一步 |
| Decision | 原则：不做 infinite memory；不自动无限生成会话 |
| Target | 一次显式 rollover 完成 1-6 的完整承接体验 |
| Do Not Forget | 承接材料须可被新 conversation 直接读取并继续 |

---

## CTX-002 — TASK / Stage Prompt / REPORT Context Bloat（层层全文叠加）

| 字段 | 内容 |
|---|---|
| ID | CTX-002 |
| Title | TASK / Stage Prompt / REPORT Context Bloat（eager full-content chaining） |
| Category | Framework protocol / Context 管理 |
| Status | SOLVED（2026-08-28，AAF-MAINT-CONTEXT-001 交付） |
| Priority | P1 |
| Evidence / Origin | 真实运行观察：Hermes → WorkBuddy → Codex 层层全文叠加——WorkBuddy prompt 嵌入 Hermes narrative 全文，Codex prompt 再嵌入 Hermes + WorkBuddy 全文；REPORT 再复制整份 Original Task 与全部 Agent 全文。同一信息在 prompt / REPORT 中重复 3–5 次 |
| Current Implementation | **Stage Context Packet 协议（reference-based / lazy-loading）**：<br>- 正式 Anti-Bloat Policy：`docs/internal/AAF_TASK_EXECUTION_POLICY.md`<br>- Compact TASK Schema：`templates/TASK.md`（TASK = current delta）<br>- 下游 prompt 只接收 TASK 引用 + 结构化摘要（`<agent>_result.json`）+ changed files / commit / evidence 路径；narrative 全文按需读取<br>- `context_manifest.json`：TASK snapshot（`TASK.snapshot.md`，immutable）/ stage artifacts path+hash 可追溯引用（`check_references` 完整性检查）<br>- REPORT `## Original Task` 全文 → `## Task Reference`（Task ID / Snapshot Path / Hash）+ `## Remote Sync`（Commit Sync / Tracked Working Tree / Task Remote Sync）<br>- Semantic Coverage Guard（`verify_semantic_coverage`）：压缩是去重，不是删约束<br>- Context size 每 stage 可观测（chars/bytes + embedded/referenced counts）<br>- 测量证据：同一 fixture（固定 workspace 路径）old full-chain 26,211 chars → new packet 5,824 chars（-77.8%，embedded=0，referenced=1/2；复算来源 tests/test_context_integrity.py test_context_size_fixture_exact_numbers；历史 25,609→3,301 / 26,191→3,585 / 26,211→5,379 为 superseded 初算值；FIX-002 因 reviewer 契约新增 blocking_provenance 字段说明，5,379 → 5,824）<br>- Structured summary 契约（FIX-002）：`AAF_STRUCTURED_RESULT_BEGIN/END` JSON 块 + schema validation；findings/warnings 未提取 → null（UNKNOWN），不伪装为 []；narrative/JSON 一致性 guard（W1/W2/W3 → warnings 不得为 []）<br>- Anti-Regression 测试：`tests/test_context_compaction.py`（23 项）+ `tests/test_context_integrity.py`（22 项） |
| Remaining Gap | 无 blocking gap。Guard 是确定性子串检查；改写措辞的语义等价性依赖 WorkBuddy 独立验证（设计如此，非缺陷） |
| Decision | 新协议作为默认路径；旧目录自动 legacy fallback（Backward Compat） |
| Target | 已达成：重复输入明显下降、零信息丢失、独立验证逻辑与安全边界不变 |
| Do Not Forget | 不得恢复 eager full-content chaining；Anti-Bloat 规则见 Policy §12 反回归 guard |

---

# 4. Historical Recovery（HIST）

## HIST-001 — Historical Framework Optimization Set Recovery

| 字段 | 内容 |
|---|---|
| ID | HIST-001 |
| Title | Historical Framework Optimization Set Recovery |
| Category | Historical recovery |
| Status | RECOVERY_PENDING |
| Priority | P2 |
| Evidence / Origin | 用户记得早期曾讨论过一组约 10 个 Framework 优化项 |
| Current Implementation | 无（尚未恢复） |
| Remaining Gap | 当前没有足够可靠证据恢复其精确原文 |
| Decision | 必须保留其"存在"这一事实，但**不能根据今天的问题、模型常识或推测重新凑成十项**（本任务未自行重构） |
| Target | 记录：`Known historical optimization set exists; exact original list not yet recovered.` |
| Do Not Forget | 后续候选恢复来源：<br>- old handoffs<br>- PROJECT_STATE history<br>- ChatGPT exported conversations<br>- Obsidian notes<br>- local Markdown records |

---

# 5. Recovery / Durability（恢复与耐久性）

## 5.1 长期恢复资产

以下资产是 Framework 长期维护的恢复链（按读取顺序）：

```
1. README
2. PROJECT_STATE（docs/internal/PROJECT_STATE.md）
3. AAF_MASTER_BACKLOG（docs/internal/AAF_MASTER_BACKLOG.md）
4. latest closing handoff（docs/internal/handoffs/）
5. git history
```

## 5.2 角色与权威关系

```
Repository（GitHub / local repo）:
  authoritative source —— 唯一权威长期知识源

ChatGPT（Project / conversation）:
  planner / discussion interface —— 用于规划和协作

Obsidian（D:\AdyAI\Obsidian-Vault\AI Agent Framework\）:
  working knowledge / conversation handoff layer（PILOT / EXPERIMENTAL，2026-08-28 建立）
  + human-readable mirror（MIRROR ONLY）—— 阅读、搜索、恢复与工作记录（详见 §5.4）
```

## 5.3 ChatGPT 丢失后的恢复原则

即使旧 ChatGPT Project 或 conversation 不存在：

```
GitHub / local repo
→ README
→ PROJECT_STATE
→ AAF_MASTER_BACKLOG
→ latest closing handoff
→ 创建新的 ChatGPT Project / Planner conversation
→ 继续维护
```

Framework 仍能恢复到可继续升级的状态（见 RW-009）。

## 5.4 Obsidian 政策（2026-08-28 更新：双角色 + 分工规则，AAF-MAINT-HANDOFF-001）

Obsidian 中的 AAF 文档承担两种角色：

1. **MIRROR（既有政策）**：repo 正式资产的镜像 —— MIRROR ONLY，顶部声明来源；
   不作为独立权威版本维护；镜像由维护任务显式建立；
   **不开发自动同步程序或 Obsidian plugin**。
2. **Working Knowledge / Conversation Handoff 层（VERIFIED，2026-08-28 由
   AAF-v0.4-TASK-005-B-FIX-001 验证）**：
   working knowledge、discussion、draft、conversation handoff、stage retrospective、
   未定 / 未提升决策、每日项目笔记。当前 Pilot 只含一个入口文件
   `CURRENT_HANDOFF.md`；不建复杂结构 / plugin / 自动化；
   **验证完成**（验证 = 新 Planner 对话读取 CURRENT_HANDOFF 后准确恢复项目状态——
   005-B-FIX-001 会话即该新 Planner 对话，经 CURRENT_HANDOFF + PROJECT_STATE
   恢复项目状态成功，PILOT / EXPERIMENTAL → VERIFIED）。

GitHub / Obsidian 知识分工（当前工作规则）：
- GitHub / repo（正式 / 已提升知识；代码与版本权威）：code、formal policy、
  frozen design、PROJECT_STATE、MASTER_BACKLOG、formal REPORTs、promoted / finalized assets
- Obsidian（Working Knowledge 层）：working knowledge、discussion、draft、
  conversation handoff、stage retrospective、uncertain / not-yet-promoted decisions、
  daily project notes
- **一条信息只有一个 active authority；禁止维护两份可编辑的权威副本。**

Promotion 模型：
Obsidian working knowledge → stable conclusion → Framework task → 提升进 repo / GitHub 正式资产

未来泛化（planned policy，未激活，AAF-MAINT-HANDOFF-001）：
若本 Pilot 成功，同类 conversation-handoff 模式可推广为其他用户项目的默认做法；
当前不迁移 / 不修改其他项目。

---

# 5.5 Capability / 能力组（Model Observability / Discovery / Future Routing）

> 登记时间：2026-08-29（AAF-v0.4-TASK-010）
> 本组是**正式 backlog capability/group 登记**（Requirement 22/23/24 要求）：
> Model Observability / Model Discovery 已建立只读事实层；
> **Automatic Model Routing 未实现**——只登记未来 policy，不把未实现能力标成已实现。

## CAP-001 — Model Observability

| 字段 | 内容 |
|---|---|
| ID | CAP-001 |
| Title | Model Observability（模型观测事实层） |
| Category | Capability（只读基础能力） |
| Status | **IMPLEMENTED**（AAF-v0.4-FINAL-ACCEPTANCE-002 Codex APPROVE 确认，2026-08-29） |
| Priority | P1 |
| Evidence / Origin | AAF-v0.4-TASK-010 交付：`ai_agent_framework/model_observation.py` + `model_observation.json`（单一 machine authority，schema_version=1）+ 每 stage `stage_timing`（started/finished/elapsed）+ REPORT 紧凑摘要 |
| Current Implementation | runner 每 stage 记录时序并执行只读 discovery；观测记录含 agent/provider/model/model_source/reasoning_effort/cost_class/cost_metadata/cost_multiplier/discovered_at/discovery_status/capabilities/notes；`AAF_MODEL_OBSERVATION=0` 可整层关闭 |
| Remaining Gap | 实际执行模型名（如 WorkBuddy 运行时默认）依赖 CLI runtime 输出，当前为 UNKNOWN 时只能记录 UNKNOWN，不做猜测 |
| Decision | 本任务只建立事实层；决策层（routing / cost gate）属 CAP-003，未实现 |
| Target | 为未来 model benchmarking / routing 提供稳定事实输入 |
| Do Not Forget | 观测失败不得阻断执行；观测不是 execution authority；不得把 inference 写成 authoritative fact |

## CAP-002 — Model Discovery

| 字段 | 内容 |
|---|---|
| ID | CAP-002 |
| Title | Model Discovery（从真实 Agent 接口发现模型信息） |
| Category | Capability（只读发现能力） |
| Status | **IMPLEMENTED（以真实 Agent 接口为限）**（AAF-v0.4-FINAL-ACCEPTANCE-002 Codex APPROVE 确认，2026-08-29） |
| Priority | P1 |
| Evidence / Origin | 真实 CLI 只读 probe（TASK-010 + FIX-001，2026-08-29）：Hermes v0.20.5（`config get model` / `config get auxiliary` / `status`）；CodeBuddy 2.141.0（`codebuddy --version` 动态 probe；FIX-001 修正 TASK-010 手写 2.137.1 无证据值；`config get model` / `--help`）；codex-cli 0.150.0-alpha.12.2（`exec --help` / `~/.codex/config.toml` / `--version`） |
| Current Implementation | 每 agent 独立 discover_*：Hermes 主模型 + auxiliary slots（本地 Ollama 可发现）；CodeBuddy 当前模型 UNKNOWN（config 不暴露）+ CLI help 文档化模型 ID；Codex 默认模型 server-side 不可枚举（documented limitation）+ `-m/--model` 显式选择能力 |
| Remaining Gap | Codex server-side model catalog 不可由当前 CLI 枚举；WorkBuddy 实际运行模型需要 runtime 观测（非 config 事实） |
| Decision | 只使用 CLI/config 实际能力；不凭知识 / 不硬编码补齐不可发现的模型目录 |
| Target | 刷新式 registry（refreshable）：模型可增删改名、免费状态可变化、积分倍率可变化 |
| Do Not Forget | 不得发明不存在的 flag；一次发现结果不得当永久事实 |

## CAP-003 — Future Model Routing（未来能力登记，未实现）

| 字段 | 内容 |
|---|---|
| ID | CAP-003 |
| Title | Future Model Routing（未来 Model Routing 政策登记） |
| Category | Policy（未来方向登记；本 backlog 登记 ≠ 实现） |
| Status | **NOT IMPLEMENTED** |
| Priority | P2 |
| Evidence / Origin | AAF-v0.4-TASK-010 Requirement 23：只登记未来 policy，不实现 |
| Current Implementation | 无（零 routing 代码）。注（2026-08-31，AAF-v0.5-A2-SHADOW-ROUTING-001）：A2 Shadow Routing 已 STARTED——`ai_agent_framework/shadow_routing.py` deterministic **shadow-selection engine**（假设性 / 非权威 / 零执行影响，live 路径零 import）；A2-002 接入 Hermes shadow observation（observation-only bypass）；A2-003 建立 explicit task-risk provenance（TASK 可选 `Risk` 字段 → immutable snapshot → shadow observation，Planner 显式结构化声明，缺失 = RISK_UNAVAILABLE，非法值严格拒绝）；A2-004 为 deepseek-v4-flash@deepseek 填入证据支持的 registry qualification（capability_tier=T2 + QUALIFIED，仅来自已接受的 003-FIX-001 HIGH 执行/审查证据，accepted evidence snapshot、不推断 T1/T0、cost_class 仍 UNKNOWN）——HIGH Hermes shadow 现产生真实 hypothetical candidate；本 CAP-003 指**实际** Model Routing（切换 / fallback / 升级），仍 **NOT IMPLEMENTED** |
| Remaining Gap | task risk → model / cheapest-model selection / fallback escalation / free→paid switching / user confirmation dialog / Cost Gate 全部未实现 |
| Decision | 未来 policy 记录：① Quality / Safety threshold 满足的前提下优先最低现金成本模型；② LOCAL_FREE / FREE / FREE_PROMO 优先，免费候选不足才考虑 paid；③ Free → Paid 必须经 Cost Gate 用户明确批准；④ 动态模型/免费/倍率元数据必须刷新后再决策。本任务禁止项：自动切换模型、自动升级付费模型、修改 Agent 模型配置、实现 Cost Gate、实现 Automatic Model Routing |
| Target | 下一阶段（Model Routing）在 CAP-001/CAP-002 事实层之上实现 |
| Do Not Forget | 不要把本登记误认为已实现；决策层必须用户批准（Free→Paid） |

---

## CAP-004 — Cost-Aware Model Routing A0：Hermes Paid Guard（v0.5 A0，已交付）

| 字段 | 内容 |
|---|---|
| ID | CAP-004 |
| Title | v0.5 A0 Hermes Paid Guard — Fail-Closed Task-Scoped Cost Authorization |
| Category | Capability（v0.5 Cost-Aware Model Routing 第一层保护；TASK: AAF-v0.5-A0-PAID-GUARD-001，2026-08-29） |
| Status | **CLOSED / COMPLETE (A0)**（2026-08-30 AAF-v0.5-A0-PAID-GUARD-001-CLOSE-001 正式关闭：FIX-006 Codex APPROVE（blocking_rework=false，blocking_provenance=structured，commit b1e8bf2）→ A0 验收链闭合——Hermes completed / WorkBuddy PASS_WITH_WARNING（non-blocking）/ Codex APPROVE / Unresolved=None；Next mainline = A1 Registry + Risk，A1 未启动；Hermes free-model 可用性/稳定性为后续路由的 runtime qualification concern，不假定 FREE=healthy。此前：v0.5 A0 交付；2026-08-29 FIX-002 修复 Codex 三个 blocking fail-open 发现（①本地端点改 hostname/IP 严格判定（substring 移除）；②移除 `AAF_COST_FREE_MODELS` 权威 FREE 路径（A0 无远程 FREE 权威）；③授权改为**准入即消费**的真一次性语义（replay 拒绝、fail closed））；2026-08-30 FIX-003 授权消费原子化（`_claim_auth` 单一原子操作，filesystem exclusive-create 为跨进程权威，TOCTOU 移除）；FIX-005 收口 Codex blocking：paid admission 无持久化 state_dir（filesystem authority）→ fail closed，`_CONSUMED_AUTHS` 绝不放行（17 项 A–H 测试 + fresh-runner 6/6）；FIX-006 收口 Codex FIX-005 review blocking：state_dir 必须为显式提供的非空绝对路径——空串 / 纯空白 / `Path("")` CWD fallback / "." / 相对 / 畸形 / 类型非法 / 任何 CWD 派生权威一律 fail closed 且零 marker 创建（24 项测试 + fresh-runner 7/7）） |
| Priority | P1 |
| Evidence / Origin | TASK: AAF-v0.5-A0-PAID-GUARD-001（v0.5 由用户显式启动的第一项） |
| Current Implementation | Hermes stage subprocess 创建前 guard（`ai_agent_framework/cost_guard.py`，runner 集成 + adapters 透传）：① effective model 解析（`AAF_HERMES_MODEL`/`AAF_HERMES_PROVIDER` env 覆盖优先，其次 `hermes config get model` 只读查询；零网络/零 LLM）；② A0 最小成本分类（LOCAL_FREE：base_url 解析后 hostname = exact localhost / loopback IP（127.0.0.0/8、::1）或 verified local Ollama；**无远程 FREE 分类**——`AAF_COST_FREE_MODELS` 仅诊断 note；其余远程/API → PAID_OR_UNKNOWN；无法解析 → COST_UNKNOWN fail closed；FIX-002）；③ 一次性 task-scoped 授权（`AAF_COST_AUTH="<Task ID>|<stage>|<model>[|<provider>]"` 整串精确匹配；**准入即消费**——in-process 集合 + 执行目录 `cost_auth_consumed.json`，同一 execution 上下文内同一授权值不可二次准入；FIX-002）；④ 决策状态机器可读（ALLOWED_FREE / ALLOWED_AUTHORIZED_PAID / BLOCKED_COST_APPROVAL；`cost_guard.json` artifact 含 decision_ms）；⑤ blocked → 不创建 Hermes 进程，任务 WAITING（COST_APPROVAL_REQUIRED），REPORT/result.md 给出 Task ID / stage / model / provider / cost status / 阻断原因 / 所需精确授权 scope |
| Remaining Gap | A1+（A1 及之后各阶段，含 A2+；本任务显式不做，非 A1 单阶段 scope——2026-08-30 CLOSURE-AUDIT-001-FIX-001 裁决注记）：Hermes candidate Tier registry、Selection Engine / Shadow Routing（= A2）、WorkBuddy RemoteConfig 解析与经济路由、free-to-free fallback、capability learning、精确 RMB/token 计价、PAID_LOW/MEDIUM/HIGH、Codex 成本优化、图形化 Cost Gate UX（当前仅最小 blocked-state 文本） |
| Decision | 授权机制最小实现 = 单 env 变量 + 整串精确匹配（不引入文件子系统/数据库/长生命周期 token；runner 无法自行持久化自授权）；Hermes 全局 config 零修改；`AAF_HERMES_MODEL`/`AAF_HERMES_PROVIDER` 覆盖会透传 `-m`/`--provider` 到实际 invocation（guard 解析的 effective model == 实际调用模型），无覆盖时 invocation args 与 v0.4 完全一致 |
| Target | 任何远程/未知成本 Hermes 调用都必须显式、窄域、task-scoped 授权后才能启动；未知成本绝不视为免费 |
| Do Not Forget | 本 A0 只做 Hermes 保护层；不得据此宣称完整 Model Routing 已实现（CAP-003 仍 NOT IMPLEMENTED）；授权 env 是 per-run 一次性，不是永久/全局 bypass |

---

# 6. Update Rules（更新规则）

1. 本文件是 **Living** 文档，随真实证据持续更新。
2. 以后任何被正式确认"稍后处理"的问题，**必须进入 Master Backlog 才算长期登记完成**。
3. 新条目使用本文件规定的 Status / Priority 词汇，禁止自造状态。
4. 每个正式条目至少包含：ID / Title / Category / Status / Priority /
   Evidence / Origin / Current Implementation / Remaining Gap / Decision /
   Target / Do Not Forget。
5. 登记未来功能方向时必须同时写明边界（不做哪些），防止范围膨胀。
6. 已解决事故（SOLVED）保留历史记录，不删除、不覆盖。
7. 描述 Router 相关事件时，**不原样引用任何 Router 触发短语**，
   防止全文信号匹配再次自我触发。
8. **Before planning new AAF work: FIRST READ this file.**
9. 事故证据目录 `.aaf/AAF-MAINT-001/` 与 `.aaf/AAF-MAINT-001-FIX-001/`
   保留为真实历史证据，不删除、不覆盖。

---

# 7. Summary（当前登记总览）

| ID | Title | Status | Priority |
|---|---|---|---|
| RW-001 | Bridge 提示音与弹窗视觉体验 | OPEN | P2 |
| RW-002 | 新用户 onboarding / 产品定位 | PARTIAL | P2 |
| RW-003 | Bridge 自动识别与切换项目 | SOLVED | P1 |
| RW-004 | Bridge 启动方式与 Windows Tray | OPEN | P1 |
| RW-005 | Framework 执行速度与阶段耗时 | OBSERVATION | P2 |
| RW-006 | Runtime 状态可视化 | SOLVED | P1 |
| RW-007 | Agent executable discovery reliability | PARTIAL | P2 |
| RW-008 | TASK / Bridge parser compatibility | SOLVED (v0.4) | P1 |
| RW-009 | ChatGPT Project / Conversation disaster recovery | PARTIAL | P0 |
| RW-010 | Desktop App / Windows Program Packaging | OPEN | P2 |
| RW-011 | Router local constraint classification incident | SOLVED | P1 |
| RW-012 | Bridge hotkey listener runtime reliability | SOLVED (v0.4) | P1 |
| RW-013 | Router self-triggering reference trap | OPEN | P1 |
| RW-014 | Task Stop / Cancel Capability | PARTIAL | P1 |
| RW-015 | Chinese-first Desktop / Tray User Interface | OPEN | P2 |
| RW-016 | Duplicate Task Status UX | SOLVED | P1 |
| RW-017 | .aaf Runtime Artifact Git Ignore Consistency | OBSERVATION | P3 |
| RW-018 | GitHub Push / Proxy Environment Reliability | OBSERVATION | P3 |
| RW-019 | Agent Review Execution Evidence Consistency | OBSERVATION | P2 |
| RW-020 | Dead Runner / Orphaned RUNNING State Detection | SOLVED | P1 |
| RW-021 | Bridge Restart / Exit Completion Notification Continuity | OPEN | P2 |
| RW-022 | Framework Final Status Aggregation: PASS_WITH_WARNING + APPROVE + Blocking NONE → WAITING | SOLVED | P1 |
| RW-023 | E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop | OPEN | P2 |
| RW-024 | Completion Dialog Copy Report UX（复制报告二次弹窗 + Z 序问题） | SOLVED | P2 |
| RW-025 | Session Continuity Clock Flake（test_first_rollover_generates_files 秒级时钟边界） | OPEN | P3 |
| RW-026 | Automated pytest 弹出真实桌面 Bridge modal（FIX-UI-A-001；GUI E2E 未结构性排除） | SOLVED | P1 |
| RW-027 | WorkBuddy Stage Reliability / Bounded Transient Retry | SOLVED | P1 |
| RW-028 | pythonw 早期校验失败 UI 仅显示 exit=2（TaskValidationError 不可见） | OBSERVATION | P2 |
| RW-029 | Windows 全量 pytest 环境 0x80000003 观察（test-env） | OBSERVATION | P3 |
| RW-030 | Hermes FREE 标记模型不可用/不稳定（user-observed runtime constraint） | OBSERVATION | P1 |
| RW-031 | Framework helper 子进程瞬时 Windows console 窗口闪现（cosmetic/UX only） | CLOSED | P2 |
| BND-001 | Planner-layer Anti-Drift Validation | PARTIAL | P2 |
| CTX-001 | Context Length / Conversation Rollover UX | PARTIAL | P1 |
| CTX-002 | TASK / Stage Prompt / REPORT Context Bloat（层层全文叠加） | SOLVED | P1 |
| HIST-001 | Historical Framework Optimization Set Recovery | RECOVERY_PENDING | P2 |
| CAP-001 | Model Observability | IMPLEMENTED | P1 |
| CAP-002 | Model Discovery（以真实 Agent 接口为限） | IMPLEMENTED | P1 |
| CAP-003 | Future Model Routing（政策登记，未实现） | NOT IMPLEMENTED | P2 |
| CAP-004 | Cost-Aware Model Routing A0：Hermes Paid Guard（v0.5 A0） | CLOSED / COMPLETE (A0) | P1 |
