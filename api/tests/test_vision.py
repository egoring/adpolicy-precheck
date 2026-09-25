"""이미지 점검 — 수집, OCR, 이미지 자체 판정.

핵심은 두 가지다.
  1. OCR 텍스트가 combined_text에 들어가 **근거 역검증이 계속 작동**하는가
  2. VLM 판정이 역검증 불가능하다는 사실이 구조에 반영돼 있는가
     (가중치, severity, 지어낸 이미지 폐기)
"""

from __future__ import annotations

import base64
import shutil
from io import BytesIO

import pytest
from selectolax.parser import HTMLParser

from adpolicy import scoring, vision
from adpolicy.analyzer import verify_evidence
from adpolicy.fetcher import _image_urls
from adpolicy.models import Finding, ImageAsset, PageSnapshot, Platform, Severity, Source

HAS_TESSERACT = shutil.which("tesseract") is not None
needs_ocr = pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract 미설치")


# ---------------------------------------------------------------------------
# 이미지 주소 수집
# ---------------------------------------------------------------------------


def _urls(html: str, base: str = "https://ex.com/lp/index.html") -> list[str]:
    tree = HTMLParser(html)
    return _image_urls(tree, tree.css("img"), base)


def test_relative_paths_become_absolute():
    got = _urls('<img src="../img/hero.png"><img src="/a/b.jpg">')
    assert "https://ex.com/img/hero.png" in got
    assert "https://ex.com/a/b.jpg" in got


def test_inline_and_non_http_sources_are_skipped():
    got = _urls(
        '<img src="data:image/png;base64,AAAA">'
        '<img src="blob:https://ex.com/x">'
        '<img src="javascript:void(0)">'
    )
    assert got == []


def test_lazy_loading_attributes_are_read():
    """src가 플레이스홀더고 진짜 주소는 data-src에 있는 흔한 형태."""
    got = _urls('<img src="/placeholder.gif" data-src="/real-banner.png">')
    assert "https://ex.com/real-banner.png" in got


def test_srcset_takes_only_the_first_candidate():
    """같은 그림의 해상도 변형을 전부 받을 이유가 없다."""
    got = _urls('<img srcset="/b-480.png 480w, /b-960.png 960w, /b-1920.png 1920w">')
    assert "https://ex.com/b-480.png" in got
    assert "https://ex.com/b-1920.png" not in got


def test_og_image_is_collected_first():
    got = _urls(
        '<meta property="og:image" content="/share.png"><img src="/inline.png">'
    )
    assert got[0] == "https://ex.com/share.png"


def test_duplicates_collapse():
    got = _urls('<img src="/x.png"><img src="/x.png"><img src="https://ex.com/x.png">')
    assert got.count("https://ex.com/x.png") == 1


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


def _banner(lines: list[str], size=(900, 320)) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    # Black은 fonts-noto-cjk-extra에만 있다. 기본 fonts-noto-cjk(CI 러너)는
    # Bold·Regular뿐이라, 하나만 보면 CI에서 이 테스트가 늘 건너뛰어진다.
    img = Image.new("RGB", size, "#14213d")
    d = ImageDraw.Draw(img)
    for weight in ("Black", "Bold", "Regular"):
        try:
            font = ImageFont.truetype(
                f"/usr/share/fonts/opentype/noto/NotoSansCJK-{weight}.ttc", 52, index=2)
            break
        except OSError:
            continue
    else:  # pragma: no cover - 폰트 없는 환경
        pytest.skip("한국어 폰트 없음")
    for i, line in enumerate(lines):
        d.text((40, 40 + i * 80), line, font=font, fill="#ffd60a")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _asset(data: bytes, url: str = "https://ex.com/banner.png") -> ImageAsset:
    return ImageAsset(
        url=url,
        content_type="image/png",
        bytes_len=len(data),
        data_b64=base64.b64encode(data).decode("ascii"),
    )


@needs_ocr
def test_ocr_reads_korean_from_a_banner():
    text, err = vision.ocr_image(_banner(["지금 신청하면 100% 보장"]))
    assert err == ""
    assert "100" in text
    assert "보장" in text


def test_ocr_missing_binary_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(vision.shutil, "which", lambda _: None)
    text, err = vision.ocr_image(b"whatever")
    assert text == ""
    assert "tesseract" in err


def test_run_ocr_skips_failed_assets():
    broken = ImageAsset(url="https://ex.com/x.png", fetch_error="HTTP 404")
    vision.run_ocr([broken])
    assert broken.ocr_text == ""


