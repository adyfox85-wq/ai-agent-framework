"""RW-022 FIX-002 regression tests：Explicit Provenance Authority（Fresh-Process Provenance Closure）。

覆盖 TASK-007-FIX-002 Requirement 9 的 A–H + explicit-field authority 语义：

- A: legacy blocking_rework=true + provenance missing → 不得自动当 structured authority
- B: legacy blocking_rework=false + provenance missing → 不得自动当 structured no-blocking authority
- C: explicit provenance=structured + valid bool → 可作为 structured verdict（blocking 与非 blocking 两个方向）
- D: invalid provenance → fail safe（写入路径 build_stage_result + 读取路径 read_structured_blocking）
- E: Hermes SUCCESS narrative 含技术性 FAILED → non-blocking
- F: FRAMEWORK_ERROR + no-blocking structured claim → blocking
- G: empty required result → blocking
- H: PASS_WITH_WARNING + no blocking + Codex APPROVE → SUCCESS

核心语义（Req 3/4/5）：
- structured authority 只来自 agent 结构化块**显式声明**的合法 blocking_provenance 字段
- blocking_rework key 存在 ≠ structured authority；provenance 缺失 = legacy → narrative
- invalid provenance（类型 / 值）→ fail closed（framework hard failure 优先级）
- 优先级：Framework hard failure > explicit structured blocking >
  explicit structured non-blocking > legacy narrative fallback
- 新契约：reviewer 结构化块显式写出 blocking_provenance；不声明不会获得 structured authority
"""
import json
from pathlib import Path

import pytest

import ai_agent_framework.runner as runner_mod
from ai_agent_framework.context_packet import (
    build_stage_result,
    extract_and_validate_structured,
    git_changed_files,
    write_stage_result,
)
from ai_agent_framework.report import (
    BLOCKING_PROVENANCE_FRAMEWORK,
    BLOCKING_PROVENANCE_NARRATIVE,
    BLOCKING_PROVENANCE_STRUCTURED,
    agent_result_blocked,
    read_structured_blocking,
)

MINIMAL_EXPLICIT_ROUTE_TASK = """# Task ID
T-RW022-FIX002

# Task Name
Explicit Provenance Authority 测试

# Objective
实现功能并验收

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过
"""


def _write_stage_json(out: Path, agent: str, *, blocking: bool, status: str = "COMPLETE",
                      verdict: str | None = None, provenance: str | None = None) -> None:
    """写 <agent>_result.json。provenance=None → 不写字段（模拟 legacy artifact）。"""
    data = {
        "protocol": "packet/1",
        "agent": agent,
        "status": "SUCCESS" if not blocking else "FAILED",
        "verdict": verdict or ("APPROVE" if agent == "codex" else "PASS"),
        "blocking_rework": blocking,
        "commit": None,
        "commit_changed": False,
        "tests": None,
        "changed_files": [],
        "evidence_paths": [],
        "findings": [],
        "warnings": [],
        "summary_complete": status == "COMPLETE",
        "structured_summary_status": status,
        "summary": "",
        "narrative_path": str(out / f"{agent}_result.md"),
    }
    if provenance is not None:
        data["blocking_provenance"] = provenance
    (out / f"{agent}_result.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ============ A: legacy blocking_rework=true + provenance missing（Req 9-A） ============

def test_a_legacy_blocking_true_no_provenance_not_structured_authority(tmp_path):
    # 旧 artifact：blocking_rework=true、无 blocking_provenance、COMPLETE
    # → provenance=narrative（不得自动升级 structured authority）；决策值仍 backward
    # compatible：阻断保持阻断（fail-safe，不 fail-open）
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'codex', blocking=True, verdict='REQUEST_CHANGE', status='COMPLETE')
    available, blocking, status, prov = read_structured_blocking('codex', out)
    assert available is True and blocking is True and status == 'COMPLETE'
    assert prov == BLOCKING_PROVENANCE_NARRATIVE
    # narrative 说通过也不放行：legacy blocking 值经 fail-safe 路径仍阻断
    assert agent_result_blocked('codex', '最终判定：APPROVE\nBlocking Issues: NONE', out) is True
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'APPROVE'}, out,
    ) == 'WAITING'


# ============ B: legacy blocking_rework=false + provenance missing（Req 9-B） ============

