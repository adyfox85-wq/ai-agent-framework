# AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001 — Implementation Report

> Task: Eliminate transient Windows subprocess console flashes（temporary UX/runtime maintenance branch）
> Executor: Hermes（AAF Executor stage）2026-08-30
> Status: **IMPLEMENTED** — 正式收口判定留待 WorkBuddy 独立验证 + Codex 审查（本任务不自行宣布 APPROVE）

## 1. 结论（先给结论）

1. ✅ 确认的 console-flash 来源全部修复：`context_packet.py`（6 处 git 调用）、`git_status.py::_git()`（全部 helper git 调用）、`model_observation.py::_run_readonly()`（Hermes / CodeBuddy / Codex 全部 CLI 观测调用）——统一复用既有 `no_console_kwargs()`（`CREATE_NO_WINDOW`），零新机制。
2. ✅ 子进程语义零变化：命令参数 / cwd / capture_output / text / encoding / errors / timeout / 返回值 / 异常处理全部原样保留（本次 diff = 13 行插入、0 删除，仅追加 `**no_console_kwargs(),`）。
3. ✅ 未大范围重构：未引入第二个 Windows 进程启动策略；未新建 shared helper（既有 `no_console_kwargs()` 即唯一策略入口）。
4. ✅ `bridge/status_window.py` explorer 调用已检查，**不改**：`explorer.exe` 是 GUI-subsystem 程序，启动它不会创建 console 窗口（与 cmd/python.exe 等 console-subsystem 程序不同），无同症状证据；按 Requirement 6 仅检查不修改。
5. ✅ 全仓库 helper subprocess 审计完成：adapters / cost_guard / workbuddy_retry / bridge launcher / bridge main 的既有调用点已全部带 no-console 配置；本次补齐的 8 个调用点是剩余全部缺口（详见 §5）。
6. ✅ 新增 10 项聚焦回归测试（`tests/test_no_console_helpers.py`）：Windows 侧验证真实收到 `CREATE_NO_WINDOW`（本机 win32 实跑）、参数与语义原样保留；非 Windows 侧 monkeypatch 验证零 Windows-only 参数（platform-safe 不破坏）。
7. ✅ 回归验证：定向 443 passed（adapters / bridge_handoff / model_observation / context_integrity / context_compaction / runner / status_window / aggregation rw022 全家）+ 全量 non-GUI 套件复跑（见 §7）。
8. ✅ Fresh-runner Run N+1 通过（见 §7）：framework 任务执行 / context packet / git status evidence / model observation artifact / 生命周期与 REPORT 全部成功，无回归。
9. ✅ 范围零泄漏：未 reopen A0、未改 Paid Guard、未实现下一个 A1 slice、未实现 A2 / routing、未改模型选择 / Cost Gate / Bridge UI、未清理 PRE_ALLOWED_UNTRACKED。
10. ✅ 文档：本观察以**原始证据级别**（confirmed Windows subprocess console-visibility omission；cosmetic/UX only，非功能正确性失败）登记 backlog **RW-031**（CLOSED）+ PROJECT_STATE v0.5 块 + 本 REPORT。
11. 返回点：**A1 Registry + Risk**（本 maintenance branch 关闭后直接回到 v0.5 A1 主线，不推进下一个 A1 slice）。

## 2. 实现文件（最小集合）

