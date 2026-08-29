# PROJECT_STATE.md

> Project: AI Agent Framework\
> Current Version: **v0.4（IN PROGRESS — Phase A/B/C/D COMPLETE；Phase E COMPLETE（E-Core / Soft Cancel COMPLETE — 005-A + FIX-001/002/003；E-Ownership / Force Cancel 已交付 — 005-B + 005-B-FIX-001（canonical force authority + successful termination proof，Codex 两个 blocker 已闭合）；005-C Status Window Cancel UX + Real Windows E2E Closure 已交付——实现 + 测试 + 真实 Windows 正负 E2E 全量通过，Phase E 正式标记 COMPLETE；005-C-FIX-001（Cancel Timestamp Timezone Compatibility Fix）已交付——canonical UTC/aware elapsed contract 统一 cancel elapsed 计算，合法 offset-aware（+08:00 / +00:00 / Z）与 legacy naive 均不再因 naive/aware 混算而破坏 Cancel UI / force eligibility，malformed fail closed，Codex 原 timezone blocker 已闭合；route 阶段 WorkBuddy / Codex 独立复核按项目惯例由 route 执行并记录于任务 REPORT，若发现 blocking 则按惯例开 FIX）；Phase F IMPLEMENTATION DELIVERED（AAF-v0.4-TASK-006：Project Switching + Duplicate Task UX 实现 + 72 项新测试（63 单元 + 9 真实 Windows E2E A–I）+ 760 passed；RW-003 / RW-016 / RW-006 按真实交付证据收口 SOLVED；正式 COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 审查后由 Planner 确认，本任务不自行宣布 Phase F COMPLETE）；Phase F FIX-001（Atomic Config Persistence + Real UX Closure）已交付——config.save_config 统一 atomic contract（同目录 tmp + flush/fsync + os.replace，失败清理 tmp 且旧 config 原样保留，无 write_text 旁路）；真实 Bridge UI 交互 harness（真实 Tk 弹窗 + 真实按钮 invoke + 真实剪贴板）覆盖 Known switch 确认/拒绝/Unknown fail-safe/Invalid fail closed/Duplicate running 卡片+无第二 runner/Duplicate terminal 卡片+不覆盖/restart 恢复；顺带修复 duplicate 卡片 [打开 REPORT] 死按钮（Tk 按钮 invoke 不带参数 → 闭包捕获 report_path）；780 passed（760 + 20 新增，零下降）；WorkBuddy 独立验证 + Codex 复审由 route 执行（本任务不自行宣布 COMPLETE））；Model Observability / Discovery Foundation 已交付（AAF-v0.4-TASK-010：只读模型观测 + 发现事实层——model_observation.json 单一 machine authority、每 stage stage_timing、REPORT 紧凑 Model Observation 摘要、30 项定向测试；Automatic Model Routing 未实现，仅登记未来 policy（backlog §5.5 CAP-003））；当前唯一 Next Step = Planner v0.4 收口评审（WorkBuddy 独立验证 + Codex 最终审查 WorkBuddy Stage Reliability：confirmed-dead-before-retry / absolute stage deadline / 无并发/孤儿 CodeBuddy child；及 Model Observability closure）→ Intake / Bridge Reliability planning（不自动进入最终封装））**\
> Last Updated: 2026-08-29（AAF-v0.4-TASK-011-FIX-001 — WorkBuddy Confirmed Cleanup and Hard Stage Budget Fix 已交付：closed Codex 确认的两个 reliability blocker——① confirmed-dead-before-retry（timeout 清理返回结构化 CleanupResult，final liveness check 必须观察到终止；终止未确认 → WorkBuddyCleanupError fail closed 绝不 retry、child PID 保持注册，Registry Gate 防任何并发/孤儿 CodeBuddy；终止确认但 reap 失败按真实资源安全语义如实分类）；② single absolute stage deadline（stage_deadline = stage_start + overall_stage_budget 唯一墙钟上限；attempt / backoff / taskkill / grace / reap 全部由同一 deadline 裁剪；cleanup_reserve 默认 60s 保证 attempt timeout ≤ remaining − reserve）；telemetry 扩展 cleanup/deadline evidence；新增 12 项定向测试；全量 non-GUI 1277 passed（1265 + 12 零下降）；WorkBuddy 独立验证 + Codex 审查 + Planner Model Observability closure 收口为 route 最后闸门）。此前更新：2026-08-29（AAF-v0.4-TASK-010-FIX-001 — Model Observation Evidence Accuracy and Test Isolation Fix：CodeBuddy installed version 改为 `codebuddy --version` 动态探测（2026-08-29 实测 2.141.0，与 WorkBuddy 独立 probe 一致；TASK-010 手写 2.137.1 为无证据值，已从 code/docs 清除；`--version` 失败 → version=UNKNOWN + discovery_status=FAILED 带原因，非阻塞）；observations 新增 version / version_source / version_evidence（model_observation.json 仍为单一 machine authority）；Codex 删除无证据的 model_options.* 推断（reasoning_effort capability = NOT_EXPOSED_BY_CURRENT_CLI，通用 -c 不构成具体 key 证据）；测试隔离（RW-026 = SOLVED）：pytest.ini gui_e2e marker + addopts 结构性排除真实窗口测试（test_phase_f_fix_001_ui.py 标记 gui_e2e），新增 tests/test_bridge_ui_headless.py 7 项 headless 等价覆盖（零真实窗口/零真实剪贴板/无人值守），热键冲突路径确认已隔离（RW-012：StubRoot + fake HotkeyListener + patched ui.show_error）；model observation 定向测试 30→37 全过；此前更新：2026-08-29（AAF-v0.4-TASK-010 — Model Observability and Discovery Foundation 已交付：只读模型观测 + 发现事实层（`ai_agent_framework/model_observation.py`；`model_observation.json` = model observation 单一 machine authority，schema_version=1，refreshable 动态元数据；runner 每 stage stage_timing + 只读 discovery，stage result 只携带 authority 引用，REPORT 只输出每 agent 一行紧凑 Model Observation 摘要；`AAF_MODEL_OBSERVATION=0` 整层关闭；discovery 全链路非阻塞（双保险），失败只记 UNKNOWN/FAILED 绝不影响执行；真实 CLI probe 证据：Hermes v0.20.5（主模型 deepseek-v4-flash / provider deepseek / effort medium；auxiliary 5 槽位全本地 Ollama qwen2.5vl:3b / qwen3:4b → 本地模型可发现；vision=model slot；ComfyUI=外部 capability/tool 不硬塞 model list）、CodeBuddy 2.141.0（2026-08-29 `codebuddy --version` 动态 probe，FIX-001 修正 TASK-010 手写 2.137.1 无证据值；当前模型 config 不暴露 → UNKNOWN；`--model`/`--effort` + CLI help 文档化模型 ID；积分/免费元数据 UNKNOWN / EXTERNAL_DYNAMIC_METADATA_REQUIRED）、codex-cli 0.150.0-alpha.12.2（config.toml 无 model key → 默认模型 server-side 不可枚举 limitation；`-m/--model` 存在；无专用 reasoning flag；catalog 不可枚举）；cost_class 如实（API provider → UNKNOWN 不硬编码 PAID；local base_url → LOCAL_FREE 带 evidence）；不实现 routing/cost gate/自动切换/付费实验（零决策层代码）；30 项定向测试 + tests/conftest.py hermetic discovery；backlog §5.5 CAP-001/002/003 登记（CAP-003 Future Model Routing = NOT IMPLEMENTED）；此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-005 — RW-012 shutdown/recovery 单一 lifecycle authority（TOCTOU 收口）：shutdown intent 发布（`shutdown()` / `_exit_aaf()` / `_restart_bridge()`）与 listener lifecycle transition 共用同一个 `_lifecycle_lock`——`_shutting_down=True` 在锁内先于 stop 发布（Popen 失败在同一 authority 下回滚并恢复热键）；`_run_lifecycle_transition()` 取得 authority 后在锁内重新验证 shutdown，关闭 Codex FIX-004 唯一 blocking finding「pre-lock check False → 等待锁 → shutdown 发布 → 取得锁后仍 rearm/创建 replacement」的精确 check-then-wait 竞态；`_apply_hotkey_locked`（唯一 listener creation authority）锁内以 shutdown 守卫拒绝 config reload / 外部触发在 shutdown 后的任何创建；`_clear_pending_ownership_locked` 的 rearm 只在非 shutdown 时发生（shutdown 期间 delayed-exit cleanup 只做 ownership bookkeeping、绝不 rearm）；无递归锁死（shutdown 阻塞等待 authority，transition 完成后接管）；新增 13 项定向回归 `tests/test_rw012_shutdown_atomicity_fix005.py`（精确 Codex TOCTOU 真实线程 + 确定性门闩 / reverse interleaving / delayed-exit during shutdown / config reload during shutdown / poll during shutdown / shutdown 发布顺序可观察 / _exit_aaf 确认-取消 / _restart_bridge 成功-失败回滚 / 唯一 authority 锁内守卫 / 并发无死锁 / 非 shutdown 正常路径无回归），TOCTOU 与 reverse 测试对未修复代码确定性 FAIL（stash 反证）；RW-012 定向 111 项 + 全量 non-GUI（排除真实 UI 文件 test_phase_f_fix_001_ui.py，任务禁止真实剪贴板/项目切换确认窗）passed；RW-008 无回归（parser 零改动）。此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-004 — RW-012 atomic recovery transition consolidation：delayed-exit recovery 收敛为单一锁内 lifecycle transition——`Bridge._run_lifecycle_transition()` 在同一个 `_lifecycle_lock` 临界区内完成 old pending 确认退出 → 锁内 identity 重验证 → clear old ownership → rearm 恰好一次 → eligibility 判定 → reserve attempt → exactly one replacement（`_apply_hotkey_locked`），关闭 FIX-003 遗留的「cleanup 释放锁 → 锁外 eligibility → 再获取锁创建」多段 ownership transition 与 exposed gap（listener=None/pending=None/rearmed 但未 reserved/owned 只在锁内瞬时存在，任何其他 trigger 锁外不可见、非阻塞获取失败即合并）；`_apply_hotkey` 拆为 public（获取锁）+ `_apply_hotkey_locked`（假定持锁，唯一 listener replace/start authority，config reload / health recovery / delayed cleanup / restart-failure 全部汇入）；无递归锁死（持锁内再触发 = coalesce）；rearm 仍只随真实 delayed-exit ownership release 发生（epoch 不因 None/DEGRADED/poll 自增）；新增 13 项定向测试（单一锁内 transition 无 gap / 精确 Codex interleaving 真实线程：第二 trigger 无独立 authority + stale cleanup 不清 replacement / exhaustion→delayed exit 恰一次 rearm 单 epoch / failed new epoch bounded / healthy 终态不无谓 restart / config reload 同 hotkey 不 restart / listener=None 不 rearm / 冲突可观察有界无 modal / shutdown 不复活 / readiness 回归 / stop-before-replace + fail safe），scratch 反证：旧设计同一交错产生 duplicate replacement（2 次创建），新设计 exactly one；RW-012 定向 98 项 + 全量 non-GUI 1182 passed；RW-008 无回归（parser 零改动）。此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-003 — RW-012 atomic delayed-exit recovery：`_poll_health` delayed-exit check-and-clear 收进 `_lifecycle_lock` 保护原子单元（`_delayed_exit_cleanup`，锁内 identity 重验证才清理，关闭 FIX-002 遗留 TOCTOU：lock 外 check → 锁内建新 → lock 外 clear 清掉 replacement 的合法交错）；recovery budget exhausted 后旧 listener 迟延退出 → `HotkeyRecovery.rearm()` 开启一次新的有界 recovery epoch（epoch+1，真实 lifecycle 状态变化才 rearm，失败仍受 max_failures/backoff 约束，无 per-poll 无限重置、无 tight loop）；identity-safe clear（pending/listener 双身份校验，stale cleanup 绝不清 replacement）；所有 ownership transition 统一锁内（_apply_hotkey / _delayed_exit_cleanup / _try_recover_hotkey 异常路径 / shutdown / restart）；shutdown 不 rearm 不复活；新增 15 项定向测试（含 Codex 精确 race 真实双线程复现 + scratch 反证旧实现确定性 FAIL），RW-012 定向 84 项 + 全量 non-GUI 1169 passed（1154 基线 + 15 新增，零下降）+ 真实 E2E 9 项全过；RW-008 无回归（18 passed，parser 零改动）。此前更新：2026-08-29（AAF-v0.4-TASK-009-FIX-002 — RW-012 listener ownership retention + readiness truth：关闭 FIX-001 遗留的最后两个同根 lifecycle blocker（Codex REQUEST_CHANGE）——① ownership retention：`_stop_listener` 只在 stop 确认退出后才清空 self.listener（stop 超时保留引用并记入 _pending_stop → DEGRADED / recovery pending），跨 recovery cycle 不启动 replacement、不伪装 healthy、无 orphan（one-listener invariant 跨 cycle 成立）；`_poll_health` 增加 pending 旧 listener 迟延退出独立检测（退出确认后必清理引用 → exactly one replacement）；② wait_ready authority：wait_ready 返回值参与 start success 判定（初始化超时不 reset recovery/backoff、不报告 healthy）；健康判定新增 is_ready() 维度（alive != ready）；新增 14 项定向测试（跨 cycle 1/2/3、readiness A–D、ownership A–H），RW-012 定向 52 项 + 全量 non-GUI 1145 passed（1131 基线 + 14 新增，零下降）+ 真实 E2E 9 项全过；RW-008 无回归；Remote Sync 0/0）
> 2026-08-29（AAF-v0.4-TASK-009-FIX-001 — RW-012 listener-owned lifecycle 修复：registration/unregistration 归 listener 线程（thread-owned unregister，Bridge 主线程不再直接 UnregisterHotKey）、显式 stop 契约（request_stop + 有界 join，WM_QUIT 唤醒真实消息循环）、stop-before-replace（旧 listener 确认退出后才创建新 listener）、旧 listener 超时 fail safe、并发 transition 单一 owner（_lifecycle_lock）、intentional shutdown 不恢复不复活；新增真实线程级所有权测试（register/unregister 线程身份断言），RW-012 定向 38 项 + 全量 non-GUI 1131 passed（1114 基线 + 17 新增）；RW-008 无回归；Remote Sync 0/0）
> 2026-08-29（AAF-v0.4-TASK-009 — Bridge Reliability Final Closure：RW-008 = SOLVED（正式 Compact TASK contract 最终确认：LF/CRLF/BOM/独立行 marker/多行 Acceptance/后续 section/EOF/duplicate fail-closed/missing-empty reject/Route fail-closed，exact TASK-009 production fixture 通过；U+3000 / 富文本 / 「Acceptance Criteria」旧别名 = LEGACY / NON-CONTRACT / OBSERVATION，不扩张 parser）；RW-012 = SOLVED（hotkey listener 自恢复：Bridge 唯一 owner + HotkeyRecovery 有界 backoff（15/30/60s、连续 3 次失败停止）、恢复不重启 Bridge、主动退出不恢复/不复活、失败经 Tray/状态窗口/log 可见；21 项定向测试）；RW-021 = DEFERRED / OPEN P2（necessity check：不同 owner/根因、非最小改动 → v0.4 freeze 显式 non-blocking）；RW-024 = 观察确认（无二次 modal 回归；未跑 ToDesk-sensitive E2E）；全量 non-GUI 测试通过；Remote Sync 0/0）
> 2026-08-28（AAF-v0.4-TASK-007-FIX-002 — RW-022 Fresh-Process Provenance Closure：关闭 FIX-001 剩余的 provenance / self-hosting artifact blocker——① provenance authority 改为 schema 驱动 / explicit field：reviewer 结构化块新增可选 `blocking_provenance`（structured/framework/narrative），structured authority 只来自**显式声明**的合法值；`blocking_rework` key 存在性 / COMPLETE 标签不再推断 structured（`context_packet.build_stage_result` 与 `report.read_structured_blocking` 同步移除旧推断；legacy 缺字段 → narrative，backward compat，不 laundering）；② invalid provenance（类型/值非法）→ invalid structured result → fail closed（blocking_rework=True / provenance=framework / structured_summary_status=MALFORMED）；schema 层放行、build_stage_result 统一判定（避免 schema 静默降级为 narrative）；③ `git_changed_files` 过滤 PRE_ALLOWED_UNTRACKED 常驻项（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs，`-uall` 逐文件判定），stage changed_files 不再被常驻 untracked 项污染（Req 8）；④ reviewer prompt 契约（adapters._structured_contract_block）显式要求声明 blocking_provenance，上游 summary 展示 provenance；⑤ 优先级保持：Framework hard failure > explicit structured blocking > explicit structured non-blocking > legacy narrative fallback；FRAMEWORK_ERROR / required result 缺失/空 / invalid structured → fail closed 不变；Hermes SUCCESS narrative 技术性 FAILED → non-blocking 不变；PASS_WITH_WARNING + APPROVE + no blocking → SUCCESS 不变；⑥ self-hosting observation 登记（Req 10）：Framework task 在运行中修改自身 artifact-generation/aggregation 代码时，runner process 继续使用启动时已加载的旧代码（本任务 runner PID 22676 启动于 20:12:54，早于本次 commit），同一 TASK 后续 runtime artifact 不代表刚提交的新实现——本任务以 fresh-process 证据验证新实现（全新 python 进程跑 16 项 A–H 场景矩阵全 PASS + 全量 pytest 886 passed + Parent artifact SHA-256 基线复核零改写），不开发 hot reload / self-restart；Parent（FIX-001）历史 artifacts 零改动（SHA-256 基线记录于 `.aaf/AAF-v0.4-TASK-007-FIX-002/parent_hashes_record.txt`）；886 passed（867 基线 + 19 新增：18 项 FIX-002 A–H/单元 + 1 项 key-existence 语义回归，零下降）；RW-020 零改动无回归（12 项 RW-020 回归全过）；RW-022 = SOLVED / AAF-v0.4-TASK-007 = CLOSED / Runtime Integrity = CLOSED 的正式判定留待 WorkBuddy no blocking rework + Codex APPROVE + Remote Sync SYNCED 后由 Planner 确认；Next Step = Planner Runtime Integrity Retrospective → RW-024 Completion Dialog UX Fix → Intake / Bridge Reliability）\\
> 2026-08-28（AAF-v0.4-TASK-007 — Runtime Integrity：Dead Runner Detection + Final Status Truth：RW-020 → SOLVED（`ai_agent_framework/runtime_health.py` 只读 Runtime Health 层——Lifecycle State 与 Runtime Health 严格分离：组合信号死判（runner 进程缺失/身份不可证明 + last_activity stale + 期望阶段产物缺失 → SUSPICIOUS_DEAD「任务可能已异常中断」）；单一 PID / 单一时间阈值不判死；PID reuse fail-safe（不把 unrelated process 当 owner）；canonical terminal wins；force-cancel/recovery 流程保护；无 ownership 记录不误报；Status Window 中文警告横幅 + [查看诊断]（诊断行 + 既有 resume-from 恢复路径提示）；CLI `python -m ai_agent_framework.runtime_health --output <dir>`；实况验证：TASK-007 自身 runner HEALTHY（creation time + 命令行 identity））；RW-022 → SOLVED（最终状态聚合 structured-first：`<agent>_result.json` blocking_rework 优先于 narrative 关键词猜测；narrative legacy fallback 保留且 fail-safe；PASS_WITH_WARNING + Codex APPROVE + blocking NONE → Current Status = SUCCESS 且 warning 内容保留；真阻断（REQUEST_CHANGE / 缺失 / FRAMEWORK_ERROR）→ WAITING 不变；历史 REPORT 不重写）；53 项新测试（30 runtime health + 20 聚合 + 3 UI 集成）+ 6 项真实 runner 运行时练习（正常 RUNNING HEALTHY / dead RUNNING SUSPICIOUS_DEAD / resume 兼容（RW-020 事故形态 → resume-from → SUCCESS）/ SUCCESS-with-warning / genuine blocking WAITING / required agent missing）；839 passed（780 基线 + 59 新增，零下降）；WorkBuddy 独立验证 + Codex 审查按 route 执行；Next Step = Planner Runtime Integrity Retrospective → Intake / Bridge Reliability planning）\
> 2026-08-28（AAF-v0.4-TASK-006-FIX-001 — Phase F Atomic Config Persistence and Real UX Closure：关闭 Codex 两个 blocker——① `bridge/config.py` save_config 从 `Path.write_text` 直写改为统一 atomic contract：正式 config.json 同目录写 `.config.json.tmp-*` 临时文件 → flush + fsync → close 完成后 `os.replace` 原子替换；临时写失败 / replace 失败 / 异常路径统一清理 tmp 并抛 ConfigError，旧 config 字节级保留；update_project 复用同一路径（无旁路）；新增 11 项原子持久化单测（success / tmp 写失败 / replace 失败 / json 序列化异常 / 旧 config 保留 / 成功切换 restart 恢复 / 失败切换 restart 旧配置可加载 / tmp 零残留）；② 补齐真实 Bridge/UI 交互证据——确定性 UI harness 驱动真实 tk.Tk + 真实剪贴板 + 真实 `_handle_hotkey → _process_clipboard` + 真实「切换项目确认」窗 /「任务已存在」状态卡片（检查窗口 Label 内容树并 invoke 真实按钮），覆盖 A Known 确认切换并执行 / B 拒绝零写入 / C Unknown 确认前不执行 / D Invalid 明确拒绝无绕过 / E Duplicate RUNNING 卡片+registry 无第二 runner / F Duplicate terminal 卡片+REPORT 路径+artifacts 不覆盖 / G RUNNING 跨 workspace 拒绝且当前任务不受影响 / H restart 恢复 current project + duplicate protection；真实 UI 验收发现并修复 duplicate 卡片 [打开 REPORT] 死按钮（`_safe` 包装器零参调用 → TypeError 被吞；改为闭包捕获 report_path）；UX evidence（9 组真实窗口内容树）存 `.aaf/AAF-v0.4-TASK-006-FIX-001/UX_EVIDENCE.md`；780 passed（760 基线 + 20 新增：11 原子 + 9 真实 UI，全量两次连跑零失败）；RW-003 / RW-016 SOLVED 状态保持（按实际证据正式收口）；Phase F 正式 COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 复审后由 Planner 确认；Next Step = Planner Phase F / v0.4 Remaining-Issues Retrospective → Runtime Integrity batch planning）\
> 2026-08-28（AAF-v0.4-TASK-006 — Phase F Project Switching and Duplicate Task UX Implementation：Bridge 从 canonical TASK Workspace 识别目标 workspace（不依赖聊天上下文）；workspace 分类驱动提交流程——SAME 无额外确认 / KNOWN（recent_projects）显式确认切换 / UNKNOWN 首次出现 fail-safe 暂停 + 明确确认 / INVALID fail closed 拒绝并给出明确原因；切换持久化唯一入口 config.update_project（current_project / current_workspace + recent_projects 上限 5）；RUNNING 任务拒绝跨 workspace 切换；duplicate 状态卡片（running 不启动第二 runner / completed 需新 Task ID / abnormal / unknown，中文展示 + 不覆盖 artifacts）；restart 恢复 current project + duplicate protection；真实 Windows E2E A–I 全过；760 passed（688 基线 + 72 新增，零下降）；RW-003 / RW-016 → SOLVED（设计 §9/§10 全量落地）；RW-006 → SOLVED（仅按 Phase C/D/E/F 真实交付证据校正状态，不重新开发）；RW-009 / RW-014 状态核对保持 PARTIAL（无新交付）；Phase F 正式 COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 审查；Next Step = Planner v0.4 Remaining-Issues Retrospective → Runtime Integrity batch）\
> 2026-08-28（AAF-v0.4-TASK-005-C-FIX-001 — Cancel Timestamp Timezone Compatibility Fix：修复 Codex 唯一 blocker——`cancel.parse_requested_at` 可返回 offset-aware datetime，但 status_window / launcher 用 naive `datetime.now()` 与其相减 → TypeError 破坏 Cancel UI（降级 unknown_snapshot）/ force eligibility；新增 canonical `cancel_mod.requested_at_elapsed_seconds`（UTC/aware contract：aware 统一到 UTC、legacy naive 明确按本地时间解释、malformed → None fail closed、未来时间戳钳制 0），status_window.collect_cancel_ui 与 launcher.force_eligible 统一走该入口；新增 22 项回归测试（+08:00 / +00:00 / Z / legacy naive / malformed / 超时前后 / collect_cancel_ui 与 force_eligible 不抛异常 / restart-reopen 推导不降级）；688 passed（666 基线 + 22 新增，零下降）；Phase E = COMPLETE / Phase F = NOT STARTED / Next Step = Planner Phase E Retrospective）\
> 2026-08-28（AAF-v0.4-TASK-005-C — Phase E Status Window Cancel UX + Real Windows E2E Closure：状态窗口「停止当前任务」soft cancel 入口 + 「强制停止」二次确认 + CancelUi 状态机（UI/control 态，§6A.3 不进入 task.json）+ force eligibility 需 ownership VERIFIED（fail closed）+ UI Authority 边界（窗口只发请求）+ canonical winner 跟随 + artifacts 恢复；真实 Windows 正负 E2E A–G 全过；666 passed（630 基线 + 36 新增）；Phase E = COMPLETE / Phase F = NOT STARTED / Next Step = Planner Phase E Retrospective）\
> 2026-08-28（AAF-v0.4-TASK-005-B-FIX-001 — Force Recovery Authority and Successful Termination Proof Closure：Core finalizer 由 canonical Bridge registry root + launch_id 推导 registry/evidence 路径（官方 read contract，evidence.registry_path 只作 proof）、evidence 绑定 canonical Bridge location、termination_exit_status == 0 才授权 CANCELLED、registry durable force 字段逐项核对、三方 identity 全量交叉；新增 32 项 authority 正负矩阵测试；Obsidian Handoff = VERIFIED（新 Planner 对话经 CURRENT_HANDOFF + PROJECT_STATE 恢复项目状态成功））\
> 2026-08-28（AAF-MAINT-CONTEXT-001-FIX-003 — Explicit Route Authority + Snapshot Reference Closure：`Route:` canonical machine 字段优先于关键词 heuristic、Route Completeness Guard（required Codex 缺失不得 SUCCESS）、manifest 区分 intake_task（provenance）/ execution_task（authority）、REPORT 统一引用 immutable snapshot；唯一 Next Step 保持 = AAF-v0.4-TASK-005-B-FIX-001）\
> 2026-08-28（AAF-MAINT-HANDOFF-001 — Obsidian Conversation Handoff Pilot + 阶段收口）：\
> Obsidian Handoff = **VERIFIED**（D:\AdyAI\Obsidian-Vault\AI Agent Framework\CURRENT_HANDOFF.md；\
> 2026-08-28 由 005-B-FIX-001 新会话读取并准确恢复项目状态后验证）；\
> Context Compaction Maintenance = **CLOSED → PRODUCTION OBSERVATION**（不主动重新设计）；\
> Stage Retrospective / Safety-Efficiency Balance Rule + Context Compaction Observation Rule\
> → AAF_TASK_EXECUTION_POLICY §13 / §14；\
> GitHub = 正式 / 已提升知识权威；Obsidian = Working Knowledge / Conversation Handoff 层\
> （GitHub / Obsidian 分工见 AAF_MASTER_BACKLOG.md §5.4）\
> Document Type: **Living Project State / 持续更新的当前状态入口**
>
> 本文件不是历史快照。后续每完成一个重要阶段、发生 Framework
> 级变更、版本状态变化或关键风险变化，都应更新本文件。
>
> 下方 v0.3 及更早内容属于历史状态，保留不删除；当前状态以顶部 v0.4 块为准。

