"""룰과 모델이 같은 코드를 잡았을 때 무엇을 잃지 않아야 하는가.

예전에는 진 쪽을 통째로 버렸다. 코드당 하나만 남긴다는 판단 자체는 맞지만,
버려진 쪽이 들고 있던 **어느 이미지에서 나왔는지**와 **다른 위반 문구**까지
같이 사라졌다. 사전점검 도구에서 고칠 대상이 안 보이면 고칠 수 없다.
"""

from __future__ import annotations

from adpolicy import scoring
from adpolicy.models import Finding, Severity, Source


def make(code: str, source: Source, evidence: str = "", image_url: str = "") -> Finding:
    return Finding(
        code=code, title="제목", severity=Severity.WARN, source=source,
        detail="설명", evidence=evidence, fix="고치세요", image_url=image_url,
    )


def test_rule_wins_over_the_model_for_reproducibility():
    rule = make("TT-BODY-IMAGE", Source.RULE, "뚱뚱한 몸 때문에 자신감")
    llm = make("TT-BODY-IMAGE", Source.LLM, "살만 빼면 연애도 취업도")
    out = scoring.merge([rule], [llm])
    assert len(out) == 1
    assert out[0].source is Source.RULE


def test_the_losing_findings_evidence_is_absorbed_not_dropped():
    rule = make("TT-BODY-IMAGE", Source.RULE, "뚱뚱한 몸 때문에 자신감")
    llm = make("TT-BODY-IMAGE", Source.LLM, "살만 빼면 연애도 취업도")
    (kept,) = scoring.merge([rule], [llm])
    assert "뚱뚱한 몸 때문에 자신감" in kept.evidence
    assert "살만 빼면 연애도 취업도" in kept.evidence


def test_image_attribution_survives_the_merge():
    """룰은 본문을 보므로 image_url이 없다. VLM이 알고 있으면 그걸 받아야 한다.

    없으면 사용자는 어느 배너를 고쳐야 하는지 알 수 없다.
    """
    rule = make("PROHIB-COUNTERFEIT", Source.RULE, "정품급")
    vlm = make("PROHIB-COUNTERFEIT", Source.VLM, "가방 로고가 모조품", "https://ex.com/b.png")
    (kept,) = scoring.merge([rule], [vlm])
    assert kept.source is Source.RULE
    assert kept.image_url == "https://ex.com/b.png"


def test_an_existing_image_url_is_not_overwritten():
    rule = make("PROHIB-COUNTERFEIT", Source.OCR, "정품급", "https://ex.com/first.png")
    vlm = make("PROHIB-COUNTERFEIT", Source.VLM, "로고", "https://ex.com/second.png")
    (kept,) = scoring.merge([rule], [vlm])
    assert kept.image_url == "https://ex.com/first.png"


def test_identical_evidence_is_not_duplicated():
    rule = make("MIS-CLICKBAIT", Source.RULE, "단 5자리 남")
    llm = make("MIS-CLICKBAIT", Source.LLM, "단 5자리 남")
    (kept,) = scoring.merge([rule], [llm])
    assert kept.evidence == "단 5자리 남"


def test_merged_evidence_is_length_capped():
    rule = make("MIS-CLICKBAIT", Source.RULE, "가" * 280)
    llm = make("MIS-CLICKBAIT", Source.LLM, "나" * 280)
    (kept,) = scoring.merge([rule], [llm])
    assert len(kept.evidence) <= scoring.EVIDENCE_JOIN_LIMIT


def test_the_merge_is_counted_so_the_numbers_add_up():
    """세지 않으면 rule+llm+vlm 합과 최종 건수가 어긋나는데 이유를 알 수 없다."""
    stats: dict[str, int] = {}
    rule = [make("A", Source.RULE), make("B", Source.RULE)]
    model = [make("A", Source.LLM), make("C", Source.VLM)]
    out = scoring.merge(rule, model, stats)
    assert len(out) == 3
    assert stats["merged_by_stronger_source"] == 1


