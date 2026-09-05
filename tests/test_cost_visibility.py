"""AAF Bridge — Cost / Model 可见性 display-only 归一化测试。

TASK: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001（Requirements 22 A–K）。

覆盖：
A. proven FREE renders FREE（A4 authoritative free-promo 证据路径）
B. proven LOCAL_FREE renders LOCAL_FREE（A0 ALLOWED_FREE / registry 端点证据）
C. proven PAID renders PAID（A0 ALLOWED_AUTHORIZED_PAID + 真实 paid runtime）
D. unavailable/ambiguous evidence renders UNKNOWN（绝不猜）
E. blocked paid state renders BLOCKED only when authoritative（guard BLOCKED；
   gate BLOCKED 不把 cost 误标 BLOCKED）
F. free fallback renders USED_FREE（A5 fallback_runtime used=true）
G. actual authorized paid fallback renders USED_PAID（paid runtime used=true）
H. authorized-but-not-invoked paid gate does NOT render USED_PAID
I. missing/corrupt optional artifact does not crash -> UNKNOWN
J. completed-task reopen（持久化 artifact 重读）deterministically reconstructs
K. no routing/payment authority is mutated（只读；文件字节零变化）

全部为 display-only 断言：只验证归一化输出，绝不触碰 routing/payment 代码路径。
"""

import json
from pathlib import Path

import pytest

from bridge import cost_visibility as cv
from bridge.cost_visibility import (
    COST_BLOCKED,
    COST_FREE,
    COST_LOCAL_FREE,
    COST_PAID,
    COST_UNKNOWN,
    FALLBACK_FAILED,
    FALLBACK_NOT_USED,
    FALLBACK_USED_FREE,
    FALLBACK_USED_PAID,
    DISPLAY_UNKNOWN,
)


def _dump(dirpath: Path, name: str, payload: dict) -> Path:
    path = dirpath / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _guard(decision: str, model: str = "deepseek-v4-flash", provider: str = "deepseek") -> dict:
    """A0 cost_guard.json 形状的最小 record（decision token = 既有权威词汇）。"""
    cost = "LOCAL_FREE" if decision == "ALLOWED_FREE" else "PAID_OR_UNKNOWN"
    return {
        "decision": decision,
        "cost_class": cost,
        "model": model,
        "provider": provider,
        "authorization_present": decision == "ALLOWED_AUTHORIZED_PAID",
        "authorization_matched": decision == "ALLOWED_AUTHORIZED_PAID",
        "authorization_consumed": decision == "ALLOWED_AUTHORIZED_PAID",
    }


def _obs(model: str | None, provider: str | None = None, cost_class: str = "UNKNOWN") -> dict:
    return {"agent": "hermes", "model": model, "provider": provider, "cost_class": cost_class}


def _active_routing(routing_applied: bool, model: str | None, provider: str | None = None) -> dict:
    return {
        "routing_applied": routing_applied,
        "routed_model": model,
        "routed_provider": provider,
        "configured_model": "deepseek-v4-flash",
    }


def _fb_free(used: bool, original: str = "deepseek-v4-flash", final: str = "qwen3:4b") -> dict:
    return {
        "decision_kind": "fallback_runtime_audit",
        "original_model": original,
        "final_actual_model": final,
        "final_actual_provider": "custom",
        "fallback_attempted": True,
        "fallback_used": used,
        "decision_reason": "eligible free candidate admitted via A0 ALLOWED_FREE",
    }


def _gate(decision: str) -> dict:
    return {"decision_kind": "paid_escalation_gate_audit", "gate_decision": decision}


