# AAF ROLE CONTRACTS — Planner / Executor / Validator / Reviewer 抽象角色契约与替换规范

> Document Type: **Durable Framework Contract / 正式角色契约**（非历史记录）
> Established: 2026-09-05（AAF-v0.5-PH1-PLANNER-BOOTSTRAP-ROLE-CONTRACTS-001；用户显式批准的 v0.5 PH-1 Portability Hardening）
> Location: `docs/internal/AAF_ROLE_CONTRACTS.md`
> Scope: AAF 四个抽象角色的最小兼容契约、当前 concrete mappings、runtime 可替换性分类、最小安全替换流程、PORTABILITY_GAP 登记
> 与既有权威的关系：本文件**加深但不改写** PROJECT_STATE v0.5「MVP FROZEN」块 / AAF-v0.5-MVP-FREEZE-CLOSE-001-REPORT.md 的角色契约抽象条目；
> 行为权威仍 = runtime 代码（本文全部分类均有代码证据）；替换任何 concrete 产品不重定义 AAF（v0.5 冻结定义）。
> 引用行号 = 撰写时点（HEAD `0c5dfad`）证据；代码行号可能随维护漂移，以文件语义为准。

## 1. 抽象角色 vs concrete mapping（先分清）

- **抽象角色（contract）** = 一组职责 + 输入/输出/行为要求的身份定义，与具体产品无关：
  Planner / Executor / Validator / Reviewer（Router = 框架自身的机器路由功能，不是 Agent 角色）。
- **concrete mapping（implementation）** = 当前由哪个产品扮演：Planner = ChatGPT；Executor = Hermes；
  Validator = WorkBuddy（codebuddy CLI）；Reviewer = Codex（按 Route 需要）。
- **替换不重定义 AAF**：若替换品满足对应角色契约，替换 ChatGPT / Hermes / WorkBuddy / Codex
  中的任何一个都不改变 AAF 的产品定义、MVP 边界或架构（v0.5 FROZEN 定义，Requirement 12）。
- 反例（不成立）：因为 Executor 现在是 Hermes，就认为 AAF = Hermes 的封装。Executor 角色契约是
  Hermes 现在满足的**要求集**；Hermes 只是当前实现。

## 2. Planner Contract

### A. REQUIRED（契约硬要求）
- **输入**：
  1. user objective（用户本轮目标）；
  2. authoritative project state（PROJECT_STATE.md 顶部 + v0.5 块；本文件；目标项目 PROJECT_SCOPE.md）；
  3. latest REPORT / relevant handoff（最近一轮 `.aaf/<Task ID>/REPORT.md`；必要时 docs/internal/handoffs/）。
- **输出**：一份合法 AAF TASK 文本——以 `AAF_TASK_BEGIN` / `AAF_TASK_END` 包裹；含 Task ID /
  Task Name / Workspace / Objective / Acceptance（Validation 强制字段）；按 Compact schema 全字段
  编写（templates/TASK.md）；关键字段单行；纯文本代码块输出（无 Markdown 转义）。
- **职责**：
  1. planning（把目标拆成最小可执行 delta）；
  2. scope control（显式 Scope / Out of Scope；不触碰冻结边界；新 capability = post-freeze opt-in）；
  3. acceptance interpretation（定义可验证的 Acceptance，并在 REPORT 返回后做最终验收判断）；
  4. next-task generation（在 REPORT 的 Planner Handoff 基础上决定：下一最小任务 / FIX / 收口 / 停止）；
  5. **不做执行-stage 冒充**：不把自己伪装成 Executor/Validator/Reviewer 的执行产物；执行由框架路由。
- 权威读取义务：先读权威文件再规划（本文件 START_HERE_FOR_NEW_PLANNER.md §3 顺序）。

### B. OPTIONAL
- 在 TASK 中显式声明 `Risk: LOW|MEDIUM|HIGH|CRITICAL`（结构化 provenance；缺失 = 向后兼容）；
- 显式声明 `Route: hermes -> workbuddy -> codex`（machine-authoritative；缺省走 legacy 关键词推断）；
- 输出 Route Hint（人类可读分工建议，不参与机器路由）；
- 跨会话 rollover / handoff 材料（session_cli rollover / handoff 文档）。

