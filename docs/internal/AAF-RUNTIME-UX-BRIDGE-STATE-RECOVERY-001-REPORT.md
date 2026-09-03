# AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001 执行报告

## Current Status
SUCCESS

## Objective
修复 Bridge 重启后的任务身份与状态恢复：状态窗口重新绑定真实 running/finished
正式任务；重复 Ctrl+Alt+A 不覆盖正式任务视图；消除测试 last_run.json 对真实
用户 Bridge state 的污染。

## 修改（实际行为 → 代码证据）

### 1. last_run / registry 同一 Bridge state root（AAF_BRIDGE_DIR 统一）
- `bridge/config.py`：新增 `state_root()`——`AAF_BRIDGE_DIR` 覆盖，默认
  `~/.aaf-bridge`。launch registry 与 last_run.json 同根解析。
- `bridge/launch_registry.py`：`registry_root()` 委托 `config.state_root()`
  （语义不变：env 优先）。
- `bridge/launcher.py`：`_state_root` 在 **FrameworkLauncher 构造时绑定一次**
  （与 `registry_dir` 同一契约），`_last_run_path` 基于绑定根——收尾
  wait thread / recovered watcher 是 daemon 线程，可能晚于其创建者的 env
  作用域结束（测试 teardown 恢复 AAF_BRIDGE_DIR），构造时捕获保证
  `_persist_last` 永远落在同一隔离根。实证：构造时绑定前，force-e2e 的
  daemon wait thread 曾在测试结束后把 `T-FORCE-E2E` 写进真实
  `~/.aaf-bridge/last_run.json`（21:25:48）；绑定后全量回归零写入。
- `bridge/status_window.py::_load_last_run_file`、`bridge/handoff.py::
  last_run_path` 全部改为 `config.state_root() / "last_run.json"`——写与读
  同一 root；测试 / E2E 经 AAF_BRIDGE_DIR 指向临时根，测试身份（F-I-RUN 等）
  **不再可能**写进真实用户 Bridge state（root cause：旧 `_last_run_path`
  硬编码 `CONFIG_DIR`）。
- `tests/conftest.py`：autouse fixture 把 AAF_BRIDGE_DIR 指向每个测试独立临时根
  （不预建目录，严格空目录断言不受影响）；handoff/launcher 三个 patch
  CONFIG_DIR 的测试改为显式 env 隔离。

### 2. recover_launches：恢复 RUNNING 状态 + current task identity（req 1/2/5/9）
`bridge/launcher.py::recover_launches` 对每个 ACTIVE launch 三方验证后分类处置：
- REAUTHENTICATED（live 正式 runner）→ **state=RUNNING + current=RunInfo**
  （task_id / launch_id / output_dir 取自 registry/control 持久权威；newest
  胜出），并启动 recovered watcher 线程（`_watch_recovered_launch`）。状态窗口
  经 `resolve_current_task` 的 RUNNING→current 路径直接绑定正式任务——不再落到
  stale active 文件或 last_run 兜底。
- canonical terminal 已存在（旧实例崩溃遗留的 ACTIVE 镜像）→ registry EXITED
  （`exit_result="TERMINAL"`；**不动 canonical**），无 live 任务时 newest
  完成态镜像进 last_run（terminal-history 视角，req 8）。
- STALE + recorded runner 失效（进程消失 / PID recycle）+ 任务非终态：
  * 本 launch 自己的 force evidence 存在 → 既有 Core finalizer 路径（不变）；
  * 无 evidence → registry EXITED（`exit_result="RECOVERY_NEEDED"`）+ last_run
    显式 mirror——**绝不伪造 RUNNING / FAILED**（req 5/9；新增
    `RESULT_RECOVERY_NEEDED`）。
- UNCERTAIN（control 缺失/损坏等）→ registry 保持 ACTIVE 不动（fail closed，
  进程可能仍存活）；PREPARED 无 runner_pid → 不自动处置（可能正在启动）。
- last_run 镜像规则（req 8）：恢复出 live 正式任务时**不**改写 last_run；
  只有无 live launch 恢复时才刷 newest 完成/孤儿镜像。
- 处置记录：`launcher.recovered_disposition[lid]`（可测诊断）。

### 3. recovered watcher（监视收尾；req 2/13 的「任务继续到终态」）
`_watch_recovered_launch / _watch_recovered_loop / _release_recovered_state`：
轮询 canonical terminal 与 recorded runner 进程；canonical 出现 → 按
`_wait_and_finish` 同款规则收尾（派生不一致则先调 Core reconcile CLI）；
进程失效且无 terminal proof → 先吸收 force 恢复窗口（control.
force_terminate_requested → 轮询 canonical），否则显式 RECOVERY_NEEDED；
registry 被其他 authority 收敛（wait thread / force 路径 / supersede）→
`_release_recovered_state` 释放本实例 state/current（并发保护不僵尸占用）+
尽力跟随 terminal 镜像。收尾共享逻辑抽为 `_finish_run` /
`result_from_canonical`（wait thread 与 watcher 同款，行为不变）。

