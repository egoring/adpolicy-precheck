"""본문을 서버에서 받아 채우는 구조, 감춘 스크립트, 심사 후 바꿔치기.

**이게 프로필 비교의 사각지대다.** JS로 콘텐츠를 갈아끼우면 데스크톱·모바일·봇
세 프로필이 전부 똑같은 빈 껍데기를 받는다. 유사도 100%라 "정상"으로 나온다.

여기서 증명할 수 있는 건 "바꿔치기했다"가 아니라 **"바꿔치기할 수 있는 구조이고
심사 대상 본문이 응답에 없다"**까지다. 그 이상을 말하면 거짓이므로, 등급도
올리지 않는다. 실제 바꿔치기는 지문 비교로만 잡을 수 있다.
"""

from __future__ import annotations

import pytest

from adpolicy import cloaking, scoring
from adpolicy.models import Enforcement, PageSnapshot
from adpolicy.policies import POLICY_BY_CODE

SHELL = """<!doctype html><html><head><title>이벤트</title></head><body>
<div id="root"></div>
<script>
fetch('/api/getValue?id=12').then(r => r.json())
  .then(d => { document.getElementById('root').innerHTML = d.html; });
</script>
</body></html>"""


def snap(text: str = "", **kw) -> PageSnapshot:
    return PageSnapshot(url="https://ex.com/", final_url="https://ex.com/",
                        status_code=200, text=text, **kw)


# ---------------------------------------------------------------------------
# 서버에서 받아 채우는 구조
# ---------------------------------------------------------------------------


def test_empty_shell_that_pulls_its_body_from_the_server_is_caught():
    ev = cloaking.detect_server_rendered_body(SHELL, snap(""))
    assert "서버에서 받아" in ev
    # 어느 주소를 부르는지까지 보여줘야 사용자가 확인할 수 있다
    assert "getValue" in ev


@pytest.mark.parametrize("call", [
    "fetch('/api/getContent')",
    "new XMLHttpRequest()",
    "$.ajax({url:'/proc.php'})",
    "axios.get('/data.php')",
])
def test_common_fetch_styles_are_recognized(call):
    html = f"<script>{call}; document.body.innerHTML = x;</script>"
    assert cloaking.detect_server_rendered_body(html, snap("")) != ""


@pytest.mark.parametrize("write", [
    "el.innerHTML = d",
    "document.write(d)",
    "el.insertAdjacentHTML('beforeend', d)",
    "$('#root').html(d)",
])
def test_common_dom_write_styles_are_recognized(write):
    html = f"<script>fetch('/x').then(d => {{ {write}; }});</script>"
    assert cloaking.detect_server_rendered_body(html, snap("")) != ""


def test_a_page_whose_body_is_already_in_the_response_is_left_alone():
    """본문이 응답에 있으면 나중에 뭘 더 붙이든 심사는 제대로 된다.

    요즘 사이트는 대부분 fetch + innerHTML을 쓴다. 그것만 보면 전부 걸린다.
    """
    body = "제품 설명입니다. " * 80
    assert cloaking.detect_server_rendered_body(SHELL, snap(body)) == ""


def test_a_normal_shop_page_that_lazy_loads_only_its_reviews_is_not_flagged():
    """실제로 여기서 오탐이 났다.

    제품 설명은 HTML에 있고 후기만 fetch로 붙이는 건 아주 흔한 구조다.
    기준을 600자로 뒀더니 본문 400자짜리 멀쩡한 쇼핑몰이 걸렸다.
    """
    body = (
        "스테인리스 304 이중 진공 구조입니다. 뜨거운 음료는 6시간, 차가운 음료는 "
        "12시간까지 온도를 유지합니다. 뚜껑은 분리 세척이 가능하고 식기세척기 "
        "상단칸을 쓸 수 있습니다. 용량 500ml, 무게 310g, 높이 21cm. 색상은 "
        "매트 블랙·아이보리·세이지·네이비 네 가지입니다. 배송비는 3,000원이며 "
        "5만원 이상 무료입니다. 단순 변심 교환·반품은 수령 후 7일 이내 가능하고 "
        "왕복 배송비 6,000원이 부과됩니다. 제품 하자는 배송비 없이 교환해 드립니다. "
        "주식회사 온도상사 | 대표 박지훈 | 사업자등록번호 123-45-67890 | 02-123-4567"
    )
    html = """<div id="reviews"></div><script>
    fetch('/api/reviews').then(r => r.json())
      .then(d => { document.getElementById('reviews').innerHTML = d.html; });
    </script>"""
    # 예전 기준(600자)이었다면 걸렸을 길이. 지금 기준(300자)에서는 안 걸린다.
    assert 300 < len(body) < 600
    assert cloaking.detect_server_rendered_body(html, snap(body)) == ""


def test_a_true_shell_is_still_caught_after_tightening():
    """기준을 조이면서 잡아야 할 것까지 놓치면 의미가 없다."""
    assert cloaking.detect_server_rendered_body(SHELL, snap("이벤트 안내")) != ""


