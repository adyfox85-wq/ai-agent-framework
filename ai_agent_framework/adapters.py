from __future__ import annotations

import os
import re
import shutil
import subprocess
import winreg
from pathlib import Path

from .context_packet import read_stage_result
from . import cost_guard as cost_guard_mod
from . import stop_loss as stop_loss_mod
from .subprocess_utils import no_console_kwargs
from .task_validation import parse_task_fields
from .workbuddy_retry import (
    WorkBuddyPermanentError,
    WorkBuddyStageError,
    permanent_stage_error,
    run_workbuddy_with_retry,
)
from .workbuddy_routing import ENV_WORKBUDDY_MODEL


ROLE_INSTRUCTIONS = {
    'hermes': '你是 Executor。严格执行 TASK，不扩大范围。完成后报告实际修改、测试、产物、问题和未完成项。',
    'workbuddy': '你是 Validator。对 TASK 和前序结果进行独立复核；必须检查实际项目状态，不默认相信前序 Agent 自述。不要修改文件。给出 PASS / PASS_WITH_WARNING / FAIL、证据和返工项。',
    'codex': '你是 Reviewer。基于 TASK、执行结果和复核结果做独立审查，重点检查代码/架构/逻辑/风险。不要代替 Executor 修改文件。给出 APPROVE / REQUEST_CHANGE 及证据。',
}

# Anti-Bloat Policy（docs/internal/AAF_TASK_EXECUTION_POLICY.md）：
# 下游 Agent（WorkBuddy / Codex）不再默认接收上游 narrative 全文——
# 只接收 TASK 引用 + 结构化 stage 摘要 + artifact 路径；全文按需读取。
# 旧任务 / 缺结构化 JSON 的目录自动 fallback 到 legacy 全文嵌入（Backward Compat）。


def _ws_block(workspace: Path | None) -> str:
    return (
        f'\n\n# WORKSPACE\n工作目录（绝对路径）：{workspace}\n'
        '所有文件创建、修改、检查都必须在 WORKSPACE 目录内进行；不要在其他位置创建任务产物。\n'
        if workspace else ''
    )


def _task_ref_block(task: str, task_path, task_hash: str | None) -> str:
    """TASK REFERENCE：Task ID / Snapshot Path / Hash + 必须读取 snapshot 全文 +
    缺失引用 fail-fast（FIX-002 Req 1/2：统一引用 immutable execution snapshot，
    不以可变化的 active TASK 文件作为审查完整性依据）。"""
    task_id = parse_task_fields(task).get('Task ID') or '(unknown)'
    lines = [
        '# TASK REFERENCE（execution snapshot）',
        f'- Task ID: {task_id}',
    ]
    if task_path:
        lines.append(f'- Snapshot Path: {task_path}')
    if task_hash:
        lines.append(f'- Task Hash: {task_hash}')
    lines += [
        '',
        '你必须首先读取 execution snapshot（TASK.snapshot.md）全文'
        '（它是本次执行/验证的 immutable 权威输入，内容 = Runner 实际执行的 TASK）；',
        'active TASK 文件的后续变化不影响本次 execution integrity。',
        '如果无法读取 snapshot → 必须报告 FAIL / REQUEST_CHANGE 并明确列出缺失引用，',
        '不得在缺失 TASK 上下文的情况下静默继续审查。',
    ]
    return '\n'.join(lines)


