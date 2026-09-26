"""C-8 evidence 위치 — 지적된 문구가 페이지·광고의 어디에 있는지.

"100% 보장"이 제목인지 본문인지 링크인지 alt인지 알아야 고칠 곳을 찾는다.
"""

from __future__ import annotations

from adpolicy import locate
from adpolicy.models import Finding, PageSnapshot, Severity, Source

SNAP = PageSnapshot(
    url="https://ex.com",
    final_url="https://ex.com",
    status_code=200,
    title="업계 1위 원두",
    meta_description="매일 볶는 스페셜티",
    text="로스팅 후 7일 이내 발송. 지금 신청하면 100% 보장. 자세히 보기",
    link_texts=["자세히 보기"],
    image_alts=["최고의 커피 한 잔"],
    form_text="이름 연락처 개인정보 수집 동의",
    ocr_text="원금 보장 확정 수익",
)


def _loc(evidence, **ad):
    return locate.locate(evidence, SNAP, **ad)


def test_title():
    assert _loc("업계 1위") == ["title"]


def test_meta_description():
    assert _loc("매일 볶는") == ["meta_description"]


def test_body_only():
    assert _loc("100% 보장") == ["body"]


def test_link_text_is_more_specific_than_body():
    """링크 글자는 본문에도 들어 있다. 더 구체적인 쪽만 알려준다."""
    assert _loc("자세히 보기") == ["link_text"]


def test_image_alt():
    assert _loc("최고의 커피") == ["image_alt"]


def test_form():
    assert _loc("개인정보 수집 동의") == ["form"]


def test_image_text_from_ocr():
    assert _loc("원금 보장") == ["image_text"]


def test_whitespace_and_width_differences_are_absorbed():
    """역검증과 같은 기준 — 띄어쓰기·전각 차이는 같은 문구다."""
    assert _loc("100 %  보장") == ["body"]
    assert _loc("１００％ 보장") == ["body"]


def test_ad_fields_are_reported_alongside_page():
    locs = _loc("업계 1위", headlines=["업계 1위 원두"], descriptions=["업계 1위 로스터리"],
                ad_copy="업계 1위 브랜드")
    assert locs == ["title", "ad_headline", "ad_description", "ad_copy"]


def test_merged_evidence_is_located_piece_by_piece():
    """scoring.merge가 근거를 ' / '로 이어 붙인다. 조각마다 찾는다."""
    assert _loc("업계 1위 / 원금 보장") == ["title", "image_text"]


def test_descriptive_evidence_gets_no_location():
    """'본문 120자' 같은 설명형 근거는 어디에도 없다 — 지어내지 않는다."""
    assert _loc("본문 120자 · 이미지에서 읽은 글자 0자") == []
    assert _loc("") == []


def test_annotate_fills_locations_on_findings():
    f = Finding(code="MIS-SUPERLATIVE", title="t", severity=Severity.WARN,
                source=Source.RULE, detail="d", evidence="업계 1위")
    locate.annotate([f], SNAP)
    assert f.locations == ["title"]


def test_mobile_only_evidence_is_marked_mobile():
    """모바일 화면에만 있는 문구는 모바일이라고 알려준다."""
    mobile = SNAP.model_copy(update={"text": "모바일 전용 특가 100% 환불"})
    f = Finding(code="X", title="t", severity=Severity.WARN, source=Source.RULE,
                detail="d", evidence="100% 환불")
    locate.annotate([f], SNAP, mobile=mobile)
    assert f.locations == ["mobile:body"]