def test_b_legacy_blocking_false_no_provenance_not_structured_no_blocking_authority(tmp_path):
    # 旧 artifact：blocking_rework=false、无 provenance、COMPLETE
    # → provenance=narrative（不是 structured no-blocking authority）；决策值仍
    # backward compatible：干净 narrative → 非阻断
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE')
    available, blocking, status, prov = read_structured_blocking('workbuddy', out)
    assert available is True and blocking is False and status == 'COMPLETE'
    assert prov == BLOCKING_PROVENANCE_NARRATIVE
    # 无 structured authority → fail-safe：narrative 显式 FAIL 仍阻断
    assert agent_result_blocked('workbuddy', '**Result: FAIL**\nB1 broken', out) is True
    # 干净 narrative → 非阻断（backward compat）
    assert agent_result_blocked('workbuddy', '**Result: PASS**\nverified', out) is False
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified'}, out,
    ) == 'SUCCESS'


# ============ C: explicit provenance=structured + valid bool（Req 9-C） ============

def test_c_explicit_structured_authoritative_blocking_direction(tmp_path):
    # structured 权威 blocking：narrative APPROVE 不得覆盖
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'codex', blocking=True, verdict='REQUEST_CHANGE',
                      status='COMPLETE', provenance='structured')
    assert agent_result_blocked('codex', '最终判定：APPROVE\nBlocking Issues: NONE', out) is True
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'ok', 'workbuddy': 'PASS', 'codex': 'APPROVE'}, out,
    ) == 'WAITING'


def test_c_explicit_structured_authoritative_non_blocking_direction(tmp_path):
    # structured 权威 non-blocking：narrative FAIL 不得覆盖
    # （explicit structured non-blocking > legacy narrative fallback）
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    assert agent_result_blocked('workbuddy', '**Result: FAIL**\nB1 broken', out) is False
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: FAIL**\nB1 broken'}, out,
    ) == 'SUCCESS'


# ============ D: invalid provenance → fail safe（Req 9-D） ============

def test_d_invalid_provenance_read_path_fail_closed(tmp_path):
    # JSON 声明非法 provenance 值（banana）→ invalid structured data → fail closed
    out = tmp_path / "out"
    out.mkdir()
    (out / "workbuddy_result.json").write_text(json.dumps({
        "blocking_rework": False, "structured_summary_status": "COMPLETE",
        "blocking_provenance": "banana"}), encoding="utf-8")
    available, blocking, status, prov = read_structured_blocking('workbuddy', out)
    assert available is False and status == 'INVALID'
    assert agent_result_blocked('workbuddy', '**Result: PASS**\nverified', out) is True
    assert runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': '**Result: PASS**\nverified'}, out,
    ) == 'WAITING'


def test_d_invalid_provenance_writer_path_fail_closed(tmp_path):
    # build_stage_result：结构化块声明非法 provenance 值 → invalid structured result
    # → fail closed（blocking_rework=True / provenance=framework / MALFORMED）
    stage = build_stage_result(
        agent='workbuddy', result_text='**Result: PASS**\nverified', output_dir=tmp_path,
        structured={'verdict': 'PASS', 'blocking_rework': False,
                    'blocking_provenance': 'auto', 'findings': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['blocking_rework'] is True
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_FRAMEWORK
    assert stage['structured_summary_status'] == 'MALFORMED'
    assert stage['summary_complete'] is False


def test_d_invalid_provenance_wrong_type_fail_closed(tmp_path):
    # 类型非法同样 fail closed（schema 不拦截，build_stage_result 统一判定）
    stage = build_stage_result(
        agent='codex', result_text='APPROVE', output_dir=tmp_path,
        structured={'verdict': 'APPROVE', 'blocking_rework': False,
                    'blocking_provenance': 123, 'findings': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['blocking_rework'] is True
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_FRAMEWORK
    assert stage['structured_summary_status'] == 'MALFORMED'


def test_d_invalid_provenance_full_pipeline_fail_closed(tmp_path, monkeypatch):
    # 真实 runner 路径：workbuddy 结构化块声明 blocking_provenance="banana"
    # + blocking_rework=false → runner 写 fail-closed JSON → 聚合 WAITING
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return ('implemented ok\nAAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"status": "SUCCESS", "changed_files": [], "warnings": []}\n'
                    'AAF_STRUCTURED_RESULT_END')
        return ('**Result: PASS**\nverified\nAAF_STRUCTURED_RESULT_BEGIN\n'
                '{"verdict": "PASS", "blocking_rework": false, '
                '"blocking_provenance": "banana", "findings": [], "warnings": []}\n'
                'AAF_STRUCTURED_RESULT_END')

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nWAITING' in report
    stage = json.loads((out / 'workbuddy_result.json').read_text(encoding='utf-8'))
    assert stage['blocking_rework'] is True
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_FRAMEWORK
    assert stage['structured_summary_status'] == 'MALFORMED'


# ============ E: Hermes SUCCESS narrative 技术性 FAILED → non-blocking（Req 9-E） ============

def test_e_hermes_technical_failed_token_non_blocking():
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'implemented ok. The previously FAILED test now passes; fixed the error.',
         'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵',
         'codex': '最终判定：APPROVE\nBlocking Issues: NONE'},
    )
    assert status == 'SUCCESS'


# ============ F: FRAMEWORK_ERROR + no-blocking structured claim → blocking（Req 9-F） ============

def test_f_framework_error_with_no_blocking_structured_claim_fail_closed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': 'FRAMEWORK_ERROR\nRuntimeError: boom'}, out,
    )
    assert status == 'WAITING'


# ============ G: empty required result → blocking（Req 9-G） ============

def test_g_empty_required_result_fail_closed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy'],
        {'hermes': 'ok', 'workbuddy': ''}, out,
    )
    assert status == 'WAITING'
    assert runner_mod._aggregate_status(['hermes'], {'hermes': '   '}) == 'WAITING'