| 文件 | 变更 | 说明 |
|---|---|---|
| `ai_agent_framework/context_packet.py` | 修改（+7） | `git_head` / `git_changed_files` / `_porcelain_all` / `remote_sync_state` 共 6 处 `subprocess.run` git 调用追加 `**no_console_kwargs(),` + import |
| `ai_agent_framework/git_status.py` | 修改（+3） | `_git()`（git rev-parse / branch / status / rev-list 等全部 helper git 调用的单一入口）追加 `**no_console_kwargs(),` + import |
| `ai_agent_framework/model_observation.py` | 修改（+3） | `_run_readonly()`（`--version` / `--help` / `config get model` / `config get auxiliary` / `exec --help` 全部 CLI 观测调用唯一入口）追加 `**no_console_kwargs(),` + import |
| `tests/test_no_console_helpers.py` | 新增 | 10 项聚焦回归（见 §6） |
| `tests/fresh_runner_console_flash_validation.py` | 新增 | Run N+1 驱动（见 §7；A0 fresh_runner_wrapper.py 同款 fresh-process 模式，真实 git workspace） |
| `docs/internal/AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001-REPORT.md` | 新增 | 本文件 |
| `docs/internal/AAF_MASTER_BACKLOG.md` | 修改 | 新增 **RW-031**（CLOSED）+ 摘要表行 + header Last Updated |
| `docs/internal/PROJECT_STATE.md` | 修改 | §0 v0.5 块登记 maintenance branch 收口 + Last Updated |

未改动：`ai_agent_framework/subprocess_utils.py`（既有策略零修改）、adapters / cost_guard / workbuddy_retry / bridge 全部（已带 no-console 配置，见 §5）、runner / router / lifecycle / report / parser / model_registry / risk_contract 零修改。

## 3. 根因与修复

### 3.1 根因（Hermes 只读诊断确认）

AAF 正常执行期间可出现 1–5 次短暂可见 Windows console 窗口。Bridge / runner / agent 主启动路径（adapters.run_agent / cost_guard / workbuddy_retry / bridge.launcher / bridge.main restart）已用 `no_console_kwargs()` / `CREATE_NO_WINDOW`；但若干 **helper 只读 subprocess.run 调用**未带该配置——这些调用从 GUI 宿主（pythonw / Tray Bridge）进程发起 console-subsystem 可执行文件（git.exe / hermes.exe / codebuddy.exe / codex.exe）时，Windows 会为子进程新建可见黑色 console 窗口。

诊断同时确认（基线事实，本次不重开）：
- 无 rogue AAF scheduled task、无 AAF Startup 条目；
- bridge.main 进程数 = shim + real process，非重复 Bridge 实例；
- 问题纯 cosmetic/UX；无功能 / lifecycle-authority 失败。

### 3.2 修复方式（复用既有策略，Requirement 1/3）

每个缺失调用点追加 `**no_console_kwargs(),`——`subprocess_utils.no_console_kwargs()` 在 Windows 返回 `{'creationflags': subprocess.CREATE_NO_WINDOW}`，非 Windows 返回 `{}`（显式 platform-safe，模块级 `_IS_WINDOWS` 导入期固化）。不新建第二个策略；不做 shared-helper 重构（Requirement 5：最小改动，每个调用点单行追加）。

## 4. 语义保持核对（Requirement 4）

| 语义维度 | 核对结果 |
|---|---|
| 命令参数 | 原样（tests 断言每个调用点的 args 与修复前完全一致，含 git 命令与 CLI 观测命令） |
| cwd | 原样（git_status: `workspace`；context_packet: `str(workspace)` / `ws`） |
| environment | 无 env 参数（原调用即无；未新增） |
| stdout/stderr capture | `capture_output=True` 原样 |
| text/encoding | `text=True` / `encoding="utf-8"` / `errors="replace"` 原样 |
| timeout | git_status 10.0 / context_packet 15 / model_observation 20 原样 |
| return-code 处理 | 原样（git_status `rc != 0 → ''`；context_packet 各 rc 分支；model_observation 返回 `(rc, out, err)`） |
| 异常行为 | 原样（git_status 捕获 `(OSError, SubprocessError) → ''`；context_packet `except Exception`；model_observation `except Exception → None`） |
| Git 解释 / model observation 解析 | 零改动（解析代码未触碰；`test_discover_hermes_end_to_end_parsing_unchanged` 以真实 `_run_readonly` 路径 + mock CLI 输出验证解析不变） |

## 5. 全仓库 helper subprocess 审计（Requirement 8）

