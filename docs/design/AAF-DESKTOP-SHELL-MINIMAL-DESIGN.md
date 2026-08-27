# AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md

> 文档类型: 设计规格（Design Specification）
> 任务: AAF-DESIGN-001 — Desktop Shell and Runtime Control Minimal Design
> 修订: AAF-DESIGN-001-FIX-001（2026-08-27）— 关闭 Codex 两个 blocking findings（Force Cancel 终态双写竞态、PID/token 防误杀协议未闭合）。权威修订见 §6A；§6/§8.3/§13.3/§14/§15/§16/§19 已同步修正。仅修订设计文档，不实现。
> 修订: AAF-DESIGN-001-FIX-002（2026-08-27）— 关闭 Codex 三个 blocking findings（①terminal commit 缺真正跨进程互斥；②terminal commit 后中断缺派生产物 reconciliation；③Launcher restart 缺独立可信的 ownership 恢复依据）。权威修订见 §6B；§6A/§15/§16/§19 已同步修正。仅修订设计文档，不实现。
> 修订: AAF-v0.4-TASK-001-FIX-001（2026-08-27）— 仅更新实现状态：Phase A（Runtime State Foundation）IMPLEMENTATION COMPLETE（commit 5a8b76a）；Design 规格不变；Phase B-F NOT STARTED。
> 日期: 2026-08-27
> 状态: **DESIGN COMPLETED / PHASE A IMPLEMENTATION COMPLETE / PHASE B-F NOT STARTED**
> 范围: 本任务只产出可执行的设计规格与实施拆分。**不实现** Tray / GUI / progress bar / cancel / autostart / project switching / packaging / heartbeat / 新 runtime schema。
> 关联 backlog: RW-003, RW-004, RW-005, RW-006, RW-010, RW-012, RW-014, RW-015, RW-016（见 `docs/internal/AAF_MASTER_BACKLOG.md` 中相应条目的 Design Reference 字段）
> 版本状态: v0.3 CLOSED（不变）；v0.4 IN PROGRESS — Phase A COMPLETE；Phase B-F NOT STARTED

---

## 0. 文档地图（对应 TASK 要求索引）

| TASK 要求 | 文档章节 |
|---|---|
| 1. 先读 backlog / PROJECT_STATE / 现有实现 | §1 现状调研 |
| 2. 设计文件创建 | 本文件 |
| 3. 第一版 Desktop Shell 选型 | §2 |
| 4. 第一版 UI 信息架构 | §3 |
| 5. Progress Bar 设计 | §4 |
| 6. Last Activity / Stuck Detection | §5 |
| 7. Stop / Cancel Current Task | §6 |
| 8. Bridge Background Runtime | §7 |
| 9. Hotkey Health（RW-012） | §8 |
| 10. Project Switching（RW-003） | §9 |
| 11. Duplicate Task UX（RW-016） | §10 |
| 12. Chinese-first UI（RW-015） | §11 |
| 13. 文字版 UI Wireframe | §12 |
| 14. Runtime State Source | §13 |
| 15. Core / UI 边界 | §14 |
| 16. 实施拆分（Phase A-F） | §15 |
| 17. 复杂度评估 | §16 |
| 18. 推荐第一版范围（MVP） | §17 |
| 19-22. 只设计 / 不启动 v0.4 / backlog 不标 SOLVED / PROJECT_STATE | §18 |
| 23-24. WorkBuddy / Codex 审查指引 | §19 |
| FIX-001: Safe Cancel / process ownership / 终态一致性（两个 blocking findings 关闭） | §6A（权威修订） |
| FIX-002: 原子终态提交（state.lock）/ artifact reconciliation / 持久 launch registry（三个 blocking findings 关闭） | §6B（权威修订） |

---

## 1. 现状调研（来源与生命周期）

本设计基于对以下实现的实际检查（2026-08-27）：

- `run.py` → `ai_agent_framework/runner.py`（正式入口）
- `ai_agent_framework/`（router / adapters / task_lifecycle / task_archive / report / project_boundary）
- `bridge/`（main / launcher / config / task_io / win32 / ui / handoff）
- 真实运行产物：`.aaf/AAF-MAINT-003/`（task.json / run.json / route.json / REPORT.md）

### 1.1 组件现状

**Runner（ai_agent_framework/runner.py）** — 顺序执行链，单进程、单线程：

```
Validation（validate_task_text，失败 → exit 2，不产生任何 artifact）
→ Boundary Check（写 boundary.json；warning-first，fail-open）
→ Router（decide_route → route.json：agents 列表）
→ Lifecycle CREATED（写 task.json）
→ RUNNING（写 task.json）
→ 对 route.agents 逐个：
    写 <agent>_prompt.md → run_agent（阻塞 subprocess.run，timeout=3600）→ 写 <agent>_result.md
    结果无效（FRAMEWORK_ERROR / 空）→ 中断后续节点
→ 聚合 SUCCESS / WAITING
→ 写 REPORT.md → 写 run.json（仅在结尾写一次）→ 终态写入 task.json
```

关键事实：

- `run.json` **只在执行结束时写一次**（timestamp = 结束时间），不是活动信号源。
- `task.json.updated_at` 在 CREATED / RUNNING / 终态时更新，**不随阶段推进更新**。
- Agent 执行期间（可能长达数十分钟）输出目录内**没有任何文件变化**——当前不存在"进行中"的中间信号。
- Agent CLI（hermes / codebuddy / codex）是 runner 的子进程；runner 是 Bridge launcher 的子进程。

**Bridge（bridge/main.py + launcher.py）** — tkinter 隐藏主窗口 + ctypes 热键线程：

```
热键 Ctrl+Alt+A → 读剪贴板 → task_io 校验（含 workspace 与 current_workspace 匹配检查）
→ 确认窗口（Execute / Cancel）→ save_task 落盘 .aaf/tasks/active/<id>.md（重复 → TASK_ALREADY_EXISTS）
→ FrameworkLauncher.launch：subprocess.Popen(run.py <task> --workspace <ws> --output <dir>)
   单任务并发保护（state=RUNNING 时拒绝新任务）
→ 等待线程收尾：FINISHED / FAILED / REPORT_NOT_FOUND / FAILED_TO_START → last_run.json → 弹窗
```

关键事实：

- Bridge 是常驻进程，但依赖一个 PowerShell / Terminal 窗口承载（python module 前台运行）；终端关闭即停止（RW-004 的根因之一）。
- Launcher 持有 runner 的 Popen 句柄，但**不持久化 PID**。
- Bridge 退出时，runner 子进程在 Windows 上继续运行（孤儿化），无人收尾。
- `bridge/config.py`：`~/.aaf-bridge/config.json` 含 hotkey / current_project / current_workspace。

**Lifecycle（ai_agent_framework/task_lifecycle.py）** — 唯一合法状态集合：

```
CREATED, RUNNING, WAITING, SUCCESS, FAILED
```

- task.json 字段：task_id / status / updated_at / task_path / workspace / report_path / reason（可选）。
- 归档（task_archive.py）：仅 SUCCESS / WAITING / FAILED 可归档到 `.aaf/archive/<id>/`；CREATED / RUNNING 拒绝。

**状态源清单（现状可读）：**

| 来源 | 位置 | 内容 | 实时性 |
|---|---|---|---|
| task.json | `.aaf/<id>/task.json` | lifecycle 状态 + updated_at + 路径 | 阶段级（CREATED/RUNNING/终态） |
| run.json | `.aaf/<id>/run.json` | 结尾时间戳 + 聚合状态 | 仅在结束时存在 |
| route.json | `.aaf/<id>/route.json` | agents 列表 + reason | 开始时写入 |
| boundary.json | `.aaf/<id>/boundary.json` | boundary 检查结果 | 开始时写入 |
| `<agent>_prompt.md` | `.aaf/<id>/` | 每个 Agent 启动前写入 | Agent 粒度 |
| `<agent>_result.md` | `.aaf/<id>/` | 每个 Agent 完成后写入 | Agent 粒度 |
| REPORT.md | `.aaf/<id>/REPORT.md` | 最终报告 | 结束时 |
| last_run.json | `~/.aaf-bridge/last_run.json` | 最近一次运行（Bridge 视角） | 结束时 |
| config.json | `~/.aaf-bridge/config.json` | 当前项目 / workspace / hotkey | 静态 |
| child process state | launcher 内存 | runner Popen / exit code | 仅 Bridge 内存 |

### 1.2 生命周期现状

```
TASK.md（唯一正式输入）
→ Runner：Validation → Boundary → Router → agents → REPORT → run.json
→ task.json：CREATED → RUNNING → SUCCESS | WAITING | FAILED（异常路径）
→ 终态后可归档
```

- 没有 per-stage 记录；"当前阶段"只能从产物存在性推断（prompt 已写而 result 未写 ⇒ 该 agent 正在执行）。
- 没有用户中断通道；没有 CANCELLED 状态。
- Validation 失败时不产生任何 artifact（仅 exit 2），外部无法从产物判断"校验失败"。

### 1.3 关键观察（设计输入）

1. **黑盒感的根因**：agent 执行期间无任何中间信号（§1.1），且阶段信息不落盘。
2. **PowerShell 常驻问题的根因**：Bridge 无 GUI 宿主时只能依附控制台窗口；需要一个无控制台的常驻宿主（pythonw / Tray）。
3. **"进程活着 ≠ 一切正常"**：Bridge 进程存活但热键线程死亡是已证实的真实场景（RW-012）。
4. **Cancel 不能是 kill**：kill 无法留下正式状态、无法区分"用户取消"与"执行失败"、也无法安全处理进程树边界。
5. **Desktop Shell 必须只读 Core 产物 + 调用现有入口**，不能复制 Router / Runner。

---

## 2. 第一版 Desktop Shell 选型

### 2.1 候选比较

| 维度 | A. Windows Tray + 小型状态窗口 | B. 常驻普通桌面窗口 | C. 浏览器本地页面 | D. Electron 类桌面应用 | E. 其他轻量 Python native（tkinter/pystray/ctypes） |
|---|---|---|---|---|---|
| 开发复杂度 | 低（复用现有 tkinter + ctypes） | 低 | 中（HTTP server + 前端页面） | 高（Node 工程 + 主进程/渲染进程） | 低（=A 的实现细节） |
| 安装复杂度 | 极低（现有 Python 环境，1 个小依赖） | 极低 | 中（端口 + 浏览器） | 高（打包体积 100MB+） | 极低（零/极少依赖） |
| Windows 兼容性 | 好（Win10 原生） | 好 | 好但受浏览器策略影响 | 好但重 | 好 |
| 后台常驻能力 | 好（Tray 是标准常驻形态） | 差（窗口占屏幕，最小化仍可见） | 差（需常驻 server + 浏览器标签） | 好 | 好 |
| Tray 支持 | 原生 | 无（需额外做） | 无 | 可 | 可（pystray / ctypes Shell_NotifyIcon） |
| 中文 UI | 直接（tkinter 文本） | 直接 | 直接（HTML） | 直接 | 直接 |
| 打包难度 | 低（PyInstaller 可选，第一版可不打包） | 低 | 中 | 中-高 | 低 |
| 资源占用 | 极低（~30-60MB 常驻） | 低 | 中（server + 浏览器） | 高（常驻 200MB+） | 极低 |
| 与当前 Python Core 集成 | 直接（同进程 / 文件契约 / subprocess） | 直接 | 需 HTTP 接口层（新边界） | 需 IPC 桥（新边界） | 直接 |
| Stop / Restart 进程控制 | 直接（同进程持有 Popen / PID） | 直接 | 间接（API → 后端） | 间接（IPC） | 直接 |
| 后续维护成本 | 低 | 低 | 中（前后端双维护） | 高（依赖树庞大） | 低 |
| Scope creep 风险 | 低（形态受限） | 中（容易长成"完整窗口应用"） | 高（天然向 Web Dashboard 演化） | 高（框架即平台诱惑） | 低 |

### 2.2 RECOMMENDED MINIMAL APPROACH

> **方案 A：Windows Tray + 小型状态窗口；宿主进程 = 现有 Bridge 进程升级；UI 栈 = 现有 tkinter + pystray（或零依赖 ctypes Shell_NotifyIcon 备选）；Core 执行模型（run.py 子进程 + 文件产物契约）保持不变。**

一句话定义：

```
第一版 Desktop Shell = 现有 Bridge 进程升级为"无控制台常驻 Tray 宿主"
                      + 一个可随时开关的小型状态窗口（tkinter Toplevel）
                      + 一组基于文件/进程契约的控制操作（Cancel / Restart / Switch / Duplicate UX）
```

理由：

1. **不引入第二进程架构**：Tray 图标、热键、状态窗口、launcher 全部落在现有 Bridge 进程内。进程模型从"终端窗口 + Bridge"变为"pythonw + Bridge（含 Tray）"，只改变宿主的启动方式，不改变任何 Core 边界。
2. **依赖增量最小**：tkinter 是 Python 标准库（Bridge 已在用）；pystray 是纯 Python 小包（ctypes 后端，Windows 下不依赖额外 DLL）；若坚持"零第三方依赖"原则，可用 ctypes `Shell_NotifyIcon` 手写 ~200 行等价实现（列为备选）。
3. **与现有集成路径完全复用**：热键（ctypes）、剪贴板、确认窗（tkinter）、launcher（subprocess + last_run.json）、状态读取（task.json / route.json / result 文件）全部是现成代码。
4. **打包不是第一版前提**：第一版以 `pythonw` + 启动快捷方式运行；PyInstaller 打包推迟（RW-010 为 P2，独立 Phase）。
5. **Scope creep 有天然防线**：形态固定为 Tray + 小窗口，无法长成大型 Dashboard；不引入 HTTP / 前端工程 / IPC 框架。

明确排除：

- **C（浏览器本地页面）**：需要常驻 HTTP server + 端口 + 浏览器生命周期管理，增加攻击面与"浏览器关了就黑盒"的新失败模式，且天然向 Web Dashboard 演化，违反"拒绝大而全 Dashboard"的既定原则（RW-006 Do Not Forget）。
- **D（Electron）**：体积、依赖树、维护成本与本项目"轻量、小而本地"原则严重冲突；为一个小状态窗口引入整个 Chromium 是过度工程。
- **B（常驻普通窗口）**：窗口遮挡工作区，最小化后仍是任务栏常驻；"关闭状态窗口 ≠ 退出 Bridge"的需求（§7）在 B 形态下反直觉，需要额外窗口管理语义。

### 2.3 Tray 实现选型（E 的细分）

| 方案 | 依赖 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| pystray（ctypes 后端） | +pystray（纯 Python） | 代码量小、稳定、API 清晰 | 图标通常需要 Pillow 或 .ico 文件 | **首选**（.ico 资源文件随包提供，避免 Pillow） |
| ctypes Shell_NotifyIcon 手写 | 零 | 保持"零第三方依赖"项目传统 | ~200 行样板、气泡/菜单细节多 | 备选（若 Ady 要求零依赖） |
| pywin32 | +pywin32 | API 全 | 依赖较大、纯 Windows 绑定 | 不推荐（pystray 已覆盖需求） |