------------------------------------------------------------------------

## 0. v0.4 Current Status（当前状态）

``` text
Version: v0.4
Status: IN PROGRESS
Phase: A — Runtime State Foundation: COMPLETE
       B — Bridge Background / Tray Skeleton: COMPLETE
       C — Status Window + Chinese-first UI: COMPLETE
       D — Progress Visualization: COMPLETE
       E — Safe Cancel Lifecycle: COMPLETE（E-Core / Soft Cancel COMPLETE — AAF-v0.4-TASK-005-A，
            005-A-FIX-001 关闭 Codex 两个 blocking safety defects 并同步；
            005-A-FIX-002 已实现 recovery 单一 state.lock 原子协议（identity+evidence+
            arbitration+commit 同一临界区，关闭遗留 recovery TOCTOU）；
            005-A-FIX-003 已实现 cancel.request mutation 锁序列化（write/consume 与
            terminal writers 共享同一 state.lock，关闭 evidence replacement race）+
            forced-order 握手修正；
            E-Ownership / Force Cancel COMPLETE — AAF-v0.4-TASK-005-B（Process Ownership
            / Force Cancel / Recovery Integration：launch_id / control.json / Bridge
            persistent launch registry / ownership verification（11 项三方校验）/
            force cancel API（verified process-tree termination + 结构化 force evidence）/
            Core recovery finalizer force path / restart reauthentication / canonical-aware
            wait thread + reconciliation；已执行：WorkBuddy PASS / Codex REQUEST_CHANGE）
            + 005-B-FIX-001（Force Recovery Authority + Successful Termination Proof
            Closure：canonical Bridge registry/evidence authority 绑定、exit 0 成功终止
            证明、registry durable force 字段逐项核对、三方 identity 全量交叉——Codex
            原两个 blocker 已闭合；新增 32 项 authority 正负矩阵）；
            Status Window Cancel UX + Real Windows E2E Closure COMPLETE —
            AAF-v0.4-TASK-005-C（状态窗口「停止当前任务」soft cancel 入口 + 二次确认
            「强制停止」+ CancelUi 状态机 + force eligibility fail closed + UI Authority
            边界 + canonical winner + artifacts 恢复；真实 Windows 正负 E2E A–G 全过；
            666 passed；见下方 Phase E 段落）
            + 005-C-FIX-001（Cancel Timestamp Timezone Compatibility Fix：canonical
            UTC/aware elapsed contract——cancel elapsed 统一经
            cancel_mod.requested_at_elapsed_seconds，合法 offset-aware（+08:00 / +00:00 /
            Z）与 legacy naive 均正确换算，malformed fail closed；status_window 与
            launcher.force_eligible 不再 naive/aware 混算；新增 22 项回归；688 passed；
            Codex 原 timezone blocker 已闭合）——Phase E 正式标记 COMPLETE（route 阶段
            WorkBuddy / Codex 独立复核按惯例执行并记录于任务 REPORT，若 blocking 则
            按惯例开 FIX））
       F — Project Switching + Duplicate Task UX: IMPLEMENTATION DELIVERED（2026-08-28，
            AAF-v0.4-TASK-006：workspace 分类提交流程（SAME/KNOWN/UNKNOWN/INVALID +
            config.update_project 持久化 + recent_projects）+ duplicate 状态卡片
            （running/completed/abnormal/unknown）+ RUNNING 保护 + restart 恢复；
            72 项新测试（63 单元 + 9 真实 Windows E2E A–I）；760 passed；
            RW-003 / RW-016 / RW-006 收口 SOLVED；正式 COMPLETE 判定留待 WorkBuddy
            独立验证 + Codex 审查后由 Planner 确认，本任务不自行宣布）
Direction: Desktop Shell MVP / Runtime Observability & Control
Context Compaction Maintenance: CLOSED → PRODUCTION OBSERVATION（不主动重新设计；观察项见 Policy §14）
Obsidian Handoff: VERIFIED（CURRENT_HANDOFF.md；2026-08-28 005-B-FIX-001 新会话读取并准确恢复项目状态后验证）
GitHub Handoff: VERIFIED（PROJECT_STATE + BACKLOG + Git + latest REPORT 权威恢复链不变）

v0.4 主线（Phase 顺序）：
A. Runtime State Foundation（COMPLETE）
B. Bridge Background / Tray Skeleton（COMPLETE）
C. Status Window + Chinese-first UI（COMPLETE — 2026-08-27 closure：AAF-v0.4-TASK-003-FIX-001 正式同步；
   实现 + WorkBuddy 独立验证 + Codex 审查全部通过，见下方 Phase C 段落）
D. Progress Visualization（COMPLETE — 2026-08-27 closure：AAF-v0.4-TASK-004-FIX-001 正式收口；
   实现 + 测试 + 真实 Windows E2E + 独立 post-completion closure audit 通过，见下方 Phase D 段落）
E. Safe Cancel Lifecycle（COMPLETE — 2026-08-28 closure：AAF-v0.4-TASK-005-A（E-Core /
   Soft Cancel）+ 005-A-FIX-001/002/003 + 005-B（E-Ownership / Force Cancel）+
   005-B-FIX-001（canonical force authority + successful termination proof）+
   005-C（Status Window Cancel UX + Real Windows E2E Closure）全部交付；
   666 passed；真实 Windows 正负 E2E A–G 全过；route 阶段 WorkBuddy / Codex 独立复核
   按项目惯例由 route 执行并记录于任务 REPORT；见下方 Phase E 段落）
F. Project Switching / Duplicate Task UX（IMPLEMENTATION DELIVERED — 2026-08-28，
   AAF-v0.4-TASK-006：workspace 分类提交流程 + duplicate 状态卡片 + RUNNING 保护 +
   restart 恢复；760 passed；RW-003 / RW-016 / RW-006 收口 SOLVED；正式 COMPLETE
   判定留待 WorkBuddy 独立验证 + Codex 审查后由 Planner 确认——见下方 Phase F 段落）

当前唯一 Next Step = Planner Runtime Integrity Retrospective
→ Intake / Bridge Reliability planning（不自动进入最终封装）。

Phase C 目标：正式状态窗口（bridge/status_window.py）—— 只读观察 + 中文优先 +
六阶段条事实映射；Tray 接入（打开状态窗口复用/聚焦，关闭不退出 Bridge）；
现有弹窗文案中文化（不改 TASK 解析 / validation / launcher 语义 / lifecycle）。

Phase C Implementation（AAF-v0.4-TASK-003，2026-08-27）：
- Status Window：bridge/status_window.py（信息架构 §3 / wireframe §12.1；当前项目 / Bridge /
  热键 / Workspace / 当前任务（Task ID / Name / 阶段 / Agent / 已运行 / 最近活动 / 整体结果）/
  六阶段条（✓ ▶ ○ ⏸ ✗）；约 1 秒 after 只读刷新；单例复用/聚焦；关闭不退出 Bridge）
- Runtime State Source：全部展示可追溯到 task.json（runtime_state reader）/ route.json /
  boundary.json / REPORT.md / last_run.json / config.json / launcher 内存；UI 不写任何 canonical artifact
- Current Task 解析：launcher RUNNING 内存任务优先 → 最近 last_run；last_run 新增持久化 output_dir
  （legacy 无该字段时从 task_path 推导，不扫描 .aaf 猜测）
- Chinese-first：窗口/弹窗/按钮中文（设计 §11.1 文案表）；技术字段（Task ID / SUCCESS 等）保留英文原值；
  CANCELLED 未增加（Phase E 范围）
- Tray：菜单项改为「打开状态窗口」；Restart / Exit / 单实例 / 热键语义未变
- 回归：239 基线不降，全量 284 passed（+45 新增 tests/test_status_window.py）
- 真实 Windows E2E（.aaf/AAF-v0.4-TASK-003/：EVIDENCE.md、s1–s7 步骤脚本、各阶段截图）：
  后台 Bridge → Tray 打开状态窗口 → 空状态显示 → 真实 Ctrl+Alt+A 全路由任务
  （Hermes→WorkBuddy→Codex→REPORT）→ 状态窗口阶段变化可见（截图验证）→ SUCCESS 收敛
  （已完成（SUCCESS）/ 六阶段全 ✓）→ 关闭窗口 Bridge 存活 → 再次打开正常 →
  Restart/Exit 回归通过（Exit 确认窗中文按钮；状态文件 0 变更）→ Agent 子进程无 console 黑窗
- WorkBuddy: PASS_WITH_WARNING（无 blocking rework；warning = TASK #10 与冻结设计中文映射措辞差异
  （实现遵循冻结设计，正确）+ Validator 未亲自重跑完整 GUI E2E（证据由 Hermes 提供，结构支撑充分））
- Codex: APPROVE（Blocking Issues: NONE；Scope Leakage: NONE；Recommended Phase C Status: COMPLETE）
- Blocking: NONE（实现侧 + 验证侧）
- Remote Sync: SYNCED
- 正式 closure: AAF-v0.4-TASK-003-FIX-001（2026-08-27）——见下方「0.2 Phase C」段落与
  docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-C-CLOSURE-2026-08-27.md
- 汇总语义异常（已登记 RW-022，非 Phase C 实现问题）：最终 REPORT 顶部 Current Status 曾为 WAITING，
  但 WorkBuddy 无 blocking rework + Codex APPROVE + Blocking Issues NONE；该 WAITING 来自
  aggregation / warning semantics，不是 Phase C implementation blocker（详见 AAF_MASTER_BACKLOG.md RW-022）

Phase A 目标：task.json = live canonical runtime view
（started_at / stage / stage_started_at / last_activity_at / agent / phases），
统一 Runtime State reader（legacy 兼容），runner EXTEND ONLY 阶段写入。

Phase A Closure（AAF-v0.4-TASK-001-FIX-001 + FIX-002 + FIX-003，2026-08-27）：
- Tests: 216 passed
- Review: COMPLETE（WorkBuddy APPROVE + Codex APPROVE）
- Remote Sync: SYNCED — closure commits 均已纳入 origin/main
- Branch: main
- Ahead/Behind: 0/0（at closure verification）
- 实时 Git HEAD 属于执行时状态，不在本 Living Project State / durable closure doc
  中硬编码为永久当前值；实时 HEAD 请直接用 Git 查询（git rev-parse HEAD / git status）
- 历史记录（RW-018 Git/network observation）：FIX-001 初次 push 曾因 TLS EOF 失败，
  后续 WorkBuddy 独立验证中成功执行 push；仅作历史环境说明，
  当前无 remote sync blocking / PENDING
- Unresolved: None blocking
- Commit 历史归属: 5a8b76a（Phase A implementation）；f81c7ee（FIX-001 closure work）；
  ca06c29（FIX-001 REMOTE_SYNC_PENDING record）；e3d39e7（FIX-002 remote-state
  documentation sync attempt）；FIX-003（docs-only closure consistency fix，
  仅作历史 reference，不写为“永久 Current HEAD”）

Phase B 目标：Bridge 以 pythonw 无控制台常驻（scripts/start_bridge.pyw）+ Tray skeleton
（打开状态 / 重启 Bridge / 退出 AAF）+ 单实例 mutex + hotkey health 判定；
Core / UI 边界：Desktop Shell 只读产物，不复制 Router / Runner / Lifecycle。

Phase B Closure（AAF-v0.4-TASK-002 + AAF-v0.4-TASK-002-FIX-001，2026-08-27）：
- TASK: AAF-v0.4-TASK-002（Bridge Background / Tray Skeleton）
- Closure validation: AAF-v0.4-TASK-002-FIX-001（Phase B Hotkey End-to-End Closure Validation）
- Implementation commit: 6a9814d
- Tests: 233 passed（216 baseline + 17 新增，零下降）
- Background pythonw Bridge: PASS（无控制台常驻，真实 Windows 验收）
- Tray: PASS（Shell_NotifyIconW 真实创建；状态窗口可打开，关闭不退出 Bridge）
- Single instance: PASS（命名 mutex；restart 交接 WAIT_ABANDONED 路径实测通过）
- Ctrl+Alt+A real GUI E2E: PASS（Hotkey → Clipboard → TASK validation → Confirmation
  → Launcher → Framework → REPORT 全链路；原 error 1409 来源确认为旧 Bridge 自身遗留）
- Restart regression: PASS（重启后单实例 / Tray / Hotkey 全部恢复）
- Exit regression: PASS（Exit 不修改 canonical task terminal state；状态快照 diff 0/0/0）
- WorkBuddy: PASS_WITH_WARNING（唯一 warning = Codex closure review 延迟，后已由 Codex 独立执行）
- Codex: APPROVE
- Remote Sync: SYNCED
- Blocking: NONE
- 新发现缺口（非 Phase B blocker，仅长期登记，不在 Phase B 实现）：
  Bridge Restart / Exit 后 completion notification continuity 丢失
  → 已登记 RW-021（见 AAF_MASTER_BACKLOG.md），与 RW-020 明确区分
- Durable closure 报告：docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-B-CLOSURE-2026-08-27.md

Next Phase Candidate: Phase D — Progress Visualization
（历史记录：Phase C 完成时的候选标记；Phase D 已由 Planner 正式启动为 AAF-v0.4-TASK-004，
现为 IMPLEMENTATION COMPLETE 待验证——见上方 Phase D 段落）

v0.3: CLOSED（见下方历史块，不重开）
v0.4 启动决定：Planner / User 已批准（见
docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-A-START-HANDOFF-2026-08-27.md）
```