### C. current concrete implementation
- ChatGPT（用户账号对话 / Project）。框架外部；无 CLI、无 API 绑定；通过人工 copy/paste 与框架交互
  （README.md 角色表；AAF 不自动写回 ChatGPT——README Known Limitations）。
- Runtime 中**不存在**任何调用 ChatGPT 的代码路径：路由白名单只有 hermes/workbuddy/codex
  （router.py ALLOWED_ROUTE_AGENTS），intake 只消费 TASK 文本（bridge/intake.py plan_submission）。

### D. replacement compatibility requirements
- 替换品只需：能读仓库/上下文（或由人喂关键文件）、能输出合法 TASK 文本、能读 REPORT 做决策。
- **不需要**改动任何 runtime / 代码 / 配置。分类 = CONTRACT_REPLACEABLE_NOW（见 §6）。
- 注意：不能读取本地文件的产品（如纯网页无工具 LLM）需要人粘贴权威上下文，仍可满足契约；
  这不构成"即插即用"之外的额外 runtime 要求。

## 3. Executor Contract

### A. REQUIRED
1. **消费 immutable Task authority**：执行以 Runner 冻结的 `TASK.snapshot.md`（immutable execution
   snapshot + raw-byte SHA-256）为唯一执行权威；active TASK 文件变化不影响本轮执行
   （runner.py 冻结逻辑 + AAF_TASK_EXECUTION_POLICY.md §4）。
2. **只执行 assigned scope**：严格执行 TASK 的 Requirements / Scope，不扩大范围；
   产物只写 TASK Workspace。
3. **产出证据**：真实修改（git commit / changed_files）+ 可复现的测试/验证输出 + narrative；
   框架以 git 观察为准派生 commit / commit_changed / changed_files（context_packet build_stage_result）。
4. **输出合法结构化 stage result**：答复以 `AAF_STRUCTURED_RESULT_BEGIN {JSON} ... END` 结尾
   （Hermes raw schema = status(SUCCESS/FAILED) / commit / changed_files / warnings；由
   adapters._structured_contract_block 注入，framework 要求，非自选）；narrative 保留追溯。
5. **保持执行 authority 语义**：不得声称框架未观察到的 git/文件事实；自报与框架观察冲突时框架观察权威。
6. **如实报告 blockers**：失败 / 环境问题 / 无法完成 → 显式 FAILED + FRAMEWORK_ERROR 或明确叙述，
   不静默跳过、不伪装成功、不伪造产物。

### B. OPTIONAL
- 结构化块内给出 warnings（确认没有 = `[]`；未确认不放数组）；findings。
- 执行后清理临时产物；提供 evidence_paths。

### C. current concrete implementation
- Hermes CLI：`hermes chat --in <workspace> -q <prompt> -Q --ignore-rules --source tool`
  （adapters.py run_agent hermes 分支）；模型覆盖经 `-m / --provider`（A0/A3 env 透传）。
- 模型/成本层（Hermes 专属语义，替换时注意）：A0 Paid Guard（cost_guard.evaluate，runner Hermes
  stage 预调用；effective model 解析 = `hermes config get model` 只读发现）；A3 LOW-risk FREE
  active routing（AAF_HERMES_MODEL/PROVIDER/BASE_URL 覆盖）；A5 bounded fallback
  （FREE/LOCAL_FREE → paid escalation Cost Gate，仅 agent=='hermes' 分支）。

### D. replacement compatibility requirements
- 替换 CLI 必须：接受完整 TASK + workspace 语义（或等价 adapter 映射）、真实修改文件并允许 git
  观察、能在 prompt 契约下输出 Hermes-等价结构化块（status/commit/changed_files/warnings——
  若不能，框架结构化 schema 需按新 agent 扩展或走 legacy narrative fallback）、如实暴露失败。
