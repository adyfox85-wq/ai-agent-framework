from ai_agent_framework.router import decide_route


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

REAL_TASK_005_FIX_001 = r'C:/Users/Admin/Downloads/TASK-005-FIX-001-profile-detail-implementation.md'


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


REAL_TASK_008_FIX_001 = r'C:/Users/Admin/Downloads/TASK-008-FIX-001-report-detail-hooks.md'


def test_real_task_008_fix_001_routes_hermes_workbuddy_codex():
    import pytest
    from pathlib import Path
    p = Path(REAL_TASK_008_FIX_001)
    if not p.exists():
        pytest.skip('real TASK-008-FIX-001 file not present')
    task = p.read_text(encoding='utf-8')
    route = decide_route(task)
    assert route.agents == ['hermes', 'workbuddy', 'codex']
