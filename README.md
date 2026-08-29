# AI Agent Framework v0.4

**本地多 Agent 协作框架** —— 减少你在 Planner / Executor / Validator / Reviewer 之间手工复制粘贴和传话的工作。

```
Planner → Copy TASK → Ctrl+Alt+A → Bridge → Validation → Boundary Check
       → Lifecycle → Router → Hermes → WorkBuddy → Codex(optional)
       → REPORT → Copy Report → Planner
```

你的角色从“搬运工”变成“规划者 + 最终决策者”：你（或你的 AI Planner）输出一份标准 TASK，Framework 负责调度各 Agent 执行、复核、审查，最后把 REPORT 交回给你。

---

## 它是什么 / 不是什么

**是**：
- 本地运行的多 Agent 协作引擎（共享工作流，不绑定具体业务）
- 一个项目一份正式输入（TASK）、一套机器状态（task.json）、一份结果（REPORT.md）
- 业务代码仍保存在业务项目自己的目录，Framework 只是驱动它的引擎

**不是**：
- ChatGPT / Hermes / Codex / WorkBuddy 的替代品
- IDE、SaaS、dashboard
- AutoGPT 式自主循环、自动无限 Agent
- 自动创建下一 TASK、自动修改项目 Scope
- 自动写回 ChatGPT（Copy Report 后仍需你粘贴）

## 角色

| 角色 | 谁 | 职责 |
|---|---|---|
| Planner | ChatGPT 或**任何能输出标准 AAF TASK 文本的 AI** | 输出 TASK、验收 REPORT、决定下一步 |
| Executor | Hermes | 执行任务、产出结果 |
| Validator | WorkBuddy / CodeBuddy | 独立复核（不默认相信前序结果） |
| Reviewer | Codex（按路由需要） | 代码/架构/高风险只读审查 |
| Router | AI Agent Framework | 决定执行链 |
| Result | REPORT / Planner Handoff | 交回 Planner 的机器可读结果 |

> Planner 不要求必须是 ChatGPT。只要能输出标准 AAF TASK 文本即可。

---

## Requirements

**Required**
- Windows（当前 Bridge 主要按 Windows 实现）
- Python 3.11+
- Git（clone 仓库用；业务项目不一定强制）
- Hermes CLI（`hermes`）—— https://hermes-agent.nousresearch.com
- WorkBuddy / CodeBuddy CLI（`codebuddy`）

**Conditional**
- Codex CLI（`codex`）—— 当 Router 选择 Codex 审查时需要

> 这些 Agent CLI **不包含在 Framework 仓库中**，需要你单独安装、登录和配置。

## Installation

```bash
git clone https://github.com/adyfox85-wq/ai-agent-framework.git
cd ai-agent-framework
```

> 当前项目**尚未打包成 pip package / installer**，现阶段通过 clone 仓库运行。
> （不要运行 `pip install ai-agent-framework` —— 仓库暂不支持。）

## Bootstrap Check

```bash
python --version
hermes --version
codebuddy --version
codex --version   # 仅当路由包含 Codex 时需要
```

任一 Agent CLI 缺失时，Framework 会在该阶段标记错误/等待，不会静默跳过。

---

## ⚠️ 先启动 Bridge（很重要）

**使用 Ctrl+Alt+A 之前，必须先启动 Bridge：**

```bash
cd <你的 ai-agent-framework 目录>
python -m bridge.main
```

如果 Bridge 没运行，**Ctrl+Alt+A 不会有任何反应**。这是真实使用中用户第一个踩到的问题。

Bridge 启动后会显示：

```
AAF Bridge 运行中 | 热键: Ctrl+Alt+A | 项目: '你的项目名'
```

（Bridge 当前**不是开机自启动**，需要每次手动启动。）

## Bridge 配置

默认配置路径：`%USERPROFILE%\.aaf-bridge\config.json`

```json
{
  "hotkey": "ctrl+alt+a",
  "current_project": "My Project",
  "current_workspace": "D:\\path\\to\\my-project"
}
```

| 字段 | 含义 |
|---|---|
| `current_project` | 给人看的项目名称 |
| `current_workspace` | 本次正式任务要操作的业务项目绝对路径 |
| `hotkey` | 默认 `ctrl+alt+a` |

- 配置支持**热加载**：修改保存后通常无需重启 Bridge
- **Project binding 是当前正式方式**：TASK 里的 Workspace 必须与 Bridge 当前 Workspace 一致，否则 Bridge 会拒绝执行
- “自动切换项目”是未来想法，当前**没有**自动 switch 能力

