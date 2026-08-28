from __future__ import annotations

import json
from pathlib import Path

from .task_validation import parse_task_fields
from .verdict_parser import canonical_blocking

# ---------- Blocking Provenance（FIX-001：structured blocking 语义必须可辨识来源） ----------
# 三种来源，优先级见 agent_result_blocked：
# - structured：blocking_rework 来自 agent 显式声明的 schema-validated 结构化块且
#   结构化块**显式声明** blocking_provenance=structured（FIX-002：explicit field 才是
#   structured authority；key 存在性 / COMPLETE 标签都不得反推来源）
# - framework：Framework 可确定的执行有效性事实（FRAMEWORK_ERROR / required result
#   缺失或空 / invalid structured blocking data）——优先于 agent 的任何 no-blocking 声明
# - narrative：legacy narrative keyword fallback / 一致性 guard 交叉验证后的派生值——
#   永远只是 fallback，不得伪装成 structured authoritative fact
BLOCKING_PROVENANCE_STRUCTURED = "structured"
BLOCKING_PROVENANCE_FRAMEWORK = "framework"
BLOCKING_PROVENANCE_NARRATIVE = "narrative"

# FIX-002 Req 3/5：structured authority 只来自 agent 结构化块中**显式声明**的合法
# blocking_provenance 字段值；blocking_rework key 存在与否、structured_summary_status
# 是否为 COMPLETE，都不得用于反推来源（legacy 兼容规则：缺字段 → narrative）。
BLOCKING_PROVENANCE_VALUES = frozenset(
    (
        BLOCKING_PROVENANCE_STRUCTURED,
        BLOCKING_PROVENANCE_FRAMEWORK,
        BLOCKING_PROVENANCE_NARRATIVE,
    )
)


def _summarize(text: str, limit: int = 6000) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + '\n...[truncated by framework]'


def verdict_ok(agent: str, body: str) -> bool:
    """该 Agent 是否有明确的 canonical 整体通过结论（PASS / PASS_WITH_WARNING /
    SUCCESS / APPROVE verdict line）。

    FIX-005（RW-022）：只认明确 overall verdict/result 行，不再全文扫描
    PASS/SUCCESS token——正文中的历史引用 / 示例 / 标题（"PASS 证据"、
    "SUCCESS path"）不是通过结论，不得覆盖真实 verdict。Hermes 正常完成
    即视为通过（无 verdict 语义）。
    """
    if agent == 'hermes':
        return True
    return canonical_blocking(_strip_structured_block(body or '')) is False


def verdict_blocked(agent: str, body: str) -> bool:
    """判定该 Agent 结果是否构成阻断（缺失 / FRAMEWORK_ERROR / canonical 失败 verdict）。

    FIX-005（RW-022）：blocking 判定与 verdict 派生使用同一 canonical verdict
    semantic——只有明确 overall verdict/result 行（VERDICT: FAIL / Result: FAILED /
    结论：REQUEST_CHANGE / FAILED: 等）才构成阻断；正文任意位置的 FAIL/FAILED/
    REQUEST_CHANGE token（"test FAILED example"、"previous result was PASS"、
    quoted 历史 reviewer output）不是结论。

    - 空结果 / FRAMEWORK_ERROR → 阻断（framework hard failure）
    - canonical blocking verdict 行 → 阻断
    - canonical 通过 verdict 行 → 非阻断（正文中的历史 FAIL/REQUEST_CHANGE
      引用不视为当前阻断）
    - 无 canonical verdict 行（ambiguous legacy narrative，Requirement 7）：
      workbuddy / codex（required reviewer，有 verdict 语义）不得凭正文任意
      token 猜通过 → fail-safe 阻断（不得 fail-open）
    - hermes 等无 verdict 语义 agent：只认显式失败判定形态（canonical 失败行 /
      整行 FAIL / FAILED）
    """
    body = _strip_structured_block(body or '').strip()
    if not body:
        return True
    if body.startswith('FRAMEWORK_ERROR'):
        return True
    cb = canonical_blocking(body)
    if cb is not None:
        return cb
    if agent in ('workbuddy', 'codex'):
        return True
    # 无 verdict 语义的 agent（hermes 等）：只认显式失败判定形态
    return _explicit_failure_marker(body)


# 显式失败判定形态已统一到 canonical verdict semantic（FIX-005）：
# verdict_parser 的行首标签 / 行内整体标签 / 裸 token 行覆盖原
# _RESULT_VERDICT_LINE_RE（Result/Verdict/Status/结论/判定 + 失败词）与
# _PREFIX_FAIL_RE（行首 FAILED:/FAIL:/REQUEST_CHANGE:）——单一 parser 复用，
# 避免多份正则漂移。

