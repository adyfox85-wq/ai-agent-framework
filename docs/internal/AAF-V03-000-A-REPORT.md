# AAF-V03-000-A-REPORT

- Task: AAF-V03-000-A (AAF Bridge Minimal Intake)
- Date: 2026-08-26
- Type: v0.3 第一个开发任务（Windows 本地 Bridge 最小入口）
- Status: **COMPLETE — WorkBuddy APPROVE**
- Executor: Hermes / Reviewer: WorkBuddy

---

## 1. 交付内容

新增 `bridge/` 模块（**零第三方依赖**：ctypes RegisterHotKey + Win32 剪贴板 + tkinter UI）：

| 文件 | 行数 | 职责 |
|---|---|---|
| `bridge/main.py` | 165 | 入口：热键监听 + 配置热加载 + 事件循环 + 流程组装 |
| `bridge/task_io.py` | 171 | TASK 解析/校验/落盘（纯函数，可单测） |
| `bridge/config.py` | 122 | 配置读写 + 热键解析/描述（纯函数） |
| `bridge/win32.py` | 105 | RegisterHotKey + 剪贴板读取（ctypes 薄封装） |
| `bridge/ui.py` | 67 | tkinter 确认窗口 + 提示 |
| `bridge/__init__.py` | 2 | 版本 |

流程：**Ctrl+Alt+A 热键 → 读剪贴板 → BEGIN/END + 必填字段 + Workspace 双重校验 → 确认窗口（Execute/Cancel）→ 落盘 `<Workspace>\.aaf\tasks\active\<Task-ID>.md` → 提示**。

## 2. Acceptance 对照

| # | 验收项 | 结果 |
|---|---|---|
| 1 | Bridge 可在 Windows 启动 | ✅ 实际启动验证（热键注册成功，mainloop 正常） |
| 2 | Ctrl+Alt+A 默认可触发 | ✅ 默认热键，注册成功 |
| 3 | 默认热键可改 | ✅ config.json `hotkey` 字段（ctrl+alt+b 等），**配置热加载无需重启**（2s 轮询） |
| 4 | 普通 Ctrl+C/V 不触发 | ✅ 仅热键触发读剪贴板（事件入队，主线程处理） |
| 5 | 非 AAF TASK 文本不生成文件 | ✅ 缺 BEGIN/END 标记 → 校验失败，不落盘 |
| 6 | 缺必填字段不生成文件 | ✅ Task ID/Name/Workspace/Objective/Acceptance 缺失 → 明确报错 |
| 7 | Workspace 不匹配不生成文件 | ✅ 双重校验（TASK 声明 vs Bridge 绑定），大小写不敏感 |
| 8 | 合法 TASK 弹确认窗口 | ✅ tkinter 确认（Task ID/Name/Project/Workspace + Execute/Cancel） |
| 9 | Cancel 不生成文件 | ✅ |
| 10 | Execute 正确生成目标文件 | ✅ `.aaf\tasks\active\<Task-ID>.md`（最小目录创建） |
| 11 | 同名 Task ID 不覆盖 | ✅ TASK_ALREADY_EXISTS，停止 |
| 12 | TASK.md 内容语义一致 | ✅ 保存提取后的标准 TASK 正文（含 BEGIN/END），不写入标记外前后文 |
| 13 | 不调用 Hermes/WorkBuddy/Codex | ✅ 零 Agent 调用 |
| 14 | 不修改 v0.2 核心逻辑 | ✅ router/runner/report/adapters/run.py 零改动（WorkBuddy 隔离性 VERIFIED） |
| 15 | 52 回归不下降 | ✅ **75 passed**（52 原有 + 23 Bridge 新增） |

## 3. 测试结果

✅ **75 passed in 0.08s**（52 v0.2 回归 + 23 Bridge：解析/校验/落盘/重复保护/配置/热键/正文保留）。

## 4. WorkBuddy 复核结果

- 第一轮：**REQUEST_CHANGE**（3 个阻断：剪贴板固定长度越界读取、热键热加载旧注册泄漏、落盘整段剪贴板）
- 修复后复核：**APPROVE** ✅（3 项 FIXED；minor 项 MOD_NOREPEAT 重复定义已一并清理为单来源）
- 修复内容：GlobalSize 按实际大小读剪贴板 / unregister 旧热键 / 落盘提取正文 / F 键显示 / 常量单来源

## 5. 使用说明

```bash
# 启动 Bridge（后台常驻）
python -m bridge.main

# 配置（用户主目录，不污染仓库）
# ~/.aaf-bridge/config.json
{
  "hotkey": "ctrl+alt+a",        # 可改，改后 ~2s 热加载生效
  "current_project": "示例项目",   # 仅展示
  "current_workspace": "D:\\path\\to\\project"   # 双重校验基准
}
```

操作：Planner 输出 TASK（含 AAF_TASK_BEGIN/END）→ 复制 → Ctrl+Alt+A → 确认 → 落盘。

## 6. 边界确认

- 未修改 v0.2 核心（router/runner/report/adapters/run.py 零改动）
- 未调用 Hermes/WorkBuddy/Codex（仅 WorkBuddy 人工复核）
- 未引入第三方依赖（纯标准库 + ctypes + tkinter）
- 配置在用户主目录（无本地路径进入公开仓库）
- v0.3 其他方向（lifecycle/archive/session）未启动