## Planner TASK Format

最小、可直接复制的示例（放在**纯文本代码块**中输出）：

```
AAF_TASK_BEGIN
Task ID: DEMO-001
Task Name: Demo Task
Workspace: D:\path\to\project

Objective:
做一件事，说清楚目标和边界。

Acceptance:
1. 完成标准
2. 可验证结果
AAF_TASK_END
```

**推荐把关键字段写成单行**：

```
Task ID: DEMO-001
Task Name: Demo Task
Workspace: D:\path\to\project
```

而不是：

```
Task Name:
Demo Task
```

**必须提醒 Planner**：
- 在纯文本代码块中输出 TASK，避免 Markdown 转义（`\_`、`\*`、行尾反斜杠）
- 不要把 `AAF_TASK_BEGIN` 写成 `AAF\_TASK\_BEGIN`
- 不要把 Task Name / Workspace 拆成多行

---

## Quick Start（完整 12 步）

1. **Clone Framework**（见 Installation）
2. **确认 Agent CLI**（见 Bootstrap Check）
3. **启动 Bridge**：`python -m bridge.main`
4. **配置目标 Project / Workspace**：编辑 `%USERPROFILE%\.aaf-bridge\config.json`
5. **让 Planner 输出标准 AAF TASK**（见 Planner TASK Format）
6. **Copy TASK**（复制 TASK 全文）
7. **按 Ctrl+Alt+A**
8. **确认弹窗**：检查 Task ID / Task Name / Project / Workspace
9. **点击 Execute**
10. **Framework 后台运行**（Hermes → WorkBuddy → Codex 依次执行）
11. **完成后点击 Copy Report**
12. **回到 Planner 粘贴**（Planner 阅读 REPORT 决定下一步）

> 更详细的分步说明见 [docs/QUICKSTART.md](docs/QUICKSTART.md)

## 运行期间能做什么

**可以**：看视频、浏览网页、使用 ChatGPT / Gemini 等聊天工具、做其他普通电脑操作。

**谨慎**：
- 不要同时让另一个 Hermes / WorkBuddy / Codex 修改同一个 workspace
- 不要重复提交相同 Task ID
- 不要在同一项目上启动两个相互冲突的写任务

---

## Runtime Artifacts

业务 Workspace 的 `.aaf/` 会保存 Framework 状态与运行产物：

```
.aaf/
├── <Task-ID>/
│   ├── task.json          # 执行生命周期状态
│   ├── route.json         # 执行链路由
│   ├── run.json           # 本轮运行结果
│   ├── boundary.json      # 边界检查结果
│   ├── context_manifest.json  # Stage Context Packet 引用清单（TASK/stage artifacts 的 path+hash）
│   ├── REPORT.md          # 正式结果（Task Reference + 摘要，不复制全文）
│   ├── hermes_result.md   # Agent 完整 narrative（追溯）
│   ├── hermes_result.json # Agent 结构化短结果（verdict/commit/changed_files/evidence_paths）
│   ├── workbuddy_result.md / workbuddy_result.json
│   └── codex_result.md / codex_result.json
├── archive/               # 显式归档的任务包
└── sessions/              # Session rollover 材料
```

> 新协议（Anti-Bloat Policy：`docs/internal/AAF_TASK_EXECUTION_POLICY.md`）：
> 下游 Agent prompt 只接收 TASK 引用 + 结构化摘要 + artifact 路径，不再默认
> 注入上游 narrative 全文；REPORT 不再复制整份 Original Task。

## Lifecycle

`CREATED` → `RUNNING` → `WAITING` / `SUCCESS` / `FAILED`

> `ARCHIVED` **不是** task status（归档是存储状态，不改变执行状态）。

## Resume（从失败阶段继续）

某个 Agent 阶段出现 `FRAMEWORK_ERROR` 时，Framework 可以通过 resume **复用已经成功的 Agent 结果，只继续失败阶段**。

真实场景示例（已泛化）：

```
Hermes ✅  WorkBuddy ✅  Codex command error ❌
→ 修复环境（如缺失 CLI）
→ resume
→ 复用 Hermes / WorkBuddy 结果
→ 仅重新执行 Codex
```

```bash
python run.py <TASK.md> --workspace <业务工作区> \
  --output <输出目录> --resume-from <输出目录>
```

## Task Archive

- 终态任务（SUCCESS / WAITING / FAILED）可以**显式** archive
- CREATED / RUNNING 不可 archive
- 归档**不会删除**正式 artifacts，也不会改变 Task Status

