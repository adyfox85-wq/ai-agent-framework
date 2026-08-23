# 协议迁移规划 — PROTOCOL MIGRATION PLAN

- 任务：TASK-AF-INIT-002
- 类型：documentation / project-initialization
- 日期：2026-08-23
- 状态：规划完成（仅分析，未迁移任何文件）
- 来源：`D:\AdyAI\guoxue-skills-lab\docs\agent\`（7 个文件，只读分析）
- 设计依据：`D:\AdyAI\guoxue-skills-lab\docs\agent\AGENT_FRAMEWORK_EXTRACTION_PLAN.md`（TASK-AF-001 抽离方案）

---

## 一、来源文件清单与逐文件分析

### 1. AGENT_PROTOCOL.md（4927B，93 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 多 Agent 协作**总原则**：四角色分工表、单一修改者原则、TASK 文件驱动规则、RESULT 记录规则、禁止修改区域、红线（offline-first 等）、项目状态摘要、H5 MVP 目标 |
| 是否进入 Framework | ✅ 进入（原则层核心资产） |
| 目标位置 | `protocols/agent-protocol.md` |
| 需要通用化改写 | ✅ 需要（中-重度） |
| 需删除的项目专属内容 | ① 标题"观微记 H5 + 国学推演 skills 项目" → 通用化；② 关键路径三行（`D:\AdyAI\guoxue-skills-lab`、`D:\guoxue-skills-acceptance`、`C:\Users\Admin\.workbuddy\skills`）→ 参数化 `{{PROJECT_ROOT}}` / `{{ACCEPTANCE_DIR}}` / `{{DEPLOY_DIR}}`；③ 禁止区域表中项目专属路径（`upstream_export/`、`workbuddy_skills/`、`frontend/`）→ 通用化为规则（冻结快照区 / 核心逻辑区 / 未创建工程区）；④ 红线"推演 offline-first"→ 通用化为 `{{CORE_ENGINE}}` 保持离线；⑤ 第 6 节项目状态摘要（Phase 10.5/10.6、Git `da41989`）→ 整体移除；⑥ 第 7 节 H5 MVP 目标 → 整体移除（项目专属） |

### 2. WORKFLOW.md（9606B，198 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 工作流协议（**流程层核心资产**）：任务生命周期状态机（DRAFT→DONE + VERIFY_FAILED→FIX_REQUIRED 回流）、TASK / RESULT / REVIEW 三规范、任务元数据 11 字段、修改权限原则、人工介入条件、验收失败回流操作细则 |
| 是否进入 Framework | ✅ 进入（流程层，最重要） |
| 目标位置 | `protocols/workflow.md` |
| 需要通用化改写 | ✅ 需要（中度） |
| 需删除的项目专属内容 | ① `guoxue-skills-lab` 项目名引用 → 通用化；② `workbuddy_skills/` 推演核心 → 通用化"核心逻辑区"；③ 角色工具名（ChatGPT / Hermes+DeepSeek V4 / Workbuddy+H3 / Codex）→ 保留为示例值，标注 `{{ROLE_MAP}}` 可配置；④ `docs/tasks/`、`docs/reviews/` 相对路径 → **保留**（作为框架目录约定）；⑤ 版本记录保留但标注来源（v1.1 ← 旧项目 TASK-AGENT-003） |

### 3. ROUTING_RULES.md（4296B，80 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 路由规则（路由层）：任务类型→执行 Agent 映射表（development / verification / architecture_review / documentation）、路由判定流程、混合任务串行链、ChatGPT→Agent 交付规范、人工介入场景 |
| 是否进入 Framework | ✅ 进入（路由层） |
| 目标位置 | `protocols/routing-rules.md` |
| 需要通用化改写 | ✅ 需要（中度） |
| 需删除的项目专属内容 | ① 执行 Agent 具体工具名（Hermes+DeepSeek V4、Workbuddy+H3）→ `{{ROLE_MAP}}` 配置化，保留示例值；② "ChatGPT→Agent 交付规范" → 通用化为"规划层→执行层交付规范"；③ `docs/tasks/` 相对路径 → 保留；④ 版本记录保留（标注来源） |

### 4. REPORTING_PROTOCOL.md（3873B，80 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 汇报协议（汇报层）：统一 9 项结果摘要、5 个汇报状态（DONE / FAILED / BLOCKED / NEED_HUMAN / WAITING_DEPENDENCY）、汇报流程、异常状态处理 |
| 是否进入 Framework | ✅ 进入（汇报层） |
| 目标位置 | `protocols/reporting-protocol.md` |
| 需要通用化改写 | ✅ 需要（轻度） |
| 需删除的项目专属内容 | ① "返回规划层（ChatGPT / Ady）" → 通用化"规划层 / 人工"；② 角色名称 → 参数化 / 示例值；③ `docs/tasks/`、`docs/reviews/` 相对路径 → 保留；④ 版本记录保留（标注来源） |

### 5. TASK_TEMPLATE.md（3014B，106 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 标准任务模板（模板层）：17 项任务文件模板 + 字段说明简表 |
| 是否进入 Framework | ✅ 进入（模板层） |
| 目标位置 | `templates/task-template.md` |
| 需要通用化改写 | ✅ 需要（轻度） |
| 需删除的项目专属内容 | ① "ChatGPT（或 Ady）生成任务文件" → 通用化"规划层生成"；② 元数据引用 `WORKFLOW.md` → 改为引用 `protocols/workflow.md`；③ `docs/tasks/` 路径 → 保留为约定 |

### 6. CURRENT_STATUS.md（3039B，71 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 项目**动态状态文件**：Git 基线、Phase 版本、H5 进度、MVP 目标、待办 |
| 是否进入 Framework | ❌ 内容不进入（全部是 guoxue-skills-lab 专属状态） |
| 目标位置 | 不迁移（留在旧项目继续使用） |
| 需要通用化改写 | 不适用 |
| 需删除的项目专属内容 | 全部（内容留在旧项目） |
| 附加建议 | **状态文件机制**值得借鉴：建议 v0.2 在 `templates/` 提供 `status-template.md`（状态文件模板），由各项目自行维护实例——机制通用、内容专属 |

### 7. AGENT_FRAMEWORK_EXTRACTION_PLAN.md（11118B，186 行）

| 项 | 内容 |
| --- | --- |
| 作用 | 框架**抽离设计方案**（TASK-AF-001 产出）：资产盘点、通用/专属分离、未来结构建议、迁移策略、版本规划。本规划（TASK-AF-INIT-002）的设计依据 |
| 是否进入 Framework | ⚠️ 建议作为**框架设计文档存档**，不进入 protocols/ |
| 目标位置 | `docs/agent-framework-extraction-plan.md`（建议后续任务复制存档，本任务不执行） |
| 需要通用化改写 | 不适用（作为历史设计文档原样存档） |
| 需删除的项目专属内容 | 无（存档性质，保留完整历史） |

---

## 二、汇总：进入 Framework 清单

| 文件 | 目标位置 | 改写程度 | 迁移阶段 |
| --- | --- | --- | --- |
| AGENT_PROTOCOL.md | `protocols/agent-protocol.md` | 中-重度 | 阶段 1 |
| WORKFLOW.md | `protocols/workflow.md` | 中度 | 阶段 1 |
| ROUTING_RULES.md | `protocols/routing-rules.md` | 中度 | 阶段 1 |
| REPORTING_PROTOCOL.md | `protocols/reporting-protocol.md` | 轻度 | 阶段 1 |
| TASK_TEMPLATE.md | `templates/task-template.md` | 轻度 | 阶段 2 |
| CURRENT_STATUS.md | ❌ 不迁移（机制借鉴 → v0.2 status-template） | — | — |
| AGENT_FRAMEWORK_EXTRACTION_PLAN.md | `docs/`（设计文档存档） | 原样 | 阶段 3 |

**结论**：5 个协议/模板文件进入 Framework；1 个状态文件只借鉴机制不迁内容；1 个设计文档建议存档。

---

## 三、迁移顺序建议

总策略：**复制 + 通用化改写，不做 `git mv`，不删除旧项目文件**（与 AGENT_FRAMEWORK_EXTRACTION_PLAN.md 第四部分一致）。

```text
阶段 0：git init + 首次提交（需 Ady 批准；当前项目尚未初始化 git）
阶段 1：protocols/ 四个协议（依赖顺序）
        agent-protocol → workflow → routing-rules → reporting-protocol
        （总原则 → 流程 → 路由 → 汇报，后者引用前者）
