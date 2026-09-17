"""사유 정규화 — Google의 policy topic을 내부 rule code로 옮긴다.

이 프로젝트에서 가장 어려운 부분이다. 양쪽 어휘가 다르고, Google이 쓰는
topic 문자열의 완전한 목록은 공개 명세가 없으며, 시간이 지나면 바뀐다.

설계 원칙 — **매핑 실패를 숨기지 않는다**
    모르는 topic이 오면 조용히 버리는 게 가장 쉬운 구현이다. 그러면
    "Google은 반려했는데 우리는 아무 말도 못 한 사유"가 영원히 보이지 않는다.
    그래서 `unmapped`로 격리해서 쌓고 리포트에 드러낸다.

    이 원장은 이 시스템의 가장 값진 산출물 중 하나다 —
    **v1에 빠진 규칙의 목록**이기 때문이다.

⚠️ 아래 표는 확인된 것만 담았다. 추측으로 채우지 않는다.
   비어 보이는 게 정직한 상태이고, 운영하면서 unmapped 원장을 보고 채운다.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from ..policies import POLICY_BY_CODE
from .models import Mapping, MappingStatus

# Google policy topic → 내부 rule code
#
# 한 topic이 여러 규칙에 걸릴 수 있다 (예: CLOAKING은 프로필 축과 파라미터 축
# 둘 다에 대응물이 있다). 그래서 값이 리스트다.
TOPIC_TO_RULES: dict[str, tuple[str, ...]] = {
    "DESTINATION_NOT_WORKING":        ("DEST-NOT-WORKING",),
    "DESTINATION_MISMATCH":           ("DEST-MISMATCH",),
    "DESTINATION_CONTENT":            ("DEST-INSUFFICIENT-CONTENT",),
    "DESTINATION_NOT_CRAWLABLE":      ("DEST-NOT-CRAWLABLE",),
    "UNACCEPTABLE_URL":               ("DEST-UNACCEPTABLE-URL",),
    "AUTOMATIC_DOWNLOAD":             ("DEST-AUTO-DOWNLOAD",),
    "BRIDGE_PAGE":                    ("DEST-BRIDGE-PAGE",),

    "CLOAKING":                       ("ABUSE-CLOAKING", "ABUSE-PARAM-CLOAKING"),
    "MALICIOUS_OR_UNWANTED_SOFTWARE": ("ABUSE-OBFUSCATED-SCRIPT",),
    "CIRCUMVENTING_SYSTEMS":          ("ABUSE-CLOAKING", "ABUSE-HIDDEN-TEXT"),

    "TRICK_TO_CLICK":                 ("MIS-CLICKBAIT",),
    "UNRELIABLE_CLAIMS":              ("MIS-UNRELIABLE-CLAIMS",),
    "UNACCEPTABLE_BUSINESS_PRACTICE": ("MIS-UNACCEPTABLE-BUSINESS",),
    "DISHONEST_PRICING":              ("MIS-DISHONEST-PRICING",),
    "MISREPRESENTATION":              ("MIS-UNRELIABLE-CLAIMS", "MIS-SUPERLATIVE"),
    "INSUFFICIENT_BUSINESS_INFO":     ("MIS-BUSINESS-IDENTITY",),

    "PERSONALIZED_ADVERTISING":       ("KR-NO-CONSENT",),
    "DATA_COLLECTION":                ("DATA-NO-PRIVACY-POLICY",),
    "INSECURE_DATA_COLLECTION":       ("DATA-INSECURE-COLLECTION",),

    "HEALTHCARE_AND_MEDICINES":       ("RESTRICT-HEALTHCARE",),
    "FINANCIAL_PRODUCTS":             ("RESTRICT-FINANCIAL",),
    "CRYPTOCURRENCY":                 ("RESTRICT-CRYPTO",),
    "GAMBLING_AND_GAMES":             ("RESTRICT-GAMBLING",),
    "ALCOHOL":                        ("RESTRICT-ALCOHOL",),
    "ADULT_CONTENT":                  ("RESTRICT-SEXUAL",),
    "DANGEROUS_PRODUCTS":             ("PROHIB-DANGEROUS",),
    "COUNTERFEIT":                    ("PROHIB-COUNTERFEIT",),
    "ENABLING_DISHONEST_BEHAVIOR":    ("PROHIB-ENABLING-DISHONEST",),

    "AD_TEXT_LENGTH":                 ("AD-HEADLINE-TOO-LONG",
                                       "AD-DESCRIPTION-TOO-LONG"),
    "PUNCTUATION_AND_SYMBOLS":        ("AD-SYMBOL-ABUSE",),
    "CAPITALIZATION":                 ("AD-CAPS-ABUSE",),
    "REPETITION":                     ("AD-REPETITION",),
    "SPACING":                        ("AD-SPACING-ABUSE",),
}


def validate_table() -> list[str]:
    """매핑표가 실재하지 않는 코드를 가리키고 있지 않은지 확인한다.

    정책 카탈로그에서 코드를 지웠는데 매핑표를 안 고치면, 매핑은 성공한 것처럼
    보이면서 그 뒤 단계가 전부 빗나간다. 조용히 넘어가면 안 되는 종류의 오류다.
    """
    bad: list[str] = []
    for topic, codes in TOPIC_TO_RULES.items():
        for code in codes:
            if code not in POLICY_BY_CODE:
                bad.append(f"{topic} → {code} (카탈로그에 없는 코드)")
    return bad


class UnmappedLedger:
    """대응 규칙이 없는 사유를 격리해 쌓는다. 버리지 않는다."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def record(self, topic: str, *, ad_id: str = "", evidence: str = "") -> None:
        with self._lock:
            self._counts[topic] = self._counts.get(topic, 0) + 1
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "ts": time.time(),
                "topic": topic,
                "ad_id": ad_id,
                "evidence": evidence[:300],
            }
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items(), key=lambda kv: -kv[1]))

    @property
    def total(self) -> int:
        return sum(self._counts.values())


def normalize(topic: str, *, ledger: UnmappedLedger | None = None,
              ad_id: str = "", evidence: str = "") -> Mapping:
    """topic 하나를 내부 코드로 옮긴다.

    대소문자와 앞뒤 공백만 정규화한다. 그 이상으로 똑똑하게 굴면
    (부분 문자열 매칭 같은 것) 엉뚱한 규칙에 붙는다 —
    "모르는 것을 아는 척하지 않는다"가 v1부터의 원칙이다.
    """
    key = topic.strip().upper()
    codes = TOPIC_TO_RULES.get(key)
    if not codes:
        if ledger is not None:
            ledger.record(key or topic, ad_id=ad_id, evidence=evidence)
        return Mapping(topic=key or topic, rule_codes=(),
                       status=MappingStatus.UNMAPPED)
    return Mapping(topic=key, rule_codes=codes, status=MappingStatus.MAPPED)