---

## 3. 第一版 UI 信息架构

单窗口信息架构（自上而下，全部中文；技术字段只在详情/日志保留英文）：

```
┌─ 顶部状态条（一行可读的全局事实）─────────────────────┐
│  AAF 状态         → 正常 / 执行中 / 已停止 / 异常       │
│  Bridge 状态      → 正常运行 / 异常 / 未运行            │
│  当前项目         → 项目名 + workspace（可点击切换）     │
├─ Current Task 区（当前或最近一次任务）─────────────────┤
│  Task ID          → AAF-XXX（可点击查看详情/归档）       │
│  Task Name        → 中文任务名                          │
│  Current Stage    → 当前阶段名（Validation/Boundary/…） │
│  Current Agent    → Hermes / WorkBuddy / Codex / -      │
│  elapsed          → 已运行时长                          │
│  last activity    → 最近活动时间（相对时间，如"3 分钟前"）│
│  overall result   → 已完成 / 执行失败 / 等待处理 / 已取消│
│  estimated progress → 约 XX%（明确标注"估算"）           │
├─ Stage Progress（固定六阶段条）────────────────────────┤
│  Validation  Boundary  Hermes  WorkBuddy  Codex  REPORT │
│  （每格：未开始 ○ / 进行中 ▶ / 已完成 ✓ / 等待处理 ⏸    │
│   / 失败 ✗ / 已取消 ⊘）                                 │
├─ 最近活动（2-3 行滚动摘要，来自 §5 事件源）───────────────┤
├─ 操作按钮 ────────────────────────────────────────────┤
│  [查看日志]  [停止当前任务]（仅执行中可点）              │
└─ 底部 ────────────────────────────────────────────────┘
   [切换项目]  [重启 Bridge]  [设置]
```

阶段状态词汇表（六态）：

| 状态 | 语义 | 显示 |
|---|---|---|
| 未开始 | 尚未到达该阶段 | ○ |
| 进行中 | 当前正在执行 | ▶ |
| 已完成 | 已通过 / 已产出有效结果 | ✓ |
| 等待处理 | 该阶段结果构成阻断，任务挂起（对应 WAITING） | ⏸ |
| 失败 | 执行出错 / FRAMEWORK_ERROR / 无有效结果 | ✗ |
| 已取消 | 用户取消时尚未执行的阶段 | ⊘ |

六阶段与现有事实的映射（第一版）：

- **Validation**：完成 = 出现 boundary.json 或 route.json；失败 = launcher 记录 exit=2（Validation 失败无 artifact，见 §13.2 缺口）。
- **Boundary**：进行中 = boundary.json 尚不存在且任务 RUNNING；完成 = boundary.json 存在。
- **Hermes / WorkBuddy / Codex**：由 route.json 决定实际执行哪些；未在 route 中的阶段显示"未开始（本任务不含）"或折叠为"－"。进行中 = `<agent>_prompt.md` 已写而 `<agent>_result.md` 未写。
- **REPORT**：进行中 = 全部 route agents 完成而 REPORT.md 未写；完成 = REPORT.md 存在。

---

## 4. Progress Bar 设计

### 4.1 两个事实层次（必须分离，UI 不得混用）

| 层 | 名称 | 性质 | 来源 |
|---|---|---|---|
| Stage State | 真实状态 | **事实**：每个阶段 未开始/进行中/已完成/等待处理/失败/已取消 | task.json + route.json + prompt/result 文件存在性（§13） |
| Estimated Percentage | 估算百分比 | **UX estimate**：不是精确剩余进度，不承诺剩余时间 | 静态权重 × 阶段状态（§4.2） |

UI 规则：

1. 进度条旁必须标注"估算"（例如：`整体进度：约 64%（估算）`）。
2. 不允许显示"预计剩余时间"或精确百分比语义（如 "64.2%"）；只显示整数约值。
3. 百分比仅由阶段状态计算，**永远不**因等待时间流逝而增长（不做无限假进度）。
4. 当前进行中阶段内部可做**有限平滑**：进行中阶段按该阶段权重的 0%～50% 区间内线性微调（仅基于该阶段自身已用时长与一个**固定上限**，如 60 分钟为满分），超过上限后停在 50%，不得继续增长。此平滑仅作用于"当前阶段内部"，且 UI 明确标注为估算。
5. 收敛规则（强制性）：

```
SUCCESS → 100%（已完成，显示 ✓）
WAITING → 停在最后一个已完成阶段权重和（等待处理，显示 ⏸，不增长）
FAILED  → 停在失败阶段之前；失败阶段标 ✗
CANCELLED → 停在取消时刻的权重和（已取消，显示 ⊘，不再变化）
Validation 失败 → 0%
```

### 4.2 第一版静态权重（允许值）

| 阶段 | 权重 | 说明 |
|---|---|---|
| Validation | 5% | 校验快 |
| Boundary | 5% | 边界检查快 |
| Hermes | 45% | 执行主体，最耗时 |
| WorkBuddy | 20% | 独立复核 |
| Codex | 20% | 架构/scope 审查 |
| REPORT | 5% | 汇总快 |

- 权重合计 100%；未出现在 route 中的阶段不占权重（按 route 归一化）。
- 示例：route = [hermes, workbuddy, codex]，Hermes 完成、WorkBuddy 进行中 ⇒ 已完成 45 + 5（Boundary）+ 5（Validation）+ WorkBuddy 内部 0～10 ≈ 约 55%～65%。

### 4.3 未来校准（RW-005 联动）

- RW-005 上线（阶段耗时观测）后，用真实阶段耗时统计（中位数 + 分位数）替代静态权重：
  `weight_i = median(duration_i) / sum(median(duration_j))`。
- 校准只改权重配置（建议放 config 或独立常量），不改阶段状态模型。
- 校准前**不得**声称百分比有真实时间含义。

---

## 5. Last Activity / Stuck Detection 设计

### 5.1 第一版可行状态来源（按可靠性排序）

| 来源 | 事实 | 说明 |
|---|---|---|
| `task.json` 的 stage / stage_started_at / last_activity_at（§13.3 提案） | 最可靠 | 需要 Phase A 写入；本任务不实现 |
| `<agent>_result.md` 的 mtime | 上一个 Agent 完成时刻 | 现有即可用 |
| `<agent>_prompt.md` 的 mtime | 当前 Agent 启动时刻 | 现有即可用 |
| task.json 的 updated_at | 状态迁移时刻 | 现有即可用 |
| run.json mtime | **不可用** | 只在结尾写入（§1.1） |
| child process state | runner 存活 | Bridge 内存 + Phase A 持久化 pid 后可查 |

第一版（在 Phase A 之前可用）的 last activity 定义：

```
last_activity = max( mtime(output_dir 内所有 .json/.md 产物), 当前阶段推断 )
```

展示为相对时间：`最近活动：3 分钟前`。

### 5.2 阈值策略（设计建议，不实现）

| 观测项 | 阈值建议 | 判定 |
|---|---|---|
| 当前阶段已用时长（stage 时长） | 超过该阶段历史中位数 3 倍 且 ≥ 15 分钟 | suspected stuck |
| last_activity_at 距今 | ≥ 10 分钟 且 阶段未变 | suspected stuck |
| agent 执行时长 | 超过 60 分钟（当前 adapters timeout=3600 的提醒线） | 提示"执行时间较长" |

- 阈值配置化（config 或常量表），可调。
- **suspected stuck 只是可观测提示**（黄色横幅：`疑似卡住：Hermes 已执行 25 分钟无活动`），**不是自动判定任务失败**，不触发任何自动终止。
- 提示必须提供下一步入口：`[停止当前任务]`（走 §6 的正式 Cancel），而不是自动动作。

### 5.3 与进程状态的关系

- Bridge 自身进程活着 ≠ 热键健康（见 §8）；runner 进程活着 ≠ agent 有进展（agent 是 runner 的子进程，可能在等待/卡死）。
- 因此"疑似卡住"只看**活动信号**（文件 mtime / stage 时长），不把"进程存活"当作"有进展"的证据。

---

## 6. Stop / Cancel Current Task 设计（重点）

### 6.0 设计目标

- 提供**正式取消语义**，不是简单 kill process。
- 取消后状态可区分、可恢复、可查证：`CANCELLED` 是正式终态。
- 与 Exit AAF 完全分离：取消当前任务后 Bridge / Tray 继续运行。
- 不误伤其他独立 Hermes / WorkBuddy / Codex 会话。
- 保留全部 `.aaf` 任务证据；REPORT 生成（标记取消）。

### 6.1 控制权模型

```
用户（Tray 菜单 / 状态窗口按钮）
  → Desktop Shell（Bridge 进程）＝ 控制代理：校验当前任务、写入取消请求、状态机去重
  → Runner（run.py 子进程）＝ 取消的执行者：在检查点读取取消请求并收敛
  → Launcher（Bridge 内）＝ 强终止执行者：仅在"请求超时未收敛"时按进程树终止
```

- **唯一合法发起人**：用户（通过 UI）。Bridge 是代理，不自动发起取消。
- Runner 是取消语义的权威落地者（写终态）；Launcher 的强终止只是兜底。

### 6.2 取消契约（文件通道，第一版不引入 IPC）

新增契约文件（schema 提案，本任务不创建）：

```
<output_dir>/cancel.request    存在即表示有取消请求（内容：{requested_at, by} 可选）
```

- Desktop Shell 只做一件事：原子写入 `cancel.request`。
- Runner 只做一件事：在**检查点**检查该文件是否存在。
- 不引入 HTTP / socket / signal 作为第一版通道（信号在 Windows 语义弱且易误伤；文件通道零依赖、与现有产物契约一致、进程崩溃后请求仍然可见）。

### 6.3 Runner 检查点（cooperative，低侵入）

Runner 在每个**阶段边界**检查 cancel.request：

```
Validation 前 → 不检查（取消尚未就绪的任务直接不做）
Boundary 后、第一个 agent 前 → 检查
每个 agent 完成后、下一个 agent 前 → 检查
全部 agent 完成后、REPORT 前 → 检查（此时取消会被"吸收"，见 §6.9）
```

- 检查点语义：**取消只影响尚未启动的后续阶段**；已完成阶段的结果与产物全部保留。
- 发现请求 → 跳过剩余 agents → 生成 REPORT（Current Status = CANCELLED，注明取消原因与已完成阶段）→ 写 run.json（status=CANCELLED）→ task.json 终态 CANCELLED。
- 该机制**不改动现有 lifecycle 主流程**（现有状态迁移代码不变），只新增一个"检查点 + 终态"路径，属增量。

### 6.4 Agent 子进程如何结束（两段式）

| 段 | 触发 | 行为 | 安全保证 |
|---|---|---|---|
| 第一段：cooperative cancel | 用户点 [停止当前任务] | 写 cancel.request；UI 立即进入"正在取消…" | 正在执行的 agent **不被打断**，在它自然结束后 runner 在检查点收敛。若该 agent 是最后一个且已出有效结果，任务正常收尾（取消被吸收）。 |
| 第二段：强终止（仅当需要立即停止） | 用户点 [强制停止]（二次确认） | Launcher `taskkill /PID <runner_pid> /T /F`（进程树） | 只杀该 runner 及其子进程树（当前任务的 agent CLI 属于该树）→ 不误伤独立会话（§6.6）。 |

- 第一段是默认与推荐路径；第二段仅在"当前 agent 明显卡死且用户要求立即终止"时使用。
- 强终止后 task.json 无法由 runner 写终态（runner 已被杀）→ **Launcher 只记录 termination evidence**（control.json + 本地记录），随后调用 **Core recovery finalizer**（`finalize_cancelled_task`）补写 CANCELLED 终态（§6A.12）。Launcher **不得**直接独立写最终 task status（§6A.1）。

### 6.5 如何避免杀错别的 Hermes / WorkBuddy / Codex 会话

- **进程树边界**：只对"本任务 runner 进程"执行 `taskkill /T`。当前任务的 agent CLI（hermes/codebuddy/codex）是 runner 的直接子进程，属于该树；用户或其他任务独立启动的会话是**独立进程树**，不在树内。
- **PID 来源**：Launcher 在 launch 时记录 `proc.pid` 并持久化到 control.json（§6A.6/§6A.7；task.json 的 pid 字段是冗余，§13.3 提案）。强终止前**重新校验**（§6A.8）：task_id / workspace / launch_id / runner PID / process creation time / normalized command line / control 未 stale，全部通过才允许强终止。**任一校验不过 → REFUSE FORCE TERMINATION**。
- **唯一性**：Launcher 单任务并发保护已保证同一时刻只有一个本框架 runner；但仍需 §6A.8 的完整 ownership verification（含 creation time 校验），防止 PID 被系统复用。

### 6.6 任务产物与状态更新

| 产物 | Cancel 后的处理 |
|---|---|
| `.aaf/tasks/active/<id>.md`（TASK.md） | 保留不动（与 FAILED 一致；它是证据与唯一输入） |
| `.aaf/<id>/` 全部既有产物 | 保留不动（已完成 agent 的 prompt/result 是证据） |
| `cancel.request` | 保留为证据（或由 runner 收敛后改名为 `cancel.done`） |
| REPORT.md | **生成**，Current Status = `CANCELLED`，列出已完成阶段、取消请求时间、取消方式（cooperative/force） |
| run.json | 写 `status: CANCELLED` + timestamp（与现有 schema 一致，仅多一个合法值）；**写者 = Runner 收敛路径或 Core recovery finalizer**（§6A.1/§6A.12），status 跟随 task.json 终态（§6A.4） |
| task.json | `status: CANCELLED`，`reason: CANCEL_REQUESTED | FORCE_CANCELLED`，updated_at=取消收敛时刻；**写者 = Runner 收敛路径或 Core recovery finalizer**，Launcher 不直接写（§6A.1） |
| last_run.json | Bridge 侧**跟随 Core final result** 记录（§6A.4/§6A.5），不自行推导覆盖 Core；result=CANCELLED 或其英文映射，保证 Copy Last Report 链路可用 |
| 归档 | CANCELLED 是否可归档：**建议纳入可归档终态**（TERMINAL_STATUSES 增加 CANCELLED），保持"终态可归档"一致性 |

### 6.7 Cancel 后最终状态叫什么

正式终态名称：**`CANCELLED`**（英文技术字段，机器可读；UI 显示"已取消"）。

- 状态集合变更提案：`CREATED, RUNNING, WAITING, SUCCESS, FAILED, CANCELLED`。
- 该状态在 task.json / run.json / REPORT / 归档规则中一致使用。

### 6.8 Cancel 与 FAILED / WAITING 的区别（正式语义）

| 维度 | CANCELLED | FAILED | WAITING |
|---|---|---|---|
| 语义 | **用户主动中断** | 执行错误 / 框架错误 | 评审未通过，需返工 |
| 发起方 | 用户（通过 UI） | Framework（异常路径） | Framework（聚合判定） |
| 恢复建议 | 可重新提交（需先移除/重命名旧 active TASK 或走 Resume 语义） | 修问题后重跑 | 处理返工项后重跑 |
| UI 文案 | 已取消 | 执行失败 | 等待处理 |
| 是否可归档 | 建议是 | 是（现状） | 是（现状） |