def _structured_contract_block(agent: str) -> str:
    """Machine-Readable Stage Summary 契约（FIX-002 Req 7）：Agent 答复必须以
    可解析结构化块结尾；Framework 只接受 schema-validated 结果。"""
    if agent == 'hermes':
        example = '{"status": "SUCCESS", "commit": "<sha 或 null>", "changed_files": ["..."], "warnings": []}'
        fields = ('status（SUCCESS/FAILED）', 'commit（真实 git sha 或 null）',
                  'changed_files（真实路径列表）', 'warnings（显式报告时列出；确认没有则为 []）')
    else:
        example = ('{"verdict": "PASS_WITH_WARNING", "blocking_rework": false, '
                   '"blocking_provenance": "structured", "findings": ["..."], "warnings": ["..."]}')
        verdict_opt = 'PASS / PASS_WITH_WARNING / FAIL' if agent == 'workbuddy' else 'APPROVE / REQUEST_CHANGE'
        fields = (f'verdict（{verdict_opt}）', 'blocking_rework（true/false）',
                  'blocking_provenance（blocking_rework 的来源声明：structured / framework / '
                  'narrative；不声明 = legacy narrative fallback，不会获得 structured authority）',
                  'findings（字符串数组）', 'warnings（字符串数组）')
    lines = [
        '# STRUCTURED RESULT CONTRACT（必读）',
        '你的最终答复必须以上述 narrative 之后、以如下机器可读块结尾（块后不得再输出其他内容）：',
        'AAF_STRUCTURED_RESULT_BEGIN',
        example,
        'AAF_STRUCTURED_RESULT_END',
        '字段：' + '；'.join(fields) + '。',
        '[] 表示"确认没有"，不是"未提取"；未确认的项目不要放入数组。',
        '块前是你的 narrative（结论、证据、证据路径）；框架以本块为机器可读 summary，',
        'narrative 仍是验证真相。',
    ]
    return '\n'.join(lines)


def _rel(path: str, workspace) -> str:
    """展示用相对路径（agent cwd = workspace；绝对路径超出 sandbox 时相对路径仍可达）。"""
    try:
        rel = os.path.relpath(path, str(workspace))
        if not rel.startswith('..'):
            return rel
    except (ValueError, OSError):
        pass
    return path


def _upstream_summary_block(agent: str, output_dir: Path, workspace: Path) -> str:
    """上游结构化 stage 摘要（来自 <agent>_result.json）；缺失 → 显式标注。

    FIX-002 Req 6/8：结构化 summary 缺失 / malformed / 不完整（summary_complete=false
    或 structured_summary_status != COMPLETE）→ 显式 PARTIAL/UNKNOWN，并要求读取
    narrative 全文复核——不得把空 findings/warnings 当成完整事实。
    """
    stage = read_stage_result(output_dir, agent)
    if stage is None:
        return (
            f'## {agent.upper()} STAGE SUMMARY\n'
            f'（缺失 {output_dir / f"{agent}_result.json"} —— 上游无结构化结果；'
            f'必须读取其 narrative 全文 {_rel(str(output_dir / f"{agent}_result.md"), workspace)} 复核）'
        )
    lines = [
        f'## {agent.upper()} STAGE SUMMARY（结构化，来自 {_rel(str(output_dir / f"{agent}_result.json"), workspace)}）',
        f'- status: {stage.get("status")}',
        f'- verdict: {stage.get("verdict")}',
        f'- blocking_rework: {stage.get("blocking_rework")}',
        f'- blocking_provenance: {stage.get("blocking_provenance")}',
        f'- summary_complete: {stage.get("summary_complete")}',
        f'- structured_summary_status: {stage.get("structured_summary_status")}',
    ]
    if stage.get('commit'):
        lines.append(f'- commit: {stage["commit"]}')
    changed = stage.get('changed_files') or []
    if changed:
        lines.append(f'- changed_files ({len(changed)}):')
        lines.extend(f'  - {c}' for c in changed[:20])
        if len(changed) > 20:
            lines.append(f'  - …（共 {len(changed)} 项，完整列表见 result.json）')
    findings = stage.get('findings')
    warnings = stage.get('warnings')
    if findings is not None:
        lines.append(f'- findings ({len(findings)}):')
        lines.extend(f'  - {f}' for f in findings[:10])
        if len(findings) > 10:
            lines.append(f'  - …（共 {len(findings)} 项）')
    else:
        lines.append('- findings: UNKNOWN（上游未提供结构化 findings；不得视为"确认没有"）')
    if warnings is not None:
        lines.append(f'- warnings ({len(warnings)}):')
        lines.extend(f'  - {w}' for w in warnings[:10])
        if len(warnings) > 10:
            lines.append(f'  - …（共 {len(warnings)} 项）')
    else:
        lines.append('- warnings: UNKNOWN（上游未提供结构化 warnings；不得视为"确认没有"）')
    if stage.get('summary_complete') is not True:
        lines.append(
            '- ⚠ 本 summary 不完整（PARTIAL/UNKNOWN）：空 findings/warnings 不代表'
            '"确认没有"；必须读取 narrative 全文'
            f'（{_rel(str(output_dir / f"{agent}_result.md"), workspace)}）复核后再下结论。'
        )
    evidence = stage.get('evidence_paths') or []
    if evidence:
        lines.append('- evidence_paths:')
        lines.extend(f'  - {_rel(str(p), workspace)}' for p in evidence)
    summary = (stage.get('summary') or '').strip()
    if summary:
        lines.append(f'- summary（仅导航，不是验证真相）: {summary[:200]}')
    return '\n'.join(lines)


