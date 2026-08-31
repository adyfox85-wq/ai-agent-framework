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

成本分类（刻意最小；FIX-002 修订）：
- LOCAL_FREE：provider base_url **解析后的真实 hostname** 明确为本机
  （exact 'localhost' 或 loopback IP —— IPv4 127.0.0.0/8、IPv6 ::1；substring
  匹配已移除，fail-closed），或 provider == ollama 且无 base_url（verified
  local Ollama）。
- PAID_OR_UNKNOWN：任何不能证明为 LOCAL_FREE 的远程/API 模型（默认）。A0 没有
  真正的权威远程 FREE registry —— 用户可控环境变量（``AAF_COST_FREE_MODELS``）
  不再作为权威 FREE 来源，一律忽略（诊断 note 保留）。
- COST_UNKNOWN（内部）：effective model 无法解析（fail closed）。

授权表示（为何最小；FIX-002 修订；FIX-003 原子 claim）：单环境变量 + 整串精确匹配 +
**准入即原子消费（claim）**。不引入数据库 / 审批服务 / 长生命周期 token：env 只存在于
发起进程；精确匹配成功后授权被**单一原子操作 claim**——跨进程权威 = 执行目录内
消费记录 ``cost_auth_consumed.json`` 的 filesystem exclusive-create
（``open(..., "x")``，O_CREAT|O_EXCL 语义），恰好一个 contender 能创建成功
（FIX-003；替换 FIX-002 的 check-then-consume TOCTOU）；in-process 集合仅作
非权威拒绝快路径（只拒绝、不放行）。**FIX-005（FIX-004 re-issue）**：paid
admission 必须存在可用的持久化 ``state_dir``（filesystem exclusive-create 是
唯一跨进程准入权威）；state_dir 缺失/无效/不可用时，matched authorization 一律
fail closed，绝不因 in-process 集合放行。**FIX-006（Codex FIX-005 review
BLOCKING）**：持久化 ``state_dir`` 必须是**显式提供的、非空的、绝对路径**——
None / 空串 / 纯空白 / ``Path("")`` CWD fallback / ``"."`` / 相对路径 /
畸形或类型非法路径 / 任何 CWD 派生 persistence authority 一律 fail closed，
且**不创建任何 marker（包括 CWD 内）**；只有合法绝对路径才能建立跨进程 claim
权威。同一授权值在同一执行上下文内不可二次准入
（replay 拒绝、fail closed）；Task ID 在 scope 内 → 对其他任务天然失效（不泄漏到
后续任务）；claim 状态不确定（marker 已存在 / I/O 失败）→ fail closed。


Hermes 全局 config 不被本模块修改（只读查询 ``hermes config get model`` 是
解析 effective model 的 fallback；env 覆盖优先）。

注：stage 目前只有 'hermes' 走本 guard（WorkBuddy / Codex 不在 A0 范围）。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time
import winreg
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .subprocess_utils import no_console_kwargs

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "cost_guard.json"

# --- 环境变量契约（AAF 自有；不修改 Hermes 全局 config） ---
# effective model / provider 显式覆盖：guard 解析的 model == 实际 invocation model
# （runner 在 hermes 调用时透传 -m / --provider，见 adapters.run_agent）。
# AAF_HERMES_BASE_URL：与 AAF_HERMES_MODEL 配套的端点事实（A3 active routing
# 把已选 LOCAL_FREE 候选的 evidence-backed base_url 显式传入；guard 用既有
# classify_cost loopback 判定识别为 LOCAL_FREE——不是凭空捏造，分类逻辑零改动；
# 未设置时保持 None，绝不虚构 base_url）。
ENV_MODEL = "AAF_HERMES_MODEL"
ENV_PROVIDER = "AAF_HERMES_PROVIDER"
ENV_BASE_URL = "AAF_HERMES_BASE_URL"
# 一次性显式授权：整串精确匹配 "<task_id>|<stage>|<model>[|<provider>]"
ENV_AUTH = "AAF_COST_AUTH"
# AAF_COST_FREE_MODELS：**不是**权威 FREE 来源（A0 无可信远程 FREE registry）。
# 保留常量仅用于诊断——若被设置，evaluate() 在 notes 里明确记录"已忽略"。
# 任何用户可控环境变量都不得把远程付费模型变成 ALLOWED_FREE（FIX-002）。
ENV_FREE_MODELS = "AAF_COST_FREE_MODELS"