对 `ai_agent_framework/` 与 `bridge/` 全部 `subprocess.run` / `Popen` / `os.system` / `os.startfile` 调用点逐一定点核对：

| 调用点 | no-console 配置 | 状态 |
|---|---|---|
| `adapters.py:531` run_agent | `**no_console_kwargs()`（L541） | ✅ 已有 |
| `cost_guard.py:228` | `**no_console_kwargs()`（L235） | ✅ 已有 |
| `workbuddy_retry.py:411` / `654` | `**no_console_kwargs()`（L415/661） | ✅ 已有 |
| `bridge/launcher.py:216` / `335` / `756` / `768` | `**no_console_kwargs()`（L224/343/763/775） | ✅ 已有 |
| `bridge/main.py:851` restart Popen | inline `creationflags=CREATE_NO_WINDOW`（getattr 默认 0x08000000） | ✅ 已有 |
| `bridge/status_window.py:818` explorer | — | ✅ 不改（见下） |
| `context_packet.py:189/211/643/680/693/702` | **本次补齐** | ✅ FIXED |
| `git_status.py:24` `_git()` | **本次补齐** | ✅ FIXED |
| `model_observation.py:245` `_run_readonly()` | **本次补齐** | ✅ FIXED |
| `bridge/main.py:1138` / `status_window.py:814` `os.startfile` | — | ✅ 不适用（shell 关联打开，无 console 创建路径） |
| `ai_agent_framework/runner.py` / `run.py` | 无 subprocess 调用 | ✅ 不适用 |

`status_window.py` explorer 决定（Requirement 6）：`subprocess.Popen(["explorer", str(path)])` —— `explorer.exe` 是 **GUI-subsystem** 可执行文件；Windows 仅为 console-subsystem 子进程分配新 console。无证据表明该调用可产生瞬时 console 窗口，且 `CREATE_NO_WINDOW` 对 GUI 程序无意义 → **不修改**（不为一致性而改）。

## 6. 测试证据

新增 `tests/test_no_console_helpers.py`（10 项，全部本机 win32 实跑）：

- Windows 侧（`skipif os.name != 'nt'`，与 test_adapters.py 同款惯例）：
  - `git_status._git()` 收到 `CREATE_NO_WINDOW`，args/cwd/capture/timeout 原样；
  - `model_observation._run_readonly()` 收到 `CREATE_NO_WINDOW`，返回 `(rc, out, err)` 不变；
  - context_packet 4 函数 7 次 git 调用**全部**收到 `CREATE_NO_WINDOW`，命令与调用次数逐项断言。
- 非 Windows 侧（monkeypatch `_IS_WINDOWS=False`，两平台可跑）：三个模块全部调用零 `creationflags`（platform-safe 未破坏）。
- 行为保持：
  - `_git` 非零退出 → `''`、异常 → `''`（不变）；
  - `_run_readonly` 异常 → `None`（non-blocking 不变）；
  - `discover_hermes` 经**真实 `_run_readonly`** + mock CLI 输出 → model/provider/status 解析与修复前一致（输出解析不变）；
  - `git_changed_files` 预允许 untracked 过滤、`tracked_tree_status` CLEAN、`remote_sync_state` SYNCED / 非 git NOT_APPLICABLE 语义不变。

运行结果：
- 新增聚焦：`tests/test_no_console_helpers.py` **10 passed**
- 定向回归（443 项）：test_adapters / test_bridge_handoff（真实 git 仓库）/ test_model_observation / test_context_integrity / test_context_compaction / test_runner / test_status_window / test_aggregation_rw022(+fix001..fix006) **443 passed / 0 failed**
- 全量 non-GUI 复跑：**1489 passed / 1 skipped / 0 failed**（全 1490 项 collected；gui_e2e 9 项结构性排除；`tests/test_rw012_listener_recovery.py` 等全部 66 个执行测试文件逐文件 fresh process 覆盖；单进程连跑触发既有 **RW-029** 0x80000003 环境 flake——按仓库惯例分块隔离复跑，每块全绿，见 §7 证据）