def _narrative_reference_block(agent: str, output_dir: Path, workspace: Path, previous_results: dict[str, str]) -> tuple[str, bool]:
    """上游 narrative 引用块。返回 (块文本, 是否已嵌入全文)。

    - 引用文件存在 → 只给路径（lazy-load）
    - 引用文件缺失 → 显式 fallback 嵌入全文（No-Information-Loss Fallback，Requirement 9），
      并标注 FALLBACK_EMBEDDED，绝不静默缺上下文
    """
    md = output_dir / f'{agent}_result.md'
    marker = f'## {agent.upper()} NARRATIVE REFERENCE'
    if md.exists():
        return (
            f'{marker}\n'
            f'- Full narrative: {_rel(str(md), workspace)}（按需读取；不默认注入全文。'
            f'如无法读取 → 报告 FAIL，不得静默继续）'
        ), False
    body = previous_results.get(agent, '(narrative missing)')
    return (
        f'{marker}\n'
        f'- 引用文件缺失: {_rel(str(md), workspace)}\n'
        f'- FALLBACK_EMBEDDED: 以下为上游完整 narrative 全文（缺失引用 fallback，Requirement 9）：\n'
        f'<narrative>\n{body}\n</narrative>'
    ), True


def _packet_prompt(
    agent: str,
    task: str,
    previous_results: dict[str, str],
    workspace: Path | None,
    output_dir: Path,
    task_path,
    task_hash: str | None,
) -> tuple[str, dict]:
    """Stage Context Packet 协议 prompt（Requirement 4）。

    WorkBuddy：TASK 引用 + Hermes 结构化摘要 + changed files/commit/evidence 路径 + repo access；
    Codex：TASK 引用 + Hermes 结构化执行事实 + WorkBuddy 结构化 verdict/findings + diff 路径。
    上游 narrative 全文只按需读取（引用缺失时显式 fallback 嵌入）。
    """
    ws = _ws_block(workspace)
    ref = _task_ref_block(task, task_path, task_hash)
    out = Path(output_dir)
    embedded = 0
    referenced = 0

    if agent == 'workbuddy':
        upstream_agents = ['hermes']
        validation_instruction = (
            '# INDEPENDENT VALIDATION\n'
            '你必须独立验证，不得只相信上游 summary（摘要只用于导航，Repository artifacts 才是验证真相）：\n'
            '1. 读取 TASK 文件全文，核对本轮 Requirements / Acceptance / Scope；\n'
            '2. 检查仓库实际状态：changed files / commit / evidence paths 是否真实存在且与声明一致；\n'
            '3. 独立验证 acceptance semantics 与 safety invariants 是否满足；\n'
            '4. 引用文件缺失或无法读取 → 报告 FAIL 并列出缺失项，不得静默降级验证质量。'
        )
    else:  # codex
        upstream_agents = ['hermes', 'workbuddy']
        validation_instruction = (
            '# INDEPENDENT REVIEW\n'
            '你必须独立审查，不得只相信上游 summary（摘要只用于导航，Repository artifacts 才是验证真相）：\n'
            '1. 读取 TASK 文件全文，核对本轮 Requirements / Acceptance / Scope；\n'
            '2. 独立检查代码/架构/逻辑/风险：读取 changed files 与相关 repo/diff 路径；\n'
            '3. 核查 Hermes 执行事实与 WorkBuddy verdict/findings 的证据链是否闭合；\n'
            '4. 引用文件缺失或无法读取 → 报告 REQUEST_CHANGE 并列出缺失项，不得静默继续审查。'
        )

    blocks = [ref]
    for up in upstream_agents:
        blocks.append(_upstream_summary_block(up, out, workspace))
        nblock, embedded_now = _narrative_reference_block(up, out, workspace, previous_results)
        blocks.append(nblock)
        embedded += 1 if embedded_now else 0
        referenced += 0 if embedded_now else 1
    blocks.append(validation_instruction)
    blocks.append(_structured_contract_block(agent))
    blocks.append(ws)

    prompt = f"{ROLE_INSTRUCTIONS[agent]}\n\n" + '\n\n'.join(blocks)
    metrics = {'embedded_artifact_count': embedded, 'referenced_artifact_count': referenced}
    return prompt, metrics