## Session Continuity

同项目对话太长时，可以**显式 rollover** 生成承接材料：

```bash
python -m ai_agent_framework.session_cli rollover --workspace D:\path\to\project \
  --project "My Project" --goal "当前核心目标" --boundaries "冻结边界..."
```

生成：
- `SESSION_SUMMARY.md`
- `NEXT_SESSION_START.md`

强调：**不保存全部聊天、不做无限记忆、不自动创建新 ChatGPT 会话、不在每个 TASK 后自动生成**。

## Project Boundary Control

`PROJECT_SCOPE.md` 是正式边界来源，表达：Core Goal / Current Scope / Frozen Boundaries / Backlog。

核心原则：**AI suggestion ≠ current project requirement**（新想法不自动进入当前 Scope）。

Boundary Check 是 **warning-first**：检查结果不默认阻断 Router；显式触碰 Frozen Boundary（如明确路径）会产生 HIGH warning。

```bash
python -m ai_agent_framework.project_boundary_cli show --workspace D:\path\to\project
python -m ai_agent_framework.project_boundary_cli check <TASK.md> --workspace D:\path\to\project
```

> 始终显式传 `--workspace <业务项目>`，否则 CLI 会使用当前目录（可能读到 Framework 仓库自身的 PROJECT_SCOPE）。

---

## Troubleshooting

常见问题速查（完整版见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)）：

| 症状 | 先检查 |
|---|---|
| Ctrl+Alt+A 完全没反应 | Bridge 是否启动？热键是否被占用？重启 Bridge |
| 提示缺少 AAF_TASK_BEGIN / END | 剪贴板不是标准 TASK，或存在 Markdown 转义 |
| 提示缺 Task ID / Name / Workspace | 推荐单行 `Task ID: VALUE` 格式 |
| Workspace mismatch | Bridge binding 与 TASK Workspace 不一致 |
| `MISSING_COMMAND: codex` | `codex --version`；Framework 支持 hash 目录 fallback |
| `TASK_ALREADY_EXISTS` | 同 Task ID 已提交过，不静默覆盖 |
| Framework WAITING | 看 REPORT / Planner Handoff 的 Unresolved Issues |
| Bridge 进程在但热键没反应 | 已启用自动自恢复（数秒内自动重建监听，有界重试）；持续异常可重启 Bridge |
| 看到两个 python.exe | uv venv 下可能是 shim + real 两层，不等于多开 |

## Known Limitations

- Bridge 当前主要按 Windows 实现
- Bridge **不自动开机启动**
- Project switching 当前需要修改 Bridge config（无自动切换）
- hotkey listener 偶发失活已有自动自恢复（RW-012 SOLVED）：健康轮询检测异常后自动重建监听（有界重试，不重启 Bridge）；恢复失败保持 Tray / 状态窗口可见
- Planner TASK parser 当前对部分换行格式较严格（推荐单行字段）
- 尚无一键 installer / pip package
- 不自动写回 ChatGPT（Copy Report 后仍需用户粘贴到 Planner）
- 不自动生成下一 TASK

---

## Real-World Validation

v0.3 已在真实业务项目中完成一次完整链路验证：

```
Planner → Bridge → Hermes → WorkBuddy → Codex → REPORT
→ environment hotfix（Codex CLI 升级后命令发现修复）
→ resume → SUCCESS
```

期间发现并修复的真实问题（均已解决或记录）：
1. Codex 自动升级更换 hash 目录 → `MISSING_COMMAND: codex` → 已支持 fallback 发现（hotfix `7cbf594`）
2. hotkey listener 偶发失效 → 已实现自动自恢复（RW-012 SOLVED）
3. Bridge 必须先启动才能响应热键（已写进 Quick Start）

## 版本

| 版本 | 状态 |
|---|---|
| v0.2 | 历史自动化 MVP |
| v0.3 | **CLOSED / stable personal-use baseline** |
| v0.4 | **FROZEN / RELEASE READY（2026-08-29 Final Acceptance PASS；implementation baseline `1d3771fe8220e1b2e21c774840d680ec9f2dce61`；tag `v0.4`；最终交接见 docs/internal/handoffs/AI-Agent-Framework-v0.4-CLOSING-HANDOFF-2026-08-29.md）** |
| v0.5+ | 未启动（仅在用户显式启动 v0.5 / Model Routing / 新功能开发时开启） |

## 测试

```bash
python -m pytest tests/ -q
```

回归基线：**198 passed**（v0.3 closure 191 + Codex discovery hotfix 7）