# ============ H: PASS_WITH_WARNING + no blocking + Codex APPROVE → SUCCESS（Req 9-H） ============

def test_h_pass_with_warning_approve_no_blocking_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    # hermes 无 blocking 字段（narrative 派生）；reviewer 显式 structured provenance
    _write_stage_json(out, 'hermes', blocking=False, status='COMPLETE')
    _write_stage_json(out, 'workbuddy', blocking=False, status='COMPLETE', provenance='structured')
    _write_stage_json(out, 'codex', blocking=False, status='COMPLETE', provenance='structured')
    status = runner_mod._aggregate_status(
        ['hermes', 'workbuddy', 'codex'],
        {'hermes': 'implemented ok',
         'workbuddy': '**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n历史 FAILED 项已解决',
         'codex': '最终判定：APPROVE\nBlocking Issues: NONE'},
        out,
    )
    assert status == 'SUCCESS'


# ============ Explicit-field authority 单元（Req 3/5） ============

def test_build_stage_result_explicit_structured_provenance_authority(tmp_path):
    # 显式声明 provenance=structured → structured authority（blocking 与非 blocking）
    stage = build_stage_result(
        agent='workbuddy', result_text='**Result: PASS**\nverified', output_dir=tmp_path,
        structured={'verdict': 'PASS', 'blocking_rework': False,
                    'blocking_provenance': 'structured', 'findings': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['blocking_rework'] is False
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_STRUCTURED
    assert stage['structured_summary_status'] == 'COMPLETE'
    # 聚合端：structured authority 生效
    out = tmp_path / 'out'
    out.mkdir()
    write_stage_result(out, stage)
    assert agent_result_blocked('workbuddy', '**Result: FAIL**\nB1 broken', out) is False


def test_build_stage_result_declared_narrative_provenance(tmp_path):
    # agent 显式声明 provenance=narrative → 按声明（blocking 决策值仍被采用，
    # 但下游不会当 structured authority）
    stage = build_stage_result(
        agent='workbuddy', result_text='**Result: PASS**\nverified', output_dir=tmp_path,
        structured={'verdict': 'PASS', 'blocking_rework': False,
                    'blocking_provenance': 'narrative', 'findings': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['blocking_rework'] is False
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE
    assert stage['structured_summary_status'] == 'COMPLETE'


def test_build_stage_result_declared_framework_provenance(tmp_path):
    stage = build_stage_result(
        agent='codex', result_text='APPROVE', output_dir=tmp_path,
        structured={'verdict': 'APPROVE', 'blocking_rework': False,
                    'blocking_provenance': 'framework', 'findings': [], 'warnings': []},
        structured_status='OK',
    )
    assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_FRAMEWORK
    assert stage['blocking_rework'] is False


def test_schema_passes_explicit_provenance_through():
    # schema 接受 blocking_provenance 字段（含非法值）——合法性由 build_stage_result
    # 统一判定（fail closed），不在 schema 层静默降级为 narrative
    data, status = extract_and_validate_structured(
        'workbuddy',
        '**Result: PASS_WITH_WARNING**\nW1: x\n\nAAF_STRUCTURED_RESULT_BEGIN\n'
        '{"verdict": "PASS_WITH_WARNING", "blocking_rework": false, '
        '"blocking_provenance": "structured", "findings": [], "warnings": ["W1: x"]}\n'
        'AAF_STRUCTURED_RESULT_END',
    )
    assert status == 'OK'
    assert data['blocking_provenance'] == 'structured'
    data2, status2 = extract_and_validate_structured(
        'codex',
        'APPROVE\n\nAAF_STRUCTURED_RESULT_BEGIN\n'
        '{"verdict": "APPROVE", "blocking_rework": false, '
        '"blocking_provenance": "banana", "findings": [], "warnings": []}\n'
        'AAF_STRUCTURED_RESULT_END',
    )
    assert status2 == 'OK'
    assert data2['blocking_provenance'] == 'banana'


def test_full_runner_legacy_block_without_provenance_not_laundered(tmp_path, monkeypatch):
    # 端到端：reviewer 结构化块有 blocking_rework 但**无** blocking_provenance
    # （legacy 形状）→ 决策保持 SUCCESS（backward compat），但 stage JSON
    # provenance=narrative——blocking_rework key 存在性不得被 laundering 成 structured
    def fake_run_agent(agent, prompt, workspace):
        if agent == 'hermes':
            return ('implemented ok\nAAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"status": "SUCCESS", "changed_files": [], "warnings": []}\n'
                    'AAF_STRUCTURED_RESULT_END')
        if agent == 'workbuddy':
            return ('**Result: PASS_WITH_WARNING**\nW1: 文档瑕疵\n'
                    'AAF_STRUCTURED_RESULT_BEGIN\n'
                    '{"verdict": "PASS_WITH_WARNING", "blocking_rework": false, '
                    '"findings": [], "warnings": ["W1: 文档瑕疵"]}\n'
                    'AAF_STRUCTURED_RESULT_END')
        return ('最终判定：APPROVE\nBlocking Issues: NONE\n'
                'AAF_STRUCTURED_RESULT_BEGIN\n'
                '{"verdict": "APPROVE", "blocking_rework": false, '
                '"findings": [], "warnings": []}\n'
                'AAF_STRUCTURED_RESULT_END')

    monkeypatch.setattr(runner_mod, 'run_agent', fake_run_agent)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(MINIMAL_EXPLICIT_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    assert '## Current Status\nSUCCESS' in report_path.read_text(encoding='utf-8')
    for agent in ('workbuddy', 'codex'):
        stage = json.loads((out / f'{agent}_result.json').read_text(encoding='utf-8'))
        assert stage['blocking_provenance'] == BLOCKING_PROVENANCE_NARRATIVE


# ============ Req 8：git_changed_files 不被常驻 untracked 项污染 ============

def test_git_changed_files_excludes_pre_allowed_untracked(tmp_path):
    import subprocess as sp
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "t@t"],
                ["git", "config", "user.name", "t"]):
        sp.run(cmd, cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "tracked.txt").write_text("v1", encoding="utf-8")
    sp.run(["git", "add", "tracked.txt"], cwd=str(tmp_path), check=True, capture_output=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "tracked.txt").write_text("v2", encoding="utf-8")
    for rel in (".aaf/", "AAF_TASK004_PROCESS_CHECK.txt",
                "scripts/start_bridge_hidden.vbs", "scratch.txt"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    files = git_changed_files(tmp_path)
    # tracked 修改保留
    assert "M tracked.txt" in files
    # FIX-002（v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001-FIX-002）：任意普通
    # untracked（含非预允许的 scratch.txt）一律不是 tracked change，必须排除——
    # 排除是通用 tracked/untracked 判定，不再保留非预允许 untracked。
    assert not any("??" in f for f in files)
    assert not any("scratch" in f for f in files)
    # 常驻预允许 untracked 项（含 scripts/ 目录折叠）被过滤
    assert not any(".aaf" in f or "PROCESS_CHECK" in f or "start_bridge_hidden" in f or "scripts" in f for f in files)