### 0.1 Phase A — Runtime State Foundation（COMPLETE）

- TASK: AAF-v0.4-TASK-001（2026-08-27）；closure: AAF-v0.4-TASK-001-FIX-001 + FIX-002 + FIX-003（2026-08-27）
- 状态：COMPLETE（WorkBuddy APPROVE + Codex APPROVE；216 passed；Remote Sync SYNCED；
  实时 HEAD 属执行时状态，用 Git 查询，不在此处硬编码为永久当前值）
- 范围：task.json live runtime state / Runtime State reader / runner 阶段写入 / PROJECT_STATE 同步
- 禁止（Phase A 不实现）：Tray / status window / pystray / autostart / progress bar / stuck 算法 /
  Safe Cancel（CANCELLED / control.json / state.lock / launch registry / force kill）/
  project switching UI / Duplicate dialog / Desktop Shell packaging

### 0.2 Phase B — Bridge Background / Tray Skeleton（COMPLETE）

- TASK: AAF-v0.4-TASK-002（2026-08-27）；closure: AAF-v0.4-TASK-002-FIX-001（Phase B Hotkey
  End-to-End Closure Validation，2026-08-27，真实 Windows GUI 验收）
- 状态：COMPLETE（WorkBuddy PASS_WITH_WARNING + Codex APPROVE；233 passed；
  Remote Sync SYNCED；实时 HEAD 属执行时状态，用 Git 查询，不在此处硬编码为永久当前值）
- 范围：pythonw 无控制台后台宿主（scripts/start_bridge.pyw）/ Tray skeleton（打开状态 /
  重启 Bridge / 退出 AAF，ctypes Shell_NotifyIconW 零第三方依赖）/ 单实例 mutex /
  hotkey health 判定（OK / DEGRADED）/ restart 交接 / exit 语义（不改 canonical state）/
  Core / UI 边界只读
- 验收证据：.aaf/AAF-v0.4-TASK-002-FIX-001/（EVIDENCE.md、status_window.png、
  s1–s6 步骤脚本、REPORT.md）；正式 closure 报告见
  docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-B-CLOSURE-2026-08-27.md
- 新发现缺口：Bridge Restart / Exit 后 completion notification continuity 丢失
  → 已登记 RW-021（非 Phase B blocker，不重开 Phase B，不在本阶段实现）
- 禁止（Phase B 不实现）：Phase C-F 全部内容 / autostart / Safe Cancel（CANCELLED /
  cancel.request / control.json / state.lock / launch registry / force kill）/
  RW-020 / completion reattachment

### 0.2 Phase C — Status Window + Chinese-first UI（COMPLETE）

- TASK: AAF-v0.4-TASK-003（2026-08-27）；closure: AAF-v0.4-TASK-003-FIX-001（Phase C Closure Sync，2026-08-27）
- 状态：COMPLETE（WorkBuddy PASS_WITH_WARNING（无 blocking rework）+ Codex APPROVE；284 passed；
  Remote Sync SYNCED；实时 HEAD 属执行时状态，用 Git 查询，不在此处硬编码为永久当前值）
- Implementation commit: 5458def（feat(v0.4-phase-c): status window + chinese-first UI）
- 范围：bridge/status_window.py 正式状态窗口（Bridge/Project 区 + Current Task 区 + 六阶段条
  ✓▶○⏸✗、约 1s tkinter.after 只读刷新、单例复用/聚焦、关闭不退出 Bridge）/ Chinese-first
  （窗口/弹窗/按钮中文、技术字段保留英文原值）/ Runtime State 只读展示（runtime_state reader +
  last_run.json + config + launcher 内存；UI 零写 canonical artifact）/ Tray「打开状态窗口」接入
  （restart / exit / 单实例 / 热键语义未变）/ 现有 Bridge 弹窗文案中文化
  （不改 TASK 解析 / validation / launcher 语义 / lifecycle）
- 验收证据：.aaf/AAF-v0.4-TASK-003/（EVIDENCE.md、空状态截图 + 4 张阶段截图 + 最终收敛截图、
  s1–s7 步骤脚本、evidence.jsonl）；正式 closure 报告见
  docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-C-CLOSURE-2026-08-27.md
- 测试：284 passed（239 基线 + 45 新增 tests/test_status_window.py，零下降；覆盖 req 19 A–L 全项：
  status/stage/agent 映射、legacy/缺失字段、空状态、当前任务解析、elapsed/last activity 格式化、
  窗口单例、Tray 集成、中文文案、刷新回调安全）
- Windows E2E：PASS（后台 Bridge → Tray 打开状态窗口 → 空状态显示 → 真实 Ctrl+Alt+A 全路由任务
  Hermes→WorkBuddy→Codex→REPORT → 阶段变化可见（截图验证）→ SUCCESS 收敛（已完成（SUCCESS）/
  六阶段全 ✓）→ 关闭窗口 Bridge 存活 → 再次打开正常 → Restart/Exit 回归通过
  （Exit 确认窗中文按钮；状态文件 0 变更）→ Agent 子进程无 console 黑窗）
- Current Task resolution: PASS / Stage strip: PASS / elapsed / last activity: PASS /
  singleton window behavior: PASS / Tray integration: PASS / no-console regression: PASS
- WorkBuddy: PASS_WITH_WARNING（无 blocking rework；warning = TASK #10 与冻结设计中文映射措辞差异 +
  Validator 未重跑完整 GUI E2E，均非代码问题）
- Codex: APPROVE（Blocking Issues: NONE；Scope Leakage: NONE；Recommended Phase C Status: COMPLETE）
- Remote Sync: SYNCED
- Phase D-F scope leakage: NONE
- Blocking: NONE
- 汇总语义异常（已登记 RW-022，非 Phase C 实现问题）：最终 REPORT 顶部 Current Status 曾为 WAITING，
  但 WorkBuddy PASS_WITH_WARNING（无 blocking rework）+ Codex APPROVE + Blocking Issues NONE；
  该 WAITING 来自 aggregation / warning semantics，不是 Phase C implementation blocker
  （详见 AAF_MASTER_BACKLOG.md RW-022）
- 既有缺口（不重复登记）：Bridge Restart / Exit 后 completion notification continuity 丢失
  → RW-021（OPEN / P2）；Phase C E2E 中再次复现，已按 RW-021 覆盖，未重复新建 issue，本阶段不实现
- 禁止（Phase C 不实现）：Phase D-F 全部内容（progress bar / percentage / phase weights /
  stuck detection / Safe Cancel / launch registry / completion reattachment / project switching /
  Duplicate UX）/ RW-020 / RW-021 / final-status aggregation fix

### 0.2 Phase D — Progress Visualization（COMPLETE）

- TASK: AAF-v0.4-TASK-004（2026-08-27）；closure: AAF-v0.4-TASK-004-FIX-001（Phase D Post-Completion
  Closure Audit，2026-08-27）
- 状态：COMPLETE（实现 + 334 passed + 真实 Windows E2E + 独立 post-completion closure audit 全部通过；
  WorkBuddy 独立验证 + Codex closure review 由 AAF-v0.4-TASK-004-FIX-001 route 阶段（hermes→workbuddy→codex）
  在 Executor 返回后依次执行，判定记录于该任务 REPORT.md；Remote Sync SYNCED）
