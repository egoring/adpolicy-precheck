"""브라우저에서 광고 파라미터를 보고 갈아끼우는 경우.

probe_params는 **서버가** 다른 HTML을 줄 때만 잡는다. 서버는 늘 같은 HTML을
주고 브라우저에서 gclid를 읽어 바꾸면, 파라미터를 어떻게 찔러도 응답이 똑같아
유사도 100%가 나온다. 실제로 그렇게 나왔고, 그래서 이 파일이 생겼다.

**오탐 쪽이 더 중요하다.** gclid를 히든 필드에 넣어 전환을 추적하는 것은
표준 관행이다. 그걸 잡으면 전환 추적을 제대로 붙인 광고주가 전부 걸린다.
"""

from __future__ import annotations

import pytest

from adpolicy import cloaking, rules

PATTERNS = [p for _code, p in rules.CONTENT_PATTERNS]


def detect(script: str) -> str:
    return cloaking.detect_param_branch_script(f"<script>{script}</script>", PATTERNS)


# --- 잡아야 하는 것 ---------------------------------------------------------


def test_swapping_the_body_when_gclid_is_present():
    assert detect("""
        var p = new URLSearchParams(location.search);
        if (p.get('gclid')) { document.getElementById('lp').innerHTML = other; }
    """)


def test_redirecting_when_the_click_id_is_present():
    assert detect("""
        if (location.search.indexOf('gclid') > -1) {
            location.replace('https://real-offer.example.com/');
        }
    """)


@pytest.mark.parametrize("param", ["gclid", "ttclid", "fbclid", "msclkid", "utm_source"])
def test_every_ad_parameter_counts(param):
    assert detect(f"""
        var p = new URLSearchParams(location.search);
        if (p.get('{param}')) {{ document.body.innerHTML = x; }}
    """)


def test_document_write_counts_too():
    assert detect("""
        var q = location.search;
        if (q.includes('gclid')) { document.write(realPage); }
    """)


# --- 오탐 방어 --------------------------------------------------------------


def test_putting_the_click_id_into_a_hidden_field_is_normal():
    """전환 추적의 표준 구현이다. 이걸 잡으면 도구를 못 쓴다."""
    assert detect("""
        var p = new URLSearchParams(location.search);
        document.querySelector('input[name=gclid]').value = p.get('gclid') || '';
    """) == ""


def test_sending_it_to_analytics_is_normal():
    assert detect("""
        var p = new URLSearchParams(location.search);
        dataLayer.push({event: 'ad_click', gclid: p.get('gclid')});
    """) == ""


def test_storing_it_in_a_cookie_is_normal():
    assert detect("""
        var p = new URLSearchParams(location.search);
        document.cookie = 'gclid=' + p.get('gclid') + '; path=/';
    """) == ""


def test_reading_the_url_without_an_ad_parameter_is_not_branching():
    """location.search를 읽는 것 자체는 어느 페이지에나 있다."""
    assert detect("""
        var p = new URLSearchParams(location.search);
        if (p.get('page')) { list.innerHTML = render(p.get('page')); }
    """) == ""


def test_the_read_and_the_swap_must_be_in_the_same_script():
    html = ("<script>var g = new URLSearchParams(location.search).get('gclid');</script>"
            "<script>document.querySelector('#x').innerHTML = '안녕하세요 반갑습니다';</script>")
    assert cloaking.detect_param_branch_script(html, PATTERNS) == ""


def test_a_page_with_no_script_is_fine():
    assert cloaking.detect_param_branch_script("<html><body>본문</body></html>",
                                               PATTERNS) == ""


# --- 근거의 강도 ------------------------------------------------------------


def test_the_hidden_content_is_quoted_when_it_is_in_the_script():
    """바꿔 넣는 내용이 문자열로 박혀 있으면 그 문구가 곧 근거다."""
    dirty = "<p>원금 보장 수익률 300% 확정 지급</p>" * 10
    evidence = detect(f"""
        var p = new URLSearchParams(location.search);
        if (p.get('gclid')) {{ document.body.innerHTML = {dirty!r}; }}
    """)
    assert "원금 보장" in evidence


def test_otherwise_it_only_claims_the_structure():
    """내용을 못 봤으면 구조만 말한다. 그 이상은 거짓이 된다."""
    evidence = detect("""
        var p = new URLSearchParams(location.search);
        if (p.get('gclid')) { document.body.innerHTML = window.__lp; }
    """)
    assert "화면을 바꿉니다" in evidence
    assert "원금" not in evidence


def test_code_between_quotes_is_not_read_as_a_string():
    """짧은 문자열을 건너뛰며 따옴표 짝이 어긋나면 코드가 문자열로 읽힌다.

    실제로 `'gclid')) { document.getElementById('` 를 문자열로 읽고 있었다.
    """
    block = ("var p=new URLSearchParams(location.search);"
             "if (p.get('gclid')) { document.getElementById('lp').innerHTML = x; }")
    found = [m.group(1) or m.group(2) for m in cloaking._STRING_LITERAL.finditer(block)]
    assert found == ["gclid", "lp"]


def test_the_policy_does_not_overclaim():
    """서버 응답은 같으므로 '실제로 다른 내용이 나갔다'는 증명되지 않는다."""
    from adpolicy.policies import POLICY_BY_CODE
    item = POLICY_BY_CODE["ABUSE-PARAM-BRANCH-SCRIPT"]
    assert item.severity.value == "warn"
    assert "구조가 있다" in item.description