- runtime 变更点（集中、单点）：router.py ALLOWED_ROUTE_AGENTS（+新 agent 名）→ adapters.py
  ROLE_INSTRUCTIONS + run_agent 新 CLI 分支（CLI 发现复用 `_require` 模式）→ runner.py 中
  `agent == 'hermes'` 分支的 A0 guard / A3 / A5 语义按新 CLI 适配或显式停用（fail closed，
  不静默降级）→ model_registry / cost_guard 的 Hermes 专属模型事实按需扩展。
- 替换后必须通过：全量 pytest 零回归 + fresh-runner N+1（真实子进程证据）+ 真实小 TASK 全链。

## 4. Validator Contract

### A. REQUIRED
1. **独立 inspect 相关证据**：读取 TASK snapshot 全文、检查仓库实际状态（changed files / commit /
   evidence paths 真实存在且与声明一致）、独立核对 acceptance semantics 与 safety invariants；
   **不得只相信 Executor summary**（adapters._packet_prompt 注入独立验证指令；摘要只用于导航）。
2. **显式 non-blocking/blocking verdict**：输出 `PASS`（无阻断）/ `PASS_WITH_WARNING`
   （有警告但非阻断）/ `FAIL`（阻断）；结构化块含 verdict + blocking_rework(bool)。
3. **区分 warning 与 required rework**：PASS_WITH_WARNING 的警告 ≠ blocking rework；
   FAIL/blocking_rework=true 的返工项必须显式列出，供 Planner 决定 FIX。
4. **不修改文件**：Validator 只读复核（role instruction 显式"不要修改文件"）。
5. **引用缺失 fail-fast**：无法读取 snapshot / 引用文件 → 报告 FAIL 并列出缺失项，不静默降级。

### B. OPTIONAL
- 结构化块含 blocking_provenance（structured/framework/narrative）；findings / warnings 数组；
- 对上游执行证据给出证据链评估（evidence chain 是否闭合）。

### C. current concrete implementation
- WorkBuddy（CodeBuddy CLI）：`codebuddy -p --output-format text -y`（prompt 走 stdin）；
  A4 economic routing 时精确追加 `--model <winner>`；transport 层有界 transient retry（RW-027
  workbuddy_retry + Windows tree cleanup 语义）；上游依赖 = Hermes stage 产物
  （adapters 上游依赖表：workbuddy ← hermes_result.json / .md 引用）。

### D. replacement compatibility requirements
- 替换 CLI 必须：能读仓库、能独立运行（不依赖执行链之外的上下文）、输出 PASS/PASS_WITH_WARNING/FAIL
  等价 verdict + blocking 语义（结构化块或 canonical line-level verdict 行——框架二者都接受，
  缺结构化块时走 narrative canonical verdict 解析，fail-safe）、只读不改写文件。
- runtime 变更点：同 Executor 的三处单点 + workbuddy_retry/cleanup 语义按新 CLI 适配 +
  A4 economic routing 分支（workbuddy_routing env 覆盖）按新 CLI 参数适配。

## 5. Reviewer Contract

### A. REQUIRED
1. **独立审查**：基于 TASK snapshot + Executor 执行事实 + Validator verdict/findings 独立审查
   代码 / 架构 / 逻辑 / 风险；读 changed files 与相关 repo/diff 路径；**不默认相信任何上游 summary**。
2. **支持 formal APPROVE / REQUEST_CHANGE-equivalent authority**：输出 APPROVE（通过）或
   REQUEST_CHANGE（阻断）；结构化块含 verdict + blocking_rework。
3. **不静默修改 accepted scope**：Reviewer 只读（当前实现 = codex `--sandbox read-only` 强制）；
   发现需修改 → REQUEST_CHANGE + 明确返工项，不代替 Executor 改文件。
4. **blocking findings 显式报告**：REQUEST_CHANGE / FAIL 必须列出具体 blocker；
   引用缺失 → REQUEST_CHANGE 并列出缺失项（fail-fast，不静默继续审查）。

### B. OPTIONAL
- 对跨 stage 证据链给出权威性评估；approve 时附带 non-blocking findings / 建议。

