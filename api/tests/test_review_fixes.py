"""코드 리뷰(docs/개선사항.md)에서 지적된 항목들.

각 테스트는 **고치기 전 코드에서 실패하도록** 썼다. 그래야 "고쳤다"는 말에
근거가 생긴다. 주석의 A-4, B-2 같은 번호는 그 문서의 항목 번호다.
"""

from __future__ import annotations

import pytest

from adpolicy import cloaking, rules
from adpolicy.models import PageSnapshot

# ---------------------------------------------------------------------------
# A-4. UA를 읽는다는 것만으로 지적하면 거의 모든 사이트가 걸린다
# ---------------------------------------------------------------------------

GA_SNIPPET = """
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('config', 'G-XXXX', {user_agent: navigator.userAgent});
</script>
"""

RESPONSIVE = """
<script>
  var isMobile = /iPhone|Android/i.test(navigator.userAgent);
  if (isMobile) { document.body.classList.add('mobile'); }
</script>
"""

REAL_BRANCHING = """
<script>
  if (/bot|crawler|spider/i.test(navigator.userAgent)) {
    document.body.innerHTML = '<h1>준비 중입니다</h1>';
  }
</script>
"""

REDIRECT_BRANCHING = """
<script>
  if (navigator.userAgent.indexOf('AdsBot') === -1) {
    location.replace('https://real-offer.example.com/');
  }
</script>
"""


@pytest.mark.parametrize("html", [GA_SNIPPET, RESPONSIVE])
def test_merely_reading_the_user_agent_is_not_a_finding(html):
    """GA 스니펫 하나로 경고가 뜨면 아무도 이 도구를 안 믿는다."""
    assert cloaking.detect_ua_sniffing(html) == ""


@pytest.mark.parametrize("html", [REAL_BRANCHING, REDIRECT_BRANCHING])
def test_reading_it_and_then_changing_the_page_is(html):
    evidence = cloaking.detect_ua_sniffing(html)
    assert evidence and "navigator.userAgent" in evidence


def test_a_class_toggle_is_not_content_branching():
    """클래스만 붙이는 건 반응형 처리다. 콘텐츠가 바뀌는 게 아니다."""
    assert cloaking.detect_ua_sniffing(RESPONSIVE) == ""


def test_the_read_and_the_action_must_be_in_the_same_script():
    """페이지 어딘가에 UA가, 다른 어딘가에 innerHTML이 있다고 분기는 아니다."""
    html = GA_SNIPPET + "<script>document.querySelector('#x').innerHTML = '안녕';</script>"
    assert cloaking.detect_ua_sniffing(html) == ""


# ---------------------------------------------------------------------------
# A-5. www 리디렉션은 정상 구성이다
# ---------------------------------------------------------------------------


def snap(url: str, final: str, **kw) -> PageSnapshot:
    base = {"status_code": 200, "text": "본문 " * 200}
    base.update(kw)
    return PageSnapshot(url=url, final_url=final, **base)


def codes(findings) -> set[str]:
    return {f.code for f in findings}


@pytest.mark.parametrize(("start", "end"), [
    ("https://example.com/lp", "https://www.example.com/lp"),
    ("https://www.example.com/lp", "https://example.com/lp"),
    ("https://shop.example.com/lp", "https://example.com/lp"),
    ("https://example.co.kr/lp", "https://www.example.co.kr/lp"),
])
def test_moving_within_the_same_site_is_not_a_mismatch(start, end):
    assert "DEST-MISMATCH" not in codes(rules.check_technical(snap(start, end)))


@pytest.mark.parametrize(("start", "end"), [
    ("https://example.com/lp", "https://other.com/lp"),
    # 국내 도메인은 co.kr을 접미사로 알아야 구분된다
    ("https://livelogin.co.kr/lp", "https://livetopic.co.kr/lp"),
])
def test_moving_to_another_site_still_is(start, end):
    assert "DEST-MISMATCH" in codes(rules.check_technical(snap(start, end)))


# ---------------------------------------------------------------------------
# A-7. 봇 요청 한 번 실패했다고 계정 정지급으로 확정하지 않는다
# ---------------------------------------------------------------------------


def profile(text: str = "본문 " * 200, error: str = "") -> PageSnapshot:
    return PageSnapshot(url="https://ex.com", final_url="https://ex.com",
                        status_code=200 if not error else 0,
                        text=text, fetch_error=error)


def test_a_timeout_on_the_bot_profile_is_only_a_warning():
    """순간 장애와 '봇을 막았다'는 다른 사건이다."""
    sev, _ratio, evidence = cloaking.analyze_divergence({
        "desktop": profile(), "bot": profile("", "응답 시간 초과")})
    assert sev == "warn"
    assert "일시적" in evidence


def test_an_explicit_refusal_to_the_bot_is_still_a_block():
    sev, _ratio, _e = cloaking.analyze_divergence({
        "desktop": profile(), "bot": profile("", "HTTP 403")})
    assert sev == "block"