# ---------------------------------------------------------------------------
# 이미지 속 텍스트 → 기존 결정적 룰
# ---------------------------------------------------------------------------


def _ocr_asset(text: str, url: str = "https://ex.com/banner.png") -> ImageAsset:
    return ImageAsset(url=url, content_type="image/png", bytes_len=9999, ocr_text=text)


def test_banner_text_triggers_the_same_rules_as_body_text():
    """새 룰을 짜지 않는다 — 본문과 같은 기준을 이미지에 적용한다."""
    assets = [_ocr_asset("지금 신청하면 효과 100% 보장! 업계 1위")]
    codes = {f.code for f in vision.check_image_text(assets, Platform.GOOGLE_ADS)}
    assert "MIS-UNRELIABLE-CLAIMS" in codes
    assert "MIS-SUPERLATIVE" in codes


def test_image_findings_say_which_image():
    """사람이 그 배너를 바로 열어볼 수 있어야 한다."""
    assets = [_ocr_asset("원금 보장 확정 수익", url="https://ex.com/hero.png")]
    f = vision.check_image_text(assets, Platform.GOOGLE_ADS)[0]
    assert f.image_url == "https://ex.com/hero.png"
    assert f.source is Source.OCR
    assert "이미지 안에서" in f.detail


def test_platform_filter_applies_to_image_findings():
    assets = [_ocr_asset("비포 애프터 사진")]
    google = {f.code for f in vision.check_image_text(assets, Platform.GOOGLE_ADS)}
    tiktok = {f.code for f in vision.check_image_text(assets, Platform.TIKTOK_ADS)}
    assert "TT-BEFORE-AFTER" in tiktok or "TT-BEFORE-AFTER" in google


def test_no_ocr_text_means_no_findings():
    assert vision.check_image_text([_ocr_asset("")], Platform.GOOGLE_ADS) == []


# ---------------------------------------------------------------------------
# 근거 역검증이 이미지까지 이어지는가 — 이 기능의 핵심 불변식
# ---------------------------------------------------------------------------


def test_rules_do_not_see_ocr_text():
    """본문 룰이 배너 문구를 잡으면 source=rule이 되어 출처가 사라진다.

    이미지 쪽은 check_image_text가 이미지 단위로 따로 판정해야 한다.
    """
    snap = PageSnapshot(
        url="https://ex.com", final_url="https://ex.com", status_code=200,
        text="본문에는 아무 문제 없습니다.",
        ocr_text="지금 신청하면 효과 100% 보장!",
    )
    assert "100% 보장" not in snap.combined_text


def test_evidence_verification_does_see_ocr_text():
    """모델이 배너 문구를 인용하면 실제 OCR 텍스트와 대조된다."""
    snap = PageSnapshot(
        url="https://ex.com", final_url="https://ex.com", status_code=200,
        text="본문", ocr_text="원금 보장 · 확정 수익 월 8%",
    )
    assert "확정 수익" in snap.verification_text
    assert verify_evidence("확정 수익", snap.verification_text)


def test_invented_banner_evidence_is_still_rejected():
    """이미지 기능을 넣었다고 환각이 통과하면 안 된다."""
    snap = PageSnapshot(
        url="https://ex.com", final_url="https://ex.com", status_code=200,
        text="본문", ocr_text="원금 보장 · 확정 수익 월 8%",
    )
    assert not verify_evidence("무료 체험 3개월 제공", snap.verification_text)


# ---------------------------------------------------------------------------
# VLM — 이미지 자체 판정
# ---------------------------------------------------------------------------


def _fake_vlm(monkeypatch, payload: str, err: str = ""):
    async def fake(self, messages, **kwargs):
        return payload, err

    monkeypatch.setattr("adpolicy.llm.LLMClient.complete_messages", fake)
    monkeypatch.setattr(vision, "VLM_BASE_URL", "http://vlm:8000/v1")


@pytest.fixture
def one_image():
    return [_asset(b"x" * 5000)]


async def test_vlm_disabled_without_base_url(monkeypatch, one_image):
    monkeypatch.setattr(vision, "VLM_BASE_URL", "")
    findings, stats, err = await vision.analyze_images(one_image, Platform.GOOGLE_ADS)
    assert findings == []
    assert "VLM_BASE_URL" in err


