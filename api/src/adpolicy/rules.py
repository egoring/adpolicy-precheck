"""결정적 룰셋 — 코드가 판정한다.

여기서 나온 Finding은 LLM을 거치지 않으므로 **재현성 100%**다.
같은 페이지를 100번 검사하면 100번 같은 결과가 나온다.

두 종류를 다룬다.
  1. 부재 감지 — 있어야 하는데 없는 것 (실무 반려 사유 1위)
  2. 패턴 매칭 — 명백한 금지 표현

애매한 판단(맥락상 과장인가, 오해 소지가 있는가)은 여기서 하지 않는다.
그건 analyzer.py의 LLM 몫이다.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import Finding, PageSnapshot, Platform, Source
from .policies import POLICY_BY_CODE

# ---------------------------------------------------------------------------
# 탐지 패턴
# ---------------------------------------------------------------------------

PRIVACY_HINTS = [
    "개인정보처리방침", "개인정보 처리방침", "개인정보취급방침",
    "privacy policy", "privacy-policy", "privacy",
]

CONTACT_PATTERNS = [
    re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}"),          # 전화번호
    re.compile(r"1[5-9]\d{2}[-.\s]?\d{4}"),                       # 대표번호
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                       # 이메일
    re.compile(r"사업자\s*등록\s*번호"),
    re.compile(r"\d{3}-\d{2}-\d{5}"),                             # 사업자번호 형식
]

PRICE_PATTERNS = [
    re.compile(r"\d[\d,]*\s*원"),
    re.compile(r"₩\s*\d[\d,]*"),
    re.compile(r"\$\s*\d[\d,.]*"),
    re.compile(r"무료|free\b", re.IGNORECASE),
]

COMMERCE_INTENT = [
    "구매", "주문", "결제", "장바구니", "신청하기", "가입하기",
    "buy now", "add to cart", "checkout", "order",
]

PII_INPUT_TYPES = {"email", "tel", "password"}
PII_FIELD_HINTS = ["이름", "성함", "연락처", "전화", "이메일", "생년월일", "주소"]

# 패턴 → 정책 코드. 각 항목은 (코드, 정규식) 쌍.
CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AD-GUARANTEE", re.compile(
        r"100\s*%\s*(보장|성공|환급)|완치|무조건\s*(성공|보장)|반드시\s*낫", re.IGNORECASE)),
    ("AD-MEDICAL", re.compile(
        r"(암|당뇨|고혈압|아토피|탈모|불면증)\s*(치료|완치|예방)|질병\s*치료|의학적으로\s*입증")),
    ("AD-FINANCIAL", re.compile(
        r"원금\s*보장|수익\s*보장|확정\s*수익|월\s*\d+\s*%\s*수익|손실\s*없")),
    ("AD-URGENCY", re.compile(
        r"단\s*\d+\s*(자리|명)\s*남|오늘\s*만|마감\s*임박|지금\s*아니면")),
    ("AD-SUPERLATIVE", re.compile(
        r"(업계|국내|세계)\s*(1위|최고|최초|유일)|넘버\s*원|No\.?\s*1", re.IGNORECASE)),
    ("AD-PERSONAL", re.compile(
        r"당신의\s*(우울|비만|탈모|빚|파산|질병)|당신은\s*\S*\s*환자")),
    ("AD-BEFORE-AFTER", re.compile(
        r"비포\s*[&·/]?\s*애프터|before\s*[&/]\s*after|전\s*후\s*사진", re.IGNORECASE)),
    ("AD-ADULT", re.compile(r"성인용품|19금|야한|은밀한\s*만남")),
    ("AD-GAMBLING", re.compile(r"토토|바카라|슬롯머신|배팅\s*사이트|카지노")),
    ("AD-COUNTERFEIT", re.compile(r"정품\s*급|이미테이션|짝퉁|A급\s*미러")),
]

THIN_CONTENT_CHARS = 300


def _make(code: str, *, evidence: str = "", detail_suffix: str = "") -> Finding:
    p = POLICY_BY_CODE[code]
    return Finding(
        code=p.code,
        title=p.title,
        severity=p.severity,
        source=Source.RULE,
        detail=p.description + (f" {detail_suffix}" if detail_suffix else ""),
        evidence=evidence,
        fix=p.fix,
    )


def _contains_any(haystack: str, needles: list[str]) -> str:
    low = haystack.lower()
    for n in needles:
        if n.lower() in low:
            return n
    return ""


def _search_any(text: str, patterns: list[re.Pattern[str]]) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(0)
    return ""


# ---------------------------------------------------------------------------
# 부재 감지
# ---------------------------------------------------------------------------

def check_absence(snap: PageSnapshot, ad_copy: str) -> list[Finding]:
    findings: list[Finding] = []

    if snap.fetch_error or snap.status_code >= 400:
        reason = snap.fetch_error or f"HTTP {snap.status_code}"
        findings.append(_make("LP-UNREACHABLE", evidence=reason))
        return findings  # 페이지를 못 읽었으면 나머지 판정은 의미가 없다

    text = snap.combined_text
    haystack = text + "\n" + " ".join(snap.links)

    collects_pii = snap.has_form and (
        bool(PII_INPUT_TYPES & set(snap.form_input_types))
        or bool(_contains_any(text, PII_FIELD_HINTS))
    )

    if collects_pii and not _contains_any(haystack, PRIVACY_HINTS):
        findings.append(_make(
            "LP-PRIVACY",
            detail_suffix="입력 폼이 감지되었으나 방침 링크를 찾지 못했습니다.",
        ))

    if not _search_any(text, CONTACT_PATTERNS):
        findings.append(_make("LP-CONTACT"))

    has_commerce_intent = bool(_contains_any(text + " " + ad_copy, COMMERCE_INTENT))
    if has_commerce_intent and not _search_any(text, PRICE_PATTERNS):
        findings.append(_make(
            "LP-PRICE",
            detail_suffix="구매 유도 문구는 있으나 가격 표기를 찾지 못했습니다.",
        ))

    if len(snap.text.strip()) < THIN_CONTENT_CHARS:
        findings.append(_make(
            "LP-THIN",
            evidence=f"본문 {len(snap.text.strip())}자",
        ))

    return findings


# ---------------------------------------------------------------------------
# 기술 요건
# ---------------------------------------------------------------------------

def check_technical(snap: PageSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    if snap.fetch_error:
        return findings

    parsed_final = urlparse(snap.final_url)
    parsed_orig = urlparse(snap.url)

    if parsed_final.scheme != "https" and snap.has_form:
        findings.append(_make("TECH-HTTPS", evidence=snap.final_url))

    if parsed_orig.netloc and parsed_final.netloc and parsed_orig.netloc != parsed_final.netloc:
        findings.append(_make(
            "TECH-REDIRECT",
            evidence=f"{parsed_orig.netloc} → {parsed_final.netloc}",
        ))

    if snap.image_count >= 3 and not any(a.strip() for a in snap.image_alts):
        findings.append(_make("TECH-NO-ALT", evidence=f"이미지 {snap.image_count}개"))

    return findings


# ---------------------------------------------------------------------------
# 금지 표현 패턴
# ---------------------------------------------------------------------------

def check_content_patterns(
    snap: PageSnapshot, ad_copy: str, platform: Platform
) -> list[Finding]:
    findings: list[Finding] = []
    haystack = f"{ad_copy}\n{snap.combined_text}"

    for code, pattern in CONTENT_PATTERNS:
        policy = POLICY_BY_CODE[code]
        if platform not in policy.platforms:
            continue
        m = pattern.search(haystack)
        if m:
            findings.append(_make(code, evidence=m.group(0).strip()))

    return findings


def run_all(snap: PageSnapshot, ad_copy: str, platform: Platform) -> list[Finding]:
    """결정적 룰 전체 실행."""
    findings = check_absence(snap, ad_copy)
    if any(f.code == "LP-UNREACHABLE" for f in findings):
        return findings
    findings += check_technical(snap)
    findings += check_content_patterns(snap, ad_copy, platform)
    return findings
