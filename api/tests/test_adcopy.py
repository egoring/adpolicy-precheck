"""광고 문구 자체의 편집 기준.

내용이 아무리 멀쩡해도 제목이 한 글자 길면 광고가 나가지 않는다. 그리고
이건 전부 코드가 100% 결정적으로 판정할 수 있다 — 이 프로젝트에서 "고치면
반드시 통과한다"고 말할 수 있는 거의 유일한 축이다.

**한국어에서 제목은 30자가 아니라 15자다.** Google이 2바이트 언어의 문자
하나를 두 자로 세기 때문이다. 이 파일의 절반은 그 사실을 지키는 테스트다.
"""

from __future__ import annotations

import pytest

from adpolicy import adcopy

# ---------------------------------------------------------------------------
# 글자 수 — 어떻게 세는가
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("abcde", 5),
    ("가나다", 6),            # 한글 한 글자가 2
    ("3만원", 1 + 2 + 2),      # 숫자는 1, 한글은 각각 2
    ("", 0),
])
def test_the_width_is_counted_the_way_google_counts_it(text, expected):
    assert adcopy.width(text) == expected


def test_fifteen_hangul_characters_are_exactly_the_headline_limit():
    """한국어 제목의 실질 한도가 15자라는 사실 자체를 못박아 둔다."""
    assert adcopy.width("가" * 15) == adcopy.HEADLINE_LIMIT
    assert adcopy.width("가" * 16) > adcopy.HEADLINE_LIMIT


def test_forty_five_hangul_characters_are_exactly_the_description_limit():
    assert adcopy.width("가" * 45) == adcopy.DESCRIPTION_LIMIT


def codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_a_sixteen_character_korean_headline_is_over():
    found = adcopy.check_lengths(["가" * 16], [])
    assert "AD-HEADLINE-TOO-LONG" in codes(found)


def test_fifteen_is_fine():
    assert adcopy.check_lengths(["가" * 15], []) == []


def test_thirty_english_characters_are_fine():
    """영문은 30자 그대로다. 한글 기준으로 깎으면 영문 광고가 억울해진다."""
    assert adcopy.check_lengths(["a" * 30], []) == []


def test_the_evidence_says_how_long_it_actually_is():
    found = adcopy.check_lengths(["가" * 20], [])
    assert "40자" in found[0].evidence and "한도 30자" in found[0].evidence


def test_the_longest_one_is_the_one_shown():
    found = adcopy.check_lengths(["가" * 16, "가" * 25, "가" * 17], [])
    assert "50자" in found[0].evidence and "3개 초과" in found[0].evidence


def test_a_long_description_is_caught_separately():
    found = adcopy.check_lengths([], ["가" * 50])
    assert codes(found) == {"AD-DESCRIPTION-TOO-LONG"}


def test_length_is_not_judged_from_a_single_blob():
    """ad_copy 한 덩어리로는 어느 필드인지 모른다. 모르면서 단정하지 않는다."""
    found = adcopy.check("가" * 100, [], [])
    assert "AD-HEADLINE-TOO-LONG" not in codes(found)
    assert "AD-DESCRIPTION-TOO-LONG" not in codes(found)


# ---------------------------------------------------------------------------
# 문장부호·기호
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "지금 신청하세요!!",           # 정책 문서의 예시가 정확히 flowers!!
    "정말요??",
    "지금 신청~~~",
])
def test_repeated_punctuation_is_caught(text):
    assert "AD-SYMBOL-ABUSE" in codes(adcopy.check_style(text))


@pytest.mark.parametrize("text", [
    "지금 신청하세요!",
    "정말 그럴까요?",
    "가격은 29,000원. 문의하세요.",
    "A/S 가능 · 무료 배송",
])
def test_normal_punctuation_is_not(text):
    assert "AD-SYMBOL-ABUSE" not in codes(adcopy.check_style(text))


def test_decorative_symbols_piled_up_are_caught():
    assert "AD-SYMBOL-ABUSE" in codes(adcopy.check_style("★★★ 초특가 ★★★"))


def test_a_single_separator_symbol_is_allowed():
    """기호 하나를 구분자로 쓰는 건 흔하고 문제도 아니다."""
    assert "AD-SYMBOL-ABUSE" not in codes(adcopy.check_style("무료 배송 ★ 당일 출고"))


@pytest.mark.parametrize("text", ["f1owers 판매", "fl@wers 배송"])
def test_symbols_swapped_into_words_are_caught(text):
    """정책 문서가 드는 예시 그대로다."""
    assert "AD-SYMBOL-ABUSE" in codes(adcopy.check_style(text))


def test_emoji_is_reported():
    found = adcopy.check_style("지금 신청하세요 🔥🔥")
    assert "AD-SYMBOL-ABUSE" in codes(found)
    assert "이모지" in next(f for f in found if f.code == "AD-SYMBOL-ABUSE").evidence


