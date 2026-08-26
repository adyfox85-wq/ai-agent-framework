# AAF Real-World Hotfix — Codex Command Discovery

- Date: 2026-08-27
- Type: real-world usage hotfix（不重开 v0.3 Scope）
- Status: **COMPLETE — WorkBuddy APPROVE**
- 触发: TASK-011 真实执行中 Codex 阶段 `MISSING_COMMAND: codex`

---

## Root Cause

Codex CLI 自动升级会**更换 hash 版本目录**（当前 `8fffe69425752027`），旧目录 `110b3d66a02d864e` 残留于 HKCU registry PATH 但已不存在；`adapters._require` 仅查询 registry PATH（`shutil.which(cmd, path=_windows_path())`）→ 找不到 codex.exe → `MISSING_COMMAND: codex`。

证据：
- HKCU Path 含 `...OpenAI\Codex\bin\110b3d66a02d864e`（目录不存在）
- 实际 candidate：`54ee14df1f760d5e/`（无 codex.exe）+ `8fffe69425752027/`（有 codex.exe）
- `where codex` / `shutil.which("codex", path=_windows_path())` → None（复现）

## Fix（最小）

`ai_agent_framework/adapters.py`（+30 行）：

```
_require(cmd)
→ registry PATH lookup（shutil.which，原行为）
→ 仅 cmd=='codex' 且 PATH 失败时 → _codex_fallback()
→ 仍失败 → MISSING_COMMAND（原语义）

_codex_fallback()
→ %LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe
→ 多版本目录按 mtime 最新（当前有效版本）
→ 0 candidate / 无 exe → None（不假装成功）
```

原则遵守：PATH 优先 / 仅 codex fallback（hermes·codebuddy 零变化）/ 不硬编码 hash / 不改 Router·Report·Lifecycle·Boundary·Archive·Session / 不扩为通用 executable manager。

## Tests

✅ **198 passed**（191 + 7 新增，零下降）：

1. codex 在 PATH → 使用 PATH
2. codex 不在 PATH + 单一 fallback → 找到
3. 多版本目录 → mtime 最新确定性选择
4. 无 candidate → MISSING_COMMAND
5. Hermes resolution 不变（无 fallback 调用）
6. WorkBuddy resolution 不变（codebuddy 无 fallback）
7. 完整回归 191 不降

真实环境冒烟 ✅：`_require('codex')` → `C:\Users\Admin\AppData\Local\OpenAI\Codex\bin\8fffe69425752027\codex.exe`

## WorkBuddy

**APPROVE**（7 项检查 VERIFIED；1 非 blocker 观察：排序用 exe mtime 与"目录更新时间"等价）

## Core Files Changed

| 文件 | 变更 |
|---|---|
| `ai_agent_framework/adapters.py` | +30（_require codex 分支 + _codex_fallback + CODEX_FALLBACK_DIR） |
| `tests/test_codex_discovery.py` | **新增**（7 测试） |

**未触碰**：router / report / lifecycle / archive / session / boundary / bridge。

## TASK-011

不重新从头执行。本 hotfix 只修复 Codex command discovery；TASK-011 的 Codex 阶段可在后续按需重试/恢复（由 Planner 决定，不自动重跑）。
