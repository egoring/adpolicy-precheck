"""공식 정책 문서와 대조해 넓힌 항목들의 회귀 테스트.

각 케이스에 붙은 문구는 정책 문서가 직접 드는 금지 사례이거나, 그것을
한국어 랜딩페이지에 흔한 형태로 옮긴 것이다. 주석에 근거 조항을 적어 둔다.

**오탐 쪽이 더 중요하다.** 사전점검 도구가 멀쩡한 페이지를 물면 사용자는
결과를 통째로 무시하게 되고, 그 순간 도구는 없는 것만 못하다.
"""

from __future__ import annotations

import pytest

from adpolicy.models import Platform
from adpolicy.policies import POLICY_BY_CODE
from adpolicy.rules import CONTENT_PATTERNS


def codes_for(text: str, platform: Platform = Platform.TIKTOK_ADS) -> set[str]:
    return {
        code for code, pat in CONTENT_PATTERNS
        if platform in POLICY_BY_CODE[code].platforms and pat.search(text)
    }


# ---------------------------------------------------------------------------
# 잡아야 하는 것
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    # TikTok 체중 관리: "식단 조절이나 운동 없이 제품만으로 …"
    "굶지 않고 운동 없이 체중이 줄어듭니다",
    "운동 없이 살이 빠지는 원리",
    "식단 조절 없이 감량하세요",
    # Google 신뢰할 수 없는 주장: "특정 기간 내에 … 비현실적인 체중 감량"
    "한 달 만에 15kg 감량",
    "3주 만에 12kg",
    "10kg 감량 보장",
])
def test_unrealistic_weight_claims_are_caught(text):
    assert "TT-WEIGHT-UNREALISTIC" in codes_for(text), text


@pytest.mark.parametrize("text", [
    # TikTok 신체 이미지 — "노골적으로 수치심을 유발"
    "뚱뚱한 몸 때문에 자신감을 잃으셨나요",
    "비만 탓에 늘 위축되셨죠",
    # "특정 외모로 보이면 … 매력적이 되거나 성공할 수 있거나 행복"
    "날씬해지면 인기가 달라집니다",
    "살만 빼면 연애도 취업도 다 풀립니다",
])
def test_body_shaming_is_caught(text):
    assert "TT-BODY-IMAGE" in codes_for(text), text


@pytest.mark.parametrize("text", [
    "비트코인 투자 상담 진행합니다",
    "코인 투자로 시작하세요",
    "암호화폐 거래소 오픈",
    "가상자산 보관 지갑",
])
def test_crypto_is_flagged_for_korea_certification(text):
    assert "RESTRICT-CRYPTO" in codes_for(text), text


@pytest.mark.parametrize("text", [
    # Google 부정 행위 조장이 직접 드는 예시들
    "대리 시험 서비스 문의",
    "논문 대필 상담",
    "리뷰 대행 · 별점 작업",
    "위조 졸업장 제작",
    "카톡 해킹 대행",
])
def test_enabling_dishonest_behavior_is_caught(text):
    assert "PROHIB-ENABLING-DISHONEST" in codes_for(text), text


@pytest.mark.parametrize("text", [
    "전자담배 액상 최저가 판매",
    "권총 부품 판매합니다",
    "전기 충격기 구매 문의",
])
def test_dangerous_products_are_caught(text):
    assert "PROHIB-DANGEROUS" in codes_for(text), text


@pytest.mark.parametrize("text", [
    # Google 데이팅 정책이 한국어 표현을 직접 금지 사례로 든다
    "조건 만남 주선",
    "원조 교제 상담",
    "애인 대행 서비스",
    "에스코트 알바 모집",
])
def test_prohibited_dating_services_are_caught(text):
    assert "RESTRICT-DATING" in codes_for(text), text


@pytest.mark.parametrize("text", [
    # "음주가 건강이나 치료에 도움이 된다고 암시하는 광고"
    "매일 한 잔이면 혈액순환에 좋습니다",
    # "음주로 사회적 … 입지가 강화되거나, 성적 매력이 높아진다"
    "술 한잔이면 자신감이 올라갑니다",
    "폭탄주 무제한",
])
def test_irresponsible_alcohol_claims_are_caught(text):
    assert "RESTRICT-ALCOHOL" in codes_for(text, Platform.GOOGLE_ADS), text


@pytest.mark.parametrize("text", [
    "3주 만에 12kg 빠졌어요",
    "체험담: 두 달에 8kg",
])
def test_result_claiming_testimonials_are_caught(text):
    assert "MIS-FAKE-TESTIMONIAL" in codes_for(text), text


