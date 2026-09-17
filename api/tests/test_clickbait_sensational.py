"""클릭베이트 — 선정적 유인 갈래.

카탈로그(policies.py)의 MIS-CLICKBAIT 설명은 "클릭베이트 기법이나 **선정적
문구**"라고 적고 있는데, 규칙은 오래도록 허위 희소성('단 1자리 남음')만
구현하고 있었다. 평가 하네스의 `clickbait` 케이스가 이 누락을 잡아냈다.

아래 테스트는 **옛 패턴에서 전부 실패한다.** 옛 패턴은 다음뿐이었다:

    단\\s*\\d+\\s*(자리|명)\\s*남|오늘만(?![가-힣])|마감\\s*임박|지금\\s*아니면
"""

from __future__ import annotations

import pytest

from adpolicy.models import PageSnapshot, Platform
from adpolicy.rules import check_content_patterns


def snap(text: str) -> PageSnapshot:
    return PageSnapshot(
        url="https://example.com/lp", final_url="https://example.com/lp",
        status_code=200, title="t", text=text,
    )


def codes(text: str, ad_copy: str = "") -> set[str]:
    return {
        f.code for f in
        check_content_patterns(snap(text), ad_copy, Platform.GOOGLE_ADS)
    }


# --- 잡아야 하는 것 (전부 옛 패턴에서는 통과하지 못한다) ----------------------

@pytest.mark.parametrize("text", [
    "충격! 이것만 알면 됩니다",
    "충격적인 사실을 공개합니다",
    "의사들이 숨긴 비밀",
    "전문가가 알려주지 않는 방법",
    "병원에서 감추는 진실",
    "당신만 모르는 절세 방법",
    "아무도 알려주지 않는 이야기",
    "클릭하지 않으면 후회합니다",
    "이것만 알면 모든 게 해결됩니다",
])
def test_sensational_hooks_are_detected(text):
    assert "MIS-CLICKBAIT" in codes(text), f"못 잡음: {text}"


# --- 기존 갈래는 그대로 살아 있어야 한다 -------------------------------------

@pytest.mark.parametrize("text", [
    "단 3자리 남았습니다",
    "오늘만 특가",
    "마감 임박",
    "지금 아니면 기회가 없습니다",
])
def test_scarcity_hooks_still_detected(text):
    assert "MIS-CLICKBAIT" in codes(text)


# --- 잡으면 안 되는 것 (넓힌 패턴이 만들 수 있는 오탐) ------------------------

@pytest.mark.parametrize("text", [
    # '충격'이 낱말로만 쓰인 정상 문장 — 갈고리 형태가 아니다
    "충격 흡수 소재를 사용했습니다",
    "충격에 강한 케이스입니다",
    # 의사가 등장하지만 '숨긴'이 아니다
    "의사가 알려주는 올바른 수면 습관",
    "전문가가 추천하는 관리법",
    "약사가 설명하는 복용 방법",
    # 주석에 남아 있는 과거 오탐 — '오늘 만든'
    "오늘 만든 빵만 판매합니다",
    "오늘 만나보세요",
    # '이것만 알면' 뒤에 해결/끝이 없으면 갈고리가 아니다
    "이것만 알면 기초는 충분합니다",
])
def test_legitimate_phrases_are_not_flagged(text):
    assert "MIS-CLICKBAIT" not in codes(text), f"오탐: {text}"


def test_catalog_description_matches_implementation():
    """카탈로그가 약속한 범위를 규칙이 실제로 덮는지 확인한다.
    이 둘이 어긋난 것이 애초의 문제였다."""
    from adpolicy.policies import POLICY_BY_CODE
    desc = POLICY_BY_CODE["MIS-CLICKBAIT"].description
    assert "선정적" in desc
    assert "MIS-CLICKBAIT" in codes("의사들이 숨긴 비밀")   # 선정적
    assert "MIS-CLICKBAIT" in codes("단 1자리 남음")        # 허위 희소성
