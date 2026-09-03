# AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001-FIX-001 执行报告

## Current Status
SUCCESS

## Objective
收口 AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001（commit 4596cede）的唯一 Codex
blocker：EXITED→last_run crash window。序列「runner 产出 canonical terminal →
mark_exited() 持久化 registry=EXITED → Bridge 在 _finish_run() 写 last_run.json
前崩溃 → restart」发生时，旧 recover_launches 只扫 ACTIVE registry（EXITED
条目被跳过），terminal task 身份/状态永远无法重建。本 FIX 使重启后能从可验证的
canonical terminal artifacts（task.json / control.json / REPORT.md）恢复正确
terminal task identity / FINISHED presentation。

## 崩溃窗口（Codex blocker 精确语义）
收尾共享路径（wait thread / recovered watcher）的顺序是：
1. `reg_mod.mark_exited(launch_id, exit_result=result)` —— registry 持久化 EXITED
2. `_finish_run(...)` → `_persist_last()` —— last_run.json 落盘
两步之间进程死亡 → registry 已是 EXITED、last_run 仍是更旧/缺失内容；restart 后
旧 `recover_launches()`（只遍历 `ACTIVE_STATES`）完全跳过该 launch。

## 修改（实际行为 → 代码证据）

### bridge/launcher.py
- `recover_launches()` 尾部由 `restored … elif mirror_last …` 增加第三分支：
  无任何 ACTIVE 处置（无 restored、无 mirror_last）时调用新方法
  `_recover_exited_crash_window(root)`。
  - recovered RUNNING 永远优先（requirement 6）：有 restored 时不进 EXITED pass；
    有 mirror_last（ACTIVE 收敛条目，必然比既有 EXITED 更新——单实例顺序执行）
    时也不进——stale 历史绝不覆盖更新正式状态（requirement 7）。
- 新方法 `_recover_exited_crash_window()`：
  - 候选选择：只取 **newest EXITED** launch（created_at → exited_at → launch_id
    权威降序）；若 last_run（launcher.last / load_last）已呈现该 launch
    （launch_id 相同 = 干净收尾已落盘）→ no-op。首个未呈现的 EXITED =
    crash-window 受害者；更旧 EXITED 一律不回溯（requirement 7：不盲目选任意/
    旧 registry 条目；多 EXITED 只选最新 validated 状态）。
  - 三方关系验证（requirement 3「validate launch/task relationship」+ 4）：
    registry.launch_id == control.launch_id、registry.task_id ==
    control.task_id == task.json canonical.task_id。canonical proof 只来自
    既有任务 authority（`_read_canonical_terminal` → task.json 终态 +
    REPORT.md 存在性经 `result_from_canonical` 映射）。
  - proof 有效 → 按 canonical 同款映射（SUCCESS/WAITING → FINISHED /
    REPORT_NOT_FOUND；FAILED → FAILED；CANCELLED → CANCELLED）重建
    launcher.last + `_persist_last()`（terminal FINISHED presentation/history
    重建；task_path=""、exit_code=None、terminal_generation 取自 canonical）；
    registry evidence 保留不动；disposition = `EXITED_TERMINAL_RECOVERED`。
  - 无 proof / 关系不可验证（requirement 5）→ last_run = RECOVERY_NEEDED（显式
    不确定，绝不从 registry EXITED 单独推断 FINISHED）；仅当 registry
    exit_result 目前误导性地声称完成/终态（FINISHED/FAILED/REPORT_NOT_FOUND/
    CANCELLED/TERMINAL/FORCE_TERMINATED）时收敛为 RECOVERY_NEEDED（原已显式
    不确定如 FAILED_TO_START/RECOVERY_NEEDED 保留 evidence；force_*/exited_at
    等一律不动）；disposition = `EXITED_RECOVERY_NEEDED`。
  - 绝不 rerun / 绝不创建 runner / 绝不启动 watcher / 绝不改 canonical /
    绝不把 EXITED 恢复成 RUNNING（state 保持 IDLE；并发保护不占用）。
- 新增处置常量 `_DISPOSITION_EXITED_TERMINAL_RECOVERED` /
  `_DISPOSITION_EXITED_RECOVERY_NEEDED`（诊断 + 可测）。