### C. current concrete implementation
- Codex CLI：`codex exec --sandbox read-only --cd <workspace> --skip-git-repo-check -`（prompt 走
  stdin）；CLI 发现含官方 hash 目录 fallback（自动升级后目录变化仍可发现）；上游依赖 =
  Hermes + WorkBuddy stage 产物（adapters 上游依赖表 codex ← hermes + workbuddy）；
  按 Route 可选（不是所有任务都含 Codex）。

### D. replacement compatibility requirements
- 替换 CLI 必须：能读仓库、能输出 APPROVE / REQUEST_CHANGE 等价 verdict、具备等价只读强制
  （sandbox/read-only 模式——若新 CLI 无强制只读，框架级只读保证消失，只能依赖 prompt 指令；
  属替换方必须评估的兼容要求）、上游依赖表支持（其审查输入 = hermes + workbuddy stage 产物引用）。
- runtime 变更点：同 Executor 三处单点；codex 专属 sandbox 参数与 CLI 发现 fallback 按新 CLI 适配。

## 6. Runtime 可替换性分类（证据）

分类词汇：`CONTRACT_REPLACEABLE_NOW`（今天即可零 runtime 变更替换）/
`REPLACEABLE_WITH_ADAPTER`（可替换，但需要集中单点 runtime 编辑）/
`CURRENTLY_HARD_CODED`（当前架构无法实际替换）。

| 角色 | 分类 | 证据（HEAD 0c5dfad 时点） |
|---|---|---|
| Planner | **CONTRACT_REPLACEABLE_NOW** | 框架外产品：无任何 runtime 调用 ChatGPT 的路径——route 白名单 = ("hermes","workbuddy","codex")（router.py:37）；intake 只消费 TASK 文本（bridge/intake.py plan_submission/apply_submission）；README 角色表"Planner = ChatGPT 或任何能输出标准 AAF TASK 文本的 AI" |
| Executor | **REPLACEABLE_WITH_ADAPTER** | run_agent 按 agent 名分派 CLI（adapters.py:486-543；hermes 分支 492-505 = hermes chat 专属参数）；角色 prompt 按 agent 键（adapters.py:23-27 ROLE_INSTRUCTIONS）；A0 Paid Guard / A3 active routing / A5 fallback 全部只在 runner `agent == 'hermes'` 分支执行（runner.py:509-532, 596-681）；cost_guard 经 `hermes config get model` 解析 effective model（Hermes 专属发现） |
| Validator | **REPLACEABLE_WITH_ADAPTER** | workbuddy 分支 = codebuddy CLI 参数（adapters.py:506-537，`-p --output-format text -y` [+ `--model`]，prompt 走 stdin）；transport retry / Windows tree cleanup 为 codebuddy 进程语义（workbuddy_retry.py）；上游依赖表 workbuddy ← hermes（adapters.py:215-216）；A4 routing env AAF_WORKBUDDY_MODEL → `--model`（workbuddy_routing.py） |
| Reviewer | **REPLACEABLE_WITH_ADAPTER** | codex 分支 = `codex exec --sandbox read-only ...`（adapters.py:538-541）；CLI 发现含官方 hash 目录 fallback（adapters.py:428-445 `_codex_fallback`，仅覆盖 codex）；上游依赖表 codex ← hermes + workbuddy（adapters.py:225-226） |
| Router / Runtime | 不适用（框架自身） | decide_route / parse_explicit_route（router.py）；Runner 编排（runner.py）；结构化结果契约注入（adapters.py:67-93 `_structured_contract_block`） |

**CURRENTLY_HARD_CODED = 无**（本轮分类未发现架构级不可替换耦合）。声明边界：
- "无 hard-coded" ≠ "即插即用"：Executor/Validator/Reviewer 的 CLI 分支与模型层语义是**产品专属实现**，
  替换必须按 §3-§5 D 与 §8 流程编辑集中单点并全量回归——这就是 REPLACEABLE_WITH_ADAPTER 的含义；
- whitelist + 分支集中在少数文件（router.py / adapters.py / runner.py），单点编辑成本低、位置可枚举，
  不需要 plugin 架构或动态 adapter 加载（后者 = 明确 out of scope，见 §10）。

## 7. 替换评估（今天，诚实的答案）

