# AAF-TASK-002-REPORT

- Task: AAF-TASK-002 (AI Agent Framework v0.2 Formal Migration Plan)
- Date: 2026-08-25
- Type: readonly planning
- Status: PLAN ONLY（未执行任何迁移/Git/文件操作）
- 依据: AAF-TASK-001-REPORT.md 实际扫描结果

---

## 1. Migration Target Structure

迁移后的正式目录目标结构（`<PROJECT_ROOT>`）：

```
ai-agent-framework/                          # formal 根（保留现有 .git）
├── README.md                                # ★ 替换为 v0.2 版（来自 prototype）
├── PROJECT_STATE.md                         # ★ 唯一 Living State 入口（已在，保持一致）
├── IDEA.md                                  # v0.1 历史保留
├── run.py                                   # ★ 迁移（prototype）
├── ai_agent_framework/                      # ★ 迁移（核心代码 5 .py）
│   ├── __init__.py
│   ├── adapters.py
│   ├── report.py
│   ├── router.py
│   └── runner.py
├── tests/                                   # ★ 迁移（4 测试）
│   ├── test_adapters.py
│   ├── test_report.py
│   ├── test_router.py
│   └── test_runner.py
├── templates/
│   └── TASK.md                              # ★ 迁移（formal 目录已存在、为空）
├── docs/
│   ├── PROJECT_SCOPE.md                     # v0.1 历史保留
│   ├── PROTOCOL_MIGRATION_PLAN.md           # v0.1 历史保留（迁移完成后标记为已执行/更新）
│   ├── AUTOMATION_NOTES.md                  # ★ 迁移（prototype docs/）
│   ├── status/
│   │   └── AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md   # ◐ 从 formal 根归档
│   └── handoffs/
│       └── AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md      # ◐ 从 formal 根归档
├── protocols/                               # 暂时保留（空目录，后续协议文档）
├── examples/                                # 暂时保留（空目录，后续示例）
├── scripts/                                 # 后续再补充（自动化脚本）
└── pyproject.toml / .gitignore / LICENSE    # 后续再补充（配置文件未来位置）
```

**目录分类**：

| 分类 | 目录 |
|---|---|
| 必须存在 | `ai_agent_framework/` `tests/` `templates/` `docs/` 及根文件 |
| 暂时保留（空） | `protocols/` `examples/`（git 不跟踪空目录，需 .gitkeep 或等有内容） |
| 后续再补充 | `scripts/`、`pyproject.toml`、`.gitignore`、`LICENSE`（v0.3 / release preparation） |

---

## 2. File Migration Matrix

### A. 必须迁移内容（prototype → formal）

| # | 源（prototype） | 目标（formal） | 原因 | 覆盖已有？ |
|---|---|---|---|---|
| 1 | `ai_agent_framework/`（5 .py） | `ai_agent_framework/` | Framework 核心代码 | 无冲突（formal 无此目录） |
| 2 | `run.py` | `run.py` | CLI 入口 | 无冲突 |
| 3 | `tests/`（4 测试） | `tests/` | 回归测试（52 passed） | 无冲突 |
| 4 | `templates/TASK.md` | `templates/TASK.md` | 标准任务模板 | formal 目录空，无文件冲突 |
| 5 | `README.md`（v0.2，1,329B） | `README.md` | v0.2 文档 | **覆盖 v0.1 README（先备份）** |
| 6 | `docs/AUTOMATION_NOTES.md` | `docs/AUTOMATION_NOTES.md` | 自动化说明 | 无冲突 |

**迁移方式**：复制（copy），**不移动**——prototype 原样保留作为回滚兜底。

### B. Formal 原有内容保留

| 内容 | 处理 |
|---|---|
| `.git` + v0.1 baseline commit（`8a8ff60`） | 保留全部历史 |
| `IDEA.md` | 历史文档保留（v0.1 项目构想） |
| `docs/PROJECT_SCOPE.md` | v0.1 历史保留 |
| `docs/PROTOCOL_MIGRATION_PLAN.md` | v0.1 历史保留；迁移完成后建议追加状态更新（"已按计划执行"，属后续任务） |
| `PROJECT_STATE.md` | 保留为唯一 Living State（与 prototype 一致，无需复制动作） |
| 2 个 HANDOFF | 从根目录**归档**至 `docs/status/` 与 `docs/handoffs/`（见第 3 节） |

### C. 不迁移内容（排除理由）

| 内容 | 排除原因 |
|---|---|
| `.aaf-backup/` | 开发期备份（14 个文件），正式仓库不需要；如需保留历史可整体压缩存档 |
| `.aaf-dry-run/` | 早期测试产物 |
| `.aaf-test-output/` | 测试输出（9 子目录 34 文件） |
| `.aaf-test-tasks/` | 测试任务（含 TASK-005/008 重建件） |
| `.aaf-test-workspace/` | 测试工作区（hello.txt） |
| `.pytest_cache/`、`__pycache__/` | 缓存，必须由 .gitignore 排除 |

> 注：以上内容**保留在 prototype 目录不删除**；只是不进正式仓库。

---

## 3. Conflict Resolution Rules

### README.md —— **替换 + 历史保留**