- Implementation commit: 6c27a27（feat(v0.4-phase-d): progress visualization + suspected-stuck）
- 范围：bridge/progress.py（集中权重表 §4.2 Validation 5 / Boundary 5 / Hermes 45 / WorkBuddy 20 / Codex 20 /
  Report 5 合计 100 断言保护 + 确定性估算纯函数 §4.1：已完成阶段全权重；进行中阶段内部 0%–50% 线性、60 分钟
  封顶；SUCCESS→100%；WAITING/FAILED 冻结在已完成阶段权重和；无任务/无 task.json → 0；legacy 缺失 phases
  不崩溃 + 中文文案 §12.1）/ bridge/stuck.py（suspected-stuck 最小观察 §5.2：RUNNING + last_activity_at
  距今 ≥ 10 分钟 →「⚠ 任务可能已停滞（最近 N 分钟没有活动）」；阈值集中常量化；只提示、零 canonical 写入；
  RW-020 边界）/ bridge/status_window.py（整体进度条 Canvas 只读渲染 +「整体进度：约 N%（估算）」+
  当前阶段占比 + stuck 黄色横幅 + 进行中阶段高亮 +「查看任务目录」按钮；约 1s tkinter.after 只读刷新、
  Tk 主线程更新、关闭后刷新安全）/ docs（QUICKSTART / TROUBLESHOOTING：进度是估算、100% 只在 SUCCESS
  保证、stuck 仅可疑）
- 进度规则（确定性，单调性）：正常推进序列单调不倒退（0→5→14→21→55→85→96→100）；SUCCESS→100%；
  FAILED/WAITING 终态按设计 §4.1.5 冻结在已完成阶段权重和（估算→事实收敛，明确理由 + 测试覆盖）
- 只读边界：进度/停滞全部由 runtime_state reader + task.json phases + timestamps 计算；
  UI 零写 task.json / run.json / route.json / boundary.json / REPORT.md / cancel.request
- 测试：334 passed（284 基线 + 50 新增 tests/test_progress.py，零下降；覆盖 TASK req 22 A–T 全项：
  0% / 各阶段 running / SUCCESS 100 / FAILED <100 / WAITING 冻结 / legacy / no-task / monotonic /
  stuck 阈值上下 / SUCCESS·FAILED·WAITING 不显示 stuck / last_activity·stage_started_at 缺失 /
  中文文案 / 权重表集中 / GUI 进度条·横幅·高亮·任务目录按钮 / 无 CANCELLED scope leak）
- 真实 Windows E2E（.aaf/AAF-v0.4-TASK-004/：EVIDENCE.md、evidence.jsonl、9 张截图、e2e_phase_d.py）：
  Tray 打开状态窗口（空状态）→ stuck fixture 独立验证（真实 Tk 断言 + live 窗口截图）→ 真实 Ctrl+Alt+A
  全路由任务（Hermes→WorkBuddy→Codex→REPORT）→ 进度采样 [10, 55, 75, 100] 单调推进 →
  SUCCESS = 100%（全绿进度条 +「整体进度：100%（已完成）」）→ 关闭窗口 Bridge 存活 → 重开进度仍正确 →
  三 Agent 进程树 console_windows 全空（无 console 黑窗）→ 无 Tk callback 异常 → Tray Exit 正常退出；
  像素级验证进度条绿色随百分比单调递增、stuck 横幅仅 stuck 态出现
- 独立 post-completion closure audit（AAF-v0.4-TASK-004-FIX-001，2026-08-27）：
  - Source of Truth 核对：PROJECT_STATE / AAF_MASTER_BACKLOG / 冻结设计 §4/§5/§12.1 / Phase C closure
    handoff / .aaf/AAF-v0.4-TASK-004 全部证据 / 当前代码（progress.py / stuck.py / status_window.py /
    tests/test_progress.py）逐一核对一致
  - 实现侧独立核对通过：progress bar / percentage text / 固定确定性权重模型 / 权重集中 / SUCCESS=100 /
    FAILED·WAITING 收敛 / 单调正常序列 / Chinese-first / suspected-stuck warning / stuck 只读 /
    零 canonical 写入 / 无 Phase E/F 泄漏（bridge/ 无 cancel.request / control.json / state.lock /
    launch registry / force kill / CANCELLED 实现，仅注释声明不实现）
  - 权重模型核对：实现 == 冻结设计（Validation 5 / Boundary 5 / Hermes 45 / WorkBuddy 20 / Codex 20 /
    Report 5 = 100，assert 保护）
  - 进度语义核对：no task → 0；RUNNING 阶段估算；completed 阶段全权重；SUCCESS=100；FAILED<100；
    WAITING 不自动推进；legacy/缺失字段安全；正常生命周期进度不倒退
  - stuck 语义核对：suspected-stuck ≠ dead runner 判定；阈值集中（10 分钟常量）；仅 RUNNING + stale
    last_activity 提示；零 canonical mutation；无自动 resume / cancel / force kill；RW-020 未标 solved
  - 测试独立重跑：`pytest -q` = **334 passed in 4.45s**（零下降）
  - E2E 证据独立复核：evidence.jsonl 全步骤一致；progress samples [10,55,75,100] 单调；SUCCESS=100；
    独立像素抽样 s4_status_final.png 绿色进度条存在（335 样本点）而 s2_status_empty.png 无（0）；
    三 Agent console_count=0；bridge_error.log 不存在（无 Tk callback 异常）
  - RW-020 真实复现（追加证据，不标 solved）：TASK-004 canonical task.json 残留 RUNNING/HERMES
    （started_at = last_activity_at = 19:07:15）而 runner / Bridge 已不存在、REPORT.md 已生成（20:03:04）；
    UI suspected-stuck 不解决 RW-020（见 AAF_MASTER_BACKLOG.md RW-020）
  - RW-021 真实复现（追加证据，不实现 callback recovery）：Phase D E2E Bridge Exit/Restart 后 REPORT 已生成
    但用户未收到最终 completion window（见 AAF_MASTER_BACKLOG.md RW-021）
  - 新登记 backlog：RW-023（E2E Validation Fixed Task ID Reuse Causes Duplicate Trigger / GUI Loop，
    OPEN/P2）、RW-024（Completion Dialog Copy Report UX，OPEN/P2）——均无既有等价 issue，未重复创建
  - WorkBuddy: 独立验证（本任务 route 阶段执行，verdict 见 AAF-v0.4-TASK-004-FIX-001 REPORT.md）
  - Codex: closure review（本任务 route 阶段执行，verdict 见 AAF-v0.4-TASK-004-FIX-001 REPORT.md）
  - Blocking: NONE（实现侧 + 审计侧）
  - Remote Sync: SYNCED
  - 正式 closure 报告：docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-D-CLOSURE-2026-08-27.md
- 历史 task.json 残留说明：TASK-004 canonical task.json 的 RUNNING/HERMES 残留属 RW-020 真实复现证据，
  本 audit 只读保留、不修改其终态、不手工标 SUCCESS；该 run 的 runner 已不存在（E2E 前 cleanup.py 清理）
- 禁止（Phase D 不实现）：Phase E/F 全部内容（Safe Cancel / CANCELLED / cancel.request / control.json /
  state.lock / launch registry / force kill / project switching / Duplicate UX）/ RW-020 完整 dead-runner
  protocol / RW-021 / RW-022 aggregation fix
- Next Phase Candidate: Phase E — Safe Cancel Lifecycle（已由 Planner 正式启动为 AAF-v0.4-TASK-005-A，
  E-Core / Soft Cancel 交付完成；Phase E 未 COMPLETE，见下方 Phase E 段落）

### 0.2 Phase E — Safe Cancel Lifecycle（COMPLETE — 2026-08-28，TASK-005-C-FIX-001 收口）

- **TASK-005-C-FIX-001（AAF-v0.4-TASK-005-C-FIX-001，2026-08-28）：Cancel Timestamp
  Timezone Compatibility Fix（关闭 Codex 唯一 blocker）**：
  - 根因：`cancel.parse_requested_at()` 可返回 offset-aware datetime，但
    `bridge/status_window.py`（Cancel UI elapsed）与 `bridge/launcher.py`
    （force_eligible）用 naive `datetime.now()` 与其相减 → `TypeError: can't
    subtract offset-naive and offset-aware datetimes` → Cancel UI 降级
    unknown_snapshot / force eligibility 异常
  - 修复：`ai_agent_framework/cancel.py` 新增 canonical UTC/aware elapsed contract
    ——`requested_at_elapsed_seconds(requested_at, now=None)`：aware（+08:00 /
    +00:00 / Z）统一到 UTC 后计算；legacy naive 明确按本地时间解释（与历史
    write_cancel_request 默认语义一致，req 4）；malformed / 非字符串 → None（fail
    closed，req 5）；未来时间戳钳制 0.0；`normalize_aware` / `_local_timezone`
    辅助；`parse_requested_at` 语义不变（recovery evidence 校验契约不破坏）
  - `status_window.collect_cancel_ui` 与 `launcher.force_eligible` 统一走该入口；
    安全不变量零改动（soft cancel first / force 二次确认 / ownership verification /
    canonical registry/evidence / Core terminal authority / terminal precedence /
    无关进程安全）
  - 测试：`tests/test_phase_e_cancel_fix_001.py` 新增 22 项回归（+08:00 / +00:00 /
    Z / legacy naive / malformed / 超时前 / 超时后 / collect_cancel_ui 不抛异常 /
    force_eligible 不抛异常（真实 FrameworkLauncher + registry artifact，不启动
    进程）/ restart-reopen 推导不降级 unknown_snapshot）；**688 passed**（666 基线
    + 22 新增，零下降）
  - 边界遵守：无 Phase F / 无 aggregation（RW-022）/ 无 Context Compaction redesign /
    无 cancel.request schema 或 writer 默认格式变更（artifact 字节兼容）
  - route 阶段：WorkBuddy / Codex 独立复核按项目惯例由 route 执行（verdict 记录于
    任务 REPORT；若 blocking 则按惯例开 FIX）
- TASK: AAF-v0.4-TASK-005-A（2026-08-27）；范围：Phase E Core Cancel Foundation + Soft Cancel
  （冻结设计 §6 / §6A / §6B 的 E-Core 部分；Force Cancel / ownership / UI 分离到后续 TASK）
- 状态：**COMPLETE（实现 + 测试 + 真实 Windows 正负 E2E 全部通过；688 passed；**\
  **route 阶段 WorkBuddy / Codex 独立复核按项目惯例由 route 执行并记录于任务 REPORT，**\
  **若发现 blocking 则按惯例开 FIX——在此之前本标记按「已交付、正式关闭」对待）**
- 实现内容：
  - `ai_agent_framework/lock_utils.py`（新）：Core-owned per-task OS-level exclusive `state.lock`
    （§6B.1–§6B.3；Windows msvcrt.locking / POSIX flock；timeout；残留文件不占锁；crash 后 OS 自动释放；
    锁失败明确错误 FINALIZATION_BUSY；不绕过锁）
  - `ai_agent_framework/task_lifecycle.py`：CANCELLED 加入 VALID_STATUSES；TERMINAL_STATUSES =
    {SUCCESS, WAITING, FAILED, CANCELLED}（§6A.1）；`finalize_terminal()` 统一锁内 critical section
    （§6B.2：锁内 reload → terminal arbitration → 原子提交 + terminal_generation/terminal_at/
    terminal_reason/cancel_mode → release）；`update_status` 拒绝终态（防绕过锁）；
    `read_canonical_terminal()` 只读 canonical；legacy 无 generation 兼容
  - `ai_agent_framework/cancel.py`（新）：cancel.request 契约（task_id / requested_at / request=soft_cancel；
    原子写；无效请求安全处理返回 warning；非 terminal truth §6A.15）
  - `ai_agent_framework/reconcile.py`（新）：`reconcile_terminal_artifacts()`（§6B.6–§6B.8；
    无 canonical 不臆造；幂等补齐 run.json / REPORT.md；不改 canonical；generation 对齐；
    完整一致 no-op）
  - `ai_agent_framework/finalize_cancelled.py`（新）：Core-owned recovery finalizer 基础
    （§6A.12/§6B.21；CLI `python -m ai_agent_framework.finalize_cancelled`；幂等；
    已有终态不改写；**本 TASK 不从 Launcher 调用它去 taskkill**——Force Cancel 链留 005-B）
  - `ai_agent_framework/runner.py`：安全检查点（Validation 后 / Boundary 前；Boundary 后 / Hermes 前；
    Agent 之间；Codex 后 / Report 前）；有效 cancel.request → 不启动后续 Agent →
    task.json(CANCELLED) → run.json(CANCELLED) → REPORT(CANCELLED)（§6A.4 顺序）；
    统一经 finalize_terminal 提交终态；FRAMEWORK_ERROR 路径同样锁内提交；soft cancel exit code = 0
  - `ai_agent_framework/report.py`：REPORT 支持 CANCELLED（Current Status: CANCELLED + 「任务已取消」+
    Task ID / 取消时间 / 已完成阶段与 Agent 结果保留 / 后续阶段未执行；不伪造 Force Cancel /
    PID kill / ownership verified）+ Terminal Generation provenance
  - `ai_agent_framework/task_archive.py`：TERMINAL_STATUSES 单一来源（含 CANCELLED，可归档 §6.6）
  - `bridge/launcher.py`：RESULT_CANCELLED + wait thread 最小 canonical-aware 兼容读取（§6A.5：
    exit code 只是 evidence；canonical 存在则跟随 Core outcome；完整 wait-thread 归 005-B）
  - `bridge/status_window.py`：STATUS_LABELS / LAUNCHER_RESULT_LABELS 增加 CANCELLED → 「已取消」
    （§11.1 最小 compatibility；最终 [停止当前任务] 按钮属 005-C）
  - `bridge/progress.py`：CANCELLED 收敛（§4.1.5：停在取消时刻权重和，不显示 100%）
  - `docs/QUICKSTART.md` / `docs/TROUBLESHOOTING.md`：CANCELLED / soft cancel Core 契约 /
    cancel.request 是 request 不是 truth / Phase E 未 COMPLETE / Force Cancel 未交付
- 测试：**391 passed**（334 基线 + 57 新增，零下降；tests/test_phase_e_core.py 45 项覆盖 req 28 A–Z
  全项 + tests/test_phase_e_concurrency.py 真实子进程锁/竞态 5 项（req 29，不 mock 锁）+
  tests/test_phase_e_e2e.py 真实 E2E 4 项（req 30 两个 scenario + CLI 级 run.py / finalize_cancelled））
- **FIX-001（AAF-v0.4-TASK-005-A-FIX-001，2026-08-27）**：Codex 复审 REQUEST_CHANGE（两个 blocking
  safety defects）→ 关闭：
  1. **late non-terminal update 覆盖 terminal**：`update_status` 与 `finalize_terminal` 共享同一
     per-task `state.lock`（§6B.1/§6B.2）：锁内 reload canonical → 已有终态 → 不写、返回
     `UpdateResult(preserved=True)`；Runner post-agent runtime update 检测到终态 → 停止后续 Agent、
     派生产物跟随 canonical。新增真实跨进程 race 测试（runtime vs CANCELLED/SUCCESS/WAITING/FAILED）、
     generation 不丢失、lock-failure 语义、legacy terminal 拒绝 late update。
  2. **recovery finalizer 无 evidence/identity 验证**：`finalize_cancelled_task` 新提交 CANCELLED 前
     必须验证 canonical task.json exists + `task_id` 匹配；soft recovery 必须存在合法 matching
     `cancel.request`（parseable / soft_cancel / task_id 匹配 / requested_at 合法）；缺失/损坏/
     mismatch → `RecoveryEvidenceError`（fail safely，零 canonical 写）；force recovery → 005-A
     明确拒绝 `FORCE_RECOVERY_NOT_AVAILABLE`（不伪造）；CLI 与 library 同规则（exit 6）。
     已有终态无 evidence 仍 preserve + reconciliation 可用（req 9）。
  - 测试：**421 passed**（391 基线 + 30 净新增，零下降；tests/test_phase_e_fix_001.py 29 项 +
    resume 拆分 1 项：late-RUNNING 四终态、generation/metadata 保留、真实跨进程 race、
    真实 Runner Agent-return race、真实 E2E（Runner + finalize CLI 子进程）、
    evidence/identity 全拒绝矩阵、CLI 无 bypass、force 拒绝、no-force-kill 静态断言、
    REPORT no-force 严格断言（修正 advisory A tautology））
  - 行为契约变更：resume 只对非终态任务生效（终态不可被降级回 RUNNING）；recovery CLI
    要求 validated cancel.request。QUICKSTART / TROUBLESHOOTING 已同步。
  - WorkBuddy / Codex 独立复核由本任务 route 阶段执行（verdict 见任务 REPORT.md）