| 问题 | 答案 | 依据 |
|---|---|---|
| Planner 可被 DeepSeek / 其他 LLM 今天替换吗？ | **可以（CONTRACT_REPLACEABLE_NOW）**。零 runtime 变更。条件 = 能读到权威上下文（本仓库文件，或人工粘贴 START_HERE + PROJECT_STATE 顶部 + 最近 REPORT）并能输出标准 AAF TASK 文本、执行人工 copy/paste 闭环。 | §2 / §6；Planner 在框架外，无代码路径绑定 |
| Hermes 今天可替换吗？ | **不能零改动替换**（REPLACEABLE_WITH_ADAPTER）。换"另一个 Hermes 实例/账号" = 可以（同 CLI）；换"另一个产品 CLI" = 需 adapter 单点编辑（run_agent hermes 分支 + A0/A3/A5 语义 + cost_guard 发现）+ 全量回归。不要声称开箱即用。 | §3C/D / §6 |
| WorkBuddy 今天可替换吗？ | **不能零改动替换**（REPLACEABLE_WITH_ADAPTER）。codebuddy CLI 参数 / retry / A4 --model / 上游依赖均为 codebuddy 语义；替换需 adapter 编辑 + 回归。 | §4C/D / §6 |
| Codex 今天可替换吗？ | **不能零改动替换**（REPLACEABLE_WITH_ADAPTER）。codex exec 参数 / sandbox / 上游依赖为 codex 语义；且 codex CLI 缺失时框架如实 WAITING（MISSING_COMMAND），已有 hash 目录 fallback 仅覆盖 codex 官方布局。 | §5C/D / §6 |

> 任何"已支持即插即用"的更强声明都需要新 runtime 证据；当前仓库证据不支持。

## 8. 最小安全替换流程（每角色通用，不改架构）

1. **登记与授权**：先在 AAF_MASTER_BACKLOG 登记拟替换 + 获得用户显式 scope 批准
   （post-freeze opt-in policy；替换属新 framework capability 边界内变更）。
2. **契约核对**：确认候选产品满足目标角色契约（本文件 §2-§5 的 A + D 列），特别是：
   结构化输出能力（或接受 narrative fallback）、verdict 词汇、执行/只读语义、CLI 可脚本化、
   上游产物读取能力。
3. **备份**：工作树备份分支 / tag（先备份后改动）。
4. **单点编辑**：
   - router.py：ALLOWED_ROUTE_AGENTS 增加（或替换）agent 名；
   - adapters.py：ROLE_INSTRUCTIONS 加角色 prompt；run_agent 加 CLI 分支（CLI 发现复用 `_require`
     模式，Windows 发现路径可参考 `_codex_fallback`）；`_packet_prompt` 上游依赖表与
     `_structured_contract_block` schema（若产物字段不同）；`verify` 所需上游 artifacts；
   - runner.py：被替换角色的专属分支适配——Executor：A0 guard / A3 / A5 的 `agent=='hermes'`
     分支按新 CLI 参数或显式停用（fail closed）；Validator：workbuddy retry 语义 + A4 env 映射；
     Reviewer：sandbox 等价参数。任何不适配的模型层功能**显式停用并审计**，绝不静默降级。
5. **验证**：全量 pytest 零回归 + fresh-runner N+1（新进程真实 CLI）正反场景 +
   真实小 TASK 全链（执行 → 验证 → 审查 → REPORT）。
6. **收口**：更新 PROJECT_STATE / README / 本文件 §1 mapping 与 C 列；按项目惯例执行
   WorkBuddy 独立验证 + Codex review 后 sync（no push 在前）。

> 角色专属差异：
> - **Planner**：无 runtime 编辑。最小流程 = 读 START_HERE_FOR_NEW_PLANNER.md → 用小型真实 TASK
>   试跑一轮 → 与旧 Planner 输出质量对比 → 正式接任。安全注意：先读权威状态，不凭旧聊天记忆规划。
> - **Validator / Reviewer**：保持"独立验证/审查"语义是契约核心——新 CLI 若倾向信任上游 summary
>   或无法读仓库，则不满足契约，不得接任。

