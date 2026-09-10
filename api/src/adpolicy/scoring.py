"""판정 종합 — 점수와 verdict는 코드가 결정적으로 계산한다.

LLM에게 "몇 점이야?"를 묻지 않는다. 같은 findings면 항상 같은 점수가 나와야
사용자가 수정 전후를 비교할 수 있기 때문이다.
"""

from __future__ import annotations

from typing import Literal

from .models import Finding, Severity

WEIGHTS: dict[Severity, int] = {
    Severity.BLOCK: 35,
    Severity.WARN: 12,
    Severity.INFO: 3,
}

# 결정적 룰(RULE)과 모델 판단(LLM)의 가중치를 다르게 둔다.
SOURCE_FACTOR = {"rule": 1.0, "llm": 0.7}


def score(findings: list[Finding]) -> int:
    penalty = 0.0
    for f in findings:
        penalty += WEIGHTS[f.severity] * SOURCE_FACTOR.get(f.source.value, 1.0)
    return max(0, min(100, round(100 - penalty)))


def verdict(findings: list[Finding]) -> Literal["pass", "review", "fail"]:
    if any(f.severity == Severity.BLOCK for f in findings):
        return "fail"
    if any(f.severity == Severity.WARN for f in findings):
        return "review"
    return "pass"


def summarize(findings: list[Finding], v: str) -> str:
    if not findings:
        return (
            "확인된 정책 위반 항목이 없습니다. "
            "다만 이 도구는 사전 점검이며 심사 통과를 보장하지 않습니다."
        )

    blocks = [f for f in findings if f.severity == Severity.BLOCK]
    warns = [f for f in findings if f.severity == Severity.WARN]

    if v == "fail":
        head = f"게재 거부 위험이 큰 항목 {len(blocks)}건이 발견되었습니다."
        if blocks:
            head += f" 가장 시급한 것은 '{blocks[0].title}'입니다."
        return head
    if v == "review":
        return f"반려 가능성이 있는 항목 {len(warns)}건을 수정하는 편이 안전합니다."
    return "경미한 개선 항목만 발견되었습니다."


def sort_findings(findings: list[Finding]) -> list[Finding]:
    order = {Severity.BLOCK: 0, Severity.WARN: 1, Severity.INFO: 2}
    # 같은 심각도면 결정적 룰을 먼저 — 확실한 것부터 고치게 한다.
    return sorted(findings, key=lambda f: (order[f.severity], f.source.value != "rule"))


def merge(rule_findings: list[Finding], llm_findings: list[Finding]) -> list[Finding]:
    """같은 코드를 룰과 LLM이 모두 잡으면 룰 쪽을 남긴다 (재현성 우선)."""
    seen = {f.code for f in rule_findings}
    merged = list(rule_findings)
    merged += [f for f in llm_findings if f.code not in seen]
    return sort_findings(merged)