def _fb_paid(used: bool, outcome: str = "success") -> dict:
    return {
        "decision_kind": "paid_fallback_runtime_audit",
        "original_model": "deepseek-v4-flash",
        "original_provider": "deepseek",
        "paid_candidate": "glm-5.2@zhipu",
        "paid_candidate_model": "glm-5.2",
        "paid_candidate_provider": "zhipu",
        "fallback_attempted": True,
        "fallback_used": used,
        "paid_invocation_outcome": outcome,
        "final_actual_model": "glm-5.2",
        "final_actual_provider": "zhipu",
        "paid_gate_decision": "AUTHORIZED",
        "authorization_present": True,
        "authorization_matched": True,
        "authorization_consumed": True,
    }


# ---------------------------------------------------------------------------
# A. proven FREE renders FREE
# ---------------------------------------------------------------------------


def test_a_workbuddy_free_promo_renders_free():
    # A4 authoritative：routing_applied=true + winner economic fact
    # cheapness_rank==0 + promotion_status=="free"（RANK_AUTHORITATIVE_CHEAP）
    wb = {
        "routing_applied": True,
        "routed_model": "hy4-preview",
        "economic_facts": {
            "hy4-preview": {"cheapness_rank": 0, "promotion_status": "free"},
        },
    }
    row = cv.derive_workbuddy_row(wb=wb, obs=_obs(None))
    assert row.cost_class == COST_FREE
    assert row.model == "hy4-preview"
    assert "free promo" in row.detail


def test_a_free_promo_without_authoritative_rank_is_not_free():
    # cheapness_rank==1（discount）或 promotion_status != free -> 绝不自称 FREE
    for fact in (
        {"cheapness_rank": 1, "promotion_status": "free"},
        {"cheapness_rank": 0, "promotion_status": "discount"},
        {"cheapness_rank": 2, "promotion_status": "discount"},
    ):
        wb = {"routing_applied": True, "routed_model": "m1", "economic_facts": {"m1": fact}}
        row = cv.derive_workbuddy_row(wb=wb, obs=_obs(None))
        assert row.cost_class == COST_UNKNOWN


def test_a_low_medium_economic_routing_alone_never_labels_free():
    # Requirement 9：LOW/MEDIUM economic routing 存在 ≠ FREE（无 free-promo 证据）
    wb = {
        "routing_applied": True,
        "routed_model": "deepseek-v4-flash",
        "economic_facts": {"deepseek-v4-flash": {"cheapness_rank": 1, "promotion_status": "discount"}},
    }
    row = cv.derive_workbuddy_row(wb=wb, obs=_obs(None))
    assert row.cost_class == COST_UNKNOWN
    assert row.model == "deepseek-v4-flash"


def test_a_hermes_free_observation_echo():
    # 显示层词汇映射：observation/registry 显式 FREE 证据 -> FREE（仅回显不推断）
    row = cv.derive_hermes_row(obs=_obs("free-model", "free-provider", "FREE"))
    assert row.cost_class == COST_FREE
    assert row.model == "free-model"


# ---------------------------------------------------------------------------
# B. proven LOCAL_FREE renders LOCAL_FREE
# ---------------------------------------------------------------------------


def test_b_guard_allowed_free_renders_local_free():
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_FREE", "qwen3:4b", "ollama"))
    assert row.cost_class == COST_LOCAL_FREE
    assert row.model == "qwen3:4b"
    assert row.detail == "local free candidate"


def test_b_observation_local_free_endpoint_evidence():
    # 端点证据（observation LOCAL_FREE）-> LOCAL_FREE
    row = cv.derive_hermes_row(
        obs=_obs("qwen3:4b", "custom", "LOCAL_FREE"),
    )
    assert row.cost_class == COST_LOCAL_FREE


def test_b_active_routing_registry_local_free(tmp_path):
    # A3 routing_applied=true 且 registry 条目 LOCAL_FREE（qwen3:4b@custom）
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_ACTIVE_ROUTING, _active_routing(True, "qwen3:4b", "custom"))
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_FREE", "qwen3:4b", "custom"))
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_LOCAL_FREE


# ---------------------------------------------------------------------------
# C. proven PAID renders PAID
# ---------------------------------------------------------------------------


