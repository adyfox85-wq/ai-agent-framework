"""AI Agent Framework — Canonical Verdict Parsing（RW-022 FIX-006）。

FIX-006（line-level verdict authority）：verdict authority 严格收敛为**独立、
明确、line-level 的 overall verdict / result / conclusion 声明行**。正文句子
中间出现的 verdict-like token / label 只是内容，不是结论。

CLOSURE-004 真实 incident（本 fix 的直接依据）：WorkBuddy narrative 首行
``## VALIDATOR VERDICT: **PASS_WITH_WARNING**`` 是唯一真实结论，blocking
rework=NO；但正文第 3 节示例枚举中包含 ``最终判定：**REQUEST_CHANGE**`` 与
``Overall result: SUCCESS.`` 等 inline example——旧的行内整体标签正则（FIX-005
遗留）在句中匹配它们为 canonical，随后 blocking-match precedence 误选
REQUEST_CHANGE，fresh workbuddy_result.json 错误记录 verdict=REQUEST_CHANGE。

本模块只做确定性本地正则解析（无 LLM / 无网络）。

--- 权威形态（Requirement 1：全部 line-level，label 必须构成该逻辑行的
conclusion 声明，而不是正文句子中的一部分）---
- 行首标签：``VERDICT: FAIL`` / ``Verdict: PASS`` / ``Result: FAILED`` /
  ``Result: SUCCESS`` / ``结论：REQUEST_CHANGE`` / ``审查结论：APPROVE`` /
  ``VALIDATOR VERDICT: PASS_WITH_WARNING`` / ``Codex Verdict: REQUEST_CHANGE`` /
  ``总体结果：SUCCESS`` / ``最终判定：APPROVE``（CJK 修饰前缀 + 结论词）
- Markdown 包裹：``## VERDICT: **FAIL**`` / ``# Result: **SUCCESS**`` /
  ``**Verdict: PASS**``
- 整行整体标签（label 位于逻辑行首）：``Overall result: SUCCESS.`` /
  ``Final verdict: APPROVE`` —— 句中形态（``…verified. Overall result: SUCCESS.``）
  不再权威（FIX-006 移除行内正则；overall/final/conclusion 形式并入行首标签）
- 裸 token 整行（整行只含一个结论词，可带冒号描述）：``PASS`` / ``APPROVE`` /
  ``REQUEST_CHANGE: fix router`` / ``FAILED: x``

--- 无权威（Requirement 2–5）---
- 正文句子中的任何 verdict-like token / label（``…Overall result: SUCCESS.``
  在句中、``expected result is SUCCESS``、``previous verdict: PASS`` 等）
- inline code（`` `REQUEST_CHANGE` `` / `` `Verdict: PASS` ``）与 code fence
  内容（`` ``` Verdict: FAIL ``` ``）——匹配前整体剥离
- JSON example（``{"verdict": "PASS"}`` / ``"result": "SUCCESS"``）
- blockquote 引用行（``> Verdict: PASS``——历史 reviewer output 不是当前结论；
  行首前缀字符集不含 ``>``）
- 普通 section heading（``## PASS evidence`` / ``## REQUEST_CHANGE example`` /
  ``## SUCCESS path`` / ``## FAILED test cases``——token 后跟非冒号文本，
  不是 verdict 行）

--- 语义 ---
- blocking token（FAIL / FAILED / REQUEST_CHANGE）优先：narrative 同时含
  通过行与失败行（自相矛盾）时，失败行是 authority（fail-safe 方向）——
  两条都是显式 conclusion 行（Requirement 7 允许 blocking conclusion 优先）。
- 无独立 conclusion 行 → None：不得从 prose / example / inline token 猜
  verdict（Requirement 8：required agent 场景不得 fail-open SUCCESS）。
- 结构化块（AAF_STRUCTURED_RESULT_BEGIN..END）中的 JSON 结论词不是 narrative
  证据（FIX-003）——调用方（context_packet._strip_structured_tail /
  report._strip_structured_block）必须先行剥离，本模块不处理。
- context_packet.py / report.py 复用本模块的唯一 parsing semantic
  （Requirement 9：consistency guard、legacy fallback、aggregation 共用，
  避免两个模块各自维护不同 regex 再次漂移）。
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

# ---------- 代码跨度剥离（Requirement 3：code / inline code 无 authority） ----------
# fence 块（``` ... ```，可含语言标记与多行）整体替换为占位符 'x'——块内任何
# verdict-like 行（含 "Verdict: FAIL"）都无权威；inline code span（`...`，单行）
# 同样替换为 'x'。占位符不在行首前缀字符集（# * - 空白）内，被替换的行不会
# 意外变成结论行；fence 不闭合（markdown 损坏）→ 剩余文本被吞 → ambiguous
# → fail-safe（不 fail-open），方向安全。
_FENCE_RE = re.compile(r"(?ms)^[ \t]*```.*?^[ \t]*```")
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")


def _strip_code_spans(text: str) -> str:
    """匹配前剥离 code fence 与 inline code（内容无 verdict authority）。"""
    text = _FENCE_RE.sub("x", text)
    return _CODE_SPAN_RE.sub("x", text)


# 行首标签（markdown 前缀可选：# / * / - / 空白；blockquote `>` 是引用行——
# 历史 reviewer output 不是当前结论，必须排除，前缀字符集不含 `>`）：
# - 英文复合标签：VALIDATOR / CODEX / FINAL / OVERALL + VERDICT / RESULT /
#   CONCLUSION（FIX-006：overall/final 整行整体标签并入此处，必须位于行首；
#   句中 "…Overall result: SUCCESS." 不再匹配）
# - 英文基础标签：VERDICT / RESULT / STATUS
# - 中文标签：结论 / 审查结论 / 最终判定 / 独立审查结论 / 验收结果 / 总体结果 等
#   （(?:[一-龥]{1,8})? 允许有限修饰前缀，如 审查/最终/独立审查/验收/总体；
#   token 必须是紧跟冒号的全大写官方词）
_LINE_LABEL_RE = re.compile(
    r"(?im)^[ \t#*\-]*[ \t]*"
    r"(?:\*{1,2}[ \t]*)?"
    r"(?:"
    r"(?:VALIDATOR|CODEX|FINAL|OVERALL)[ \t]+(?:VERDICT|RESULT|CONCLUSION)"
    r"|VERDICT|RESULT|STATUS"
    r"|(?:[一-龥]{1,8})?(?:结论|判定|结果|状态)"
    r")"
    r"[ \t]*[:：][ \t]*"
    r"(?:\*{1,2}[ \t]*)?"
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
    kind: str   # 'line'（行首标签 / 整行整体标签）| 'bare'（裸 token 行）


def _all_canonical_matches(text: str) -> list[CanonicalVerdict]:
    """收集全部 canonical verdict 行匹配，按出现位置排序。

    匹配前先剥离 code fence / inline code（Requirement 3：code 内容无权威）。
    只有独立 conclusion 行（行首标签 / 整行整体标签 / 裸 token 行）拥有
    authority；正文句子中的 verdict-like token / label 不是结论（FIX-006）。
    """
    text = _strip_code_spans(text)
    found: list[tuple[int, CanonicalVerdict]] = []
    for m in _LINE_LABEL_RE.finditer(text):
        found.append((m.start(), CanonicalVerdict(token=m.group(1), kind="line")))
    for m in _BARE_LINE_RE.finditer(text):
        found.append((m.start(), CanonicalVerdict(token=m.group(1), kind="bare")))
    found.sort(key=lambda item: item[0])
    return [v for _, v in found]


def parse_canonical_verdict(text: str | None) -> CanonicalVerdict | None:
    """从 narrative 提取 canonical overall verdict；无独立 conclusion 行 → None。

    blocking token（FAIL / FAILED / REQUEST_CHANGE）优先：narrative 同时含通过行
    与失败行（自相矛盾）时，失败行是 authority（fail-safe 方向——不得取通过方
    而 fail-open；两条都是显式 conclusion 行，Requirement 7 允许 blocking 优先）。
    调用方必须先剥离结构化块。
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

    True / False = 存在明确 canonical verdict 行（legacy narrative authority）；
    None = ambiguous legacy narrative（无独立 conclusion 行，Requirement 8）——
    调用方不得凭正文任意 token 猜结论，必须按 fail-safe policy 处理
    （required agent 不得 fail-open）。
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
