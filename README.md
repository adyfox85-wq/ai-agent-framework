# AI Agent Framework v0.2

个人 AI 工作协作基础设施——通过 `TASK.md` 驱动多 Agent 协作：

`Planner -> TASK.md -> Router -> Hermes -> WorkBuddy -> Codex(optional) -> REPORT.md -> Planner`

Router 可能跳过 Hermes（纯复核/视觉任务）；Codex 在代码/架构/高风险审查时追加。

## 定位

- 用于沉淀个人 AI 工作协作体系（Agent 角色协议、TASK 任务机制、路由、验收、汇报）
- 服务未来所有 AI 协作项目，不属于具体业务项目
- v0.2 为已验证的自动化 MVP（真实项目连续试跑通过，回归基线 52 passed）

## 核心机制

- **TASK.md 是唯一正式执行入口**（含目标/允许修改/禁止修改/验收标准）
- **Router** 按任务类型决定执行链：执行类 → `hermes -> workbuddy`；代码/架构高风险追加 `codex`；纯复核/视觉 → `workbuddy`
- **REPORT.md 是结果载体**（Current Status / Route / Agent Results / Unresolved Issues / Planner Handoff），供下一轮 Planner 读取

## Requirements

- Python 3.11+
- Hermes CLI 可用（`hermes`）
- Tencent CodeBuddy/WorkBuddy CLI 可用（`codebuddy`）
- Codex CLI 可用（`codex`，仅当路由包含 Codex 时需要）

## 使用方式

在仓库目录运行：

```powershell
# 先 dry-run 确认路由
python run.py <TASK.md> --workspace <业务工作区> --output <输出目录> --dry-run

# 确认路由后正式运行
python run.py <TASK.md> --workspace <业务工作区> --output <输出目录>

# 从失败点恢复（复用已完成 Agent 结果）
python run.py <TASK.md> --workspace <业务工作区> --output <输出目录> --resume-from <输出目录>
```

最终机器交接物是输出目录中的 `REPORT.md`。

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
