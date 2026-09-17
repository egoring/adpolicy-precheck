"""v2 반려 복구 루프 — 감지 · 정규화 · 재점검 · 원장.

가장 중요한 테스트는 지표가 아니라 **안전장치**다. 잘못된 대상을 처리하는 것이
이 시스템에서 가장 위험한 실수이고, 그게 깨지면 광고주에게 피해가 간다.
"""

from __future__ import annotations

import json

import pytest

from adpolicy.ads import (
    AccountHalted,
    AdRecord,
    ApprovalStatus,
    FakeAdsClient,
    GoogleAdsClient,
    PolicyTopicEntry,
    SeenIndex,
    UnmappedLedger,
    collect,
    make_offline_checker,
    normalize,
    parse_ad,
    recheck_ad,
    recheck_all,
    validate_table,
)
from adpolicy.ads.client import DEFAULT_FIXTURE_DIR
from adpolicy.ads.models import AccountStatus, MappingStatus

NORMAL = "1234567890"
SUSPENDED = "9999999999"


@pytest.fixture
def client() -> FakeAdsClient:
    return FakeAdsClient(DEFAULT_FIXTURE_DIR)


@pytest.fixture
def pages() -> dict[str, str]:
    p = DEFAULT_FIXTURE_DIR / "landing_pages.json"
    return json.loads(p.read_text("utf-8"))


# --- 안전장치 (가장 중요) ---------------------------------------------------

def test_suspended_account_halts_before_reading_ads(client):
    """계정이 정지되면 소재를 읽지도 않아야 한다.

    소재 수정은 의미가 없고, 계정 정지는 이 시스템이 다루는 문제가 아니다.
    """
    with pytest.raises(AccountHalted) as exc:
        collect(client, SUSPENDED)
    assert exc.value.account.status is AccountStatus.SUSPENDED
    assert "사람이 직접" in str(exc.value)


@pytest.mark.parametrize("status", ["SUSPENDED", "CANCELED", "CLOSED", "UNKNOWN"])
def test_only_enabled_accounts_can_be_operated_on(status):
    data = {"X": {"account": {"customer_id": "X", "status": status}, "ads": []}}
    with pytest.raises(AccountHalted):
        collect(FakeAdsClient(data=data), "X")


def test_approved_limited_is_collected_but_not_processed(client):
    """제한 승인은 반려가 아니다. 게재는 된다 — 고치려 들면 안 된다."""
    res = collect(client, NORMAL)
    limited_ids = {a.ad_id for a in res.limited}
    assert "a-limited" in limited_ids
    assert "a-limited" not in {a.ad_id for a in res.actionable}
    assert "처리 안 함" in res.note


def test_approved_ads_are_ignored(client):
    res = collect(client, NORMAL)
    assert "a-ok" not in {a.ad_id for a in res.actionable}


def test_seen_index_prevents_retriggering_on_same_reason(client):
    """같은 사유로 매 폴링마다 다시 트리거되면 그 끝은 재제출 루프다."""
    seen = SeenIndex()
    first = collect(client, NORMAL, seen=seen)
    assert first.actionable, "첫 회차에는 대상이 있어야 한다"
    second = collect(client, NORMAL, seen=seen)
    assert second.actionable == []
    assert second.skipped_seen


def test_seen_index_is_per_reason_not_per_ad():
    """하나를 고친 뒤 다른 사유로 다시 반려될 수 있다."""
    seen = SeenIndex()
    ad1 = AdRecord(ad_id="a", customer_id="c",
                   approval_status=ApprovalStatus.DISAPPROVED,
                   policy_topic_entries=(PolicyTopicEntry(topic="CLOAKING"),))
    ad2 = AdRecord(ad_id="a", customer_id="c",
                   approval_status=ApprovalStatus.DISAPPROVED,
                   policy_topic_entries=(PolicyTopicEntry(topic="TRICK_TO_CLICK"),))
    assert seen.is_new(ad1)
    seen.mark(ad1)
    assert not seen.is_new(ad1)
    assert seen.is_new(ad2), "새 사유는 새로 처리해야 한다"


def test_live_adapter_refuses_instead_of_guessing():
    """검증하지 않은 스키마로 실제 호출을 흉내 내면 안 된다."""
    with pytest.raises(NotImplementedError, match="덤프"):
        GoogleAdsClient()


# --- 정규화 ----------------------------------------------------------------

def test_known_topic_maps_to_rule_codes():
    m = normalize("DESTINATION_NOT_WORKING")
    assert m.is_mapped
    assert m.rule_codes == ("DEST-NOT-WORKING",)


def test_topic_matching_is_case_and_space_insensitive():
    assert normalize("  cloaking  ").is_mapped


def test_unknown_topic_is_recorded_not_dropped():
    """모르는 사유가 조용히 사라지면 v1에 빠진 규칙을 영원히 못 본다."""
    ledger = UnmappedLedger()
    m = normalize("SOME_BRAND_NEW_TOPIC", ledger=ledger, ad_id="a1")
    assert m.status is MappingStatus.UNMAPPED
    assert m.rule_codes == ()
    assert ledger.counts() == {"SOME_BRAND_NEW_TOPIC": 1}


