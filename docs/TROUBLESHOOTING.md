# AI Agent Framework — Troubleshooting

> 按症状速查。概念与流程见 [README](../README.md) / [QUICKSTART](QUICKSTART.md)。

## A. Ctrl+Alt+A 完全没反应

按顺序检查：

1. **Bridge 是否启动** —— 后台模式下看任务栏右下角是否有 AAF 托盘图标；调试模式下启动输出应包含 `AAF Bridge 运行中 | 热键: Ctrl+Alt+A`
2. **热键是否被占用** —— 是否有其他程序（截图/翻译/剪贴板工具）占用了 Ctrl+Alt+A。占用时 Bridge 会提示"热键冲突"并把状态显示为异常。处理：关闭占用程序，或修改 `%USERPROFILE%\.aaf-bridge\config.json` 的 `hotkey`（如 `ctrl+alt+b`），保存后 Bridge 自动热加载
3. **重启 Bridge** —— Tray 菜单 [重启 Bridge]；或调试模式关闭后重新启动

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

**处理**：后台模式用 Tray 菜单 [重启 Bridge]（当前实例自动替换，热键在新实例中重新注册）；调试模式关闭后重新 `python -m bridge.main`。

> 这是**已知非阻断 runtime issue**，不是正常预期行为。重启可恢复。

## I. 看到两个 python.exe（Bridge 相关）

- **uv venv 环境**：`venv\Scripts\python.exe`（shim）+ uv 缓存真实 python.exe（real）是**同一个逻辑实例的两层进程**，属正常现象。
- **后台模式多实例**：Bridge 启动时有单实例保护（命名 mutex），重复启动会被拒绝并提示。Tray [重启 Bridge] 的交接瞬间可能出现两个 pythonw（旧实例正在退出 + 新实例正在接管），持续约 1~2 秒，之后只剩一个——这是正常的重启交接窗口，不是双开。

## J. 后台模式看不到任何输出 / 启动失败

pythonw 无控制台，启动异常（如导入错误）会：

1. 弹窗提示"AAF Bridge — 启动失败"
2. 详情写入 `%USERPROFILE%\.aaf-bridge\bridge_error.log`

排查时先看该日志；仍无法解决再用调试方式 `python -m bridge.main` 复现（保留完整控制台输出）。

## K. Tray 图标不出现

- 先确认 Bridge 进程是否在运行（任务管理器 → 详情 → pythonw.exe）
- Explorer 重启（任务管理器 → Windows 资源管理器 → 重新启动）后 Tray 会自动重新注册
- 图标仍不出现 → 用调试方式启动查看是否有"Tray 启动失败"提示；Tray 失败不影响热键功能

## L. 状态窗口相关问题

**如何打开状态窗口**

- 右键任务栏右下角 AAF 图标 → **打开状态窗口**；双击图标也可打开
- 窗口已打开时再次点击菜单：不会创建重复窗口，而是复用并聚焦已有窗口
- 关闭状态窗口（点 X 或 [关闭]）**不会退出 Bridge** —— 需要时随时可再次打开

**状态窗口显示什么**

状态窗口是**只读观察界面**，每约 1 秒自动刷新，显示：当前项目 / Bridge 状态 / 热键 / Workspace、
当前任务（Task ID / Task Name / 当前阶段 / 当前 Agent / 已运行 / 最近活动 / 整体结果）、
整体进度（估算百分比 + 进度条）、当前阶段占比，
以及 Validation → Boundary → Hermes → WorkBuddy → Codex → Report 六阶段条
（✓ 已完成 / ▶ 进行中 / ○ 未开始 / ⏸ 等待处理 / ✗ 失败；进行中阶段高亮）。

**整体进度（估算）是什么意思？**

- **进度是估算值，不是精确剩余进度**：由固定阶段权重（Validation 5% / Boundary 5% /
  Hermes 45% / WorkBuddy 20% / Codex 20% / Report 5%）与阶段完成事实确定性计算，
  进度条旁标注「估算」。它不承诺剩余时间，不会随时间流逝自动增长
  （只有进行中阶段内部按 0%–50% 线性微调，60 分钟封顶）。
- **进度不是 canonical lifecycle**：任务的权威状态始终是 `task.json`
  （由 Framework runner 写入）。进度条只读展示，永不回写 task.json / run.json /
  route.json / boundary.json / REPORT.md / cancel.request 等任何状态文件。
- **100% 只在任务 SUCCESS 时保证**：SUCCESS → 100%（已完成）。
  FAILED 停在失败阶段之前（< 100%）；WAITING 停在已完成事实（不自动推进）；
  没有任务或 task.json 缺失时显示「暂无进度信息」（0%）。

**「⚠ 任务可能已停滞」是什么意思？**

- 触发条件：任务 status = RUNNING **且** last_activity_at 距今 ≥ 10 分钟
  （runner 每个阶段 / Agent 边界都会刷新 last_activity_at，停滞即代表无可观察活动）。
- **这只是"可疑"提示，不等于确定进程已死**：它只基于可观察活动信号，
  不做进程级判定（进程存活 ≠ 有进展，RUNNING ≠ alive）。
- **提示不会自动终止 / 修改任何任务状态**：不会自动 Resume / Cancel / Force Kill。
  请点 [查看日志] / [查看任务目录] 打开任务输出目录，检查
  `task.json` / `<agent>_prompt.md` / `<agent>_result.md` 等产物，
  判断是 Agent 仍在工作、等待外部输入，还是确实异常中断。
  如确认中断，可参考本文件 G（Framework WAITING）用 resume 恢复。

**状态窗口会不会改任务状态？**

不会。窗口只读取产物（task.json / route.json / boundary.json / REPORT.md / last_run.json / config.json），
不写任何文件；任务状态由 Framework（runner）自己写。窗口只读，所以**关闭它不会中断任务**。

**某些字段显示 — / 未知**

- 没有任务时显示"当前没有任务"，属正常空状态
- task.json 缺失或为旧版（无 Phase A 字段）时，字段显示 —（未知），不会报错
- 任务正在执行时"已运行 / 最近活动"每秒刷新；任务结束后显示最终时长

**Bridge 状态显示"异常"**

Tray 图标与状态窗口的 Bridge 状态来自热键监听健康检查（listener registered + loop alive）。
显示异常通常是热键注册失败或被占用 —— 参见本节 A（Ctrl+Alt+A 没反应）处理。

---

## 还没解决？

1. 查看 `%USERPROFILE%\.aaf-bridge\config.json` 是否合法 JSON
2. 查看业务项目 `.aaf\<Task-ID>\` 下的 `task.json` / `run.json` / `boundary.json` 状态
3. 把 REPORT + 相关状态文件给 Planner 分析