### 6.9 边界情况

**重复点击 Cancel**：UI 状态机保证单任务取消请求去重。

```
任务运行中:   [停止当前任务] 可点 → 点击后变灰，文案变"正在取消…"
取消请求已发出: 按钮禁用；Tray 图标/状态窗口显示"正在取消"
任务已收敛:   按钮恢复禁用态（任务已结束）
```

- 第二次点击（同一次运行中）**不产生新请求**，不重复写文件；UI 只提示"取消请求已发送"。
- "强制停止"与"停止当前任务"是两个不同按钮；强停止每次都需要二次确认。

**Agent 刚好完成时的 race condition**：规则——**取消请求只影响尚未启动的后续阶段**。

- 场景 1：取消请求在最后一个 agent 完成后到达 → 全部阶段已完成 → **正常 SUCCESS**（UI 提示"任务已在取消前完成"），CANCELLED 不覆盖已完成事实。
- 场景 2：取消请求与 agent 完成同时 → 以检查点读取顺序为准：检查点读到请求 → CANCELLED；否则继续 → 完成。**状态以检查点结果为准，绝不回滚已写产物**。
- 场景 3：取消后用户立刻再次提交相同 Task ID → active TASK.md 仍在（证据保留）→ duplicate 保护生效 → 走 §10 的 Duplicate UX 提供"查看状态/打开 REPORT"，不静默重跑。

**取消请求发出后 Bridge 重启**：cancel.request 文件仍在 → 新 Bridge 的 Launcher 启动检查：若检测到残留 cancel.request 且对应任务已完成/已取消，正常忽略并提示；若任务仍在运行（孤儿 runner），提示用户选择"接管并继续"或"按取消处理"——接管必须通过 §6A.9 的 ownership verification 才能取得管理权；按取消处理走 **Core recovery finalizer** 收敛为 CANCELLED（§6A.12），Launcher 不自行补写终态。

### 6.10 生命周期最小方案（汇总图）

```
[RUNNING] --用户点停止--> [CANCEL_REQUESTED(UI/内存态)] --写 cancel.request--> runner 检查点
   │                                                                          │
   │ agent 完成、检查点未读到                                         检查点读到请求
   ▼                                                                          ▼
[继续下一阶段] <──────────────────────────────────────────────┐    [跳过剩余阶段]
   │                                                            │            │
   └── 全部完成 → [SUCCESS]（取消被吸收）                      │            ▼
                                                               │   [task.json(CANCELLED) → run.json(CANCELLED)
                                                               │    → REPORT(CANCELLED)] → 终态（§6A.4 提交顺序）
（可选）强终止：二次确认 → ownership verification（§6A.8）→ taskkill /T
        → Launcher 记录 termination evidence
        → Core recovery finalizer 写 CANCELLED（§6A.12）
```

- **不改变现有 lifecycle 主流程代码**：现有 CREATED→RUNNING→SUCCESS/WAITING/FAILED 路径不动；仅新增检查点、CANCELLED 终态、Core recovery finalizer 路径（均为增量）。是否纳入 v0.4 由 Planner 决策。

---

## 6A. Safe Cancel 状态一致性与 Process Ownership 协议（AAF-DESIGN-001-FIX-001 修订）

> **本节是 §6 的权威修订（2026-08-27，AAF-DESIGN-001-FIX-001）。** 凡与本节冲突的 §6 表述，一律以本节为准；§6 中对应表述已就地修正并标注指引。本节只定义设计级协议——**当前代码不实现**（§6A.18）。

### 6A.0 修订背景：两个 blocking findings

Codex（AAF-DESIGN-001 审查）指出两个阻断项，本节逐一关闭：

| # | Blocking Finding | 关闭位置 |
|---|---|---|
| 1 | **Force Cancel 终态双写竞态**：Launcher 可能写 CANCELLED，现有 wait thread 又可能因子进程非零退出写 FAILED，导致 task.json / run.json / REPORT.md / last_run.json 状态不一致 | §6A.1 唯一终态裁决者 + §6A.2 终态优先 + §6A.4 提交顺序 + §6A.5 wait thread |
| 2 | **PID/token 防误杀协议未闭合**：只提出 PID+token，无完整、可恢复、可验证的 process ownership protocol | §6A.6–§6A.10（launch_id / control.json / ownership verification / restart / stale） |

修订原则：Desktop Shell 整体方案不动；只关闭上述两项及其派生的一致性要求。

### 6A.1 唯一终态裁决者（Terminal Authority）

**Runner / Lifecycle Core 是 Task terminal state 的唯一 authoritative finalizer。**

- 合法终态集合 `TERMINAL = {SUCCESS, WAITING, FAILED, CANCELLED}`；只有**两类入口**可以写终态：
  1. **Runner 自身生命周期路径**：正常收敛（SUCCESS / WAITING）、FRAMEWORK_ERROR（FAILED）、检查点取消收敛（CANCELLED，§6.3）。
  2. **Core recovery finalizer**：`finalize_cancelled_task(...)`，属于 Lifecycle Core，供强杀/崩溃后恢复终态（§6A.12）。
- **Launcher / Desktop Shell 不得直接独立裁决最终 task status。** Launcher 可以且只能：
  - 发出 cancel request（原子写 cancel.request）
  - 发出 force terminate request（写 control.json.force_terminate_requested，§6A.7）
  - 终止它**拥有且已验证**的 runner process tree（§6A.8 校验全部通过后 taskkill /T /F）
  - 记录 termination evidence（control.json + 本地记录；exit code 是 evidence，不是判定）
- **不存在第三条写终态路径。** wait thread 的 result（FINISHED / FAILED / REPORT_NOT_FOUND / FAILED_TO_START）是 **Bridge 视角的收尾分类**，不是 Task 终态裁决（现状即如此，§1.1 launcher 模块头注释；修订后显式化）。
- **互斥补充（FIX-002）**：上述所有写终态入口共享同一把 per-task exclusive `state.lock`（§6B.1）。锁不改变 authority 归属（谁有写权仍由本节决定），只保证跨进程 read/check/write 串行（§6B.2）。

### 6A.2 终态优先规则（Terminal-State Precedence）

**Terminal state 一旦 committed，不得被任何后续 late event 覆盖。**

```text
if terminal_state_exists(task.json):            # SUCCESS | WAITING | FAILED | CANCELLED
    late cancel / late launcher event / late request → 拒绝写入，返回现有终态（幂等）
```

并发裁决规则（Runner 正常完成 vs force cancel）：

| 时序 | 裁决 |
|---|---|
| Runner 在 cancel commit 前已合法进入 SUCCESS / WAITING / FAILED | **原终态胜出**（cancel 被吸收 / 拒绝） |
| Core 已接受 cancel、进入 cancelling 状态，Runner 尚未提交终态 | **Cancel path 胜出**（终态 = CANCELLED） |
| 只有 Launcher 观察到非零 exit code（process-exit observation） | **只是 evidence**：不能单独把 Cancel 改写为 FAILED（§6A.5） |

实现约束：所有写终态入口（Runner 收敛、recovery finalizer）写前必须在 **per-task `state.lock` 内**原子读取现有 task.json（read/check/write 同锁，§6B.2）；已存在终态 → 放弃写入并返回现有终态。这是双写竞态的闭合机制——互斥由锁提供，`os.replace` 只承担单文件完整替换，不再被当作跨进程 CAS（FIX-002，§6B.1/§6B.23）。

### 6A.3 最小中间状态（设计级，仅提案）

- 允许设计级中间态：`CANCEL_REQUESTED`、`CANCELLING`。
- 明确边界：它们只是 **UI/Launcher 内存态 + control.json 字段**（`cancel_requested` / `force_terminate_requested`），**不属于 task.json 的合法 status 集合**（`task_lifecycle.VALID_STATUSES` 不变）。
- 这是未来 lifecycle proposal；**当前代码不实现**。
- 最终 terminal state 只有一个：**`CANCELLED`**（task.json / run.json / REPORT / 归档规则一致使用）。

### 6A.4 四类产物的一致性提交顺序（Artifact Commit Order）

**第一步永远是 Core/Lifecycle 确定 terminal outcome（决策），之后才是产物落盘。** 规范顺序：

```text
A. Core/Lifecycle 确定 terminal outcome（SUCCESS | WAITING | FAILED | CANCELLED）
B. 原子更新 task.json（唯一权威终态载体；**必须在 state.lock 内完成 read/check/write**，§6B.2；tmp + os.replace 仅承担完整文件替换，不再被当作跨进程 CAS，§6B.23）
C. 写 run.json（status 跟随 B 的终态）
D. 生成 REPORT.md（Current Status 行与终态一致）
E. Launcher/Bridge 读取 Core terminal result（task.json）→ 更新 last_run.json
```

- **所有权**：A–D 全部由 Core（Runner 收敛路径或 recovery finalizer）执行；E 由 Launcher/Bridge 执行，**只跟随、不推导**。
- **last_run.json 不能自行推导最终状态覆盖 Core**：若 last_run 与 task.json 冲突，以 Core 为准，并记录 inconsistency warning（§6A.15 同源规则）。
- 与现状的差异说明（基于代码事实）：当前 runner 实际顺序为 REPORT.md → run.json → task.json（§1.1）。修订后终态提交提前到 task.json 先行，使"唯一权威终态"最先成为持久事实，run.json / REPORT / last_run 全部服从同一裁决，消除"REPORT 已写 CANCELLED 而 task.json 尚 RUNNING"的观察窗口。实现时允许的变体：REPORT.md 可在 B 之前生成（因 task.json 需嵌入 report_path），但**终态裁决必须先行、task.json 终态提交必须先于 run.json 与 last_run.json，且四产物 status 必须一致**。

### 6A.5 wait thread 行为（Wait Thread Rule）

针对当前 `bridge/launcher.py` 的 wait thread（`_wait_and_finish`），未来设计规定：

```text
子进程结束（exit code 已知）之后：
1. 先读取 Core final result / terminal artifact（task.json.status）
2. 若存在合法 terminal outcome（SUCCESS | WAITING | FAILED | CANCELLED）
   → last_run.json 跟随 Core outcome（result 映射：CANCELLED → RESULT_CANCELLED 或等价映射；
     FINISHED / FAILED 沿用现状语义，但以 Core 终态为准）
3. 仅当：Runner 异常退出（exit code ≠ 0）
        且不存在合法 terminal outcome（task.json 无终态 / 无 task.json）
   → 才归类为 FRAMEWORK_ERROR / FAILED 类异常结果
     （RESULT_FAILED / REPORT_NOT_FOUND / FAILED_TO_START 等 Bridge 收尾分类）
```

- **不得把"force cancel 导致的非零退出码"直接认定为 FAILED**：exit code 只作为 evidence 记录（RunInfo.exit_code），不参与状态判定。
- 该规则同时消灭 Finding 1 的竞态：wait thread 不再有独立裁决权，只镜像 Core 结果。
- **FIX-002 补充**：canonical terminal 存在但派生产物（run.json / REPORT.md）不完整 → wait thread 触发 Core reconciliation（§6B.7-C / §6B.22），之后 last_run 跟随 canonical result。

### 6A.6 Process Ownership 协议（launch_id）

选定**唯一可实施协议：launch_id**（一次性随机标识，如 `uuid4().hex`；不依赖环境变量注入 token，避免继承/泄露问题）。

生命周期：

```text
1. Launcher 启动 task runner 前：生成唯一 launch_id
2. launch_id 与 (task_id, workspace, output_dir) 绑定，一一对应
3. Launcher 原子写入 task-owned control artifact（control.json，§6A.7）：
   task_id / workspace / launch_id / launcher_pid / started_at / runner_cmdline（实际 argv）
4. Runner 启动后写回（原子）：
   runner_pid / runner_creation_time / launch_id / task_id / workspace
   （写回时校验 launch_id / task_id / workspace 与预写值一致；不一致 → 视为 ownership 异常，
    记录并拒绝接管）
5. Launcher 保存自身 ownership record（**持久化到 Bridge launch registry**：`~/.aaf-bridge/launches/<launch_id>.json`，§6B.11；control.json 内 launcher_pid + 内存句柄为辅助）
```

- 同一 task 的**新一次 launch 必须生成新 launch_id**；旧 control 被 supersede（`superseded_by` 记录新 launch_id）→ 旧 control 立即 stale（§6A.10）。
- launch_id 的用途：ownership verification（§6A.8）、restart 接管判定（§6A.9）、stale 判定（§6A.10）、recovery finalizer 的幂等键（§6A.12）。

### 6A.7 Control Artifact（schema 提案）

设计路径：`.aaf/<Task-ID>/control.json`（task-owned，与 task.json 同目录；仅 schema 提案，**本任务不创建真实文件**）：

```jsonc
{
  "task_id": "AAF-XXX",                       // 绑定任务
  "workspace": "D:\\...",                     // 绑定 workspace
  "launch_id": "<uuid4-hex>",                 // 本次 launch 唯一标识
  "runner_pid": 12345,                        // Runner 写回
  "runner_creation_time": "2026-08-27T10:00:00.000",  // Runner 写回（Windows 进程创建时间）
  "launcher_pid": 67890,                      // Launcher 预写
  "started_at": "2026-08-27T10:00:00",        // Launcher 预写
  "runner_cmdline": ["python", "run.py", "<task>", "--workspace", "<ws>", "--output", "<dir>"],  // Launcher 预写：实际 argv，供命令行校验
  "cancel_requested": false,                  // cancel.request 的镜像（§6A.15）
  "force_terminate_requested": false,         // force terminate 请求标记
  "superseded_by": null                       // 新 launch 覆盖时记录新 launch_id
}
```

写者归属与原子性：

- Launcher：创建（launch 前预写）+ 更新 `cancel_requested` / `force_terminate_requested` / `superseded_by`。
- Runner：启动后写回 `runner_pid` / `runner_creation_time`（并校验绑定字段）。
- 全部原子写（tmp + os.replace），与 task.json 同一模式。
- `task.json` 内 `pid` 字段（§13.3 提案）与 control.json 互为冗余；**运行期 ownership 判定以 control.json 为准**。
- **FIX-002**：control.json 是 task-owned 证据；**独立第二记录 = Bridge launch registry**（`~/.aaf-bridge/launches/<launch_id>.json`，§6B.11）。Launcher restart 恢复必须 registry + control + live process 三方验证（§6B.13），不是 control.json 自我比较（§6B.14）。

### 6A.8 强制终止前的 Ownership Verification

Force terminate（taskkill /T /F）执行前，**必须全部通过**以下校验（基于 control.json + 实况查询）：

