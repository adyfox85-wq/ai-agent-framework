# AI Agent Framework v0.2

AI 工作协作基础设施（多 Agent 协作框架）——通过 `TASK.md` 驱动多 Agent 协作：

`Planner -> TASK.md -> Router -> Hermes -> WorkBuddy -> Codex(optional) -> REPORT.md -> Planner`

Router 可能跳过 Hermes（纯复核/视觉任务）；Codex 在代码/架构/高风险审查时追加。

## 定位

- 用于沉淀可复用的 AI 工作协作体系（Agent 角色协议、TASK 任务机制、路由、验收、汇报）
- 服务所有 AI 协作项目，**不绑定任何具体业务**
- v0.2 为已验证的自动化 MVP（真实项目连续试跑通过，回归基线 52 passed）

## 核心机制

- **TASK.md 是唯一正式执行入口**（含目标/允许修改/禁止修改/验收标准）
- **Router** 按任务类型决定执行链：执行类 → `hermes -> workbuddy`；代码/架构高风险追加 `codex`；纯复核/视觉 → `workbuddy`
- **REPORT.md 是结果载体**（Current Status / Route / Agent Results / Unresolved Issues / Planner Handoff），供下一轮 Planner 读取

## Requirements

- Python 3.11+
- Hermes CLI 可用（`hermes`）——见 https://hermes-agent.nousresearch.com
- Tencent CodeBuddy/WorkBuddy CLI 可用（`codebuddy`）——腾讯 CodeBuddy 官方 CLI
- Codex CLI 可用（`codex`，仅当路由包含 Codex 时需要）——OpenAI Codex CLI

> 这些 Agent CLI 是本框架的执行后端。运行时会检测各 CLI 是否可用；
> 缺失的 Agent 会以 `WAITING` 状态在 REPORT 中标记，不会静默跳过。

## 使用方式（Quick Start）

```powershell
# 1. 准备 TASK 文件（可参考 templates/TASK.md 的格式）
#    TASK 需包含：Objective / Requirements / Scope 禁止事项 / Acceptance Criteria

# 2. 先 dry-run 确认路由
python run.py <TASK.md> --workspace <业务工作区> --output <输出目录> --dry-run

# 3. 确认路由后正式运行
python run.py <TASK.md> --workspace <业务工作区> --output <输出目录>

# 4. 从失败点恢复（复用已完成 Agent 结果）
python run.py <TASK.md> --workspace <业务工作区> --output <输出目录> --resume-from <输出目录>
```

最终机器交接物是输出目录中的 `REPORT.md`。

## 新用户使用说明

1. 先理解流程：**TASK 是唯一输入**，Router 决定执行链，Agent 依次执行/复核，REPORT 是结果载体
2. 用 `templates/TASK.md` 创建自己的第一个 TASK（目标 + 允许/禁止 + 验收标准）
3. 始终先 `--dry-run` 看 `route.json`，再正式运行
4. 执行类任务需要 `hermes`；验收需要 `codebuddy`；代码/架构高风险审查需要 `codex`（按需安装）
5. 测试：`uv run --with pytest python -m pytest tests/ -q`（基线 52 passed）

## Agent CLI 集成说明

- Hermes：非交互单查询（`hermes chat --in <workspace> -q <prompt> -Q`），完整 prompt 通过 `-q` 传入
- WorkBuddy/CodeBuddy：官方 headless（`codebuddy -p --output-format text -y`），**完整 prompt 经 stdin 传入**（避免 Windows 命令行长度限制）；运行设 `CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS=1`
- Codex：非交互只读审查（`codex exec --sandbox read-only --cd <workspace> --skip-git-repo-check -`），prompt 经 stdin 传入

## Bootstrap checks

```powershell
hermes --version
codebuddy --version
codex --version
python --version
```

任一 Agent 命令缺失时，运行停止并标记 `WAITING`，在 `REPORT.md` 记录缺失命令，不会静默跳过验证/审查。

## 测试

```powershell
uv run --with pytest python -m pytest tests/ -q
```

回归基线：52 passed。

## 边界

- 不修改 Hermes / WorkBuddy 配置
- 不涉及账号 / token
- 不创建自动化程序、launcher、消息总线
- 业务项目只作为被驱动的工作区，Framework 仓库不包含业务代码

## 版本

- v0.2：自动化 MVP（已验证，Release Candidate）
- v0.3：未启动
