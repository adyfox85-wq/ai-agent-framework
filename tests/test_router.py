from pathlib import Path

from ai_agent_framework.router import (
    decide_route,
    parse_explicit_route,
)


def test_execution_routes_hermes_then_workbuddy():
    route = decide_route('请修改前端代码并运行测试')
    assert route.agents[:2] == ['hermes', 'workbuddy']


def test_visual_review_skips_hermes():
    route = decide_route('请检查这张页面设计图的视觉效果和一致性')
    assert route.agents[0] == 'workbuddy'
    assert 'hermes' not in route.agents


def test_code_risk_adds_codex():
    route = decide_route('重构核心路由架构并修改 TypeScript 代码')
    assert route.agents == ['hermes', 'workbuddy', 'codex']


# --- Bug1 回归：实现类任务不得被误判跳过 Hermes ---

def test_frontend_feature_implementation_includes_hermes():
    route = decide_route('frontend feature implementation')
    assert 'hermes' in route.agents


def test_implementation_recovery_includes_hermes():
    route = decide_route('frontend implementation recovery / missing implementation fix')
    assert 'hermes' in route.agents


def test_english_fix_word_includes_hermes():
    route = decide_route('bugfix: fix the data contract correction')
    assert 'hermes' in route.agents


def test_review_words_do_not_override_implementation():
    # 同时出现 review/validate/acceptance 词，但要求实现 → 仍必须含 Hermes
    route = decide_route('实现关系页 feature，接受 review/validate/acceptance criteria 检查')
    assert 'hermes' in route.agents


def test_pure_visual_review_skips_hermes():
    route = decide_route('检查页面视觉层级，不修改任何文件')
    assert route.agents[0] == 'workbuddy'
    assert 'hermes' not in route.agents


def test_readonly_review_with_modify_word_skips_hermes():
    # "不修改" 含 "修改" 字样，但只读信号优先 → 纯复核
    route = decide_route('review the page design, without modifying any file')
    assert 'hermes' not in route.agents
    assert route.agents[0] == 'workbuddy'


# --- 真实 TASK-005-FIX-001 回归（完整真实内容，禁止事项含"不实现 X"不得否决执行） ---

REAL_TASK_005_FIX_001 = str(Path(__file__).resolve().parent / 'fixtures' / 'TASK-005-FIX-001.md')


def _load_real_task() -> str:
    import pytest
    from pathlib import Path
    p = Path(REAL_TASK_005_FIX_001)
    if not p.exists():
        pytest.skip('real TASK-005-FIX-001 file not present')
    return p.read_text(encoding='utf-8')


def test_real_task_005_fix_001_routes_hermes_workbuddy_codex():
    task = _load_real_task()
    route = decide_route(task)
    assert route.agents == ['hermes', 'workbuddy', 'codex']


def test_weak_readonly_does_not_override_implementation():
    # "不实现真实排盘算法" 是禁止事项（weak readonly），任务主体是"实现页面" → 必须含 Hermes
    route = decide_route('实现我的命盘详情页面功能，但不实现真实排盘算法、不实现推演页新功能')
    assert 'hermes' in route.agents


def test_strong_readonly_still_skips_hermes():
    # 全局只读（不修改任何文件）仍是纯复核
    route = decide_route('检查我的命盘详情页视觉层级与一致性，不修改任何文件')
    assert 'hermes' not in route.agents
    assert route.agents[0] == 'workbuddy'


# --- TASK-008-FIX-001 回归：bugfix/correctness 必须含 Hermes，局部"不改变"约束不得判只读 ---

def test_frontend_bugfix_correctness_includes_hermes():
    route = decide_route('frontend bugfix / React Hooks correctness')
    assert 'hermes' in route.agents


def test_fix_conditional_hook_includes_hermes():
    route = decide_route('修复 ReportDetailPage 条件 Hook 调用')
    assert 'hermes' in route.agents