@pytest.mark.parametrize("text", [
    # TikTok 의료: "'기적' 또는 '비밀이나 치료법을 보유'한 제품임을 주장"
    "기적의 성분이 지방을 녹입니다",
    "만병통치 한방 처방",
    # "제품/서비스가 처방약과 동등하거나 더 우수하다는 암시"
    "약보다 낫습니다",
])
def test_miracle_and_better_than_prescription_claims_are_caught(text):
    assert "RESTRICT-HEALTHCARE" in codes_for(text), text


# ---------------------------------------------------------------------------
# 물면 안 되는 것 — 여기가 더 중요하다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "code"), [
    # 체중 맥락 없이 '운동 없이'만 있는 정상 문구
    ("운동 없이 편안하게 쓰는 안마의자", "TT-WEIGHT-UNREALISTIC"),
    ("계단 오르기 없이 바로 3층까지", "TT-WEIGHT-UNREALISTIC"),
    # 기간+무게가 붙어도 '만에'가 없으면 감량 주장이 아니다
    ("6개월 5kg 원두 정기배송", "TT-WEIGHT-UNREALISTIC"),
    ("3개월 무이자 할부, 총 12kg 상자", "TT-WEIGHT-UNREALISTIC"),
    # 음식·재료 묘사
    ("통통한 식감의 새우살", "TT-BODY-IMAGE"),
    ("살짝 마르면 바삭해집니다", "TT-BODY-IMAGE"),
    # '코인'이 붙은 정상 업종
    ("코인노래방 24시간 운영", "RESTRICT-CRYPTO"),
    ("코인세탁방 건조기 이용 안내", "RESTRICT-CRYPTO"),
    # 금연·예방 캠페인을 담배 광고로 보면 안 된다
    ("금연 클리닉 무료 상담", "PROHIB-DANGEROUS"),
    ("청소년 흡연 예방 교육 자료", "PROHIB-DANGEROUS"),
    ("담배 끊기 성공 사례", "PROHIB-DANGEROUS"),
    # 절주 캠페인이 주류 광고로 잡히면 정반대다
    ("술을 줄이면 건강에 좋습니다", "RESTRICT-ALCOHOL"),
    ("음주를 끊으면 혈액순환에 도움이 됩니다", "RESTRICT-ALCOHOL"),
    # 재고·중량 문구
    ("재고가 5kg 줄었습니다", "MIS-FAKE-TESTIMONIAL"),
    ("배송 상자 무게 3kg", "MIS-FAKE-TESTIMONIAL"),
    # 후원·협찬
    ("스폰서십 문의는 메일로", "RESTRICT-DATING"),
    # 기존 함정도 계속 지켜져야 한다
    ("이웃집 토토로 굿즈", "RESTRICT-GAMBLING"),
    ("정품 급속 충전기", "PROHIB-COUNTERFEIT"),
])
def test_normal_korean_copy_is_not_flagged(text, code):
    assert code not in codes_for(text, Platform.GOOGLE_ADS), f"{code} 오탐: {text}"
    assert code not in codes_for(text, Platform.TIKTOK_ADS), f"{code} 오탐: {text}"


# ---------------------------------------------------------------------------
# 카탈로그 자체의 정합성
# ---------------------------------------------------------------------------


def test_every_pattern_code_exists_in_the_catalog():
    """패턴만 추가하고 정책 항목을 빠뜨리면 KeyError로 /v1/check가 500이 된다."""
    for code, _ in CONTENT_PATTERNS:
        assert code in POLICY_BY_CODE, code


def test_platform_specific_codes_are_not_offered_to_the_other_platform():
    """TikTok 전용 항목이 Google 점검에 나오면 사용자가 헛수고한다."""
    for code in ("TT-BODY-IMAGE", "TT-YOUTH-PRESSURE"):
        assert POLICY_BY_CODE[code].platforms == (Platform.TIKTOK_ADS,)


def test_before_after_applies_to_both_platforms():
    """Google도 클릭베이트 조항에서 '전후 비교' 이미지를 직접 금지한다 —
    TikTok 전용으로 두면 Google 점검에서 통째로 빠진다."""
    p = POLICY_BY_CODE["TT-BEFORE-AFTER"]
    assert Platform.GOOGLE_ADS in p.platforms and Platform.TIKTOK_ADS in p.platforms
    assert "클릭베이트" in p.official_name
