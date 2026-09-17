"""계정 정지 축과, HTML만 보고 잡는 우회 신호들.

광고 하나가 반려되는 것과 계정이 영구 정지되는 것은 광고주에게 완전히 다른
사건이다. 예전에는 둘 다 severity=block으로만 찍혀 구분이 안 됐다.

등급의 근거는 Google 정책 문서에 박혀 있는 정형 문장이다.
  정지급 "사전 경고 없이 즉시 해당 Google Ads 계정을 정지하며 …"
  반려급 "이 정책을 위반해도 사전 경고 없이 바로 계정이 정지되지는 않습니다."

**오탐이 특히 위험하다.** "계정이 정지됩니다"는 무거운 말이라, 근거 없이
띄우면 사용자는 도구를 아예 못 믿게 된다.
"""

from __future__ import annotations

import pytest

from adpolicy import cloaking, scoring
from adpolicy.models import Enforcement, Finding, PageSnapshot, Severity, Source
from adpolicy.policies import POLICY_BY_CODE
from adpolicy.rules import CONTENT_PATTERNS

PATTERNS = [pat for _code, pat in CONTENT_PATTERNS]


def make(code: str, source: Source = Source.RULE) -> Finding:
    p = POLICY_BY_CODE[code]
    return Finding(code=p.code, title=p.title, severity=p.severity,
                   enforcement=p.enforcement, source=source, detail=p.description,
                   evidence="근거", fix=p.fix)


# ---------------------------------------------------------------------------
# 등급 매핑
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", [
    # Google이 '중대한 위반'으로 열거한 10개 중 우리가 탐지하는 것들
    "ABUSE-CLOAKING",                  # 시스템 우회: 클로킹
    "ABUSE-AUTO-REDIRECT",             # 시스템 우회
    "PROHIB-COUNTERFEIT",              # 위조품
    "MIS-UNACCEPTABLE-BUSINESS",       # 허용되지 않는 비즈니스 관행
    "MIS-COORDINATED-DECEPTION",       # 조직적 기만 행위
])
def test_egregious_violations_are_marked_as_immediate_suspension(code):
    assert POLICY_BY_CODE[code].enforcement is Enforcement.SUSPEND


@pytest.mark.parametrize("code", [
    # 3진 아웃(경고 누적) 목록에 이름이 올라 있는 것들
    "PROHIB-ENABLING-DISHONEST",  # 부정 행위 조장
    "PROHIB-DANGEROUS",           # 총기·폭발물·무기·담배·약물
    "MIS-CLICKBAIT",              # 클릭베이트
    "RESTRICT-DATING",            # 대가성 성행위
])
def test_three_strike_policies_are_marked_as_strike(code):
    assert POLICY_BY_CODE[code].enforcement is Enforcement.STRIKE


@pytest.mark.parametrize("code", [
    # 흔한 반려 사유들. 이걸 정지급으로 올리면 사용자를 겁주는 오탐이 된다.
    "MIS-SUPERLATIVE", "DEST-INSUFFICIENT-CONTENT", "RESTRICT-CRYPTO",
    "DATA-NO-PRIVACY-POLICY", "TT-BEFORE-AFTER", "RESTRICT-SEXUAL",
])
def test_ordinary_disapprovals_are_not_escalated(code):
    assert POLICY_BY_CODE[code].enforcement is Enforcement.DISAPPROVE


def test_sexual_content_is_not_confused_with_explicit_pornography():
    """중대한 위반 목록의 '음란물'과 제한 콘텐츠의 '성적인 콘텐츠'는 다른 정책이다.

    '성인용품'을 파는 페이지를 계정 정지급으로 올리면 명백한 오탐이다.
    """
    assert POLICY_BY_CODE["RESTRICT-SEXUAL"].enforcement is Enforcement.DISAPPROVE


# ---------------------------------------------------------------------------
# 두 번째 축 — 계정 정지 위험
# ---------------------------------------------------------------------------


def test_no_suspension_items_reads_as_safe():
    risk = scoring.account_risk([make("MIS-SUPERLATIVE"), make("DEST-UNACCEPTABLE-URL")])
    assert risk.level is Enforcement.DISAPPROVE
    assert risk.suspend_count == 0 and risk.strike_count == 0


def test_a_single_suspension_item_dominates_everything_else():
    """반려 20건보다 정지 1건이 치명적이다. 그 사실이 그대로 드러나야 한다."""
    findings = [make("MIS-SUPERLATIVE") for _ in range(20)]
    findings.append(make("ABUSE-CLOAKING"))
    risk = scoring.account_risk(findings)
    assert risk.level is Enforcement.SUSPEND
    assert risk.suspend_count == 1
    assert "ABUSE-CLOAKING" in risk.codes
    assert "즉시" in risk.note


def test_strike_items_are_reported_as_cumulative_not_immediate():
    risk = scoring.account_risk([make("MIS-CLICKBAIT")])
    assert risk.level is Enforcement.STRIKE
    assert "누적" in risk.note
    # 경고 누적형인데 '즉시 정지'라고 말하면 거짓이다
    assert "즉시 정지" not in risk.note


def test_suspension_outranks_strike():
    risk = scoring.account_risk([make("MIS-CLICKBAIT"), make("PROHIB-COUNTERFEIT")])
    assert risk.level is Enforcement.SUSPEND
    assert risk.strike_count == 1 and risk.suspend_count == 1


