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

> 注意：resume 只对**非终态**任务生效（如 runner 中断后残留 `RUNNING` 的现场，见
> FIX-001 后 terminal precedence §6A.2：SUCCESS / WAITING / FAILED / CANCELLED 一旦
> committed 不可被任何 late non-terminal update 降级回 RUNNING，resume 也不例外）。
> resume 会复用已完成 Agent 结果，只重跑缺失/失败的阶段（`FRAMEWORK_ERROR` 结果会被
> 重新执行）；若任务已是终态（WAITING / SUCCESS / FAILED / CANCELLED），resume 会被
> 拒绝并返回已有 REPORT——此时按上方处理（修改 TASK 或新 TASK）。

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
  FAILED 停在失败阶段之前（< 100%）；WAITING / CANCELLED 停在已完成事实（不自动推进）；
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

不会直接改。窗口只读取产物（task.json / route.json / boundary.json / REPORT.md /
last_run.json / config.json）；**停止当前任务**只写 `cancel.request`（外部请求，
非终态裁决），**强制停止**（必须二次确认）只终止已通过 11 项 ownership 三方验证的
任务进程树——两种操作都**不写 task.json / run.json / REPORT.md 终态**，最终状态
永远由 Framework（Core）裁决。关闭窗口不会中断任务。

**任务状态显示「已取消」（CANCELLED）是什么意思？**

- CANCELLED 是 v0.4 Phase E 的**合法终态**（cooperative soft cancel 收敛结果），表示任务被
  主动取消：已完成阶段的 Agent 结果保留，后续阶段未执行；`task.json / run.json / REPORT.md`
  三处状态一致为 CANCELLED。
- 触发方式（TASK-005-C 起）：状态窗口 [停止当前任务]（中文确认窗）→ 在任务输出目录
  `.aaf/<Task-ID>/` 写入 `cancel.request`
  （JSON：`{"task_id": "<Task-ID>", "requested_at": "<ISO 时间>", "request": "soft_cancel"}`）。
  Runner 在安全检查点读到后收敛；`cancel.request` 只是**外部请求，不是终态裁决**
  （最终状态由 Core 根据 `task.json` 裁决）。也可 CLI / 手动写文件触发。
- **状态窗口显示 CANCELLED 时**：查看 `task.json` 的 `terminal_reason`（CANCEL_REQUESTED /
  FORCE_CANCELLED）与 `cancel_mode`（soft / force）；确认已完成阶段的 `<agent>_result.md`
  仍保留。
- **late cancel 不会覆盖已完成任务**：任务已 SUCCESS / WAITING / FAILED 后再写
  cancel.request 会被吸收 / 忽略，终态不变（窗口显示「任务已先完成」）。
- **停止状态行怎么看**：窗口「停止状态」区分 正在运行 / 请求停止（等待安全退出）/
  正在取消（软取消超时仍未退出）/ 已取消 / 已完成 / 无法安全停止——这些是
  UI/control 状态（§6A.3），**不是** task.json 的合法 status。
- **Force Cancel（TASK-005-B API + TASK-005-C 用户按钮）**：
  `FrameworkLauncher.request_force_cancel(task_id)` 是唯一 force 入口；用户从状态窗口
  [强制停止] 按钮（仅当 backend 明确 force eligible 时出现）→ 红色风险确认窗二次
  确认后才调用——必须先有 soft cancel.request 且超过 `force_cancel_soft_timeout`
  （默认 30s）→ ownership verification（registry + control + live process 三方，11 项）
  全部通过 → 才执行 `taskkill /T /F`（只对 verified runner 进程树）→ 结构化 force
  evidence → Core recovery finalizer 收敛 CANCELLED。
  - **ownership 未验证（PID / creation time / 命令行 / workspace / task_id 任一不匹配、
    任务已终态、registry 已 SUPERSEDED / EXITED、进程已消失）→ REFUSE**，绝不降级成
    "看起来像"就杀（`refusal_reason` 以 `OWNERSHIP_` 开头）；窗口相应显示
    「无法安全停止」且不提供强制停止。
  - **soft timeout 不会自动 taskkill**（设计 §6A.11：必须显式 force 请求 + 二次确认）。
  - **force 收敛门槛（FIX-001）**：`request_force_cancel` 只把 `taskkill /T /F` 的
    **exit 0** 视为 verified successful termination（128 = 进程已不存在，不算成功 →
    fail closed，不调 finalizer）；Launcher 把 termination 关键事实（requested /
    observed / exit status / evidence path / verification result+checks）写入
    registry 后才会调用 Core finalizer，后者锁内逐项核对与 evidence 一致。
  - **诊断**：`~/.aaf-bridge/launches/<launch_id>.json`（registry）+ `.aaf/<Task-ID>/control.json`
    （task-owned）+ `~/.aaf-bridge/launches/<launch_id>.force-evidence.json`（force
    证据，**必须位于 canonical Bridge location**）三份记录可交叉核对。
  - 已知环境坑：本机 hermes venv 的 `python.exe` 是 uv 重定向壳——Popen 直连子与真实
    解释器是父子关系（pid 不同）。Launcher 会采纳 runner 自报身份（registry 跟随
    control），命令行校验按 runner entry + 参数（不含解释器 argv[0]）比较；进程树
    终止先杀 runner 树再补杀壳。**不要**手工用 registry 里的旧 pid 猜测。