def test_analytics_calls_without_a_dom_write_are_not_flagged():
    """통계 전송·폼 제출은 받아온 걸 화면에 꽂지 않는다."""
    html = "<script>fetch('/collect', {method:'POST', body: payload});</script>"
    assert cloaking.detect_server_rendered_body(html, snap("")) == ""


def test_rendering_without_a_server_call_is_not_flagged():
    """정적 템플릿 조립은 서버가 내용을 정하는 게 아니다."""
    html = "<script>document.getElementById('x').innerHTML = '<b>안녕</b>';</script>"
    assert cloaking.detect_server_rendered_body(html, snap("")) == ""


def test_this_finding_never_claims_account_suspension():
    """여기서 증명되는 건 '구조'까지다. 그걸로 정지를 말하면 거짓이 된다."""
    p = POLICY_BY_CODE["ABUSE-SERVER-RENDERED-BODY"]
    assert p.enforcement is Enforcement.DISAPPROVE
    assert "직접 확인" in p.description or "정상일 수 있" in p.description


# ---------------------------------------------------------------------------
# 감춘 스크립트
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("html", "want"), [
    ("<script>eval(atob('aGVsbG8='))</script>", "eval"),
    ("<script>new Function(atob(p))()</script>", "Function"),
    ("<script>document.write(unescape('%3Cdiv%3E'))</script>", "document.write"),
    ("<script>var s=String.fromCharCode(" + ",".join(["104"] * 20) + ")</script>",
     "fromCharCode"),
    ("<script>var s='" + "\\x61" * 45 + "'</script>", "이스케이프"),
])
def test_obfuscated_code_is_caught(html, want):
    assert want in cloaking.detect_obfuscated_script(html)


@pytest.mark.parametrize("html", [
    # 정상적인 base64·인코딩 사용은 감춘 게 아니다
    "<script>const img = atob(raw);</script>",
    "<script>const url = decodeURIComponent(q);</script>",
    "<script>String.fromCharCode(65, 66, 67)</script>",
    "<script>const key = '\\x41\\x42';</script>",
])
def test_ordinary_encoding_use_is_not_obfuscation(html):
    assert cloaking.detect_obfuscated_script(html) == ""


def test_obfuscation_is_a_strike_not_an_instant_suspension():
    """정책 문서가 '사전 경고 없이 바로 정지되지는 않습니다'라고 명시한 항목이다."""
    assert POLICY_BY_CODE["ABUSE-OBFUSCATED-SCRIPT"].enforcement is Enforcement.STRIKE


# ---------------------------------------------------------------------------
# 심사 후 바꿔치기 — 지문 비교
# ---------------------------------------------------------------------------


def test_the_same_page_gives_the_same_fingerprint():
    a = snap("원금 보장 확정 수익", title="투자")
    b = snap("원금 보장 확정 수익", title="투자")
    assert cloaking.content_fingerprint(a) == cloaking.content_fingerprint(b)


def test_whitespace_and_case_changes_do_not_trip_the_alarm():
    """줄바꿈 정리나 오타 수정으로 경보가 뜨면 아무도 안 쓰게 된다."""
    a = snap("원금 보장  확정 수익", title="투자")
    b = snap("원금 보장 확정 수익\n", title="투자")
    assert cloaking.content_fingerprint(a) == cloaking.content_fingerprint(b)


def test_swapped_body_changes_the_fingerprint():
    before = snap("보험 상담 안내입니다", title="보험")
    after = snap("원금 보장 확정 수익 월 300만원", title="보험")
    assert cloaking.content_fingerprint(before) != cloaking.content_fingerprint(after)


def test_swapping_only_the_banner_text_is_also_caught():
    """본문은 그대로 두고 배너만 갈아끼우는 게 국내에서 더 흔하다."""
    before = snap("상담 안내", ocr_text="정상적인 안내 문구")
    after = snap("상담 안내", ocr_text="원금 100% 보장 확정 수익")
    assert cloaking.content_fingerprint(before) != cloaking.content_fingerprint(after)


def test_a_content_change_is_an_account_level_event():
    """TikTok이 '캠페인 생성 후 랜딩 페이지 변경'을 계정 정지 사유로 명시한다."""
    p = POLICY_BY_CODE["ABUSE-CONTENT-CHANGED"]
    assert p.enforcement is Enforcement.SUSPEND


def test_the_change_finding_lifts_the_account_risk_level():
    from adpolicy.models import Finding, Source

    p = POLICY_BY_CODE["ABUSE-CONTENT-CHANGED"]
    f = Finding(code=p.code, title=p.title, severity=p.severity,
                enforcement=p.enforcement, source=Source.RULE,
                detail=p.description, evidence="abc → def", fix=p.fix)
    risk = scoring.account_risk([f])
    assert risk.level is Enforcement.SUSPEND and risk.suspend_count == 1