def test_c_guard_allowed_authorized_paid_renders_paid():
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_AUTHORIZED_PAID"))
    assert row.cost_class == COST_PAID
    assert row.model == "deepseek-v4-flash"
    assert row.detail == "explicitly authorized paid"


def test_c_paid_fallback_runtime_renders_paid():
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=True))
    assert row.cost_class == COST_PAID
    assert row.fallback == FALLBACK_USED_PAID
    assert row.model == "glm-5.2"


# ---------------------------------------------------------------------------
# D. unavailable / ambiguous evidence renders UNKNOWN
# ---------------------------------------------------------------------------


def test_d_no_evidence_renders_unknown():
    for row in (
        cv.derive_hermes_row(),
        cv.derive_workbuddy_row(),
        cv.derive_codex_row(),
    ):
        assert row.cost_class == COST_UNKNOWN
        assert row.model == DISPLAY_UNKNOWN
        assert row.provider == DISPLAY_UNKNOWN
        assert row.fallback == FALLBACK_NOT_USED


def test_d_guard_paid_or_unknown_without_auth_is_not_paid():
    # guard cost_class=PAID_OR_UNKNOWN 无授权 -> 既不是 PAID 也不是 FREE
    # （真实运行时该 guard 会是 BLOCKED；此处直接构造 guard 缺失场景 = 无证据）
    row = cv.derive_hermes_row(obs=_obs("deepseek-v4-flash", "deepseek", "UNKNOWN"))
    assert row.cost_class == COST_UNKNOWN
    assert row.fallback == FALLBACK_NOT_USED


def test_d_workbuddy_auto_preserved_is_unknown():
    # Auto 保留（routing_applied=false）时 actual model/cost 不可观测 -> UNKNOWN
    wb = {"routing_applied": False, "routed_model": None, "reason": "RISK_OUTSIDE_ACTIVE_SLICE: x"}
    row = cv.derive_workbuddy_row(wb=wb, obs=_obs(None))
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


# ---------------------------------------------------------------------------
# E. blocked renders BLOCKED only when authoritative
# ---------------------------------------------------------------------------


def test_e_guard_blocked_renders_blocked():
    row = cv.derive_hermes_row(guard=_guard("BLOCKED_COST_APPROVAL"))
    assert row.cost_class == COST_BLOCKED
    assert row.detail == "blocked: cost approval required"
    assert row.fallback == FALLBACK_NOT_USED


def test_e_paid_gate_blocked_alone_does_not_label_cost_blocked():
    # gate BLOCKED = 付费兜底被阻断（fallback FAILED），但 cost 显示不是
    # BLOCKED——BLOCKED 只来自权威 guard 阻断证据（Requirement 13）
    row = cv.derive_hermes_row(gate=_gate("BLOCKED"), obs=_obs("deepseek-v4-flash", "deepseek"))
    assert row.cost_class == COST_UNKNOWN
    assert row.fallback == FALLBACK_FAILED


# ---------------------------------------------------------------------------
# F. free fallback renders USED_FREE
# ---------------------------------------------------------------------------


def test_f_free_fallback_used_renders_used_free():
    row = cv.derive_hermes_row(fb_free=_fb_free(used=True))
    assert row.fallback == FALLBACK_USED_FREE
    assert row.cost_class == COST_LOCAL_FREE  # 最终 actual = A0 ALLOWED_FREE 证据
    assert "free fallback" in row.detail


def test_f_free_fallback_attempt_failed_renders_failed():
    row = cv.derive_hermes_row(fb_free=_fb_free(used=False))
    assert row.fallback == FALLBACK_FAILED
    assert "original failure preserved" in row.detail


# ---------------------------------------------------------------------------
# G. actual authorized paid fallback renders USED_PAID
# ---------------------------------------------------------------------------