### 测试
- 新增 `tests/test_bridge_state_recovery_exited_window.py`（10 项聚焦回归）：
  1. terminal SUCCESS → EXITED → 模拟崩溃 → restart → 正确 terminal task 恢复
     （FINISHED / task_id / launch_id / REPORT / generation；view SUCCESS/已完成）
  2. terminal FAILED 同崩溃点 → FAILED 恢复（canonical 跟随，非伪造）
  3. terminal CANCELLED 同崩溃点 → CANCELLED 恢复（cancellation 语义保留）
  4. EXITED 无 canonical proof（registry 误导性 exit_result=FINISHED）→ 绝不
     伪造 FINISHED → RECOVERY_NEEDED + registry 收敛 + 幂等（二次 restart no-op）
  5. canonical 存在但 launch/task 关系不可验证（control launch_id 不一致）→
     fail closed RECOVERY_NEEDED
  6. 旧 EXITED（SUCCESS proof）不覆盖更新的 live RUNNING 任务（restored 优先；
     last_run/F-I-RUN 不被旧 EXITED 覆盖；无第二 runner）
  7. 多 EXITED 只选最新 validated 终态（FAILED 胜出，旧 SUCCESS 保留不动）
  8. 多 EXITED 最新无 proof → RECOVERY_NEEDED（不回退呈现旧 FINISHED）
  9. 干净收尾稳态（last_run 已呈现 newest EXITED）→ recover no-op（last_run
     字节级不变）+ F-I-RUN 污染 last_run 被真实 victim 重建覆盖（无泄漏）
  10. 真实子进程全链路：bounded 任务自然完成 → EXITED → 模拟崩溃 → restart
      从权威 artifacts 恢复同一 identity → 无 rerun / 无重复 runner → 新任务
      可再执行（无回归）
- `tests/fresh_runner_state_recovery_wrapper.py` / `fresh_runner_state_recovery_
  validation.py`：新增 stage `crashwin`（N4）+ `crashreopen`（N5，各自独立进程、
  独立隔离根 ev/cw-bridge）——真实 bounded 任务自然完成到 registry EXITED +
  canonical SUCCESS → last_run 回退为更早 launch（SRV-FRESH-OLD）旧呈现（=
  crash-window 可观察磁盘状态）→ 新进程 recover_launches → 从权威 artifacts
  重建 victim terminal（task_id/launch_id/FINISHED/REPORT 一致）、无 rerun
  （canonical generation 不变 / 无 ACTIVE / launch 数不变）、旧 last_run 不覆盖
  恢复结果、再真实启动新任务（执行/报告无回归）。

## 验证证据
- `python -m pytest tests/test_bridge_state_recovery_exited_window.py -q` →
  10 passed
- `python -m pytest tests/test_bridge_state_recovery.py tests/test_bridge_launcher.py
  tests/test_bridge_handoff.py -q` → 34 passed（既有恢复/launcher/handoff 零回归）
- `python tests/fresh_runner_state_recovery_validation.py` → fresh-runner
  validation PASS（stage launch/restart/reopen/crashwin/crashreopen 5/5；证据
  `.aaf/AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001/fresh-runner-validation/
  stage-*.json`；真实 ~/.aaf-bridge last_run/launches 前后零变化、零测试身份）
- 全量 canonical（分块，每批独立进程规避本机整包单进程 Windows 原生异常）：
  `python .aaf/_chunked_canonical.py` → ALL GREEN（日志
  `.aaf/_chunked_canonical_fix001.log`）

## 未改动（保留语义，requirement 8/9/14）
live RUNNING restart recovery / 同 task_id / launch_id / runner identity /
duplicate Ctrl+Alt+A 保护 / 无第二 formal runner / 无 view overwrite /
RECOVERY_NEEDED 孤儿处置 / unified Bridge state root / AAF_BRIDGE_DIR 隔离 /
cancellation / force terminate / supersede / routing / Paid Guard / task
lifecycle 语义全部未动（改动仅限 recover_launches 尾部第三分支 + 新方法 +
测试）。AAF_MASTER_BACKLOG.md / PROJECT_STATE.md 未含本 RUNTIME 任务登记
（0 引用），不属本任务跟踪范围，未触碰；PRE_ALLOWED_UNTRACKED 保留；无 push。

## Unresolved Issues
None（已知边界——与 FIX 前行为一致、无回归：EXITED force-evidence 残留而
canonical 未提交的极端场景按 requirement 5 呈现 RECOVERY_NEEDED 显式不确定，
不自动重调 finalizer——force 语义保持，FIX 前同样不处理，本 FIX 使其可观察）。

## Remote Sync
- Commit Sync: SYNCED（单 commit；parent 4596cede；no amend；no push）