def test_a_model_guess_about_an_image_never_claims_suspension():
    """VLM은 인용할 문구가 없어 역검증이 불가능하다.

    그런 추측을 근거로 "계정이 정지됩니다"라고 말할 수는 없다.
    """
    from adpolicy.vision import analyze_images  # noqa: F401  (모듈 로드 확인)

    vlm_finding = Finding(
        code="PROHIB-COUNTERFEIT", title="위조 상품", severity=Severity.WARN,
        enforcement=Enforcement.DISAPPROVE, source=Source.VLM,
        detail="모델 판단", evidence="가방 로고가 이상함",
        image_url="https://ex.com/a.jpg",
    )
    risk = scoring.account_risk([vlm_finding])
    assert risk.level is Enforcement.DISAPPROVE


# ---------------------------------------------------------------------------
# 자동 리디렉션
# ---------------------------------------------------------------------------


def test_meta_refresh_to_another_page_is_caught():
    html = '<meta http-equiv="refresh" content="0; url=https://other.example/lp">'
    assert "other.example" in cloaking.detect_meta_refresh(html, "https://a.example/")


def test_slow_meta_refresh_is_not_a_redirect():
    """30초 뒤 안내 페이지로 넘어가는 건 사용자를 속이는 게 아니다."""
    html = '<meta http-equiv="refresh" content="30; url=https://other.example/">'
    assert cloaking.detect_meta_refresh(html, "https://a.example/") == ""


def test_self_refresh_is_not_a_redirect():
    html = '<meta http-equiv="refresh" content="0; url=https://a.example/">'
    assert cloaking.detect_meta_refresh(html, "https://a.example/") == ""


def test_js_redirect_on_load_is_caught():
    html = '<script>location.replace("https://other.example/go")</script>'
    assert "other.example" in cloaking.detect_js_redirect(html)


def test_a_click_handler_is_not_an_auto_redirect():
    """진입 즉시가 아니라 클릭했을 때 이동하는 건 지극히 정상이다."""
    html = """<script>
    document.querySelector('#buy').addEventListener('click', function () {
        location.href = "https://shop.example/cart";
    });
    </script>"""
    assert cloaking.detect_js_redirect(html) == ""


def test_cross_domain_landing_is_reported():
    hop = cloaking.detect_cross_domain_landing(
        "https://livelogin.co.kr/lp/a/", "https://livetopic.co.kr/tik/b/")
    assert "livelogin.co.kr" in hop and "livetopic.co.kr" in hop


@pytest.mark.parametrize(("start", "end"), [
    ("https://ex.com/a", "https://ex.com/b"),
    ("https://ex.com/a", "https://www.ex.com/a"),      # www는 같은 사이트다
    ("https://ex.com/a", "https://shop.ex.com/a"),     # 서브도메인도 같은 사이트
    ("https://ex.com/a", "https://ex.com/a?utm=x"),
])
def test_same_site_redirects_are_not_reported(start, end):
    assert cloaking.detect_cross_domain_landing(start, end) == ""


# ---------------------------------------------------------------------------
# 숨긴 것들
# ---------------------------------------------------------------------------


def test_hidden_policy_violating_text_is_caught():
    html = '<div style="display:none">지금 신청하면 원금 보장 확정 수익 드립니다</div>'
    assert "원금 보장" in cloaking.detect_hidden_text(html, PATTERNS)


def test_ordinary_hidden_elements_are_left_alone():
    """탭·모달·드롭다운은 어느 사이트에나 있다. 숨긴 것 자체는 위반이 아니다."""
    html = (
        '<div style="display:none">배송 안내: 평일 오후 2시 이전 주문은 당일 출고됩니다</div>'
        '<div style="visibility:hidden">자주 묻는 질문 목록을 여기에 표시합니다</div>'
    )
    assert cloaking.detect_hidden_text(html, PATTERNS) == ""


def test_zero_width_characters_are_caught():
    text = "원​금 보​장 확​정"
    assert "3개" in cloaking.detect_zero_width(text)


def test_one_stray_invisible_character_is_not_flagged():
    """BOM 하나쯤은 편집기가 남긴 것일 수 있다."""
    assert cloaking.detect_zero_width("﻿정상적인 본문입니다") == ""


# ---------------------------------------------------------------------------
# 심사 차단 / 미러링 / 브리지
# ---------------------------------------------------------------------------


def test_full_screen_overlay_with_scroll_lock_is_caught():
    html = """<style>body { overflow: hidden; }</style>
    <div style="position:fixed;width:100%;height:100%;z-index:9999">회원가입 후 이용하세요</div>"""
    assert cloaking.detect_blocking_overlay(html) != ""


def test_a_banner_without_scroll_lock_is_not_an_overlay():
    html = '<div style="position:fixed;width:100%;height:60px">상단 배너</div>'
    assert cloaking.detect_blocking_overlay(html) == ""


def test_full_page_iframe_of_another_domain_is_caught():
    html = '<iframe src="https://other.example/site" width="100%" height="100%"></iframe>'
    assert "other.example" in cloaking.detect_framed_content(html, "https://a.example/")


def test_an_embedded_video_is_not_mirroring():
    html = '<iframe src="https://www.youtube.com/embed/abc" width="560" height="315"></iframe>'
    assert cloaking.detect_framed_content(html, "https://a.example/") == ""


def test_bridge_page_is_caught():
    snap = PageSnapshot(
        url="https://a.example/", final_url="https://a.example/", status_code=200,
        text="잠시 후 이동합니다",
        links=["https://other.example/offer", "https://other.example/signup"],
    )
    assert "외부 링크" in cloaking.detect_bridge_page(snap)


def test_a_normal_page_with_outbound_links_is_not_a_bridge():
    snap = PageSnapshot(
        url="https://a.example/", final_url="https://a.example/", status_code=200,
        text="제품 설명 " * 100,
        links=["https://other.example/ref", "/about", "/contact"],
    )
    assert cloaking.detect_bridge_page(snap) == ""