async def test_vlm_finding_is_attributed_to_its_image(monkeypatch, one_image):
    _fake_vlm(monkeypatch, '{"analysis":"a","findings":[{"code":"TT-BEFORE-AFTER",'
                           '"reason":"좌우로 체중 변화 비교 사진"}]}')
    findings, stats, err = await vision.analyze_images(one_image, Platform.TIKTOK_ADS)
    assert err == ""
    assert len(findings) == 1
    f = findings[0]
    assert f.source is Source.VLM
    assert f.image_url == "https://ex.com/banner.png"
    assert "체중 변화" in f.evidence
    assert "직접 확인하세요" in f.detail


async def test_vlm_cannot_invent_policy_codes(monkeypatch, one_image):
    _fake_vlm(monkeypatch, '{"findings":[{"code":"MADE-UP-CODE","reason":"x"}]}')
    findings, stats, _ = await vision.analyze_images(one_image, Platform.GOOGLE_ADS)
    assert findings == []
    assert stats["vlm_dropped_unknown_code"] == 1


async def test_vlm_cannot_use_codes_it_was_not_asked_about(monkeypatch, one_image):
    """텍스트 룰이 담당하는 코드를 VLM이 올리면 폐기한다 — 역검증이 없기 때문."""
    _fake_vlm(monkeypatch, '{"findings":[{"code":"MIS-UNRELIABLE-CLAIMS","reason":"x"}]}')
    findings, stats, _ = await vision.analyze_images(one_image, Platform.GOOGLE_ADS)
    assert findings == []
    assert stats["vlm_dropped_unknown_code"] == 1


async def test_vlm_block_is_downgraded_to_warn(monkeypatch, one_image):
    """역검증이 불가능한 판단으로 게재 거부를 단정하지 않는다."""
    _fake_vlm(monkeypatch, '{"findings":[{"code":"RESTRICT-SEXUAL","reason":"노출"}]}')
    findings, _, _ = await vision.analyze_images(one_image, Platform.GOOGLE_ADS)
    assert findings[0].severity is Severity.WARN


async def test_vlm_non_json_response_is_not_an_error(monkeypatch, one_image):
    _fake_vlm(monkeypatch, "죄송합니다. 판단할 수 없습니다.")
    findings, _, err = await vision.analyze_images(one_image, Platform.GOOGLE_ADS)
    assert findings == []
    assert err == ""


async def test_vlm_transport_error_is_reported(monkeypatch, one_image):
    _fake_vlm(monkeypatch, "", err="LLM 서버가 연결을 거부했습니다")
    findings, _, err = await vision.analyze_images(one_image, Platform.GOOGLE_ADS)
    assert findings == []
    assert "거부" in err


async def test_unusable_images_are_skipped(monkeypatch):
    broken = [ImageAsset(url="https://ex.com/x.png", fetch_error="HTTP 404")]
    findings, stats, err = await vision.analyze_images(broken, Platform.GOOGLE_ADS)
    assert findings == [] and err == ""


# ---------------------------------------------------------------------------
# 점수 가중치 — 근거가 약할수록 낮게
# ---------------------------------------------------------------------------


def _f(source: Source) -> Finding:
    return Finding(code="X", title="t", severity=Severity.BLOCK, source=source, detail="d")


def test_weight_decreases_as_evidence_gets_weaker():
    rule = 100 - scoring.score([_f(Source.RULE)])
    ocr = 100 - scoring.score([_f(Source.OCR)])
    llm = 100 - scoring.score([_f(Source.LLM)])
    vlm = 100 - scoring.score([_f(Source.VLM)])
    assert rule > ocr > llm > vlm


def test_findings_are_ordered_by_evidence_strength():
    got = scoring.sort_findings([_f(Source.VLM), _f(Source.RULE), _f(Source.OCR)])
    assert [f.source for f in got] == [Source.RULE, Source.OCR, Source.VLM]


# ---------------------------------------------------------------------------
# 종단 — 본문은 깨끗한데 배너에 문제가 박혀 있는 페이지
# ---------------------------------------------------------------------------

CLEAN_BODY = (
    "자산관리 상담을 제공합니다. 사전 예약제입니다. "
    "문의 02-1234-5678 · 사업자등록번호 123-45-67890 · 상담료 50,000원. "
    "[필수] 개인정보 수집·이용에 동의합니다. 수집·이용 목적: 상담. "
    "수집 항목: 이름, 연락처. 보유·이용 기간: 3개월. "
    "동의를 거부할 수 있으며 거부 시 상담이 제한됩니다. 개인정보처리방침. "
    + "서비스 소개 " * 80
)


