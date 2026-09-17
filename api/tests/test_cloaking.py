"""클로킹 **탐지** 테스트.

이 모듈이 검증하는 것은 "클로킹이 일어나고 있는지 잡아내는가"이다.
네트워크 없이, 스냅샷을 직접 구성해 판정 로직만 확인한다.
"""

from __future__ import annotations

import pytest

from adpolicy import cloaking
from adpolicy.cloaking import (
    CLIENT_PROFILES,
    analyze_divergence,
    detect_auto_download,
    detect_ua_sniffing,
    similarity,
)
from adpolicy.models import PageSnapshot


def snap(text: str, *, error: str = "") -> PageSnapshot:
    return PageSnapshot(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200 if not error else 403,
        text=text,
        fetch_error=error,
    )


LONG_A = "저희 제품은 친환경 소재로 만들어졌습니다. " * 20
LONG_B = "지금 바로 카지노에 가입하고 보너스를 받으세요. " * 20


# --- 프로필 구성 -----------------------------------------------------------

def test_profiles_do_not_impersonate_search_crawlers():
    """크롤러를 사칭하지 않는다 — 탐지에 필요도 없고 그 자체로 회색지대다."""
    for ua in CLIENT_PROFILES.values():
        low = ua.lower()
        assert "googlebot" not in low
        assert "adsbot" not in low
        assert "bingbot" not in low


def test_bot_profile_identifies_itself():
    assert "adpolicy-precheck" in CLIENT_PROFILES["bot"].lower()


# --- 유사도 ----------------------------------------------------------------

def test_identical_text_is_fully_similar():
    assert similarity("같은 내용", "같은 내용") == 1.0


def test_whitespace_difference_stays_similar():
    assert similarity("가 나 다", "가  나\n다") > 0.95


def test_completely_different_text_is_dissimilar():
    assert similarity(LONG_A, LONG_B) < 0.6


def test_empty_vs_content_is_zero():
    assert similarity("", "내용 있음") == 0.0


# --- 분기 판정 --------------------------------------------------------------

def test_same_content_across_profiles_is_clean():
    snaps = {"desktop": snap(LONG_A), "mobile": snap(LONG_A), "bot": snap(LONG_A)}
    severity, ratio, _ = analyze_divergence(snaps)
    assert severity == ""
    assert ratio > 0.99


def test_bot_sees_different_content_is_blocked():
    snaps = {"desktop": snap(LONG_A), "mobile": snap(LONG_A), "bot": snap(LONG_B)}
    severity, ratio, evidence = analyze_divergence(snaps)
    assert severity == "block"
    assert ratio < 0.6
    assert evidence


def test_bot_blocked_while_browser_ok_is_flagged():
    """WAF가 봇만 차단하는 흔한 사고 — 의도가 없어도 심사에서는 같은 결과다."""
    snaps = {"desktop": snap(LONG_A), "bot": snap("", error="HTTP 403")}
    severity, _, evidence = analyze_divergence(snaps)
    assert severity == "block"
    assert "403" in evidence


def test_short_pages_are_not_compared():
    """본문이 너무 짧으면 유사도가 불안정하므로 판정하지 않는다."""
    snaps = {"desktop": snap("짧음"), "bot": snap("다름")}
    severity, _, _ = analyze_divergence(snaps)
    assert severity == ""


def test_single_usable_profile_yields_no_verdict():
    snaps = {"desktop": snap(LONG_A), "bot": snap("", error="타임아웃")}
    # desktop만 성공했지만 bot 실패는 위 규칙에서 이미 처리된다
    severity, _, _ = analyze_divergence(snaps)
    assert severity == "block"


# --- 정적 신호 --------------------------------------------------------------

@pytest.mark.parametrize("html", [
    # UA를 보고 **내용을 바꾼다**. 이게 분기다.
    "<script>if (navigator.userAgent.match(/bot/i)) "
    "{ document.body.innerHTML = '준비중'; }</script>",
    "<script>if (/bot/i.test(navigator.userAgent)) "
    "{ location.replace('https://other.example.com/'); }</script>",
    # 서버 코드가 응답에 그대로 노출된 경우
    "<?php if (strpos($_SERVER['HTTP_USER_AGENT'], 'Google')) {} ?>",
])
def test_ua_sniffing_detected(html):
    assert detect_ua_sniffing(html)


@pytest.mark.parametrize("html", [
    # 읽기만 한다. GA 스니펫·반응형 처리에 다 들어 있는 코드다.
    "<script>const ua = navigator.userAgent;</script>",
    "<script>if (navigator.userAgent.match(/bot/i)) { showOther(); }</script>",
])
def test_merely_reading_the_ua_is_not_branching(html):
    """예전에는 이것도 경고였다. 그러면 거의 모든 실사이트가 걸린다."""
    assert not detect_ua_sniffing(html)


def test_ua_sniffing_absent_in_plain_page():
    assert detect_ua_sniffing("<html><body><p>평범한 페이지</p></body></html>") == ""


@pytest.mark.parametrize("html", [
    '<meta http-equiv="refresh" content="0;url=/setup.exe">',
    '<script>location.href = "https://cdn.example.com/app.apk";</script>',
])
def test_auto_download_detected(html):
    assert detect_auto_download(html)


def test_auto_download_absent_for_normal_links():
    html = '<a href="/guide.pdf">가이드 보기</a>'
    assert detect_auto_download(html) == ""


def test_googlebot_only_block_is_not_an_adsbot_block():
    """SEO 목적으로 Googlebot만 막은 사이트는 광고 심사가 막힌 게 아니다.

    AdsBot-Google은 전역 `*` 규칙도 googlebot 규칙도 따르지 않는다.
    여기에 googlebot을 넣어두면 멀쩡한 사이트가 block으로 잡힌다.
    """
    assert "googlebot" not in cloaking.AD_CRAWLERS
    assert "adsbot-google" in cloaking.AD_CRAWLERS


def test_bot_getting_a_blank_200_is_flagged():
    """이 모듈이 잡겠다고 한 대표 시나리오(JS 전용 렌더링, 대기 페이지).

    짧다는 이유로 비교 대상에서 빠지면 desktop·mobile만 남아 '차이 없음'이 된다.
    """
    long_text = "정상 콘텐츠입니다. " * 40

    def snap(text: str) -> PageSnapshot:
        return PageSnapshot(url="u", final_url="u", status_code=200, text=text)

    severity, _, evidence = analyze_divergence(
        {"desktop": snap(long_text), "mobile": snap(long_text), "bot": snap("")}
    )
    assert severity == "block"
    assert "봇에는" in evidence


def test_identical_profiles_still_pass():
    long_text = "정상 콘텐츠입니다. " * 40

    def snap(text: str) -> PageSnapshot:
        return PageSnapshot(url="u", final_url="u", status_code=200, text=text)

    severity, ratio, _ = analyze_divergence(
        {"desktop": snap(long_text), "mobile": snap(long_text), "bot": snap(long_text)}
    )
    assert severity == "" and ratio == 1.0