| # | 校验项 | 通过条件 |
|---|---|---|
| 1 | task_id 一致 | control.task_id == 目标 task_id |
| 2 | workspace 一致 | control.workspace == 目标 workspace |
| 3 | launch_id 一致 | control.launch_id == 本次会话持有的 launch_id |
| 4 | runner PID 一致 | 实况进程 PID == control.runner_pid |
| 5 | process creation time 一致 | 实况创建时间 == control.runner_creation_time（防 PID recycle） |
| 6 | normalized command line 符合预期 runner entry | 实况命令行规范化后 == control.runner_cmdline 规范化（run.py <task> --workspace <ws> --output <dir>） |
| 7 | control artifact 未过期 / 未被 superseded | 非 stale（§6A.10）且 superseded_by == null |

- **任一校验失败 → REFUSE FORCE TERMINATION**（拒绝执行；UI 显示拒绝原因）。**不能降级成"尽量 kill"**——所有权不确定时宁可不杀。
- 规范化规则（实现时定义精确实现）：大小写归一、路径归一（绝对路径 + 统一分隔符）、参数顺序无关比较；Windows 下实况命令行通过 PowerShell CIM `Win32_Process.CommandLine` 或 psutil 获取。

### 6A.9 Launcher / Tray Restart 场景

> **FIX-002 修正（权威版本见 §6B.13）**：重启后**不得仅信任 control.json**——它是 task-owned 单记录，无法独立证明 launch 归属。必须同时读取 Bridge launch registry 与 task control artifact，并与 live Windows process identity 三方验证：

```text
A. ~/.aaf-bridge/launches/<launch_id>.json   （Bridge launch registry，§6B.11）
B. .aaf/<Task-ID>/control.json               （task control artifact，§6A.7）
C. live Windows process identity             （PID + creation time + command line）
```

**只有在全部满足**时才重新取得该 runner 的管理权（十项校验见 §6B.13）：

```text
- PID 仍存在（进程存活）
- creation time 一致（未被 PID recycle 顶替）
- launch_id 一致（registry 与 control 交叉一致）
- command line 一致（与 registry.expected_command_line 相符）
- task 未有 terminal outcome（task.json 无终态）
- registry 未 EXITED / SUPERSEDED；control 未 stale / superseded
```

- 全部满足 → **ownership = REAUTHENTICATED**（可继续观察、可响应 cancel / force cancel）。
- 任一不满足 → **ownership = UNCERTAIN**，并**拒绝 force kill**；UI 提示用户（如：存在孤儿 runner，建议人工处理或走恢复流程）。
- 重启后**不得自动 force kill**；**不得自动改写 task.json**（终态裁决权仍在 Core，§6A.1）。
- **launcher_instance_id 不得作为恢复前提**（§6B.16）：重启后 instance 身份必然不同，恢复只依赖持久记录 + 实况进程，不依赖旧进程内存身份。

### 6A.10 Lease / Stale 规则

**control artifact 不等于永远有效。** 以下任一情况 → control 视为 **stale**：

| 情形 | 判定 |
|---|---|
| 进程已不存在 | 查 PID 无结果（或进程已退出） |
| PID recycled | PID 存在但 creation time 与记录不一致 |
| terminal state 已存在 | task.json 已有 SUCCESS / WAITING / FAILED / CANCELLED |
| launch_id superseded | `superseded_by` 非空 |
| creation time 不一致 | 与 `runner_creation_time` 记录不符 |

- stale control 的处理：**不授予 force kill 权**；标记 ownership uncertain；可进入清理流程。
- 设计级可选增强：lease 过期（`started_at` + 最大时长上限后强制视为 stale）——第一版不做，避免误判长任务。

### 6A.11 Soft Cancel 与 Force Cancel 语义

**Soft Cancel（默认路径）：**

```text
UI 写 cancel.request（原子）→ Runner 在 safe checkpoint 读取（§6.3）
→ 不启动后续 agent → 已完成阶段产物全部保留
→ Core 收敛：task.json(CANCELLED) → run.json(CANCELLED) → REPORT(CANCELLED)（§6A.4 顺序）
→ Launcher 跟随更新 last_run.json
```

**Force Cancel（兜底路径）——三个条件全部满足才允许：**

1. soft cancel 超时（设计建议：阈值配置化，默认 30–60s，实现时定值）；
2. 用户二次确认（UI 红色警示文案，§12.3）；
3. ownership verification 全部通过（§6A.8）。

```text
Force Cancel 动作：Launcher 终止它拥有且已验证的 runner process tree（taskkill /T /F）
→ Launcher 只记录 termination evidence（control.json.force_terminate_requested = true + 本地记录）
→ 最终 terminal state 由 Core recovery finalization 决定（§6A.12），Launcher 不自行写终态
```

### 6A.12 强杀后 Core 不再运行时的 Recovery Finalization

场景：runner 被强杀（或崩溃、被外部终止），未留下任何终态。此时 Launcher 不能自己拼状态，必须调用 **Core 提供的独立 finalizer**：

```text
finalize_cancelled_task(output_dir, task_id, workspace, launch_id, evidence)
    → 属于 Lifecycle Core（不是 UI/Launcher 逻辑）
    → 原子、幂等（FIX-002 强化，权威版本见 §6B.21）：
      1. acquire per-task state.lock（§6B.1）
      2. 锁内 canonical reload（重读 task.json）
      3. terminal arbitration：已有终态 → 不改写，幂等返回现有 canonical result
      4. 无终态 → 确定 outcome=CANCELLED，原子提交 task.json
         （status=CANCELLED + terminal_generation；reason=FORCE_CANCELLED + evidence）
      5. reconcile run.json（status=CANCELLED，跟随 canonical generation）
      6. reconcile REPORT.md（Current Status=CANCELLED；注明强制终止时间与证据）
      7. 返回 canonical result（供 Launcher 更新 last_run.json）
```

- 设计实现形态：独立 CLI 入口（如 `python -m ai_agent_framework.finalize_cancelled --output <dir> …`）或库调用；**推荐 CLI 入口**——Launcher 通过子进程调用，避免 import Core 内部执行逻辑（§14.4 防侵入规则）。
- 幂等：重复调用（如 Launcher 重启后再调）返回相同结果，不重复改写；**已存在终态也必须走 reconciliation**（补齐 run.json / REPORT.md，§6B.21），不再"发现终态直接 return"。
- 等价方案可接受，但必须保持"**Core 是唯一终态裁决者**"（§6A.1）。

### 6A.13 Race：Agent 刚完成时用户点 Cancel

| 场景 | 规则 |
|---|---|
| terminal commit 已完成（task.json 终态已落盘） | **Cancel 拒绝**：UI 提示"任务已在取消前完成"；保留原结果，不覆盖 |
| cancel 已 accepted（进入 cancelling），agent result 刚落盘 | **Core 根据 lifecycle checkpoint 判定**：检查点先于 result 提交读到 cancel → CANCELLED；result 提交先于检查点 → 按正常完成。判定点在 Core，UI 不猜 |
| 已完成 agent artifact | **保留**，不删除已完成结果（CANCELLED 只作用于未启动的后续阶段） |

### 6A.14 重复 Cancel

```text
第一次点击：CANCEL_REQUESTED（UI/内存态 + 写 cancel.request）
后续点击：显示"正在取消"，不重复发请求、不重复写文件
任务已 terminal：按钮禁用（§6.9 状态机）
```

### 6A.15 cancel.request / task.json Mirror 不一致规则

- **canonical source = Core lifecycle state（task.json）**。
- **cancel.request 是 external request artifact，不是 terminal truth**。

```text
若 cancel.request 存在 且 task 已 terminal
    → request 标记 consumed/ignored（如改名 cancel.done 或仅日志），不得改终态
若 task.json.cancel_requested == true 但 request artifact 缺失
    → Core 仍按 lifecycle record 继续执行，同时记录 inconsistency warning（不拒绝执行）
```

（现状说明：`cancel_requested` 字段属 §13.3 Phase A 提案，当前代码无此字段；本规则是设计级约定。）

### 6A.16 复杂度评估调整

**Core Intrusion Risk：LOW → MEDIUM**（§16 同步更新）。原因：

- 新增终态（CANCELLED）进入状态机与归档规则；
- 跨进程取消（cancel.request 契约 + 检查点收敛）；
- process ownership（launch_id / creation time / command line 校验）；
- recovery finalization（finalize_cancelled_task 独立入口）；
- multi-artifact 一致性（task.json / run.json / REPORT / last_run 提交顺序与幂等规则）；
- **FIX-002 追加**：cross-process terminal lock（state.lock，§6B.1–§6B.3）、persistent launch registry + 三方验证（§6B.11–§6B.14）、reconciliation protocol（§6B.6–§6B.8）。**评级保持 MEDIUM**（§6B.24）。

### 6A.17 Heartbeat 观测补充

- 未来 heartbeat **不能依赖阻塞 `GetMessageW` 的自然周期 tick**（消息循环可长期阻塞，tick 不更新 → heartbeat 恒旧）。
- 必须使用：**timer**（`SetTimer` / tkinter `after`）或 **worker thread**（定时更新共享时间戳）或 **non-blocking heartbeat mechanism**。
- 本任务仍不实现（设计约束；§8.3 同步）。

### 6A.18 实施边界（FIX-001）

- 本任务**只修订设计文档**；不实现 Cancel、不修改 runtime / launcher / lifecycle / tests / .gitignore / Desktop UI。
- `task_lifecycle.VALID_STATUSES` 当前不含 CANCELLED —— **保持不变**（含 CANCELLED 属 Phase A/E 提案）。
- backlog RW 状态不变（不标 SOLVED）；v0.3 CLOSED；v0.4 NOT STARTED；PROJECT_STATE 不变。
- 实施归口：§6A 内容在实现时归入 Phase E（§15），recovery finalizer 建议独立拆分（E-core）。

### 6A.19 验收对照表（FIX-001 acceptance → 小节）

| Acceptance | 位置 |
|---|---|
| 1. 唯一 terminal finalizer | §6A.1 |
| 2. Launcher 不直接裁决终态 | §6A.1 |
| 3. 终态不被晚事件覆盖 | §6A.2 |
| 4. wait thread 不只看 exit code | §6A.5 |
| 5. last_run 跟随 Core | §6A.4/§6A.5 |
| 6. launch_id 协议完整 | §6A.6 |
| 7. control artifact schema | §6A.7 |
| 8. PID creation time 校验 | §6A.8 |
| 9. command line 校验 | §6A.8 |
| 10. stale lease 规则 | §6A.10 |
| 11. restart ownership recovery | §6A.9 |
| 12. ownership 不确定拒绝 force kill | §6A.8/§6A.9 |
| 13. Soft Cancel 语义 | §6A.11 |
| 14. Force Cancel 语义 | §6A.11 |
| 15. recovery finalizer 属于 Core | §6A.12 |
| 16. race 闭合 | §6A.13 |
| 17. duplicate cancel 闭合 | §6A.14 |
| 18. cancel.request 非 terminal truth | §6A.15 |
| 19. Core Intrusion Risk = MEDIUM | §6A.16 |
| 20. heartbeat 非阻塞机制 | §6A.17 |
| 21. 无 runtime 实现 | §6A.18 |

---

## 6B. 原子终态提交与进程所有权恢复协议（AAF-DESIGN-001-FIX-002 修订）

> **本节是 §6A 之上的第二层权威修订（2026-08-27，AAF-DESIGN-001-FIX-002）。** 凡与本节冲突的 §6/§6A 表述，一律以本节为准；§6A 中对应表述已就地修正并标注指引。本节只定义设计级协议——**当前代码不实现**（§6B.25）。FIX-001 的验收基线（§6A.19）保持不变；本节在其上追加第三批关闭项。

### 6B.0 修订背景：三个 blocking findings

Codex（FIX-001 复审）指出三个阻断项，本节逐一关闭：

| # | Blocking Finding | 关闭位置 |
|---|---|---|
| A | **terminal commit 缺少真正跨进程互斥**：`read task.json → 判断无 terminal state → os.replace` 不是跨进程 compare-and-set；Runner 与 recovery finalizer 仍可能同时读到 RUNNING，随后分别写 SUCCESS 与 CANCELLED | §6B.1–§6B.5（state.lock + 锁内临界区 + generation） |
| B | **terminal commit 后中断缺少派生产物 reconciliation**：Core 在 task.json terminal commit 后崩溃时，没有规定如何基于已提交的 terminal truth 幂等补齐缺失/冲突的 run.json / REPORT.md | §6B.6–§6B.10（reconciliation protocol） |
| C | **Launcher restart 缺少独立可信的 ownership 恢复依据**：原内存 ownership record 丢失后只剩 task-owned control.json，launch_id 没有独立的第二可信记录可交叉验证 | §6B.11–§6B.16（Bridge launch registry + 三方验证） |

### 6B.1 跨进程互斥协议：Core-owned per-task state.lock

**正式选定：Core-owned per-task OS-level exclusive state lock。**

路径：

```text
.aaf/<Task-ID>/state.lock
```

（与 task.json 同目录；每个 task 一把独立锁。）

- **所有可能写 terminal state 的 Core 路径都必须先获取同一把 per-task exclusive lock**：
  1. normal Runner finalization（正常收敛）
  2. soft-cancel finalization（检查点取消收敛）
  3. recovery cancel finalization（`finalize_cancelled_task`）
  4. crash recovery finalization（§6B.9 场景）
- **Launcher / Desktop UI 不取得该锁来写 Task terminal state**——它们没有终态写权（§6A.1）；锁只被 Core 路径使用。
- 锁与 §6A.1 的 authority 模型正交：authority 决定"谁能写"，锁决定"同一时刻只有一个写者在做 read/check/write"。

### 6B.2 Lock Critical Section（锁内临界区）

terminal finalizer 必须按以下顺序在**同一把锁内**完成：

```text
A. acquire exclusive state.lock（阻塞/短超时；失败行为见 §6B.19）
B. reload canonical task.json from disk（锁内重读，禁止使用锁外缓存的旧值）
C. inspect current lifecycle status
D. if terminal already exists:
     返回现有 canonical terminal result（幂等；不写任何东西）
E. otherwise: 确定 allowed terminal outcome（SUCCESS | WAITING | FAILED | CANCELLED）
F. atomically commit task.json terminal state（tmp + os.replace）
G. persist terminal generation / revision（与 F 同一次原子提交，§6B.4）
H. release state.lock 仅当 canonical terminal commit 已 durable（os.replace 返回后）
```

**关键原则：read/check/write 必须全部发生在同一把跨进程锁内。**

不得再用：

```text
read
→ unlock / no lock
→ os.replace
```

冒充 CAS。`os.replace` 只承担"完整文件替换"的原子性（单个文件不会半写坏），**不承担**"多进程 read-modify-write 串行化"——后者由 state.lock 提供（§6B.23 修正旧表述）。

### 6B.3 Windows 第一版锁实现方向（设计指定，不实现）

Desktop Shell 第一版为 Windows-local，**优先使用 Python 标准库可实现的 Windows OS file locking**：

