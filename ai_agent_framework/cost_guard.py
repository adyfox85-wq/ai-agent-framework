"""AAF v0.5 A0 — Hermes Paid Guard（fail-closed，task-scoped 成本授权）。

TASK: AAF-v0.5-A0-PAID-GUARD-001
在 Hermes stage 真正创建 subprocess 之前执行：如果 effective Hermes model 是
付费或成本未知的远程/API 模型，则只有在存在**精确匹配的显式一次性授权**
（Task ID + Hermes stage + effective model（+ provider））时才放行；否则 fail
closed——Hermes 进程不启动，任务进入 WAITING（COST_APPROVAL_REQUIRED）。

设计规则（本模块只实现 A0 最小层，不实现 Routing / Registry / 自动选模型）：
1. 能力/安全优先于成本。
2. UNKNOWN 成本绝不视为 FREE。
3. 付费/未知模型调用必须显式用户授权。
4. 授权必须窄且 task-scoped：``AAF_COST_AUTH="<task_id>|<stage>|<model>[|<provider>]"``
   与解析出的 scope 做**整串精确匹配**（不是前缀/包含/正则）。
5. 无静默付费 fallback（不存在 fallback 分支）。
6. 决策不依赖额外 LLM 调用 / 网络请求：只读本地 CLI config 查询或环境变量。
7. 缓存/本地决策快速（决策耗时记录于 cost_guard.json 的 decision_ms）。
8. 不构建 Registry / Selection Engine（A1+ 范围）。

成本分类（刻意最小）：
- LOCAL_FREE：provider base_url 明确指向本机（127.0.0.1 / localhost / 0.0.0.0），
  或 provider == ollama 且无远程 base_url（verified local Ollama）。
- FREE：仅当 AAF 有**显式权威 FREE 元数据**（``AAF_COST_FREE_MODELS`` 环境变量，
  条目为精确 model 或 model@provider）。绝不根据模型名猜测免费。
- PAID_OR_UNKNOWN：任何不能证明为 FREE/LOCAL_FREE 的远程/API 模型。

授权表示（为何最小）：单环境变量 + 整串精确匹配。不引入文件子系统 / 数据库 /
长生命周期 token：env 只存在于发起进程，天然一次性（per-run）、无法被 runner
持久化自授权、Task ID 在 scope 内 → 对其他任务天然失效（不泄漏到后续任务）。

Hermes 全局 config 不被本模块修改（只读查询 ``hermes config get model`` 是
解析 effective model 的 fallback；env 覆盖优先）。

注：stage 目前只有 'hermes' 走本 guard（WorkBuddy / Codex 不在 A0 范围）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import winreg
from datetime import datetime
from pathlib import Path

from .subprocess_utils import no_console_kwargs

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "cost_guard.json"

# --- 环境变量契约（AAF 自有；不修改 Hermes 全局 config） ---
# effective model / provider 显式覆盖：guard 解析的 model == 实际 invocation model
# （runner 在 hermes 调用时透传 -m / --provider，见 adapters.run_agent）。
ENV_MODEL = "AAF_HERMES_MODEL"
ENV_PROVIDER = "AAF_HERMES_PROVIDER"
# 一次性显式授权：整串精确匹配 "<task_id>|<stage>|<model>[|<provider>]"
ENV_AUTH = "AAF_COST_AUTH"
# 显式权威 FREE 元数据：逗号分隔；条目 = 精确 model 或 model@provider。
# 缺省 = 没有任何模型被声明为 FREE（UNKNOWN 不视为 FREE）。
ENV_FREE_MODELS = "AAF_COST_FREE_MODELS"

# --- 成本分类（A0 刻意最小） ---
COST_LOCAL_FREE = "LOCAL_FREE"
COST_FREE = "FREE"
COST_PAID_OR_UNKNOWN = "PAID_OR_UNKNOWN"
COST_UNKNOWN = "COST_UNKNOWN"  # 内部：effective model 无法解析（fail closed）

# --- 决策（machine-readable state） ---
DECISION_ALLOWED_FREE = "ALLOWED_FREE"
DECISION_ALLOWED_AUTHORIZED_PAID = "ALLOWED_AUTHORIZED_PAID"
DECISION_BLOCKED_COST_APPROVAL = "BLOCKED_COST_APPROVAL"

STAGE_HERMES = "hermes"

# model_source：有证据才填具体值
MODEL_SOURCE_ENV = "env_override"
MODEL_SOURCE_CONFIG = "hermes_config"
MODEL_SOURCE_UNKNOWN = "unknown"

_LOCAL_HOST_HINTS = ("127.0.0.1", "localhost", "0.0.0.0")
_OLLAMA_PROVIDER = "ollama"

_SEPARATOR = "|"


# ---------------------------------------------------------------------------
# 只读环境工具（不发起网络 / 不发付费推理；Windows PATH 与 adapters 一致）
# ---------------------------------------------------------------------------


def _windows_path() -> str:
    """Windows 新会话 PATH：用户 PATH + 机器 PATH（registry；与 adapters 一致）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            user = winreg.QueryValueEx(k, "Path")[0] or ""
    except OSError:
        user = ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ) as k:
            machine = winreg.QueryValueEx(k, "Path")[0] or ""
    except OSError:
        machine = ""
    return ";".join(filter(None, [user, machine]))


