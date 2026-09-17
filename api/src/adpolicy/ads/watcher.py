"""반려 감지와 안전장치.

이 모듈의 책임은 "무엇을 처리 대상으로 삼을 것인가"를 정하는 것이다.
고치는 일은 하지 않는다.

안전장치가 여기 모여 있는 이유
    잘못된 대상을 큐에 넣는 것이 이 시스템에서 가장 위험한 실수다.
    계정이 정지된 상태인데 소재를 만지거나, 같은 사유로 무한히 재트리거되면
    광고주에게 피해가 간다. 그래서 필터링을 한곳에 모아 테스트한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .client import AdsClient
from .models import AccountInfo, AdRecord, ApprovalStatus


class AccountHalted(RuntimeError):
    """계정 자체가 정지·해지된 상태. 소재 수정은 의미가 없다.

    **계정 정지는 이 시스템이 다루는 문제가 아니다.** 소재 반려와는 다른
    문제이고, 자동으로 손대면 안 되는 영역이다. 감지하면 멈추고 사람에게 넘긴다.
    """

    def __init__(self, account: AccountInfo) -> None:
        self.account = account
        super().__init__(
            f"계정 {account.customer_id}의 상태가 {account.status.value}입니다. "
            "소재를 고쳐도 광고가 나가지 않습니다. 자동 처리를 중단합니다 — "
            "계정 정지는 사람이 직접 확인해야 하는 사안입니다."
        )


@dataclass
class WatchResult:
    account: AccountInfo
    rejected: list[AdRecord] = field(default_factory=list)
    limited: list[AdRecord] = field(default_factory=list)
    skipped_seen: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def actionable(self) -> list[AdRecord]:
        return self.rejected


class SeenIndex:
    """이미 처리한 (소재, 사유) 조합을 기억한다.

    이게 없으면 같은 사유로 매 폴링마다 다시 트리거되고, 그 끝은 재제출
    루프다. 소재 단위가 아니라 **(소재, 사유) 단위**인 이유는, 하나를 고친
    뒤 다른 사유로 다시 반려될 수 있기 때문이다.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def is_new(self, ad: AdRecord) -> bool:
        keys = {(ad.ad_id, t) for t in ad.topics} or {(ad.ad_id, "")}
        return bool(keys - self._seen)

    def mark(self, ad: AdRecord) -> None:
        keys = {(ad.ad_id, t) for t in ad.topics} or {(ad.ad_id, "")}
        self._seen |= keys

    def __len__(self) -> int:
        return len(self._seen)


def collect(client: AdsClient, customer_id: str, *,
            seen: SeenIndex | None = None) -> WatchResult:
    """반려된 소재를 모은다.

    Raises:
        AccountHalted: 계정이 ENABLED가 아닐 때. 소재를 읽지도 않는다.
    """
    account = client.get_account(customer_id)
    if not account.status.can_operate:
        raise AccountHalted(account)

    result = WatchResult(account=account)
    for ad in client.list_ads(customer_id):
        status = ad.approval_status
        if status is ApprovalStatus.APPROVED_LIMITED:
            # 반려가 아니다 — 게재는 된다. 수집만 하고 처리하지 않는다.
            result.limited.append(ad)
            continue
        if not status.is_rejected:
            continue
        if seen is not None and not seen.is_new(ad):
            result.skipped_seen.append(ad.ad_id)
            continue
        if seen is not None:
            seen.mark(ad)
        result.rejected.append(ad)

    parts = [f"반려 {len(result.rejected)}건"]
    if result.limited:
        parts.append(f"제한 승인 {len(result.limited)}건(처리 안 함)")
    if result.skipped_seen:
        parts.append(f"이미 본 것 {len(result.skipped_seen)}건 건너뜀")
    result.note = " · ".join(parts)
    return result