## 7. Fresh-runner Run N+1（Requirement 9/10）

上下文 / evidence / model-observation 行为属于运行中 framework 的 self-observation 路径，按 Requirement 9 做 **一次** fresh-runner N+1 验证（不叠加冗余 fresh-runner 循环）。

驱动：`tests/fresh_runner_console_flash_validation.py`（新增；A0 `fresh_runner_wrapper.py` 同款 fresh-process 模式）。Run N+1 用全新 python 进程经 wrapper 启动真实 runner 执行一个 Route=hermes→workbuddy 的 TASK；workspace 为**真实 git 仓库**（git init + commit），fake hermes/codebuddy `.bat` 是真实 child process（marker 为调用证据）。

结果（1/1 PASS，证据：`.aaf/AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001/fresh-runner-validation/N1/scenario_record.json`）：

| Requirement 10 验证点 | 结果 |
|---|---|
| 1. framework 任务执行成功 | ✅ runner exit 0；run.json status=SUCCESS；task.json / route.json / boundary.json / state.lock / cost_guard.json 全部生成 |
| 2. context packet 生成成功 | ✅ hermes_result.json / workbuddy_result.json 存在；context_manifest.json 存在且 `manifest.head` == 真实 git HEAD（`4d055957…`），stages = {hermes, workbuddy} |
| 3. Git status evidence 成功 | ✅ driver 侧 `git_snapshot`（修复后的 `git_status._git()`）在真实 git 仓库返回 is_git_repo=true、local_head 与 HEAD 一致、working_tree=clean；runner 侧 git_head / git_changed_files / remote_sync_state 全部经修复路径成功 |
| 4. model observation artifact 成功 | ✅ model_observation.json 存在；hermes 观测 discovery_status=**OK**，model=deepseek-v4-flash / provider=deepseek（**真实 hermes CLI** 经修复后的 `_run_readonly` probe——`--version` / `config get model` / `config get auxiliary` / `--help` 全部成功；version=Hermes Agent v0.20.5；auxiliary 5 槽位含 LOCAL_FREE 分类）。注：wrapper 只 patch adapters/cost_guard 的 discovery PATH，model_observation 走 winreg 真实 PATH → 探测真实 CLI 正是修复后 self-observation 路径的真实行为 |
| 5. 生命周期 / REPORT 无回归 | ✅ REPORT.md 存在且含 Model Observation 段；hermes marker 存在（Hermes stage 真实 child 达 invocation 边界） |

可见窗口的消失不依赖人工截图证明：代码级 Windows creation-flag 证据（§6 Windows 侧测试断言，win32 实跑）+ 本成功 fresh run 即满足框架验收（Requirement 10）。

## 8. 范围边界（Requirement 11）

- 未 reopen A0；未修改 Paid Guard（cost_guard 零改动）；未实现下一个 A1 slice / A2 / routing；未改模型选择 / Cost Gate 行为 / Bridge UI；未 clean PRE_ALLOWED_UNTRACKED 文件。
- 未 push：本任务提交保留本地（Requirement 13），review 通过后由同步任务推送。
- 无 force push、无 history rewrite；基线 = 当前 synced main（`ea0d0ad`）。

## 9. Git 状态（Requirement 13）

- 基线：`ea0d0ad`（origin/main，ahead/behind = 0/0，tracked working tree CLEAN——3 个 PRE_ALLOWED_UNTRACKED untracked 常驻项：`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs` 未删除未 clean）。
- 本任务提交后：本地 main 前移 1 commit（本实现 commit），**未 push**；ahead/behind 以提交后实际 `git status` 输出为准（见提交后状态）。

## 10. 返回点

本 maintenance branch 关闭后直接返回 **v0.5 -> A1 Registry + Risk**（A1 = STARTED，foundation slice 已交付，remaining slices 未实现；本任务不推进任何 A1 内容）。