# --- 成本分类（A0 刻意最小；FIX-002：无远程 FREE 分类） ---
COST_LOCAL_FREE = "LOCAL_FREE"
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

_OLLAMA_PROVIDER = "ollama"

_SEPARATOR = "|"

# 一次性授权消费（FIX-003）：原子 claim（exclusive-create 为跨进程权威）+ in-process
# 只拒绝快路径。不构建数据库 / 审批服务 / 永久子系统（A0 最小；claim 状态不确定 → fail closed）。
# FIX-005（FIX-004 re-issue）：paid admission 必须存在可用的持久化 state_dir ——
# filesystem exclusive-create 是唯一准入权威；state_dir=None → fail closed。
# FIX-006（Codex FIX-005 review BLOCKING）：state_dir 必须为显式提供的非空绝对路径；
# None / 空 / 纯空白 / Path("") CWD fallback / "." / 相对 / 畸形 / CWD 派生权威一律
# fail closed（_state_dir_validation_error），且不创建任何 marker（含 CWD 内）。
CONSUMPTION_FILENAME = "cost_auth_consumed.json"
_CONSUMED_AUTHS: set[str] = set()
_CONSUMED_LOCK = threading.Lock()

_STATE_DIR_REQUIRED_ERR = (
    "persistent state_dir is REQUIRED for paid admission — the filesystem "
    "exclusive-create claim is the cross-process authority and cannot be "
    "established without it; _CONSUMED_AUTHS is NOT an admission authority "
    "(fail closed)"
)

_STATE_DIR_INVALID_PREFIX = (
    "persistent state_dir is NOT a valid paid-admission authority — an "
    "explicitly supplied, non-empty, ABSOLUTE, usable persistent state_dir is "
    "REQUIRED (the filesystem exclusive-create claim is the cross-process "
    "authority; a CWD-derived/relative persistence authority is ambiguous and "
    "never creates any marker)"
)


