"""v2 — 반려 복구 루프의 1~4단계 (감지 · 정규화 · 재점검 · 원장).

    python -m adpolicy.ads --customer 1234567890

무엇을 하는가
    v1은 "이 페이지가 정책에 걸릴 것 같다"를 예측한다. 그런데 그 예측이
    맞았는지 확인할 방법이 없었다. 이 모듈은 Google의 실제 판정을 가져와
    **채점표를 만든다.**

무엇을 하지 않는가 (설계 원칙으로 배제)
    - 정지된 계정을 대체할 새 계정 생성 — 시스템 우회 정책 위반
    - 사람 승인 없는 자동 재제출
    - 랜딩페이지 자동 수정
    자세한 근거는 docs/설계서-v2-반려복구루프.md §0 참조.

⚠️ 스키마 미검증
    개발자 토큰이 없어 실제 API 응답으로 검증하지 못했다. 필드명·열거값은
    문서를 읽고 옮긴 것이다. `GoogleAdsClient`는 일부러 구현하지 않았고,
    토큰이 생기면 첫 응답을 덤프해 스키마를 교정한 뒤 채워야 한다.
"""

from .client import AdsClient, FakeAdsClient, GoogleAdsClient, parse_ad
from .mapping import TOPIC_TO_RULES, UnmappedLedger, normalize, validate_table
from .models import (
    AccountInfo,
    AccountStatus,
    AdRecord,
    ApprovalStatus,
    Mapping,
    MappingStatus,
    PolicyTopicEntry,
    PolicyTopicType,
    RecallReport,
    RecheckOutcome,
)
from .recheck import PageChecker, make_offline_checker, recheck_ad, recheck_all
from .watcher import AccountHalted, SeenIndex, WatchResult, collect

__all__ = [
    "AccountHalted", "AccountInfo", "AccountStatus", "AdRecord", "AdsClient",
    "ApprovalStatus", "FakeAdsClient", "GoogleAdsClient", "Mapping",
    "MappingStatus", "PageChecker", "PolicyTopicEntry", "PolicyTopicType",
    "RecallReport", "RecheckOutcome", "SeenIndex", "TOPIC_TO_RULES",
    "UnmappedLedger", "WatchResult", "collect", "make_offline_checker",
    "normalize", "parse_ad", "recheck_ad", "recheck_all", "validate_table",
]
