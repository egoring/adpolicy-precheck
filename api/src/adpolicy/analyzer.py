"""LLM 분석 계층 — 맥락 판단을 맡되, 출력은 코드가 검증한다.

이 파일의 핵심은 두 가지다.

1. **Chain-of-Thought 강제**
   7B급 모델에 "JSON만 출력하라"고 하면 사고 과정 없이 결론부터 뱉어
   환각이 크게 는다. 스키마에 `analysis` 필드를 먼저 두어
   모델이 근거를 적은 뒤 판정하도록 순서를 고정했다.

2. **Evidence 역검증** (`verify_evidence`)
   모델이 "페이지에 '100% 보장'이라고 적혀 있다"고 주장해도,
   그 문자열이 실제 페이지 텍스트에 없으면 그 지적은 **폐기**한다.
   판단은 LLM에게, 사실 확인은 코드에게 맡기는 구조다.
"""

from __future__ import annotations

import json
import re
import unicodedata

from .llm import LLMClient
from .models import Finding, PageSnapshot, Platform, Source
from .policies import POLICY_BY_CODE, catalog_for_prompt

MAX_PAGE_CHARS = 6000

SYSTEM_PROMPT = """당신은 온라인 광고 정책 심사를 돕는 분석가입니다.
주어진 광고 문구와 랜딩 페이지 내용을 검토해, 심사에서 반려될 수 있는 항목을 찾습니다.

반드시 지켜야 할 규칙:
1. evidence에는 제공된 텍스트에 **실제로 존재하는 문자열만** 그대로 옮겨 적으세요.
   지어내거나 요약하지 마세요. 근거를 찾을 수 없으면 그 항목은 보고하지 마세요.
2. code는 아래 정책 목록에 있는 코드만 사용하세요.
3. 확실하지 않으면 보고하지 마세요. 놓치는 것보다 잘못 지적하는 쪽이 더 나쁩니다.
4. 반드시 JSON 하나만 출력하세요. 설명을 덧붙이지 마세요."""

USER_TEMPLATE = """## 플랫폼
{platform}

## 검토 가능한 정책 목록
{catalog}

## 광고 문구
{ad_copy}

## 랜딩 페이지
제목: {title}
설명: {meta}

본문:
{page_text}

## 출력 형식
{{
  "analysis": "무엇을 근거로 어떻게 판단했는지 2~4문장. 여기서 먼저 생각을 정리하세요.",
  "findings": [
    {{
      "code": "정책 목록의 코드",
      "evidence": "문구나 본문에 실제로 있는 문자열 그대로",
      "reason": "왜 문제가 되는지 한 문장"
    }}
  ]
}}

지적할 항목이 없으면 findings를 빈 배열로 두세요."""


def _normalize(text: str) -> str:
    """역검증용 정규화.

    공백을 전부 제거한다. 모델은 인용할 때 띄어쓰기를 자주 바꾸는데
    ("100% 보장" → "100 % 보장"), 이건 환각이 아니라 재포맷이므로 흡수해야 한다.
    반대로 글자 자체가 다르면 여전히 걸러진다 — 문자 순서는 보존되기 때문이다.
    한국어는 띄어쓰기 변형이 특히 잦아 이 처리가 실질적으로 중요하다.
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def verify_evidence(evidence: str, haystack: str, *, min_len: int = 4) -> bool:
    """모델이 인용한 evidence가 원문에 실제로 존재하는가.

    이 함수가 이 프로젝트의 핵심 안전장치다. 통과하지 못한 지적은 버린다.
    min_len은 공백 제거 후 기준 — 너무 짧은 조각은 우연히 일치할 수 있다.
    """
    ev = _normalize(evidence)
    if len(ev) < min_len:
        return False
    return ev in _normalize(haystack)


def _extract_json(raw: str) -> dict | None:
    """코드펜스·잡담이 섞여 있어도 JSON 객체를 건져낸다."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = raw[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def build_prompt(snap: PageSnapshot, ad_copy: str, platform: Platform) -> str:
    return USER_TEMPLATE.format(
        platform="Google Ads" if platform == Platform.GOOGLE_ADS else "TikTok Ads",
        catalog=catalog_for_prompt(platform),
        ad_copy=ad_copy.strip() or "(입력 없음)",
        title=snap.title or "(없음)",
        meta=snap.meta_description or "(없음)",
        page_text=snap.text[:MAX_PAGE_CHARS] or "(본문 없음)",
    )


def parse_findings(
    raw: str, snap: PageSnapshot, ad_copy: str, platform: Platform
) -> tuple[list[Finding], dict[str, int], str]:
    """LLM 응답을 Finding으로 변환하며 검증한다.

    Returns: (검증 통과 findings, 폐기 통계, analysis 텍스트)
    """
    stats = {"llm_raw": 0, "dropped_unknown_code": 0,
             "dropped_no_evidence": 0, "dropped_platform": 0}

    data = _extract_json(raw)
    if data is None:
        return [], stats, ""

    analysis = str(data.get("analysis", "")).strip()
    haystack = f"{ad_copy}\n{snap.combined_text}"

    out: list[Finding] = []
    seen: set[str] = set()

    for item in data.get("findings") or []:
        if not isinstance(item, dict):
            continue
        stats["llm_raw"] += 1

        code = str(item.get("code", "")).strip().upper()
        policy = POLICY_BY_CODE.get(code)
        if policy is None:
            stats["dropped_unknown_code"] += 1
            continue
        if platform not in policy.platforms:
            stats["dropped_platform"] += 1
            continue

        evidence = str(item.get("evidence", "")).strip()
        if not verify_evidence(evidence, haystack):
            stats["dropped_no_evidence"] += 1
            continue

        if code in seen:
            continue
        seen.add(code)

        reason = str(item.get("reason", "")).strip()
        out.append(Finding(
            code=policy.code,
            title=policy.title,
            severity=policy.severity,
            source=Source.LLM,
            detail=reason or policy.description,
            evidence=evidence,
            fix=policy.fix,
        ))

    return out, stats, analysis


async def analyze(
    snap: PageSnapshot,
    ad_copy: str,
    platform: Platform,
    client: LLMClient | None = None,
) -> tuple[list[Finding], dict[str, int], str, str]:
    """LLM 분석 실행.

    Returns: (findings, stats, analysis, error). error가 있으면 findings는 비어 있다.
    """
    if snap.fetch_error:
        return [], {}, "", "페이지를 가져오지 못해 LLM 분석을 건너뛰었습니다."

    client = client or LLMClient()
    raw, err = await client.complete(SYSTEM_PROMPT, build_prompt(snap, ad_copy, platform))
    if err:
        return [], {}, "", err

    findings, stats, analysis = parse_findings(raw, snap, ad_copy, platform)
    return findings, stats, analysis, ""