def _clean_page() -> PageSnapshot:
    return PageSnapshot(
        url="https://ex.com/lp", final_url="https://ex.com/lp", status_code=200,
        title="재테크 상담", text=CLEAN_BODY,
        image_urls=["https://ex.com/hero.png"],
        has_form=True, form_input_types=["text", "tel"],
    )


def test_clean_body_alone_passes():
    """기준선 — 본문만 보면 지적할 게 없다."""
    from adpolicy import rules

    assert rules.run_all(_clean_page(), "재테크 상담 신청", Platform.GOOGLE_ADS) == []


def test_banner_flips_a_passing_page_to_fail():
    """이 기능이 존재하는 이유. 본문은 통과, 배너 때문에 거부 위험."""
    from adpolicy import rules

    snap = _clean_page()
    banner = _ocr_asset(
        "지금 신청하면 100% 보장!\n원금 보장 · 확정 수익 월 8%\n단 3자리 남았습니다",
        url="https://ex.com/hero.png",
    )
    body = rules.run_all(snap, "재테크 상담 신청", Platform.GOOGLE_ADS)
    image = vision.check_image_text([banner], Platform.GOOGLE_ADS)
    merged = scoring.merge(body + image, [])

    assert scoring.verdict(body) == "pass"
    assert scoring.verdict(merged) == "fail"
    # 전부 이미지 출처로, 어느 배너인지 붙어 있어야 한다
    assert {f.source for f in merged} == {Source.OCR}
    assert all(f.image_url == "https://ex.com/hero.png" for f in merged)


# ---------------------------------------------------------------------------
# API 계약 — 화면이 이미지 점검 결과를 보여줄 수 있어야 한다
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(monkeypatch):
    """네트워크 없이 /v1/check 를 부른다. 배너 한 장이 달린 깨끗한 페이지."""
    from fastapi.testclient import TestClient

    from adpolicy import cloaking, main

    page = PageSnapshot(
        url="https://ex.com/lp", final_url="https://ex.com/lp", status_code=200,
        title="재테크 상담", text=CLEAN_BODY, image_urls=["https://ex.com/hero.png"],
    )
    banner = _ocr_asset("지금 신청하면 100% 보장! 원금 보장", url="https://ex.com/hero.png")
    banner.bytes_len = 9999
    banner.data_b64 = base64.b64encode(b"x" * 5000).decode("ascii")

    async def fake_probe(url):
        return {"desktop": page.model_copy(deep=True)}, {"desktop": "<html></html>"}

    async def fake_robots(url):
        return False, ""

    async def fake_collect(snap, limit=8):
        snap.ocr_text = banner.ocr_text
        return [banner]

    async def fake_params(url):
        # 파라미터 조합도 실제 요청이다. 안 막으면 테스트가 밖으로 나간다.
        return dict.fromkeys(cloaking.PARAM_PROFILES, page.model_copy(deep=True))

    monkeypatch.setattr(cloaking, "probe_profiles", fake_probe)
    monkeypatch.setattr(cloaking, "check_robots", fake_robots)
    monkeypatch.setattr(cloaking, "probe_params", fake_params)
    monkeypatch.setattr(vision, "collect", fake_collect)
    monkeypatch.setattr(vision, "run_ocr", lambda assets: None)
    return TestClient(main.app)


def _check(client, **extra):
    return client.post(
        "/v1/check",
        json={"url": "https://ex.com/lp", "ad_copy": "재테크 상담",
              "use_llm": False, **extra},
    ).json()


def test_response_reports_how_many_images_were_looked_at(api_client):
    """0건이 '문제 없음'인지 '아예 안 봤음'인지 화면이 구분할 수 있어야 한다."""
    body = _check(api_client, check_images=True)
    assert body["stats"]["images_fetched"] == 1
    assert body["stats"]["images_with_text"] == 1


def test_image_findings_carry_source_and_image_url_over_http(api_client):
    body = _check(api_client, check_images=True)
    image_findings = [f for f in body["findings"] if f["source"] == "ocr"]
    assert image_findings, body["findings"]
    assert all(f["image_url"] == "https://ex.com/hero.png" for f in image_findings)


def test_check_images_false_really_skips_it(api_client):
    body = _check(api_client, check_images=False)
    assert [f for f in body["findings"] if f["source"] == "ocr"] == []
    assert "images_fetched" not in body["stats"]