- **FIX-002（AAF-v0.4-TASK-005-A-FIX-002，2026-08-27）**：Codex 复审 REQUEST_CHANGE（遗留唯一
  blocking：recovery identity / evidence 验证与 CANCELLED commit 不在同一 state.lock 临界区，
  TOCTOU）→ 实现侧关闭：
  1. **单一不可分割临界区（frozen safety rule）**：`finalize_cancelled_task` 现在
     acquire state.lock → 锁内 reload canonical → 锁内 identity 校验（canonical exists +
     task_id 匹配）→ 锁内 terminal arbitration（已有终态 → 保留，不要求 evidence）→
     无终态 → 锁内验证当前 cancel.request（request=soft_cancel / task_id 匹配 /
     requested_at 合法）→ 同一临界区内经共享 helper 提交 CANCELLED + terminal_generation
     → release lock → reconciliation。验证与 commit 之间**不 release lock**。
  2. **无 nested lock reentry**：`task_lifecycle.py` 提取共享锁内 helper
     `_finalize_terminal_locked`（调用方已持锁、传入锁内 canonical snapshot、不再次
     acquire 锁）；public `finalize_terminal` 与 recovery finalizer 共用同一实现——
     terminal commit 逻辑仍只有一套，无第三 terminal writer。
  3. **lock-stable identity / evidence**：canonical identity 与 cancel.request 均在
     锁内读取验证，commit 使用同一锁内 snapshot；错误 task_id 不能被取消；
     验证失败/evidence 不匹配/identity 不匹配 → 零写、零 generation bump、
     零 reconciliation 变更。
  4. **强制时序测试（req 8）**：真实 OS 锁 + 子进程 + 握手文件——runtime writer
     已启动并阻塞等待 state.lock → terminal writer 持锁 commit（CANCELLED/SUCCESS）→
     release → runtime 后获锁、锁内 reload 看到 terminal → 零写入（preserved）。
  5. 测试：**447 passed**（421 基线 + 26 净新增，零下降；tests/test_phase_e_fix_002.py：
     A 单一临界区静态契约 + 持锁对抗者、B 取锁前 evidence 失效拒绝、C 临界区内替换
     无 stale window、D/E identity 改写拒绝/覆盖、F/G generation 不变量、H/I 已有终态
     preserve + reconciliation、J force 仍拒绝、K CLI 同一路径、L 强制时序、
     M/N 无 force kill / 无第三写者、双 recovery 并发恰一次 commit、锁失败不写、
     真实 E2E 两场景（合法 request → CANCELLED 全套产物 / 不匹配 request → 安全失败））
  - 行为契约不变：soft recovery 仍要求 validated cancel.request；force recovery 仍
    明确拒绝（FORCE_RECOVERY_NOT_AVAILABLE）；已有终态无 evidence 仍 preserve +
    reconciliation；CLI 与 library 同一原子验证路径。
  - WorkBuddy / Codex 独立复核由本任务 route 阶段执行（verdict 见任务 REPORT.md；
    **未经两者通过不记录 FIX-002 CLOSED**）
- **FIX-003（AAF-v0.4-TASK-005-A-FIX-003，2026-08-27）**：Codex 复审 REQUEST_CHANGE
  （两个剩余 blocking：evidence replacement race / forced-order 握手错误）→ 实现侧关闭：
  1. **cancel.request mutation 锁序列化（one lock protocol）**：`write_cancel_request` /
     `consume_cancel_request` 与 terminal writers 共享同一 per-task `state.lock`
     （`lock_utils.task_state_lock`，§6B.1）：recovery 在锁内验证 evidence 与 commit
     CANCELLED 之间，另一个 Framework writer 无法替换 / 删除 / consume 该 request——
     authority evidence 真正 lock-stable（Blocking 1 CLOSED）。公共 API =
     acquire state.lock → 委托锁内 helper（`_write_cancel_request_locked` /
     `_consume_cancel_request_locked`，不复制第二套 write/consume 语义，caller-already-
     locked 直接调 helper，无 nested reentry）；锁失败（timeout/OS 错误）→ 显式
     `LockTimeout` / `LockError`，不写 / 不 consume / 不 fallback 无锁写（§6B.19）。
  2. **身份护栏（req 8）**：`write_cancel_request` 锁内读取 canonical task.json，
     task_id mismatch → 拒绝写入（`CancelRequestIdentityError`，显式错误）；
     无 canonical（legacy / 新目录）→ 兼容写入，不破坏既有 soft-cancel E2E。
  3. **forced-order 握手修正（Blocking 2 CLOSED）**：重写 `test_l`——T_LOCKED 只在
     terminal writer **成功 acquire state.lock 之后**（锁内）发出；R_STARTED 在 runtime
     取锁前发出；R_DONE 缺失 + 进程存活 + 显式超时断言证明 runtime 真正等待锁；
     terminal 持锁 commit（CANCELLED + SUCCESS）→ release → runtime 后获锁 preserved。
  4. 测试：**461 passed**（447 基线 + 14 净新增，零下降；tests/test_phase_e_fix_003.py
     14 项：write/consume 锁静态契约、无未加锁官方 mutation 路径（静态 + 行为）、
     writer/consumer 持锁阻塞 + timeout 不写不 consume、consume 锁下幂等、身份护栏、
     invalid-before-lock 拒绝、mutation-after-terminal 不可变、真实 evidence-mutation
     race E2E 两变体（replace + consume：Recovery 持锁验证后暂停 → 官方 writer/consumer
     阻塞 → commit CANCELLED → release → 后者才完成 → terminal 不可变）、无 force kill /
     无第三 terminal writer；并发/竞态子集 74 项连跑 5 轮零 flake）。
  5. 行为契约变更：`write_cancel_request` 在 canonical task_id mismatch 时拒绝写入
     （显式错误）；`consume_cancel_request` 增加可选 task_id 参数（锁诊断用）与
     `lock_timeout` 参数；两者锁获取失败均显式抛错（原无锁语义不再存在）。
     recovery 单一临界区（FIX-002）保持不动；runner 检查点读取行为不变。
  - 边界遵守：无 Force Kill / 无 launch registry / 无 Stop UX / 无 005-B/005-C 泄漏；
    `.aaf/`、`scripts/start_bridge_hidden.vbs`、`AAF_TASK004_PROCESS_CHECK.txt` 未动。
  - WorkBuddy / Codex 独立复核由本任务 route 阶段执行（verdict 见任务 REPORT.md；
    **未经两者通过不记录 FIX-003 CLOSED**）
- **TASK-005-B（AAF-v0.4-TASK-005-B，2026-08-27）：Phase E Process Ownership / Force
  Cancel / Recovery Integration（E-Ownership / Force Cancel 已交付，待 005-B-FIX-001
  关闭后核准）**：
  - `ai_agent_framework/proc_identity.py`（新）：Windows 进程身份只读工具——真实进程
    创建时间（psutil 优先 / ctypes GetProcessTimes fallback）、live 命令行、Windows
    命令行 tokenize（CommandLineToArgvW）与规范化比较（argv[0] 解释器不参与比较——
    uv venv 重定向壳场景；身份绑定 runner entry + 参数，绝不只是"包含 run.py"）、
    creation time 防 PID recycle 比较
  - `ai_agent_framework/control.py`（新）：control.json task-owned artifact（§6A.7）——
    launch_id / task_id / workspace / launcher_pid / launcher_instance_id / started_at /
    expected_runner_entry / expected_command_line / runner_pid / runner_creation_time /
    cancel_requested / force_terminate_requested / superseded_by；原子写 + schema 验证；
    Framework-owned 变更经 per-task state.lock 串行化（owner protocol）；**不是
    terminal truth**
  - `ai_agent_framework/force_evidence.py`（新）：结构化 force termination evidence
    （§6B.17 / req 21）——task_id / launch_id / runner_pid / runner_creation_time /
    workspace / termination_requested_at+observed_at / exit status / verification
    result+checks / registry+control proof 路径；原子写；recovery input 非 terminal truth
  - `ai_agent_framework/runner.py`：Runner ownership handshake（§6A.6-4）——启动后校验
    control.json（launch_id / task_id / workspace / 非 superseded / 非 force-requested）
    并原子回写 runner_pid / runner_creation_time；mismatch → `HandshakeError`（fail
    safely：不接管 / 不执行 / 零 canonical 写）；`--launch-id` CLI 参数；无 control.json
    的 direct/legacy 调用路径保持兼容（无 ownership 契约）
  - `ai_agent_framework/finalize_cancelled.py`：**force recovery 正式开放**（005-A 的
    FORCE_RECOVERY_NOT_AVAILABLE 由 `ForceEvidenceError` 取代）——force 模式必须提供
    `--force-evidence`；state.lock 临界区内三方交叉验证（evidence ↔ control.json ↔
    Bridge launch registry：launch_id / task_id / runner 身份 / ownership verified /
    control.force_terminate_requested / 非 superseded / 时间序 sane）→ 才提交 CANCELLED
    （cancel_mode=force）；已有终态 + force → arbitration 优先 preserve（req 22）；
    伪造 / 过期 / 不匹配 → exit 6 安全失败，零 canonical 写
  - `ai_agent_framework/reconcile.py`：正式 CLI 入口 `python -m ai_agent_framework.reconcile`
    （Launcher wait thread 经子进程调用，§14.4 防侵入；幂等）
  - `bridge/launch_registry.py`（新）：Bridge persistent launch registry（§6B.11）——
    `~/.aaf-bridge/launches/<launch_id>.json`，PREPARED → RUNNING → EXITED（↘
    SUPERSEDED）；expected_command_line / launcher_instance_id / runner 身份 /
    launch_root_pid（uv venv 壳 kill 根）；同 task 新 launch supersede 旧 launch
  - `bridge/ownership.py`（新）：`verify_runner_ownership` 11 项校验（§6A.8/§6B.13：
    registry/control launch_id+task_id 交叉、workspace、目标 task_id、runner PID、
    live 存在、creation time、命令行、registry state、control 非 superseded、任务无
    终态）→ VERIFIED / STALE / UNCERTAIN；`reauthenticate_launch`（restart 三方验证；
    launcher_instance_id 不要求相同）
  - `bridge/launcher.py`：launch order（§6B.12：launch_id → registry PREPARED →
    control → Popen → PID/creation time → RUNNING → runner handshake 回写）；启动失败
    → registry EXITED + control start_failed（无 phantom RUNNING）；`force_eligible`
    （soft cancel 超时状态，不自动 kill）；`request_force_cancel`（ownership VERIFIED /
    REAUTHENTICATED + eligibility → taskkill /T /F（verified runner 树 + 壳）→ 结构化
    evidence → registry force 字段 + EXITED → Core finalizer CLI → canonical CANCELLED）；
    `recover_launches`（restart reauthentication + 本协议 launch 的 verified-force
    残留自动 finalizer 收敛——不扫描旧历史任务，RW-020 保持 OPEN）；canonical-aware
    wait thread（§6B.22：有 canonical 跟随 + 派生物不完整 → reconcile CLI；无 canonical
    + force 已请求 → 轮询/调 finalizer；否则 legacy 分类；registry EXITED；last_run
    镜像 canonical，非零 force 退出不判 FAILED）；launcher_instance_id 只作诊断
  - `bridge/config.py`：`force_cancel_soft_timeout`（默认 30s，§6A.11 阈值配置化）
  - `bridge/main.py`：Bridge 启动时 `recover_launches()`（只读恢复 force capability，
    不自动 force kill / 不改写 canonical；失败不阻断启动）
  - 测试：**509 passed**（461 基线 + 48 净新增，零下降；tests/test_phase_e_ownership.py
    40 项覆盖 req 32 A–AN 矩阵（launch_id 唯一 / control schema / registry PREPARED+
    RUNNING / handshake 正反 / PID+creation time+命令行存储 / ownership 11 项全矩阵 /
    restart reauth 正反 / launcher_instance_id 不要求相同 / normal-vs-force race
    真实跨进程 state.lock 仲裁 / fake+stale evidence 拒绝 / wait thread 跟随 canonical /
    last_run 镜像 / 无 UI Stop 按钮泄漏 / 无 project switching 泄漏 / Core 无进程控制
    静态断言）；tests/test_phase_e_force_e2e.py 7 项真实 Windows E2E（dummy runner
    进程树：verified force 全链路含 child 同树死亡 + sibling 存活 + evidence + CANCELLED
    全套产物 + last_run + registry EXITED；wrong ownership force refused 目标存活；
    restart reauth 正反；soft timeout 不自动 kill → 显式 force；reconciliation 恢复
    缺 run.json / REPORT；连跑 3 轮零 flake）；dummy runner 只杀测试自己的进程树，
    不碰真实 Hermes / WorkBuddy / Codex 会话（req 33）
  - 环境实证：本机 hermes venv `python.exe` 是 uv 重定向壳——Popen 直连子 ≠ 真实
    解释器（父子关系，pid 不同）；Launcher 采纳 runner 自报身份（registry 跟随
    control），命令行校验排除解释器 argv[0]，进程树终止先杀 runner 树再补杀壳；
    已写入 TROUBLESHOOTING 已知环境坑
  - 边界遵守：无 Status Window Stop UX / 无确认窗 / 无 project switching（Phase F）/
    无 RW-020 自动 orphan 修复（保持 OPEN）/ 无 RW-021/022/023/024 顺手修复；
    `.aaf/`、`scripts/start_bridge_hidden.vbs`、`AAF_TASK004_PROCESS_CHECK.txt` 未动；
    无 git clean
  - WorkBuddy / Codex 独立复核由本任务 route 阶段执行（verdict 见任务 REPORT.md；
    **未经两者通过不记录 E-Ownership / Force Cancel CLOSED**）