### 4. 状态窗口
- `resolve_current_task` 优先级文档化：① RUNNING current（含 recover 恢复的
  正式任务）→ ② last_run（launcher.last / load_last / last_run.json，只作
  terminal-history/fallback，req 8）→ ③ 空态。逻辑未变（优先级 1 天然压制
  last_run 覆盖）。
- `LAUNCHER_RESULT_LABELS` 增加 `RECOVERY_NEEDED → 「状态无法确认，需人工核查」`
  ——last_result 兜底文案不再把不确定态渲染成「执行失败」（req 5）。

### 5. 未改动（保留语义，req 10）
cancellation / force-terminate / supersede / duplicate protection /
task lifecycle / Paid Guard / routing / artifact 语义全部未动；duplicate
module、intake 决策、main.py 接线零改动（恢复后 launcher.state=RUNNING 使
既有 AlreadyRunningError / duplicate reject 路径自然生效）。

## 测试
- 新增 `tests/test_bridge_state_recovery.py`（9 项，req 11 全覆盖）：
  live 中 restart 恢复同一 RUNNING 任务（task_id/launch_id/registry↔control
  runner 身份一致）；旧实例崩溃 + terminal → EXITED TERMINAL + terminal 状态
  恢复；dead runner + 非终态 → RECOVERY_NEEDED（不 FAILED）；stale registry
  混合（terminal / orphan / PREPARED 保守）；duplicate hotkey while running →
  无第二 runner / 无 view overwrite；recovered active 优先于 last_run
  （F-I-RUN 兜底不覆盖）；测试 AAF_BRIDGE_DIR 隔离 + F-I-RUN 不泄漏真实
  state；watcher 全链路自然完成 → terminal 恢复 → 新任务可再执行。
- 新增 fixture `tests/fixtures/dummy_recover_runner.py`（sleep 后提交 SUCCESS
  canonical 全套；确定性 bounded runner）。
- 既有 Bridge/Phase E/F/UX 相关测试全部通过（launcher / handoff / status_window /
  progress / duplicate / intake / phase_e ownership/core/force/cancel /
  phase_f e2e / UI headless 等 440+）。
- 全量回归：`python -m pytest tests/`（见下方）。
- fresh-runner closure（req 13）：`tests/fresh_runner_state_recovery_wrapper.py`
  + `fresh_runner_state_recovery_validation.py`，三个阶段各在**全新进程**扮演
  Bridge 实例：launch（bounded 真实任务，实例退出）→ restart（新进程恢复同一
  RUNNING 身份、duplicate 拒绝无第二 runner、自然完成 watcher 收尾）→ reopen
  （新进程 terminal 视图恢复 + 第二任务执行/报告无回归）+ 真实 state 零泄漏断言。

## 验证证据
- `python -m pytest tests/test_bridge_state_recovery.py -q` → 9 passed
- `python -m pytest tests/test_phase_e_force_e2e.py tests/test_phase_e_cancel_ui_e2e.py -q` → 16 passed
- `python -m pytest tests/test_phase_f_e2e.py -q` → 9 passed
- `python -m pytest tests/test_phase_e_ownership.py ...（12 个相关文件）` → 249 passed
- `python tests/fresh_runner_state_recovery_validation.py` → fresh-runner validation PASS
  （stage launch/restart/reopen 证据：
  `.aaf/AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001/fresh-runner-validation/stage-*.json`；
  真实 ~/.aaf-bridge last_run/launches 前后零变化、零测试身份）
- 全量 canonical（分块，每批独立进程）：`python .aaf/_chunked_canonical.py`
  → ALL GREEN（5 批：476 + 393 + 448 + 306 + 516 passed，1 skipped，
  9 gui_e2e deselected；日志 `.aaf/_chunked_canonical2.log`）
- 真实用户 state 零污染验证：分块全量回归前后 `~/.aaf-bridge/last_run.json`
  内容/mtime 不变（恢复为任务开始时快照），launches/ 文件数不变。

## 环境备注（非本任务缺陷；基线复现）
本机整包单进程 `pytest tests/` 在 ~50% 处触发 Windows 原生异常
（`0x80000003`，GC 期间 json 编码线程崩溃）：在本任务改动被 git stash、
运行**未改动基线**（HEAD 927d965 + 新测试文件移出）时同样复现（4 次崩溃中
含基线 1 次）——判定为环境/解释器级既有问题，与本任务无关。canonical
覆盖改以分块独立进程运行验证（见上，全绿）。

## 重要安全说明（验证过程中发现并确认）
fresh-runner wrapper 首版误用 FrameworkLauncher 默认 run_py（真实仓库 run.py）
在隔离证据根内真实执行了一次 run.py：A5 Paid Guard 按预期 **fail-closed**
（REPORT 记录 `COST_APPROVAL_REQUIRED — Hermes stage NOT started`），零 Agent
调用、零付费、产物全部落在隔离证据根内；已修复为显式注入 dummy fixture
runner（`_make_launcher` 注释警示），后续阶段证据全绿。真实用户 state 全程
零写入（driver 前后快照断言）。

## Unresolved Issues
None.

## Remote Sync
- Commit Sync: SYNCED（单 commit；no amend；no push）
