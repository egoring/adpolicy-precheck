"""오탐 회귀 — 멀쩡한 페이지가 '게재 거부 위험'으로 잡히면 도구를 못 믿는다.

여기 있는 문구는 전부 실제로 잘못 걸렸던 것들이다.
"""

from __future__ import annotations

import pytest

from adpolicy import rules
from adpolicy.fetcher import _extract
from adpolicy.models import PageSnapshot, Platform

FILLER = "서비스 소개 " * 100


def _codes(text: str) -> set[str]:
    snap = PageSnapshot(url="u", final_url="u", status_code=200, text=text)
    return {f.code for f in rules.check_content_patterns(snap, "", Platform.GOOGLE_ADS)}


# --- 도박 -------------------------------------------------------------------


@pytest.mark.parametrize("text", ["이웃집 토토로 인형", "토토로 캐릭터 상품", "토토넷 물류"])
def test_toto_substring_is_not_gambling(text):
    assert "RESTRICT-GAMBLING" not in _codes(text)


@pytest.mark.parametrize(
    "text", ["스포츠 토토 추천", "토토 사이트 가입", "온라인 카지노", "바카라", "안전 놀이터"]
)
def test_real_gambling_still_caught(text):
    assert "RESTRICT-GAMBLING" in _codes(text)


# --- 위조품 -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["정품 급속 충전기", "정품 급행 배송", "정품 급 나눔"])
def test_genuine_product_is_not_counterfeit(text):
    assert "PROHIB-COUNTERFEIT" not in _codes(text)


@pytest.mark.parametrize("text", ["정품급 시계", "이미테이션 가방", "짝퉁 판매", "미러급 제품"])
def test_real_counterfeit_still_caught(text):
    assert "PROHIB-COUNTERFEIT" in _codes(text)


# --- 클릭베이트 --------------------------------------------------------------


@pytest.mark.parametrize("text", ["오늘 만나보세요", "오늘 만든 빵", "오늘 만족도 조사"])
def test_oneul_man_is_not_clickbait(text):
    assert "MIS-CLICKBAIT" not in _codes(text)


@pytest.mark.parametrize("text", ["오늘만 이 가격", "마감 임박", "단 3자리 남았습니다"])
def test_real_clickbait_still_caught(text):
    assert "MIS-CLICKBAIT" in _codes(text)


# --- 연락처 -----------------------------------------------------------------


def _has_contact(text: str) -> bool:
    # 사업자 정보 판정은 **거래를 하는 페이지**에만 걸린다. 판단 대상이 되도록
    # 구매 유도 문구를 넣어준다. 안 넣으면 이 헬퍼는 항상 True가 된다.
    snap = PageSnapshot(url="u", final_url="u", status_code=200,
                        text="지금 구매하세요 29,000원 " + text + FILLER)
    return "MIS-BUSINESS-IDENTITY" not in {f.code for f in rules.check_absence(snap, "")}


@pytest.mark.parametrize("text", ["상품코드 08123456789", "주문번호 12345678901"])
def test_random_digit_runs_are_not_phone_numbers(text):
    assert not _has_contact(text)


@pytest.mark.parametrize(
    "text", ["문의 02-1234-5678", "010-1234-5678", "1588-1234", "help@example.com"]
)
def test_real_contacts_recognised(text):
    assert _has_contact(text)


# --- 개인정보 수집 판정 ------------------------------------------------------


def _pii_codes(html: str) -> set[str]:
    snap = _extract(html, "u", "u", 200)
    return {
        f.code for f in rules.check_absence(snap, "")
        if f.code.startswith(("DATA-", "KR-"))
    }


def test_search_box_plus_footer_address_is_not_pii_collection():
    """푸터의 '주소:' 한 줄 때문에 검색창만 있는 페이지가 전부 걸렸다."""
    html = (
        '<html><body><input type="text" name="q" placeholder="검색">'
        f"<p>{FILLER}</p><footer>주소: 서울시 강남구 · 문의 02-111-2222</footer>"
        "</body></html>"
    )
    assert _pii_codes(html) == set()


def test_consultation_form_is_still_pii_collection():
    html = (
        "<html><body><form><label>이름</label><input name=name>"
        "<label>연락처</label><input name=phone><button>신청</button></form>"
        f"<p>{FILLER}</p></body></html>"
    )
    assert "DATA-NO-PRIVACY-POLICY" in _pii_codes(html)
    assert "KR-NO-CONSENT" in _pii_codes(html)


def test_email_input_alone_is_pii_collection():
    """타입만으로도 충분하다 — 폼 문구가 영어여도 잡혀야 한다."""
    html = (
        '<html><body><form><input type="email" name="email">'
        f"<button>Subscribe</button></form><p>{FILLER}</p></body></html>"
    )
    assert "DATA-NO-PRIVACY-POLICY" in _pii_codes(html)
