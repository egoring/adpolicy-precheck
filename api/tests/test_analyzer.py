"""LLM 계층 테스트 — 모의 클라이언트로 네트워크 없이 검증한다.

가장 중요한 것은 `verify_evidence`가 **환각을 실제로 걸러내는가**이다.
"""

from __future__ import annotations

import json

import pytest

from adpolicy.analyzer import _extract_json, analyze, parse_findings, verify_evidence
from adpolicy.models import PageSnapshot, Platform, Source


def snap(text: str = "저희 제품은 효과 100% 보장 합니다.") -> PageSnapshot:
    return PageSnapshot(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        title="제품 소개",
        text=text,
    )


class ScriptedLLM:
    """각본대로 답하는 모의 LLM."""

    def __init__(self, reply: str, error: str = "") -> None:
        self.reply = reply
        self.error = error
        self.calls = 0

    async def complete(self, system, user, **kw):
        self.calls += 1
        return self.reply, self.error


def payload(findings) -> str:
    return json.dumps({"analysis": "검토했습니다.", "findings": findings},
                      ensure_ascii=False)


# --- evidence 역검증 (핵심) ------------------------------------------------

def test_verify_evidence_accepts_real_quote():
    assert verify_evidence("100% 보장", "저희는 효과 100% 보장 합니다")


def test_verify_evidence_rejects_hallucination():
    assert not verify_evidence("무조건 완치됩니다", "저희는 효과 100% 보장 합니다")


def test_verify_evidence_tolerates_whitespace_difference():
    assert verify_evidence("100 %  보장", "효과 100% 보장 합니다")


def test_verify_evidence_rejects_too_short():
    # 짧은 문자열은 우연히 일치할 수 있으므로 근거로 인정하지 않는다
    assert not verify_evidence("보장", "효과 100% 보장")


def test_hallucinated_finding_is_dropped():
    raw = payload([
        {"code": "AD-GUARANTEE", "evidence": "100% 보장", "reason": "절대적 표현"},
        {"code": "AD-MEDICAL", "evidence": "암을 치료합니다", "reason": "의학적 주장"},
    ])
    found, stats, _ = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)

    assert [f.code for f in found] == ["AD-GUARANTEE"]
    assert stats["dropped_no_evidence"] == 1
    assert stats["llm_raw"] == 2


def test_unknown_code_is_dropped():
    raw = payload([{"code": "AD-MADE-UP", "evidence": "100% 보장", "reason": "x"}])
    found, stats, _ = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)
    assert found == []
    assert stats["dropped_unknown_code"] == 1


def test_evidence_from_ad_copy_is_accepted():
    raw = payload([{"code": "AD-URGENCY", "evidence": "오늘만 할인", "reason": "긴급성"}])
    found, _, _ = parse_findings(raw, snap("평범한 본문"), "오늘만 할인", Platform.GOOGLE_ADS)
    assert [f.code for f in found] == ["AD-URGENCY"]


def test_duplicate_codes_collapse():
    raw = payload([
        {"code": "AD-GUARANTEE", "evidence": "100% 보장", "reason": "a"},
        {"code": "AD-GUARANTEE", "evidence": "효과 100% 보장", "reason": "b"},
    ])
    found, _, _ = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)
    assert len(found) == 1


def test_findings_are_marked_as_llm_source():
    raw = payload([{"code": "AD-GUARANTEE", "evidence": "100% 보장", "reason": "x"}])
    found, _, _ = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)
    assert found[0].source == Source.LLM


def test_analysis_field_is_captured():
    raw = payload([])
    _, _, analysis = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)
    assert analysis == "검토했습니다."


# --- 파싱 내성 ------------------------------------------------------------

def test_extract_json_from_code_fence():
    raw = '설명입니다\n```json\n{"analysis":"a","findings":[]}\n```\n끝'
    assert _extract_json(raw) == {"analysis": "a", "findings": []}


def test_extract_json_from_bare_text():
    raw = '결과: {"analysis":"a","findings":[]} 이상입니다'
    assert _extract_json(raw) is not None


def test_broken_json_yields_no_findings():
    found, _, _ = parse_findings("완전히 깨진 응답", snap(), "", Platform.GOOGLE_ADS)
    assert found == []


# --- 통합 동작 ------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_returns_error_without_calling_on_fetch_failure():
    broken = PageSnapshot(url="u", final_url="u", status_code=0, fetch_error="타임아웃")
    client = ScriptedLLM(payload([]))
    found, _, _, err = await analyze(broken, "", Platform.GOOGLE_ADS, client)
    assert found == []
    assert err
    assert client.calls == 0  # 페이지를 못 읽었으면 LLM을 부르지 않는다


@pytest.mark.asyncio
async def test_analyze_propagates_llm_error():
    client = ScriptedLLM("", error="LLM 서버에 연결할 수 없습니다")
    found, _, _, err = await analyze(snap(), "", Platform.GOOGLE_ADS, client)
    assert found == []
    assert "연결할 수 없습니다" in err


@pytest.mark.asyncio
async def test_analyze_happy_path():
    client = ScriptedLLM(payload(
        [{"code": "AD-GUARANTEE", "evidence": "100% 보장", "reason": "절대적 표현"}]
    ))
    found, stats, analysis, err = await analyze(snap(), "", Platform.GOOGLE_ADS, client)
    assert err == ""
    assert [f.code for f in found] == ["AD-GUARANTEE"]
    assert analysis