- **指定：`msvcrt.locking` exclusive file lock 封装**（`LK_NBLCK` 非阻塞尝试 + 重试/短超时，或 `LK_LOCK` 阻塞式），或等价 Windows OS-level exclusive lock（如 `CreateFile` + `LockFileEx` 经 ctypes 实现）。
- **封装位置：Lifecycle/Core utility**（如 `ai_agent_framework/lock_utils.py`）——**UI / Launcher 不复制锁逻辑**（§14.4 防侵入规则同样适用于锁）。
- 锁文件语义：`state.lock` 是锁的载体文件，锁本身是 OS 级文件锁；**文件存在 ≠ 锁被占用**（§6B.20）。
- 本任务**不实现该锁**；实现归口 Phase E（§6B.25）。

### 6B.4 terminal_generation（终态代次）

在 task.json schema 中加入 **`terminal_generation`**（monotonically increasing revision，整数）：

- **生成规则**：terminal commit 时写入 `(prev_generation or 0) + 1`；非终态更新不递增；只有 terminal commit 递增。
- **用途**：
  - diagnostics（诊断哪一次 commit 是最终裁决）
  - reconciliation（派生产物应跟随哪一代 terminal commit）
  - stale writer detection（旧代次写者不得覆盖新代次）
  - derived artifact provenance（run.json / REPORT.md 记录其跟随的 generation）
- **边界**：generation **不是代替 lock 的 CAS**。第一版以 exclusive lock 为主互斥手段；generation 用于识别"派生产物是否跟随同一 terminal commit"（§6B.8/§6B.9）。

### 6B.5 Canonical Terminal Record（canonical 终态记录）

task.json 的 terminal commit 至少包含：

```jsonc
{
  "status": "SUCCESS",                    // SUCCESS | WAITING | FAILED | CANCELLED
  "terminal_generation": 12,              // 单调递增（§6B.4）
  "terminal_at": "2026-08-27T10:05:00",
  "terminal_reason": "NORMAL_COMPLETION", // 或 CANCEL_REQUESTED | FORCE_CANCELLED | FRAMEWORK_ERROR | ...
  "launch_id": "<uuid4-hex>",
  "task_id": "AAF-XXX",
  "workspace": "D:\\...",
  // 如适用：
  "cancel_mode": "soft" | "force",        // 仅取消终态
  "exit_evidence": { "exit_code": 1, "observed_at": "..." }  // 仅 evidence，不参与判定
}
```

- **task.json 的 terminal record 是唯一 canonical terminal truth。**
- run.json / REPORT.md / last_run.json / control.json 都不是 canonical terminal truth（§6B.10）。

### 6B.6 Core-owned Reconciliation Protocol

正式定义：

```text
reconcile_terminal_artifacts(task_id, workspace, output_dir, launch_id)
```

**归属于 Lifecycle Core**（与 `finalize_cancelled_task` 同属 Core，不是 UI/Launcher 逻辑）。

职责：

1. 读取 canonical task.json terminal state（若无终态 → 返回设计错误"无 canonical terminal，无法 reconciliation"，**不臆造终态**）
2. 幂等检查并补齐派生产物：`run.json`、`REPORT.md`
3. **返回 canonical result 给 Launcher**（供 last_run.json 更新）

硬约束：

- **不得改变已经提交的 terminal status / generation**（canonical 不可变；§6B.8 关键原则）。
- 幂等：重复调用返回相同结果，不重复改写。
- Launcher **不自行修文件**；Launcher 只能调用 Core reconciliation entry point，或展示"需要恢复 / reconciliation failed"（§6B.7-D）。

### 6B.7 Reconciliation 触发时机

至少四个：

```text
A. normal finalization terminal commit 后（§6A.4 顺序内：task.json 提交后、返回前）
B. recovery finalizer 启动时（finalize_cancelled_task 内，§6B.21）
C. Launcher wait thread 发现 runner 已退出但派生产物不完整时（§6B.22）
D. Bridge / Desktop Shell 打开已终止任务但检测到 artifact inconsistency 时
   （如 run.json 缺失、run.json generation 落后于 canonical）
```

- Launcher 在 C/D 场景**不修文件**：调用 Core reconciliation entry point（CLI 或库调用，与 §6A.12 同一形态），或展示"需要恢复 / reconciliation failed"。

### 6B.8 Reconciliation 行为（generation 对齐）

示例：canonical = task.json `CANCELLED` generation 7。

| 派生产物状态 | 行为 |
|---|---|
| run.json missing | 根据 canonical terminal record 重建 generation 7 的 run.json（status=CANCELLED + terminal_generation=7） |
| REPORT.md missing | 根据 canonical terminal record + 已有 agent artifacts 生成取消 REPORT（Current Status=CANCELLED，注明取消原因/时间） |
| run.json generation 6 | 视为 stale derived artifact → 重建为 generation 7 |
| run.json generation 7 但 status 与 canonical 冲突 | 视为损坏 → 按 canonical 重建 generation 7 |
| REPORT 指向旧 terminal result | 重建或明确刷新为 generation 7（更新 Current Status 行） |
| 派生产物完整且 generation == canonical generation | 无操作（幂等完成） |

**关键原则：derived artifacts 可以被修复；canonical terminal state 不被改变。**

### 6B.9 Partial Commit Crash 场景（完整例子）

```text
Core acquires state.lock
→ task.json SUCCESS generation 12 committed（F 完成，durable）
→ process crashes before run.json（G 未写 / H 未释放锁——OS 自动释放，§6B.20）
```

恢复后：

```text
recovery / reconciliation 读取 task.json
→ 看到 SUCCESS generation 12（canonical terminal truth）
→ 不得改成 CANCELLED / FAILED（terminal state 不可变，§6B.6）
→ 补 run.json（generation 12，status=SUCCESS）
→ 补 REPORT（Current Status=SUCCESS）
→ Launcher 最终写 last_run 跟随 SUCCESS
```

任何后续 late event（cancel 请求、非零 exit evidence、Launcher 观察）都**不能改写**已提交的 SUCCESS（§6A.2 终态优先在锁内强制执行，§6B.2-D）。

### 6B.10 last_run.json 仍不是 canonical truth

- 属 **Bridge convenience state**（`~/.aaf-bridge/last_run.json`）。
- 必须根据 Core canonical result 更新（§6A.4-E / §6A.5 / §6B.22）。
- **可以重建**（Launcher 可随时从 task.json canonical 重建）。
- 冲突时**永远服从 task.json terminal record**。
- **不参与 terminal arbitration**（不参与 SUCCESS / CANCELLED / FAILED 的裁决）。

### 6B.11 Bridge Persistent Launch Registry（第二份独立 ownership 记录）

正式选定第二份独立记录：**Bridge-owned launch registry**。

路径：

```text
~/.aaf-bridge/launches/<launch_id>.json
# 即 C:\Users\<user>\.aaf-bridge\launches\<launch_id>.json
```

（`~/.aaf-bridge/` 是 Bridge 私有 state root——与 §1.1 的 config.json / last_run.json 同根。）

它与 `.aaf/<Task-ID>/control.json` 是**两份不同 ownership evidence**（§6B.14）。

Schema（**只做 proposal**）：

```jsonc
{
  "launch_id": "<uuid4-hex>",
  "task_id": "AAF-XXX",
  "workspace": "D:\\...",
  "expected_runner_entry": "run.py",                        // 预期 runner 入口（规范化）
  "expected_command_line": ["python", "run.py", "<task>",
                            "--workspace", "<ws>", "--output", "<dir>"],  // 预期 argv
  "launcher_instance_id": "<bridge-instance-uuid>",          // §6B.16
  "created_at": "2026-08-27T10:00:00",
  "runner_pid": 12345,                                       // 启动后回填
  "runner_creation_time": "2026-08-27T10:00:00.000",         // 启动后回填（Windows 进程创建时间）
  "state": "PREPARED"                                        // PREPARED | RUNNING | EXITED | SUPERSEDED
}
```

`state` 状态机（proposal）：

```text
PREPARED → RUNNING → EXITED
                 ↘ SUPERSEDED（新 launch 覆盖旧 launch 时；旧 registry 标记 SUPERSEDED + 指向新 launch_id）
```

### 6B.12 启动顺序（Launcher 启动 Runner 前 → handshake）

```text
A. generate launch_id
B. create persistent Bridge launch registry entry = PREPARED
C. create task control.json with same launch_id（§6A.7）
D. launch runner
E. obtain PID / creation time（proc.pid + Windows process creation time）
F. update both records to RUNNING（registry + control.json）
G. Runner handshake 回写 control.json（runner_pid / runner_creation_time，§6A.6-4）
```

**要求：Bridge registry 与 task control artifact 必须能够交叉验证**（字段对齐：launch_id / task_id / workspace / runner_pid / runner_creation_time）。启动失败（B/C 之后、D 失败）：registry 标记 EXITED 或记录 FAILED_TO_START，control 相应清理，避免 phantom RUNNING。

### 6B.13 Launcher Restart 后的重新认证（Reauthentication）

Launcher / Tray 重启后，**不得仅信任 control.json**。必须同时读取：

```text
A. ~/.aaf-bridge/launches/<launch_id>.json   （Bridge launch registry）
B. .aaf/<Task-ID>/control.json               （task control artifact）
```

并验证（全部通过才恢复管理权）：

| # | 校验项 | 通过条件 |
|---|---|---|
| 1 | launch_id 相同 | registry.launch_id == control.launch_id |
| 2 | task_id 相同 | registry.task_id == control.task_id |
| 3 | canonical workspace 相同 | registry.workspace == control.workspace |
| 4 | runner PID 相同 | 实况进程 PID == registry.runner_pid == control.runner_pid |
| 5 | process creation time 相同 | 实况创建时间 == registry.runner_creation_time == control.runner_creation_time（防 PID recycle） |
| 6 | normalized command line 与 registry expected command 相符 | 实况命令行规范化后 == registry.expected_command_line 规范化 |
| 7 | process 当前存在 | PID 存活 |
| 8 | task 尚无 terminal state | task.json 无终态 |
| 9 | registry 未 EXITED / SUPERSEDED | registry.state ∈ {PREPARED, RUNNING} |
| 10 | control 未 stale / superseded | 非 stale（§6A.10）且 superseded_by == null |

- 全部通过 → **ownership = REAUTHENTICATED**（可继续观察、可响应 cancel / force cancel）。
- **任一失败 → ownership = UNCERTAIN → REFUSE FORCE TERMINATION**（UI 显示原因，如：存在孤儿 runner，建议人工处理或走恢复流程）。
- 重启后**不得自动 force kill**；**不得自动改写 task.json**（终态裁决权仍在 Core，§6A.1）。

### 6B.14 为什么 Bridge registry 是独立可信证据

- registry 位于 **Bridge 私有 state root**（`~/.aaf-bridge/launches/`），**不是 Task workspace 的 control.json 本身**。
- 因此 Launcher restart 后不是：

```text
control.json vs control.json   ← 自我比较，无意义
```

而是**三方验证**：

```text
Bridge launch registry        （launch 发起方的持久记录）
vs
Task control artifact         （task-owned 契约）
vs
Live Windows process identity （PID + creation time + command line）
```

- 两份记录由不同写者（Bridge vs Launcher/Runner）、落在不同目录（Bridge root vs task workspace）；一份被丢失/损坏/篡改时，另一份仍可交叉验证。

### 6B.15 Registry Stale / Cleanup 规则

以下任一情况 → registry 视为 stale / 失效：

- Task terminal（task.json 已有终态）
- process exited（PID 无存活进程）
- PID recycled（creation time 不一致）
- registry older generation（同一 launch_id 被更新的 registry 记录取代）
- launch superseded（registry.state == SUPERSEDED）
- workspace moved / deleted（registry.workspace 不存在）

处理：

- **上述情况下不得 force kill**。
- 可将 registry 标记 `EXITED` / `SUPERSEDED` / `STALE`。
- 历史记录**保留一段时间用于诊断**（保留时长由实现定，如 N 天）。
- 本任务**不决定自动清理实现**（仅定义规则）。

### 6B.16 Launcher Instance Identity

- 允许增加 `launcher_instance_id`（每次 Bridge 启动生成，用于诊断哪个 Bridge instance 创建了某 launch）。
- **明确：Launcher restart 后不能要求 instance_id 相同**，否则无法恢复管理。
- ownership 恢复基于：**persistent registry + task control + live process identity**（§6B.13），**而不是旧进程的内存身份**（旧进程已死，内存身份不可用也不可信）。

### 6B.17 Force Cancel 完整闭环

```text
User force cancel
→ ownership verification（§6A.8 全部通过；restart 场景为 §6B.13 三方验证）
→ verified process tree termination（taskkill /T /F）
→ record termination evidence（control.json.force_terminate_requested + registry 记录）
→ invoke Core recovery finalizer（finalize_cancelled_task，§6A.12/§6B.21）
→ acquire state.lock
→ re-read task.json（锁内）
→ existing terminal?
     yes → preserve existing terminal（不改写，返回 canonical）
     no  → commit CANCELLED（+ terminal_generation）
→ reconcile run.json / REPORT.md（§6B.6–§6B.8）
→ return canonical result
→ Launcher writes last_run.json from canonical result
```

### 6B.18 Normal Completion vs Force Cancel Race（terminal winner 规则）

**Winner 由"谁在同一把 Core lock 下先 commit"决定，不由 Launcher 时间猜测。**

```text
Case A（Runner 先拿到锁）：
Runner obtains state.lock first
→ SUCCESS committed（generation N）
→ Launcher/Core recovery later gets lock
→ sees terminal SUCCESS
→ CANCEL rejected / ignored（§6B.2-D）
→ SUCCESS wins

Case B（recovery cancel finalizer 先拿到锁）：
recovery cancel finalizer obtains state.lock first
→ CANCELLED committed（generation M）
→ Runner later gets lock
→ sees terminal CANCELLED
→ cannot write SUCCESS
→ CANCELLED wins
```

- 锁内 re-read（§6B.2-B/C/D）保证：任何后来的写者看到的是**已提交的** terminal truth，不存在"读到旧 RUNNING 后覆盖"的窗口。
- 与 §6A.2 终态优先规则一致；§6B 把它的执行从"尽力而为的原子读"升级为"锁内强制"。

### 6B.19 锁失败行为（Lock Failure）

如果 Core 无法取得 state.lock（超时 / 已被持有 / OS 错误）：

- **不写 terminal state**
- **不 force 推断**
- 返回 `FINALIZATION_BUSY`（或等价设计错误）
- UI 显示"正在收尾"或"恢复失败"
- **可以安全重试**
- **不得绕过锁**（不写 = 安全失败；绕过 = 重新引入竞态）

### 6B.20 Abandoned Lock / Crash Semantics

- **OS-level file lock 随进程退出自动释放**——Core 崩溃后锁不会永久占用，**避免永久逻辑死锁**。
- `state.lock` 文件本身可以留在磁盘；**"文件存在"不代表"锁被占用"**。
- **不得用 `if state.lock exists` 判断锁状态**——锁状态只能通过实际 acquire（或 OS 查询）得知。
- 崩溃后恢复路径（§6B.9）：直接 acquire 即可，残留文件不构成障碍。

