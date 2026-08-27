from dataclasses import dataclass, field
from enum import Enum
import re

from .task_validation import count_field_occurrences, parse_task_fields


@dataclass(frozen=True)
class Route:
    agents: list[str]
    reason: str


class RouteStatus(Enum):
    """显式 Route 字段三态（FIX-004 Req 9）。

    不得用 None 同时表示“没写 Route”和“写了但非法”：
    - ABSENT：TASK 完全没有 Route 字段 → legacy keyword heuristic 唯一允许路径
    - VALID：可解析且全部 agent 合法、无重复 → authoritative（覆盖 heuristic）
    - INVALID：非法 agent / malformed syntax / empty route / duplicate structure
      → 必须 Task Validation FAIL（fail-closed），不得回退 heuristic
    """

    ABSENT = "ABSENT"
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True)
class RouteParseResult:
    status: RouteStatus
    agents: list[str] = field(default_factory=list)
    error: str | None = None


# 合法 route agent（Explicit Route Authority，FIX-003 Req 1/2）
ALLOWED_ROUTE_AGENTS = ("hermes", "workbuddy", "codex")

# canonical machine Route 字段的分隔符：-> / → / > / , / 空白（容错 parse）
_ROUTE_SPLIT_RE = re.compile(r"\s*(?:->|→|>|,)\s*|\s+")

ROUTE_REASON_EXPLICIT = "explicit route (machine field)"


def parse_explicit_route(task_text: str) -> RouteParseResult:
    """三态解析 TASK 的 canonical machine Route 字段（FIX-003 Req 1/2 + FIX-004 Req 7–9 + FIX-005 Req 6/7）。

    ``Route: hermes -> workbuddy -> codex`` 是结构化机器字段（非人类说明文字）。
    返回 ``RouteParseResult(status, agents, error)``：
    - ABSENT：无 Route 字段 → 调用方（Runner/decide_route）走 legacy heuristic
    - VALID：有序 agent 列表（authoritative，覆盖 heuristic）
    - INVALID：fail-closed——非法 agent / malformed syntax（空段/悬挂分隔符）/
      empty route / duplicate agent 结构一律 INVALID，必须 Task Validation FAIL，
      绝不静默回退 heuristic。

    FIX-005 Req 6/7：Route 字段必须**唯一**。出现次数 >1（无论值相同 / 不同 /
    一个合法一个非法）→ 一律 INVALID（fail-closed）；唯一性在正式 parser 层
    验证，不得 first/last wins（count_field_occurrences 为通用 helper，可复用
    于其他 machine-authoritative control field）。

    Route Hint 仍是纯人类补充，不参与机器路由（parse 只认 ``Route:`` 字段）。
    """
    occurrences = count_field_occurrences(task_text or "", "Route")
    if occurrences == 0:
        return RouteParseResult(RouteStatus.ABSENT)
    if occurrences > 1:
        return RouteParseResult(
            RouteStatus.INVALID,
            error=(
                f"Route 字段重复声明（{occurrences} 个）——machine control "
                f"field 必须唯一（fail-closed，不得 first/last wins）"
            ),
        )
    field = (parse_task_fields(task_text).get("Route") or "").strip().lower()
    if not field:
        return RouteParseResult(RouteStatus.INVALID, error="Route 字段存在但为空")
    segments = _ROUTE_SPLIT_RE.split(field)
    if any(not s for s in segments):
        return RouteParseResult(
            RouteStatus.INVALID,
            error="Route 语法 malformed（空段 / 悬挂分隔符，如 'hermes ->'）",
        )
    unknown = [p for p in segments if p not in ALLOWED_ROUTE_AGENTS]
    if unknown:
        return RouteParseResult(
            RouteStatus.INVALID, error=f"未知 route agent: {unknown}"
        )
    if len(set(segments)) != len(segments):
        return RouteParseResult(
            RouteStatus.INVALID,
            error="Route 含重复 agent（unsupported route structure）",
        )
    return RouteParseResult(RouteStatus.VALID, list(segments))


EXECUTION_WORDS = (
    '修改', '创建', '删除', '安装', '配置', '执行', '运行', '实现', '开发', '生成文件', '批量', '重构',
    '修复', '恢复', '重建', '补充', '新增', '调整', '修正', '落地', '更新',
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
# 强只读信号：任务整体只读（只检查/只读/only review）→ 无执行意图时判纯复核。
# 注意：这些信号不得被局部 scope 约束（"不修改任何 Framework 功能代码"）命中。
# 含明确执行意图时，必须由 GLOBAL_READONLY_SIGNALS（真正的文件/仓库级全局只读）才能压过执行。
STRONG_READONLY_SIGNALS = (
    '只检查', '只读', 'read-only', 'only review',
)
# 真正全局只读表达（文件/仓库级"不修改任何..."、整体只读）：
# 这些可以压过执行意图（如 "review without modifying any file" 中 modify 是执行词但整体只读）。
GLOBAL_READONLY_SIGNALS = (
    '不修改任何文件', '不修改任何仓库', '不修改仓库任何', '不修改任何东西', '不修改任何内容',
    '不进行任何修改', '不要修改任何文件',
    '整个任务只读', '整个任务仅只读', '整体只读', '只读审计',
    # 英文同样只用文件/仓库级完整表达（裸 without modifying any 会命中局部约束
    # 如 "without modifying any framework code"）
    'without modifying any file', 'without modifying any files',
    'without modifying any repository', 'without modifying any project',
    'without modifying anything', 'no changes to any files',
    'no modification at all',
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
    # Explicit Route Authority（FIX-003 Req 1/2 + FIX-004 Req 7–9）：
    # TASK 声明 canonical Route 字段 → 以此为准，不靠全文关键词猜测。
    # - VALID → authoritative（覆盖 heuristic）
    # - INVALID → fail-closed：不得静默回退 heuristic（formal validation 已先行
    #   拒绝；此处是纯函数层的不变量防御，直接抛错）
    # - ABSENT → 唯一允许 legacy keyword inference 的场景
    explicit = parse_explicit_route(task_text)
    if explicit.status is RouteStatus.VALID:
        return Route(list(explicit.agents), ROUTE_REASON_EXPLICIT)
    if explicit.status is RouteStatus.INVALID:
        raise ValueError(
            f"INVALID_ROUTE: 非法显式 Route（fail-closed，不回退 heuristic）——"
            f"{explicit.error or 'invalid route structure'}"
        )

    t = task_text.lower()

    execution_hit = _has_execution_word(t)
    strong_readonly_hit = any(s in t for s in STRONG_READONLY_SIGNALS)
    global_readonly_hit = any(s in t for s in GLOBAL_READONLY_SIGNALS)
    needs_codex = _has_any_word(t, CODE_RISK_WORDS) and (execution_hit or _has_any_word(t, REVIEW_WORDS))

    # 整体只读：明确全局只读表达（文件/仓库级，可压过执行词），或强只读信号且无执行意图
    # 局部约束（"不修改任何 Framework 功能代码"）不命中 STRONG → 不会压过执行意图
    if global_readonly_hit or (strong_readonly_hit and not execution_hit):
        agents = ['workbuddy']
        if needs_codex:
            agents.append('codex')
        return Route(agents, 'review/validation task (readonly)')

    # 实现类词优先：只要 TASK 主体要求实现/修改/修复/更新等，路由必须包含 Hermes；
    # 同时出现 review/validate/acceptance 或"不实现 X"禁止事项不否决实现。
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