- 采用 **替换**：formal 根目录 README.md 更新为 prototype 的 v0.2 版（内容更完整：定位/版本/结构/边界）
- **备份**：覆盖前将 v0.1 README 复制为 `docs/README.md.v0.1-baseline`（或由 git 历史天然保留——v0.1 README 已在 commit `8a8ff60` 中，git 层已有备份）
- 不合并（v0.1 与 v0.2 定位一致，v0.2 是超集）

### PROJECT_STATE.md —— **唯一 Living State**

- **唯一维护位置 = formal 根目录**
- 当前两边内容完全一致（diff IDENTICAL）→ 无需迁移动作
- 迁移后**声明规则**：后续所有状态更新只写 formal 根目录版本；prototype 版本冻结不再更新（prototype 进入冻结态）

### HANDOFF 文件 —— **归档**

| 文件 | 当前（formal 根） | 归档目标 |
|---|---|---|
| `AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md` | 根目录 | `docs/status/` |
| `AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md` | 根目录 | `docs/handoffs/` |

- 采用 `git mv`（保留文件历史）或移动后 commit
- prototype 中的 `docs/status/`、`docs/handoffs/` 副本保留（历史）

---

## 4. Git Strategy

**原则**：保留 v0.1 baseline commit（`8a8ff60`），不 reset、不删历史、不重新 init。分支维持 `main`。

推荐 commit 顺序（在 formal 仓库执行，每步独立可回滚）：

| # | Commit | 内容 |
|---|---|---|
| 0 | （前置，不 commit） | 创建 `.gitignore`（排除 `__pycache__/` `.pytest_cache/` `.aaf-*/`） |
| 1 | `feat: migrate v0.2 core implementation from prototype` | `ai_agent_framework/` + `run.py` + `tests/` + `templates/TASK.md` + `.gitignore` |
| 2 | `docs: formalize v0.2 documentation` | README 替换 + `docs/AUTOMATION_NOTES.md` + HANDOFF 归档（git mv）+ `PROJECT_STATE.md` 纳入跟踪 |
| 3 | `chore: v0.2 release preparation` | 收尾：更新 `PROTOCOL_MIGRATION_PLAN.md` 状态、LICENSE 占位（如需要） |

> 每个 commit 前执行 `git status` 核对暂存清单，避免混入无关文件（沿用 TASK-003 教训：精确暂存）。

---

## 5. Rollback Strategy

迁移必须可回滚，三层兜底：

| 层 | 恢复方式 | 触发条件 |
|---|---|---|
| **Git 层** | 已 commit 后发现问题：`git revert <commit>`（保留历史）或 `git reset --hard 8a8ff60`（恢复到迁移前） | 验证阶段失败 |
| **文件层** | 被覆盖文件有备份（v0.1 README 在 git 历史 + 可选 docs 备份）；HANDOFF 用 git mv 天然可回滚 | 单个文件异常 |
| **prototype 层** | **迁移只复制不移动**——prototype 完整保留，任何情况下可从 prototype 重新迁移/重建正式仓库 | 最终兜底 |

**回滚触发条件**（第 6 节验证任一失败）：
- Python import 失败
- tests 回归 ≠ 52 passed
- smoke TASK 链路不通

---

## 6. Post Migration Verification Plan

迁移完成后（在 formal 目录 `<PROJECT_ROOT>` 内执行）：

| # | 验证项 | 命令/方法 | 通过标准 |
|---|---|---|---|
| 1 | Python 环境验证 | `python --version` + `python -c "import ai_agent_framework; print(ai_agent_framework.__file__)"` | 3.11.x；import 自 formal 目录 |
| 2 | tests 全量回归 | `uv run --with pytest python -m pytest tests/ -q` | 全绿 |
| 3 | 52 passed 基线确认 | 同上结果对比 prototype 基线 | 数量一致（52 passed） |
| 4 | 最小 smoke TASK（dry-run） | 用 `templates/TASK.md` 建简单执行类 TASK，`python run.py <task> --workspace <tmp> --output <tmp/out> --dry-run` | route.json 正确生成 |
| 5 | REPORT 输出验证 | 检查 dry-run 生成的 REPORT.md | 含 Current Status / Route / Original Task / Agent Results / Unresolved Issues / Planner Handoff |
| 6 | TASK → Router → Agent → REPORT 链路 | mock Agent 跑完整链（或真实最小 smoke：创建 hello.txt 类任务） | 闭环成功、REPORT 状态正确 |

> 说明：第 6 项若用真实 Agent 会消耗模型额度，建议先用 mock 验证链路；真实 smoke 可选（与 Ady 确认后执行）。

---

## 附：事实 vs 建议

- **事实**：目录结构、文件清单、git 状态、PROJECT_STATE 一致性均来自 AAF-TASK-001 真实扫描
- **建议**：本报告全部为迁移方案设计，未执行任何复制/移动/覆盖/Git 操作
- **边界确认**：未创建目录、未修改任何输入文件、未修改 Git、未安装依赖、未启动 v0.3
- **执行前提**：本计划获批后，需单独创建 migration TASK（建议 AAF-TASK-003）才可执行
