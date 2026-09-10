"""점수 계산과 페이지 추출·SSRF 방어 테스트."""

from __future__ import annotations

import pytest

from adpolicy.fetcher import UnsafeURLError, _extract, assert_safe_url
from adpolicy.models import Finding, Severity, Source
from adpolicy.scoring import merge, score, sort_findings, verdict


def f(code: str, sev: Severity, src: Source = Source.RULE) -> Finding:
    return Finding(code=code, title=code, severity=sev, source=src, detail="d")


# --- 점수 ------------------------------------------------------------------

def test_clean_page_scores_100():
    assert score([]) == 100
    assert verdict([]) == "pass"


def test_block_finding_fails():
    findings = [f("A", Severity.BLOCK)]
    assert verdict(findings) == "fail"
    assert score(findings) < 100


def test_warn_only_needs_review():
    assert verdict([f("A", Severity.WARN)]) == "review"


def test_info_only_passes():
    assert verdict([f("A", Severity.INFO)]) == "pass"


def test_llm_findings_weigh_less_than_rules():
    rule_score = score([f("A", Severity.BLOCK, Source.RULE)])
    llm_score = score([f("A", Severity.BLOCK, Source.LLM)])
    assert llm_score > rule_score


def test_score_never_negative():
    assert score([f(str(i), Severity.BLOCK) for i in range(20)]) == 0


def test_scoring_is_deterministic():
    findings = [f("A", Severity.BLOCK), f("B", Severity.WARN)]
    assert score(findings) == score(findings)


# --- 병합·정렬 --------------------------------------------------------------

def test_rule_wins_over_llm_for_same_code():
    merged = merge([f("MIS-UNRELIABLE-CLAIMS", Severity.BLOCK, Source.RULE)],
                   [f("MIS-UNRELIABLE-CLAIMS", Severity.BLOCK, Source.LLM)])
    assert len(merged) == 1
    assert merged[0].source == Source.RULE


def test_block_sorts_before_warn():
    ordered = sort_findings([f("W", Severity.WARN), f("B", Severity.BLOCK)])
    assert [x.code for x in ordered] == ["B", "W"]


def test_rule_sorts_before_llm_at_same_severity():
    ordered = sort_findings([
        f("L", Severity.BLOCK, Source.LLM),
        f("R", Severity.BLOCK, Source.RULE),
    ])
    assert [x.code for x in ordered] == ["R", "L"]


# --- SSRF 방어 --------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://localhost:8080",
    "file:///etc/passwd",
    "ftp://example.com",
])
def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


# --- HTML 추출 --------------------------------------------------------------

HTML = """
<html><head>
  <title>테스트 상품</title>
  <meta name="description" content="설명입니다">
</head><body>
  <script>var x = "스크립트는 제외";</script>
  <style>.a{color:red}</style>
  <h1>본문 제목</h1>
  <p>실제 내용입니다.</p>
  <a href="/privacy">개인정보처리방침</a>
  <img src="a.png" alt="대체 텍스트">
  <img src="b.png">
  <form><input type="email" name="mail"></form>
</body></html>
"""


def test_extract_basic_fields():
    s = _extract(HTML, "https://e.com", "https://e.com", 200)
    assert s.title == "테스트 상품"
    assert s.meta_description == "설명입니다"
    assert "본문 제목" in s.text
    assert "실제 내용입니다." in s.text


def test_extract_drops_script_and_style():
    s = _extract(HTML, "https://e.com", "https://e.com", 200)
    assert "스크립트는 제외" not in s.text
    assert "color:red" not in s.text


def test_extract_collects_links_and_images():
    s = _extract(HTML, "https://e.com", "https://e.com", 200)
    assert "개인정보처리방침" in s.link_texts
    assert s.image_count == 2
    assert "대체 텍스트" in s.image_alts


def test_extract_detects_pii_form():
    s = _extract(HTML, "https://e.com", "https://e.com", 200)
    assert s.has_form
    assert "email" in s.form_input_types


def test_combined_text_includes_links_and_alts():
    s = _extract(HTML, "https://e.com", "https://e.com", 200)
    combined = s.combined_text
    assert "개인정보처리방침" in combined
    assert "대체 텍스트" in combined