def _find_cli(cmd: str) -> str | None:
    """解析 CLI 路径；找不到 → None（resolution 视为不可用，fail closed 路径）。"""
    try:
        return shutil.which(cmd, path=_windows_path())
    except Exception:
        return None


def _run_readonly(args: list[str], timeout: float = 15.0):
    """只读本地命令执行：capture-only、无输入、有界超时、Windows 无控制台窗口。

    返回 (exit_code, stdout, stderr)；调用本身失败 → None。绝不写配置。
    """
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **no_console_kwargs(),
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Effective model 解析（env 优先 → hermes config 只读查询）
# ---------------------------------------------------------------------------


def _parse_config_key_values(text: str) -> dict:
    """解析 ``key: value`` 行（首冒号分割）。解析失败 → {}（不发明）。"""
    out: dict = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or ":" not in s:
            continue
        key, _, value = s.partition(":")
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z0-9_.\-]+$", key):
            continue
        out[key] = value.strip()
    return out


def _resolve_from_hermes_config() -> dict | None:
    """``hermes config get model`` 只读查询（Hermes config 的 resolved default）。

    返回 {"model", "provider", "base_url"}；失败 → None（fail closed，不猜测）。
    """
    exe = _find_cli("hermes")
    if not exe:
        return None
    res = _run_readonly([exe, "config", "get", "model"])
    if res is None:
        return None
    code, out, _err = res
    if code != 0:
        return None
    parsed = _parse_config_key_values(out)
    model = parsed.get("default")
    if not model:
        return None
    return {
        "model": model,
        "provider": parsed.get("provider"),
        "base_url": parsed.get("base_url"),
    }


def resolve_effective_hermes() -> dict:
    """解析 Hermes stage 的 effective model / provider（不发起任何网络/LLM）。

    优先级：
    1. ``AAF_HERMES_MODEL``（+ ``AAF_HERMES_PROVIDER``）显式覆盖 —— 与 runner
       实际透传给 hermes 的参数一致（invocation-truth）。
    2. ``hermes config get model`` 只读查询（v0.4 model_observation 同款发现）。
    3. 都无法解析 → model=None（cost_class=COST_UNKNOWN → fail closed）。

    返回 dict：model / provider / base_url / model_source / notes。
    """
    model = os.environ.get(ENV_MODEL, "").strip()
    provider = os.environ.get(ENV_PROVIDER, "").strip()
    if model:
        return {
            "model": model,
            "provider": provider or None,
            "base_url": None,  # env 覆盖时不虚构 base_url（不参与 local 判定）
            "model_source": MODEL_SOURCE_ENV,
            "notes": [
                f"effective model pinned via {ENV_MODEL}"
                + (f" / provider via {ENV_PROVIDER}" if provider else "")
            ],
        }
    from_config = _resolve_from_hermes_config()
    if from_config:
        return {
            "model": from_config["model"],
            "provider": from_config.get("provider"),
            "base_url": from_config.get("base_url"),
            "model_source": MODEL_SOURCE_CONFIG,
            "notes": ["effective model from `hermes config get model` (read-only)"],
        }
    return {
        "model": None,
        "provider": None,
        "base_url": None,
        "model_source": MODEL_SOURCE_UNKNOWN,
        "notes": [
            "effective Hermes model cannot be resolved (no AAF_HERMES_MODEL override "
            "and `hermes config get model` unavailable/failed) — fail closed"
        ],
    }


