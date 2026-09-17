"""개인정보 수집·이용 동의 점검 (개인정보 보호법).

개인정보처리방침과 동의는 다른 것이다. 방침은 상시 공개하는 문서, 동의는
수집 시점의 행위. 하나가 다른 하나를 대신하지 못하므로 따로 판정해야 한다.
"""

from __future__ import annotations

import pytest

from adpolicy import rules
from adpolicy.models import PageSnapshot, Platform
from adpolicy.policies import CODE_DECIDED_PREFIXES, KR_POLICIES, POLICY_BY_CODE

FULL_CONSENT = (
    "[필수] 개인정보 수집·이용에 동의합니다. "
    "수집·이용 목적: 상담 신청 처리. "
    "수집 항목: 이름, 연락처. "
    "보유·이용 기간: 상담 종료 후 3개월. "
    "동의를 거부할 수 있으며 거부 시 상담 신청이 제한됩니다."
)


def _page(text: str, *, form: bool = True) -> PageSnapshot:
    return PageSnapshot(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        title="상담 신청",
        text="상담을 신청하세요. 문의 02-000-0000. " + ("본문 " * 200) + text,
        has_form=form,
        form_input_types=["text", "tel"] if form else [],
        fetch_error="",
    )


def _codes(snap: PageSnapshot) -> set[str]:
    return {f.code for f in rules.check_absence(snap, "상담 신청하기")}


# --- 두 항목이 서로를 대신하지 않는다 -------------------------------------


def test_no_form_means_neither_applies():
    """폼이 없으면 개인정보를 안 받는 것이니 둘 다 해당 없음."""
    codes = _codes(_page("회사 소개입니다.", form=False))
    assert "KR-NO-CONSENT" not in codes
    assert "DATA-NO-PRIVACY-POLICY" not in codes


def test_privacy_policy_alone_does_not_satisfy_consent():
    """방침 링크만 있고 동의 절차가 없는, 실무에서 가장 흔한 형태."""
    codes = _codes(_page("푸터: 개인정보처리방침 | 이용약관"))
    assert "DATA-NO-PRIVACY-POLICY" not in codes   # 방침은 있다
    assert "KR-NO-CONSENT" in codes                # 동의는 없다


def test_consent_alone_does_not_satisfy_privacy_policy():
    """반대 방향 — 체크박스만 있고 방침 페이지가 없는 경우."""
    codes = _codes(_page(FULL_CONSENT))
    assert "KR-NO-CONSENT" not in codes
    assert "DATA-NO-PRIVACY-POLICY" in codes


def test_both_present_is_clean():
    codes = _codes(_page("개인정보처리방침 | " + FULL_CONSENT))
    assert "KR-NO-CONSENT" not in codes
    assert "KR-INCOMPLETE-CONSENT" not in codes
    assert "DATA-NO-PRIVACY-POLICY" not in codes


def test_neither_present_reports_both():
    codes = _codes(_page("지금 바로 신청하세요."))
    assert {"KR-NO-CONSENT", "DATA-NO-PRIVACY-POLICY"} <= codes


# --- 동의 문구 인식 --------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "개인정보 수집·이용에 동의합니다",
        "개인정보 수집 및 이용 동의",
        "[필수] 개인정보 수집·이용 동의",
        "개인정보의 수집, 이용에 관한 사항에 동의",
        "위와 같이 개인정보를 수집·이용하는 데 동의합니다",
    ],
)
def test_recognizes_common_consent_phrasings(phrase):
    assert "KR-NO-CONSENT" not in _codes(_page(phrase))


@pytest.mark.parametrize(
    "phrase",
    [
        "이용약관에 동의합니다",
        "마케팅 정보 수신에 동의합니다",
        "만 14세 이상입니다 동의",
    ],
)
def test_unrelated_consent_does_not_count(phrase):
    """약관 동의·수신 동의는 개인정보 수집 동의가 아니다."""
    assert "KR-NO-CONSENT" in _codes(_page(phrase))


# --- 고지사항 누락 ---------------------------------------------------------


def test_bare_checkbox_flags_all_four_missing():
    findings = rules.check_absence(_page("개인정보 수집·이용에 동의합니다"), "신청")
    f = next(x for x in findings if x.code == "KR-INCOMPLETE-CONSENT")
    for label in ("수집·이용 목적", "수집 항목", "보유·이용 기간", "거부권 고지"):
        assert label in f.detail


def test_missing_refusal_notice_only():
    """거부권 고지가 가장 자주 빠지는 항목."""
    text = (
        "개인정보 수집·이용에 동의합니다. 수집 목적: 상담. "
        "수집 항목: 이름, 연락처. 보유 기간: 3개월."
    )
    findings = rules.check_absence(_page(text), "신청")
    f = next(x for x in findings if x.code == "KR-INCOMPLETE-CONSENT")
    # detail은 "정책 설명 + 확인되지 않은 항목: ..." 꼴이다. 설명 쪽에도 항목
    # 이름이 전부 등장하므로, 뒤쪽 목록만 떼어내서 본다.
    missing = f.detail.split("확인되지 않은 항목:")[1]
    assert "거부권 고지" in missing
    assert "수집 항목" not in missing
    assert "보유" not in missing


def test_complete_consent_has_no_incomplete_finding():
    codes = _codes(_page(FULL_CONSENT))
    assert "KR-INCOMPLETE-CONSENT" not in codes


# --- 처리방침 표기 오탐 ----------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["개인정보처리방침", "개인정보취급방침", "개인정보보호정책", "프라이버시 정책",
     "Privacy Policy"],
)
def test_privacy_policy_label_variants_are_accepted(label):
    """표기가 달라도 방침이 있으면 위반이 아니다 — 예전엔 오탐이었다."""
    assert "DATA-NO-PRIVACY-POLICY" not in _codes(_page(f"푸터: {label}"))


# --- 카탈로그 정합성 -------------------------------------------------------


def test_kr_items_are_not_labelled_as_google_policy():
    """국내 법령 항목이 Google 공식 분류에 섞이면 안 된다."""
    for p in KR_POLICIES:
        assert p.code.startswith("KR-")
        assert p.category == "국내 법령"
        assert "support.google.com" not in p.source
        assert "law.go.kr" in p.source


def test_kr_items_are_code_decided_not_asked_to_llm():
    """결정적으로 판정하므로 LLM 프롬프트 카탈로그에 넣지 않는다."""
    assert "KR-" in CODE_DECIDED_PREFIXES
    catalog = __import__(
        "adpolicy.policies", fromlist=["catalog_for_prompt"]
    ).catalog_for_prompt(Platform.GOOGLE_ADS)
    for p in KR_POLICIES:
        assert p.code not in catalog


def test_kr_items_registered_in_lookup():
    for p in KR_POLICIES:
        assert POLICY_BY_CODE[p.code] is p
