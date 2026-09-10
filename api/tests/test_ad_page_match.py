"""광고 ↔ 방문 페이지 대조 테스트.

공식 정책의 Unclear relevance / Unavailable offers 대응 로직을 검증한다.
"""

from __future__ import annotations

from adpolicy.models import PageSnapshot
from adpolicy.rules import check_ad_page_match, check_technical


def snap(text: str, **kw) -> PageSnapshot:
    base = dict(
        url="https://example.com/lp",
        final_url="https://example.com/lp",
        status_code=200,
        title="",
        text=text,
    )
    base.update(kw)
    return PageSnapshot(**base)


def codes(findings) -> set[str]:
    return {f.code for f in findings}


# --- 관련성 ----------------------------------------------------------------

def test_relevant_ad_and_page_pass():
    page = snap("유기농 원두 커피를 판매합니다. 원두 로스팅 당일 배송합니다.")
    found = check_ad_page_match(page, "유기농 원두 커피 로스팅 배송")
    assert "MIS-UNCLEAR-RELEVANCE" not in codes(found)


def test_irrelevant_ad_is_flagged():
    page = snap("저희는 자동차 정비소입니다. 엔진오일 교환과 타이어 정비를 합니다.")
    found = check_ad_page_match(page, "유기농 원두 커피 로스팅 신선한 배송")
    assert "MIS-UNCLEAR-RELEVANCE" in codes(found)


def test_relevance_skipped_without_ad_copy():
    page = snap("아무 내용")
    assert check_ad_page_match(page, "") == []


def test_relevance_skipped_for_too_few_keywords():
    page = snap("전혀 다른 내용입니다")
    # 키워드가 3개 미만이면 판정하지 않는다 (오탐 방지)
    found = check_ad_page_match(page, "커피")
    assert "MIS-UNCLEAR-RELEVANCE" not in codes(found)


def test_relevance_evidence_lists_missing_keywords():
    page = snap("자동차 정비소입니다 엔진오일 교환")
    found = check_ad_page_match(page, "유기농 원두 커피 로스팅 배송")
    hit = next(f for f in found if f.code == "MIS-UNCLEAR-RELEVANCE")
    assert hit.evidence  # 어떤 키워드가 없는지 알려준다


# --- 약속한 혜택 ------------------------------------------------------------

def test_offer_present_on_page_passes():
    page = snap("지금 가입하면 30% 할인 혜택을 드립니다. 자세한 내용은 아래를 보세요.")
    found = check_ad_page_match(page, "30% 할인 진행중 지금 확인하세요")
    assert "MIS-UNAVAILABLE-OFFER" not in codes(found)


def test_offer_missing_from_page_is_flagged():
    page = snap("저희 제품을 소개합니다. 품질 좋은 원두를 사용합니다. 매장 안내입니다.")
    found = check_ad_page_match(page, "지금 30% 할인 원두 제품 소개 품질 매장")
    assert "MIS-UNAVAILABLE-OFFER" in codes(found)


def test_free_shipping_offer_checked():
    page = snap("저희 제품을 소개합니다. 품질 좋은 원두를 사용합니다. 매장 안내입니다.")
    found = check_ad_page_match(page, "무료 배송 원두 제품 소개 품질 매장")
    assert "MIS-UNAVAILABLE-OFFER" in codes(found)


def test_no_offer_in_ad_means_no_check():
    page = snap("평범한 소개 페이지입니다. 저희 회사를 소개합니다.")
    found = check_ad_page_match(page, "회사 소개 페이지 방문")
    assert "MIS-UNAVAILABLE-OFFER" not in codes(found)


def test_fetch_error_skips_matching():
    page = snap("", fetch_error="타임아웃")
    assert check_ad_page_match(page, "30% 할인 원두 커피") == []


# --- URL 형식 --------------------------------------------------------------

def test_ip_address_url_flagged():
    page = snap("내용" * 200, url="http://203.0.113.10/lp",
                final_url="http://203.0.113.10/lp")
    assert "DEST-UNACCEPTABLE-URL" in codes(check_technical(page))


def test_normal_domain_not_flagged():
    page = snap("내용" * 200)
    assert "DEST-UNACCEPTABLE-URL" not in codes(check_technical(page))