阶段 2：templates/ 三个模板
        task-template.md（由 TASK_TEMPLATE 通用化）
        result-template.md（新增，按 WORKFLOW 第四部分 9 项）
        review-template.md（新增，按 WORKFLOW 第五部分 6 项）
阶段 3：docs/ 框架文档
        agent-framework-extraction-plan.md（设计文档存档）
        getting-started.md（新项目接入指南）
        migration-guide.md（存量项目迁移指南）
        versioning.md（版本策略，v0.1/v0.2/v1.0 路线）
阶段 4：examples/ 示例
        虚构项目完整任务链（TASK-demo → RESULT → REVIEW）
```

每阶段独立成任务（建议编号 TASK-AF-003+），逐个验收，不一次全做。

---

## 四、通用化改写原则（供实施阶段执行）

1. **机制与内容分离**：Framework 提供机制（协议、模板、状态机）；项目提供内容（实例、状态）。
2. **不引用项目路径**：`D:\AdyAI\guoxue-skills-lab` 等一律替换为 `{{PROJECT_ROOT}}` 等占位符。
3. **角色工具名配置化**：ChatGPT / Hermes / Workbuddy / Codex 保留为**示例值**，声明 `{{ROLE_MAP}}` 可由项目配置。
4. **相对目录约定保留**：`docs/tasks/`、`docs/reviews/` 作为框架目录约定保留。
5. **来源可追溯**：改写后文件头部注明"基于 guoxue-skills-lab docs/agent/ 原文件通用化，原版本 vX.Y"。

---

## 五、前置条件与本任务边界

- ✅ 本任务（TASK-AF-INIT-002）已完成：只输出本规划文档，**未迁移任何文件**，未修改 guoxue-skills-lab，未修改 README.md / PROJECT_SCOPE.md。
- ⚠️ **Git 状态**：当前 `ai-agent-framework/` 尚未初始化 git 仓库，无法产出 git status / diff / commit hash。是否需要 git init 需 Ady 决定（阶段 0）。
- 风险：无（本任务只读分析 + 新建一个文档）。
- 未完成事项：实际迁移（阶段 0-4）未执行，等待后续任务授权。