- **恢复 finalizer（崩溃/强杀后收敛）**：`python -m ai_agent_framework.finalize_cancelled
  --task-id <ID> --workspace <WS> --output <OUT>` 把无终态的 RUNNING 任务收敛为 CANCELLED。
  - soft 收敛是**单一锁原子协议**：canonical identity 验证、terminal arbitration、
    `cancel.request` 验证与新 CANCELLED 提交在同一个 `state.lock` 临界区内完成
    （验证与提交之间不释放锁）；要求合法 matching `cancel.request`（`request=soft_cancel`、
    `task_id` 一致、`requested_at` 合法），缺失 / 损坏 / 不匹配 → exit code 6 安全失败，
    不修改 canonical。
  - **force 收敛（TASK-005-B + FIX-001）**：加 `--cancel-mode force --force-evidence <path>`——
    evidence 必须是 Launcher 在 verified termination 后生成的结构化 JSON **且位于
    canonical Bridge location**（`~/.aaf-bridge/launches/<launch_id>.force-evidence.json`）；
    `termination_exit_status` 必须 == 0；registry 必须独立记录 termination 关键事实并与
    evidence 逐项一致。finalizer 在锁内三方交叉验证（evidence ↔ control.json ↔
    canonical registry），伪造 / 非 canonical / 过期 / 不匹配 → exit code 6 安全失败
    （零 canonical 写）。已有终态 + force → 保留现有 terminal。
  - **request 写入也要锁（FIX-003）**：`cancel.request` 不是 terminal truth，
    **但** Framework-owned 的写入 / 替换 / consume（`write_cancel_request` /
    `consume_cancel_request`）与 recovery 共享同一 per-task `state.lock`——否则
    recovery 锁内验证的 evidence 仍可在 commit 前被替换 / 删除 / consume（authority
    evidence 必须 lock-stable）。锁获取失败 → 明确错误（`LockTimeout` / `LockError`），
    不写、不 consume、不 fallback 无锁写。手动写文件（如测试 / 临时验证）不受锁约束，
    但 recovery 锁内重新验证会拒绝损坏 / mismatch 的 evidence。
  - 已有终态（SUCCESS / WAITING / FAILED / CANCELLED）无 evidence 也会被保留，
    派生产物（run.json / REPORT.md）仍会补齐。
- **任务已结束但 run.json / REPORT.md 缺失（partial commit）**：Launcher wait thread
  检测到 canonical terminal 存在而派生产物不完整时，会自动调用 Core reconciliation
  （`python -m ai_agent_framework.reconcile --task-id <ID> --workspace <WS> --output <OUT>`，
  幂等）补齐跟随 canonical；`last_run.json` 始终镜像 canonical terminal，不按 exit code
  推导终态。
- 已取消任务无法直接重跑：`TASK.md` 仍在 `tasks/active/`（证据保留），重复提交会触发
  TASK_ALREADY_EXISTS；需要重跑时按常规流程处理（移除/重命名旧 active TASK 或走 resume 语义）。

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
