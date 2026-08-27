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
) -> dict:
    """确定性派生 stage 结构化结果（Requirement 5）。

    只记录 Framework 可验证的事实，不解析 / 不虚构 LLM 正文语义：
    - status：result 有效 → SUCCESS，无效（空 / FRAMEWORK_ERROR）→ FAILED
    - verdict / blocking_rework：由结论词与 report.verdict_blocked 派生
    - commit / changed_files：调用方传入的真实 git 事实（head_before / head_after）
    - tests / findings / warnings：框架无法确定性派生 → 显式 None / 空列表，
      真实内容保留在 <agent>_result.md narrative（evidence_paths 可追溯）
    """
    output_dir = Path(output_dir)
    body = result_text.strip()
    valid = bool(body) and not body.startswith("FRAMEWORK_ERROR")
    changed = list(changed_files or [])
    return {
        "protocol": PROTOCOL_VERSION,
        "agent": agent,
        "status": "SUCCESS" if valid else "FAILED",
        "verdict": _derive_verdict(agent, result_text),
        "blocking_rework": verdict_blocked(agent, result_text),
        "commit": head_after,
        "commit_changed": bool(head_before and head_after and head_before != head_after),
        "tests": None,  # 框架不猜测；真实测试证据在 narrative / evidence paths
        "changed_files": changed,
        "evidence_paths": [
            str(output_dir / f"{agent}_result.md"),
            str(output_dir / f"{agent}_result.json"),
        ],
        "findings": [],   # 真实 findings 在 narrative（summary 仅导航）
        "warnings": [],   # 真实 warnings 在 narrative（summary 仅导航）
        "summary": _summarize(result_text),
        "narrative_path": str(output_dir / f"{agent}_result.md"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
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
) -> Path:
    """写 ``context_manifest.json``（Requirement 6）。

    - TASK path + hash
    - 每个 stage 的 result_md / result_json path + hash
    - workspace / HEAD
    - 每 stage prompt 的 size 指标（Requirement 10）
    """
    output_dir = Path(output_dir)
    manifest = {
        "protocol": PROTOCOL_VERSION,
        "task": {
            "path": str(task_path),
            "hash": task_hash,
            "bytes": task_bytes,
        },
        "workspace": str(workspace),
        "head": head,
        "stages": stages,
        "prompts": prompts,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
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