# ---------------------------------------------------------------------------
# 成本分类（A0 刻意最小；绝不根据模型名推断免费）
# ---------------------------------------------------------------------------


def _parse_free_models(raw: str | None) -> list[str]:
    """解析 AAF_COST_FREE_MODELS：逗号分隔；条目 = 精确 model 或 model@provider。"""
    if not raw:
        return []
    return [e.strip() for e in raw.split(",") if e.strip()]


def _free_list_match(free_entries: list[str], model: str, provider: str | None) -> bool:
    """FREE 元数据精确匹配：裸 model 或 model@provider 形式。"""
    if model in free_entries:
        return True
    if provider and f"{model}@{provider}" in free_entries:
        return True
    return False


def classify_cost(
    model: str | None,
    provider: str | None,
    base_url: str | None,
    free_entries: list[str] | None = None,
) -> tuple[str, dict | None]:
    """A0 最小成本分类 → (cost_class, cost_metadata)。

    - base_url 明确本机 → LOCAL_FREE（evidence 来自 endpoint，不是促销表）
    - provider=ollama 且无远程 base_url → LOCAL_FREE（verified local Ollama；
      有非本机 base_url 时 Ollama 可能服务远程 → PAID_OR_UNKNOWN，fail closed）
    - 显式权威 FREE 元数据精确匹配 → FREE
    - 其余远程/API 模型 → PAID_OR_UNKNOWN（UNKNOWN 不视为 FREE）
    - model=None → COST_UNKNOWN（调用方 fail closed）
    """
    if model is None:
        return COST_UNKNOWN, {"evidence": "effective model unresolved"}
    if base_url and any(h in base_url for h in _LOCAL_HOST_HINTS):
        return COST_LOCAL_FREE, {
            "evidence": f"provider base_url={base_url} (local endpoint)",
            "note": "local inference; no per-token cash cost",
        }
    p = (provider or "").strip().lower()
    if p == _OLLAMA_PROVIDER:
        if not base_url:
            return COST_LOCAL_FREE, {
                "evidence": "provider=ollama with no base_url (verified local Ollama server)",
                "note": "local inference; no per-token cash cost",
            }
        return COST_PAID_OR_UNKNOWN, {
            "evidence": f"provider=ollama but base_url={base_url} is non-local — "
            "Ollama may be serving a remote endpoint; not verified local",
            "note": "fail closed: not treated as local",
        }
    if _free_list_match(free_entries or [], model, provider):
        return COST_FREE, {
            "evidence": "explicit authoritative FREE metadata match",
            "note": f"declared FREE via {ENV_FREE_MODELS}",
        }
    return COST_PAID_OR_UNKNOWN, {
        "evidence": "remote/API model with no authoritative FREE metadata",
        "note": "UNKNOWN/paid cost is never treated as FREE",
    }


# ---------------------------------------------------------------------------
# 授权 scope（整串精确匹配；任务 + stage + model（+ provider））
# ---------------------------------------------------------------------------


def scope_string(task_id: str, stage: str, model: str, provider: str | None) -> str:
    """授权 scope 规范化串：``<task_id>|<stage>|<model>[|<provider>]``。"""
    parts = [task_id, stage, model]
    if provider:
        parts.append(provider)
    return _SEPARATOR.join(parts)


def _auth_env_value() -> str | None:
    raw = os.environ.get(ENV_AUTH, "")
    value = raw.strip()
    return value or None


def _authorization_matches(auth: str | None, scope: str) -> bool:
    """显式一次性授权是否精确匹配 scope（整串相等；无前缀/包含/模糊匹配）。"""
    if not auth:
        return False
    return auth == scope


# ---------------------------------------------------------------------------
# Guard 决策（纯本地；无网络 / 无 LLM；决策耗时被记录）
# ---------------------------------------------------------------------------


