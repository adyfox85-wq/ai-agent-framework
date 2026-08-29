"""AAF-v0.5-A0-PAID-GUARD-001-FIX-002 对抗性回归测试。

Codex REQUEST_CHANGE 的三个阻断发现，每项一个测试区块：
1. 本地端点分类必须是 hostname/IP 语义（不是 substring）→ fail-closed
2. AAF_COST_FREE_MODELS（或任何用户可控 env 元数据）不是权威 FREE 来源
3. 授权必须是真正的一次性（准入即消费；replay 拒绝；消费失败 fail closed）

conftest hermetic（autouse）会清除 guard env 并清空 in-process 消费集合。
"""
import json

import pytest

from ai_agent_framework import cost_guard as cg
from ai_agent_framework import runner as runner_mod

MINIMAL_VALID_TASK = """# Task ID
T-EXEC

# Task Name
执行链测试

# Objective
实现功能并验收

# Acceptance
1. 通过
"""


def _paid_resolution(model="deepseek-v4-flash", provider="deepseek", base_url=None):
    return {
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "model_source": cg.MODEL_SOURCE_ENV,
        "notes": ["test paid resolution"],
    }


def _run_full_runner(tmp_path, monkeypatch, task_text=MINIMAL_VALID_TASK):
    """完整 runner.run（真实 lifecycle / filesystem；mock run_agent 记录调用）。"""
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)

    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding="utf-8")
    return calls, out, report


# ---------------------------------------------------------------------------
# 1. 本地端点对抗（Codex BLOCKING #1 —— hostname/IP 语义，fail-closed）
# ---------------------------------------------------------------------------


def test_classify_fake_local_hostnames_never_local_free():
    """远程 URL 伪装本地（substring 会误判的用例）→ 一律 NOT LOCAL_FREE。"""
    for url in (
        "https://localhost.evil.example/v1",
        "https://notlocalhost.example/v1",
        "https://api.example/127.0.0.1/v1",
        "https://api.example/v1?callback=localhost",
        "https://api.example/v1?host=127.0.0.1",
        "https://api.example/localhost/path",
        "https://127.0.0.1.evil.example/v1",
        "http://localhost.evil.com:11434/v1",
        "http://0.0.0.0:11434/v1",          # bind 通配地址 ≠ 权威本地证据
        "https://8.8.8.8/v1",               # 合法 IP 但非 loopback
        "http://localhost.localdomain/v1",  # 非 exact localhost
        "http://127.0.0.1.example.com/v1",
    ):
        cls, meta = cg.classify_cost("paid-model", "deepseek", url)
        assert cls == cg.COST_PAID_OR_UNKNOWN, url
        assert "local" in meta["evidence"].lower() or "remote" in meta["evidence"].lower()


