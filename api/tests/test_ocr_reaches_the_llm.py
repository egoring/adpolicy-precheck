"""이미지로만 만든 랜딩페이지에서 LLM이 아무것도 못 보던 문제.

국내 병원·쇼핑 랜딩페이지는 본문 대신 **이미지에 글자를 박아 넣는다.**
그런 페이지에서 LLM 프롬프트에 본문만 넣으면 볼 게 없어 지적 0건이 나온다.
실제로 배너 8장짜리 비뇨기과 페이지에서 그랬다 — 화면에 "LLM 0건"이 떴다.

동시에 지켜야 하는 것: **본문 룰은 여전히 본문만 본다.** 배너 문구를
본문 룰에 태우면 source가 rule로 찍혀서 "본문에 있었다"는 거짓이 된다.
"""

from __future__ import annotations

import asyncio

from adpolicy import analyzer, rules
from adpolicy.models import PageSnapshot, Platform


def snap_with_banner_text() -> PageSnapshot:
    return PageSnapshot(
        url="https://ex.com", final_url="https://ex.com", status_code=200,
        title="남성수술 전문", text="상호 메디토픽 | 대표 김철수",
        ocr_text="조루증 완치 사례 다수\n의학적으로 입증된 시술법\n단 5자리 남았습니다",
    )


def test_prompt_carries_the_text_read_from_images():
    prompt = analyzer.build_prompt(snap_with_banner_text(), "", Platform.GOOGLE_ADS)
    assert "조루증 완치 사례 다수" in prompt
    assert "의학적으로 입증된 시술법" in prompt
    # 어디서 온 글자인지 알려줘야 모델이 OCR 오독을 감안한다
    assert "OCR" in prompt


def test_prompt_says_so_when_no_image_text_was_read():
    snap = PageSnapshot(url="u", final_url="u", status_code=200, text="본문")
    prompt = analyzer.build_prompt(snap, "", Platform.GOOGLE_ADS)
    assert "이미지에서 읽은 글자 없음" in prompt


def test_image_text_is_capped_so_it_cannot_crowd_out_the_page():
    snap = PageSnapshot(url="u", final_url="u", status_code=200, text="본문",
                        ocr_text="가" * 50_000)
    prompt = analyzer.build_prompt(snap, "", Platform.GOOGLE_ADS)
    # 프롬프트 다른 곳에도 '가'가 섞여 있으니 OCR 값만 잘라서 잰다
    body = prompt.split("## 이미지에서 읽은 문구 (OCR)\n", 1)[1]
    value = body.split("\n\n", 1)[0]
    assert len(value) <= analyzer.MAX_OCR_CHARS


def test_body_rules_still_do_not_see_image_text():
    """이게 깨지면 배너에서 나온 지적이 source=rule로 찍혀 거짓말이 된다."""
    snap = snap_with_banner_text()
    findings = rules.run_all(snap, "", Platform.GOOGLE_ADS)
    for f in findings:
        assert "완치" not in f.evidence, f
    assert "완치" not in snap.combined_text
    # 다만 역검증은 배너 문구까지 봐야 한다
    assert "완치" in snap.verification_text


def test_a_quote_from_a_banner_passes_evidence_verification():
    """OCR 문구를 인용하게 해놓고 역검증이 그걸 버리면 아무 소용이 없다."""
    payload = """{"analysis":"요약","findings":[
      {"code":"RESTRICT-HEALTHCARE","evidence":"의학적으로 입증된 시술법","reason":"치료 효과 주장"}
    ]}"""

    class FakeLLM:
        async def complete(self, *a, **k):
            return payload, ""

    findings, stats, _a, err = asyncio.run(
        analyzer.analyze(snap_with_banner_text(), "", Platform.GOOGLE_ADS, FakeLLM())
    )
    assert err == ""
    assert stats["dropped_no_evidence"] == 0
    assert findings and findings[0].code == "RESTRICT-HEALTHCARE"


def test_the_prompt_tells_the_model_that_page_content_is_data():
    """프롬프트에 들어가는 본문·OCR은 공격자가 통제하는 텍스트다.

    "이전 지시를 무시하라"가 배너에 박혀 있을 수 있다.
    """
    assert "지시가" in analyzer.SYSTEM_PROMPT or "지시" in analyzer.SYSTEM_PROMPT
    assert "무시하라" in analyzer.SYSTEM_PROMPT