@pytest.mark.asyncio
async def test_a_failed_bot_fetch_is_retried_once(monkeypatch):
    calls: list[str] = []

    async def fake(url: str, ua: str):
        calls.append(ua)
        if ua == cloaking.CLIENT_PROFILES["bot"] and calls.count(ua) == 1:
            return profile("", "응답 시간 초과"), ""
        return profile(), "<html></html>"

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    monkeypatch.setattr(cloaking, "assert_safe_url", lambda url: None)
    snaps, _raws = await cloaking.probe_profiles("https://ex.com")

    assert calls.count(cloaking.CLIENT_PROFILES["bot"]) == 2
    assert not snaps["bot"].fetch_error   # 재시도가 성공했으면 지적하지 않는다


@pytest.mark.asyncio
async def test_the_profiles_are_fetched_at_the_same_time(monkeypatch):
    """B-3. 순차로 돌면 응답 시간이 프로필 수만큼 곱해진다."""
    import asyncio

    running, peak = 0, 0

    async def fake(url: str, ua: str):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return profile(), "<html></html>"

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    monkeypatch.setattr(cloaking, "assert_safe_url", lambda url: None)
    await cloaking.probe_profiles("https://ex.com")
    assert peak == len(cloaking.CLIENT_PROFILES)


# ---------------------------------------------------------------------------
# B-1. robots.txt — 경로 단위 차단과 그룹형 레코드
# ---------------------------------------------------------------------------


def test_a_path_level_disallow_on_the_landing_page_counts():
    """`Disallow: /landing`이 랜딩을 막고 있는데 '/'만 보면 전부 놓친다."""
    body = "User-agent: AdsBot-Google\nDisallow: /landing\n"
    blocked, evidence = cloaking._robots_blocks(body, "/landing/spring")
    assert blocked and "/landing" in evidence


def test_an_unrelated_path_is_not_blocked():
    body = "User-agent: AdsBot-Google\nDisallow: /admin\n"
    blocked, _e = cloaking._robots_blocks(body, "/landing")
    assert not blocked


def test_a_longer_allow_beats_the_disallow():
    body = ("User-agent: AdsBot-Google\n"
            "Disallow: /landing\n"
            "Allow: /landing/public\n")
    blocked, _e = cloaking._robots_blocks(body, "/landing/public/a")
    assert not blocked


def test_grouped_user_agent_lines_all_get_the_rule():
    """User-agent가 연속으로 오면 규칙은 그 전부에 적용된다.

    마지막 한 줄만 기억하면 AdsBot에 걸린 규칙을 통째로 놓친다.
    """
    body = ("User-agent: AdsBot-Google\n"
            "User-agent: Bingbot\n"
            "Disallow: /\n")
    blocked, _e = cloaking._robots_blocks(body, "/lp")
    assert blocked


def test_a_rule_for_someone_else_does_not_apply_to_us():
    body = ("User-agent: Bingbot\nDisallow: /\n\n"
            "User-agent: AdsBot-Google\nAllow: /\n")
    blocked, _e = cloaking._robots_blocks(body, "/lp")
    assert not blocked


def test_the_global_star_does_not_bind_adsbot():
    """AdsBot-Google은 `User-agent: *`를 따르지 않는다. 이건 예전부터의 규칙이다."""
    blocked, _e = cloaking._robots_blocks("User-agent: *\nDisallow: /\n", "/lp")
    assert not blocked


def test_an_empty_disallow_means_everything_is_allowed():
    body = "User-agent: AdsBot-Google\nDisallow:\n"
    blocked, _e = cloaking._robots_blocks(body, "/lp")
    assert not blocked


# ---------------------------------------------------------------------------
# B-2. 조사가 붙은 채로 비교하면 같은 말이 안 맞는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("word", "stem"), [
    ("원두를", "원두"), ("배송을", "배송"), ("가격이", "가격"),
    ("매장에서", "매장"), ("고객에게", "고객"), ("로스팅은", "로스팅"),
])
def test_particles_are_stripped(word, stem):
    assert stem in rules._keywords(word)


@pytest.mark.parametrize("word", ["커피", "주문", "무료"])
def test_a_word_that_merely_ends_like_a_particle_survives(word):
    """'주문'의 '문'을 조사로 오해해 '주'만 남기면 안 된다."""
    assert word in rules._keywords(word)


def test_a_matching_ad_and_page_are_not_called_unrelated():
    """조사 때문에 정상 광고가 '관련성 불명확'으로 걸리던 사례."""
    ad = "갓 볶은 원두를 무료 배송으로 받아보세요"
    page = PageSnapshot(
        url="https://ex.com", final_url="https://ex.com", status_code=200,
        title="원두 정기배송",
        text="신선한 원두 정기 배송 서비스입니다. 배송 비용은 무료이며 "
             "주문 다음 날 로스팅한 원두가 출발합니다. " + "본문 " * 100,
    )
    assert "MIS-UNCLEAR-RELEVANCE" not in codes(rules.check_ad_page_match(page, ad))