def _state_dir_validation_error(
    state_dir: str | os.PathLike | None,
) -> str | None:
    """FIX-006：校验 state_dir 是否可作为 paid admission 的持久化跨进程 claim 权威。

    返回 fail-closed 错误文本；合法（显式提供的非空绝对路径）→ None。以下输入
    全部是 ambiguous persistence authority → 必须 BLOCKED，且调用方**不得创建
    任何 marker**（包括 CWD 内）：

    - None → ``_STATE_DIR_REQUIRED_ERR``（FIX-005 语义保持）；
    - 非 str / 非 os.PathLike（或 ``__fspath__`` 返回非 str，如 bytes/int）→
      类型非法（Path() 会 TypeError，不能让异常逃逸 evaluate）；
    - 空串 / 纯空白 → ``Path("")`` / ``Path("   ")`` 会静默落到 CWD（FIX-005
      review 阻塞点：``Path("")`` 解析为相对 CWD 的 marker）；
    - 含 NUL 字节 → 畸形路径（Path/mkdir/open 会 ValueError）；
    - 其余 str：``Path(raw).is_absolute()`` 为 False（``"."`` / ``"./x"`` /
      ``"relative-state"`` / ``"C:foo"`` 驱动器相对 / ``"\\foo"`` 盘符相对）
      → 相对或 CWD 派生，拒绝。
    """
    if state_dir is None:
        return _STATE_DIR_REQUIRED_ERR
    try:
        raw = os.fspath(state_dir)
    except TypeError:
        return (
            f"{_STATE_DIR_INVALID_PREFIX} (unsupported state_dir type "
            f"{type(state_dir).__name__!r})"
        )
    if not isinstance(raw, str):
        return (
            f"{_STATE_DIR_INVALID_PREFIX} (unsupported state_dir type "
            f"{type(raw).__name__!r} — str or os.PathLike[str] required)"
        )
    if not raw.strip():
        return (
            f"{_STATE_DIR_INVALID_PREFIX} (state_dir {raw!r} is empty or "
            "whitespace-only — it would silently fall back to the current "
            "working directory, an ambiguous CWD-derived persistence authority)"
        )
    if "\x00" in raw:
        return f"{_STATE_DIR_INVALID_PREFIX} (state_dir contains a NUL byte — malformed path)"
    p = Path(raw)
    if not p.is_absolute():
        return (
            f"{_STATE_DIR_INVALID_PREFIX} (state_dir {raw!r} is NOT an absolute "
            f"path — it resolves relative to the current working directory "
            f"{os.getcwd()!r}, an ambiguous CWD-derived persistence authority)"
        )
    return None


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
    1. ``AAF_HERMES_MODEL``（+ ``AAF_HERMES_PROVIDER`` / ``AAF_HERMES_BASE_URL``）
       显式覆盖 —— 与 runner 实际透传给 hermes 的参数一致（invocation-truth）。
       base_url 是调用方（A3 active routing）显式传入的端点事实：存在时经既有
       ``classify_cost`` 的 loopback 判定参与 LOCAL_FREE 识别；缺失时保持 None
       （不虚构）。它只在 AAF_HERMES_MODEL 同时存在时被消费。
    2. ``hermes config get model`` 只读查询（v0.4 model_observation 同款发现）。
    3. 都无法解析 → model=None（cost_class=COST_UNKNOWN → fail closed）。

    返回 dict：model / provider / base_url / model_source / notes。
    """
    model = os.environ.get(ENV_MODEL, "").strip()
    provider = os.environ.get(ENV_PROVIDER, "").strip()
    base_url = os.environ.get(ENV_BASE_URL, "").strip() or None
    if model:
        notes = [
            f"effective model pinned via {ENV_MODEL}"
            + (f" / provider via {ENV_PROVIDER}" if provider else "")
        ]
        if base_url:
            notes.append(
                f"base_url pinned via {ENV_BASE_URL} (framework-provided endpoint "
                "fact from registry evidence; classified by the same loopback "
                "check as config-sourced base_url)"
            )
        return {
            "model": model,
            "provider": provider or None,
            "base_url": base_url,
            "model_source": MODEL_SOURCE_ENV,
            "notes": notes,
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
# 成本分类（A0 刻意最小；FIX-002：严格 hostname/IP 语义 + 无远程 FREE 权威）
# ---------------------------------------------------------------------------


def _endpoint_is_local(base_url: str | None) -> tuple[bool, str]:
    """严格本地端点判定（fail-closed；FIX-002 替代原 substring 匹配）。

    只依据 URL **解析后的真实 hostname**（``urllib.parse.urlsplit``）：
    接受（LOCAL_FREE）：
    - hostname == 'localhost'（urlsplit 已小写化 → 大小写不敏感、exact 匹配）
    - hostname 为合法 IP 且 ``ipaddress.is_loopback`` 为真
      （IPv4 127.0.0.0/8 全段、IPv6 ::1 等标准 loopback 语义）

    一律拒绝（NOT local → PAID_OR_UNKNOWN，fail closed）：
    - 无 base_url / 无法解析 / 无 hostname / 非 http(s) scheme / 非法 port
    - 形似本地的域名但非 exact 'localhost'（localhost.evil.example、
      notlocalhost.example、127.0.0.1.evil.com …）
    - 合法 IP 但非 loopback（0.0.0.0 是 bind 通配地址、8.8.8.8 等 → 非权威
      本地证据，fail closed）
    - path/query 中的 localhost / 127.0.0.1 字样（hostname 才是判定依据）

    返回 (is_local, evidence)。
    """
    if not base_url or not base_url.strip():
        return False, "no base_url"
    raw = base_url.strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return False, f"unparseable base_url={raw!r}"
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"scheme={scheme!r} not http(s) — ambiguous endpoint"
    host = parts.hostname  # 已小写化、已去 []；缺省 None
    if not host:
        return False, f"no hostname in base_url={raw!r}"
    try:
        _ = parts.port  # 非法 port（99999 / 非数字）→ ValueError → fail closed
    except ValueError:
        return False, f"invalid port in base_url={raw!r}"
    if host == "localhost":
        return True, f"exact hostname 'localhost' (case-insensitive) in {raw!r}"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False, (
            f"hostname={host!r} is neither exact 'localhost' nor a valid IP — "
            "remote/ambiguous; substring occurrence in URL is not evidence"
        )
    if addr.is_loopback:
        return True, f"loopback IP {host} (ipaddress.is_loopback) in {raw!r}"
    return False, f"hostname={host!r} is a valid IP but NOT loopback — remote"


def classify_cost(
    model: str | None,
    provider: str | None,
    base_url: str | None,
) -> tuple[str, dict | None]:
    """A0 最小成本分类 → (cost_class, cost_metadata)。FIX-002：无远程 FREE 分类。

    - base_url 存在 → 严格 hostname/IP 判定（本地 → LOCAL_FREE；否则
      PAID_OR_UNKNOWN，fail closed）
    - provider=ollama 且无 base_url → LOCAL_FREE（verified local Ollama）
    - 其余远程/API 模型 → PAID_OR_UNKNOWN（A0 无权威远程 FREE 来源；
      UNKNOWN 不视为 FREE）
    - model=None → COST_UNKNOWN（调用方 fail closed）
    """
    if model is None:
        return COST_UNKNOWN, {"evidence": "effective model unresolved"}
    if base_url:
        is_local, evidence = _endpoint_is_local(base_url)
        if is_local:
            return COST_LOCAL_FREE, {
                "evidence": f"provider base_url={base_url} ({evidence})",
                "note": "local inference; no per-token cash cost",
            }
        return COST_PAID_OR_UNKNOWN, {
            "evidence": f"base_url={base_url} not a verified local endpoint "
            f"({evidence})",
            "note": "fail closed: remote/ambiguous endpoint is never LOCAL_FREE",
        }
    p = (provider or "").strip().lower()
    if p == _OLLAMA_PROVIDER:
        return COST_LOCAL_FREE, {
            "evidence": "provider=ollama with no base_url (verified local Ollama server)",
            "note": "local inference; no per-token cash cost",
        }
    return COST_PAID_OR_UNKNOWN, {
        "evidence": "remote/API model with no verified local endpoint",
        "note": "A0 has no trusted remote FREE authority — PAID_OR_UNKNOWN (fail closed)",
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
# 一次性授权消费（FIX-002 引入；FIX-003：check-then-consume → 单一原子 claim）
# ---------------------------------------------------------------------------


def _auth_fingerprint(auth: str) -> str:
    """授权值的稳定指纹（sha256；消费记录不落盘授权原文，仅等价标识）。"""
    return hashlib.sha256(auth.encode("utf-8")).hexdigest()


_CLAIM_ALREADY_CONSUMED = (
    "authorization already consumed (one-time) — replay rejected; "
    "a NEW authorization value is required for another admission"
)


def _claim_auth(
    auth: str, scope: str, state_dir: str | os.PathLike | None
) -> tuple[bool, str]:
    """原子 claim 一次性授权（FIX-003；替换 FIX-002 的 check-then-consume TOCTOU）。

    单一原子操作，不再“先检查是否已消费、再消费”：
    - **state_dir 必须为显式提供的非空绝对路径（FIX-006）**：paid admission
      的唯一跨进程权威 = filesystem exclusive-create；None / 空串 / 纯空白 /
      ``Path("")`` CWD fallback / ``"."`` / 相对路径 / 畸形或类型非法路径 /
      任何 CWD 派生 persistence authority 一律直接失败（``_state_dir_validation_error``），
      且**不创建任何 marker（包括 CWD 内）**。`_CONSUMED_AUTHS` 只是非权威
      拒绝快路径，绝不放行。任何 matched paid authorization 在无合法持久化权威时
      都必须 fail closed。
    - in-process 快路径（``_CONSUMED_LOCK`` 保护）：只拒绝（已在本进程消费过），
      不放行任何东西 —— 非权威优化，不可能造成 fail-open；
    - 跨进程权威 = 文件系统 exclusive-create：确定性子路径
      ``<state_dir>/cost_auth_consumed.json`` 用 ``open(marker, "x")``
      （O_CREAT|O_EXCL / CREATE_NEW）创建，恰好一个 contender 能成功；
    - marker 路径已被占用（文件/目录/符号链接；FileExistsError 或任何 OSError 且
      ``marker.exists()`` 为真）→ 该授权已被 claim/消费 → 返回 False（BLOCK）；
    - 其余 I/O / 持久化失败（无法建立 marker，含 ValueError 畸形路径）→ 返回
      False（fail closed，不静默放行）；
    - claim 成功后进程崩溃 → marker 已存在，授权保持已消费（fail-closed 结果可接受，
      优于 replay）。

    返回 (ok, err)。ok=True 仅当本次调用赢得了 claim。
    """
    with _CONSUMED_LOCK:
        state_err = _state_dir_validation_error(state_dir)
        if state_err is not None:
            # FIX-005/FIX-006：无合法持久化 filesystem authority（None / 空 /
            # 相对 / CWD 派生 / 畸形）→ 无法原子 claim → fail closed。
            # 即便 auth 已在 _CONSUMED_AUTHS 中（本进程曾消费），也绝不因此放行。
            return False, state_err
        if auth in _CONSUMED_AUTHS:
            return False, _CLAIM_ALREADY_CONSUMED
        marker = Path(state_dir) / CONSUMPTION_FILENAME
        payload = {
            "schema_version": SCHEMA_VERSION,
            "decision": DECISION_ALLOWED_AUTHORIZED_PAID,
            "scope": scope,
            "consumed_auth_fingerprint": _auth_fingerprint(auth),
            "consumed_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            # state_dir 路径本身是已存在文件 → marker 无法建立 → fail closed
            return False, (
                "cannot persist consumption marker (state_dir is not a "
                "directory) — fail closed"
            )
        except (OSError, ValueError) as exc:
            # OSError：权限/非法字符/路径过长/中间组件是文件等不可用路径；
            # ValueError：畸形路径（如 NUL，_state_dir_validation_error 已拦，
            # 此处兜底）→ fail closed
            return False, f"cannot persist consumption marker ({exc})"
        try:
            with open(marker, "x", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
        except (OSError, ValueError) as exc:
            if marker.exists():
                # 路径已被占用（含目录/符号链接等非 FileExistsError 平台差异）
                # → 他人已 claim → 视为已消费（fail closed）
                return False, _CLAIM_ALREADY_CONSUMED
            return False, f"cannot persist consumption marker ({exc})"
        _CONSUMED_AUTHS.add(auth)
        return True, ""


def _consume_auth(
    auth: str, scope: str, state_dir: str | os.PathLike | None
) -> tuple[bool, str]:
    """兼容别名（FIX-002 名称保留）：委托给原子 ``_claim_auth``。"""
    return _claim_auth(auth, scope, state_dir)


# ---------------------------------------------------------------------------
# Guard 决策（纯本地；无网络 / 无 LLM；决策耗时被记录）
# ---------------------------------------------------------------------------


def evaluate(
    task_id: str,
    stage: str,
    state_dir: str | os.PathLike | None = None,
) -> dict:
    """对指定 Task + stage 求值 Hermes Paid Guard。

    ``state_dir``：一次性授权消费记录所在目录（runner 传 execution output dir）。
    **FIX-005（FIX-004 re-issue）**：paid admission 必须存在可用的持久化
    state_dir —— filesystem exclusive-create（``open(marker, "x")``）是唯一
    跨进程准入权威；state_dir=None / 缺失 / 无效 / 不可用（无法提供持久化原子
    claim 权威）时，matched paid authorization 一律 BLOCKED（fail closed），
    绝不因 ``_CONSUMED_AUTHS`` 等 in-process 集合放行。
    **FIX-006（Codex FIX-005 review BLOCKING）**：state_dir 必须为**显式提供的、
    非空、绝对路径**——None / 空串 / 纯空白 / ``Path("")`` CWD fallback /
    ``"."`` / 相对路径（如 ``"./relative-state"``）/ 畸形或类型非法路径 / 任何
    CWD 派生 persistence authority 一律 fail closed（``_state_dir_validation_error``），
    且**不创建任何 marker（包括 CWD 内）**；只有合法绝对路径才能建立跨进程
    claim 权威。消费在准入边界完成（FIX-002）。

    返回 machine-readable record（可直接序列化为 cost_guard.json）：

    {schema_version, task_id, stage, decision, cost_class, model, provider,
     model_source, cost_metadata, required_scope, authorization_present,
     authorization_matched, authorization_consumed, decision_ms, timestamp, notes}
    """
    started = time.monotonic()
    effective = resolve_effective_hermes()
    model = effective.get("model")
    provider = effective.get("provider")
    base_url = effective.get("base_url")
    notes = list(effective.get("notes") or [])

    # A0 无远程 FREE 权威（FIX-002）：AAF_COST_FREE_MODELS 一律忽略——
    # 仅作诊断记录，绝不参与分类（Codex BLOCKING #2）。
    free_env = os.environ.get(ENV_FREE_MODELS, "").strip()
    if free_env:
        notes.append(
            f"{ENV_FREE_MODELS} is set but deliberately IGNORED: A0 has no trusted "
            "remote FREE authority — user-controlled env metadata is not "
            "authoritative FREE evidence (fail closed)"
        )

    cost_class, cost_metadata = classify_cost(model, provider, base_url)

    auth_value = _auth_env_value()
    required_scope = None
    authorization_matched = False
    authorization_consumed = False
    decision: str

    if model is None or cost_class == COST_UNKNOWN:
        # 缺失/歧义 effective model：无法证明 scope → fail closed（requirement F）
        decision = DECISION_BLOCKED_COST_APPROVAL
        notes.append(
            "effective model missing/ambiguous — cannot verify authorization scope; "
            f"fail closed (set {ENV_MODEL} to pin the model explicitly)"
        )
    elif cost_class == COST_LOCAL_FREE:
        decision = DECISION_ALLOWED_FREE
    else:  # PAID_OR_UNKNOWN
        scope = scope_string(task_id, stage, model, provider)
        required_scope = scope
        if _authorization_matches(auth_value, scope):
            # FIX-003：单一原子 claim（exclusive-create 跨进程权威），
            # 不再 check-then-consume —— 并发/重入 admission 不可能同时看到
            # “未消费”并双双放行；恰好一个 contender 赢得 claim。
            # FIX-005（FIX-004 re-issue）：_claim_auth 在 state_dir=None /
            # 不可用时直接失败 —— matched authorization 无持久化 filesystem
            # authority → BLOCKED（fail closed），_CONSUMED_AUTHS 绝不放行。
            claimed, claim_err = _claim_auth(auth_value, scope, state_dir)
            if claimed:
                decision = DECISION_ALLOWED_AUTHORIZED_PAID
                authorization_matched = True
                authorization_consumed = True
                notes.append(
                    "exact task/stage/model authorization atomically claimed at "
                    "admission boundary (one-time; same auth cannot admit twice)"
                )
            else:
                decision = DECISION_BLOCKED_COST_APPROVAL
                authorization_consumed = claim_err == _CLAIM_ALREADY_CONSUMED
                notes.append(claim_err)
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
        "authorization_consumed": authorization_consumed,
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
    if record.get("authorization_consumed"):
        lines.append(
            "注意：当前 AAF_COST_AUTH 授权值已在本次 execution 上下文中被准入消费"
            "（一次性语义，fail-closed）。同一 execution 目录内该授权不可再次准入；"
            "如需再次运行该任务，请以新 execution（新目录）重新提交并重新设置授权。"
        )
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