def test_minimal_fix_with_review_routes_hermes_workbuddy_codex():
    route = decide_route('最小修复 React Hooks 顺序问题，并由 WorkBuddy/Codex 复核')
    assert route.agents == ['hermes', 'workbuddy', 'codex']


def test_local_semantic_constraint_does_not_make_task_readonly():
    # "不改变收藏业务语义"是局部约束，任务主体是修复 → 必须含 Hermes
    route = decide_route('修复 Hook 调用，但不改变收藏业务语义')
    assert 'hermes' in route.agents


def test_pure_check_hooks_skips_hermes():
    route = decide_route('只检查 ReportDetailPage Hooks 是否正确，不修改任何文件')
    assert 'hermes' not in route.agents
    assert route.agents[0] == 'workbuddy'


REAL_TASK_008_FIX_001 = str(Path(__file__).resolve().parent / 'fixtures' / 'TASK-008-FIX-001.md')


def test_real_task_008_fix_001_routes_hermes_workbuddy_codex():
    import pytest
    from pathlib import Path
    p = Path(REAL_TASK_008_FIX_001)
    if not p.exists():
        pytest.skip('real TASK-008-FIX-001 file not present')
    task = p.read_text(encoding='utf-8')
    route = decide_route(task)
    assert route.agents == ['hermes', 'workbuddy', 'codex']


# --- Router hotfix：局部 readonly 约束不得压过明确执行意图（AAF-MAINT-001 回归） ---

def test_local_readonly_constraint_does_not_suppress_execution_case1():
    # Case 1: 创建文件 + 局部"不修改 Framework 功能代码" → 必须含 Hermes
    route = decide_route('创建 AAF_MASTER_BACKLOG.md，但不修改任何 Framework 功能代码')
    assert route.agents[0] == 'hermes'
    assert 'workbuddy' in route.agents


def test_local_readonly_constraint_does_not_suppress_execution_case2():
    # Case 2: 更新文档 + 局部"不修改 Router/Bridge 代码" → 必须含 Hermes
    route = decide_route('更新 PROJECT_STATE.md，不修改任何 Router/Bridge 代码')
    assert route.agents[0] == 'hermes'
    assert 'workbuddy' in route.agents


def test_true_global_readonly_skips_hermes_case3():
    # Case 3: 只读检查 + 全局"不修改任何文件" → 不含 Hermes
    route = decide_route('只读检查仓库，不修改任何文件')
    assert 'hermes' not in route.agents
    assert route.agents[0] == 'workbuddy'


def test_code_readonly_review_routes_workbuddy_codex_case4():
    # Case 4: 代码只读审查 + 全局"不修改任何文件" → workbuddy -> codex
    route = decide_route('对代码做只读审查，不修改任何文件')
    assert route.agents == ['workbuddy', 'codex']


def test_normal_execution_task_unchanged_case5():
    # Case 5: 普通执行任务 → 现有行为不退化
    route = decide_route('实现登录页面功能')
    assert route.agents == ['hermes', 'workbuddy']


def test_normal_review_task_unchanged_case6():
    # Case 6: 普通 review 任务 → 现有行为不退化
    route = decide_route('复核 Hermes 生成的结果报告')
    assert route.agents[0] == 'workbuddy'
    assert 'hermes' not in route.agents


def test_english_local_readonly_constraint_does_not_suppress_execution_case7():
    # Case 7: 英文局部约束（without modifying any framework code）→ 必须含 Hermes
    route = decide_route('create docs without modifying any framework code')
    assert route.agents[0] == 'hermes'
    assert 'workbuddy' in route.agents


def test_english_global_readonly_still_skips_hermes_case8():
    # Case 8: 英文文件级全局只读 → 不含 Hermes
    route = decide_route('review the page design, without modifying any file')
    assert 'hermes' not in route.agents
    assert route.agents[0] == 'workbuddy'


# --- FIX-003：Explicit Route Authority（Req 1/2/4/11/12） ---

