from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Route:
    agents: list[str]
    reason: str


EXECUTION_WORDS = (
    '修改', '创建', '删除', '安装', '配置', '执行', '运行', '实现', '开发', '生成文件', '批量', '重构',
    '修复', '恢复', '重建', '补充', '新增', '调整', '修正', '落地',
)
# 英文实现类词：词边界匹配，避免子串误伤（如 prefix 含 fix）
EXECUTION_EN_WORDS = (
    'implement', 'implementation', 'fix', 'bugfix', 'bug fix', 'repair', 'restore', 'recovery',
    'recover', 'modify', 'modification', 'create', 'refactor', 'feature', 'build',
    'patch', 'correct', 'correctness',
)
VISUAL_REVIEW_WORDS = ('视觉', '设计图', '截图', '页面设计', 'UI', '排版', '审美')
REVIEW_WORDS = (
    '检查', '复核', '验收', '评价', '评估', '审查', '分析',
    'review', 'validate', 'validation', 'acceptance',
)
# 强只读信号：任务整体只读（不修改任何文件 / 只检查）→ 即使含"修改/实现"字样也判纯复核。
# 注意：必须是"全局只读"表述；"不改变业务语义""不修改数据结构"等局部约束不得命中
STRONG_READONLY_SIGNALS = (
    '不修改任何', '不要修改任何', '不进行任何修改',
    '只检查', '只读', 'read-only', 'without modifying',
    'no modification', 'only review',
)
# 弱只读信号：常见于禁止事项（如"不实现真实排盘"）——只否定特定范围，
# 不否定任务主体的执行意图；仅在任务整体无执行词时才用于兜底判定纯复核
WEAK_READONLY_SIGNALS = ('不实现', '不创建', '不修复', '不生成')
CODE_RISK_WORDS = (
    '代码', 'typescript', 'javascript', 'python', '架构', '重构', '核心', '路由',
    '数据库', '迁移', '权限', '安全',
    'code', 'architecture', 'refactor', 'backend', 'api',
    'correctness', 'correct', 'hook', 'hooks', 'react',
)


def _has_any_word(t: str, words: tuple[str, ...]) -> bool:
    """中文词子串匹配；ASCII 词词边界匹配（避免 requirements 含 'ui' 这类误伤）。"""
    for w in words:
        if w.isascii():
            if re.search(rf'\b{re.escape(w)}\b', t, re.IGNORECASE):
                return True
        elif w.lower() in t:
            return True
    return False


def _has_execution_word(t: str) -> bool:
    return _has_any_word(t, EXECUTION_WORDS) or _has_any_word(t, EXECUTION_EN_WORDS)


def _contains_visual_word(t: str) -> bool:
    """视觉词（短 ASCII 词如 UI 用词边界）。"""
    return _has_any_word(t, VISUAL_REVIEW_WORDS)


def decide_route(task_text: str) -> Route:
    t = task_text.lower()

    # 强只读信号优先：任务整体"不修改/只检查" → 纯复核，跳过 Hermes
    if any(s in t for s in STRONG_READONLY_SIGNALS):
        needs_codex = _has_any_word(t, CODE_RISK_WORDS) and _has_any_word(t, REVIEW_WORDS)
        agents = ['workbuddy']
        if needs_codex:
            agents.append('codex')
        return Route(agents, 'review/validation task (readonly)')

    # Bug1 修复：实现类词优先——只要 TASK 主体要求实现/修改/修复/恢复等，
    # 路由必须包含 Hermes；同时出现 review/validate/acceptance 或"不实现 X"禁止事项不否决实现。
    execution_hit = _has_execution_word(t)
    needs_codex = _has_any_word(t, CODE_RISK_WORDS) and (execution_hit or _has_any_word(t, REVIEW_WORDS))

    if execution_hit:
        agents = ['hermes', 'workbuddy']
        if needs_codex:
            agents.append('codex')
        return Route(agents, 'execution task')

    # 无执行意图：弱只读（仅禁止事项）或纯 review/视觉 → 允许跳过 Hermes
    weak_readonly = any(s in t for s in WEAK_READONLY_SIGNALS)
    review_hit = _has_any_word(t, REVIEW_WORDS) or _contains_visual_word(t)
    if weak_readonly or review_hit:
        agents = ['workbuddy']
        if needs_codex:
            agents.append('codex')
        return Route(agents, 'review/validation task')

    return Route(['workbuddy'], 'default validation/analysis route')
