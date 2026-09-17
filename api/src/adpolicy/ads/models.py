"""Google Ads 쪽 자료형.

⚠️ 필드명과 열거값은 **공식 문서를 읽고 옮긴 것이며 실제 응답으로 검증하지
않았다.** 개발자 토큰이 없어 호출해 보지 못했다. 토큰이 생기면 첫 응답을
`fixtures/`에 덤프해 이 정의를 교정하는 단계가 반드시 필요하다.
(docs/설계서-v2-반려복구루프.md §8-1 참조)

그래서 이 계층은 **어댑터 경계**로 설계했다. 실제 스키마가 달라도
`GoogleAdsClient` 한 곳만 고치면 나머지 파이프라인은 그대로 돈다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ApprovalStatus(str, Enum):
    """소재의 승인 상태."""

    APPROVED = "APPROVED"
    APPROVED_LIMITED = "APPROVED_LIMITED"
    AREA_OF_INTEREST_ONLY = "AREA_OF_INTEREST_ONLY"
    DISAPPROVED = "DISAPPROVED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_rejected(self) -> bool:
        """복구 루프를 태울 대상인가.

        APPROVED_LIMITED는 **반려가 아니다.** 게재는 되고 범위만 좁다.
        수집은 하되(학습 데이터로 값지다) 수정·재제출은 하지 않는다.
        """
        return self in (self.DISAPPROVED, self.AREA_OF_INTEREST_ONLY)


class PolicyTopicType(str, Enum):
    """위반의 성격."""

    PROHIBITED = "PROHIBITED"
    LIMITED = "LIMITED"
    FULLY_LIMITED = "FULLY_LIMITED"
    DESCRIPTIVE = "DESCRIPTIVE"
    BROADENING = "BROADENING"
    AREA_OF_INTEREST_ONLY = "AREA_OF_INTEREST_ONLY"
    UNKNOWN = "UNKNOWN"


class AccountStatus(str, Enum):
    ENABLED = "ENABLED"
    CANCELED = "CANCELED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"

    @property
    def can_operate(self) -> bool:
        """이 계정에서 소재를 고치는 게 의미가 있는가.

        계정이 정지된 상태라면 소재를 아무리 고쳐도 광고가 나가지 않는다.
        그리고 **계정 정지는 이 시스템이 다루는 문제가 아니다.**
        감지하면 멈추고 사람에게 넘긴다.
        """
        return self is self.ENABLED


@dataclass(frozen=True)
class PolicyTopicEntry:
    """반려 사유 하나. Google이 알려주는 '무엇이 왜 걸렸는가'."""

    topic: str
    type: PolicyTopicType = PolicyTopicType.UNKNOWN
    evidences: tuple[str, ...] = ()      # 근거 문자열 (본문 조각, URL 등)
    constraints: tuple[str, ...] = ()    # 지역 제한 등


@dataclass(frozen=True)
class AdRecord:
    """소재 하나의 현재 상태."""

    ad_id: str
    customer_id: str
    campaign_id: str = ""
    ad_group_id: str = ""
    final_urls: tuple[str, ...] = ()
    headlines: tuple[str, ...] = ()
    descriptions: tuple[str, ...] = ()
    approval_status: ApprovalStatus = ApprovalStatus.UNKNOWN
    review_status: str = ""
    policy_topic_entries: tuple[PolicyTopicEntry, ...] = ()

    @property
    def landing_url(self) -> str:
        return self.final_urls[0] if self.final_urls else ""

    @property
    def topics(self) -> tuple[str, ...]:
        return tuple(e.topic for e in self.policy_topic_entries)


@dataclass(frozen=True)
class AccountInfo:
    customer_id: str
    status: AccountStatus = AccountStatus.UNKNOWN
    descriptive_name: str = ""


class MappingStatus(str, Enum):
    MAPPED = "mapped"
    UNMAPPED = "unmapped"


@dataclass(frozen=True)
class Mapping:
    """Google의 사유를 내부 rule code로 옮긴 결과."""

    topic: str
    rule_codes: tuple[str, ...] = ()
    status: MappingStatus = MappingStatus.UNMAPPED

    @property
    def is_mapped(self) -> bool:
        return self.status is MappingStatus.MAPPED


@dataclass
class RecheckOutcome:
    """반려된 소재를 v1로 다시 점검한 결과 — 채점표의 한 줄."""

    ad_id: str
    topic: str
    rule_codes: tuple[str, ...] = ()
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    detected: bool = False               # v1도 이 사유를 잡았는가
    produced_codes: tuple[str, ...] = () # v1이 실제로 낸 코드 전체
    note: str = ""

    @property
    def verdict(self) -> str:
        """세 갈래. 이 분류가 그대로 로드맵이 된다.

        hit       우리도 잡았다 — 정상
        miss      매핑은 됐는데 우리가 못 잡았다 — v1 규칙의 민감도 문제
        no_rule   대응 규칙 자체가 없다 — 신규 규칙 후보
        """
        if self.mapping_status is MappingStatus.UNMAPPED:
            return "no_rule"
        return "hit" if self.detected else "miss"


@dataclass
class RecallReport:
    """재현율 — "우리 사전 점검이 실제 반려의 몇 %를 예측했는가"."""

    outcomes: list[RecheckOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def hits(self) -> int:
        return sum(1 for o in self.outcomes if o.verdict == "hit")

    @property
    def misses(self) -> int:
        return sum(1 for o in self.outcomes if o.verdict == "miss")

    @property
    def no_rule(self) -> int:
        return sum(1 for o in self.outcomes if o.verdict == "no_rule")

    @property
    def mapped(self) -> int:
        return self.hits + self.misses

    @property
    def recall_on_mapped(self) -> float | None:
        """매핑된 사유에 한정한 재현율. 분모가 0이면 None —
        0.0을 돌려주면 '재현율 0%'로 읽혀 오해를 부른다."""
        return (self.hits / self.mapped) if self.mapped else None

    @property
    def coverage(self) -> float | None:
        """전체 사유 중 우리 규칙 체계에 대응물이 있는 비율."""
        return (self.mapped / self.total) if self.total else None

    def unmapped_topics(self) -> dict[str, int]:
        """대응 규칙이 없는 사유와 빈도. v1에 빠진 규칙의 목록이다."""
        out: dict[str, int] = {}
        for o in self.outcomes:
            if o.verdict == "no_rule":
                out[o.topic] = out.get(o.topic, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def missed_topics(self) -> dict[str, int]:
        """규칙은 있는데 못 잡은 사유와 빈도. 민감도를 손볼 대상이다."""
        out: dict[str, int] = {}
        for o in self.outcomes:
            if o.verdict == "miss":
                out[o.topic] = out.get(o.topic, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
