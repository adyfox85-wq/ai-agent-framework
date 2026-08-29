"""AAF — Model Observability / Discovery Foundation（AAF-v0.4-TASK-010）。

只读基础能力，为未来 Automatic Model Routing 建立事实层：

- Model Observability：记录 Hermes / WorkBuddy / Codex 每个 stage 实际使用或
  可确定的模型信息。
- Model Discovery：从各 Agent 自身当前 CLI / config / provider 能力中发现模型
  信息；**不得把模型名称 / 免费状态 / 积分倍率硬编码为永久事实**。
- Execution Metrics Foundation：stage 时序由 runner 记录于
  ``<agent>_result.json``（stage_timing），模型观测数据由本模块维护。

权威（Single Source of Truth）：
  ``model_observation.json``（output_dir 内）是 **model observation authority**
  （machine-readable artifact，schema_version 版本化，可刷新）。REPORT 只含
  紧凑摘要；stage result 只含指向该 artifact 的引用（model_observation_ref），
  不在多处维护独立 truth。

严格约束（本任务范围边界）：
- 不做任何模型选择 / 切换 / 升级 / Cost Gate / Routing。
- 不发起点付费推理（只跑 --help / config get / 读本地 config 的只读命令）。
- 不修改任何 Agent 的 model / provider / config。
- 任何 discovery 失败都非阻塞：记录 discovery_status / UNKNOWN，绝不抛出
  使 runner 中断，绝不把观测失败升级为 TASK FAILED。
- 隐私：绝不记录 API keys / tokens / secrets / credential 文件内容。

动态元数据原则：
- 模型可增加 / 删除 / 改名；免费状态可变化；积分倍率可变化。
- registry 每次 run 重新 discovery 并覆盖条目（refreshable），
  一次发现结果绝不当永久事实。
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

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "model_observation.json"

# model_source：只有有证据时才能填具体 model；inference 不得写成 authoritative fact
MODEL_SOURCE_EXPLICIT_CLI = "explicit_cli"
MODEL_SOURCE_CONFIG = "config"
MODEL_SOURCE_RUNTIME_OUTPUT = "runtime_output"
MODEL_SOURCE_INFERRED_DEFAULT = "inferred_default"
MODEL_SOURCE_UNKNOWN = "unknown"
MODEL_SOURCES = frozenset(
    (
        MODEL_SOURCE_EXPLICIT_CLI,
        MODEL_SOURCE_CONFIG,
        MODEL_SOURCE_RUNTIME_OUTPUT,
        MODEL_SOURCE_INFERRED_DEFAULT,
        MODEL_SOURCE_UNKNOWN,
    )
)

# cost_class：只允许这些值；只有 Agent/provider 当前可提供可靠数据时才填写
COST_CLASS_LOCAL_FREE = "LOCAL_FREE"
COST_CLASS_FREE = "FREE"
COST_CLASS_FREE_PROMO = "FREE_PROMO"
COST_CLASS_PAID = "PAID"
COST_CLASS_UNKNOWN = "UNKNOWN"
COST_CLASSES = frozenset(
    (
        COST_CLASS_LOCAL_FREE,
        COST_CLASS_FREE,
        COST_CLASS_FREE_PROMO,
        COST_CLASS_PAID,
        COST_CLASS_UNKNOWN,
    )
)

# discovery_status：任何 failure 只反映在状态上，不阻断执行
DISCOVERY_STATUS_OK = "OK"
DISCOVERY_STATUS_UNAVAILABLE = "UNAVAILABLE"
DISCOVERY_STATUS_FAILED = "FAILED"

# 遥测开关：AAF_MODEL_OBSERVATION=0/false/off → 完全关闭（行为与未引入遥测前一致）
ENV_TOGGLE = "AAF_MODEL_OBSERVATION"
_DISABLED_VALUES = frozenset({"0", "false", "off", "no", "disable", "disabled"})

_LOCAL_HOST_HINTS = ("127.0.0.1", "localhost", "0.0.0.0")

# 本任务登记的能力组（用于文档 / registry 元信息；不是实现）
CAPABILITY_GROUP = "Model Observability / Model Discovery / Future Model Routing"


def observations_enabled() -> bool:
    """遥测开关：显式禁用 → False；默认启用。"""
    return os.environ.get(ENV_TOGGLE, "").strip().lower() not in _DISABLED_VALUES


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Observation record
# ---------------------------------------------------------------------------


def empty_observation(agent: str) -> dict:
    """全 UNKNOWN 观测记录（未知就是未知；不伪造）。"""
    return {
        "agent": agent,
        "provider": None,
        "model": None,
        "model_source": MODEL_SOURCE_UNKNOWN,
        "reasoning_effort": None,
        "cost_class": COST_CLASS_UNKNOWN,
        "cost_metadata": None,
        "cost_multiplier": None,  # 动态积分倍率；无法可靠读取 → null
        "discovered_at": _now_iso(),
        "discovery_status": DISCOVERY_STATUS_UNAVAILABLE,
        "capabilities": {},
        "notes": [],
    }


def make_observation(
    agent: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    model_source: str = MODEL_SOURCE_UNKNOWN,
    reasoning_effort: str | None = None,
    cost_class: str = COST_CLASS_UNKNOWN,
    cost_metadata: dict | None = None,
    cost_multiplier: float | None = None,
    discovery_status: str = DISCOVERY_STATUS_OK,
    capabilities: dict | None = None,
    notes: list[str] | None = None,
) -> dict:
    """构造合法观测记录（schema 校验 model_source / cost_class）。"""
    if model_source not in MODEL_SOURCES:
        raise ValueError(f"invalid model_source: {model_source!r}")
    if cost_class not in COST_CLASSES:
        raise ValueError(f"invalid cost_class: {cost_class!r}")
    obs = empty_observation(agent)
    obs.update(
        {
            "provider": provider,
            "model": model,
            "model_source": model_source,
            "reasoning_effort": reasoning_effort,
            "cost_class": cost_class,
            "cost_metadata": cost_metadata,
            "cost_multiplier": cost_multiplier,
            "discovered_at": _now_iso(),
            "discovery_status": discovery_status,
            "capabilities": dict(capabilities or {}),
            "notes": list(notes or []),
        }
    )
    return obs


# ---------------------------------------------------------------------------
# 只读 subprocess 工具（无 stdin payload / 有界超时 / 绝不写配置）
# ---------------------------------------------------------------------------


def _windows_path() -> str:
    """Windows 新会话 PATH：用户 PATH + 机器 PATH（与 adapters 一致）。"""
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


CODEX_FALLBACK_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"


def _codex_fallback() -> str | None:
    """Codex known-install fallback（与 adapters 相同的 real-world hotfix）。"""
    try:
        if not CODEX_FALLBACK_DIR.is_dir():
            return None
        candidates = [
            d / "codex.exe"
            for d in CODEX_FALLBACK_DIR.iterdir()
            if d.is_dir() and (d / "codex.exe").is_file()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])
    except OSError:
        return None


def _find_cli(cmd: str) -> str | None:
    """解析 CLI 路径；找不到 → None（discovery 视为 UNAVAILABLE，不抛出）。"""
    try:
        found = shutil.which(cmd, path=_windows_path())
        if not found and cmd == "codex":
            found = _codex_fallback()
        return found
    except Exception:
        return None


def _run_readonly(args: list[str], timeout: float = 20.0) -> tuple[int, str, str] | None:
    """只读命令执行：capture-only、无输入、有界超时。

    返回 (exit_code, stdout, stderr)；调用本身失败 → None。
    任何异常都被吸收（non-blocking）。
    """
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception:
        return None


# 每进程缓存 CLI --help 文本（capability 探测是版本级常量；失败 → None 不再重试）
_HELP_CACHE: dict[str, str | None] = {}


def _cli_help(exe: str) -> str | None:
    """``<exe> --help``（只读；失败 → None）。"""
    if exe in _HELP_CACHE:
        return _HELP_CACHE[exe]
    res = _run_readonly([exe, "--help"])
    if res is None:
        _HELP_CACHE[exe] = None
        return None
    code, out, err = res
    text = (out or "") + ("\n" + err if err else "")
    _HELP_CACHE[exe] = text if code == 0 else None
    return _HELP_CACHE[exe]


# ---------------------------------------------------------------------------
# 文本解析（只解析真实 CLI 输出形态；解析失败 → UNKNOWN，不发明）
# ---------------------------------------------------------------------------


def _parse_key_value_lines(text: str) -> dict:
    """解析 ``key: value`` 行（首冒号分割；含缩进层级信息忽略）。"""
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


def _parse_aux_slots(text: str) -> list[dict]:
    """解析 ``hermes config get auxiliary`` 的缩进槽位输出。

    形态（真实 v0.20.5 输出）::

        vision:
          provider: custom
          model: qwen2.5vl:3b
          base_url: http://127.0.0.1:11434/v1
          ...

    返回 [{"slot", "provider", "model", "base_url", "reasoning_effort"}, ...]。
    解析失败 → []（UNKNOWN，不发明）。
    """
    slots: list[dict] = []
    current: dict | None = None
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and stripped.endswith(":"):
            name = stripped[:-1].strip()
            if re.match(r"^[A-Za-z0-9_.\-]+$", name):
                current = {
                    "slot": name,
                    "provider": None,
                    "model": None,
                    "base_url": None,
                    "reasoning_effort": None,
                }
                slots.append(current)
            else:
                current = None
            continue
        if current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            if key in ("provider", "model", "base_url", "reasoning_effort"):
                raw = value.strip()
                # 去除 CLI 输出中的字面引号（'' / "" → 空值语义）
                if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
                    raw = raw[1:-1].strip()
                current[key] = raw or None
    return [s for s in slots if s.get("model")]


def _parse_codebuddy_model_list(help_text: str) -> list[str]:
    """从 CodeBuddy CLI ``--model`` help 行提取官方支持的模型 ID 列表。

    形态（真实 2.137.1 输出）::

        --model <model>   Model for the current session. ... Currently supported:
                          (hy4-preview, hy4-preview-x, hy3, ...)

    该列表来自 CLI 自身帮助文本（版本级静态元数据，刷新 = 重新 --help），
    不是 AAF 硬编码。解析失败 → []。
    """
    m = re.search(r"--model\s+<model>.*?Currently supported:\s*\(([^)]+)\)", help_text, re.DOTALL)
    if not m:
        return []
    parts = [p.strip() for p in m.group(1).split(",")]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Per-agent discovery（只读；返回观测记录，绝不抛出）
# ---------------------------------------------------------------------------


def _local_free_from_base_url(base_url: str | None) -> tuple[str, dict]:
    """base_url 指向本机（127.0.0.1 / localhost）→ LOCAL_FREE（证据来自 provider
    config 的 local endpoint，不是促销表）。否则 UNKNOWN。"""
    if base_url and any(h in base_url for h in _LOCAL_HOST_HINTS):
        return COST_CLASS_LOCAL_FREE, {
            "evidence": f"provider base_url={base_url} (local endpoint)",
            "note": "local inference; no per-token cash cost",
        }
    return COST_CLASS_UNKNOWN, None


def discover_hermes() -> dict:
    """Hermes：主模型 / provider / reasoning 从 ``hermes config get model`` 读取；
    auxiliary slots 从 ``hermes config get auxiliary`` 读取；capability 从 --help 判定。

    - 主模型：resolved config（model_source=config）。
    - 本地/Ollama：auxiliary.* 槽位 base_url=http://127.0.0.1:11434/v1 可发现。
    - 视觉/图像：auxiliary.vision 是 model slot（Ollama 本地模型）；ComfyUI 不在
      Hermes text-model registry 中 → 分类为外部 capability/tool（见 notes）。
    """
    obs = empty_observation("hermes")
    exe = _find_cli("hermes")
    if not exe:
        obs["notes"].append("hermes CLI not found on PATH — main model UNKNOWN")
        return obs

    res = _run_readonly([exe, "config", "get", "model"])
    if res is None:
        obs["discovery_status"] = DISCOVERY_STATUS_FAILED
        obs["notes"].append("`hermes config get model` invocation failed")
        return obs
    code, out, err = res
    parsed = _parse_key_value_lines(out) if code == 0 else {}
    model = parsed.get("default")
    provider = parsed.get("provider")
    effort = parsed.get("reasoning_effort")
    base_url = parsed.get("base_url")
    if model:
        obs.update(
            model=model,
            provider=provider or None,
            model_source=MODEL_SOURCE_CONFIG,
            reasoning_effort=effort or None,
            discovery_status=DISCOVERY_STATUS_OK,
        )
        cost_class, cost_meta = _local_free_from_base_url(base_url)
        obs["cost_class"] = cost_class
        obs["cost_metadata"] = cost_meta
        if cost_class == COST_CLASS_UNKNOWN:
            obs["notes"].append(
                "cost metadata NOT exposed by `hermes config get model` → UNKNOWN "
                "(EXTERNAL_DYNAMIC_METADATA_REQUIRED)"
            )
        obs["notes"].append("model read via `hermes config get model` (resolved config)")
    else:
        obs["discovery_status"] = DISCOVERY_STATUS_UNAVAILABLE
        obs["notes"].append(
            f"`hermes config get model` unavailable (exit={code}): "
            f"{(err or 'empty').strip()[:120]}"
        )

    # auxiliary slots（本地/Ollama 可发现性；vision 分类）
    aux_res = _run_readonly([exe, "config", "get", "auxiliary"])
    if aux_res is not None and aux_res[0] == 0:
        slots = _parse_aux_slots(aux_res[1])
        obs["auxiliary_slots"] = []
        for slot in slots:
            entry = {
                "slot": slot["slot"],
                "provider": slot["provider"],
                "model": slot["model"],
                "model_source": MODEL_SOURCE_CONFIG,
            }
            cost_class, cost_meta = _local_free_from_base_url(slot["base_url"])
            entry["cost_class"] = cost_class
            entry["cost_metadata"] = cost_meta
            if slot["slot"] == "vision":
                entry["classification"] = "model_slot"
                entry["classification_evidence"] = (
                    "auxiliary.vision is a Hermes auxiliary model slot "
                    "(provider=custom, local Ollama endpoint)"
                )
            obs["auxiliary_slots"].append(entry)
        obs["notes"].append(
            "auxiliary slots discovered via `hermes config get auxiliary` "
            "(model_source=config); local Ollama endpoints identified by base_url"
        )
        obs["notes"].append(
            "ComfyUI is NOT part of Hermes text-model registry in this environment "
            "→ classified as external image-generation capability/tool, "
            "not an LLM model slot"
        )
    else:
        obs["notes"].append(
            "`hermes config get auxiliary` unavailable → auxiliary slots UNKNOWN"
        )

    # capability（版本级，来自 --help）
    help_text = _cli_help(exe)
    if help_text:
        obs["capabilities"] = {
            "explicit_model_selection": "-m MODEL" in help_text or "--model " in help_text,
            "provider_selectable": "--provider" in help_text,
            "reasoning_effort_option": "--reasoning" in help_text,
            "models_listable": False,  # `hermes model` 是交互式 picker，无非交互 list
        }
        obs["notes"].append(
            "`hermes model` is interactive-only (no non-interactive model list command)"
        )
    return obs


def discover_codebuddy() -> dict:
    """WorkBuddy / CodeBuddy：当前模型 config 读取 + CLI 官方能力判定。

    真实结论（codebuddy 2.137.1）：
    - ``codebuddy config get model`` 为空 → 当前模型不由用户 config 暴露；
      实际模型由 CLI default / last-used 决定 → UNKNOWN（需 runtime 观测）。
    - ``--model`` 显式选择存在；``--effort`` reasoning effort 存在；
      支持的模型 ID 由 CLI --help 文本文档化（版本级静态元数据）。
    - 积分倍率 / 免费状态 CLI 不暴露 → UNKNOWN / EXTERNAL_DYNAMIC_METADATA_REQUIRED。
    """
    obs = empty_observation("workbuddy")
    exe = _find_cli("codebuddy")
    if not exe:
        obs["notes"].append("codebuddy CLI not found on PATH — current model UNKNOWN")
        return obs

    res = _run_readonly([exe, "config", "get", "model"])
    if res is None:
        obs["discovery_status"] = DISCOVERY_STATUS_FAILED
        obs["notes"].append("`codebuddy config get model` invocation failed")
        return obs
    code, out, err = res
    model = (out or "").strip()
    if model:
        obs.update(
            model=model,
            model_source=MODEL_SOURCE_CONFIG,
            discovery_status=DISCOVERY_STATUS_OK,
        )
        obs["notes"].append("model read via `codebuddy config get model`")
    else:
        obs["discovery_status"] = DISCOVERY_STATUS_UNAVAILABLE
        obs["notes"].append(
            "`codebuddy config get model` returned empty — current model NOT exposed "
            "by user config; actual model determined by CLI default / last-used "
            "(runtime observation required; config is not authoritative)"
        )

    obs["cost_class"] = COST_CLASS_UNKNOWN
    obs["cost_multiplier"] = None
    obs["notes"].append(
        "cost/free/credit-multiplier metadata NOT exposed by CodeBuddy CLI "
        "→ UNKNOWN (EXTERNAL_DYNAMIC_METADATA_REQUIRED)"
    )

    help_text = _cli_help(exe)
    if help_text:
        documented = _parse_codebuddy_model_list(help_text)
        obs["capabilities"] = {
            "explicit_model_selection": "--model" in help_text,
            "reasoning_effort_option": "--effort" in help_text,
            "models_documented_by_cli": documented,
            "models_listable": False,  # 只有 help 静态文档，无动态 list 命令
        }
        if documented:
            obs["notes"].append(
                "model IDs documented in CLI --model help text (version-level static "
                "metadata; refresh = re-run `codebuddy --help`, not hardcoded by AAF)"
            )
    return obs


def _codex_config_model() -> str | None:
    """从 ~/.codex/config.toml 只读提取 ``model`` key（唯一读取的字段；
    其他内容（含 secrets）绝不进入观测。文件缺失 / 无 model key → None。"""
    home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    cfg = Path(home) / "config.toml"
    try:
        if not cfg.is_file():
            return None
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"(?m)^\s*model\s*=\s*[\"']([^\"']+)[\"']", text)
    return m.group(1) if m else None


def discover_codex() -> dict:
    """Codex：当前/default 模型 + 显式选择 + reasoning + 可枚举性（真实判定）。

    真实结论（codex-cli 0.150.0-alpha.12.2）：
    - ~/.codex/config.toml 无 model key → 默认模型由 server-side 决定，
      本地 CLI 不可读 → UNKNOWN（documented discoverability limitation）。
    - ``codex exec -m/--model`` 显式选择存在。
    - 无专用 reasoning-effort flag；只有通用 ``-c model_options.*`` 覆盖机制。
    - CLI 无命令枚举 server-side model catalog → 不可枚举（limitation）。
    """
    obs = empty_observation("codex")
    exe = _find_cli("codex")
    if not exe:
        obs["notes"].append("codex CLI not found on PATH — current model UNKNOWN")
        return obs

    model = _codex_config_model()
    if model:
        obs.update(
            model=model,
            model_source=MODEL_SOURCE_CONFIG,
            discovery_status=DISCOVERY_STATUS_OK,
        )
        obs["notes"].append("model key present in ~/.codex/config.toml")
    else:
        obs["discovery_status"] = DISCOVERY_STATUS_UNAVAILABLE
        obs["notes"].append(
            "no `model` key in ~/.codex/config.toml — current/default model is "
            "determined server-side and NOT locally discoverable "
            "(documented discoverability limitation; do not guess or hardcode)"
        )

    obs["cost_class"] = COST_CLASS_UNKNOWN
    obs["cost_multiplier"] = None
    obs["notes"].append(
        "cost metadata NOT exposed by Codex CLI/config → UNKNOWN "
        "(EXTERNAL_DYNAMIC_METADATA_REQUIRED)"
    )

    exec_help = _run_readonly([exe, "exec", "--help"])
    if exec_help is not None and exec_help[0] == 0:
        text = exec_help[1] + "\n" + exec_help[2]
        obs["capabilities"] = {
            "explicit_model_selection": "-m, --model" in text or "--model" in text,
            "reasoning_effort_option": "--reasoning-effort" in text,
            "models_listable": False,  # 无命令枚举 server-side catalog
            "local_provider_option": "--local-provider" in text,
        }
        if "--reasoning-effort" not in text:
            obs["notes"].append(
                "no dedicated reasoning-effort flag in this Codex version; generic "
                "`-c model_options.*` config override mechanism exists "
                "(config-level capability, semantics unverified)"
            )
        obs["notes"].append(
            "Codex CLI does not enumerate the server-side model catalog "
            "(discoverability limitation)"
        )
    return obs


DISCOVERERS = {
    "hermes": discover_hermes,
    "workbuddy": discover_codebuddy,
    "codebuddy": discover_codebuddy,
    "codex": discover_codex,
}


def discover_agent(agent: str) -> dict:
    """按 route agent 名分发 discovery。未知 agent → 全 UNKNOWN 观测。"""
    fn = DISCOVERERS.get(agent)
    if fn is None:
        obs = empty_observation(agent)
        obs["notes"].append(f"no discovery probe for agent {agent!r}")
        return obs
    return fn()


def safe_discover_agent(agent: str) -> dict:
    """非阻塞 discovery 入口：任何异常都吸收为 FAILED 观测，绝不向上抛出。

    Model observability 是辅助 telemetry，不是 execution authority。
    """
    try:
        return discover_agent(agent)
    except Exception as exc:  # noqa: BLE001 — 观测失败不得影响执行
        obs = empty_observation(agent)
        obs["discovery_status"] = DISCOVERY_STATUS_FAILED
        obs["notes"].append(f"discovery raised {type(exc).__name__}: {exc}")
        return obs


def observe_stage(output_dir: Path | str, agent: str) -> dict | None:
    """Runner 用的单入口：discovery + registry 合并 + 持久化。

    任何失败（discovery 异常 / registry 写失败）→ None（非阻塞；
    runner 侧再套一层 try/except 双保险）。返回观测记录（调用方用于
    组装 stage result 的 model_observation_ref）。
    """
    try:
        observation = safe_discover_agent(agent)
        update_registry_entry(output_dir, observation)
        return observation
    except Exception:  # noqa: BLE001 — telemetry 失败不得影响执行
        return None


# ---------------------------------------------------------------------------
# Registry（model_observation.json = model observation authority）
# ---------------------------------------------------------------------------


def _registry_template() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "capability_group": CAPABILITY_GROUP,
        "generated_at": None,
        "authority": (
            f"{ARTIFACT_FILENAME} is the single machine authority for model "
            "observation data; <agent>_result.json carries only a reference. "
            "REPORT contains a compact summary only."
        ),
        "refresh_policy": {
            "refreshable": True,
            "semantics": (
                "entries are re-discovered per run and replaced; one discovery "
                "result is never treated as permanent truth"
            ),
            "model_names": "may be added / removed / renamed by agent updates",
            "free_status": "may change; cost_class filled only from current "
            "provider data, else UNKNOWN",
            "cost_multiplier": "may change; recorded as null unless the "
            "provider/CLI exposes it",
        },
        "observations": {},
    }


def load_registry(output_dir: Path | str) -> dict:
    """读取现有 registry；缺失 / 损坏 → 空 registry（不抛出）。"""
    path = Path(output_dir) / ARTIFACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return _registry_template()
    if not isinstance(data, dict) or not isinstance(data.get("observations"), dict):
        return _registry_template()
    base = _registry_template()
    base["generated_at"] = data.get("generated_at")
    base["observations"] = {
        k: v for k, v in data["observations"].items() if isinstance(v, dict)
    }
    return base


def save_registry(output_dir: Path | str, registry: dict) -> Path:
    """原子写 registry（同目录 tmp + os.replace，符合项目 atomic 约定）。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / ARTIFACT_FILENAME
    tmp = output_dir / f"{ARTIFACT_FILENAME}.tmp-{os.getpid()}"
    tmp.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def update_registry_entry(output_dir: Path | str, observation: dict) -> dict:
    """把单 agent 观测合并进 registry 并持久化（覆盖式刷新）。"""
    registry = load_registry(output_dir)
    agent = observation.get("agent")
    if agent:
        registry["observations"][agent] = observation
    registry["generated_at"] = _now_iso()
    save_registry(output_dir, registry)
    return registry