- **FIX-001（AAF-v0.4-TASK-005-B-FIX-001，2026-08-28）：Force Recovery Authority and
  Successful Termination Proof Closure**——关闭 Codex 对 005-B 的两个 blocking
  findings（① 任意 evidence.registry_path 可被当作 registry authority；② 非成功
  termination 也可授权 CANCELLED）：
  - `ai_agent_framework/finalize_cancelled.py`：`_validate_force_evidence` 重写——
    **canonical authority 推导**（req 1/2/3）：Core 经 `bridge.launch_registry`
    官方 path/schema/read contract 由 canonical Bridge registry root
    （`AAF_BRIDGE_DIR` / `~/.aaf-bridge`）+ launch_id 推导 registry 与 evidence
    路径；evidence 文件必须位于 `<registry_root>/<launch_id>.force-evidence.json`；
    `evidence.registry_path` / `control_path` 只作 proof，必须严格等于 canonical
    路径——任意外部 registry/evidence 路径不得授权 CANCELLED
    （fake/noncanonical registry + evidence 全拒）
  - **successful termination proof**（req 5）：`termination_exit_status == 0`
    （`force_evidence.SUCCESSFUL_TERMINATION_EXIT_STATUS`，Windows contract）才授权
    新的 CANCELLED；nonzero / missing / malformed → fail closed（Codex blocker 2
    闭合：原 `termination_exit_status=1` 合法 evidence 的测试已改为 exit 0）
  - **durable bridge evidence**（req 6）：Launcher 在调 finalizer 前把 force
    termination 关键事实（requested / observed / exit status / evidence path /
    verification result+checks）写入 Bridge-owned registry；Core 锁内逐项核对与
    evidence 一致（缺 durable 字段 = Bridge 在 evidence 写后、registry 更新前崩溃
    → fail closed，任务保持非终态）
  - **三方 identity 全量**（req 3/4/7）：task / launch / workspace / output /
    PID / creation time / expected entry / normalized command line / registry
    state（PREPARED / SUPERSEDED 拒绝，RUNNING / EXITED 可）全部一致；timestamp
    mismatch / verification mismatch / failed taskkill 全拒——仍在同一
    `state.lock` 临界区内完成（req 9，无 TOCTOU 回归）；已有终态 precedence 不变
    （req 8：force validation 只决定 non-terminal 是否允许新写 CANCELLED）
  - `bridge/launcher.py`：`_TASKKILL_OK_EXIT_CODES` 收紧为 `(0,)`（128 进程已不存在
    不再视为成功终止 → 失败路径 fail closed）；成功路径 registry 增写
    `force_termination_verification_result` / `force_termination_verification_checks`
  - `ai_agent_framework/force_evidence.py`：新增 `SUCCESSFUL_TERMINATION_EXIT_STATUS`
    contract 常量（Launcher 与 Core finalizer 共用单一成功定义）
  - 测试：**630 passed**（596 基线 + 34 新增，零下降；tests/test_phase_e_force_authority.py
    32 项 authority 正负矩阵：全一致正向 → CANCELLED；非 canonical evidence 路径 /
    registry_path proof 篡改 / canonical 路径 fake registry（垃圾 JSON + 他 launch
    的 schema-合法记录）/ registry 缺 durable 字段 / status 1·128·-1·999 / 缺失
    status / registry durable 六字段逐一不一致 / registry 侧 workspace·output_dir·
    PID·creation·entry·command 不一致 / control 侧 workspace·creation·command 不一致 /
    workspace 参数不一致 / PREPARED·SUPERSEDED / 已有终态 precedence / CLI 正负
    （真实子进程 + AAF_BRIDGE_DIR，exit 0 与 exit 6 两路径））；真实 Windows E2E
    新增 2 项反向/恢复路径（tests/test_phase_e_force_e2e.py：失败 taskkill →
    TERMINATION_FAILED fail closed 目标存活零 CANCELLED；verified termination 后
    Bridge 崩溃窗口（registry 仍 RUNNING + durable 字段已落盘）→ instance B
    recover_launches 兜底收敛 CANCELLED）；既有
    test_phase_e_ownership.py / test_phase_e_force_e2e.py 适配新契约（exit 0 +
    registry durable 字段断言 + AAF_BRIDGE_DIR 隔离，不再污染真实 ~/.aaf-bridge）；
    fix_002/003 对抗 worker 签名适配 workspace 透传
  - 行为契约变更：force recovery 现在要求 evidence 位于 canonical Bridge location、
    termination_exit_status == 0、registry 独立 durable 记录；128 不再视为成功终止
  - 边界遵守：无 Status Window Stop UX / 无 Phase F / 无 RW-020–024 顺手修复；
    `.aaf/`、`scripts/start_bridge_hidden.vbs`、`AAF_TASK004_PROCESS_CHECK.txt` 未动
  - Obsidian Handoff：PILOT → **VERIFIED**（本任务即“新 Planner 对话”，经
    CURRENT_HANDOFF + PROJECT_STATE 恢复项目状态成功；记录于本文件与
    AAF_MASTER_BACKLOG §5.4；未另开维护支线）
  - WorkBuddy / Codex 独立复核由本任务 route 阶段执行（verdict 见任务 REPORT.md；
    **未经两者通过不记 005-B CLOSED / E-Ownership / Force Cancel COMPLETE**）
- 真实软取消 E2E：Scenario 1（Hermes 前 cancel → Hermes 不启动 → CANCELLED 全套产物）PASS；
  Scenario 2（Hermes 完成 → WorkBuddy 前 cancel → Hermes result 保留 → CANCELLED）PASS；
  真实 run.py CLI 子进程 + finalize_cancelled CLI 幂等 PASS
- 边界遵守：无 Force Kill（taskkill 零实现）、无 Bridge launch registry、无 Status Window Stop 按钮、
  RW-020/021/022/023/024 未自动修复、历史 TASK-004 task.json 未修改、用户本地 helper
  （scripts/start_bridge_hidden.vbs / AAF_TASK004_PROCESS_CHECK.txt / .aaf/）未动
- WorkBuddy / Codex：由本任务 route 阶段执行（verdict 见任务 REPORT.md）
- Next Phase Step（历史记录，superseded）：**AAF-v0.4-TASK-005-C — Phase E Status Window
  Cancel UX + Real Windows E2E Closure**（005-B 交付时的原候选；005-B 已执行并被 Codex
  REQUEST_CHANGE → 该候选被 superseded，不再作为当前 Next Step；005-B-FIX-001 关闭 +
  005-C 全部完成后 Phase E 才可标 COMPLETE）
- **当前唯一 Next Step（当前状态）**：**AAF-v0.4-TASK-005-B-FIX-001**（005-B 的 pending
  Codex blocker；见下方 Maintenance 段落；FIX-001 关闭前不进入 005-C）
- **TASK-005-C（AAF-v0.4-TASK-005-C，2026-08-28）：Phase E Status Window Cancel UX +
  Real Windows E2E Closure（Phase E 最后一块；交付后 Phase E 正式标记 COMPLETE）**：
  - `bridge/status_window.py`：CancelUi 状态机（UI/control 态，§6A.3 最小中间状态——
    **绝不进入 task.json 合法 status**）：正在运行 / 请求停止（停止请求已发送，正在
    等待任务安全退出）/ 正在取消（软取消超时仍未退出 → 提供 [强制停止]）/ 已取消 /
    已完成（曾有请求 → 「任务已先完成」，canonical winner，req 8）/ 无法安全停止 /
    无法确认（不可验证 → 不提供 Stop，req 1）；`derive_cancel_ui` 纯函数只依赖
    canonical artifacts（task.json / cancel.request / registry / force eligibility
    backend），不依赖 UI 内存（req 9）；`collect_cancel_ui` 从真实 artifacts 收集 +
    force eligible 时再经 `launcher.ownership_status` 确认 VERIFIED/REAUTHENTICATED
    （UNCERTAIN / STALE / mismatch → fail closed 不提供 Force，req 6）；快照新增
    `cancel_ui` 字段；窗口新增「停止状态」行 + [停止当前任务]（soft cancel，req 3）+
    [强制停止]（仅 eligible 时显示，req 6；点击经回调转发，窗口零写 canonical / 零
    taskkill——req 7，静态 AST 断言保护）
  - `bridge/ui.py`：中文停止确认窗（§12.3 [确认停止] [取消]）+ 强制停止红色风险确认窗
    （[确认强制停止] [取消]，二次确认，req 4/5）
  - `bridge/main.py`：`_request_stop`（只允许当前 RUNNING 任务；确认后经 Core-owned
    cancel 模块写 cancel.request——state.lock 序列化；绝不直接写 SUCCESS/FAILED/
    WAITING/CANCELLED）+ `_request_force_stop`（ask_force_stop 二次确认后才调
    launcher.request_force_cancel——不绕过 ownership/registry/evidence/finalizer，
    req 5/7）+ `_force_refusal_cn`（拒绝原因 → 中文主文案，req 10）；StatusWindowController
    新回调接线
  - `tests/fixtures/dummy_runner.py`：cancel-aware 模式（检查点语义 + cancel.gate 门闩
    确定性收敛，TASK-005-C UI E2E 专用）
  - 测试：**666 passed**（630 基线 + 36 净新增，零下降；tests/test_phase_e_cancel_ui.py
    29 项：状态机全矩阵 / Stop 入口守卫（terminal·无任务·不可验证）/ soft-cancel-first
    真实写入断言（只写 cancel.request，零 canonical）/ soft timeout 不自动 kill /
    force 二次确认（confirm=False 零终止调用）/ eligibility fail closed（backend
    异常·ownership 未通过）/ UI Authority 静态 AST 边界 / canonical winner race /
    artifacts 恢复（两独立会话同 artifacts 同状态）/ 中文文案 / GUI 真实 Tk 渲染
    （按钮可用性·Force 显隐·回调转发）；tests/test_phase_e_cancel_ui_e2e.py 7 项真实
    Windows E2E（req 11 A–G：A 运行中软取消→CANCELLED+后续 agent 不启动；
    B 阶段间软取消→结果保留→CANCELLED；C 正常完成胜出→SUCCESS 保持+late cancel
    absorbed；D 软超时→不自动 kill→force option；E 二次确认后 verified force→owned
    进程树终止+evidence+CANCELLED+unrelated sibling 存活；F ownership 篡改→force
    refused→目标存活；G instance B 重启→artifacts 恢复+REAUTHENTICATED force 可用）；
    连跑 3 轮零 flake）
  - 既有测试适配：test_phase_e_ownership.py test_am 从「无 Stop 按钮泄漏」更新为
    「005-C 交付后 authority 边界」（status_window 有按钮但零直接 force/terminal 写；
    Tray 菜单项不在 005-C 范围）
  - 行为契约：CANCEL_REQUESTED / CANCELLING 只属 UI/control 态（§6A.3），task.json
    VALID_STATUSES 不变；停止动作永远先 soft cancel；soft timeout 永不自动 force kill
  - 边界遵守：无 Phase F（项目切换 / Duplicate UX）/ 无 RW-020–024 顺手修复 / 无
    Tray 停止菜单项（设计 §12.2 Tray 停止项留待后续阶段，已登记为范围边界）；`.aaf/`
    真实任务目录未动（本任务运行目录由 Framework 自己管理）
  - route 阶段：WorkBuddy / Codex 独立复核按项目惯例由 route 执行（verdict 记录于
    任务 REPORT.md；若 blocking 则按惯例开 FIX）
  - 005-C-FIX-001（2026-08-28）：关闭 Codex 唯一 timezone blocker——canonical
    UTC/aware elapsed contract 统一 cancel elapsed 计算（合法 offset-aware 与
    legacy naive 均兼容，malformed fail closed）；22 项回归，688 passed——
    详见上方 0.2 Phase E 段落
- **Phase E 收口结论（2026-08-28）**：E-Core / Soft Cancel（005-A + FIX-001/002/003）+
  E-Ownership / Force Cancel（005-B + 005-B-FIX-001）+ Status Window Cancel UX +
  Real Windows E2E Closure（005-C）+ Cancel Timestamp Timezone Compatibility Fix
  （005-C-FIX-001：canonical UTC/aware elapsed contract 关闭 Codex 唯一 timezone
  blocker——688 passed，666 基线 + 22 新增零下降）全部交付 → **Phase E = COMPLETE；
  Phase F = NOT STARTED；Next Step = Planner Phase E Stage Retrospective（不自动
  进入 Phase F）**

### 0.2 Phase F — Project Switching / Duplicate Task UX（IMPLEMENTATION DELIVERED，2026-08-28）

- **任务**：AAF-v0.4-TASK-006（RW-003 Project Switching + RW-016 Duplicate Task UX，
  设计 §9/§10 全量落地；冻结设计未重新设计）
- **实现**：
  - `bridge/workspace.py`（新）——TASK Workspace 校验与分类纯函数：check_workspace
    （fail closed：空/malformed/控制字符/非绝对路径/不存在/非目录/无权限/Bridge 私有
    目录安全校验）；classify_workspace → SAME / KNOWN / UNKNOWN / INVALID
  - `bridge/duplicate.py`（新）——duplicate 状态卡片数据：running（registry 活跃
    launch / launcher 当前任务）/ completed（终态 SUCCESS/WAITING/FAILED/CANCELLED）/
    abnormal（残留 RUNNING/CREATED）/ unknown（无 task.json）；REPORT 路径
    task.json.report_path → task_archive.find_report_path 归档兜底；最近活动 =
    产物最大 mtime；判定基础 = canonical TASK.md 落盘路径存在（与 save_task 同一
    判定，未放宽 execution authority）
  - `bridge/intake.py`（新）——提交流程决策（纯逻辑）：plan_submission（只读）+
    apply_submission（确认后切换持久化 + 落盘）；决策矩阵：SAME 无额外确认 /
    KNOWN confirm_switch / UNKNOWN confirm_unknown（fail-safe）/ INVALID reject /
    RUNNING 拒绝跨 workspace 切换 / duplicate running 拒绝第二 runner /
    completed/abnormal/unknown 拒绝 + 卡片（需新 Task ID，不另造 rerun 架构）
  - `bridge/config.py`——recent_projects（上限 5，last_used 倒序）+ update_project
    （唯一切换持久化入口）+ known_workspaces / same_workspace / normalize_workspace
  - `bridge/ui.py`——「切换项目确认」窗（当前/目标项目 + Workspace + Task ID + 将修改
    AAF Bridge 项目设置 + 陌生路径警示）与「任务已存在」状态卡片（查看状态 / 打开
    REPORT / 关闭），全部中文优先（技术状态值保留英文原值）
  - `bridge/main.py`——_process_clipboard 接入 intake 流程（决策 → UI 确认 → apply →
    launch）；duplicate 卡片接线 [查看状态]（复用状态窗口）/ [打开 REPORT]（os.startfile）
  - `tests/fixtures/run_dry.py`（新）——真实 run.py 的 dry-run 包装（真实 runner
    子进程 + 真实文件契约，零 Agent 依赖；Phase E 同款确定性约束）
- **测试**：760 passed（688 基线 + 72 新增零下降）——tests/test_phase_f_workspace.py
  （18 项）、test_phase_f_duplicate.py（20 项）、test_phase_f_intake.py（25 项）、
  test_phase_f_e2e.py（9 项真实 Windows E2E A–I：同 workspace 无额外确认执行 /
  已知切换并执行 / 拒绝切换零写入 / 陌生 workspace 确认前不执行 / invalid fail
  closed / RUNNING 拒绝切换与第二启动 / duplicate RUNNING 不启动第二 runner /
  duplicate terminal 不覆盖 artifacts + 清晰提示 / restart 恢复 current project
  + duplicate protection）
- **Backlog 收口**（仅状态校正，不重新开发）：RW-003 OPEN → SOLVED；RW-016 OPEN →
  SOLVED；RW-006 OPEN → SOLVED（按 Phase C/D/E/F 真实交付证据校正）；RW-009 /
  RW-014 状态核对保持 PARTIAL（无新交付）
- **边界遵守**：未实现 autostart / parser compatibility / orphan-dead runner
  recovery / final status aggregation / hotkey self-heal / completion notification
  continuity / Context Compaction redesign / 大型项目 dashboard（TASK req 16）；
  未放宽 duplicate protection / execution authority；未改写 Task ID / Workspace /
  canonical terminal / 历史 artifacts（req 12）；未另造 rerun 架构（沿用既有
  `--resume-from` CLI 边界）
- **结论**：Phase F 实现 + 测试 + 真实 Windows E2E 全部完成；**正式 Phase F =
  COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 审查后由 Planner 确认（本任务不
  自行宣布）**；Next Step = Planner v0.4 Remaining-Issues Retrospective →
  Runtime Integrity batch planning（不自动进入最终封装）

#### FIX-001 — Atomic Config Persistence + Real UX Closure（2026-08-28，关闭 Codex 两个 blocker）

- **背景**：Codex REQUEST_CHANGE（① save_config 用 `Path.write_text` 直写正式
  config.json，非报告所称 tmp + os.replace，中断可产生截断配置破坏重启恢复；
  ② WorkBuddy 承认独立 UX/safety 验证未执行，且现有 E2E 直接调用
  plan/apply/launcher，不能替代真实确认窗/状态卡片 UX 证据）
