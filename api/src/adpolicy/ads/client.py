"""Ads API 어댑터 경계.

왜 경계를 두는가
    개발자 토큰이 없어 실제 호출을 검증할 수 없다. 그렇다고 구현을 미루면
    파이프라인 전체가 멈춘다. 그래서 **읽기 계약만 먼저 고정**하고, 뒤에
    두 가지 구현을 둔다.

        FakeAdsClient    녹화된 JSON 픽스처로 동작. 지금 쓰는 것.
        GoogleAdsClient  실제 호출. 토큰이 생기면 이 파일만 채운다.

    v1에서 `probe_profiles`를 mock으로 갈아끼워 테스트한 것과 같은 구조다.

이 계층이 하지 않는 것
    쓰기. 소재 수정·재제출은 승인 게이트(설계서 §3-5) 뒤에 오는 별도 단계이며,
    실제 API 없이 검증할 수 없으므로 여기에 넣지 않았다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import (
    AccountInfo,
    AccountStatus,
    AdRecord,
    ApprovalStatus,
    PolicyTopicEntry,
    PolicyTopicType,
)

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "eval" / "ads_fixtures"


class AdsClient(Protocol):
    """읽기 전용 계약."""

    def get_account(self, customer_id: str) -> AccountInfo: ...

    def list_ads(self, customer_id: str) -> list[AdRecord]:
        """해당 계정의 소재 목록. 필터링은 호출자(watcher)가 한다 —
        어댑터가 똑똑해지면 Fake와 Real의 동작이 갈라진다."""
        ...


# ---------------------------------------------------------------------------
# 역직렬화 — 픽스처와 실제 응답이 같은 경로를 타게 한다
# ---------------------------------------------------------------------------

def _enum(cls, raw: str):
    """모르는 값이 와도 터지지 않는다. API는 언제든 새 열거값을 추가한다."""
    try:
        return cls(raw)
    except ValueError:
        return cls.UNKNOWN


def parse_topic_entry(raw: dict) -> PolicyTopicEntry:
    return PolicyTopicEntry(
        topic=str(raw.get("topic", "")),
        type=_enum(PolicyTopicType, str(raw.get("type", ""))),
        evidences=tuple(str(x) for x in raw.get("evidences", ())),
        constraints=tuple(str(x) for x in raw.get("constraints", ())),
    )


def parse_ad(raw: dict, customer_id: str = "") -> AdRecord:
    summary = raw.get("policy_summary") or {}
    return AdRecord(
        ad_id=str(raw.get("ad_id", "")),
        customer_id=str(raw.get("customer_id") or customer_id),
        campaign_id=str(raw.get("campaign_id", "")),
        ad_group_id=str(raw.get("ad_group_id", "")),
        final_urls=tuple(str(u) for u in raw.get("final_urls", ())),
        headlines=tuple(str(h) for h in raw.get("headlines", ())),
        descriptions=tuple(str(d) for d in raw.get("descriptions", ())),
        approval_status=_enum(
            ApprovalStatus, str(summary.get("approval_status", ""))),
        review_status=str(summary.get("review_status", "")),
        policy_topic_entries=tuple(
            parse_topic_entry(e) for e in summary.get("policy_topic_entries", ())
        ),
    )


class FakeAdsClient:
    """녹화된 JSON으로 동작하는 어댑터.

    픽스처 형식 (`<customer_id>.json`)::

        {
          "account": {"customer_id": "...", "status": "ENABLED", ...},
          "ads": [ {...}, ... ]
        }
    """

    def __init__(self, fixture_dir: Path | str | None = None,
                 data: dict[str, dict] | None = None) -> None:
        self._dir = Path(fixture_dir) if fixture_dir else DEFAULT_FIXTURE_DIR
        self._data = data or {}

    def _load(self, customer_id: str) -> dict:
        if customer_id in self._data:
            return self._data[customer_id]
        path = self._dir / f"{customer_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"픽스처가 없습니다: {path}")
        blob = json.loads(path.read_text("utf-8"))
        self._data[customer_id] = blob
        return blob

    def get_account(self, customer_id: str) -> AccountInfo:
        acc = self._load(customer_id).get("account", {})
        return AccountInfo(
            customer_id=str(acc.get("customer_id", customer_id)),
            status=_enum(AccountStatus, str(acc.get("status", ""))),
            descriptive_name=str(acc.get("descriptive_name", "")),
        )

    def list_ads(self, customer_id: str) -> list[AdRecord]:
        blob = self._load(customer_id)
        return [parse_ad(a, customer_id) for a in blob.get("ads", ())]


class GoogleAdsClient:
    """실제 API 어댑터 — **아직 구현하지 않았다.**

    구현할 때 할 일 (설계서 §3-1의 GAQL을 그대로 쓴다)

        1. `google-ads` 라이브러리로 GoogleAdsService.search_stream 호출
        2. 첫 응답을 `eval/ads_fixtures/` 에 그대로 덤프
        3. 그 덤프로 `parse_ad`가 도는지 확인하고, 어긋나면 models.py 교정
        4. 그 다음에야 이 클래스를 실제로 쓴다

    2~3번을 건너뛰면 필드명 추측이 파이프라인 전체로 번진다.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "실제 Ads API 어댑터는 아직 구현하지 않았습니다. "
            "개발자 토큰과 테스트 계정으로 응답을 한 번 덤프해 "
            "eval/ads_fixtures/ 에 넣고 스키마를 교정한 뒤 구현하세요. "
            "그 전까지는 FakeAdsClient를 쓰십시오."
        )