def evaluate(task_id: str, stage: str) -> dict:
    """对指定 Task + stage 求值 Hermes Paid Guard。

    返回 machine-readable record（可直接序列化为 cost_guard.json）：

    {schema_version, task_id, stage, decision, cost_class, model, provider,
     model_source, cost_metadata, required_scope, authorization_present,
     authorization_matched, decision_ms, timestamp, notes}
    """
    started = time.monotonic()
    effective = resolve_effective_hermes()
    model = effective.get("model")
    provider = effective.get("provider")
    base_url = effective.get("base_url")
    notes = list(effective.get("notes") or [])

    free_entries = _parse_free_models(os.environ.get(ENV_FREE_MODELS, ""))
    cost_class, cost_metadata = classify_cost(model, provider, base_url, free_entries)
    if free_entries:
        notes.append(f"FREE metadata declared via {ENV_FREE_MODELS}")

    auth_value = _auth_env_value()
    required_scope = None
    authorization_matched = False
    decision: str

    if model is None or cost_class == COST_UNKNOWN:
        # 缺失/歧义 effective model：无法证明 scope → fail closed（requirement F）
        decision = DECISION_BLOCKED_COST_APPROVAL
        notes.append(
            "effective model missing/ambiguous — cannot verify authorization scope; "
            f"fail closed (set {ENV_MODEL} to pin the model explicitly)"
        )
    elif cost_class in (COST_LOCAL_FREE, COST_FREE):
        decision = DECISION_ALLOWED_FREE
    else:  # PAID_OR_UNKNOWN
        scope = scope_string(task_id, stage, model, provider)
        required_scope = scope
        if _authorization_matches(auth_value, scope):
            decision = DECISION_ALLOWED_AUTHORIZED_PAID
            authorization_matched = True
            notes.append("exact task/stage/model authorization matched")
        else:
            decision = DECISION_BLOCKED_COST_APPROVAL
            if auth_value:
                notes.append(
                    f"{ENV_AUTH} present but does not exactly match required scope"
                )
            else:
                notes.append(f"no {ENV_AUTH} authorization present")

    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task_id": task_id,
        "stage": stage,
        "decision": decision,
        "cost_class": cost_class,
        "model": model,
        "provider": provider,
        "model_source": effective.get("model_source") or MODEL_SOURCE_UNKNOWN,
        "cost_metadata": cost_metadata,
        "required_scope": required_scope,
        "authorization_present": auth_value is not None,
        "authorization_matched": authorization_matched,
        "decision_ms": elapsed_ms,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 人读 blocked 文本（写入 hermes_result.md / 进入 REPORT）
# ---------------------------------------------------------------------------


def blocked_stage_text(record: dict) -> str:
    """BLOCKED 时写回 stage result 的文本。

    以 ``FRAMEWORK_ERROR`` 开头（既有语义：无效 result → 链中断 → WAITING；
    resume 时不会把 blocked result 当作已完成 hermes 结果复用）。
    内容必须清晰给出：Task ID / stage / effective model / provider / cost status /
    为什么被阻断 / 需要授权的精确 scope。
    """
    lines = [
        "FRAMEWORK_ERROR",
        "COST_APPROVAL_REQUIRED",
        "Hermes stage NOT started: cost authorization required (A0 Paid Guard, fail-closed).",
        "",
        f"Task ID: {record.get('task_id')}",
        f"Stage: {record.get('stage')}",
        f"Effective model: {record.get('model') or '(unresolved)'}",
        f"Provider: {record.get('provider') or '(unknown)'}",
        f"Cost status: {record.get('cost_class') or COST_UNKNOWN}",
        f"Decision: {record.get('decision')}",
    ]
    for note in record.get("notes") or []:
        lines.append(f"- note: {note}")
    lines.append("")
    lines.append(
        "Why blocked: 该 Hermes 模型为远程/API 模型或成本未知；A0 规则下未知成本"
        "一律视为非免费，且未检测到精确匹配的 task-scoped 显式授权——"
        "为避免无意的 API 花费，Hermes 进程未被创建。"
    )
    scope = record.get("required_scope")
    if scope:
        lines.append("")
        lines.append("Required authorization (exact scope, one-time, task-scoped):")
        lines.append(f'  set {ENV_AUTH}="{scope}"')
        lines.append(
            "授权仅对 任务+stage+model（+provider）整串精确匹配生效；"
            "不会泄漏到其他任务或后续运行。设置后重新提交任务（新 execution）即可。"
        )
    else:
        lines.append("")
        lines.append(
            f"Effective model 无法解析：设置 {ENV_MODEL}（可选 {ENV_PROVIDER}）"
            "显式指定模型后再运行。"
        )
    return "\n".join(lines)


def blocked_stage_json(record: dict) -> str:
    """BLOCKED 时写回 stage result.json 的 JSON（与 blocked_stage_text 同源）。"""
    return json.dumps(record, ensure_ascii=False, indent=2)