def test_one_card_per_code_even_when_eight_banners_all_match():
    """병원 랜딩페이지는 배너 8장이 전부 같은 항목에 걸린다.

    이미지마다 카드를 만들면 제목·설명·수정방법이 똑같은 카드가 8장 쌓이고,
    정작 다른 지적이 그 아래로 밀려 안 보인다. 실제 페이지에서 그랬다.
    """
    vlm = [
        make("RESTRICT-HEALTHCARE", Source.VLM, f"배너 {i} 의료 효과 주장",
             f"https://ex.com/img{i}.jpg")
        for i in range(8)
    ]
    stats: dict[str, int] = {}
    out = scoring.merge([], vlm, stats)
    assert len(out) == 1
    assert stats["merged_same_source"] == 7
    # 다만 어느 배너였는지는 전부 남아야 한다 — 8장을 다 고쳐야 하기 때문이다
    assert len(out[0].image_urls) == 8
    assert out[0].image_urls[0] == "https://ex.com/img0.jpg"


def test_the_strongest_source_survives_regardless_of_input_order():
    """VLM이 먼저 들어와도 룰이 이겨야 한다. 재현성이 근거 강도의 이유다."""
    vlm = make("RESTRICT-HEALTHCARE", Source.VLM, "사진 판단", "https://ex.com/a.jpg")
    ocr = make("RESTRICT-HEALTHCARE", Source.OCR, "탈모 치료", "https://ex.com/b.jpg")
    rule = make("RESTRICT-HEALTHCARE", Source.RULE, "의학적으로 입증")
    (kept,) = scoring.merge([], [vlm, ocr, rule])
    assert kept.source is Source.RULE
    # 이미지도 근거가 강한 순으로 붙는다 (ocr이 vlm보다 앞)
    assert kept.image_urls == ["https://ex.com/b.jpg", "https://ex.com/a.jpg"]


def test_findings_without_images_get_no_image_list():
    rule = make("MIS-CLICKBAIT", Source.RULE, "단 5자리 남")
    (kept,) = scoring.merge([rule], [])
    assert kept.image_urls == []


def test_model_only_codes_still_come_through():
    rule = [make("A", Source.RULE)]
    vlm = [make("TT-BEFORE-AFTER", Source.VLM, "전후 실루엣", "https://ex.com/ba.png")]
    out = scoring.merge(rule, vlm)
    codes = {f.code for f in out}
    assert codes == {"A", "TT-BEFORE-AFTER"}
    assert next(f for f in out if f.code == "TT-BEFORE-AFTER").image_url


def test_analyzer_merges_repeated_codes_instead_of_dropping_them(monkeypatch):
    """LLM이 같은 코드로 문구 두 개를 올리면 둘 다 보여야 한다."""
    import asyncio

    from adpolicy import analyzer
    from adpolicy.models import PageSnapshot, Platform

    snap = PageSnapshot(
        url="u", final_url="u", status_code=200,
        text="한 달 만에 15kg 감량 보장. 굶지 않고 운동 없이 가능합니다.",
    )
    payload = """{"analysis":"요약","findings":[
      {"code":"TT-WEIGHT-UNREALISTIC","evidence":"한 달 만에 15kg 감량 보장","reason":"기간 보장"},
      {"code":"TT-WEIGHT-UNREALISTIC","evidence":"굶지 않고 운동 없이","reason":"노력 없이"}
    ]}"""

    class FakeLLM:
        async def complete(self, *a, **k):
            return payload, ""

    findings, stats, _analysis, err = asyncio.run(
        analyzer.analyze(snap, "", Platform.TIKTOK_ADS, FakeLLM())
    )
    assert err == ""
    assert stats["llm_raw"] == 2
    assert stats["merged_duplicate_code"] == 1
    (f,) = findings
    assert "한 달 만에 15kg 감량 보장" in f.evidence
    assert "굶지 않고 운동 없이" in f.evidence