### 6B.21 Recovery Finalizer 更新（finalize_cancelled_task）

`finalize_cancelled_task(...)` 必须：

```text
- acquire state.lock
- canonical reload（锁内重读 task.json）
- terminal arbitration（§6B.2-D：已有终态 → 返回 canonical，不改写）
- terminal commit if allowed（§6B.2-E/F/G）
- reconcile derived artifacts（run.json / REPORT.md，§6B.6–§6B.8）
- idempotent return（重复调用返回相同 canonical result）
```

**不再允许**：发现已有 terminal → 简单 return → 不检查 run/report。已有终态也必须走 reconciliation（§6B.6），保证派生产物跟随 canonical。

### 6B.22 Wait Thread 规则更新

```text
runner exits
→ wait thread calls/reads Core terminal result（task.json）
→ 如果 canonical terminal 存在但派生产物不完整：
     触发 Core reconciliation（§6B.6–§6B.8）
→ last_run follows canonical result
→ 仅当：无 terminal + Core recovery/reconciliation 无法得到合法 outcome
     才归类 Framework-level abnormal exit（FRAMEWORK_ERROR / FAILED 类）
```

（在 §6A.5 的两分支上增加中间分支："有 terminal 但派生产物不完整 → reconciliation"。）

### 6B.23 Process Ownership 与 Terminal Section 旧表述修正

- **§6A.9 修正**：重启后控制权恢复**不再以 control.json 单记录为准**；control.json 只是三方验证之一（§6B.13）。"可以重新读取 control.json"仅当与 registry + live process 全部一致才恢复管理权。
- **§6A.2/§6A.4 修正**：`os.replace` 不再被表述为跨进程互斥手段；它只保证单文件完整替换。跨进程 read/check/write 串行化由 `state.lock` 提供（§6B.1–§6B.2）。
- **§6A.6-5 修正**：Launcher 的持久 ownership record = Bridge launch registry（§6B.11），不再是"内存句柄 + control.json 内 launcher_pid"。

### 6B.24 复杂度评估调整（FIX-002）

**Cancel Lifecycle：保持 HIGH**（§16 同步），追加理由：

- cross-process lock（state.lock 临界区、锁失败与崩溃语义）
- persistent launch registry（第二记录 + 三方验证）
- reconciliation（派生产物幂等修复）

**Core Intrusion Risk：保持 MEDIUM**（§6A.16 不变），追加理由：

- cross-process terminal lock 进入 Core（锁 utility + 所有终态路径改造）
- persistent launch registry 与三方验证（Launcher 侧持久化）
- reconciliation protocol（Core 新增入口）

**不得把整个 Desktop Shell 评成 HIGH**：HIGH 仍仅限 Cancel lifecycle（Phase E）；Shell 其余部分（Tray / UI / 切换）评级不变。

### 6B.25 实施边界（FIX-002）

- 本任务**只修订设计文档**；不实现锁、不实现 reconciliation、不实现 registry、不修改 runtime / launcher / lifecycle / tests / .gitignore / Desktop UI。
- 实现归口：全部归入 Phase E（§15）——state.lock utility（§6B.3）、reconcile_terminal_artifacts（§6B.6）、Bridge launch registry（§6B.11）作为 E 的独立子项。
- backlog RW 状态不变（不标 SOLVED）；v0.3 CLOSED；v0.4 NOT STARTED；PROJECT_STATE 不变。
- `task_lifecycle.VALID_STATUSES` 不含 CANCELLED —— 保持不变（同 §6A.18）。
- 测试基线：**206 tests 保持通过**（本任务零代码改动，仅文档）。

### 6B.26 验收对照表（FIX-002 acceptance → 小节）

| Acceptance | 位置 |
|---|---|
| 1. per-task OS-level terminal lock 明确 | §6B.1 |
| 2. read/check/write 同锁完成 | §6B.2 |
| 3. os.replace 不再被当作 CAS | §6B.2/§6B.23 |
| 4. terminal winner rule 明确 | §6B.18 |
| 5. terminal_generation 定义 | §6B.4 |
| 6. task.json 是 canonical terminal truth | §6B.5 |
| 7. reconciliation protocol 存在 | §6B.6 |
| 8. partial commit 可恢复 | §6B.9 |
| 9. run.json 可按 terminal generation 修复 | §6B.8 |
| 10. REPORT 可幂等补齐 | §6B.8 |
| 11. last_run 不参与 terminal arbitration | §6B.10 |
| 12. Bridge persistent launch registry 存在 | §6B.11 |
| 13. registry 与 control.json 独立 | §6B.14 |
| 14. restart 需要双记录 + live process 三方验证 | §6B.13 |
| 15. PID creation time 继续校验 | §6B.13-5 |
| 16. command line 继续校验 | §6B.13-6 |
| 17. stale / superseded 规则存在 | §6B.15 |
| 18. ownership uncertain 时拒绝 force kill | §6B.13/§6B.15 |
| 19. force cancel end-to-end 闭合 | §6B.17 |
| 20. normal completion vs cancel race 由同一 Core lock 决定 | §6B.18 |
| 21. recovery finalizer 会 reconciliation | §6B.21 |
| 22. wait thread 可触发 Core reconciliation | §6B.22 |
| 23. OS lock crash-release semantics 定义 | §6B.20 |
| 24. Cancel HIGH / Core Intrusion MEDIUM 保持 | §6B.24 |
| 25. 无 runtime 实现 | §6B.25 |
| 26. backlog 未误标 SOLVED | §6B.25 |
| 27. v0.3 CLOSED | §6B.25 |
| 28. v0.4 NOT STARTED | §6B.25 |
| 29-33. tests PASS / WorkBuddy / Codex / commit+push / 不自动实现 | 由执行报告与 §19 FIX-002 清单验证 |

---

## 7. Bridge Background Runtime 设计

### 7.1 候选比较

| 方案 | 无终端常驻 | 复杂度 | 用户可控性 | 故障恢复 | 结论 |
|---|---|---|---|---|---|
| pythonw background process（Bridge 以 pythonw 启动） | ✅ | 低 | 高（Tray 管理） | 进程崩溃需手动/自启重启 | **首选宿主** |
| Windows Startup（启动文件夹/注册表 Run） | ✅（自启） | 低 | 中 | 登录时自动恢复 | **首选自启机制**（与 pythonw 组合） |
| Scheduled Task | ✅ | 中 | 中 | 可配重启策略 | 不必要（它解决"定时"问题，不是"常驻"问题） |
| Tray process owns Bridge | ✅ | 低 | 高 | 随 Tray 宿主 | 与 pythonw 方案等价，见 7.2 |
| Windows Service | ✅ | 高 | 低（需服务管理） | 高 | **第一版明确排除**（7.3） |

### 7.2 推荐最小方案

```
启动方式: pythonw.exe 运行 Bridge 入口脚本（无控制台窗口）
自启:     启动文件夹（%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup）
          放一个 run_bridge.vbs / 快捷方式（第一版）；注册表 Run 键为备选
宿主:     Bridge 进程即 Tray 宿主（pystray/ctypes 图标 + tkinter 状态窗口 + 热键线程 + launcher）
```

- **用户启动 AAF 后不需要 Terminal 常驻**：Bridge 由 pythonw 承载，无控制台；用户平时只看到 Tray 图标。
- **关闭状态窗口 ≠ 退出 Bridge**：状态窗口是 tkinter `Toplevel`，关闭只 `withdraw()` 隐藏；Bridge 继续常驻。退出 AAF 的唯一途径是 Tray 菜单 [退出 AAF]（带确认）。
- **Tray 图标显示 Bridge 是否健康**：图标/气泡颜色映射 Bridge Health（§8）：正常（绿/正常图标）、异常（黄/红）、未运行（无图标——由启动器负责）。
- Tray 提供最小三项：**打开状态 / 重启 Bridge / 退出 AAF**（重启 = 自身退出并由自启机制/守护逻辑重新拉起；第一版实现为"退出后提示用户重新运行启动脚本"，或由一个极小的 watchdog 入口负责重启——见 §8 的 Restart Bridge 语义）。

### 7.3 Windows Service 是否必要：**第一版明确排除**

理由：

1. tkinter UI / 热键在 Session 0（服务会话）不可见——服务承载 GUI 是错误模型。
2. 服务需管理员权限安装、需服务管理器操作，与"轻量、用户可控"目标冲突。
3. 本场景是"单用户桌面常驻"，不是"系统级无人值守服务"；pythonw + 自启已满足。
4. 引入服务会显著抬高运维复杂度（日志、权限、升级），无对应收益。

排除记录：`NOT_IN_FIRST_VERSION: Windows Service`（§17）。

### 7.4 Exit AAF 语义

- [退出 AAF] → 确认窗（中文）：若当前有任务运行中，提示"当前任务将被中断（按取消处理）"→ 用户确认 → 先写 cancel.request 并（如需）强终止 runner → 退出 Bridge 进程。
- **Stop Current Task 与 Exit AAF 明确分离**（RW-014 Do Not Forget）：取消任务不动 Bridge；退出 AAF 是整体关闭（含确认）。

---

## 8. Hotkey Health 设计（RW-012）

核心原则（RW-012 Do Not Forget）：**process alive ≠ listener healthy**。

### 8.1 最小健康模型（4 个事实）

```
Bridge Health:
  1. process alive        — 进程存在（Tray 自身运行时恒真；对"未运行"判定由自启入口负责）
  2. hotkey registered    — RegisterHotKey 成功（listener._ready + error()==None，现有代码已有）
  3. listener loop alive  — GetMessageW 消息循环线程存活（listener.is_alive()，现有代码可查）
  4. last heartbeat       — 最近一次事件/循环 tick 时间戳（第一版不实现，见下）
```

### 8.2 第一版可落地判定（不实现 heartbeat）

| 组合 | 判定 | Tray 显示 |
|---|---|---|
| 进程存在 且 2、3 均真 | Bridge 正常 | `Bridge 正常运行`（绿） |
| 进程存在 但 2 或 3 为假 | Bridge 异常（热键失活） | `Bridge 异常`（黄/红，气泡提示"热键可能无响应"） |
| 进程不存在 | Bridge 未运行 | `Bridge 未运行`（灰，提供 [启动 Bridge]） |

- 2/3 的检查 = 直接复用现有 `HotkeyListener.wait_ready()` / `error()` / `is_alive()`，零新机制。
- 热键失活的**自恢复**（重注册）列为候选（RW-012 Remaining Gap 的 listener self-recovery），第一版提供 [重启 Bridge] 一键恢复，不自动重注册（避免与冲突源反复抢键）。

### 8.3 heartbeat（未来，不在本任务实现）

- 提案：listener 循环内每收到一条消息（或每 N 秒）更新 `last_heartbeat` 时间戳；Tray 轮询时若 `now - last_heartbeat > 阈值` 且 3 为真 → 判定"循环活着但无消息"→ 仍算正常（热键本就低频）；该值主要用于诊断日志。
- 本任务**不实现** heartbeat（TASK 要求 19 明确排除）。
- **约束（FIX-001 补充）**：未来 heartbeat **不能依赖阻塞 `GetMessageW` 的自然周期 tick**（消息循环可长期阻塞，tick 不更新 → heartbeat 恒旧）；必须使用 timer（`SetTimer` / tkinter `after`）或 worker thread 或 non-blocking heartbeat mechanism（§6A.17）。仍属设计约束，不实现。

---

## 9. Project Switching 设计（RW-003）

### 9.1 触发场景

TASK Workspace ≠ Bridge `current_workspace` 时，当前实现直接报 `Workspace 不匹配` 错误。第一版改为**显式确认切换**流程：

```
检测到新项目：

  当前：  AI Agent Framework
         D:\AdyAI\ai-agent-framework

  TASK：  观微记 H5
         D:\AdyAI\guoxue-skills-lab

  [切换并执行]   [取消]
```

### 9.2 设计规则

1. **不静默切换**：任何 workspace 变化必须经过上面的确认窗；取消 = 不切换、不执行、不写任何文件。
2. **切换动作**（确认后）：更新 `~/.aaf-bridge/config.json` 的 `current_project` / `current_workspace` → 更新 `recent_projects`（见下）→ 继续正常执行链。
3. **Recent Projects**（配置 schema 提案，不实现）：

```
config.json 新增:
  "recent_projects": [
    {"name": "AI Agent Framework", "workspace": "D:\\AdyAI\\ai-agent-framework", "last_used": "2026-08-27T09:50:00"},
    ...
  ]
```

   第一版上限 5 条，按 last_used 倒序；切换确认窗中提供"从最近项目选择"下拉（可选，若实现成本低；否则仅确认窗）。
4. **不自动扫描整个磁盘**：候选项目只来自 recent_projects + TASK 声明的 workspace。不实现目录扫描器。
5. **current_project / current_workspace 更新位置明确**：唯一写入点 = Bridge config 模块（`bridge/config.py`），新增 `update_project()` 纯函数（写 config.json + 更新 recent_projects），UI / 流程调用它，不直接改文件。
6. 校验层兼容：`task_io.validate_task_text` 的 workspace 不匹配目前是硬错误——设计为 Bridge 层在调用校验前**先比较** workspace，发现不一致直接进入确认切换流程（不动 parser 纯函数；或给 validate 增加 `allow_workspace_switch` 参数，实现时二选一，倾向 Bridge 层处理以保持 parser 纯净）。
7. 防漂移：切换确认窗文案必须包含"将修改 AAF Bridge 的项目设置"说明；最近项目列表只做选择入口，不自动触发切换。

---

## 10. Duplicate Task UX 设计（RW-016）

原则（RW-016 Do Not Forget）：`TASK_ALREADY_EXISTS` 本身不是错误；缺口是"只告诉存在，不告诉现在是什么状态"。**不得删除 duplicate protection**。

### 10.1 触发与信息卡片

Bridge 捕获 `TaskParseError(TASK_ALREADY_EXISTS)` 后，不再只弹一行错误，而是查询既有任务状态并显示卡片：

```
任务已存在

Task ID:        AAF-MAINT-002
当前状态:       已完成（SUCCESS）          ← 中文映射（§11）
当前阶段:       REPORT（全部完成）
最近活动:       2026-08-27 09:41
结果:           SUCCESS；Codex APPROVE
REPORT 路径:    D:\...\.aaf\AAF-MAINT-002\REPORT.md

[查看状态]  [打开 REPORT]  [返回]
```

### 10.2 状态来源映射（现有即可用）

| 卡片字段 | 来源 |
|---|---|
| Task ID | duplicate 检查时已知 |
| Current Status | `.aaf/<id>/task.json` 的 status（缺失 → "状态未知"；损坏 → 提示） |
| Current Stage | route.json + prompt/result 文件存在性（§3 映射） |
| Last Activity | max(产物 mtime)（§5.1） |
| Result | REPORT.md 存在 → 读取 Current Status 行；或 last_run.json |
| REPORT Path | task.json.report_path → 不存在时归档兜底（task_archive.find_report_path） |

### 10.3 候选操作

