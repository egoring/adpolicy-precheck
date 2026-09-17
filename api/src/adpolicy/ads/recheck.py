"""재점검 — 반려된 소재를 v1으로 다시 돌려 채점한다.

핵심 질문은 하나다.

    **Google이 지목한 사유를 우리 사전 점검도 찾았는가?**

여기서 세 갈래가 나온다.

    hit      우리도 잡았다              → 정상
    miss     규칙은 있는데 못 잡았다     → 민감도 문제. 규칙을 손본다
    no_rule  대응 규칙 자체가 없다       → 신규 규칙 후보

세 번째 갈래가 그대로 로드맵이 된다.

설계 판단 — 점검기를 주입받는다
    v1의 `/v1/check`는 네트워크를 타고 LLM도 쓴다. 그걸 직접 부르면 이
    모듈을 테스트할 수 없고, 채점 결과가 실행할 때마다 달라진다.
    그래서 `PageChecker`를 주입받는다. 실제 운영에서는 v1 파이프라인을,
    테스트·재현에서는 저장된 HTML을 쓰는 구현을 꽂는다.
"""

from __future__ import annotations

from typing import Protocol

from ..fetcher import _extract
from .mapping import UnmappedLedger, normalize
from .models import AdRecord, MappingStatus, RecallReport, RecheckOutcome


class PageChecker(Protocol):
    """랜딩페이지를 점검해 코드 집합을 돌려준다."""

    def __call__(self, *, url: str, ad_copy: str, headlines: list[str],
                 descriptions: list[str]) -> set[str]: ...


def make_offline_checker(html_by_url: dict[str, str]) -> PageChecker:
    """저장된 HTML로 v1 룰셋을 돌리는 점검기.

    네트워크를 타지 않으므로 결정적이다. 평가 하네스와 같은 계층을 쓴다 —
    두 곳이 다른 판정을 내면 숫자를 비교할 수 없다.
    """
    from .. import adcopy, rules
    from ..evalkit.runner import html_only_findings
    from ..models import Platform

    def check(*, url: str, ad_copy: str, headlines: list[str],
              descriptions: list[str]) -> set[str]:
        html = html_by_url.get(url, "")
        if not html:
            return set()
        snap = _extract(html, url, url, 200)
        findings = rules.run_all(snap, ad_copy, Platform.GOOGLE_ADS)
        findings += adcopy.check(ad_copy, headlines, descriptions)
        findings += html_only_findings(html, snap, url)
        return {f.code for f in findings}

    return check


def recheck_ad(ad: AdRecord, checker: PageChecker, *,
               ledger: UnmappedLedger | None = None) -> list[RecheckOutcome]:
    """소재 하나의 반려 사유들을 채점한다."""
    produced = checker(
        url=ad.landing_url,
        ad_copy=" ".join(ad.headlines[:1]) if ad.headlines else "",
        headlines=list(ad.headlines),
        descriptions=list(ad.descriptions),
    )

    outcomes: list[RecheckOutcome] = []
    for entry in ad.policy_topic_entries:
        evidence = entry.evidences[0] if entry.evidences else ""
        m = normalize(entry.topic, ledger=ledger, ad_id=ad.ad_id,
                      evidence=evidence)
        detected = bool(set(m.rule_codes) & produced) if m.is_mapped else False
        note = ""
        if not m.is_mapped:
            note = "대응 규칙 없음 — 신규 규칙 후보"
        elif not detected:
            note = (f"규칙은 있으나 탐지 실패: {', '.join(m.rule_codes)}")
        outcomes.append(RecheckOutcome(
            ad_id=ad.ad_id,
            topic=m.topic,
            rule_codes=m.rule_codes,
            mapping_status=m.status,
            detected=detected,
            produced_codes=tuple(sorted(produced)),
            note=note,
        ))

    if not ad.policy_topic_entries:
        # 반려됐는데 사유가 비어 있다. 드물지만 조용히 넘기면 안 된다 —
        # 사유 없는 반려는 그 자체로 조사 대상이다.
        outcomes.append(RecheckOutcome(
            ad_id=ad.ad_id, topic="(사유 없음)",
            mapping_status=MappingStatus.UNMAPPED,
            produced_codes=tuple(sorted(produced)),
            note="반려 상태이나 policy_topic_entries가 비어 있습니다.",
        ))
        if ledger is not None:
            ledger.record("(사유 없음)", ad_id=ad.ad_id)
    return outcomes


def recheck_all(ads: list[AdRecord], checker: PageChecker, *,
                ledger: UnmappedLedger | None = None) -> RecallReport:
    report = RecallReport()
    for ad in ads:
        report.outcomes.extend(recheck_ad(ad, checker, ledger=ledger))
    return report