def test_unmapped_ledger_persists_to_disk(tmp_path):
    path = tmp_path / "unmapped.jsonl"
    ledger = UnmappedLedger(path)
    ledger.record("A", ad_id="x", evidence="근거")
    ledger.record("A", ad_id="y")
    rows = [json.loads(x) for x in path.read_text("utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["topic"] == "A"
    assert rows[0]["evidence"] == "근거"


def test_no_partial_string_matching():
    """'CLOAKING'이 들어 있다고 'PARAM_CLOAKING_SUSPECTED'에 붙으면 안 된다.
    모르는 것을 아는 척하지 않는다."""
    assert not normalize("PARAM_CLOAKING_SUSPECTED").is_mapped


def test_mapping_table_points_only_to_real_codes():
    """카탈로그에서 코드를 지웠는데 매핑표를 안 고치면, 매핑은 성공한 것처럼
    보이면서 그 뒤 단계가 전부 빗나간다."""
    assert validate_table() == []


# --- 재점검 ----------------------------------------------------------------

def test_detected_reason_is_a_hit(pages):
    ad = AdRecord(
        ad_id="a", customer_id="c",
        final_urls=("https://example.com/superlative",),
        approval_status=ApprovalStatus.DISAPPROVED,
        policy_topic_entries=(PolicyTopicEntry(topic="MISREPRESENTATION"),),
    )
    out = recheck_ad(ad, make_offline_checker(pages))
    assert [o.verdict for o in out] == ["hit"]


def test_reason_without_a_rule_is_no_rule(pages):
    ad = AdRecord(
        ad_id="a", customer_id="c",
        final_urls=("https://example.com/clean",),
        approval_status=ApprovalStatus.DISAPPROVED,
        policy_topic_entries=(PolicyTopicEntry(topic="TRADEMARK_IN_AD_TEXT"),),
    )
    out = recheck_ad(ad, make_offline_checker(pages))
    assert [o.verdict for o in out] == ["no_rule"]
    assert "신규 규칙 후보" in out[0].note


def test_mapped_but_undetected_is_a_miss(pages):
    """규칙은 있는데 못 잡은 경우. 이게 v1을 손볼 지점이다."""
    ad = AdRecord(
        ad_id="a", customer_id="c",
        final_urls=("https://example.com/clean",),
        approval_status=ApprovalStatus.DISAPPROVED,
        policy_topic_entries=(PolicyTopicEntry(topic="COUNTERFEIT"),),
    )
    out = recheck_ad(ad, make_offline_checker(pages))
    assert [o.verdict for o in out] == ["miss"]
    assert "탐지 실패" in out[0].note


def test_rejected_ad_without_reasons_is_not_swallowed(pages):
    """사유 없는 반려는 그 자체로 조사 대상이다."""
    ad = AdRecord(ad_id="a", customer_id="c",
                  final_urls=("https://example.com/clean",),
                  approval_status=ApprovalStatus.DISAPPROVED)
    ledger = UnmappedLedger()
    out = recheck_ad(ad, make_offline_checker(pages), ledger=ledger)
    assert len(out) == 1
    assert out[0].topic == "(사유 없음)"
    assert ledger.total == 1


def test_unknown_landing_page_does_not_crash(pages):
    ad = AdRecord(ad_id="a", customer_id="c",
                  final_urls=("https://nowhere.example.com/x",),
                  approval_status=ApprovalStatus.DISAPPROVED,
                  policy_topic_entries=(PolicyTopicEntry(topic="CLOAKING"),))
    out = recheck_ad(ad, make_offline_checker(pages))
    assert out[0].verdict == "miss"      # 못 잡은 것으로 정직하게 기록


# --- 지표 -------------------------------------------------------------------

def test_recall_is_none_when_nothing_is_mapped(pages):
    ad = AdRecord(ad_id="a", customer_id="c",
                  final_urls=("https://example.com/clean",),
                  approval_status=ApprovalStatus.DISAPPROVED,
                  policy_topic_entries=(PolicyTopicEntry(topic="NOPE"),))
    rep = recheck_all([ad], make_offline_checker(pages))
    assert rep.recall_on_mapped is None, "0.0을 돌려주면 '재현율 0%'로 오독된다"
    assert rep.coverage == 0.0


def test_full_pipeline_on_fixtures(client, pages):
    watch = collect(client, NORMAL)
    ledger = UnmappedLedger()
    rep = recheck_all(watch.actionable, make_offline_checker(pages), ledger=ledger)

    assert rep.total == 4                     # 반려 3건에서 사유 4개
    assert rep.hits >= 2
    assert rep.no_rule >= 1
    assert "TRADEMARK_IN_AD_TEXT" in rep.unmapped_topics()
    assert ledger.total == rep.no_rule        # 미대응은 전부 원장에 남는다


# --- 역직렬화 ---------------------------------------------------------------

def test_unknown_enum_value_does_not_crash():
    """API는 언제든 새 열거값을 추가한다. 터지는 대신 UNKNOWN으로 받는다."""
    ad = parse_ad({
        "ad_id": "x",
        "policy_summary": {"approval_status": "SOMETHING_NEW",
                           "policy_topic_entries": [
                               {"topic": "T", "type": "BRAND_NEW_TYPE"}]},
    }, customer_id="c")
    assert ad.approval_status is ApprovalStatus.UNKNOWN
    assert ad.policy_topic_entries[0].type.value == "UNKNOWN"
    assert not ad.approval_status.is_rejected   # 모르면 손대지 않는다


def test_fixture_files_carry_a_verification_warning():
    """손으로 만든 픽스처를 실제 응답으로 착각하면 안 된다."""
    blob = json.loads((DEFAULT_FIXTURE_DIR / f"{NORMAL}.json").read_text("utf-8"))
    assert "검증하지 않았습니다" in blob["_note"]