_SECTION_START_RE = re.compile(r'^[ \t]*(#{1,2}[ \t]+\S|[A-Z][A-Za-z /()\-]{2,40}[:：]|\d+\.\s)')
_SOURCE_OF_TRUTH_RE = re.compile(r'(?im)^[ \t]*Source of Truth[ \t]*[:：][ \t]*$')


def _extract_source_of_truth_paths(task: str) -> list[str]:
    """从 TASK 的 Source of Truth 节提取路径类引用（用于 Hermes prompt 的引用清单）。"""
    m = _SOURCE_OF_TRUTH_RE.search(task)
    if not m:
        return []
    paths = []
    for line in task[m.end():].splitlines():
        s = line.strip()
        if not s:
            continue
        if _SECTION_START_RE.match(s) and not s.startswith(('-', '*')):
            break
        if s.startswith(('-', '*')):
            item = s.lstrip('-* ').strip()
            if item and ('/' in item or '\\' in item or '.' in item):
                paths.append(item)
    return paths


def _hermes_prompt(task: str, workspace: Path | None, task_path, task_hash: str | None) -> tuple[str, dict]:
    """Hermes（Executor）：TASK 全文（= current delta）+ Source of Truth 引用清单 +
    Structured Result Contract。

    FIX-003 Req 5/6/13：Hermes prompt 也显式引用 immutable execution snapshot
    （path + 单一 hash）——本 prompt 嵌入的 TASK 即 snapshot 内容；active TASK
    后续变化不影响本次 execution integrity。legacy 调用方（无 task_path/hash）
    不注入引用块，保持向后兼容。
    """
    sources = _extract_source_of_truth_paths(task)
    blocks = ['# ORIGINAL TASK', task]
    ref_lines = []
    if task_path:
        ref_lines.append(f'- Snapshot Path: {task_path}')
    if task_hash:
        ref_lines.append(f'- Task Hash: {task_hash}')
    if ref_lines:
        ref_lines = [
            '# TASK REFERENCE（execution snapshot）',
            *ref_lines,
            '- 本 prompt 嵌入的 TASK 即 immutable execution snapshot（TASK.snapshot.md）内容；',
            '  active TASK 文件的后续变化不影响本次 execution integrity。',
        ]
        blocks.append('\n'.join(ref_lines))
    if sources:
        src_lines = ['# SOURCE OF TRUTH（Repository 权威来源；按需读取，不重复全文）']
        src_lines += [f'- {s}' for s in sources]
        blocks.append('\n'.join(src_lines))
    blocks.append(_structured_contract_block('hermes'))
    ws = _ws_block(workspace)
    if ws:
        blocks.append(ws.strip())
    prompt = f"{ROLE_INSTRUCTIONS['hermes']}\n\n" + '\n\n'.join(blocks)
    metrics = {
        'embedded_artifact_count': 0,
        'referenced_artifact_count': len(sources),
    }
    return prompt, metrics


def legacy_build_prompt(agent: str, task: str, previous_results: dict[str, str], workspace: Path | None = None) -> str:
    """Legacy prompt（Backward Compatibility，Requirement 8）：全文嵌入 TASK + 全部前序结果。

    仅用于：旧目录 / 缺结构化 stage JSON 的任务 / 未提供 output_dir 的调用方。
    """
    prior = '\n\n'.join(f'## {name.upper()} RESULT\n{body}' for name, body in previous_results.items())
    return f"{ROLE_INSTRUCTIONS[agent]}\n\n# ORIGINAL TASK\n{task}\n\n# PREVIOUS RESULTS\n{prior or '(none)'}\n{_ws_block(workspace)}"


