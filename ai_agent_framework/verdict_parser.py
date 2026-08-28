"""AI Agent Framework — Canonical Verdict Parsing（RW-022 FIX-005）。

legacy narrative verdict 只从**明确、可识别的 overall conclusion / verdict /
result 行**解析；正文任意位置的 PASS / PASS_WITH_WARNING / SUCCESS / FAIL /
FAILED / APPROVE / REQUEST_CHANGE token 只是内容，不是结论（RW-022 fail-open
根因——CLOSURE-003 中正文 ``## PASS 证据`` 曾覆盖首行 ``## VERDICT: **FAIL**``）。

context_packet.py / report.py 复用本模块的唯一 parsing semantic
（Requirement 13：consistency guard、legacy fallback、aggregation 共用，
避免两个模块各自维护不同 regex 再次漂移）。

可识别的 canonical verdict 形态（Requirement 1）：
- 行首标签：``VERDICT: FAIL`` / ``Verdict: PASS`` / ``Result: FAILED`` /
  ``Result: SUCCESS`` / ``结论：REQUEST_CHANGE`` / ``审查结论：APPROVE`` /
  ``VALIDATOR VERDICT: PASS_WITH_WARNING`` / ``Codex Verdict: REQUEST_CHANGE``
- Markdown 包裹：``## VERDICT: **FAIL**`` / ``# Result: **SUCCESS**``
- 行内整体标签：``Overall result: SUCCESS.`` / ``Final verdict: APPROVE``
- 裸 token 整行（整行只含一个结论词，可带冒号描述）：
  ``PASS`` / ``APPROVE`` / ``REQUEST_CHANGE: fix router`` / ``FAILED: x``

非权威（正文 token，不得改变 verdict，Requirement 2）：
- ``PASS 证据`` / ``SUCCESS path`` / ``previous result was PASS`` /
  ``test FAILED example`` / ``failure handling`` / ``REQUEST_CHANGE example``
- quoted 历史 reviewer output（``>`` 引用行）
- 含 token 的 section heading / code block / JSON example
- 无标签的句中 token（``All checks passed. SUCCESS.``）

结构化块（AAF_STRUCTURED_RESULT_BEGIN..END）中的 JSON 结论词不是 narrative
证据（FIX-003）——调用方（context_packet._strip_structured_tail /
report._strip_structured_block）必须先行剥离，本模块不处理。

本模块只做确定性本地正则解析（无 LLM / 无网络）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 官方结论词（全大写 token）。FRAMEWORK_ERROR 是 framework hard failure 标记，
# 不是 verdict token——由调用方（空结果 / 行首 FRAMEWORK_ERROR）单独判定。
VERDICT_TOKENS = (
    "PASS_WITH_WARNING",
    "PASS",
    "SUCCESS",
    "FAILED",
    "FAIL",
    "APPROVE",
    "REQUEST_CHANGE",
)
_TOKEN_RE = r"(?:PASS_WITH_WARNING|PASS|SUCCESS|FAILED|FAIL|APPROVE|REQUEST_CHANGE)"

# blocking token 集合（agent 无关）：canonical narrative 出现任一 → blocking。
BLOCKING_TOKENS = frozenset(("FAIL", "FAILED", "REQUEST_CHANGE"))
# 通过 token 集合：canonical narrative 出现任一 → non-blocking。
PASS_TOKENS = frozenset(("PASS", "PASS_WITH_WARNING", "SUCCESS", "APPROVE"))

# 行首标签（markdown 前缀可选：# / * / - / 空白；blockquote `>` 是引用行——
# 历史 reviewer output 不是当前结论，必须排除，前缀字符集不含 `>`）：
# - 英文复合标签：VALIDATOR / CODEX / FINAL / OVERALL + VERDICT / RESULT
# - 英文基础标签：VERDICT / RESULT / STATUS
# - 中文标签：结论 / 审查结论 / 最终判定 / 独立审查结论 / 验收结果 等
#   （(?:[一-龥]{1,8})? 允许有限修饰前缀，如 审查/最终/独立审查/验收；
#   token 必须是紧跟冒号的全大写官方词）
_LINE_LABEL_RE = re.compile(
    r"(?im)^[ \t#*\-]*[ \t]*"
    r"(?:\*{1,2}[ \t]*)?"
    r"(?:"
    r"(?:VALIDATOR|CODEX|FINAL|OVERALL)[ \t]+(?:VERDICT|RESULT)"
    r"|VERDICT|RESULT|STATUS"
    r"|(?:[一-龥]{1,8})?(?:结论|判定|结果|状态)"
    r")"
    r"[ \t]*[:：][ \t]*"
    r"(?:\*{1,2}[ \t]*)?"
    r"(" + _TOKEN_RE + r")\b"
)

# 行内整体标签（句内/句尾）："Overall result: SUCCESS." /
# "Final verdict: APPROVE" / "总体结果：SUCCESS"（明确的整体结论声明，
# 与任务列出的 canonical 形态一致；不是正文关键词情绪判断）
_INLINE_LABEL_RE = re.compile(
    r"(?i)(?:overall|final)[ \t]+(?:verdict|result|conclusion)"
    r"|(?:整体|总体|最终)[ \t]*(?:结果|结论|判定)"
)
_INLINE_RE = re.compile(
    r"(?i)(?:(?:overall|final)[ \t]+(?:verdict|result|conclusion)"
    r"|(?:整体|总体|最终)[ \t]*(?:结果|结论|判定))"
    r"[ \t]*[:：]?[ \t]*(?:\*{1,2}[ \t]*)?"
    r"(" + _TOKEN_RE + r")\b"
)

# 裸 token 整行：整行只含一个结论词（+ 可选冒号描述）。token 后跟非冒号文本
# （"PASS evidence" / "SUCCESS path"）不是 verdict 行——正文 token 无权威。
# blockquote `>` 引用行不在前缀字符集内（历史 reviewer output 不是当前结论）。
_BARE_LINE_RE = re.compile(
    r"(?im)^[ \t#*\-]*[ \t]*(?:\*{1,2}[ \t]*)?(" + _TOKEN_RE + r")\b"
    r"[ \t]*(?:\*{1,2})?[ \t]*(?:[:：][ \t]*.*)?$"
)


@dataclass(frozen=True)
class CanonicalVerdict:
    """一次 canonical verdict 行解析结果。"""

    token: str  # 官方结论词（全大写）
    kind: str   # 'line'（行首标签）| 'inline'（行内整体标签）| 'bare'（裸 token 行）


def _all_canonical_matches(text: str) -> list[CanonicalVerdict]:
    """收集全部 canonical verdict 匹配，按出现位置排序。"""
    found: list[tuple[int, CanonicalVerdict]] = []
    for m in _LINE_LABEL_RE.finditer(text):
        found.append((m.start(), CanonicalVerdict(token=m.group(1), kind="line")))
    for m in _INLINE_RE.finditer(text):
        found.append((m.start(), CanonicalVerdict(token=m.group(1), kind="inline")))
    for m in _BARE_LINE_RE.finditer(text):
        found.append((m.start(), CanonicalVerdict(token=m.group(1), kind="bare")))
    found.sort(key=lambda item: item[0])
    return [v for _, v in found]


def parse_canonical_verdict(text: str | None) -> CanonicalVerdict | None:
    """从 narrative 提取 canonical overall verdict；无明确 conclusion 行 → None。

    blocking token（FAIL / FAILED / REQUEST_CHANGE）优先：narrative 同时含通过行
    与失败行（自相矛盾）时，失败行是 authority（fail-safe 方向——不得取通过方
    而 fail-open）。调用方必须先剥离结构化块。
    """
    if not text:
        return None
    matches = _all_canonical_matches(text)
    if not matches:
        return None
    blocking = [m for m in matches if m.token in BLOCKING_TOKENS]
    return (blocking or matches)[0]


def canonical_blocking(text: str | None) -> bool | None:
    """canonical narrative verdict 是否 blocking。

    True / False = 存在明确 canonical verdict 行（Requirement 3 的 legacy
    narrative authority）；None = ambiguous legacy narrative（无明确
    conclusion/verdict/result 行，Requirement 7）——调用方不得凭正文任意
    token 猜结论，必须按 fail-safe policy 处理（required agent 不得 fail-open）。
    """
    if not text:
        return None
    c = parse_canonical_verdict(text)
    if c is None:
        return None
    return c.token in BLOCKING_TOKENS


def normalize_verdict(agent: str, token: str | None) -> str | None:
    """canonical token → agent 官方 verdict 词。

    - workbuddy: PASS / PASS_WITH_WARNING / FAIL；FAILED 归一化为 FAIL（FIX-003）；
      SUCCESS / APPROVE 归一化为 PASS
    - codex: APPROVE / REQUEST_CHANGE；SUCCESS / PASS / PASS_WITH_WARNING
      归一化为 APPROVE；FAIL / FAILED 归一化为 REQUEST_CHANGE
    - hermes: 无 verdict 语义 → None
    """
    if not token:
        return None
    if agent == "hermes":
        return None
    if token in BLOCKING_TOKENS:
        if agent == "codex":
            return "REQUEST_CHANGE" if token in ("FAIL", "FAILED") else token
        return "FAIL" if token == "FAILED" else token
    # 通过 token：PASS / PASS_WITH_WARNING / SUCCESS / APPROVE
    if agent == "codex":
        return "APPROVE"
    if token == "PASS_WITH_WARNING":
        return "PASS_WITH_WARNING"
    return "PASS"