_STRUCTURED_BEGIN_MARKER = 'AAF_STRUCTURED_RESULT_BEGIN'
_STRUCTURED_END_MARKER = 'AAF_STRUCTURED_RESULT_END'


def _strip_structured_block(text: str) -> str:
    """移除答复末尾的机器可读结构化块，返回纯 narrative（FIX-003）。

    verdict 判定只应考察 prose：结构化块 JSON 中的结论词（{"verdict": "PASS"}）
    不是 narrative 证据——narrative "Result: FAILED" + tail 声称 PASS 时，
    fail-safe 路径不得因 JSON 中的 PASS 而放行（RW-022 fail-open）。
    """
    if not text:
        return text
    begin = text.find(_STRUCTURED_BEGIN_MARKER)
    if begin == -1:
        return text
    end = text.find(_STRUCTURED_END_MARKER, begin)
    if end == -1:
        return text[:begin]
    return text[:begin] + text[end + len(_STRUCTURED_END_MARKER):]


def _explicit_failure_marker(body: str) -> bool:
    """无 verdict 语义 agent（hermes 等）的显式失败判定形态（FIX-005）。

    统一 canonical verdict semantic：只有明确 verdict/result 行含失败 token
    （``Result: FAILED`` / ``FAILED: 实现不完整`` / 整行 ``FAILED`` / ``FAIL``）
    才阻断；句中技术性词语（"the previously FAILED test now passes"）不是
    execution failure / blocking verdict。
    """
    b = body.strip()
    if not b:
        return True
    return canonical_blocking(b) is True


def read_structured_blocking(agent: str, output_dir) -> tuple[bool, bool | None, str, str]:
    """读取 ``<agent>_result.json`` 的 blocking 信号 + provenance（RW-022 / FIX-001 / FIX-002）。

    返回 (available, blocking, status, provenance)：
    - available=False：JSON 缺失 / 损坏（不可解析）→ 调用方走 legacy narrative fallback
    - status == 'INVALID'：结构化 blocking 数据非法 → 调用方必须 fail closed（FIX-001 Req G）：
      * ``blocking_rework`` 字段存在且非 bool
      * ``blocking_provenance`` 字段存在但类型 / 值不合法（FIX-002 Req 9-D）
    - provenance：structured / framework / narrative（见模块常量）。
      FIX-002 Req 3/4：``blocking_provenance`` 缺失 = legacy artifact → **一律** narrative
      fallback——不得凭 ``blocking_rework`` key 存在或 status==COMPLETE 推断 structured
      authority（旧框架的 COMPLETE 推断语义已移除；blocking 决策值仍 backward compatible）。
    """
    if output_dir is None:
        return False, None, '', ''
    path = Path(output_dir) / f'{agent}_result.json'
    if not path.exists():
        return False, None, '', ''
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False, None, '', ''
    if not isinstance(data, dict):
        return False, None, '', ''
    br = data.get('blocking_rework')
    if 'blocking_rework' in data and not isinstance(br, bool):
        # 字段存在但类型非法：invalid structured blocking data → fail closed
        return False, None, 'INVALID', ''
    if not isinstance(br, bool):
        # 旧 artifact 缺少新 blocking 字段 → legacy fallback（Req 6 backward compat）
        return False, None, '', ''
    status = str(data.get('structured_summary_status') or '')
    prov = data.get('blocking_provenance')
    if prov is not None and not (isinstance(prov, str) and prov in BLOCKING_PROVENANCE_VALUES):
        # 显式 provenance 字段存在但非法（类型 / 值）→ invalid structured data → fail closed
        return False, None, 'INVALID', ''
    if not prov:
        # FIX-002 Req 3/4：provenance 缺失 = legacy artifact → narrative（backward
        # compat）；绝不自动升级为 structured authority
        prov = BLOCKING_PROVENANCE_NARRATIVE
    return True, bool(br), status, prov