- **[查看状态]**：打开状态窗口并聚焦该任务（第一版：直接展示同一卡片 + 阶段条）。
- **[打开 REPORT]**：用系统默认编辑器打开 REPORT.md（`os.startfile`）；归档任务自动定位到 `.aaf/archive/<id>/REPORT.md`。
- **[返回]**：关闭弹窗，不做任何操作。
- **[Resume]**：仅当生命周期允许（status=WAITING 或 FAILED 且产物完整）时显示为次级操作（第一版可只显示提示"该任务需重新提交"，Resume 按钮列入 Phase F 评估；`--resume-from` 已存在，风险在于 UX 确认，不在本任务定死）。
- 运行中任务：卡片显示当前阶段 + elapsed + [查看状态]；不提供 [打开 REPORT]（REPORT 尚未生成）。

---

## 11. Chinese-first UI（RW-015）

原则：**所有人类主界面默认中文**；日志、内部协议、技术状态字段保留英文；第一版不建设完整国际化系统（无 i18n 框架，无语言切换）。

### 11.1 核心文案映射表（第一版必须包含）

| 技术字段 / 英文状态 | 中文界面显示 |
|---|---|
| Bridge Running | Bridge 正常运行 |
| Bridge Error / degraded | Bridge 异常 |
| Bridge Not Running | Bridge 未运行 |
| Hermes Running | Hermes 执行中 |
| WorkBuddy Running | WorkBuddy 复核中 |
| Codex Running | Codex 审查中 |
| CREATED | 已创建 |
| RUNNING | 执行中 |
| WAITING | 等待处理 |
| SUCCESS | 已完成 |
| FAILED | 执行失败 |
| FRAMEWORK_ERROR | 框架错误 |
| CANCELLED | 已取消 |
| TASK_ALREADY_EXISTS | 任务已存在 |
| REPORT_NOT_FOUND | 未找到报告 |
| FAILED_TO_START | 启动失败 |
| suspected stuck | 疑似卡住 |
| estimated progress | 估算进度 |

- 状态窗口、Tray 菜单、确认窗、错误弹窗、按钮、提示语全部中文（§12 wireframe 中的文案即第一版默认文案）。
- 技术字段（status 值、Task ID、路径、agent 名）在详情视图/日志中保留英文原样，不翻译。
- 现有 Bridge 弹窗（ui.py 的 Execute/Cancel 按钮等）在 Phase C 一并中文化（属 UI 文案修改，不改变逻辑）。

---

## 12. 文字版 UI Wireframe

### 12.1 主状态窗口（第一版）

```
┌──────────────────────────────────────────────────────────────┐
│  AI Agent Framework                                          │
│                                                              │
│  当前项目：AI Agent Framework                                 │
│  Bridge：正常运行       热键：Ctrl+Alt+A                      │
│                                                              │
│  ── 当前任务 ──────────────────────────────────────────────  │
│  Task ID：AAF-DESIGN-001                                     │
│  Task Name：Desktop Shell and Runtime Control Minimal Design │
│  当前阶段：WorkBuddy       当前 Agent：WorkBuddy              │
│  已运行：12:34       最近活动：2 分钟前                       │
│  整体结果：执行中                                             │
│  整体进度：约 64%（估算）                                     │
│                                                              │
│  [██████████████░░░░░░░░░░░░░░]                               │
│                                                              │
│  Validation ✓   Boundary ✓   Hermes ✓                       │
│  WorkBuddy ▶    Codex ○      REPORT ○                        │
│                                                              │
│  最近活动：                                                  │
│   · 09:51 WorkBuddy 复核开始                                  │
│   · 09:48 Hermes 执行完成                                     │
│                                                              │
│  [查看日志]            [停止当前任务]                          │
│                                                              │
│  ──────────────────────────────────────────────────────────  │
│  [切换项目]      [重启 Bridge]      [设置]                    │
└──────────────────────────────────────────────────────────────┘
```

状态标注约定：

- `✓ 已完成`、`▶ 进行中`、`○ 未开始`、`⏸ 等待处理`、`✗ 失败`、`⊘ 已取消`。
- "约 XX%（估算）"必须出现在进度条旁；禁止显示剩余时间。
- [停止当前任务] 仅当任务 RUNNING 时可用；点击后变灰 → "正在取消…"。
- [查看日志] 第一版 = 打开输出目录（`os.startfile`）或打开最近日志文件；不做内嵌日志查看器。

### 12.2 Tray 菜单最小结构

```
[AAF 图标]
├─ 打开状态窗口
├─ ───────────
├─ 当前项目：AI Agent Framework        （子菜单/灰显信息行）
├─ 当前任务：AAF-DESIGN-001（执行中）   （灰显信息行）
├─ ───────────
├─ 停止当前任务                         （仅运行中可用；点击后变"正在取消…"）
├─ ───────────
├─ 重启 Bridge
├─ 退出 AAF                            （确认窗：含"当前任务将被中断"提示）
```

- 信息行灰显不可点；操作用中文。
- 图标颜色反映 Bridge Health（§8）：正常 / 异常 / 未运行。

### 12.3 关键弹窗（第一版）

| 弹窗 | 触发 | 按钮 |
|---|---|---|
| 项目切换确认（§9.1） | workspace 不一致 | [切换并执行] [取消] |
| Duplicate 状态卡片（§10.1） | TASK_ALREADY_EXISTS | [查看状态] [打开 REPORT] [返回] |
| 停止确认 | [停止当前任务] | [确认停止] [取消] |
| 强制停止确认 | [强制停止] | [确认强制停止] [取消]（红色警示文案） |
| 退出 AAF 确认 | [退出 AAF] | [确认退出] [取消] |

---

## 13. Runtime State Source

原则：**UI 不能靠猜测**。所有显示必须可追溯到现有 artifact 或 Phase A 新增字段。

### 13.1 现有可利用的真实状态源（见 §1.1 表）

task.json / route.json / boundary.json / `<agent>_prompt.md` / `<agent>_result.md` / REPORT.md / run.json（仅结尾）/ last_run.json / config.json / launcher 内存中的 Popen 状态。

### 13.2 识别出的缺失字段（现状无法回答的问题）

| 缺失 | 现状问题 | 影响 |
|---|---|---|
| started_at | 只有 updated_at（每次状态迁移被覆盖），无法知道"何时开始" | elapsed 不可算 |
| stage / current stage | 只能从产物存在性推断，Validation 失败时**无任何 artifact** | 阶段显示不可靠 |
| stage_started_at | 无 | stage 时长 / stuck 判定不可算 |
| last_activity_at | Agent 执行期间产物无变化（§1.1），UI 无法区分"运行中"与"卡住" | 黑盒感根因 |
| agent（current agent） | 只能从 prompt/result 文件推断 | 当前 Agent 显示不可靠 |
| cancel_requested | 无取消通道 | Cancel 设计（§6）依赖 |
| pid（runner 进程） | Launcher 有句柄但不持久化 | 强终止 / 健康检查不可靠 |
| per-stage 完成标记 | prompt/result 文件是隐式标记 | 阶段条（§3）依赖推断 |

### 13.3 Schema 提案（**只提案，本任务不修改 schema**）

`task.json` 扩展（向后兼容：全部新字段可选，旧产物不失效）：

```jsonc
{
  "task_id": "AAF-XXX",
  "status": "RUNNING",              // 现有
  "updated_at": "...",              // 现有
  "task_path": "...",               // 现有
  "workspace": "...",               // 现有
  "report_path": null,              // 现有
  "started_at": "2026-08-27T09:50:36",       // 新增：首次进入 RUNNING 时刻（不可变）
  "stage": "workbuddy",                      // 新增：validation|boundary|hermes|workbuddy|codex|report|done
  "stage_started_at": "2026-08-27T10:03:12", // 新增：当前 stage 开始时刻
  "last_activity_at": "2026-08-27T10:05:00", // 新增：最近活动（runner 每阶段/agent 边界更新）
  "agent": "workbuddy",                      // 新增：当前 agent（或 null）
  "pid": 12345,                              // 新增：runner 进程 PID（Launcher 注入 env 或 runner 自写）
  "cancel_requested": false,                 // 新增：cancel 请求标记（与 cancel.request 文件互为镜像）
  "phases": [                                // 新增（可选）：per-stage 记录，供阶段条与 RW-005 校准
    {"name": "validation", "status": "done", "started_at": "...", "finished_at": "..."}
  ]
}
```

写入规则提案：

- `started_at`：首次 `RUNNING` 时写入后不再变更。
- `stage` / `stage_started_at` / `agent`：runner 每个阶段边界原子更新（与现有 update_status 同一原子写路径）。
- `last_activity_at`：阶段边界更新 + Agent 执行期间由 runner 周期性 touch（如每 60s，轻量；仅当 last_activity_at 更新时重写 task.json——注意写入频率，建议 ≥30s 间隔，避免磁盘抖动）。
- `pid`：runner 启动时自写（`os.getpid()`），Launcher 强终止前读取校验；与 §6A.6 的 `launch_id` 协议配合——**运行期 ownership 判定以 control.json 为准**（§6A.7），task.json.pid 是冗余字段；**restart 恢复场景为 registry + control + live process 三方验证**（§6B.13）。
- `cancel_requested`：与 cancel.request 文件一致；UI 优先读文件（单一事实源），task.json 字段作冗余。
- Validation 失败仍无 artifact（现状 exit 2）：设计为 Bridge/Launcher 在 FAILED_TO_START 路径旁记录"validation failed"事件到 last_run.json（增量，不动 runner）。

`run.json` 变更提案：合法 status 集合增加 `CANCELLED`（§6.7）；其余不变。

`config.json` 变更提案：新增 `recent_projects`（§9.2）。

---

## 14. Core / UI 边界

目标：**Desktop Shell → 调用 / 观察 AAF Core**；Desktop Shell **绝不**复制 Router / Runner / Lifecycle / Agent 适配逻辑。

### 14.1 UI 可以做什么

| 类别 | 动作 |
|---|---|
| 观察（只读） | 读 task.json / route.json / boundary.json / prompt / result / REPORT / last_run.json / config.json；计算 elapsed / last activity / 估算进度 / stuck 提示；检查 listener 健康（§8） |
| 操作（经 Bridge 代理） | 触发热键等价流程（读剪贴板→确认→落盘→launch）；写 cancel.request；调用 launcher 强终止（**§6A.8 ownership verification 通过后**）；更新 config（project 切换 / recent_projects）；打开日志目录 / REPORT；重启 / 退出 Bridge 进程 |
| 展示 | 中文文案、阶段条、进度条、按钮状态机 |

### 14.2 Core 必须做什么（不变更职责）

| 组件 | 职责（现状保持） |
|---|---|
| Runner | Validation / Boundary / Router 调用 / Agent 链 / 聚合 / REPORT / lifecycle 写入；新增：cancel 检查点与 CANCELLED 收敛（§6） |
| Lifecycle | task.json 状态机（新增 CANCELLED 合法值 + §13.3 字段写入，属 Phase A/E 增量） |
| Launcher | 启动 run.py 子进程、单任务保护、收尾判定（新增：launch_id / control.json 持久化、强终止 + 调用 Core recovery finalizer §6A.12） |
| 协议 | TASK / REPORT 格式不变；产物契约不变 |

### 14.3 两者之间的最小接口

第一版**只有两类接口**（不引入 RPC / HTTP / IPC / 数据库）：

```
1. 文件契约（唯一状态通道）:
   - 读：<output_dir>/{task.json, run.json, route.json, <agent>_prompt.md,
         <agent>_result.md, boundary.json, REPORT.md}
   - 写：<output_dir>/cancel.request；~/.aaf-bridge/config.json
2. 进程契约（唯一执行通道）:
   - 启动：subprocess.run(run.py <task> --workspace <ws> --output <dir>)
   - 终止：taskkill /T /F /PID <runner_pid>（强终止，§6A.8 ownership verification 全部通过后）
   - 完成通知：launcher 等待线程 → 事件队列 → UI 弹窗（现有机制）
```

### 14.4 防侵入规则（未来实现时强制）

1. Desktop Shell 代码**不得 import** `ai_agent_framework.router` / `runner` / `adapters` / `task_lifecycle` 并调用其内部函数来"替 Core 做事"；唯一允许的 Core 依赖 = 只读工具函数（如 `task_archive.find_report_path`、`git_status`）与配置模块。
2. 状态显示**只读产物**；任何"写状态"动作必须经由：runner（正常收敛）/ **Core recovery finalizer**（强杀恢复终态，§6A.12）/ config 模块（项目切换）三个归属者之一；Launcher 不得直接写终态（§6A.1）。
3. 新增状态字段的**唯一写者**是 runner / lifecycle / launcher；UI 永远不直接写 task.json / run.json。
4. Desktop Shell 不实现 Router 判定、不实现阶段逻辑、不实现 agent 调用；遇到需要这些能力的需求 → 回到 Core 加接口（如 `--watch-cancel` 参数），而不是在 Shell 侧复制。

---

## 15. 实施拆分（Phase A-F）

按依赖排序；允许调整顺序（说明见各 Phase）。

### Phase A — Runtime State Foundation

- **Goal**：让运行时状态可被外部只读观测（schema 扩展 + runner 阶段标记写入），为一切 UI 提供事实底座。
- **Files likely affected**：`ai_agent_framework/task_lifecycle.py`（update_status 增加可选字段与 CANCELLED 合法值）、`ai_agent_framework/runner.py`（阶段/agent/last_activity 写入、pid 自写、started_at 一次性写入）、`tests/test_task_lifecycle.py`、`tests/test_runner.py`。
- **Dependencies**：无（纯 Core 侧；不依赖 Bridge）。
- **Risk**：低（新字段全部可选，向后兼容；原子写路径复用现有实现）。
- **Acceptance**：task.json 在真实运行中包含 started_at / stage / stage_started_at / last_activity_at / agent / pid；Validation 失败场景有 Bridge 侧记录；206 tests 保持通过 + 新增字段单测。
- **可单独发布 / 测试**：是（对现有行为零影响，可独立验证）。

### Phase B — Bridge Background / Tray Skeleton

- **Goal**：Bridge 以 pythonw 无控制台常驻；Tray 图标 + 最小菜单（打开状态 / 重启 / 退出）；Hotkey Health 判定（§8）。
- **Files likely affected**：`bridge/main.py`、`bridge/tray.py`（新）、`bridge/launcher.py`（pid 持久化）、`scripts/start_bridge.pyw`（新，pythonw 入口）、`docs/QUICKSTART.md` / `TROUBLESHOOTING.md`。
- **Dependencies**：Phase A 可选（Tray 健康显示可先显示进程级状态）；建议 A 先行以显示 stage。
- **Risk**：中（进程模型变化：需验证 pythonw 下 tkinter 主循环 / ctypes 热键 / 剪贴板行为不变；自启项行为需人工验证）。
- **Acceptance**：无控制台窗口运行；热键仍可用；Tray 菜单三项可用；关闭状态窗口不影响 Bridge；[重启 Bridge] 生效。
- **可单独发布 / 测试**：是（骨架 + 菜单可独立验收）。