def test_g_paid_fallback_used_renders_used_paid():
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=True))
    assert row.fallback == FALLBACK_USED_PAID
    assert row.cost_class == COST_PAID
    assert "authorized paid fallback" in row.detail


def test_g_paid_fallback_attempt_failed_renders_failed():
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=False, outcome="failed"))
    assert row.fallback == FALLBACK_FAILED
    assert row.cost_class == COST_PAID  # paid-class invocation 已尝试（证据存在）


# ---------------------------------------------------------------------------
# H. authorized-but-not-invoked paid gate does NOT render USED_PAID
# ---------------------------------------------------------------------------


def test_h_gate_authorized_without_invocation_is_not_used_paid():
    # Requirement 12：授权存在 ≠ 执行发生 -> 绝不 USED_PAID
    row = cv.derive_hermes_row(gate=_gate("AUTHORIZED"))
    assert row.fallback != FALLBACK_USED_PAID
    assert row.fallback == FALLBACK_NOT_USED
    assert "not USED_PAID" in row.detail


# ---------------------------------------------------------------------------
# I. missing / corrupt optional artifact -> UNKNOWN, no crash
# ---------------------------------------------------------------------------


def test_i_missing_artifacts_no_crash(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, "route.json", {"agents": ["hermes", "workbuddy", "codex"]})
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert len(rows) == 3
    for row in rows:
        assert row.cost_class == COST_UNKNOWN
        assert row.model == DISPLAY_UNKNOWN
        assert row.fallback == FALLBACK_NOT_USED