def agent_result_blocked(agent: str, body: str, output_dir=None) -> bool:
    """聚合用阻断判定：framework hard failure > structured 权威 > canonical
    narrative authority > fail-safe fallback（FIX-001 / FIX-005）。

    优先级（FIX-005 更新，Requirement 3/4/7）：
    1. Framework-determined hard failure（Req 3，优先于 agent 的任何 no-blocking 声明）：
       - required result missing / empty
       - FRAMEWORK_ERROR（required agent execution failure）
       - invalid structured blocking data（blocking_rework 存在但非 bool）→ fail closed
    2. explicit structured verdict：JSON 存在、blocking_rework 合法、summary COMPLETE
       且 provenance=structured → 直接采用 blocking_rework（agent 显式声明的权威事实）。
       provenance=narrative（narrative keyword 派生）**永远不是** structured authority。
    3. canonical narrative verdict（明确 overall verdict/result 行）→ legacy narrative
       authority（Requirement 3：VERDICT: FAIL 后文无论多少 PASS/SUCCESS 仍 FAIL）。
       structured 部分信号（provenance=narrative / 非 COMPLETE）与 canonical narrative
       明确冲突 → fail closed（Requirement 4：structured 与 canonical narrative 冲突
       不得放行）。
    4. ambiguous legacy narrative（无 canonical verdict 行，Requirement 7）：不得凭
       正文任意 PASS/FAIL token 猜权威结论——required agent（workbuddy/codex）不得
       fail-open；hermes 只认显式失败判定形态（FIX-001 保持）。
    """
    stripped = (body or '').strip()
    # 1) Framework-determined hard failures（最高优先级；COMPLETE 标签不得覆盖 execution validity）
    if not stripped:
        return True  # required result missing / empty（required stage not executed）
    if stripped.startswith('FRAMEWORK_ERROR'):
        return True  # framework execution failure
    available, blocking, status, provenance = read_structured_blocking(agent, output_dir)
    if status == 'INVALID':
        return True  # invalid structured blocking data → fail closed
    # 2) explicit structured verdict（唯一权威路径：COMPLETE + provenance=structured）
    if available and status == 'COMPLETE' and provenance == BLOCKING_PROVENANCE_STRUCTURED:
        return blocking
    # 3) canonical narrative verdict authority（FIX-005）
    n_blocking = canonical_blocking(stripped)
    if n_blocking is not None:
        # structured 部分信号与 canonical narrative 明确冲突 → fail closed
        if available and blocking != n_blocking:
            return True
        return n_blocking
    # 4) fail-safe：structured 部分信号可用 → 采用；否则 required reviewer 不 fail-open
    if available:
        return blocking
    if agent in ('workbuddy', 'codex'):
        return True
    return _explicit_failure_marker(stripped)


def _extract_unresolved(results: dict[str, str], output_dir=None) -> str:
    """只收集真正未解决的阻断项；正常执行摘要 / diff / PASS / PASS_WITH_WARNING / APPROVE / 非阻断 warning 不进入。"""
    issues = []
    for name, body in results.items():
        if agent_result_blocked(name, body, output_dir):
            head = ' | '.join(body.strip().splitlines()[:3])[:600]
            issues.append(f'- {name}: {head}')
    return '\n'.join(issues) if issues else 'None identified.'


def _cancellation_section(terminal: dict) -> str:
    """CANCELLED REPORT 的取消说明（§6.6 / TASK req 17）。

    记录合理事实：Task ID / 取消时间 / 已完成阶段与 Agent 结果保留 / 后续阶段未执行。
    不伪造 Force Cancel / PID kill / ownership verified（本 TASK 只有 soft cancel）。
    """
    cancel_mode = terminal.get("cancel_mode")
    mode_text = {
        "soft": "cooperative（soft cancel）",
        "force": "force cancel（TASK-005-B 交付，本 TASK 未使用）",
    }.get(cancel_mode, str(cancel_mode))
    requested_at = terminal.get("cancel_requested_at")
    lines = [
        '## Cancellation',
        '任务已取消（CANCELLED）',
        f'- Task ID: {terminal.get("task_id", "")}',
    ]
    if requested_at:
        lines.append(f'- 取消请求时间: {requested_at}')
    if terminal.get("terminal_at"):
        lines.append(f'- 取消收敛时间: {terminal["terminal_at"]}')
    lines.append(f'- 取消方式: {mode_text}')
    lines.append('- 已完成阶段与 Agent 结果已保留')
    lines.append('- 后续阶段未执行')
    return '\n'.join(lines)


