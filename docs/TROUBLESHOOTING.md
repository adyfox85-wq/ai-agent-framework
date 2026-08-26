# AI Agent Framework — Troubleshooting

> 按症状速查。概念与流程见 [README](../README.md) / [QUICKSTART](QUICKSTART.md)。

## A. Ctrl+Alt+A 完全没反应

按顺序检查：

1. **Bridge 是否启动** —— `python -m bridge.main` 是否在运行（启动输出应包含 `AAF Bridge 运行中 | 热键: Ctrl+Alt+A`）
2. **热键是否被占用** —— 是否有其他程序（截图/翻译/剪贴板工具）占用了 Ctrl+Alt+A
3. **重启 Bridge** —— 关闭后重新启动

## B. 提示缺少 AAF_TASK_BEGIN / AAF_TASK_END

剪贴板内容不是标准 AAF TASK，或存在 Markdown 转义。

**修复**：让 Planner 在**纯文本代码块**中输出 TASK，不要有 `\_`、`\*`、行尾反斜杠。不要把 `AAF_TASK_BEGIN` 写成 `AAF\_TASK\_BEGIN`。

## C. 提示缺 Task ID / Task Name / Workspace

TASK 字段格式不兼容当前 parser。

**修复**：使用单行字段格式：

```
Task ID: MY-001
Task Name: My Task
Workspace: D:\path\to\project
```

不要写成：

```
Task Name:
My Task
```

## D. Workspace mismatch

TASK 里的 `Workspace` 与 Bridge 配置的 `current_workspace` 不一致。

**修复**：编辑 `%USERPROFILE%\.aaf-bridge\config.json`，把 `current_workspace` 改成 TASK 的 Workspace（或改 TASK 的 Workspace）。当前版本无自动切换项目，必须手动对齐。

## E. MISSING_COMMAND: codex

Codex 阶段找不到命令。

**修复**：
1. 运行 `codex --version` 确认已安装
2. Framework v0.3 已支持 OpenAI Codex 的 hash 目录 fallback（自动升级换目录也能找到）
3. 如果仍失败：检查 Codex 是否真正安装、登录（`~/.codex/auth.json`）

## F. TASK_ALREADY_EXISTS

同 Task ID 已提交过。

**处理**：不静默覆盖。换一个新的 Task ID，或先处理已有任务（归档 / 删除）。

## G. Framework WAITING

任务停在 WAITING 状态。

**处理**：查看 `REPORT.md` / Planner Handoff 的 **Unresolved Issues**，按其中的返工项处理后重新规划（修改 TASK 或修复后新 TASK）。

> 注意：resume 只对 `FRAMEWORK_ERROR`（环境/框架错误）阶段重新执行；Agent 业务性失败（FAIL / REQUEST_CHANGE）的结果会被复用，任务通常仍停在 WAITING。

## H. Bridge 进程在但热键没反应

真实使用曾发现：**Bridge 进程存活但 hotkey listener 失效**。

**处理**：安全重启 Bridge（关闭后重新 `python -m bridge.main`）。

> 这是**已知非阻断 runtime issue**，不是正常预期行为。重启可恢复。

## I. 看到两个 python.exe（Bridge 相关）

uv venv 环境下，`venv\Scripts\python.exe`（shim）+ uv 缓存真实 python.exe（real）是**同一个逻辑实例的两层进程**。

**判断**：不要仅凭 `-m bridge.main` 的进程条数判断 Bridge 多开。检查父子进程链：若一个是另一个的子进程（且创建时间几乎相同），它们是同一实例。

---

## 还没解决？

1. 查看 `%USERPROFILE%\.aaf-bridge\config.json` 是否合法 JSON
2. 查看业务项目 `.aaf\<Task-ID>\` 下的 `task.json` / `run.json` / `boundary.json` 状态
3. 把 REPORT + 相关状态文件给 Planner 分析