def test_explicit_route_field_parsed_3_agents():
    """canonical machine Route 字段被正式 parse（非人类说明文字）。"""
    task = '完成资料汇总。\nRoute: hermes -> workbuddy -> codex\n'
    assert parse_explicit_route(task) == ['hermes', 'workbuddy', 'codex']
    route = decide_route(task)
    assert route.agents == ['hermes', 'workbuddy', 'codex']
    assert route.reason == 'explicit route (machine field)'


def test_explicit_route_parsing_variants():
    """分隔符容错：-> / → / , / 空白 / 大小写；去重保序。"""
    assert parse_explicit_route('Route: hermes -> workbuddy -> codex') == ['hermes', 'workbuddy', 'codex']
    assert parse_explicit_route('Route: hermes→workbuddy→codex') == ['hermes', 'workbuddy', 'codex']
    assert parse_explicit_route('Route: hermes, workbuddy, codex') == ['hermes', 'workbuddy', 'codex']
    assert parse_explicit_route('Route: HERMES -> WORKBUDDY') == ['hermes', 'workbuddy']
    assert parse_explicit_route('Route: hermes -> hermes') == ['hermes']  # 去重
    # 未声明 / 空 → None（legacy inference）
    assert parse_explicit_route('没有 Route 字段的任务') is None
    assert parse_explicit_route('Route:') is None
    # Route Hint 不参与机器路由（parse 只认 Route: 字段）
    assert parse_explicit_route('Route Hint: Hermes → WorkBuddy → Codex') is None
    # 未知 agent → None（不采信，不虚构）
    assert parse_explicit_route('Route: hermes -> alien') is None


def test_explicit_route_overrides_heuristic():
    """heuristic 判 review-only（workbuddy 起步），显式 Route 声明全链 → 以声明为准。"""
    task = '只检查页面设计，不修改任何文件。\nRoute: hermes -> workbuddy -> codex\n'
    route = decide_route(task)
    assert route.agents == ['hermes', 'workbuddy', 'codex']


def test_explicit_route_can_narrow_to_workbuddy_only():
    """heuristic 判执行+代码风险（hermes/workbuddy/codex），显式 Route 收窄 → 以声明为准。"""
    task = '实现并修改核心功能代码。\nRoute: workbuddy\n'
    route = decide_route(task)
    assert route.agents == ['workbuddy']


def test_explicit_route_unknown_agent_falls_back_to_heuristic():
    """声明含未知 agent → 不采信，回退 heuristic（不崩溃、不虚构 agent）。"""
    task = '实现核心功能代码。\nRoute: hermes -> alien\n'
    route = decide_route(task)
    assert route.agents == ['hermes', 'workbuddy', 'codex']


def test_compact_text_without_code_risk_words_still_runs_codex():
    """Anti-Bloat 回归（Req 11）：正文完全不含 代码/安全/架构/code/architecture，
    仅凭显式 Route 字段仍路由 hermes -> workbuddy -> codex。"""
    body = '任务要求：完成资料汇总、结果核验并输出清单。'
    assert not any(w in body for w in ('代码', '安全', '架构', 'code', 'architecture'))
    task_with_route = body + '\nRoute: hermes -> workbuddy -> codex\n'
    route = decide_route(task_with_route)
    assert route.agents == ['hermes', 'workbuddy', 'codex']
    # 对照：去掉 Route 字段 → heuristic 不含 codex（证明不是靠关键词膨胀触发）
    route_legacy = decide_route(body)
    assert 'codex' not in route_legacy.agents


def test_legacy_route_inference_unchanged_without_route_field():
    """旧 TASK 无 Route 字段 → keyword heuristic 行为不变（Req 12）。"""
    route = decide_route('修改前端代码并运行测试')
    assert route.agents == ['hermes', 'workbuddy', 'codex']
    route2 = decide_route('请检查这张页面设计图的视觉效果和一致性')
    assert route2.agents[0] == 'workbuddy'
    assert 'hermes' not in route2.agents