def build_report(
    task: str,
    route: list[str],
    results: dict[str, str],
    status: str,
    integrity_notes: list[str] | None = None,
    terminal: dict | None = None,
    *,
    task_path=None,
    task_hash: str | None = None,
    output_dir=None,
    sync_state: dict | None = None,
    intake_task_path=None,
) -> str:
    """生成 REPORT.md 文本（REPORT De-duplication，Requirement 7）。

    - 提供 ``task_path`` / ``task_hash``（Runner / Reconcile 新协议路径）→
      ``## Original Task`` 不再复制全文，改为 ``## Task Reference``（Task ID / Path / Hash）；
      未提供（legacy 外部调用方）→ 保留旧 ``## Original Task`` 全文嵌入（Backward Compat）。
      FIX-002 Req 1/2：Runner 传入的 task_path 是 immutable execution snapshot
      （TASK.snapshot.md），task_hash 只从 snapshot 计算一次并在整个 lifecycle 复用。
      FIX-003 Req 8：``intake_task_path``（active TASK 原始路径）只作为
      ``Original Intake Path`` provenance 记录，不是 execution authority。
    - Agent Results：摘要 + 完整结果 artifact 路径（output_dir 提供时）；不复制上游 narrative 全文。
    - ``sync_state``：``context_packet.remote_sync_state()`` 的 dict（FIX-002 Req 4/5）——
      提供时附加 ``## Remote Sync`` 段（Commit Sync / Tracked Working Tree /
      Task Remote Sync）；缺省（legacy 调用方）不输出该段，不虚构。
    - ``terminal``：canonical terminal metadata（TerminalResult.to_dict() 或等价 dict），
      提供时附加 ``## Terminal Generation``（派生产物 provenance，§6B.4）
    - status == CANCELLED：追加 ``## Cancellation`` 中文说明（§6.6 / req 17）；
      未执行 agent 的缺失结果不列入 Unresolved Issues（取消是预期中断，不是缺陷）
    """
    agent_sections = []
    for name in route:
        body = _summarize(results.get(name, '(not run)'), 1200)
        section = f'### {name}\n{body}'
        if output_dir is not None:
            md = Path(output_dir) / f'{name}_result.md'
            section += f'\n- Full result: {md}'
        agent_sections.append(section)
    results_text = '\n\n'.join(agent_sections)

    if status == 'CANCELLED':
        unresolved = 'None identified.'  # 取消任务不把未执行 agent 当 unresolved
        if integrity_notes:
            unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])
    else:
        # RW-022：unresolved 同样 structured-first（<agent>_result.json blocking_rework），
        # legacy narrative 为 fail-safe fallback
        unresolved = _extract_unresolved(results, output_dir)
        if integrity_notes:
            unresolved = '\n'.join([unresolved, *[f'- {n}' for n in integrity_notes]])

    extra = ''
    if status == 'CANCELLED' and terminal:
        extra = '\n\n' + _cancellation_section(terminal)
    if terminal and terminal.get('terminal_generation') is not None:
        extra += f'\n\n## Terminal Generation\n{terminal["terminal_generation"]}'

    if task_path or task_hash:
        # Requirement 7：REPORT 不再全文复制 Original Task，改为可追溯引用
        task_id = parse_task_fields(task).get('Task ID') or '(unknown)'
        ref_lines = [
            '## Task Reference',
            f'- Task ID: {task_id}',
        ]
        if task_path:
            ref_lines.append(f'- Task Path: {task_path}')
        if task_hash:
            ref_lines.append(f'- Task Hash: {task_hash}')
        if intake_task_path:
            ref_lines.append(
                f'- Original Intake Path: {intake_task_path}'
                '（provenance；execution authority 为上方 immutable snapshot）'
            )
        if output_dir is not None:
            ref_lines.append(f'- Artifacts: {output_dir}')
        task_section = '\n'.join(ref_lines)
    else:
        # Legacy 调用方（未提供引用信息）：保留全文嵌入，确保自包含
        task_section = f'## Original Task\n{_summarize(task, 8000)}'

    sync_section = ''
    if sync_state and isinstance(sync_state, dict) and sync_state.get('is_git_repo') is not False:
        # FIX-002 Req 4/5：区分 commit graph sync 与 tracked working tree；
        # Task Remote Sync 仅当两者都满足（commit+push 且 tracked CLEAN）才为 SYNCED
        dirty = sync_state.get('tracked_dirty_entries') or []
        sync_lines = [
            '## Remote Sync',
            f"- Commit Sync: {sync_state.get('commit_sync', 'UNKNOWN')}",
            f"- Tracked Working Tree: {sync_state.get('tracked_working_tree', 'UNKNOWN')}",
            f"- Task Remote Sync: {sync_state.get('task_remote_sync', 'UNKNOWN')}",
        ]
        if sync_state.get('ahead') is not None or sync_state.get('behind') is not None:
            sync_lines.append(
                f"- Ahead/Behind: {sync_state.get('ahead', 0)}/{sync_state.get('behind', 0)}"
            )
        if dirty:
            sync_lines.append('- Tracked 未提交条目:')
            sync_lines.extend(f'  - {d}' for d in dirty[:20])
        sync_section = '\n\n' + '\n'.join(sync_lines)

    return f'''# REPORT

## Current Status
{status}

## Route
{' -> '.join(route)}

{task_section}

## Agent Results
{results_text}

## Unresolved Issues
{unresolved}
{sync_section}

## Planner Handoff
Use this report as the authoritative context for the next planning turn. Resolve any FAIL / REQUEST_CHANGE / unresolved warnings before creating the next TASK. If all required checks passed, plan the next smallest task without reopening completed scope.{extra}
'''
