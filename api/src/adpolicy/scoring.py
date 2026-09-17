"""판정 종합 — 점수와 verdict는 코드가 결정적으로 계산한다.

LLM에게 "몇 점이야?"를 묻지 않는다. 같은 findings면 항상 같은 점수가 나와야
사용자가 수정 전후를 비교할 수 있기 때문이다.
"""

from __future__ import annotations

from typing import Literal

from .models import AccountRisk, Enforcement, Finding, Severity

WEIGHTS: dict[Severity, int] = {
    Severity.BLOCK: 35,
    Severity.WARN: 12,
    Severity.INFO: 3,
}

# 결정적 룰(RULE)과 모델 판단(LLM)의 가중치를 다르게 둔다.
SOURCE_FACTOR = {"rule": 1.0, "ocr": 0.85, "llm": 0.7, "vlm": 0.5}


def score(findings: list[Finding]) -> int:
    penalty = 0.0
    for f in findings:
        penalty += WEIGHTS[f.severity] * SOURCE_FACTOR.get(f.source.value, 1.0)
    return max(0, min(100, round(100 - penalty)))


# ---------------------------------------------------------------------------
# 두 번째 축 — 계정 정지 위험
#
# 광고 하나가 반려되는 것과 계정이 영구 정지되는 것은 광고주에게 완전히 다른
# 사건이다. 반려 20건보다 정지 1건이 치명적인데, 한 점수로 합치면 그 사실이
# 묻힌다. 그래서 따로 센다.
# ---------------------------------------------------------------------------

ENFORCEMENT_RANK = {
    Enforcement.DISAPPROVE: 0,
    Enforcement.STRIKE: 1,
    Enforcement.SUSPEND: 2,
}


def account_risk(findings: list[Finding]) -> AccountRisk:
    """계정에 어떤 일이 생길 수 있는지. 점수가 아니라 등급으로 센다.

    정지는 '몇 점짜리 위험'이 아니라 '있다/없다'에 가깝다 — 중대한 위반은
    한 건이면 사전 경고 없이 즉시 영구 정지다. 숫자로 뭉개면 안 된다.
    """
    suspend = [f for f in findings if f.enforcement is Enforcement.SUSPEND]
    strike = [f for f in findings if f.enforcement is Enforcement.STRIKE]

    if suspend:
        level = Enforcement.SUSPEND
        note = (
            f"사전 경고 없이 계정이 즉시 정지될 수 있는 항목이 {len(suspend)}건입니다. "
            f"가장 먼저 '{suspend[0].title}'을 확인하세요. "
            "중대한 위반은 한 건으로도 영구 정지이며 재광고가 불가능합니다."
        )
    elif strike:
        level = Enforcement.STRIKE
        note = (
            f"경고가 누적되는 항목이 {len(strike)}건입니다. "
            "첫 위반은 주의로 끝나지만, 90일 안에 같은 정책을 다시 어기면 "
            "1차 경고(3일 일시정지) → 2차(7일) → 3차 정지로 올라갑니다."
        )
    else:
        level = Enforcement.DISAPPROVE
        note = (
            "계정 정지로 직결되는 항목은 발견되지 않았습니다. "
            "반려 항목도 누적되면 최소 7일 전 예고 후 정지될 수 있습니다."
        )

    return AccountRisk(
        level=level,
        suspend_count=len(suspend),
        strike_count=len(strike),
        codes=[f.code for f in suspend + strike],
        note=note,
    )


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


# 같은 심각도면 근거가 확실한 것부터 — 사용자가 위에서부터 고치면 되게.
SOURCE_ORDER = {"rule": 0, "ocr": 1, "llm": 2, "vlm": 3}


def sort_findings(findings: list[Finding]) -> list[Finding]:
    order = {Severity.BLOCK: 0, Severity.WARN: 1, Severity.INFO: 2}
    return sorted(
        findings,
        key=lambda f: (order[f.severity], SOURCE_ORDER.get(f.source.value, 9)),
    )


EVIDENCE_JOIN_LIMIT = 300


def _absorb(kept: Finding, other: Finding) -> None:
    """진 쪽이 들고 있던 것을 이긴 쪽으로 옮긴다. 버리지 않는다."""
    if not kept.image_url and other.image_url:
        kept.image_url = other.image_url
    for url in ([other.image_url] if other.image_url else []) + other.image_urls:
        if url and url not in kept.image_urls:
            kept.image_urls.append(url)
    if other.evidence and other.evidence not in kept.evidence:
        kept.evidence = f"{kept.evidence} / {other.evidence}".strip(" /")[:EVIDENCE_JOIN_LIMIT]


def merge(
    rule_findings: list[Finding],
    model_findings: list[Finding],
    stats: dict[str, int] | None = None,
) -> list[Finding]:
    """코드당 지적 하나로 모은다. 근거가 강한 쪽(rule > ocr > llm > vlm)을 남긴다.

    합치는 이유가 둘이다.

    하나는 재현성. 같은 코드를 룰과 모델이 모두 잡으면 룰 쪽을 남긴다.

    다른 하나는 **읽을 수 있는 보고서**. 병원 랜딩페이지는 배너 8장이 전부
    같은 항목(의료 효과 주장)에 걸린다. 이미지마다 카드를 만들면 제목도
    설명도 수정 방법도 똑같은 카드가 8장 쌓여서, 정작 다른 지적이 그 아래로
    밀려 안 보인다. 실제 페이지에서 그렇게 나왔다.

    다만 합치면서 버리면 안 된다. 예전 구현은 진 쪽을 통째로 버렸고
    그래서 **어느 이미지에서 나왔는지**와 **다른 위반 문구**가 사라졌다.
    고칠 대상이 안 보이면 고칠 수 없다. 그래서 근거는 이어 붙이고
    이미지 주소는 image_urls에 모은다.
    """
    ordered = sorted(
        rule_findings + model_findings,
        key=lambda f: SOURCE_ORDER.get(f.source.value, 9),
    )

    by_code: dict[str, Finding] = {}
    merged: list[Finding] = []
    for f in ordered:
        kept = by_code.get(f.code)
        if kept is None:
            by_code[f.code] = f
            if f.image_url and f.image_url not in f.image_urls:
                f.image_urls.append(f.image_url)
            merged.append(f)
            continue
        if stats is not None:
            key = ("merged_same_source" if kept.source is f.source
                   else "merged_by_stronger_source")
            stats[key] = stats.get(key, 0) + 1
        _absorb(kept, f)

    return sort_findings(merged)