# ---------------------------------------------------------------------------
# B-4. 스스로 변하는 페이지를 프로필 차이로 오해하지 않는다
# ---------------------------------------------------------------------------


def test_profile_difference_within_the_pages_own_noise_is_ignored():
    a, b = "여름 특가 " * 100, "가을 신상 " * 100
    # 잡음(자기 유사도)이 이미 낮으면 프로필 간 차이도 그 탓일 수 있다
    sev, _ratio, _e = cloaking.analyze_divergence(
        {"desktop": profile(a), "mobile": profile(b)}, noise=0.2)
    assert sev == ""


def test_a_real_divergence_still_reports_with_the_noise_shown():
    sev, _ratio, evidence = cloaking.analyze_divergence(
        {"desktop": profile("정상 쇼핑몰 본문 " * 100),
         "mobile": profile("원금 보장 수익 " * 100)}, noise=0.99)
    assert sev == "block"
    assert "같은 프로필끼리는" in evidence


# ---------------------------------------------------------------------------
# B-5. 사업자 정보는 거래하는 페이지에 있어야 하는 것이다
# ---------------------------------------------------------------------------


def info_page(text: str, **kw) -> PageSnapshot:
    base = {"url": "https://ex.com", "final_url": "https://ex.com",
            "status_code": 200, "text": text}
    base.update(kw)
    return PageSnapshot(**base)


def test_an_informational_page_is_not_asked_for_business_details():
    page = info_page("원두 보관법을 정리했습니다. 서늘한 곳에 두세요. " + "본문 " * 200)
    found = codes(rules.check_absence(page, ""))
    assert "MIS-BUSINESS-IDENTITY" not in found


def test_a_page_that_sells_still_is():
    page = info_page("지금 구매하세요. 가격 29,000원. " + "본문 " * 200)
    found = codes(rules.check_absence(page, ""))
    assert "MIS-BUSINESS-IDENTITY" in found


def test_a_page_that_collects_personal_data_still_is():
    page = info_page("상담 신청서" + "본문 " * 200, has_form=True,
                     form_input_types=["tel"], form_text="연락처를 남겨주세요")
    found = codes(rules.check_absence(page, ""))
    assert "MIS-BUSINESS-IDENTITY" in found


def test_a_selling_page_with_contact_details_is_fine():
    page = info_page("지금 구매하세요. 29,000원. 문의 02-1234-5678 " + "본문 " * 200)
    found = codes(rules.check_absence(page, ""))
    assert "MIS-BUSINESS-IDENTITY" not in found


# ---------------------------------------------------------------------------
# 유사도 자체가 무너지던 문제 (검증 중 발견)
#
# difflib.SequenceMatcher는 기본이 autojunk=True다. 200자가 넘는 쪽에서 1%
# 넘게 나오는 요소를 '잡음'으로 빼는데, 상품 목록·후기처럼 같은 구조가
# 반복되는 페이지는 거의 모든 글자가 그 조건에 걸린다. 그 결과 90% 닮은 두
# 페이지가 2%로 나오고, 멀쩡한 쇼핑몰이 계정 정지급으로 보고됐다.
# ---------------------------------------------------------------------------


def test_repetitive_pages_are_not_falsely_different():
    a = "신선한 원두를 매주 보내드립니다. 가격은 29,000원입니다. 문의 02-1234-5678 " * 20
    b = "신선한 원두를 매주 보내드립니다. 지금 구매하세요. 문의는 채팅으로. " * 20
    assert cloaking.similarity(a, b) > 0.5


def test_the_same_repetitive_page_is_identical_to_itself():
    page = "상품 A 29,000원 장바구니 담기 " * 60
    assert cloaking.similarity(page, page) == 1.0


def test_a_repetitive_page_does_not_become_a_suspension_verdict():
    """이게 실제로 나던 증상이다 — 유사도 3%, [block] ABUSE-CLOAKING.

    두 페이지는 문장 몇 개가 실제로 다르므로 경고까지는 나올 수 있다.
    문제는 그게 **계정 정지급(block)** 으로 보고됐다는 것이다.
    """
    a = profile("신선한 원두를 매주 보내드립니다. 가격 29,000원. 문의 02-1234-5678 " * 20)
    b = profile("신선한 원두를 매주 보내드립니다. 지금 구매하세요. 문의는 채팅으로. " * 20)
    sev, ratio, _e = cloaking.analyze_divergence({"desktop": a, "mobile": b})
    assert sev != "block"
    assert ratio > 0.5   # 고치기 전에는 0.02였다


def test_genuinely_different_content_is_still_caught():
    """잡음을 끈다고 진짜 분기를 놓치면 안 된다."""
    a = profile("정품 등산화 전문몰입니다. 가벼운 트레킹화를 정가에 판매합니다. " * 20)
    b = profile("원금 보장 수익률 300% 확정 지급. 지금 입금하세요. " * 20)
    sev, _ratio, _e = cloaking.analyze_divergence({"desktop": a, "mobile": b})
    assert sev == "block"