def _structured_results_available(agent: str, output_dir: Path) -> bool:
    """下游是否需要 / 是否有结构化上游结果：
    - workbuddy 依赖 hermes_result.json
    - codex 依赖 hermes_result.json + workbuddy_result.json
    缺失 → legacy fallback（旧任务 / 中断目录可继续运行）。
    """
    out = Path(output_dir)
    if agent == 'workbuddy':
        return (out / 'hermes_result.json').exists()
    if agent == 'codex':
        return (out / 'hermes_result.json').exists() and (out / 'workbuddy_result.json').exists()
    return False


def build_prompt_measured(
    agent: str,
    task: str,
    previous_results: dict[str, str],
    workspace: Path | None = None,
    output_dir: Path | None = None,
    task_path=None,
    task_hash: str | None = None,
) -> tuple[str, dict]:
    """构建 stage prompt；返回 (prompt, metrics)。

    metrics = {embedded_artifact_count, referenced_artifact_count}（Requirement 10）。
    """
    if agent == 'hermes':
        return _hermes_prompt(task, workspace, task_path, task_hash)
    if output_dir is not None and _structured_results_available(agent, Path(output_dir)):
        return _packet_prompt(agent, task, previous_results, workspace, Path(output_dir), task_path, task_hash)
    prompt = legacy_build_prompt(agent, task, previous_results, workspace)
    metrics = {
        'embedded_artifact_count': len(previous_results),
        'referenced_artifact_count': 0,
    }
    # FIX-002 Req 8（No Silent Information Loss）：结构化 summary 缺失（legacy 目录 /
    # 中断目录）→ legacy 全文嵌入 fallback 之上，显式标记缺失 + 回退语义，
    # 不得让下游把"没有 JSON"当成"没有 findings/warnings"。
    missing = _missing_structured_upstream(agent, Path(output_dir)) if output_dir is not None else []
    if missing:
        note = (
            '\n\n# STRUCTURED SUMMARY 缺失（FALLBACK_EMBEDDED）\n'
            '- 缺失: ' + ', '.join(f'{a}_result.json' for a in missing) + '\n'
            '- 已回退到 legacy 全文嵌入（无信息丢失）；上游 narrative 全文即验证真相。\n'
            '- 缺失结构化 summary 不代表"确认没有 findings/warnings"；'
            'findings/warnings 一律视为 UNKNOWN，以上游 narrative 为准。'
        )
        prompt = prompt + note
    return prompt, metrics


def _missing_structured_upstream(agent: str, output_dir: Path) -> list[str]:
    """当前 agent 缺失哪些上游结构化 result.json（用于显式标注）。"""
    out = Path(output_dir)
    if agent == 'workbuddy':
        return ['hermes'] if not (out / 'hermes_result.json').exists() else []
    if agent == 'codex':
        missing = []
        if not (out / 'hermes_result.json').exists():
            missing.append('hermes')
        if not (out / 'workbuddy_result.json').exists():
            missing.append('workbuddy')
        return missing
    return []


def build_prompt(agent: str, task: str, previous_results: dict[str, str], workspace: Path | None = None,
                 output_dir: Path | None = None, task_path=None, task_hash: str | None = None) -> str:
    """构建 stage prompt（Stage Context Packet 协议；旧调用保持兼容）。"""
    prompt, _ = build_prompt_measured(agent, task, previous_results, workspace, output_dir, task_path, task_hash)
    return prompt


def _registry_path(key: int, subkey: str, name: str = 'Path') -> str:
    try:
        with winreg.OpenKey(key, subkey) as k:
            return winreg.QueryValueEx(k, name)[0] or ''
    except OSError:
        return ''


def _windows_path() -> str:
    """Windows 新会话 PATH：用户 PATH + 机器 PATH（不依赖调用方 shell 的 PATH 格式）。"""
    user = _registry_path(winreg.HKEY_CURRENT_USER, 'Environment')
    machine = _registry_path(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')
    return ';'.join(filter(None, [user, machine]))


def _require(cmd: str) -> str:
    found = shutil.which(cmd, path=_windows_path())
    if not found and cmd == 'codex':
        # real-world hotfix：Codex 自动升级会更换 hash 版本目录，
        # registry PATH 可能残留旧目录导致 PATH discovery 失效。
        # 仅对 codex 增加受控 fallback（不改变 hermes / codebuddy 解析）。
        found = _codex_fallback()
    if not found:
        raise RuntimeError(f'MISSING_COMMAND: {cmd}')
    return found


CODEX_FALLBACK_DIR = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'


def _codex_fallback() -> str | None:
    """Windows Codex known-install fallback：%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe。

    多版本 hash 目录按 mtime 最新选当前有效版本（新版本目录更新时间更近）；
    0 candidate 或 candidate 不可用 → None（调用方保持 MISSING_COMMAND 语义）。
    """
    try:
        if not CODEX_FALLBACK_DIR.is_dir():
            return None
        candidates = [
            d / 'codex.exe'
            for d in CODEX_FALLBACK_DIR.iterdir()
            if d.is_dir() and (d / 'codex.exe').is_file()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])
    except OSError:
        return None


