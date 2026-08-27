"""AI Agent Framework — Stage Context Packet Protocol（AAF-MAINT-CONTEXT-001）。

职责：
- 为每个 Agent stage 生成结构化短结果 ``<agent>_result.json``（机器可读；
  ``<agent>_result.md`` 长报告继续保留用于追溯，但不再默认全文注入下游 prompt）
- 生成 ``context_manifest.json``（TASK path+hash、stage result paths+hashes、
  workspace、HEAD、prompt 指标）——确保引用模式不会因为文件后来变化而失去可追溯性
- 引用完整性检查（引用可解析 / hash 匹配）
- Semantic Coverage Guard（压缩不丢信息：unique requirement / safety invariant /
  acceptance semantics 覆盖率检查）
- Context size 测量（prompt chars/bytes、embedded / referenced artifact counts）

设计依据：docs/internal/AAF_TASK_EXECUTION_POLICY.md（Anti-Bloat Policy）。
要点：
- TASK = current delta；Repository 已有信息优先引用 path/section，不重复全文
- 摘要只用于导航，Repository artifacts 才是验证真相
- 缺失引用 → 显式 fallback 到必要全文或失败，不得静默缺上下文继续审查
- 本模块只做确定性本地操作（无 LLM / 无 Agent / 无网络）
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .git_status import SYNC_SYNCED, compute_sync
from .report import verdict_blocked

PROTOCOL_VERSION = "packet/1"

# 结构化 stage result 的最小字段集合（Requirement 5）
STAGE_FIELDS = (
    "agent",
    "status",
    "verdict",
    "blocking_rework",
    "commit",
    "tests",
    "changed_files",
    "evidence_paths",
    "findings",
    "warnings",
)

_SUMMARY_LIMIT = 400

# ---------- Machine-Readable Stage Summary 契约（Requirement 7） ----------
# Agent 答复末尾的可解析结构化块。Framework 只接受经 schema validation 的结果；
# 缺失 / 损坏 / 与 narrative 冲突 → 显式 PARTIAL/UNKNOWN，不得伪装为空数组。
STRUCTURED_RESULT_BEGIN = "AAF_STRUCTURED_RESULT_BEGIN"
STRUCTURED_RESULT_END = "AAF_STRUCTURED_RESULT_END"
_STRUCTURED_TAIL_RE = re.compile(
    re.escape(STRUCTURED_RESULT_BEGIN) + r"\s*(\{.*?\})\s*" + re.escape(STRUCTURED_RESULT_END),
    re.DOTALL,
)

# 每 agent 的结构化块 schema（必填 / 可选 / 类型约束）
_STRUCTURED_SCHEMAS: dict[str, dict] = {
    "hermes": {
        "required": ("status",),
        "optional": ("commit", "changed_files", "warnings", "findings"),
        "types": {
            "status": str,
            "commit": (str, type(None)),
            "changed_files": list,
            "warnings": list,
            "findings": list,
        },
    },
    "workbuddy": {
        "required": ("verdict", "blocking_rework", "findings", "warnings"),
        "optional": (),
        "types": {
            "verdict": str,
            "blocking_rework": bool,
            "findings": list,
            "warnings": list,
        },
    },
    "codex": {
        "required": ("verdict", "blocking_rework", "findings", "warnings"),
        "optional": (),
        "types": {
            "verdict": str,
            "blocking_rework": bool,
            "findings": list,
            "warnings": list,
        },
    },
}

# structured_summary_status 取值：
# NOT_PROVIDED / MALFORMED / COMPLETE / CONSISTENCY_VIOLATION
SUMMARY_STATUS_NOT_PROVIDED = "NOT_PROVIDED"
SUMMARY_STATUS_MALFORMED = "MALFORMED"
SUMMARY_STATUS_COMPLETE = "COMPLETE"
SUMMARY_STATUS_VIOLATION = "CONSISTENCY_VIOLATION"

# ---------- Remote Sync 语义（Requirement 4 / 5） ----------
# 预先允许的 untracked local artifacts：不得单独导致 Task Remote Sync 失败
PRE_ALLOWED_UNTRACKED = (
    ".aaf/",
    "scripts/start_bridge_hidden.vbs",
    "AAF_TASK004_PROCESS_CHECK.txt",
)


# ---------- hash / size ----------

def sha256_text(text: str) -> str:
    """UTF-8 文本 SHA-256（manifest 引用完整性用）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str | None:
    """文件内容 SHA-256；不可读 → None（调用方必须显式处理缺失引用）。"""
    try:
        return sha256_text(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def file_bytes(path: Path | str) -> int | None:
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


# ---------- git 事实（确定性；非 git 仓库优雅降级） ----------

def git_head(workspace: Path | str) -> str | None:
    """workspace 当前 HEAD；非 git 仓库 / 失败 → None（不抛出，不虚构）。

    只用于 manifest 可观测性（非验证 truth）；任何异常（含 subprocess 被 mock
    的测试环境）都必须优雅降级，绝不阻断 runner 主链路。
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(workspace), capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def git_changed_files(workspace: Path | str) -> list[str]:
    """workspace git status --porcelain 行；非 git 仓库 / 失败 → []。"""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(workspace), capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


# ---------- 结构化 stage result ----------

def _derive_verdict(agent: str, body: str) -> str | None:
    """从 narrative 中提取显式结论标记（全大写）；无 → None。

    只认官方结论词（WorkBuddy: PASS / PASS_WITH_WARNING / FAIL；
    Codex: APPROVE / REQUEST_CHANGE）；Hermes 是 Executor，无 verdict。
    """
    if not body.strip() or body.lstrip().startswith("FRAMEWORK_ERROR"):
        return None
    if agent == "workbuddy":
        m = re.search(r"\b(PASS_WITH_WARNING|PASS|FAIL)\b", body)
        return m.group(1) if m else None
    if agent == "codex":
        m = re.search(r"\b(APPROVE|REQUEST_CHANGE)\b", body)
        return m.group(1) if m else None
    return None


def _summarize(text: str, limit: int = _SUMMARY_LIMIT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


def build_stage_result(
    *,
    agent: str,
    result_text: str,
    output_dir: Path | str,
    head_before: str | None = None,
    head_after: str | None = None,
    changed_files: list[str] | None = None,
    structured: dict | None = None,
    structured_status: str = SUMMARY_STATUS_NOT_PROVIDED,
) -> dict:
    """确定性派生 stage 结构化结果（Requirement 5 / FIX-002 Req 6–9）。

    只记录 Framework 可验证的事实，不解析 / 不虚构 LLM 正文语义：
    - status：result 有效 → SUCCESS，无效（空 / FRAMEWORK_ERROR）→ FAILED
    - verdict / blocking_rework：优先来自 schema-validated 结构化块；未提供时
      由结论词与 report.verdict_blocked 派生（narrative fallback）
    - commit / changed_files：调用方传入的真实 git 事实（head_before / head_after）
    - findings / warnings：**未知就是未知** —— Agent 未提供结构化块（或块损坏 /
      一致性违规）时为 None（UNKNOWN），绝不伪装为空数组（FIX-002 Req 6）。
      `[]` 只出现在结构化块中 Agent 显式声明“确认没有”的情况。
    - summary_complete / structured_summary_status：结构化块经 schema validation
      且与 narrative 一致性 guard 通过 → COMPLETE；否则 PARTIAL/UNKNOWN
      （下游必须 reference/read narrative，不得把空 findings/warnings 当完整事实）。
    """
    output_dir = Path(output_dir)
    body = result_text.strip()
    valid = bool(body) and not body.startswith("FRAMEWORK_ERROR")
    changed = list(changed_files or [])

    findings: list | None = None
    warnings: list | None = None
    verdict = _derive_verdict(agent, result_text)
    blocking_rework = verdict_blocked(agent, result_text)
    summary_complete = False
    status = structured_status

    if structured is not None and isinstance(structured, dict):
        if "verdict" in structured and structured["verdict"]:
            verdict = structured["verdict"]
        if "blocking_rework" in structured:
            blocking_rework = bool(structured["blocking_rework"])
        findings = list(structured.get("findings") or [])
        warnings = list(structured.get("warnings") or [])
        # Narrative / JSON 一致性 guard（FIX-002 Req 9）：structured 声明 complete 时，
        # narrative 显式 warning / blocking finding / REQUEST_CHANGE / FAIL 不得消失
        violations = check_narrative_json_consistency(agent, result_text, structured)
        if violations:
            status = SUMMARY_STATUS_VIOLATION
            summary_complete = False
        else:
            status = SUMMARY_STATUS_COMPLETE
            summary_complete = True

    return {
        "protocol": PROTOCOL_VERSION,
        "agent": agent,
        "status": "SUCCESS" if valid else "FAILED",
        "verdict": verdict,
        "blocking_rework": blocking_rework,
        "commit": head_after,
        "commit_changed": bool(head_before and head_after and head_before != head_after),
        "tests": None,  # 框架不猜测；真实测试证据在 narrative / evidence paths
        "changed_files": changed,
        "evidence_paths": [
            str(output_dir / f"{agent}_result.md"),
            str(output_dir / f"{agent}_result.json"),
        ],
        "findings": findings,   # None = UNKNOWN（未提取）；[] 仅当 Agent 显式确认没有
        "warnings": warnings,   # None = UNKNOWN（未提取）；[] 仅当 Agent 显式确认没有
        "summary_complete": summary_complete,
        "structured_summary_status": status,
        "summary": _summarize(result_text),
        "narrative_path": str(output_dir / f"{agent}_result.md"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------- Machine-Readable Stage Summary：提取 / schema validation（FIX-002 Req 7） ----------

def extract_structured_tail(text: str) -> tuple[dict | None, str]:
    """从 narrative 提取结构化块。返回 (data, status)。

    status: NOT_PROVIDED（无块）/ MALFORMED（存在 BEGIN 标记但 JSON 损坏或
    块结构不完整）/ OK。注意：JSON 可解析但 schema 不合法 → 仍返回 OK，由
    validate_structured_summary 判定（MALFORMED 语义合并，调用方负责）。
    """
    if not text:
        return None, SUMMARY_STATUS_NOT_PROVIDED
    m = _STRUCTURED_TAIL_RE.search(text)
    if not m:
        if STRUCTURED_RESULT_BEGIN in text:
            # 块标记存在但结构不完整 / JSON 损坏 → 显式 MALFORMED（不是"未提供"）
            return None, SUMMARY_STATUS_MALFORMED
        return None, SUMMARY_STATUS_NOT_PROVIDED
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None, SUMMARY_STATUS_MALFORMED
    if not isinstance(data, dict):
        return None, SUMMARY_STATUS_MALFORMED
    return data, "OK"


def validate_structured_summary(agent: str, data: dict) -> tuple[dict | None, list[str]]:
    """schema validation（FIX-002 Req 7：Framework 只接受经 schema validation 的
    structured summary）。返回 (cleaned dict, errors)；errors 非空 → 调用方按
    MALFORMED 处理（structured 内容不被接受）。
    """
    schema = _STRUCTURED_SCHEMAS.get(agent)
    if schema is None:
        return None, [f"unknown agent {agent!r}（无结构化块 schema）"]
    errors: list[str] = []
    cleaned: dict = {}
    for field_name in (*schema["required"], *schema["optional"]):
        if field_name not in data:
            if field_name in schema["required"]:
                errors.append(f"missing required field {field_name!r}")
            continue
        value = data[field_name]
        expected = schema["types"].get(field_name)
        if expected is not None and not isinstance(value, expected):
            errors.append(
                f"field {field_name!r} type {type(value).__name__} != expected {expected!r}"
            )
            continue
        if isinstance(value, list):
            if not all(isinstance(v, str) for v in value):
                errors.append(f"field {field_name!r} 的元素必须是字符串")
                continue
            value = [v for v in value]  # 原样保留
        cleaned[field_name] = value
    if errors:
        return None, errors
    return cleaned, []


def extract_and_validate_structured(agent: str, text: str) -> tuple[dict | None, str]:
    """一步完成提取 + schema validation。返回 (data, status)：
    status ∈ NOT_PROVIDED / MALFORMED / OK（data 为 validated dict）。
    """
    data, status = extract_structured_tail(text)
    if status == "OK":
        data, errors = validate_structured_summary(agent, data)
        if errors:
            return None, SUMMARY_STATUS_MALFORMED
        return data, "OK"
    return None, status


# ---------- Narrative / JSON 一致性 guard（FIX-002 Req 9） ----------

_NARRATIVE_WARNING_RE = re.compile(
    r"(?im)^[ \t]*(?:W\d+[ \t]*[:：]|WARNING[ \t]*[:：]|⚠|warning[ \t]*[:：])"
)
_NARRATIVE_FAIL_RE = re.compile(r"\b(REQUEST_CHANGE|FAIL)\b")


def narrative_warning_count(text: str) -> int:
    """narrative 中显式 warning 标记数（W1:/W2:/WARNING:/⚠/warning: 行首标记）。"""
    return len(_NARRATIVE_WARNING_RE.findall(text or ""))


def check_narrative_json_consistency(agent: str, narrative: str, structured: dict) -> list[str]:
    """一致性 guard：structured summary 声明 complete 时，narrative 中显式的
    blocking finding / warning / REQUEST_CHANGE / FAIL 不得在 JSON 中消失。

    返回违规列表（空 = 一致）。检测到违规 → 调用方标记 CONSISTENCY_VIOLATION /
    summary_complete=False（下游必须读 narrative，不得把空 JSON 当完整事实）。
    """
    violations: list[str] = []
    if not isinstance(structured, dict):
        return violations
    narrative = narrative or ""

    # 1) warnings：narrative 显式 warning 标记不得在 structured warnings 消失
    n_warn = narrative_warning_count(narrative)
    s_warn = structured.get("warnings")
    if n_warn > 0 and isinstance(s_warn, list):
        if len(s_warn) == 0:
            violations.append(
                f"narrative 有 {n_warn} 处显式 warning 标记但 structured warnings 为空"
            )
        elif n_warn > len(s_warn):
            violations.append(
                f"narrative warning 标记数（{n_warn}）> structured warnings 数（{len(s_warn)}）"
            )

    # 2) verdict / blocking：narrative 显式失败结论不得在 JSON 消失
    if agent in ("workbuddy", "codex"):
        n_verdict = _derive_verdict(agent, narrative)
        s_verdict = structured.get("verdict")
        if n_verdict and s_verdict and n_verdict != s_verdict:
            violations.append(f"narrative verdict {n_verdict} != structured verdict {s_verdict}")
        has_fail = bool(_NARRATIVE_FAIL_RE.search(narrative))
        if has_fail and not _narrative_has_positive_verdict(agent, narrative):
            # narrative 有显式 REQUEST_CHANGE/FAIL 且无通过结论 → structured 必须反映 blocking
            blocking = structured.get("blocking_rework")
            if s_verdict not in ("REQUEST_CHANGE", "FAIL") or blocking is not True:
                violations.append(
                    "narrative 有显式 REQUEST_CHANGE/FAIL 且无通过结论，"
                    "但 structured 未反映 blocking"
                )
    return violations


def _narrative_has_positive_verdict(agent: str, narrative: str) -> bool:
    """narrative 是否有明确通过结论（PASS/PASS_WITH_WARNING/APPROVE）——
    此时 narrative 中的历史 FAIL/REQUEST_CHANGE 引用不视为当前阻断。"""
    if agent == "workbuddy":
        return bool(re.search(r"\bPASS_WITH_WARNING\b|\bPASS\b", narrative))
    if agent == "codex":
        return bool(re.search(r"\bAPPROVE\b", narrative))
    return False


# ---------- Remote Sync 语义（FIX-002 Req 4 / 5） ----------

def _is_pre_allowed_untracked(line: str) -> bool:
    """porcelain 行是否属于预先允许的 untracked local artifact（不得单独导致失败）。"""
    if len(line) < 3 or line[:2].strip() != "??":
        return False
    path = line[3:].strip()
    p = path.rstrip("/")
    for allowed in PRE_ALLOWED_UNTRACKED:
        if allowed.endswith("/"):
            if p == allowed.rstrip("/") or p.startswith(allowed):
                return True
        elif p == allowed:
            return True
    return False


def _porcelain_all(workspace: Path | str) -> list[str]:
    """git status --porcelain -uall（untracked 逐文件列出，不折叠目录）。

    tracked_tree_status 专用：预允许 untracked artifacts 需要逐文件判定
    （如 scripts/start_bridge_hidden.vbs 在新目录下会折叠为 "?? scripts/"）。
    """
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=str(workspace), capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


def tracked_tree_status(workspace: Path | str) -> tuple[str, list[str]]:
    """Tracked Working Tree：CLEAN / DIRTY（忽略预允许 untracked artifacts）。

    返回 (状态, 违规 porcelain 行)。预允许项（.aaf/、start_bridge_hidden.vbs、
    AAF_TASK004_PROCESS_CHECK.txt）单独存在 → CLEAN。
    """
    lines = _porcelain_all(workspace)
    if not lines:
        return "CLEAN", []
    offending = [line for line in lines if not _is_pre_allowed_untracked(line)]
    return ("DIRTY" if offending else "CLEAN"), offending


def remote_sync_state(workspace: Path | str) -> dict:
    """Remote Sync 真值（FIX-002 Req 4）：区分 commit graph sync 与 tracked tree。

    - commit_sync: SYNCED / UNSYNCED / UNKNOWN（HEAD==origin/main 且 ahead/behind=0/0
      只是 commit graph synced，不代表本轮 tracked 修改已同步）
    - tracked_working_tree: CLEAN / DIRTY / UNKNOWN
    - task_remote_sync: **SYNCED 仅当 commit_sync=SYNCED 且 tracked tree=CLEAN**
      （本轮 tracked 修改必须 commit + push 后才能满足；预允许 untracked
      artifacts 不阻断）；否则 UNSYNCED / NOT_APPLICABLE（非 git 仓库）
    """
    ws = str(workspace)
    is_git = False
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ws, capture_output=True, text=True, timeout=15,
        )
        is_git = r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        is_git = False

    commit_sync = "UNKNOWN"
    ahead = behind = 0
    has_upstream = False
    if is_git:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "@{u}"],
                cwd=ws, capture_output=True, text=True, timeout=15,
            )
            has_upstream = r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            has_upstream = False
        if has_upstream:
            try:
                r = subprocess.run(
                    ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
                    cwd=ws, capture_output=True, text=True, timeout=15,
                )
                parts = r.stdout.split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])
            except Exception:
                pass
            raw = compute_sync(ahead, behind, True)
            commit_sync = "SYNCED" if raw == SYNC_SYNCED else "UNSYNCED"

    tree, offending = tracked_tree_status(ws)
    if not is_git:
        task_remote_sync = "NOT_APPLICABLE"
    elif commit_sync == "SYNCED" and tree == "CLEAN":
        task_remote_sync = "SYNCED"
    else:
        task_remote_sync = "UNSYNCED"
    return {
        "is_git_repo": is_git,
        "commit_sync": commit_sync,
        "ahead": ahead,
        "behind": behind,
        "has_upstream": has_upstream,
        "tracked_working_tree": tree,
        "tracked_dirty_entries": offending,
        "task_remote_sync": task_remote_sync,
    }


def write_stage_result(output_dir: Path | str, stage: dict) -> Path:
    """写 ``<agent>_result.json``；返回该文件路径。"""
    output_dir = Path(output_dir)
    agent = stage.get("agent")
    if not agent:
        raise ValueError("stage result 缺少 agent 字段")
    path = output_dir / f"{agent}_result.json"
    path.write_text(
        json.dumps(stage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_stage_result(output_dir: Path | str, agent: str) -> dict | None:
    """读取 ``<agent>_result.json``；缺失 / 损坏 → None（调用方显式处理）。"""
    path = Path(output_dir) / f"{agent}_result.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


# ---------- context manifest ----------

def _artifact_entry(path: Path) -> dict:
    return {
        "path": str(path),
        "hash": sha256_file(path),
        "bytes": file_bytes(path),
    }


def write_manifest(
    output_dir: Path | str,
    *,
    task_path: Path | str,
    task_hash: str,
    task_bytes: int,
    workspace: Path | str,
    head: str | None,
    stages: dict[str, dict],
    prompts: dict[str, dict],
    intake_task_path: Path | str | None = None,
) -> Path:
    """写 ``context_manifest.json``（Requirement 6 / FIX-003 Req 9）。

    - ``task``：execution snapshot 的 path + hash + bytes（= execution_task；
      legacy key 保留，两者始终一致）
    - ``execution_task``：immutable snapshot（TASK.snapshot.md）的 path + hash +
      bytes——**所有 downstream integrity check 的默认验证对象**
    - ``intake_task``：仅 provenance（active TASK 的原始 path，**无 hash**——
      不得出现第二个 hash authority；active 文件后续变化不影响 execution）
    - 每个 stage 的 result_md / result_json path + hash
    - workspace / HEAD；每 stage prompt 的 size 指标（Requirement 10）
    """
    output_dir = Path(output_dir)
    task_entry = {
        "path": str(task_path),
        "hash": task_hash,
        "bytes": task_bytes,
    }
    manifest: dict = {
        "protocol": PROTOCOL_VERSION,
        "task": dict(task_entry),
        "execution_task": dict(task_entry),
        "workspace": str(workspace),
        "head": head,
        "stages": stages,
        "prompts": prompts,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if intake_task_path:
        manifest["intake_task"] = {"path": str(intake_task_path)}
    path = output_dir / "context_manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_manifest(output_dir: Path | str) -> dict | None:
    path = Path(output_dir) / "context_manifest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def check_references(manifest: dict, base_dir: Path | str | None = None) -> list[str]:
    """引用完整性检查（Requirement 6 / 11）：所有引用 path 存在且 hash 匹配。

    返回问题列表（空 = 全部可解析）。base_dir 仅用于生成相对显示路径。
    """
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return ["context_manifest.json 不是有效 dict"]

    def _check(entry: dict | None, label: str) -> None:
        if not isinstance(entry, dict):
            problems.append(f"{label}: 缺少引用条目")
            return
        path = entry.get("path")
        if not path or not Path(path).exists():
            problems.append(f"{label}: 引用文件缺失 -> {path}")
            return
        cur = sha256_file(path)
        expected = entry.get("hash")
        if expected and cur and cur != expected:
            problems.append(f"{label}: hash 不匹配（引用时 {expected}，当前 {cur}）-> {path}")

    task = manifest.get("task")
    if isinstance(task, dict):
        _check(task, "task")
    else:
        problems.append("manifest 缺少 task 引用")
    # FIX-003 Req 9：execution_task 是 downstream integrity 的默认验证对象；
    # 两者指向同一 immutable snapshot。intake_task 仅 provenance（active 文件
    # 可能被移动/归档），不参与完整性校验——其变化不得破坏 execution 引用。
    execution_task = manifest.get("execution_task")
    if isinstance(execution_task, dict):
        _check(execution_task, "execution_task")
    for agent, entry in (manifest.get("stages") or {}).items():
        if isinstance(entry, dict):
            _check(entry.get("result_md"), f"stage {agent} result_md")
            _check(entry.get("result_json"), f"stage {agent} result_json")
        else:
            problems.append(f"stage {agent}: 缺少引用条目")
    return problems


def references_resolvable(manifest: dict, base_dir: Path | str | None = None) -> bool:
    """引用完整性快速判定（供 downstream 使用）。"""
    return not check_references(manifest, base_dir)


# ---------- Semantic Coverage Guard（Requirement 3） ----------

@dataclass
class CoverageResult:
    covered: int = 0
    total: int = 0
    missing: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return 1.0 if self.total == 0 else self.covered / self.total

    def to_dict(self) -> dict:
        return {
            "covered": self.covered,
            "total": self.total,
            "ratio": round(self.ratio, 4),
            "missing": self.missing,
            "checks": self.checks,
        }


_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_SECTION_HEADER_RE = re.compile(
    r"^[ \t]*(?:#{1,2}[ \t]+\S|[A-Z][A-Za-z /()\-]{2,40}[:：])"
)
# 安全不变量关键词：不得 / 必须 / 禁止 / safety / invariant / 安全
_SAFETY_KEYWORDS = ("不得", "必须", "禁止", "safety", "invariant", "安全", "cannot", "must not")


def _section_lines(text: str, header: str) -> list[str]:
    """提取某字段节（如 Requirements / Acceptance）下的行，直到下一节标题。"""
    pat = re.compile(r"(?im)^[ \t]*" + re.escape(header) + r"[ \t]*[:：]?[ \t]*$")
    m = pat.search(text)
    if not m:
        return []
    lines: list[str] = []
    for line in text[m.end():].splitlines():
        s = line.strip()
        if not s:
            continue
        if _SECTION_HEADER_RE.match(s):
            break
        lines.append(s)
    return lines


def _extract_units(lines: list[str]) -> list[str]:
    """从节行中提取语义单元：编号项优先，其次顶层 bullet；去重保序。"""
    units: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = _NUMBERED_RE.match(line)
        if m:
            unit = m.group(1).strip()
        else:
            m = _BULLET_RE.match(line)
            if not m:
                continue
            unit = m.group(1).strip()
        if unit and unit not in seen:
            seen.add(unit)
            units.append(unit)
    return units


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def verify_semantic_coverage(original: str, compact: str) -> CoverageResult:
    """Semantic Coverage Guard：压缩是去重，不是删约束（Requirement 3）。

    检查三类语义单元在 compact 中是否逐字保留（归一化空白/大小写后）：
    - unique requirement coverage（Requirements 节编号/bullet 项）
    - safety invariant coverage（含 不得/必须/禁止/safety/invariant/安全 的单元）
    - acceptance semantics coverage（Acceptance 节单元）

    说明：本 Guard 是确定性本地检查，能捕获"整项删除"；若压缩改写措辞，
    语义等价性必须由 WorkBuddy 独立验证（Guard 不是语义证明）。
    """
    req_units = _extract_units(_section_lines(original, "Requirements"))
    acc_units = _extract_units(_section_lines(original, "Acceptance"))
    all_units = list(dict.fromkeys([*req_units, *acc_units]))
    safety_units = [u for u in all_units if any(k.lower() in u.lower() for k in _SAFETY_KEYWORDS)]

    compact_norm = _norm(compact)
    missing: list[str] = []
    checks: list[str] = []
    covered = 0
    for unit in all_units:
        if _norm(unit) in compact_norm:
            covered += 1
        else:
            missing.append(unit)
    checks.append(f"unique requirement coverage: {covered}/{len(all_units)}")

    safety_covered = sum(1 for u in safety_units if _norm(u) in compact_norm)
    checks.append(f"safety invariant coverage: {safety_covered}/{len(safety_units)}")

    acc_covered = sum(1 for u in acc_units if _norm(u) in compact_norm)
    checks.append(f"acceptance semantics coverage: {acc_covered}/{len(acc_units)}")

    return CoverageResult(
        covered=covered,
        total=len(all_units),
        missing=missing,
        checks=checks,
    )


# ---------- Context size 测量（Requirement 10） ----------

def measure_prompt(prompt: str, embedded_artifact_count: int = 0, referenced_artifact_count: int = 0) -> dict:
    """记录每 stage prompt 的 size 观测（无 tokenizer 时不虚构 token 值）。"""
    return {
        "chars": len(prompt),
        "bytes": len(prompt.encode("utf-8")),
        "embedded_artifact_count": embedded_artifact_count,
        "referenced_artifact_count": referenced_artifact_count,
    }


def compare_packet_sizes(old_chain_chars: int, new_chain_chars: int) -> dict:
    """before/after 对比（同一 fixture 上 old full-chain vs new packet）。"""
    return {
        "old_chain_chars": old_chain_chars,
        "new_chain_chars": new_chain_chars,
        "reduction_ratio": round(1 - new_chain_chars / old_chain_chars, 4)
        if old_chain_chars else None,
        "reduced": new_chain_chars < old_chain_chars,
    }