### Phase C — Status Window + Chinese UI

- **Goal**：§3 信息架构 + §12 wireframe 的状态窗口；全部人机界面中文（§11）；现有 ui.py 弹窗文案中文化。
- **Files likely affected**：`bridge/status_window.py`（新）、`bridge/ui.py`、`bridge/main.py`（窗口开关）、`bridge/handoff.py`（文案，如有）。
- **Dependencies**：A（状态读取）、B（宿主）。
- **Risk**：低（纯 UI，无 Core 改动）。
- **Acceptance**：主窗口按 §12.1 呈现全部字段；阶段条映射正确（§3 表格）；中文文案表（§11.1）全部落实；关闭窗口不退出 Bridge。
- **可单独发布 / 测试**：是。

### Phase D — Progress Visualization

- **Goal**：估算进度条 + 权重表（§4.2）+ 收敛规则（§4.1.5）+ last activity（§5.1）+ suspected stuck 提示（§5.2）。
- **Files likely affected**：`bridge/status_window.py`（进度条渲染）、`bridge/progress.py`（新：权重/估算/收敛纯函数，可单测）、`bridge/stuck.py`（新：阈值判定纯函数，可单测）。
- **Dependencies**：A、C。
- **Risk**：低-中（风险在"估算语义被误读"，靠文案约束与收敛规则控制）。
- **Acceptance**：估算值与阶段状态计算一致；SUCCESS/WAITING/FAILED/CANCELLED 均按收敛规则定格；所有百分比旁有"估算"标注；stuck 提示只提示不动作。
- **可单独发布 / 测试**：是（纯函数单测 + UI 集成验收）。

### Phase E — Safe Cancel Lifecycle

- **Goal**：§6 + §6A + §6B 完整落地：cancel.request 契约、runner 检查点、CANCELLED 终态、Launcher 强终止（launch_id / control.json / Bridge launch registry / §6A.8 + §6B.13 ownership verification）+ Core recovery finalizer（§6A.12/§6B.21）+ state.lock（§6B.1–§6B.3）+ reconciliation（§6B.6–§6B.8）、UI 按钮状态机、race 规则。
- **Files likely affected**：`ai_agent_framework/task_lifecycle.py`（CANCELLED）、`ai_agent_framework/runner.py`（`--watch-cancel <path>` 参数 + 检查点 + control.json 写回）、`ai_agent_framework/finalize_cancelled.py`（新：Core recovery finalizer CLI，§6A.12/§6B.21）、`bridge/launcher.py`（launch_id、control.json、§6A.8 ownership verification、taskkill）、`bridge/status_window.py` + `bridge/tray.py`（按钮/状态机）、`tests/test_runner.py`、`tests/test_bridge_launcher.py`、`tests/test_finalize_cancelled.py`（新）、`ai_agent_framework/lock_utils.py`（新：state.lock 封装，§6B.3）、`ai_agent_framework/reconcile.py`（新：reconcile_terminal_artifacts，§6B.6）、`bridge/launch_registry.py`（新：persistent launch registry，§6B.11）。
- **Dependencies**：A（字段）、B（宿主）；与 C/D 解耦（Core 部分可独立先行）。
- **Risk**：**高**（进程终止安全、race condition、误杀防护；FIX-002 追加：cross-process lock、reconciliation、persistent launch registry（§6B.24））——本 Phase 必须经过 Codex 专项 audit 与真实任务演练。
- **Acceptance**：单测覆盖检查点/终态/重复点击/race（§6.9 场景 1-3）；真实任务 Cancel 后 task.json= CANCELLED、REPORT 生成、产物保留、独立会话存活；强终止 §6A.8 ownership verification 拒绝错误目标；finalizer 幂等。
- **可单独发布 / 测试**：是（Core 侧先于 UI 发布，可用 CLI 演练）。

### Phase F — Project Switching / Duplicate UX

- **Goal**：§9 项目切换确认 + recent_projects；§10 Duplicate 状态卡片。
- **Files likely affected**：`bridge/config.py`（update_project / recent_projects）、`bridge/task_io.py`（如需 workspace 切换兼容参数）、`bridge/main.py`（切换流程接入）、`bridge/ui.py`（确认窗 / 卡片）、`tests/test_bridge_config.py`、`tests/test_bridge_task_io.py`。
- **Dependencies**：B、C（UI 宿主与中文窗）。
- **Risk**：低-中（切换确认涉及 config 写，但流程简单；duplicate 卡片只读产物）。
- **Acceptance**：workspace 不一致时出现确认窗；确认后 config 正确更新且 recent_projects 更新；拒绝时不写任何文件；duplicate 提示显示 §10.1 卡片全部字段；[打开 REPORT] 对归档任务生效。
- **可单独发布 / 测试**：是。

### 顺序结论

推荐执行顺序：**A → B → C → D → E → F**（依赖驱动）。
可选调整：若 Cancel 安全优先级高于可视化，可将 E 的 Core 部分（runner 检查点 + CANCELLED + launcher 强终止）提前到 B 之后、C 之前独立发布（E-core 不依赖 C/D）；UI 按钮在 C 后接入。本设计按依赖排序，最终顺序由 Planner 决定。

---

## 16. 复杂度评估

| 项 | 复杂度 | 说明 |
|---|---|---|
| Tray | MEDIUM | pystray/ctypes + 图标 + 菜单 + 健康颜色；代码量小但 Windows 细节多 |
| background Bridge | LOW | pythonw 入口 + 启动快捷方式；无需服务 |
| status window | LOW | 纯 tkinter 只读展示 |
| progress bar | LOW | 静态权重 + 状态映射；逻辑简单，约束在文案 |
| last activity | MEDIUM | 多源 mtime 聚合 + 阈值调参；依赖 Phase A 字段才可靠 |
| Cancel lifecycle | **HIGH** | 进程树终止、race、误杀防护、Core recovery finalizer；FIX-002 追加：cross-process lock（state.lock）、reconciliation、persistent launch registry（§6B.24）；唯一高风险项 |
| project switching | LOW | 确认窗 + config 更新 |
| packaging | MEDIUM | PyInstaller 单目录；**第一版可不做**（pythonw + 快捷方式先行） |
| autostart | LOW | 启动文件夹快捷方式；注册表 Run 为备选 |

### 总体评估

| 维度 | 评级 | 理由 |
|---|---|---|
| Feasibility | **HIGH** | 全部能力基于现有 tkinter/ctypes/subprocess 与产物契约；无新框架 |
| Engineering Complexity | **MEDIUM** | 总体轻量；唯一 HIGH 项是 Cancel（集中在 Phase E） |
| Core Intrusion Risk | **MEDIUM** | 从 LOW 上调（FIX-001，§6A.16）：新增终态 CANCELLED、跨进程取消、process ownership（launch_id / creation time / command line 校验）、recovery finalization（finalize_cancelled_task）、multi-artifact 一致性提交（§6A.4）。FIX-002 追加：cross-process terminal lock（state.lock）、persistent launch registry 与三方验证、reconciliation protocol（§6B.24）。**评级保持 MEDIUM，不随 Cancel 升 HIGH**。Core 改动面仍限于 Phase A/E，但状态机与终态语义侵入深度高于原评估 |
| Maintenance Cost | **LOW** | 单进程、文件契约、无前端/无服务/无 IPC 框架 |

---

## 17. 推荐的第一版范围（MVP）

### MVP Desktop Shell MUST HAVE

1. Bridge 以 pythonw 常驻（无终端依赖），启动文件夹自启。
2. Tray 图标 + 最小菜单：打开状态窗口 / 重启 Bridge / 退出 AAF；图标反映 Bridge Health（正常/异常/未运行）。
3. 状态窗口（§3 IA / §12.1 wireframe）：当前项目 / Bridge 状态 / 当前任务（ID/Name/Stage/Agent/elapsed/last activity/result）/ 六阶段条。
4. 估算进度条（§4）：事实与估算分离、收敛规则、中文"估算"标注。
5. Last activity + 疑似卡住提示（§5）：只提示、不自动终止。
6. Stop Current Task（§6 完整生命周期）：cooperative cancel + 强终止兜底 + CANCELLED 终态 + 防误杀。
7. Chinese-first 全 UI（§11 文案表）。
8. Duplicate Task 状态卡片 + 打开 REPORT（§10）。
9. Project Switching 显式确认 + recent_projects（§9）。
10. Phase A 状态字段（started_at / stage / stage_started_at / last_activity_at / agent / pid / cancel_requested）。

### NOT IN FIRST VERSION（明确排除）

- 安装包 / 分发打包（PyInstaller / installer）→ 独立后续（RW-010 的 packaging 部分）。
- Windows Service（§7.3 已论证排除）。
- heartbeat 机制（§8.3；第一版用 is_alive/error 判定健康）。
- 真实时间预测 / 动态权重校准（等 RW-005 数据）。
- 内嵌日志查看器（用"打开日志目录"替代）。
- 设置中心（设置项并入 Tray/状态窗口；不单独建页）。
- 多语言切换 / i18n 系统。
- Resume 按钮（第一版仅提示；Resume 走既有 `--resume-from` CLI，UX 按钮列入后续评估）。
- 任何 Web / SaaS / 多用户 / 云同步 / marketplace / 远程协作能力（RW-010 防漂移边界，自动扩展禁止项）。

---

## 18. 设计边界确认

1. **本任务只设计**，未实现：Tray / GUI / progress bar / cancel / autostart / project switching / packaging / heartbeat / 新 runtime schema。本仓库**无任何产品功能代码改动**（唯一变更 = docs 设计文档 + backlog/PROJECT_STATE 登记）。
2. **不启动 v0.4**：v0.3 CLOSED、v0.4 NOT STARTED 保持不变（见 PROJECT_STATE）。是否将 Desktop Shell 纳入 v0.4 由 Planner 单独决策。
3. **Backlog 未标 SOLVED**：RW-003/004/005/006/010/012/014/015/016 状态不变；仅新增 Design Reference 指向本文档。
4. **PROJECT_STATE 仅增加**："Desktop Shell design completed / implementation not started"，版本状态不变。
5. 现有 lifecycle（task_lifecycle 状态机、runner 主流程、归档规则）**未被修改**；§6/§13 均为实现阶段的增量提案。

---

## 19. 审查指引（WorkBuddy / Codex）

### WorkBuddy（可用性与完整性重点）

1. 方案是否真的轻量（§2/§16/§17：无前端、无服务、无新进程架构、依赖增量极小）。
2. 是否解决 PowerShell / Terminal 常驻问题（§7：pythonw + Tray + 自启；明确排除 Service）。
3. 是否有 Runtime 状态来源（§13：现有 artifact + Phase A 字段提案；UI 不靠猜测）。
4. progress 是否区分事实与估算（§4.1：Stage State 与 Estimated Percentage 分离；收敛规则）。
5. Cancel 是否有正式 lifecycle 设计（§6：CANCELLED 终态、检查点、race/重复点击规则、产物保留）。
6. Bridge 与 Task Cancel 是否分离（§6.1/§7.4：Cancel 不动 Bridge；Exit AAF 单独语义）。
7. 项目切换是否保持显式确认（§9：确认窗、不静默、不扫描磁盘）。
8. Chinese-first 是否明确（§11 文案表）。
9. 是否避免大型 Dashboard（§2.2 排除 C/D；§17 Not-in-v1）。
10. 是否没有提前实现（§18.1：零功能代码改动）。

#### FIX-001 追加检查清单（WorkBuddy）

1. terminal state 是否只有一个 authoritative finalizer（§6A.1）？
2. wait thread 是否不会再把 force cancel 误判为 FAILED（§6A.5）？
3. last_run 是否跟随 Core outcome（§6A.4/§6A.5）？
4. PID recycle 是否处理（§6A.8 creation time 校验 / §6A.10 stale）？
5. Launcher restart 是否安全（§6A.9）？
6. stale lease 是否定义（§6A.10）？
7. force cancel 是否默认拒绝不确定 ownership（§6A.8/§6A.9）？
8. cancel.request 是否不是 terminal truth（§6A.15）？
9. race / duplicate cancel 是否闭合（§6A.13/§6A.14）？
10. 是否无代码实现（§6A.18）？

### Codex（架构 / scope 审计重点）

1. UI / Core 边界（§14：文件契约 + 进程契约；Shell 不 import Core 执行逻辑）。
2. Cancel lifecycle 安全性（§6 + §6A：进程树边界、ownership verification §6A.8、Core recovery finalizer §6A.12、race 规则、重复点击状态机）。
3. process ownership（§6.4/§7：runner 子进程归属 Bridge；孤儿 runner 场景 §6.9；Launcher 是唯一进程控制者）。
4. stale / duplicate state（§6.9 场景 3、§13.2：cancel.request 残留、task.json 冗余字段一致性、TASK_ALREADY_EXISTS 不删除）。
5. state source consistency（§13：task.json 单一权威 + cancel.request 文件镜像；写入者归属 §14.4）。
6. scope creep（§2.2/§17：明确排除项清单；防漂移边界）。
7. implementation sequencing（§15：A→B→C→D→E→F，E 风险最高需专项 audit）。

#### FIX-001 专项审查清单（Codex）

重点只审：terminal state consistency（§6A.2/§6A.4）、ownership verification（§6A.6–§6A.8）、force kill safety（§6A.8/§6A.10）、race conditions（§6A.2/§6A.13）、stale / restart recovery（§6A.9–§6A.12）、Core vs Launcher authority（§6A.1）。
目标：若两个 blocking findings（终态双写竞态、PID/token 协议未闭合）均已关闭 → **APPROVE**。

#### FIX-002 追加检查清单（WorkBuddy）

重点：原子性、恢复完整性、独立性。

1. read/check/write 是否真正位于同一跨进程锁（§6B.2）？
2. os.replace 是否仅承担完整文件替换，不再冒充 CAS（§6B.2/§6B.23）？
3. terminal winner 是否确定（§6B.18：同一 Core lock 下先 commit 者胜）？
4. reconciliation 是否可补 partial commit（§6B.9）？
5. canonical truth 是否唯一（§6B.5：仅 task.json terminal record）？
6. Bridge registry 是否真的独立于 control.json（§6B.14：Bridge root vs task workspace）？
7. restart 是否三方验证（§6B.13：registry + control + live process）？
8. PID recycle 是否仍被防护（§6B.13-5 / §6B.15）？
9. 不确定 ownership 是否拒绝 kill（§6B.13 / §6B.15）？
10. 无代码实现（§6B.25）？

#### FIX-002 专项审查清单（Codex）

重点只看三个原 blocking：

```text
A. cross-process terminal arbitration（§6B.1–§6B.5 / §6B.18）
B. partial artifact recovery（§6B.6–§6B.9 / §6B.21）
C. restart ownership trust chain（§6B.11–§6B.16 / §6B.13）
```

目标：若三个问题均闭合 → **APPROVE**。

---

*文档结束。设计范围：仅设计规格与实施拆分；实现与否、何时实现、是否纳入 v0.4 由 Planner 决策。*