def refresh_observations(output_dir: Path | str, agents: list[str]) -> dict:
    """对每个 agent 重新 discovery 并刷新 registry（dynamic metadata 原则）。

    注意：调用方负责先检查 ``observations_enabled()``；本函数不做开关判断。
    """
    registry = load_registry(output_dir)
    for agent in agents:
        obs = safe_discover_agent(agent)
        registry["observations"][agent] = obs
    registry["generated_at"] = _now_iso()
    save_registry(output_dir, registry)
    return registry


# ---------------------------------------------------------------------------
# REPORT 数据（紧凑摘要；详细数据留在 artifact）
# ---------------------------------------------------------------------------


def _stage_elapsed(output_dir: Path | str, agent: str) -> float | None:
    """从 ``<agent>_result.json`` 读取 stage_timing.stage_elapsed_seconds。"""
    path = Path(output_dir) / f"{agent}_result.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        timing = data.get("stage_timing") or {}
        elapsed = timing.get("stage_elapsed_seconds")
        return elapsed if isinstance(elapsed, (int, float)) else None
    except Exception:
        return None


def model_report_data(output_dir: Path | str, route_agents: list[str]) -> dict:
    """为 REPORT 组装紧凑数据：{agent: {"observation": ..., "stage_elapsed": ...}}。

    详细 discovery metadata 只存在于 model_observation.json（lazy artifact）；
    REPORT 只消费这里的紧凑摘要。
    """
    registry = load_registry(output_dir)
    observations = registry.get("observations") or {}
    out: dict = {}
    for agent in route_agents:
        entry = observations.get(agent) or empty_observation(agent)
        out[agent] = {
            "observation": entry,
            "stage_elapsed": _stage_elapsed(output_dir, agent),
        }
    return out


def render_compact_summary(model_observations: dict, output_dir: Path | str | None = None) -> str:
    """渲染 REPORT 的 ``## Model Observation`` 紧凑摘要（每 agent 一行 + artifact 行）。"""
    lines = ["## Model Observation"]
    for agent, entry in model_observations.items():
        obs = (entry or {}).get("observation") or {}
        model = obs.get("model") or "UNKNOWN"
        provider = obs.get("provider") or "UNKNOWN"
        source = obs.get("model_source") or MODEL_SOURCE_UNKNOWN
        effort = obs.get("reasoning_effort") or "UNKNOWN"
        cost = obs.get("cost_class") or COST_CLASS_UNKNOWN
        elapsed = (entry or {}).get("stage_elapsed")
        elapsed_s = f"{elapsed:.2f}s" if isinstance(elapsed, (int, float)) else "UNKNOWN"
        lines.append(
            f"- {agent}: model={model} provider={provider} source={source} "
            f"effort={effort} cost={cost} stage={elapsed_s}"
        )
    if output_dir is not None:
        lines.append(f"- Artifact (machine authority): {Path(output_dir) / ARTIFACT_FILENAME}")
    return "\n".join(lines)