# TASK-011：WorkBuddy retry telemetry 一次性槽位。run_agent 执行后由 runner 读取
# （pop 语义；单线程 runner 内安全）。保持 run_agent 调用签名不变，不破坏既有
# (agent, prompt, workspace) mock 形态。
_workbuddy_telemetry: dict | None = None


def pop_workbuddy_telemetry() -> dict | None:
    """取出最近一次 WorkBuddy retry 执行的 telemetry（一次性；无 → None）。"""
    global _workbuddy_telemetry
    value = _workbuddy_telemetry
    _workbuddy_telemetry = None
    return value


def _workbuddy_invocation(prompt: str, env: dict, model: str | None = None) -> tuple[list[str], str, dict]:
    """WorkBuddy/CodeBuddy 精确 invocation（single source of truth，TASK-011）。

    官方 headless：``-p`` 为 print 模式；完整 prompt 走 stdin（input=），
    避免 50KB+ 长 prompt 超出 Windows 命令行长度限制（WinError 206）。
    retry 的每次 attempt 复用同一 (args, stdin_data, env)——绝不换 provider、
    不升级付费层级、不修改用户配置。

    A4（TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001）：``model`` 非 None
    时精确追加 ``--model <model>``（恰好一个 --model；无 --effort / 无
    provider override / 无 fallback）。``model`` 由调用方（runner）从
    AAF_WORKBUDDY_MODEL env 覆盖读取——本函数保持纯参数语义，不自行读 env。
    """
    exe = _require('codebuddy')
    args = [exe, '-p', '--output-format', 'text', '-y']
    if model is not None:
        args += ['--model', model]
    stdin_data = prompt
    env['CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS'] = '1'
    return args, stdin_data, env