def test_banner_changes_the_verdict_over_http(api_client):
    assert _check(api_client, check_images=False)["verdict"] == "pass"
    assert _check(api_client, check_images=True)["verdict"] == "fail"


# ---------------------------------------------------------------------------
# 이미지 보고 — 무엇을 읽었는지 보여준다
# ---------------------------------------------------------------------------


def test_clean_images_are_reported_too():
    """지적이 없어도 남는다. '읽었는데 문제 없음'과 '못 읽음'은 다른 정보다."""
    assets = [_ocr_asset("강남점 안내 평일 10시~19시", url="https://ex.com/info.png")]
    report = vision.build_reports(assets, [])[0]
    assert report.ocr_text.startswith("강남점")
    assert report.finding_codes == []
    assert report.note == ""


def test_report_links_findings_to_their_image():
    bad = _ocr_asset("100% 보장", url="https://ex.com/a.png")
    good = _ocr_asset("영업시간 안내", url="https://ex.com/b.png")
    findings = vision.check_image_text([bad, good], Platform.GOOGLE_ADS)
    reports = {r.url: r for r in vision.build_reports([bad, good], findings)}
    assert reports["https://ex.com/a.png"].finding_codes
    assert reports["https://ex.com/b.png"].finding_codes == []


def test_skipped_image_explains_why():
    skipped = ImageAsset(url="https://ex.com/px.gif",
                         fetch_error="너무 작아 건너뜀 (아이콘·추적 픽셀)")
    report = vision.build_reports([skipped], [])[0]
    assert report.ocr_text == ""
    assert "건너뜀" in report.note


def test_image_with_no_readable_text_says_so():
    photo = ImageAsset(url="https://ex.com/photo.jpg", bytes_len=50000, ocr_text="")
    report = vision.build_reports([photo], [])[0]
    assert "글자가 없" in report.note


def test_long_ocr_text_is_truncated(monkeypatch):
    monkeypatch.setattr(vision, "OCR_TEXT_PREVIEW", 20)
    report = vision.build_reports([_ocr_asset("가" * 100)], [])[0]
    assert len(report.ocr_text) < 40
    assert report.ocr_text.endswith("…")


def test_response_carries_what_was_read(api_client):
    body = _check(api_client, check_images=True)
    assert body["images"], "읽은 내용을 응답에 실어야 화면이 보여줄 수 있다"
    assert any(i["ocr_text"] for i in body["images"])


def test_vlm_state_is_always_explained(api_client):
    """켰는데 아무 일도 안 일어나면 사용자가 이유를 알 수 없다."""
    off = _check(api_client, check_images=True, use_vlm=False)
    assert off["vlm_used"] is False
    assert "끈 상태" in off["vlm_note"]

    on = _check(api_client, check_images=True, use_vlm=True)
    assert on["vlm_note"]  # 설정이 없으면 없다고 말해야 한다


# ---------------------------------------------------------------------------
# 콘텐츠가 이미지 안에 있는 페이지 — 오탐 방지
# ---------------------------------------------------------------------------


def _thin_page(body: str, ocr: str = "") -> PageSnapshot:
    return PageSnapshot(
        url="https://ex.com", final_url="https://ex.com", status_code=200,
        title="상담", text=body, ocr_text=ocr,
    )


def _codes_for(snap: PageSnapshot) -> set[str]:
    from adpolicy import rules

    return {f.code for f in rules.check_absence(snap, "")}


def test_image_only_page_is_not_called_thin():
    """국내 랜딩페이지는 본문이 통째로 이미지인 경우가 흔하다.

    이미지에서 글자를 읽어놓고 '독자적 콘텐츠 부족'이라고 하면 앞뒤가 안 맞는다.
    """
    snap = _thin_page("짧은 안내." * 10, ocr="상세 소개 " * 200)
    codes = _codes_for(snap)
    assert "DEST-INSUFFICIENT-CONTENT" not in codes
    assert "DEST-IMAGE-ONLY-CONTENT" in codes


def test_image_only_finding_is_only_informational():
    """내용은 있으므로 반려 위험으로 올리지 않는다."""
    from adpolicy import rules

    snap = _thin_page("짧은 안내." * 10, ocr="상세 소개 " * 200)
    f = next(x for x in rules.check_absence(snap, "")
             if x.code == "DEST-IMAGE-ONLY-CONTENT")
    assert f.severity is Severity.INFO
    assert "본문" in f.evidence and "이미지" in f.evidence