def test_i_corrupt_artifacts_no_crash_and_unknown(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    (out / cv.ARTIFACT_COST_GUARD).write_text("{broken json", encoding="utf-8")
    (out / cv.ARTIFACT_MODEL_OBSERVATION).write_text("not json at all", encoding="utf-8")
    (out / cv.ARTIFACT_ACTIVE_ROUTING).write_text("[]", encoding="utf-8")  # 非 dict
    (out / cv.ARTIFACT_PAID_GATE).write_text("", encoding="utf-8")
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert len(rows) == 3  # 不崩溃；全部降级 UNKNOWN
    for row in rows:
        assert row.cost_class == COST_UNKNOWN
        assert row.model == DISPLAY_UNKNOWN


def test_i_wrong_type_observation_entry(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_MODEL_OBSERVATION, {"observations": {"hermes": "not-a-dict"}})
    row = cv.build_cost_rows(out, ["hermes"])[0]
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


def test_i_build_never_raises(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    (out / cv.ARTIFACT_MODEL_OBSERVATION).write_text("\x00\x01\x02", encoding="latin-1")
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert rows and all(r.cost_class == COST_UNKNOWN for r in rows)


# ---------------------------------------------------------------------------
# J. completed-task reopen deterministically reconstructs from persisted artifacts
# ---------------------------------------------------------------------------


def _completed_task_dir(tmp_path: Path) -> Path:
    out = tmp_path / "AAF-REOPEN-1"
    out.mkdir()
    _dump(out, "route.json", {"agents": ["hermes", "workbuddy", "codex"]})
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_AUTHORIZED_PAID"))
    _dump(
        out, cv.ARTIFACT_MODEL_OBSERVATION,
        {"observations": {"hermes": _obs("deepseek-v4-flash", "deepseek", "UNKNOWN")}},
    )
    _dump(out, cv.ARTIFACT_ACTIVE_ROUTING, _active_routing(False, None))
    (out / "REPORT.md").write_text("# REPORT", encoding="utf-8")
    (out / "hermes_result.md").write_text("ok", encoding="utf-8")
    (out / "workbuddy_result.md").write_text("ok", encoding="utf-8")
    (out / "codex_result.md").write_text("ok", encoding="utf-8")
    return out


def test_j_reopen_reconstructs_same_rows(tmp_path):
    out = _completed_task_dir(tmp_path)
    first = [(r.agent, r.cost_class, r.model, r.fallback) for r in cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])]
    # 第二次读取（模拟窗口/终端 reopen：只读持久化 artifact）= 同一显示
    second = [(r.agent, r.cost_class, r.model, r.fallback) for r in cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])]
    assert first == second
    hermes = [r for r in cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"]) if r.agent == "hermes"][0]
    assert hermes.cost_class == COST_PAID
    assert hermes.model == "deepseek-v4-flash"


def test_j_row_visible_filters_unstarted_stages(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, "route.json", {"agents": ["hermes", "workbuddy", "codex"]})
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert all(not cv.row_visible(out, r) for r in rows)  # 零 evidence -> 不显示


# ---------------------------------------------------------------------------
# K. no routing / payment authority is mutated（只读）
# ---------------------------------------------------------------------------


def test_k_build_does_not_mutate_artifacts(tmp_path):
    out = _completed_task_dir(tmp_path)
    before = {
        name: (p.read_bytes() if p.exists() else None)
        for p in out.iterdir()
        for name in [p.name]
    }
    files_before = sorted(p.name for p in out.iterdir())
    for _ in range(3):
        cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
        cv.build_cost_rows(out, None)
    after = {
        name: (p.read_bytes() if p.exists() else None)
        for p in out.iterdir()
        for name in [p.name]
    }
    assert sorted(after) == files_before
    assert after == before
    # 无任何新文件（无 claim / 无 marker / 无 registry 写入）
    assert sorted(p.name for p in out.iterdir()) == files_before


def test_k_display_module_has_no_payment_side_effect_imports():
    # 显示层只读回显既有 token：零 subprocess / 零环境变量读取 / 零 guard
    # 决策代码 import（唯一框架 import = 函数内延迟的只读 model_registry）
    source = Path(cv.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.environ" not in source
    assert "import cost_guard" not in source
    assert "from ai_agent_framework import cost_guard" not in source
    assert "from ai_agent_framework import" not in source.split("def _registry_cost_label")[0]
    registry_import_idx = source.index("from ai_agent_framework import model_registry")
    def_idx = source.index("def _registry_cost_label")
    assert def_idx < registry_import_idx  # 只读 registry import 仅存在于函数体内


# ---------------------------------------------------------------------------
# 词汇 / 渲染辅助
# ---------------------------------------------------------------------------


def test_vocabularies_are_closed_sets():
    assert set(cv.COST_CLASSES_DISPLAY) == {COST_FREE, COST_LOCAL_FREE, COST_PAID, COST_UNKNOWN, COST_BLOCKED}
    assert set(cv.FALLBACK_DISPLAY_VALUES) == {
        FALLBACK_NOT_USED, FALLBACK_USED_FREE, FALLBACK_USED_PAID, FALLBACK_FAILED, "UNKNOWN",
    }


def test_render_row_line_compact_format():
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_AUTHORIZED_PAID"))
    line = cv.render_row_line(row, "Hermes")
    assert line.startswith("Hermes")
    assert COST_PAID in line
    assert "deepseek-v4-flash" in line
    assert "(deepseek)" in line


def test_render_row_line_unknown_model_no_parens():
    row = cv.CostRow(agent="codex")
    line = cv.render_row_line(row, "Codex")
    assert COST_UNKNOWN in line
    assert DISPLAY_UNKNOWN in line


def test_route_agent_order_is_fixed():
    assert cv.ROUTE_AGENTS == ("hermes", "workbuddy", "codex")


def test_build_rows_order_matches_route_agents(tmp_path):
    out = _completed_task_dir(tmp_path)
    rows = cv.build_cost_rows(out, ["codex", "hermes", "workbuddy"])
    # 行序固定 = ROUTE_AGENTS 序（渲染层与 Stage Strip 同序，不随输入序变化）
    assert [r.agent for r in rows] == ["hermes", "workbuddy", "codex"]
