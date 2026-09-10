"""결정적 룰셋 테스트 — 네트워크 없이 동작한다."""

from __future__ import annotations

import pytest

from adpolicy.models import PageSnapshot, Platform, Severity, Source
from adpolicy.rules import check_absence, check_content_patterns, check_technical, run_all


def snap(**kw) -> PageSnapshot:
    base = dict(
        url="https://example.com/lp",
        final_url="https://example.com/lp",
        status_code=200,
        title="상품 소개",
        text="가" * 500,
    )
    base.update(kw)
    return PageSnapshot(**base)


def codes(findings) -> set[str]:
    return {f.code for f in findings}


# --- 부재 감지 ------------------------------------------------------------

def test_privacy_missing_when_form_collects_pii():
    s = snap(has_form=True, form_input_types=["email"], text="문의하기 " + "가" * 400)
    assert "LP-PRIVACY" in codes(check_absence(s, ""))


def test_privacy_ok_when_policy_link_present():
    s = snap(
        has_form=True,
        form_input_types=["email"],
        link_texts=["개인정보처리방침"],
        text="문의하기 " + "가" * 400,
    )
    assert "LP-PRIVACY" not in codes(check_absence(s, ""))


def test_privacy_not_flagged_without_pii_form():
    s = snap(has_form=False)
    assert "LP-PRIVACY" not in codes(check_absence(s, ""))


@pytest.mark.parametrize("contact", ["02-1234-5678", "help@example.com", "123-45-67890"])
def test_contact_detected(contact):
    s = snap(text=f"문의 {contact} " + "가" * 400)
    assert "LP-CONTACT" not in codes(check_absence(s, ""))


def test_contact_missing():
    assert "LP-CONTACT" in codes(check_absence(snap(), ""))


def test_price_required_only_with_commerce_intent():
    without = snap(text="회사 소개입니다 " + "가" * 400)
    assert "LP-PRICE" not in codes(check_absence(without, ""))

    with_intent = snap(text="지금 구매 하세요 " + "가" * 400)
    assert "LP-PRICE" in codes(check_absence(with_intent, ""))


def test_price_satisfied_by_won_amount():
    s = snap(text="지금 구매 하세요 29,000원 " + "가" * 400)
    assert "LP-PRICE" not in codes(check_absence(s, ""))


def test_thin_content():
    assert "LP-THIN" in codes(check_absence(snap(text="짧음"), ""))


def test_unreachable_short_circuits_other_checks():
    s = snap(status_code=404, fetch_error="HTTP 404")
    found = check_absence(s, "")
    assert codes(found) == {"LP-UNREACHABLE"}


def test_run_all_stops_on_unreachable():
    s = snap(status_code=500, fetch_error="HTTP 500")
    assert codes(run_all(s, "100% 보장", Platform.GOOGLE_ADS)) == {"LP-UNREACHABLE"}


# --- 기술 요건 ------------------------------------------------------------

def test_cross_domain_redirect_flagged():
    s = snap(url="https://a.com/x", final_url="https://b.com/y")
    assert "TECH-REDIRECT" in codes(check_technical(s))


def test_http_with_form_flagged():
    s = snap(url="http://a.com", final_url="http://a.com", has_form=True)
    assert "TECH-HTTPS" in codes(check_technical(s))


def test_missing_alt_flagged():
    s = snap(image_count=5, image_alts=["", "", "", "", ""])
    assert "TECH-NO-ALT" in codes(check_technical(s))


# --- 금지 표현 ------------------------------------------------------------

@pytest.mark.parametrize(
    "text,code",
    [
        ("효과 100% 보장 합니다", "AD-GUARANTEE"),
        ("아토피 완치 사례", "AD-MEDICAL"),
        ("원금 보장 상품", "AD-FINANCIAL"),
        ("단 3자리 남음", "AD-URGENCY"),
        ("업계 1위 브랜드", "AD-SUPERLATIVE"),
        ("정품급 가방 판매", "AD-COUNTERFEIT"),
    ],
)
def test_content_patterns(text, code):
    found = check_content_patterns(snap(), text, Platform.GOOGLE_ADS)
    assert code in codes(found)


def test_evidence_is_recorded_for_pattern_hits():
    found = check_content_patterns(snap(), "효과 100% 보장", Platform.GOOGLE_ADS)
    hit = next(f for f in found if f.code == "AD-GUARANTEE")
    assert hit.evidence
    assert hit.source == Source.RULE


def test_clean_copy_produces_no_content_findings():
    found = check_content_patterns(snap(), "신제품을 소개합니다", Platform.GOOGLE_ADS)
    assert found == []


def test_severity_mapping_is_stable():
    found = check_content_patterns(snap(), "원금 보장", Platform.GOOGLE_ADS)
    assert all(f.severity == Severity.BLOCK for f in found)