def test_genuinely_empty_page_still_flagged():
    """이미지에도 글자가 없으면 진짜로 빈약한 페이지다."""
    codes = _codes_for(_thin_page("환영합니다", ocr=""))
    assert "DEST-INSUFFICIENT-CONTENT" in codes
    assert "DEST-IMAGE-ONLY-CONTENT" not in codes


def test_thin_body_and_thin_images_reports_the_combined_total():
    from adpolicy import rules

    snap = _thin_page("환영합니다", ocr="배너")
    f = next(x for x in rules.check_absence(snap, "")
             if x.code == "DEST-INSUFFICIENT-CONTENT")
    assert "이미지 포함" in f.evidence


def test_page_with_enough_body_text_is_untouched():
    codes = _codes_for(_thin_page("본문 내용입니다. " * 60))
    assert "DEST-INSUFFICIENT-CONTENT" not in codes
    assert "DEST-IMAGE-ONLY-CONTENT" not in codes


# ---------------------------------------------------------------------------
# OCR 잡음 걸러내기 — 반쯤 읽힌 줄이 본문에 섞이면 안 된다
# ---------------------------------------------------------------------------


def test_low_confidence_lines_are_dropped():
    """사진 위 장식 글자는 반쯤 읽혀 쓰레기 문자열로 남는다."""
    lines = [("정상적인 한국어 본문입니다", 88.0), ("은 ae [버", 21.0), ("= hel 0y ea, 7", 18.0)]
    assert vision._join(lines) == "정상적인 한국어 본문입니다"


def test_latin_fragments_need_more_content_than_hangul():
    """노이즈는 대개 한두 글자 라틴 조각으로 나온다."""
    assert not vision._keep_line("iN", 95.0)
    assert not vision._keep_line("~", 95.0)
    assert vision._keep_line("SALE", 95.0)
    assert vision._keep_line("할인", 95.0)


def test_result_of_only_fragments_counts_as_nothing_read():
    """조각 몇 개를 '읽었다'고 내보내면 사용자가 결과를 오해한다."""
    assert vision._score([("ve", 90.0), ("iN", 90.0), ("~", 90.0)]) < 0


def test_score_prefers_more_readable_content():
    thin = [("할인", 95.0)]
    rich = [("지금 신청하면 효과 100% 보장", 80.0), ("원금 보장 확정 수익", 80.0)]
    assert vision._score(rich) > vision._score(thin)


@needs_ocr
def test_pure_noise_yields_no_text():
    """읽을 게 없는 이미지에서 그럴듯한 쓰레기를 만들어내면 안 된다."""
    import random
    from io import BytesIO

    from PIL import Image, ImageDraw

    random.seed(7)
    im = Image.new("RGB", (600, 300))
    d = ImageDraw.Draw(im)
    for _ in range(4000):
        x, y = random.randrange(600), random.randrange(300)
        d.line(
            [(x, y), (x + random.randrange(-8, 8), y + random.randrange(-8, 8))],
            fill=(random.randrange(256),) * 3,
            width=random.randrange(1, 3),
        )
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=60)
    text, _ = vision.ocr_image(buf.getvalue())
    assert text.strip() == ""


def test_line_filter_falls_back_when_counts_disagree(monkeypatch):
    """줄 수가 안 맞으면 억지로 거르지 않는다 — 멀쩡한 줄을 버리는 게 더 나쁘다."""
    monkeypatch.setattr(vision, "_plain_lines", lambda png, psm: ["가", "나", "다"])
    monkeypatch.setattr(vision, "_line_confidences", lambda png, psm: [90.0])
    got = vision._read(b"x", 6)
    assert [t for t, _ in got] == ["가", "나", "다"]
    assert all(c == 100.0 for _, c in got)


def test_page_wide_ocr_budget_skips_the_rest(monkeypatch):
    """8장이면 장당 예산의 합이 요청 데드라인을 넘긴다."""
    monkeypatch.setattr(vision, "OCR_PAGE_BUDGET", -1.0)
    assets = [
        ImageAsset(url=f"https://ex.com/{i}.png", content_type="image/png",
                   bytes_len=9999, data_b64=base64.b64encode(b"x").decode())
        for i in range(3)
    ]
    vision.run_ocr(assets)
    assert all("예산" in a.ocr_error for a in assets)