- **修复 ① 原子持久化**（`bridge/config.py`）：
  - `save_config` 改为统一 atomic contract（正式 config.json 唯一写入路径）：
    同目录 `.config.json.tmp-<pid>-<seq>-<monotonic>` → `open(...)` 写 →
    `flush()` + `os.fsync()` → close 完成后 `os.replace(tmp, 正式路径)`
  - 失败语义：tmp 写失败 / os.replace 失败 / json 序列化异常 → 统一清理 tmp 并
    抛 `ConfigError`（不静默声称切换成功）；正式 config 字节级保留、不残留半截
    正式文件、不残留 tmp；`update_project` 复用同一函数（无旁路特殊实现）
  - 新增 11 项单测（tests/test_phase_f_fix_001.py）：atomic success（spy
    os.replace 验证 tmp→正式）+ tmp 写失败 + replace 失败 + replace 前异常 +
    旧 config 保留 + update_project 同契约 + 成功切换 restart 恢复 + 失败切换
    restart 旧配置可加载 + tmp 零残留 + 完整 JSON 字段
- **修复 ② 真实 UX 证据**（tests/test_phase_f_fix_001_ui.py，8 项）：
  - 确定性 UI harness 驱动**真实** UI 接线：真实 tk.Tk root + 真实剪贴板往返 +
    真实 `Bridge._handle_hotkey → _process_clipboard` + 真实「切换项目确认」窗 /
    「任务已存在」状态卡片（真实 Toplevel；harness 读取窗口 Label 内容树断言
    显示正确，再 invoke 真实按钮）；仅 patch messagebox（模态阻塞）与
    CONFIG_PATH / AAF_BRIDGE_DIR（隔离）
  - 覆盖：A Known switch 确认窗内容正确 + 确认后切换并执行（真实 run_dry
    子进程）；B 拒绝切换零写入（config 字节级不变 + 无 TASK.md + launcher IDLE）；
    C Unknown 首次出现警示文案 + 确认前不执行 + 确认后才执行；D Invalid 明确
    拒绝原因 + 无确认窗无绕过；E Duplicate RUNNING 卡片「执行中（RUNNING）」+
    registry 无第二 launch；F Duplicate terminal 卡片「已完成（SUCCESS）」+
    REPORT 路径 + artifacts 哈希不变；G RUNNING 跨 workspace 拒绝（「当前任务
    正在运行」）+ 当前任务 registry 不变；H restart 后 current project 恢复 +
    duplicate protection 仍有效
  - **真实 UI 验收发现并修复死按钮**：duplicate 卡片 [打开 REPORT] 的 `_safe`
    包装器零参调用 `on_open_report(report_path)` → TypeError 被吞 → 按钮无效果；
    改为按钮命令以闭包捕获 `info.report_path`（`bridge/ui.py`）；新增断言
    `bridge.report_opens == [REPORT 路径]` 证明接线真实生效
  - UX evidence：9 组真实窗口内容树 + 测试输出存
    `.aaf/AAF-v0.4-TASK-006-FIX-001/UX_EVIDENCE.md`（可复核，非纯函数调用）
- **测试**：780 passed（760 基线 + 20 新增：11 原子 + 9 真实 UI），全量两次连跑
  零失败；Phase F targeted 92 项（72 原有 + 20 新增）全过；既有 Phase F tests
  未删除未修改
- **Backlog / 状态**：RW-003 / RW-016 SOLVED 状态按实际证据保持（FIX-001 为
  Codex blocker 关闭轮，不改写 backlog 判定）；Phase F 正式 COMPLETE 仍留待
  WorkBuddy 独立验证 + Codex 复审后由 Planner 确认；Next Step 保持 Planner
  Phase F / v0.4 Remaining-Issues Retrospective → Runtime Integrity planning
  （未自动进入 Runtime Integrity batch / 最终封装）

### 0.2 Maintenance — Context Compaction / Stage Packet Protocol（AAF-MAINT-CONTEXT-001，2026-08-28）

- 类型：维护任务（非 Phase 任务）；Phase E 状态未被改变（IN PROGRESS 保持）；
  **当前唯一 Next Step = AAF-v0.4-TASK-005-B-FIX-001**（005-B 的 pending Codex blocker；
  本任务不实现其 force-recovery blocker；FIX-001 关闭前不进入 005-C）
- 解决的问题（正式登记 CTX-002，见 AAF_MASTER_BACKLOG.md）：TASK / stage prompt /
  REPORT 层层全文叠加导致 Context 膨胀——Hermes 完成后 WorkBuddy 接收 Hermes narrative
  全文，Codex 再叠加 Hermes + WorkBuddy 全文（eager full-content chaining）
- 交付内容：
  - **Anti-Bloat Policy**：`docs/internal/AAF_TASK_EXECUTION_POLICY.md`（durable
    Framework policy：TASK = current delta；引用优先；同语义不重复；FIX 只写
    parent blocker + delta；长度增加需新信息依据；摘要只导航、artifacts 才是真相）
  - **Compact TASK Schema**：`templates/TASK.md` 正式最小结构
    （Task ID / Name / Workspace / Objective / Context / Source of Truth /
    Requirements / Scope / Out of Scope / Validation / Acceptance / Route Hint）；
    `task_validation.py` OPTIONAL_FIELDS 增加 Context / Source of Truth /
    Validation / Out of Scope / Scope / Out of Scope（旧必填集不变，向后兼容）
  - **Semantic Coverage Guard**：`context_packet.verify_semantic_coverage`——
    unique requirement / safety invariant / acceptance semantics 覆盖率检查
    （压缩是去重，不是删约束）
  - **Stage Context Packet 协议**（`adapters.py`）：WorkBuddy 只接收 TASK 引用 +
    Hermes 结构化摘要 + changed files/commit/evidence 路径；Codex 再叠加 WorkBuddy
    结构化 verdict；上游 narrative 全文按需读取；独立验证指令保留；引用缺失 →
    显式 FALLBACK_EMBEDDED 全文或 FAIL（不静默缺上下文）
  - **Structured Stage Results**：`<agent>_result.json`（agent / status / verdict /
    blocking_rework / commit / tests / changed_files / evidence_paths / findings /
    warnings + summary 导航字段）；框架只写确定性可验证事实，不猜测 LLM 语义
  - **Context Manifest**：`context_manifest.json`（TASK path+hash、stage result
    paths+hashes、workspace、HEAD、prompt 指标）；`check_references` 完整性检查
    （文件变化 → hash 不匹配检出）
  - **REPORT De-duplication**（`report.py`）：`## Original Task` 全文 → `## Task
    Reference`（Task ID / Path / Hash）；Agent Results = 摘要 + 完整结果路径；
    无引用信息的 legacy 调用方保持旧格式
  - **Context Size 可观测性**：每 stage prompt chars/bytes + embedded/referenced
    artifact counts 写入 manifest；测量证据（可复算，固定 workspace 路径 fixture）：
    old full-chain 26,211 chars → new packet 5,379 chars（-79.5%，embedded=0，
    referenced=1/2；复算来源：tests/test_context_integrity.py
    test_context_size_fixture_exact_numbers；历史 25,609→3,301 / 26,191→3,585
    为 superseded 初算值，已以可复算值取代）
  - **Backward Compatibility**：旧目录无 `<agent>_result.json` → 自动 legacy
    全文嵌入 fallback；旧 REPORT 无 Task Reference 参数保持原格式
  - **Anti-Regression 测试**：`tests/test_context_compaction.py` 23 项（req 11
    全项 + req 12 guard：REPORT 不恢复 full TASK 嵌入 / prompt builder 不恢复
    无条件全文拼接 / Policy 存在且被模板引用）
- 测试：**532 passed**（509 基线 + 23 新增，零下降）
- 边界遵守：Phase E force-recovery blocker 未实现；Cancel UI / Phase F /
  RW-020–024 产品修复 / Agent model-provider 未动；`.aaf/` 历史产物未动；
  005-B-FIX-001 技术结论未修改
- WorkBuddy / Codex 独立复核由本任务 route 阶段执行（verdict 见任务 REPORT.md）
- **AAF-MAINT-CONTEXT-001-FIX-001（2026-08-28，docs-only）**：关闭 Codex 唯一 blocker
  （PROJECT_STATE.md 当前 Next Step 自相矛盾）——统一当前状态入口：
  - 当前唯一 Next Step = **AAF-v0.4-TASK-005-B-FIX-001**（见本段落顶部；Phase E 内旧的
    「Next Phase Step（唯一）= 005-C」与 §0.5 旧 v0.4 快照已明确标 historical /
    superseded，不再表现为当前 Next Step）
  - Phase E 保持 IN PROGRESS（005-B 已执行：WorkBuddy PASS / Codex REQUEST_CHANGE →
    pending blocker 005-B-FIX-001）；Phase F 保持 NOT STARTED
  - Context-size 证据数字统一为可复算值：old full-chain **26,211 chars** → new packet
    **5,824 chars**（**-77.8%**，embedded=0，referenced=1/2；复算来源
    tests/test_context_integrity.py test_context_size_fixture_exact_numbers；
    FIX-002 因 reviewer 契约新增 blocking_provenance 字段说明，5,379 → 5,824）；
    AAF_MASTER_BACKLOG.md CTX-002 同步
  - session_continuity 秒级时钟 flake（tests/test_session_continuity.py）本任务不处理，
    已登记 **RW-025**（见 AAF_MASTER_BACKLOG.md，后续维护项）
  - 未改任何 Context Packet / prompt / report protocol 代码（docs-only）
- **AAF-MAINT-CONTEXT-001-FIX-002（2026-08-28，代码 + docs + tests）**：关闭 Codex
  三个 blocker（TASK path/hash 引用不稳定 / Remote Sync 误报 / structured
  findings-warnings 与 narrative 不一致）——补齐完整性协议（不重做 Context
  Compaction）：
  - **Immutable Task Snapshot（Req 1/2）**：Runner 每次执行开始时写入
    `<output_dir>/TASK.snapshot.md`（内容 = 实际执行 TASK）；Task Reference /
    task hash / context_manifest / WorkBuddy/Codex packet / REPORT 统一引用
    snapshot；active/archive TASK 后续变化不影响 execution integrity；
    Hash Single Source：hash 只从 snapshot 计算一次并全程复用
    （`runner.py` / `reconcile.py` snapshot-aware；`check_references` 检出
    tampered snapshot）
  - **Remote Sync Truth（Req 4/5）**：`context_packet.remote_sync_state()` 区分
    Commit Sync（SYNCED/UNSYNCED）与 Tracked Working Tree（CLEAN/DIRTY，
    `-uall` 逐文件 + 预允许 untracked artifacts：`.aaf/`、
    `scripts/start_bridge_hidden.vbs`、`AAF_TASK004_PROCESS_CHECK.txt`）；
    Task Remote Sync 仅当两者都满足才 SYNCED；REPORT 新增 `## Remote Sync` 段；
    `commit_changed:false` 不再作为同步证据
  - **Structured Result Completeness（Req 6/7）**：`<agent>_result.json` 增加
    `summary_complete` / `structured_summary_status`；findings/warnings 未提取时
    为 `null`（UNKNOWN）而非 `[]`（unknown ≠ empty）；Agent 答复末尾
    `AAF_STRUCTURED_RESULT_BEGIN/END` JSON 块契约（WorkBuddy/Codex: verdict /
    blocking_rework / findings / warnings；Hermes: status / changed_files /
    commit / warnings），Framework 只接受 schema-validated 结构化块
  - **Narrative/JSON 一致性 guard（Req 9）**：structured 声明 complete 时，
    narrative 显式 warning（W1:/WARNING:/⚠）与 REQUEST_CHANGE/FAIL（无通过结论）
    不得在 JSON 消失；违反 → CONSISTENCY_VIOLATION + summary_complete=false
    （WorkBuddy W1/W2/W3 → warnings=[] 的真实模式已被测试覆盖）
  - **No Silent Information Loss（Req 8）**：summary 缺失/损坏/不完整 → 下游
    prompt 显式 PARTIAL/UNKNOWN + narrative 路径指引；缺失 result.json 的 legacy
    目录 → 全文 fallback 之上显式 FALLBACK_EMBEDDED 标注
  - **Measurement Evidence（Req 11）**：context-size 数字统一为可复算 fixture
    结果 26,211 → 5,379（**-79.5%**，约 80% reduction），不再保留冲突数字
  - 测试：**554 passed**（532 基线 + 22 新增 tests/test_context_integrity.py：
    snapshot hash 精确匹配 / active 变化不影响 / tampered 检出 / 下游引用同一
    snapshot / tracked-dirty Remote Sync / 预允许 untracked / structured schema /
    W1-W3 一致性 / 缺失 fallback / 真实 WorkBuddy→Codex packet / 精确测量数字）
  - 边界遵守：Phase E force-recovery blocker / Cancel UI / Phase F / RW-020–024 /
    session continuity clock flake 均未处理
  - 本轮 tracked docs（PROJECT_STATE.md / AAF_MASTER_BACKLOG.md /
    AAF_TASK_EXECUTION_POLICY.md）已 commit + push（Req 5 Closure Evidence）

### 0.2 v0.3 历史状态（CLOSED，保留）

``` text
Version: v0.3
Core Implementation: COMPLETE
Core Acceptance: PASS
Lifecycle: CLOSED（v0.3 已收官；不因 v0.4 开发重新定义 v0.3）

v0.3 三大核心方向：
1. Task Automation     ✅ COMPLETE（000-A/B/C + 001 Validation + 002 Lifecycle + 003 Archive）
2. Session Continuity  ✅ COMPLETE（004）
3. Project Boundary    ✅ COMPLETE（005）

v0.3 closure: WorkBuddy APPROVE + Codex milestone audit APPROVE + Blocking=0
```

### 0.1 Maintenance Period（当前维护/观察期）

v0.3 已 CLOSED，当前为维护 / 观察期。此期间只做：

- 文档、登记、恢复资产维护（如本任务）；
- 已确认真实问题的 hotfix（须独立记录，不重开 v0.3 Scope）。
- AAF-DESIGN-001（2026-08-27）：**Desktop Shell design completed / implementation not started**。设计规格见 `docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md`（仅设计，无产品功能实现；是否纳入 v0.4 由 Planner 决策）。

**不**做：新功能实现；v0.4 规划以外的工作；自动进入下一 TASK。

### 0.2 近期 Hotfix 与真实事故记录

| 事项 | 状态 | 记录 |
|---|---|---|
| Agent 子进程黑色 console 窗口抑制 hotfix | COMPLETE | commit **44ecfa8**（AAF-v0.4-TASK-002-FIX-003：Windows 下 Hermes / WorkBuddy / Codex 子进程统一 CREATE_NO_WINDOW 无控制台；共享 helper `ai_agent_framework/subprocess_utils.py`，Bridge launcher 同类修正；239 passed；真实 Windows 探针 Hermes/WorkBuddy/Codex 均无 console 窗口） |
| Codex command discovery hotfix | COMPLETE | commit **7cbf594**（Codex 升级 hash 目录变化导致 discovery 失败 → registry PATH 优先 + hash 目录 fallback；198 passed） |
| Router local readonly constraint hotfix | COMPLETE | commit **457df93**（execution intent 与局部限制区分；206 passed；WorkBuddy APPROVE + Codex APPROVE） |
| AAF-MAINT-001 routing incident | 已登记 | 局部范围限制被误判为任务级 review 模式 → Hermes 被跳过；Root cause 与修复见 `AAF-HOTFIX-ROUTER-READONLY.md`；事故登记 RW-011 |
| AAF-MAINT-001-FIX-001 self-triggering routing incident | 已登记 | 为描述前一次事故引用 Router 分类短语 → 全文信号匹配再次触发 review route → Hermes 第二次被跳过；Runtime Diagnose 排除 stale route / wrong import / truncation，根因为 self-triggering reference trap；事故登记 RW-013 |

两个事故任务证据保留：

``` text
.aaf/AAF-MAINT-001/
.aaf/AAF-MAINT-001-FIX-001/
```

不删除、不覆盖。

### 0.3 Current Usability Gaps（当前已知可用性缺口）

详见 `docs/internal/AAF_MASTER_BACKLOG.md`（完整登记），摘要：