def test_classify_malformed_or_ambiguous_endpoint_fails_closed():
    """畸形/歧义 endpoint → 无法安全建立真实 hostname → fail closed。"""
    for url in (
        None,
        "",
        "   ",
        "127.0.0.1:11434",             # 无 scheme → 无 hostname
        "localhost:11434",
        "not a url",
        "http:///v1",                  # 无 hostname
        "http://localhost:99999/v1",   # 非法 port
        "http://localhost:abc/v1",     # 非法 port
        "ftp://localhost/v1",          # 非 http(s)
        "file:///C:/local/v1",
        "http://[::1:11434",           # 非法 IPv6
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_PAID_OR_UNKNOWN, repr(url)


def test_classify_exact_localhost_is_local_free():
    for url in (
        "http://localhost:11434/v1",
        "http://LOCALHOST:11434/v1",       # urlsplit 小写化 → 大小写不敏感
        "https://localhost/v1",
        "http://localhost:11434/v1?x=1#f",
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_LOCAL_FREE, url


def test_classify_loopback_ip_variants_local_free():
    """标准 parser（ipaddress）支持的标准 loopback 语义。"""
    for url in (
        "http://127.0.0.1:11434/v1",
        "http://127.0.0.2:11434/v1",           # 127.0.0.0/8 全段 loopback
        "http://127.255.255.255:11434/v1",
        "http://[::1]:11434/v1",
        "http://[0:0:0:0:0:0:0:1]:11434/v1",   # ::1 长写
        "http://[::ffff:127.0.0.1]:11434/v1",  # IPv4-mapped loopback
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_LOCAL_FREE, url


def test_classify_userinfo_cannot_fake_local_host():
    # userinfo 不是 hostname：真实 host 才是判定依据
    cls, _ = cg.classify_cost("m", "p", "http://127.0.0.1@evil.example/v1")
    assert cls == cg.COST_PAID_OR_UNKNOWN
    cls, _ = cg.classify_cost("m", "p", "http://evil.example@127.0.0.1/v1")
    assert cls == cg.COST_LOCAL_FREE


def test_classify_ollama_with_fake_local_remote_base_url_fails_closed():
    # ollama provider + 伪装本地 URL → PAID_OR_UNKNOWN（endpoint 证据优先）
    cls, _ = cg.classify_cost("qwen3:4b", "ollama", "http://localhost.evil.example/v1")
    assert cls == cg.COST_PAID_OR_UNKNOWN
    cls, _ = cg.classify_cost("qwen3:4b", "ollama", "http://127.0.0.1:11434/v1")
    assert cls == cg.COST_LOCAL_FREE


# ---------------------------------------------------------------------------
# 2. FREE 元数据（Codex BLOCKING #2 —— AAF_COST_FREE_MODELS 非权威）
# ---------------------------------------------------------------------------


def test_classify_no_remote_free_authority_fix002():
    """A0 无权威远程 FREE registry：任何远程/API 模型一律 PAID_OR_UNKNOWN。"""
    for model, provider, url in (
        ("free-model-a", "deepseek", None),
        ("deepseek-v4-flash", "deepseek", "https://api.example/v1"),
        ("free-trial-llm", "some-api", None),
    ):
        cls, _ = cg.classify_cost(model, provider, url)
        assert cls == cg.COST_PAID_OR_UNKNOWN, (model, provider, url)


def test_evaluate_free_env_does_not_allow_remote_paid(monkeypatch):
    """AAF_COST_FREE_MODELS=paid-model 不能把远程付费模型变成 ALLOWED_FREE。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_FREE_MODELS, "deepseek-v4-flash@deepseek,deepseek-v4-flash")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert rec["authorization_consumed"] is False
    assert any("IGNORED" in n and "not authoritative" in n for n in rec["notes"])


def test_evaluate_free_env_does_not_allow_remote_paid_with_authless_local(monkeypatch):
    """任意用户可控 env 元数据不能把远程 unknown/paid 变成 ALLOWED_FREE
    （即使 FREE env 同时声明多个条目 + 另一模型）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_FREE_MODELS, "anything,another-model@deepseek")
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL


def test_evaluate_free_env_remote_local_ollama_unaffected(monkeypatch):
    """FREE env 存在不干扰本地路径：本地 ollama 仍 ALLOWED_FREE（本地证据）。"""
    monkeypatch.setenv(cg.ENV_FREE_MODELS, "garbage-model")
    rec = cg.evaluate("T1", "hermes")  # hermetic：本地 ollama
    assert rec["decision"] == cg.DECISION_ALLOWED_FREE
    assert any("IGNORED" in n for n in rec["notes"])


# ---------------------------------------------------------------------------
# 3. 一次性授权消费（Codex BLOCKING #3 —— 准入即消费，replay 拒绝）
# ---------------------------------------------------------------------------


def test_one_time_auth_first_admission_allowed_second_blocked(monkeypatch):
    """同一进程内：精确授权第一次准入 allowed，第二次（同值）replay → blocked。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec1 = cg.evaluate("T1", "hermes")
    assert rec1["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert rec1["authorization_consumed"] is True
    rec2 = cg.evaluate("T1", "hermes")
    assert rec2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec2["authorization_consumed"] is True
    assert any("consumed" in n for n in rec2["notes"])


def test_one_time_auth_state_dir_fresh_process_replay_blocked(monkeypatch, tmp_path):
    """state_dir 持久化：模拟 fresh process 用同一执行目录 + 同一授权值 re-entry。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec1 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec1["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    marker = tmp_path / cg.CONSUMPTION_FILENAME
    assert marker.exists()
    cg._CONSUMED_AUTHS.clear()  # 模拟新进程（仅剩磁盘消费记录）
    rec2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec2["authorization_consumed"] is True


def test_one_time_auth_consumed_state_blocks_any_later_admission(monkeypatch, tmp_path):
    """消费后同一 execution 上下文内无法再次准入：同值 replay 与新值均 blocked。

    整串精确匹配下，同 scope 只有唯一匹配值；消费后该值永久失效（fail-closed），
    且消费记录不产生任何 later fail-open。
    """
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    cg._CONSUMED_AUTHS.clear()
    # 同值 replay（跨进程等价：仅剩磁盘 marker）→ blocked
    rec2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec2["authorization_consumed"] is True
    # 尝试其他值（不同 model 的授权）→ 不匹配 scope → blocked，且不产生消费
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|other-model|deepseek")
    rec3 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec3["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec3["authorization_consumed"] is False


def test_one_time_auth_consumption_uncertain_fails_closed(monkeypatch, tmp_path):
    """消费状态不确定（marker 不可读）→ fail closed（BLOCKED，不静默放行）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    (tmp_path / cg.CONSUMPTION_FILENAME).mkdir()  # marker 路径是目录 → 读失败 → 状态不确定
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is True


def test_consume_auth_write_failure_returns_error(tmp_path):
    """持久化失败路径（函数级）：返回错误 → 调用方 fail closed。"""
    state_dir = tmp_path / "afile"
    state_dir.write_text("x")  # state_dir 是文件 → marker.parent.mkdir 失败
    ok, err = cg._consume_auth("auth-x", "scope-x", state_dir)
    assert ok is False
    assert "persist" in err


def test_one_time_auth_unmatched_not_consumed(monkeypatch, tmp_path):
    """未匹配的授权不产生消费记录 → 后续正确授权仍可准入（不误锁不 fail-open）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "OTHER|hermes|deepseek-v4-flash|deepseek")
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    rec2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec2["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID


def test_one_time_auth_malformed_authorization_blocked(monkeypatch):
    """畸形授权（缺字段/多余字段）→ blocked，且不消费任何状态。

    注：env 值的前后空白由 _auth_env_value 归一化（Windows env 常见），
    非结构畸形；结构畸形（缺 model/provider、多余字段）绝不匹配。
    """
    for bad in (
        "T1|hermes",
        "T1|hermes|deepseek-v4-flash",
        "T1|hermes|deepseek-v4-flash|deepseek|extra",
    ):
        monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
        monkeypatch.setenv(cg.ENV_AUTH, bad)
        rec = cg.evaluate("T1", "hermes")
        assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL, bad
        assert rec["authorization_consumed"] is False


def test_runner_replay_same_auth_second_admission_blocked(tmp_path, monkeypatch):
    """runner 集成：授权放行一次后，同一 execution 目录内同一授权值再准入 → BLOCKED。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T-EXEC|hermes|deepseek-v4-flash|deepseek")
    calls, out, report = _run_full_runner(tmp_path, monkeypatch)
    assert calls == ["hermes", "workbuddy"]
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert guard["authorization_consumed"] is True
    assert (out / cg.CONSUMPTION_FILENAME).exists()
    # 模拟 fresh process 在同一执行上下文（同一 output dir）replay：
    cg._CONSUMED_AUTHS.clear()
    rec = cg.evaluate("T-EXEC", "hermes", state_dir=out)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is True


def test_blocked_replay_text_mentions_one_time(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T1|hermes|deepseek-v4-flash|deepseek")
    cg.evaluate("T1", "hermes", state_dir=tmp_path)  # admission 1（消费）
    cg._CONSUMED_AUTHS.clear()
    rec2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)  # replay → blocked
    text = cg.blocked_stage_text(rec2)
    assert text.startswith("FRAMEWORK_ERROR\nCOST_APPROVAL_REQUIRED")
    assert "一次性语义" in text
    assert "不可再次准入" in text
