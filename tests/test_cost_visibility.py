"""AAF Bridge — Cost / Model 可见性 display-only 归一化测试。

TASK: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001（Requirements 22 A–K）
+ FIX-001 truth semantics（planned/authorized ≠ actual invocation）
+ FIX-002 paid fallback evidence validation（损坏/字段不完整/非权威 paid
fallback artifact ≠ 真实 paid invocation——Requirement 11 A–H）。

覆盖（FIX-001 主线，Requirement 18 A–K）：
A. cost_guard ALLOWED_AUTHORIZED_PAID without invocation -> Actual UNKNOWN,
   not PAID
B. cost_guard ALLOWED_FREE without invocation -> Actual UNKNOWN,
   not FREE/LOCAL_FREE
C. routing-selected candidate without invocation -> Actual UNKNOWN
D. proven actual FREE invocation -> FREE
E. proven actual LOCAL_FREE invocation -> LOCAL_FREE
F. proven actual PAID invocation -> PAID
G. authorized paid fallback without invocation -> not USED_PAID
H. actual paid fallback invocation -> USED_PAID
I. actual free fallback invocation -> USED_FREE
J. missing evidence -> UNKNOWN
K. completed-task reopen preserves the same truth semantics

另覆盖：
- guard BLOCKED 仅权威阻断时显示 BLOCKED（Requirement 15）
- observation 单独存在（无 invocation）不制造 actual model（blocked 场景防幻影）
- planned/authorized 信息以显式 "Planned:" 文本呈现、不进入 actual 字段
- 缺失/损坏 optional artifact fail-soft（Requirement 14/15）
- 只读：多次 build 文件字节零变化/零新文件 + 无 subprocess/os.environ/
  guard 决策 import
- 词汇闭集 / 行序确定性 / 渲染行格式

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

# FIX-002：valid paid runtime record 只由既有权威模块产生/校验（display 测试
# 不重实现 paid runtime schema——与 Requirement 2 复用权威 validator 一致）
from ai_agent_framework import cost_guard as _cg
from ai_agent_framework import fallback_contract as _fc
from ai_agent_framework import fallback_paid_gate as _fpg
from ai_agent_framework import fallback_runtime as _fr
from ai_agent_framework.risk_contract import RISK_LOW, ROLE_EXECUTOR


def _dump(dirpath: Path, name: str, payload: dict) -> Path:
    path = dirpath / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _guard(decision: str, model: str = "deepseek-v4-flash", provider: str = "deepseek") -> dict:
    """A0 cost_guard.json 形状的最小 record（decision token = 既有权威词汇）。

    FIX-001：guard decision/model/provider 是 pre-invocation 准入证据
    （planned/authorized），单独出现绝不等于 actual invocation。
    """
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


def _fb_paid(used: bool, outcome: str | None = None) -> dict:
    """FIX-002：schema-valid authoritative paid runtime audit record。

    合法 JSON dict ≠ 合法 evidence——valid case 的 fixture 走既有权威组装器
    ``fallback_runtime.assemble_paid_runtime_audit_record``（组装即
    fail-closed 校验，含 decision_kind / authority / attempted=true /
    全 required 字段 / AUTHORIZED gate + exact scope / candidates / final /
    outcome 一致性不变量），与真实 paid fallback 执行后落盘的 record 同构。
    """
    if outcome is None:
        outcome = "success" if used else "failed"
    task_id = "AAF-CV-FIX002-T"
    paid_candidate = "glm-5.2@zhipu"
    gate_record = {
        "paid_candidate": paid_candidate,
        "contract_candidates": [paid_candidate],
        "paid_candidates": [paid_candidate],
        "gate_decision": _fpg.GATE_DECISION_AUTHORIZED,
        "required_scope": _cg.scope_string(task_id, "hermes", "glm-5.2", "zhipu"),
        "guard_decision": _cg.DECISION_ALLOWED_AUTHORIZED_PAID,
        "authorization_present": True,
        "authorization_matched": True,
        "authorization_consumed": True,
    }
    decision_record = {
        "failure_class": _fc.FAILURE_INVOCATION,
        "failure_label": _fc.FAILURE_LABELS[_fc.FAILURE_INVOCATION],
        "trigger": "RuntimeError: original invocation failed (simulated)",
        "trigger_evidence": ["original invocation raised RuntimeError (simulated)"],
    }
    return _fr.assemble_paid_runtime_audit_record(
        decision_record=decision_record,
        original_identity={"model": "deepseek-v4-flash", "provider": "deepseek"},
        task_id=task_id,
        stage_agent="hermes",
        role=ROLE_EXECUTOR,
        risk_class=RISK_LOW,
        risk_source="task_risk",
        gate_record=gate_record,
        transport_retry_count=0,
        automatic_fallback_count_used=0,
        free_fallback_unavailable_reason="no eligible FREE/LOCAL_FREE fallback candidate",
        attempted=True,
        used=used,
        paid_invocation_outcome=outcome,
        invocation_evidence=[
            f"paid fallback invocation of {paid_candidate!r} (simulated display fixture)",
        ],
    )


# ---------------------------------------------------------------------------
# A. ALLOWED_AUTHORIZED_PAID without invocation -> Actual UNKNOWN, not PAID
# ---------------------------------------------------------------------------


def test_a_guard_auth_paid_alone_is_never_actual_paid():
    # guard 授权单独存在（无 <agent>_result.md / 无 A5 invocation 证据）
    # -> Actual UNKNOWN，绝不 PAID（FIX-001 Requirement 6）
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_AUTHORIZED_PAID"))
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN
    assert row.provider == DISPLAY_UNKNOWN
    assert row.fallback == FALLBACK_NOT_USED
    assert COST_PAID not in (row.cost_class,)


def test_a_guard_auth_paid_invalid_result_still_unknown():
    # FRAMEWORK_ERROR result（guard 后启动失败/崩溃）-> actual 仍不可证
    row = cv.derive_hermes_row(
        guard=_guard("ALLOWED_AUTHORIZED_PAID"),
        result_md="FRAMEWORK_ERROR\nstartup failed",
    )
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


def test_a_guard_auth_paid_without_invocation_shows_planned_label():
    # Requirement 9/10：planned/authorized 信息保留但显式标签、不冒充 actual
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_AUTHORIZED_PAID"))
    assert row.planned != ""
    assert "deepseek-v4-flash" in row.planned
    assert "PAID" in row.planned
    assert "AUTHORIZED" in row.planned
    assert row.cost_class != COST_PAID  # planned 文本绝不进入 actual cost


# ---------------------------------------------------------------------------
# B. ALLOWED_FREE without invocation -> Actual UNKNOWN, not FREE/LOCAL_FREE
# ---------------------------------------------------------------------------


def test_b_guard_allowed_free_alone_is_never_actual_local_free():
    # ALLOWED_FREE 单独存在 -> Actual UNKNOWN，绝不 LOCAL_FREE/FREE
    # （FIX-001 Requirement 7）
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_FREE", "qwen3:4b", "ollama"))
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN
    assert row.cost_class not in (COST_LOCAL_FREE, COST_FREE)


def test_b_guard_allowed_free_without_invocation_planned_label():
    row = cv.derive_hermes_row(guard=_guard("ALLOWED_FREE", "qwen3:4b", "ollama"))
    assert row.planned != ""
    assert "qwen3:4b" in row.planned
    assert "LOCAL_FREE" in row.planned


def test_b_guard_allowed_free_output_dir_no_result(tmp_path):
    # output_dir 只有 guard（无 hermes_result.md）-> Actual UNKNOWN
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_FREE", "qwen3:4b", "custom"))
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


# ---------------------------------------------------------------------------
# C. routing-selected candidate without invocation -> Actual UNKNOWN
# ---------------------------------------------------------------------------


def test_c_hermes_active_routing_without_invocation_unknown():
    # A3 routing_applied=true（registry LOCAL_FREE 候选）但无 invocation
    # -> Actual UNKNOWN（FIX-001 Requirement 8/18-C）
    active = _active_routing(True, "qwen3:4b", "custom")
    row = cv.derive_hermes_row(active=active)
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


def test_c_hermes_active_routing_output_dir_no_result(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_ACTIVE_ROUTING, _active_routing(True, "qwen3:4b", "custom"))
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN
    assert "qwen3:4b" in row.planned  # 候选信息只进 planned 标签


def test_c_workbuddy_routing_without_invocation_unknown():
    # A4 economic routing winner 存在但无 workbuddy_result.md
    # -> Actual UNKNOWN（routing candidate ≠ actual）
    wb = {
        "routing_applied": True,
        "routed_model": "hy4-preview",
        "economic_facts": {
            "hy4-preview": {"cheapness_rank": 0, "promotion_status": "free"},
        },
    }
    row = cv.derive_workbuddy_row(wb=wb)
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN
    assert "hy4-preview" in row.planned


def test_c_workbuddy_routing_free_promo_without_invocation_not_actual_free():
    # 即使 A4 free-promo 经济事实存在，无 invocation 也绝不 actual FREE
    wb = {
        "routing_applied": True,
        "routed_model": "hy4-preview",
        "economic_facts": {
            "hy4-preview": {"cheapness_rank": 0, "promotion_status": "free"},
        },
    }
    row = cv.derive_workbuddy_row(wb=wb)
    assert row.cost_class != COST_FREE
    assert row.cost_class == COST_UNKNOWN


# ---------------------------------------------------------------------------
# D. proven actual FREE invocation -> FREE
# ---------------------------------------------------------------------------


def test_d_hermes_observation_free_with_invocation_renders_free():
    # observation 端点证据 FREE + <agent>_result.md valid（invocation 已证）
    # -> actual FREE
    row = cv.derive_hermes_row(
        obs=_obs("free-model", "free-provider", "FREE"),
        result_md="SUCCESS\nreal executor output",
    )
    assert row.cost_class == COST_FREE
    assert row.model == "free-model"


def test_d_workbuddy_free_promo_with_invocation_renders_free():
    # A4 free-promo winner + workbuddy_result.md valid（invocation 已证）
    # -> actual FREE
    wb = {
        "routing_applied": True,
        "routed_model": "hy4-preview",
        "economic_facts": {
            "hy4-preview": {"cheapness_rank": 0, "promotion_status": "free"},
        },
    }
    row = cv.derive_workbuddy_row(wb=wb, result_md="SUCCESS\nvalidator output")
    assert row.cost_class == COST_FREE
    assert row.model == "hy4-preview"
    assert "free promo" in row.detail


def test_d_workbuddy_free_promo_without_authoritative_rank_is_not_free():
    # 即使 invocation 已证，经济事实不足（rank!=0 / promo!=free）仍不 FREE
    for fact in (
        {"cheapness_rank": 1, "promotion_status": "free"},
        {"cheapness_rank": 0, "promotion_status": "discount"},
        {"cheapness_rank": 2, "promotion_status": "discount"},
    ):
        wb = {"routing_applied": True, "routed_model": "m1", "economic_facts": {"m1": fact}}
        row = cv.derive_workbuddy_row(wb=wb, result_md="SUCCESS\nok")
        assert row.cost_class == COST_UNKNOWN


def test_d_low_medium_economic_routing_never_labels_free():
    # LOW/MEDIUM economic routing 存在（已证 invocation）≠ FREE
    wb = {
        "routing_applied": True,
        "routed_model": "deepseek-v4-flash",
        "economic_facts": {"deepseek-v4-flash": {"cheapness_rank": 1, "promotion_status": "discount"}},
    }
    row = cv.derive_workbuddy_row(wb=wb, result_md="SUCCESS\nok")
    assert row.cost_class == COST_UNKNOWN


# ---------------------------------------------------------------------------
# E. proven actual LOCAL_FREE invocation -> LOCAL_FREE
# ---------------------------------------------------------------------------


def test_e_guard_allowed_free_with_invocation_renders_local_free():
    # guard ALLOWED_FREE + <agent>_result.md valid（local-free model 实际执行）
    # -> actual LOCAL_FREE
    row = cv.derive_hermes_row(
        guard=_guard("ALLOWED_FREE", "qwen3:4b", "ollama"),
        obs=_obs("qwen3:4b", "custom", "LOCAL_FREE"),
        result_md="SUCCESS\nreal output",
    )
    assert row.cost_class == COST_LOCAL_FREE
    assert row.model == "qwen3:4b"


def test_e_observation_local_free_with_invocation_renders_local_free():
    # observation 端点证据 LOCAL_FREE + invocation 已证 -> LOCAL_FREE
    row = cv.derive_hermes_row(
        obs=_obs("qwen3:4b", "custom", "LOCAL_FREE"),
        result_md="SUCCESS\nreal output",
    )
    assert row.cost_class == COST_LOCAL_FREE


def test_e_active_routing_registry_local_free_with_invocation(tmp_path):
    # A3 routing_applied=true + registry LOCAL_FREE + invocation 已证
    # -> LOCAL_FREE（registry 端点证据 + 实际执行）
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_ACTIVE_ROUTING, _active_routing(True, "qwen3:4b", "custom"))
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_FREE", "qwen3:4b", "custom"))
    (out / "hermes_result.md").write_text("SUCCESS\nreal output", encoding="utf-8")
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_LOCAL_FREE


# ---------------------------------------------------------------------------
# F. proven actual PAID invocation -> PAID
# ---------------------------------------------------------------------------


def test_f_guard_auth_paid_with_invocation_renders_paid():
    # guard ALLOWED_AUTHORIZED_PAID + <agent>_result.md valid
    # （已授权 paid-class model 实际执行）-> actual PAID
    row = cv.derive_hermes_row(
        guard=_guard("ALLOWED_AUTHORIZED_PAID"),
        obs=_obs("deepseek-v4-flash", "deepseek", "UNKNOWN"),
        result_md="SUCCESS\nreal executor output",
    )
    assert row.cost_class == COST_PAID
    assert row.model == "deepseek-v4-flash"
    assert row.provider == "deepseek"
    assert row.fallback == FALLBACK_NOT_USED
    assert row.planned == ""  # actual 已证，不需要 planned 标签


def test_f_output_dir_full_proven_paid(tmp_path):
    # 真实形状 output_dir：guard + obs + valid result.md -> actual PAID
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_AUTHORIZED_PAID"))
    _dump(out, cv.ARTIFACT_MODEL_OBSERVATION, {"observations": {"hermes": _obs(
        "deepseek-v4-flash", "deepseek", "UNKNOWN")}})
    (out / "hermes_result.md").write_text("SUCCESS\nreal output", encoding="utf-8")
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_PAID
    assert row.model == "deepseek-v4-flash"


def test_f_paid_fallback_runtime_is_paid():
    # A5 paid runtime audit（真实 paid-class invocation）-> PAID
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=True))
    assert row.cost_class == COST_PAID
    assert row.fallback == FALLBACK_USED_PAID
    assert row.model == "glm-5.2"


# ---------------------------------------------------------------------------
# G. authorized paid fallback without invocation -> not USED_PAID
# ---------------------------------------------------------------------------


def test_g_gate_authorized_without_invocation_is_not_used_paid():
    # Requirement 12/14/18-G：gate AUTHORIZED（授权）无 paid runtime invocation
    # 证据 -> 绝不 USED_PAID（= NOT_USED + detail）
    row = cv.derive_hermes_row(gate=_gate("AUTHORIZED"))
    assert row.fallback != FALLBACK_USED_PAID
    assert row.fallback == FALLBACK_NOT_USED
    assert "not USED_PAID" in row.detail


def test_g_gate_authorized_with_guard_but_no_paid_runtime_is_not_paid():
    # guard AUTH_PAID + gate AUTHORIZED，但无 paid_fallback_runtime.json
    # （原 invocation 失败、paid fallback 未真实执行）-> cost 不是 PAID
    row = cv.derive_hermes_row(
        guard=_guard("ALLOWED_AUTHORIZED_PAID"),
        gate=_gate("AUTHORIZED"),
        fb_free=_fb_free(used=False),
        result_md="FRAMEWORK_ERROR\noriginal failed",
    )
    assert row.fallback != FALLBACK_USED_PAID
    assert row.cost_class != COST_PAID
    assert row.cost_class == COST_UNKNOWN


# ---------------------------------------------------------------------------
# H. actual paid fallback invocation -> USED_PAID
# ---------------------------------------------------------------------------


def test_h_paid_fallback_used_renders_used_paid():
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=True))
    assert row.fallback == FALLBACK_USED_PAID
    assert row.cost_class == COST_PAID
    assert "authorized paid fallback" in row.detail


def test_h_paid_fallback_attempt_failed_renders_failed():
    # attempted=true / used=false（paid invocation 真实发生但输出未被接受）
    # -> fallback FAILED（绝不 USED_PAID），cost PAID（真实 paid 尝试）
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=False, outcome="failed"))
    assert row.fallback == FALLBACK_FAILED
    assert row.fallback != FALLBACK_USED_PAID
    assert row.cost_class == COST_PAID
    assert row.model == "glm-5.2"


# ---------------------------------------------------------------------------
# I. actual free fallback invocation -> USED_FREE
# ---------------------------------------------------------------------------


def test_i_free_fallback_used_renders_used_free():
    # fallback_runtime.json used=true（free fallback invocation 真实发生且被接受）
    row = cv.derive_hermes_row(fb_free=_fb_free(used=True))
    assert row.fallback == FALLBACK_USED_FREE
    assert row.cost_class == COST_LOCAL_FREE
    assert "free fallback" in row.detail


def test_i_free_fallback_attempt_failed_renders_failed():
    # attempted-not-used -> FAILED（绝不 USED_FREE）
    row = cv.derive_hermes_row(fb_free=_fb_free(used=False))
    assert row.fallback == FALLBACK_FAILED
    assert row.fallback != FALLBACK_USED_FREE
    assert "original failure preserved" in row.detail


# ---------------------------------------------------------------------------
# J. missing evidence -> UNKNOWN
# ---------------------------------------------------------------------------


def test_j_no_evidence_renders_unknown():
    for row in (
        cv.derive_hermes_row(),
        cv.derive_workbuddy_row(),
        cv.derive_codex_row(),
    ):
        assert row.cost_class == COST_UNKNOWN
        assert row.model == DISPLAY_UNKNOWN
        assert row.provider == DISPLAY_UNKNOWN
        assert row.fallback == FALLBACK_NOT_USED
        assert row.planned == ""


def test_j_observation_without_invocation_does_not_make_actual_model():
    # FIX-001 关键场景：observation 存在（blocked stage 也会写 observation）
    # 但无 invocation -> model/provider 不得回显（防幻影 actual）
    row = cv.derive_hermes_row(obs=_obs("deepseek-v4-flash", "deepseek", "UNKNOWN"))
    assert row.model == DISPLAY_UNKNOWN
    assert row.provider == DISPLAY_UNKNOWN
    assert row.cost_class == COST_UNKNOWN


def test_j_workbuddy_auto_preserved_is_unknown():
    # Auto 保留（routing_applied=false）-> actual model/cost UNKNOWN
    wb = {"routing_applied": False, "routed_model": None, "reason": "RISK_OUTSIDE_ACTIVE_SLICE: x"}
    row = cv.derive_workbuddy_row(wb=wb, result_md="SUCCESS\nok")
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


# ---------------------------------------------------------------------------
# BLOCKED（Requirement 15）+ gate 语义
# ---------------------------------------------------------------------------


def test_guard_blocked_renders_blocked():
    # guard BLOCKED_COST_APPROVAL = 权威阻断证据（Hermes 未执行）-> BLOCKED
    row = cv.derive_hermes_row(guard=_guard("BLOCKED_COST_APPROVAL"))
    assert row.cost_class == COST_BLOCKED
    assert row.detail == "blocked: cost approval required"
    assert row.fallback == FALLBACK_NOT_USED
    assert row.planned == ""


def test_guard_blocked_with_observation_model_still_unknown_model():
    # blocked stage：即使 observation 有 model 也不得显示为 actual model
    row = cv.derive_hermes_row(
        guard=_guard("BLOCKED_COST_APPROVAL"),
        obs=_obs("deepseek-v4-flash", "deepseek", "UNKNOWN"),
    )
    assert row.cost_class == COST_BLOCKED
    assert row.model == DISPLAY_UNKNOWN


def test_paid_gate_blocked_alone_does_not_label_cost_blocked():
    # gate BLOCKED = 付费兜底被阻断（fallback FAILED），cost 显示不是 BLOCKED
    # ——BLOCKED 只来自权威 guard 阻断证据（Requirement 13/15）
    row = cv.derive_hermes_row(
        gate=_gate("BLOCKED"),
        obs=_obs("deepseek-v4-flash", "deepseek"),
        result_md="FRAMEWORK_ERROR\noriginal failed",
    )
    assert row.cost_class == COST_UNKNOWN
    assert row.fallback == FALLBACK_FAILED


def test_paid_gate_fail_closed_fallback_failed():
    row = cv.derive_hermes_row(gate=_gate("FAIL_CLOSED"))
    assert row.fallback == FALLBACK_FAILED


# ---------------------------------------------------------------------------
# K. completed-task reopen preserves the same truth semantics
# ---------------------------------------------------------------------------


def _completed_task_dir(tmp_path: Path, with_result: bool = True) -> Path:
    out = tmp_path / "AAF-REOPEN-1"
    out.mkdir()
    _dump(out, "route.json", {"agents": ["hermes", "workbuddy", "codex"]})
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_AUTHORIZED_PAID"))
    _dump(
        out, cv.ARTIFACT_MODEL_OBSERVATION,
        {"observations": {"hermes": _obs("deepseek-v4-flash", "deepseek", "UNKNOWN")}},
    )
    _dump(out, cv.ARTIFACT_ACTIVE_ROUTING, _active_routing(False, None))
    if with_result:
        (out / "hermes_result.md").write_text("SUCCESS\nreal executor output", encoding="utf-8")
    (out / "REPORT.md").write_text("# REPORT", encoding="utf-8")
    return out


def test_k_reopen_reconstructs_same_rows(tmp_path):
    out = _completed_task_dir(tmp_path)
    first = [(r.agent, r.cost_class, r.model, r.fallback, r.planned) for r in cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])]
    # 第二次读取（模拟窗口/终端 reopen：只读持久化 artifact）= 同一显示
    second = [(r.agent, r.cost_class, r.model, r.fallback, r.planned) for r in cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])]
    assert first == second
    hermes = [r for r in cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"]) if r.agent == "hermes"][0]
    assert hermes.cost_class == COST_PAID  # guard AUTH + valid result -> actual PAID
    assert hermes.model == "deepseek-v4-flash"
    assert hermes.planned == ""


def test_k_reopen_guard_only_dir_keeps_unknown_semantics(tmp_path):
    # Reopen 一个只有 guard（无 result.md）的目录：truth 语义保持一致
    # ——actual UNKNOWN + planned 标签，而不是把 authorization 当 actual
    out = _completed_task_dir(tmp_path, with_result=False)
    rows_a = [(r.cost_class, r.model, r.planned) for r in cv.build_cost_rows(out, ["hermes"])]
    rows_b = [(r.cost_class, r.model, r.planned) for r in cv.build_cost_rows(out, ["hermes"])]
    assert rows_a == rows_b
    cost_class, model, planned = rows_a[0]
    assert cost_class == COST_UNKNOWN
    assert model == DISPLAY_UNKNOWN
    assert planned != "" and "AUTHORIZED" in planned


def test_k_row_visible_filters_unstarted_stages(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, "route.json", {"agents": ["hermes", "workbuddy", "codex"]})
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert all(not cv.row_visible(out, r) for r in rows)  # 零 evidence -> 不显示


def test_k_guard_only_row_visible_with_planned(tmp_path):
    # guard 存在（stage 已开始/崩溃但无 result）-> 行可见（planned 信息）
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_COST_GUARD, _guard("ALLOWED_AUTHORIZED_PAID"))
    rows = cv.build_cost_rows(out, ["hermes"])
    assert rows and cv.row_visible(out, rows[0])
    assert rows[0].planned != ""


# ---------------------------------------------------------------------------
# FIX-002（TASK: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-002）
# paid fallback evidence validation：损坏/非权威 artifact ≠ actual paid usage
# ---------------------------------------------------------------------------


def test_fix002_a_empty_paid_dict_is_not_paid_evidence():
    # A. fb_paid = {}（可解析 JSON 但零字段）-> 绝不 PAID / USED_PAID
    row = cv.derive_hermes_row(fb_paid={})
    assert row.cost_class == COST_UNKNOWN
    assert row.cost_class != COST_PAID
    assert row.fallback == FALLBACK_NOT_USED
    assert row.fallback != FALLBACK_USED_PAID
    assert row.model == DISPLAY_UNKNOWN


def test_fix002_a_empty_paid_dict_output_dir_not_paid(tmp_path):
    # A（output_dir 路径）：paid_fallback_runtime.json = {} -> 不 PAID/USED_PAID
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_PAID_RUNTIME, {})
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_UNKNOWN
    assert row.fallback == FALLBACK_NOT_USED
    rows = cv.build_cost_rows(out, ["hermes"])
    assert rows[0].cost_class == COST_UNKNOWN
    assert rows[0].fallback != FALLBACK_USED_PAID


def test_fix002_b_missing_required_fields_is_unknown():
    # B. schema-valid record 缺 required 字段 -> UNKNOWN（不 PAID/USED_PAID）
    base = _fb_paid(used=True)
    for key in ("authority", "no_silent_paid_evidence", "paid_required_scope",
                "decision_kind"):
        broken = dict(base)
        del broken[key]
        row = cv.derive_hermes_row(fb_paid=broken)
        assert row.cost_class == COST_UNKNOWN, key
        assert row.cost_class != COST_PAID, key
        assert row.fallback != FALLBACK_USED_PAID, key
        assert row.fallback == FALLBACK_NOT_USED, key


def test_fix002_b_missing_required_fields_output_dir_unknown(tmp_path):
    # B（output_dir 路径）：合法但字段不全的 JSON record -> UNKNOWN
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_PAID_RUNTIME, {"decision_kind": "paid_fallback_runtime_audit"})
    rows = cv.build_cost_rows(out, ["hermes"])
    assert rows[0].cost_class == COST_UNKNOWN
    assert rows[0].fallback != FALLBACK_USED_PAID


def test_fix002_c_wrong_decision_kind_is_unknown():
    # C. decision_kind ≠ paid_fallback_runtime_audit -> UNKNOWN
    wrong = dict(_fb_paid(used=True), decision_kind="fallback_runtime_audit")
    row = cv.derive_hermes_row(fb_paid=wrong)
    assert row.cost_class == COST_UNKNOWN
    assert row.cost_class != COST_PAID
    assert row.fallback == FALLBACK_NOT_USED
    assert row.fallback != FALLBACK_USED_PAID


def test_fix002_d_fallback_attempted_false_is_not_paid():
    # D. fallback_attempted=false（含 used=false）-> 不是真实 paid invocation
    not_attempted = dict(
        _fb_paid(used=False),
        fallback_attempted=False,
        fallback_used=False,
        paid_invocation_outcome="failed",
    )
    row = cv.derive_hermes_row(fb_paid=not_attempted)
    assert row.cost_class == COST_UNKNOWN
    assert row.cost_class != COST_PAID
    assert row.fallback == FALLBACK_NOT_USED
    assert row.fallback != FALLBACK_USED_PAID


def test_fix002_d_attempted_false_never_used_paid_with_other_evidence():
    # D': attempted=false 的 paid artifact 与 guard/gate 组合也不产生 USED_PAID
    not_attempted = dict(
        _fb_paid(used=False),
        fallback_attempted=False,
        fallback_used=False,
        paid_invocation_outcome="failed",
    )
    row = cv.derive_hermes_row(
        fb_paid=not_attempted,
        guard=_guard("ALLOWED_AUTHORIZED_PAID"),
        gate=_gate("AUTHORIZED"),
        result_md="FRAMEWORK_ERROR\noriginal failed",
    )
    assert row.fallback != FALLBACK_USED_PAID
    assert row.fallback == FALLBACK_NOT_USED
    # cost 不可证 -> UNKNOWN（guard AUTH + 无效 result ≠ 实际 paid invocation）
    assert row.cost_class == COST_UNKNOWN


def test_fix002_e_schema_invalid_contradictory_is_unknown():
    # E. schema-invalid / 矛盾 record -> UNKNOWN（绝不 PAID/USED_PAID）
    contradictions = (
        dict(_fb_paid(used=True), paid_invocation_outcome="failed"),       # used↔outcome 矛盾
        dict(_fb_paid(used=False), paid_invocation_outcome="success"),
        dict(_fb_paid(used=True), paid_gate_decision=_fpg.GATE_DECISION_BLOCKED),
        dict(_fb_paid(used=True), authorization_consumed=False),
        dict(_fb_paid(used=True), authoritative=False),
        dict(_fb_paid(used=True), final_actual_model="other-model"),        # final ≠ candidate
    )
    for broken in contradictions:
        row = cv.derive_hermes_row(fb_paid=broken)
        assert row.cost_class != COST_PAID, broken
        assert row.fallback != FALLBACK_USED_PAID, broken
        assert row.cost_class == COST_UNKNOWN, broken
        assert row.fallback == FALLBACK_NOT_USED, broken


def test_fix002_f_valid_paid_used_still_renders_paid_used_paid():
    # F. schema-valid paid used -> PAID + USED_PAID（valid case 保持）
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=True))
    assert row.cost_class == COST_PAID
    assert row.fallback == FALLBACK_USED_PAID
    assert row.model == "glm-5.2"
    assert row.provider == "zhipu"
    assert row.planned == ""


def test_fix002_f_valid_paid_output_dir_renders(tmp_path):
    # F（output_dir 路径）：真实权威 record 文件 -> PAID/USED_PAID
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_PAID_RUNTIME, _fb_paid(used=True))
    row = cv.derive_hermes_row(output_dir=out)
    assert row.cost_class == COST_PAID
    assert row.fallback == FALLBACK_USED_PAID
    assert row.model == "glm-5.2"


def test_fix002_g_valid_paid_attempted_but_failed_not_inventing_usage():
    # G. attempted=true / used=false -> FAILED（真实 paid attempt 已发生；
    #    不捏造成功 usage——绝不 USED_PAID）
    row = cv.derive_hermes_row(fb_paid=_fb_paid(used=False))
    assert row.fallback == FALLBACK_FAILED
    assert row.fallback != FALLBACK_USED_PAID
    assert "attempted but not accepted" in row.detail


def test_fix002_h_gate_authorized_without_paid_runtime_not_used_paid():
    # H. gate AUTHORIZED 无（或只有损坏的）paid runtime -> 不 USED_PAID
    for fb in (None, {}):
        row = cv.derive_hermes_row(gate=_gate("AUTHORIZED"), fb_paid=fb)
        assert row.fallback != FALLBACK_USED_PAID
        assert row.fallback == FALLBACK_NOT_USED
        assert "not USED_PAID" in row.detail
        assert row.cost_class == COST_UNKNOWN


def test_fix002_corrupt_paid_file_never_crashes_bridge(tmp_path):
    # fail-soft：损坏 paid artifact（不可解析 / 非 dict / 空文件）绝不 crash UI
    out = tmp_path / "t"
    out.mkdir()
    (out / cv.ARTIFACT_PAID_RUNTIME).write_text("{broken json", encoding="utf-8")
    rows = cv.build_cost_rows(out, ["hermes"])
    assert rows[0].cost_class == COST_UNKNOWN
    (out / cv.ARTIFACT_PAID_RUNTIME).write_text("[]", encoding="utf-8")
    rows = cv.build_cost_rows(out, ["hermes"])
    assert rows[0].cost_class == COST_UNKNOWN
    (out / cv.ARTIFACT_PAID_RUNTIME).write_text("", encoding="utf-8")
    rows = cv.build_cost_rows(out, ["hermes"])
    assert rows[0].cost_class == COST_UNKNOWN
    assert rows[0].fallback != FALLBACK_USED_PAID


def test_fix002_display_reuses_authoritative_validator():
    # Requirement 2：显示层复用既有权威 validator，不重实现第二份 paid schema
    source = Path(cv.__file__).read_text(encoding="utf-8")
    assert "validate_paid_fallback_runtime_record" in source
    assert "from ai_agent_framework import fallback_runtime" in source
    # 独立于显示层的权威拒绝语义（{} / attempted=false）由 A5 validator 保证：
    with pytest.raises(ValueError):
        _fr.validate_paid_fallback_runtime_record({})
    with pytest.raises(ValueError):
        _fr.validate_paid_fallback_runtime_record(
            dict(_fb_paid(used=False), fallback_attempted=False)
        )


# ---------------------------------------------------------------------------
# 只读 / fail-soft / 词汇 / 渲染辅助
# ---------------------------------------------------------------------------


def test_missing_artifacts_no_crash(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, "route.json", {"agents": ["hermes", "workbuddy", "codex"]})
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert len(rows) == 3
    for row in rows:
        assert row.cost_class == COST_UNKNOWN
        assert row.model == DISPLAY_UNKNOWN
        assert row.fallback == FALLBACK_NOT_USED


def test_corrupt_artifacts_no_crash_and_unknown(tmp_path):
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


def test_wrong_type_observation_entry(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    _dump(out, cv.ARTIFACT_MODEL_OBSERVATION, {"observations": {"hermes": "not-a-dict"}})
    row = cv.build_cost_rows(out, ["hermes"])[0]
    assert row.cost_class == COST_UNKNOWN
    assert row.model == DISPLAY_UNKNOWN


def test_build_never_raises(tmp_path):
    out = tmp_path / "t"
    out.mkdir()
    (out / cv.ARTIFACT_MODEL_OBSERVATION).write_text("\x00\x01\x02", encoding="latin-1")
    rows = cv.build_cost_rows(out, ["hermes", "workbuddy", "codex"])
    assert rows and all(r.cost_class == COST_UNKNOWN for r in rows)


def test_build_does_not_mutate_artifacts(tmp_path):
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


def test_display_module_has_no_payment_side_effect_imports():
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


def test_vocabularies_are_closed_sets():
    assert set(cv.COST_CLASSES_DISPLAY) == {COST_FREE, COST_LOCAL_FREE, COST_PAID, COST_UNKNOWN, COST_BLOCKED}
    assert set(cv.FALLBACK_DISPLAY_VALUES) == {
        FALLBACK_NOT_USED, FALLBACK_USED_FREE, FALLBACK_USED_PAID, FALLBACK_FAILED, "UNKNOWN",
    }


def test_render_row_line_proven_paid_compact_format():
    # 已证 invocation -> 主行 = actual（cost PAID + model）
    row = cv.derive_hermes_row(
        guard=_guard("ALLOWED_AUTHORIZED_PAID"),
        obs=_obs("deepseek-v4-flash", "deepseek", "UNKNOWN"),
        result_md="SUCCESS\nok",
    )
    line = cv.render_row_line(row, "Hermes")
    assert line.startswith("Hermes")
    assert COST_PAID in line
    assert "deepseek-v4-flash" in line
    assert "(deepseek)" in line
    assert "Planned:" not in line  # actual 已证，无 planned 标签


def test_render_row_line_planned_labeled(tmp_path):
    # actual 不可证 -> planned 信息显式 "Planned:" 标签（Requirement 9/10）
    row = cv.derive_hermes_row(
        guard=_guard("ALLOWED_AUTHORIZED_PAID"),
        result_md="",
    )
    line = cv.render_row_line(row, "Hermes")
    assert COST_UNKNOWN in line
    assert "Planned:" in line
    assert "PAID / AUTHORIZED" in line


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