- Bridge 无开机自动启动（RW-004；Phase B 已提供 pythonw 后台 + Tray skeleton，autostart 仍未实现）；
- 项目切换需人工改 config（RW-003）；
- hotkey listener 偶发失活已实现自动自恢复（RW-012 = SOLVED for v0.4：Bridge 唯一 owner 有界 backoff，失败经 Tray/状态窗口可见；FIX-001 后 registration/unregistration 归 listener 线程（thread-owned unregister）+ 显式 stop 契约（有界 join）+ stop-before-replace，one-listener invariant 有真实线程级证据；FIX-002 后 stop 超时保留 ownership reference（_pending_stop）、跨 recovery cycle 不启动 replacement、delayed exit 后恰一 replacement、wait_ready 返回值参与 start success 判定、alive != ready；FIX-003 后 delayed-exit cleanup 为 lifecycle lock 内原子单元（锁内 identity 重验证 + exhausted recovery 在真实 ownership release 后 rearm 一次新有界 epoch）；FIX-004 后 delayed-exit recovery 收敛为单一锁内 lifecycle transition（_run_lifecycle_transition：cleanup→rearm→eligibility→reserve→exactly one replacement 同一 _lifecycle_lock 临界区，_apply_hotkey_locked 为唯一 listener replace/start authority，无 exposed ownership gap、无 per-poll rearm、无递归锁死、stale cleanup 绝不清 replacement））；
- TASK parser 换行格式兼容性已修复（RW-008 = SOLVED for v0.4 正式 Compact TASK contract；U+3000 / 富文本 / 旧别名仅 legacy observation，不扩张 parser）；
- 无运行时状态可视化（RW-006）；Phase C（v0.4）已交付只读状态窗口（当前项目 / 任务 / 阶段 / Agent / 结果），
  剩余缺口：进度估算 / stuck 提示 / 停止入口（Phase D/E）；
- 重复提交 Task 仅提示 TASK_ALREADY_EXISTS，无状态 / 查看 / REPORT 入口（RW-016）；
- 无当前任务 Stop / Cancel 入口（RW-014）；
- 无统一桌面 UI；未来 Chinese-first（RW-015）；Phase C（v0.4）已交付中文优先的状态窗口与弹窗文案；
- 无会话过长提醒/承接 UX（CTX-001）；
- 环境 / 仓库观察项：.aaf ignore 一致性、Git push 代理可靠性、Agent review 证据一致性（RW-017～RW-019，详见 Master Backlog，仅登记不实现）。

### 0.4 Source / Mirror / Recovery Policy（长期政策）

``` text
Repository（GitHub / local repo）:
  authoritative source —— 唯一权威长期知识源

ChatGPT（Project / conversation）:
  planner / discussion interface —— 规划和协作界面，
  不能作为唯一长期知识来源

Obsidian（D:\AdyAI\Obsidian-Vault\AI Agent Framework\）:
  human-readable mirror and recovery layer —— MIRROR ONLY，
  非独立权威版本；不开发自动同步程序或 Obsidian plugin
```

ChatGPT disaster recovery principle（详见 RW-009）：

``` text
GitHub / local repo → README → PROJECT_STATE
→ AAF_MASTER_BACKLOG → latest closing handoff
→ 创建新的 ChatGPT Project / Planner conversation → 继续维护
```

即使旧 ChatGPT Project 或 conversation 不存在，Framework 仍能恢复到
可继续升级的状态。

### 0.5 Future Planning Rule（未来规划规则）

``` text
Before planning new AAF work:
FIRST READ:
docs/internal/AAF_MASTER_BACKLOG.md
```

以后任何被正式确认"稍后处理"的问题，**必须进入 Master Backlog 才算
长期登记完成**。

（历史快照 — superseded：以下为 005-B 交付前的 v0.4 状态记录，保留不删除；
当前状态以顶部「0. v0.4 Current Status」块为准；当前唯一 Next Step =
AAF-v0.4-TASK-005-B-FIX-001，Phase E 仍 IN PROGRESS，Phase F 仍 NOT STARTED）

v0.4 IN PROGRESS — Phase A/B/C/D COMPLETE；Phase E IN PROGRESS（E-Core / Soft Cancel COMPLETE，由 AAF-v0.4-TASK-005-A 交付；005-A-FIX-001 已关闭 Codex 两个 blocking safety defects（late non-terminal update 覆盖 terminal / recovery finalizer 无 evidence+identity 验证）；005-A-FIX-002 已实现 recovery 单一 state.lock 原子协议（identity+evidence+arbitration+commit 同一临界区，关闭遗留 recovery TOCTOU）；005-A-FIX-003 已实现 cancel.request mutation 锁序列化（write/consume 与 terminal writers 共享同一 state.lock，关闭 evidence replacement race）+ forced-order 握手修正（T_LOCKED 在 acquire 后发出）；各 FIX 验证结果见任务 REPORT，未经 WorkBuddy/Codex 通过不记 CLOSED；剩余 TASK-005-B + TASK-005-C 未交付，Phase E 不得标 COMPLETE）；Phase F NOT STARTED，不得自动启动；Next Phase Step = AAF-v0.4-TASK-005-B（Phase E Process Ownership + Force Cancel + Recovery Integration；superseded 历史记录，005-B 已执行，当前唯一 Next Step 见顶部）。

------------------------------------------------------------------------

## 1. Historical Status（v0.2 及更早，保留不删除）

## 1. Current Status

``` text
Version: v0.2
Lifecycle: v0.2 CLOSED

MVP Core Loop Validation: PASSED
Regression Baseline: 52 passed

Public Release: COMPLETED
Repository: Public — https://github.com/adyfox85-wq/ai-agent-framework
Release: v0.2.0-rc1 (2026-08-25, prerelease)

v0.2 Final Status:
- Migration Completed
- Validation Completed
- GitHub Repository Completed
- Open Source Sanitization Completed
- Public Release Completed

Latest Production Validation:
TASK-010
Current Status: SUCCESS
WorkBuddy: PASS_WITH_WARNING
Codex: APPROVE
Unresolved Issues: None identified.
```

当前结论：

> AI Agent Framework v0.2 自动化 MVP
> 核心闭环已经通过真实项目连续试跑验证，
> 并已完成正式化迁移、GitHub 公开仓库上线与 v0.2.0-rc1 Release。

当前阶段：

``` text
v0.2 收官
→ Freeze Preparation ✅
→ 正式化整理 ✅
→ GitHub Repositoryization ✅
→ Open Source Sanitization ✅
→ Public Release ✅
→ v0.2 CLOSED（当前）
```

------------------------------------------------------------------------

## 2. Current Architecture

固定角色：

``` text
Planner: ChatGPT
Router: AI Agent Framework
Executor: Hermes
Reviewer / Validator: WorkBuddy (CodeBuddy)
Milestone / Code Reviewer: Codex
Result Carrier: REPORT.md
```

正式执行链：

``` text
需求 / 产品规划
→ Planner
→ TASK.md
→ Framework Router
→ Hermes（需要执行时）
→ WorkBuddy
→ Codex（按任务需要）
→ REPORT.md
→ Planner
```

TASK.md 是 Framework 的唯一正式执行入口。

------------------------------------------------------------------------

## 3. Current Working Locations

### Verified prototype（冻结参考）

``` text
<PROJECT_ROOT>-prototype
```

这是 v0.2 真实试跑、修复和 52 项测试验证的原始工作源。
已完成正式迁移（AAF-TASK-004）后保持完整冻结，不再作为正式入口更新。

### Formal Framework directory（唯一正式入口）

``` text
<PROJECT_ROOT>
```

状态：v0.2 已完成正式迁移与正式验证（AAF-TASK-004 / AAF-TASK-005）。

- 核心代码、测试、模板、文档已迁移；
- 52 passed 已在正式目录验证通过；
- TASK → Router → Agent → REPORT 真实闭环已验证；
- WorkBuddy 独立 review：FORMAL_REPOSITORY_OK；
- **本目录是 v0.2 唯一正式入口。**

### Current production-use project

``` text
<BUSINESS_PROJECT>
```

该项目已经完成 TASK-001 ～ TASK-010 及多个 FIX TASK 的真实 Framework
试跑。

Framework 收官不得随意修改业务项目代码。

禁止修改：

``` text
<BUSINESS_PROJECT>\workbuddy_skills\skills\
```

------------------------------------------------------------------------

## 4. Validation Baseline

当前已知回归基线：

``` text
52 passed
```

已经真实验证：

-   TASK → Router → Agent chain → REPORT；
-   Hermes execution；
-   WorkBuddy 独立复核；
-   Codex APPROVE / REQUEST_CHANGE；
-   SUCCESS / WAITING 状态；
-   FIX TASK；
-   stdin 长 prompt；
-   Windows WinError 206 修复；
-   workspace 绝对路径；
-   CodeBuddy 空输出保护；
-   Router execution / review / readonly 边界；
-   resume；
-   状态聚合；
-   Unresolved Issues 聚合；
-   dry-run Route 验证。

TASK-010 在没有新增 Framework 补丁的情况下直接完成：

``` text
SUCCESS
PASS_WITH_WARNING
APPROVE
None identified
```

因此 v0.2 MVP 验证阶段已结束。

------------------------------------------------------------------------

## 5. Known Non-blocking Risks / Notes

当前已知但非阻断：

1.  WorkBuddy 某些环境下不能独立复跑 browser smoke。
2.  业务项目工作树可能包含跨 TASK 历史未提交改动，不能自动解释为当前
    TASK 越界。
3.  CodeBuddy 登录态未来可能失效，需要重新 `/login`。
4.  Codex websocket 在部分网络环境可能失败，但已验证可 fallback HTTPS。
5.  当前真实运行基线是 Windows；尚不能未经验证宣称 Linux/macOS
    完全等价。
6.  verdict 聚合仍依赖 Agent
    输出遵守当前结论格式规范，后续正式化时应记录该契约。
7.  WorkBuddy stage 已实现有界 transient retry（AAF-v0.4-TASK-011，RW-027
    SOLVED）：per-attempt timeout 默认 900s（实测成功 stage ~556s）替代统一
    3600s 硬等待；max_attempts=2（`AAF_WORKBUDDY_MAX_ATTEMPTS` 可配）、
    backoff 30s、overall stage budget 硬上限、timeout 进程树清理；Hermes/Codex
    不自动获得 retry，`AAF_WORKBUDDY_RETRY=0` 整体关闭。详见
    `ai_agent_framework/workbuddy_retry.py` 与 backlog RW-027。
8.  pythonw 早期 validation 失败（exit=2）在 Bridge UI 只显示 enter=2、
    具体 TaskValidationError 不可见（backlog RW-028，OBSERVATION）——仅登记，
    不在本阶段实现。

这些事项当前不要求生成新的 FIX TASK，除非出现新的可复现阻断证据。

------------------------------------------------------------------------

## 6. Current Objective

当前唯一主目标：

> **完成 AI Agent Framework v0.2 的收官、冻结、正式化整理与 GitHub
> 仓库化。**

当前不是 v0.3 开发阶段。

未经用户明确决定：

``` text
v0.3 = NOT STARTED
```

AI 不得自行切换、升级或开展 v0.3 功能实现。

可以记录 future / backlog，但不得提前实施。

------------------------------------------------------------------------

## 7. Next Action

下一步优先事项：

### Step 1 --- Baseline Freeze

冻结当前已经验证的 prototype 状态，确保收官整理前有可靠回滚点。

### Step 2 --- Directory Diff / Inventory

盘点：

``` text
<PROJECT_ROOT>-prototype
```

与：

``` text
<PROJECT_ROOT>
```

之间的实际差异。

目标：

-   确认哪些修复只存在于 prototype；
-   确认哪些文件属于测试/备份/临时输出；
-   确认哪些文件应该进入正式仓库；
-   确认哪些文件必须排除；
-   不直接覆盖正式目录。

### Step 3 --- Repository Formalization

在差异盘点后继续：

-   正式目录结构；
-   README；
-   安装说明；
-   TASK / REPORT 规范；
-   dry-run / run / resume 标准命令；
-   tests；
-   changelog / version；
-   `.gitignore`；
-   敏感信息检查；
-   GitHub 仓库化。

### Step 4 --- Final Verification

正式化迁移后：

1.  重跑完整测试；
2.  基线不得无解释低于当前 `52 passed`；
3.  从正式目录执行最小 smoke TASK；
4.  验证完整链路；
5.  再决定 v0.2 Freeze / Release。

------------------------------------------------------------------------

## 8. Hard Boundaries

没有新的可复现证据时，不得重新：

-   设计基本 Agent 角色；
-   推翻 TASK 唯一输入机制；
-   重写已验证 Router；
-   重做 stdin 长 prompt；
-   重做 resume；
-   重做状态聚合；
-   把 TASK-001 ～ TASK-010 当成未完成重新执行；
-   为"更漂亮"进行无目标架构重构。

禁止未经风险确认：

-   删除历史 TASK / REPORT；
-   清空 `.aaf` 历史证据；
-   删除备份；
-   覆盖正式目录；
-   强制 reset / clean；
-   大范围移动用户文件；
-   修改 `workbuddy_skills/skills/`。

------------------------------------------------------------------------

## 9. Source-of-Truth Documents

本项目当前有三类恢复文档。

### A. Historical MVP Snapshot --- Frozen

建议正式保存为：

``` text
docs/status/AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md
```

作用：

> 记录 v0.2 MVP 验证完成时的完整历史事实。

原则上冻结，不持续覆盖。

### B. Conversation / Stage Handoff --- Frozen

建议正式保存为：

``` text
docs/handoffs/AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md
```

作用：

> 结束上一超长对话，并规定新阶段的边界、行为限制和恢复规则。

原则上冻结，不持续覆盖。

### C. Current Project State --- Living

本文件正式保存为：

``` text
PROJECT_STATE.md
```

建议位于 Framework 仓库根目录。

作用：

> **当前项目状态的持续更新入口。**

后续新对话、换模型、隔一段时间恢复项目时，应优先读取本文件，再按需要查阅历史快照与阶段交接。

------------------------------------------------------------------------

## 10. Update Rules for Future Conversations

后续负责 AI Agent Framework 的对话必须知道本文件存在。

发生以下情况时应更新 `PROJECT_STATE.md`：

-   完成一个 v0.2 收官步骤；
-   prototype → 正式目录迁移；
-   测试基线变化；
-   新增或关闭 Framework 级风险；
-   GitHub 仓库建立；
-   v0.2 freeze / release；
-   用户明确决定进入新的版本阶段。

更新原则：

1.  更新当前事实，不改写历史。
2.  历史细节进入 handoff / changelog，不无限堆入本文件。
3.  任何状态结论优先依据真实测试、REPORT 和代码证据。
4.  不因为新对话上下文缺失而重新规划已完成阶段。
5.  新对话完成重要工作后，应主动判断是否需要同步更新本文件。

------------------------------------------------------------------------

## 11. Recovery Protocol

新对话恢复项目时，读取顺序：

``` text
1. PROJECT_STATE.md
2. docs/status/AI-Agent-Framework-v0.2-MVP-STATUS-HANDOFF-2026-08-25.md
3. docs/handoffs/AI-Agent-Framework-v0.2-CLOSING-HANDOFF-2026-08-25.md
4. 必要时查看真实 REPORT / tests / source code
```

恢复后必须接受以下当前事实：

``` text
v0.2 MVP Validation: PASSED
Regression Baseline: 52 passed
Latest Production Validation: TASK-010 SUCCESS
Current Lifecycle: CLOSING / FREEZE PREPARATION
Next Work: prototype/formal directory inventory and v0.2 formalization
v0.3: NOT STARTED
```

------------------------------------------------------------------------

## 12. Current State Summary

``` text
Project:
AI Agent Framework

Version:
v0.2

MVP Validation:
PASSED

Regression:
52 passed

Latest Real Task:
TASK-010 SUCCESS

Framework Blocking Bug:
None currently known

Working Source:
<PROJECT_ROOT>
(formal repository — v0.2 formalized, AAF-TASK-004/005)

Formal Directory:
<PROJECT_ROOT>
(migrated and validated)

Current Phase:
v0.2 CLOSED

Immediate Next Step:
v0.3 Planning (NOT STARTED — requires explicit user decision)

GitHub:
Public — https://github.com/adyfox85-wq/ai-agent-framework
Release: v0.2.0-rc1 (2026-08-25)

v0.3:
NOT STARTED
DO NOT START WITHOUT EXPLICIT USER DECISION
```