def test_the_emoji_rule_does_not_claim_more_than_the_document_says():
    """정책 문서는 이모지를 이름으로 지목하지 않는다. 그렇게 적어 둔다."""
    from adpolicy.policies import POLICY_BY_CODE
    detail = POLICY_BY_CODE["AD-SYMBOL-ABUSE"].description
    assert "명시된 금지 조항은 아니다" in detail


# ---------------------------------------------------------------------------
# 대문자
# ---------------------------------------------------------------------------


def test_all_caps_words_are_caught():
    assert "AD-CAPS-ABUSE" in codes(adcopy.check_style("BEST PRICE 지금 구매"))


@pytest.mark.parametrize("text", [
    "HTML 강의 모집",       # 알려진 약어
    "FAQ 보기",
    "KTX 특가",
    "Best Price 지금 구매",  # 첫 글자만 대문자
])
def test_acronyms_and_normal_case_survive(text):
    assert "AD-CAPS-ABUSE" not in codes(adcopy.check_style(text))


def test_korean_is_never_flagged_for_capitalization():
    """한글에는 대소문자가 없다. 여기서 걸리면 규칙 자체가 잘못된 것이다."""
    assert "AD-CAPS-ABUSE" not in codes(adcopy.check_style("지금 신청하세요 무료 상담"))


# ---------------------------------------------------------------------------
# 반복
# ---------------------------------------------------------------------------


def test_keyword_stuffing_is_caught():
    text = "원두 원두 원두 정기배송"
    found = adcopy.check_style(text)
    assert "AD-REPETITION" in codes(found)
    assert "원두" in next(f for f in found if f.code == "AD-REPETITION").evidence


def test_saying_something_twice_is_allowed():
    """두 번까지는 자연스러운 문장에서도 흔하다."""
    assert "AD-REPETITION" not in codes(adcopy.check_style("원두 정기배송, 원두 선물세트"))


# ---------------------------------------------------------------------------
# 공백
# ---------------------------------------------------------------------------


def test_letter_spacing_to_dodge_filters_is_caught():
    assert "AD-SPACING-ABUSE" in codes(adcopy.check_style("무 료 상 담 신청"))


def test_extra_spaces_are_caught():
    assert "AD-SPACING-ABUSE" in codes(adcopy.check_style("지금    신청하세요"))


def test_ordinary_spacing_is_fine():
    assert "AD-SPACING-ABUSE" not in codes(
        adcopy.check_style("지금 신청하세요. 무료 상담 가능합니다."))


def test_a_single_letter_word_does_not_trigger_it():
    assert "AD-SPACING-ABUSE" not in codes(adcopy.check_style("A/S 문의 주세요"))


# ---------------------------------------------------------------------------
# 완전히 깨끗한 문구는 아무것도 나오면 안 된다
# ---------------------------------------------------------------------------


def test_a_clean_ad_produces_nothing():
    found = adcopy.check(
        "", ["갓 볶은 원두 정기배송", "첫 주문 30% 할인"],
        ["매주 로스팅한 원두를 집으로 보내드립니다. 무료 배송."],
    )
    assert found == []


# ---------------------------------------------------------------------------
# TikTok — 광고 문구와 랜딩페이지의 언어
# ---------------------------------------------------------------------------

KOREAN_PAGE = "신선한 원두를 정기 배송해 드립니다. 주문하시면 다음 날 로스팅합니다. " * 3
ENGLISH_PAGE = "We deliver freshly roasted coffee beans to your door every week. " * 3


def test_a_korean_ad_pointing_at_an_english_page_is_reported():
    found = adcopy.check_language_match("갓 볶은 원두를 집까지 보내드립니다", ENGLISH_PAGE)
    assert "TT-LANGUAGE-MISMATCH" in codes(found)
    assert "한국어" in found[0].evidence and "로마자" in found[0].evidence


def test_matching_languages_are_not_reported():
    assert adcopy.check_language_match("갓 볶은 원두를 집까지 보내드립니다", KOREAN_PAGE) == []


def test_a_korean_page_with_english_brand_names_is_still_korean():
    """국내 페이지에는 브랜드명·버튼 라벨이 영문으로 섞인다. 이걸로 걸면 안 된다."""
    mixed = ("COFFEE LAB 원두 정기배송 서비스입니다. "
             "지금 주문하시면 다음 날 로스팅해 보내드립니다. " * 3)
    assert adcopy.dominant_script(mixed) == "한국어"


def test_too_short_to_tell_is_not_guessed():
    """몇 글자로 언어를 단정하면 틀린다. 모르면 모른다고 한다."""
    assert adcopy.dominant_script("무료") == ""
    assert adcopy.check_language_match("무료", KOREAN_PAGE) == []


def test_a_half_and_half_page_is_not_judged():
    """어느 쪽도 확실하지 않으면 언어를 단정하지 않는다."""
    half = "커피 원두 정기배송 " * 5 + "coffee bean subscription service " * 3
    assert adcopy.dominant_script(half) == ""