def run_agent(agent: str, prompt: str, workspace: Path, timeout: float | None = None) -> str:
    global _workbuddy_telemetry
    _workbuddy_telemetry = None  # 每次调用重置（单线程 runner 内安全）
    workspace = workspace.resolve()
    # v0.5 COST-STOP-LOSS-001：显式 timeout 参数优先（既有调用方/test 语义不变）；
    # None → env override 或按 agent 的有界默认（hermes 无 Risk 上下文 = 保守
    # 1800s，Risk 分级档 1200–2400s；codex 600s——evidence-based，见
    # stop_loss.resolve_agent_attempt_timeout；runner 在 Hermes stage 会以
    # AAF_HERMES_ATTEMPT_TIMEOUT env 注入 Risk 分级值，此处解析生效）。
    # WorkBuddy 不消费该 timeout（retry 层以 AAF_WORKBUDDY_* 自管）。
    if timeout is None:
        timeout = stop_loss_mod.resolve_agent_attempt_timeout(agent)
    # v0.5 COST-STOP-LOSS-001-FIX-001（shared Hermes stage deadline——Codex
    # REQUEST_CHANGE blocker 收口）：original invocation 与 A5 FREE/PAID
    # fallback 共享 runner 设置的同一个绝对 stage deadline。每次 subprocess
    # 创建前：effective_timeout = min(per_attempt_timeout, remaining_stage_budget)
    # （Requirement 4/8）——fallback 绝不能重启一个完整 per-attempt timeout；
    # remaining ≤ 0 → 以 subprocess.TimeoutExpired 有界早停（不 spawn child，
    # 分类路径与真实 timeout 相同：ATTEMPT_TIMEOUT）。deadline env 只由 runner
    # 在 Hermes stage 期间设置/还原；absent → 本段 no-op（既有语义零变化；
    # codex/workbuddy stage、直接调用本模块的测试均不受影响）。
    remaining = stop_loss_mod.hermes_stage_remaining_seconds()
    if remaining is not None:
        if remaining <= 0.0:
            raise subprocess.TimeoutExpired(agent, timeout)
        timeout = min(timeout, remaining)
    # 子进程统一使用 Windows 新会话 PATH；workbuddy 额外禁用后台任务
    env = {**os.environ, 'PATH': _windows_path()}
    if agent == 'hermes':
        exe = _require('hermes')
        # hermes v0.20.1 无 --query-file；用 -q 单查询 + -Q 静默 + --source tool 隔离
        args = [exe, 'chat', '--in', str(workspace), '-q', prompt, '-Q', '--ignore-rules', '--source', 'tool']
        # v0.5 A0 Paid Guard：AAF_HERMES_MODEL（+ AAF_HERMES_PROVIDER）显式覆盖时
        # 透传给实际 invocation，保证 guard 解析的 effective model == 实际调用模型
        # （无覆盖时 args 与旧版完全一致；不修改 Hermes 全局 config）。
        ov_model = os.environ.get(cost_guard_mod.ENV_MODEL, '').strip()
        if ov_model:
            args += ['-m', ov_model]
            ov_provider = os.environ.get(cost_guard_mod.ENV_PROVIDER, '').strip()
            if ov_provider:
                args += ['--provider', ov_provider]
        stdin_data = None
    elif agent == 'workbuddy':
        # TASK-011：WorkBuddy stage 走有界 transient retry（transport 层）。
        # invocation 只构建一次，每次 attempt 复用同一 (args, stdin_data, env)——
        # same agent / same current CodeBuddy model & default config / same prompt /
        # same workspace / same execution role；绝不换模型/provider/付费层级。
        # timeout 参数对 workbuddy 不再生效：由 AAF_WORKBUDDY_* 策略控制
        # （per-attempt timeout / max_attempts / backoff / overall stage budget）。
        # A4 active economic routing（TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001）：
        # runner 在 routing_applied 时设置 AAF_WORKBUDDY_MODEL 覆盖；此处读取并
        # 把 ``--model <value>`` 精确追加到 invocation。无覆盖 → model=None →
        # 与 A4 之前完全一致（CodeBuddy Auto）。transport retry 复用同一 args
        # （含 --model）——绝不退回 Auto / 不换模型（无 silent fallback）。
        model_override = os.environ.get(ENV_WORKBUDDY_MODEL, "").strip() or None
        try:
            args, stdin_data, env = _workbuddy_invocation(prompt, env, model=model_override)
        except RuntimeError as exc:
            if 'MISSING_COMMAND' in str(exc):
                # 永久性（missing executable）：快速失败，不无意义 retry
                err = permanent_stage_error(
                    f'WorkBuddy stage cannot start (permanent, no retry): {exc}',
                    retry_reason=f'missing executable: {exc}',
                )
                _workbuddy_telemetry = err.telemetry
                raise err from exc
            raise
        try:
            output, telemetry = run_workbuddy_with_retry(args, env, stdin_data, workspace)
        except WorkBuddyStageError as exc:
            _workbuddy_telemetry = exc.telemetry or None
            raise
        _workbuddy_telemetry = telemetry
        return output
    elif agent == 'codex':
        exe = _require('codex')
        args = [exe, 'exec', '--sandbox', 'read-only', '--cd', str(workspace), '--skip-git-repo-check', '-']
        stdin_data = prompt
    else:
        raise ValueError(f'Unknown agent: {agent}')

    proc = subprocess.run(
        args,
        cwd=workspace,
        input=stdin_data,
        text=True,
        encoding='utf-8',
        errors='replace',
        capture_output=True,
        timeout=timeout,
        env=env,
        **no_console_kwargs(),  # Windows: CREATE_NO_WINDOW，抑制 Agent CLI 新建黑色 console 窗口
    )
    if proc.returncode != 0:
        raise RuntimeError(f'{agent} failed (exit={proc.returncode})\nSTDERR:\n{proc.stderr[-4000:]}')
    out = proc.stdout.strip()
    if not out:
        # exit 0 但无输出（如未认证的 CLI）也必须视为失败，不能静默 PASS
        raise RuntimeError(f'{agent} produced empty output (exit=0)\nSTDERR:\n{proc.stderr[-4000:]}')
    return out