## 9. PORTABILITY_GAP 登记（只登记有代码证据的具体缺口；本任务不实现修复）

| ID | Gap（证据） | 影响角色 | blocking? |
|---|---|---|---|
| GAP-PH1-01 | route agent 白名单 + role→agent 绑定 + 每 CLI 调用分支 + 上游依赖表全部以 **agent 名硬编码**在 router.py:37 / adapters.py:23-27, 215-226, 486-543 / runner.py 各 `agent == '...'` 分支；无单一 role→agent 配置/注册表 | Executor / Validator / Reviewer（+ 未来新增 agent） | non-blocking（MVP FROZEN 块已文档化这些集中改动点并判 MVP_SUFFICIENT；本文件 §6 已给出完整清单） |
| GAP-PH1-02 | Executor **模型层为 Hermes 专属**：A0 Paid Guard 经 `hermes config get model` 解析（cost_guard.resolve_effective_hermes）、A3 用 AAF_HERMES_* env 覆盖、A5 fallback 只在 agent=='hermes' 分支评估；换非 Hermes CLI 时这些 guard/routing 语义无法原样复用 | Executor | non-blocking（当前 Hermes 运行正常；替换时才暴露） |
| GAP-PH1-03 | Reviewer CLI 发现 fallback 只覆盖 Codex 官方 hash 目录布局（adapters.py:428-445 `_codex_fallback`）；无通用 CLI 发现表；其他 reviewer CLI 缺失 → MISSING_COMMAND → WAITING（如实，但需人工修复后 resume） | Reviewer | non-blocking（fail-safe 行为正确；resume 路径存在） |

> 未发现其它可证实的 portability gap；所有 gap 的最小修复方向见 §11（PH-1 gap table）。
> 本任务**不实现**任何修复（docs-only；Requirement 17/21）。

## 10. Out of Scope（本文件不授权、本任务未构建）

- ❌ plugin ecosystem / 动态 adapter 加载框架 / 通用 adapter registry 服务；
- ❌ model marketplace / agent marketplace；
- ❌ 自动模型选择扩张（A6）/ HIGH/CRITICAL economic routing（A4+）；
- ❌ memory system / self-learning / Agent OS 化。
（以上全部 = v0.5 non-MVP 列表 + NOT_REQUIRED_FOR_MVP，进入 mainline 前须用户显式 scope 批准。）

## 11. PH-1 gap table（只列具体缺口）

| gap | 受影响角色 | blocking / non-blocking | 最小未来修复（非本任务实现） |
|---|---|---|---|
| GAP-PH1-01：agent 名硬编码（白名单 + role 绑定 + CLI 分支 + 上游依赖表） | Executor / Validator / Reviewer | non-blocking | role→agent binding 配置化（MVP FROZEN 块已标 FUTURE_IMPROVEMENT）：单张配置表映射 role → agent → CLI adapter → 上游依赖 → 模型层语义；router/adapters/runner 消费同一表（静态加载即可，不需要动态插件加载） |
| GAP-PH1-02：Executor 模型层 Hermes 专属（A0 发现 / A3 env / A5 fallback） | Executor | non-blocking | 把 cost-classify + model-override + fallback 决策抽象为 per-executor adapter 契约（CLI 参数模板 + 模型 env 映射 + guard 语义声明）；A0 授权 authority 不变（唯一付费闸） |
| GAP-PH1-03：Reviewer CLI 发现仅 Codex 官方布局 | Reviewer | non-blocking | 通用 CLI 发现表（`shutil.which` + 已知安装布局枚举 + 版本探测），替换 codex 专属 fallback |

## 12. 本文件维护规则

- 与 PROJECT_STATE / README 的角色表述冲突时：PROJECT_STATE v0.5「MVP FROZEN」块为 frozen
  authority；本文件为细化契约；README 为产品摘要。三者不得互相矛盾——发现漂移以正式 TASK 修正。
- 新增/替换角色、修改分类或 gap 表 = 需要新 runtime 证据 + 正式 TASK（post-freeze opt-in）。
- 本文件遵守 Anti-Bloat Policy：引用而非复制 PROJECT_STATE / policy / runtime 细节。
