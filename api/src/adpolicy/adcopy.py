"""광고 문구 자체의 편집 기준 — 랜딩페이지가 아니라 문구를 본다.

Google Ads 반려 사유 중 가장 흔하면서 가장 허무한 축이다. 내용에 아무
문제가 없어도 제목이 한 글자 길면 광고가 나가지 않는다. 그리고 이건 전부
**코드가 100% 결정적으로 판정할 수 있다** — LLM을 부를 이유가 없는 영역이다.

## 한국어에서 제목은 30자가 아니라 15자다

이게 이 모듈에서 제일 중요한 사실이다. Google은 "한국어, 일본어, 중국어와
같은 2바이트 언어의 경우 문자 한 개를 두 자로 계산해 한도를 적용"한다.
그래서 영문 기준 30자인 제목이 한글로는 15자다. 국내 대행사가 영문 기준
30자로 써 두고 왜 반려되는지 모르는 경우가 실제로 많다.

## 여기 없는 것

"여기를 클릭" 같은 일반적 유도 문구는 넣지 않았다. 편집 기준 문서(한국어·
영문 양쪽)를 확인했는데 그런 조항이 없다. 흔히들 있다고 말하지만 문서에
없는 것을 근거로 지적하면 이 도구의 다른 판정까지 의심받는다.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Finding, Source
from .policies import POLICY_BY_CODE

# 영문 기준 한도. 한글은 아래 width()가 2배로 세므로 이 숫자 그대로 쓴다.
HEADLINE_LIMIT = 30
DESCRIPTION_LIMIT = 90


def width(text: str) -> int:
    """Google이 세는 방식의 길이.

    동아시아 전각 문자(한글·한자·가나)는 한 글자를 2로 센다. 이모지도
    전각으로 취급된다 — 실제로 자리를 두 칸 차지하므로 같은 취급이 맞다.
    """
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue        # 조합용 문자는 자리를 차지하지 않는다
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


# --- 문장부호·기호 -----------------------------------------------------------

# 같은 문장부호를 잇달아 쓴 것. 정책 문서가 드는 예시가 정확히 "flowers!!"다.
_REPEATED_PUNCT = re.compile(r"([!?…~])\1+|[!?]{2,}")

# 장식 기호. 시선을 끌려고 넣는 것이고 본래 용도가 아니다.
_DECORATIVE = re.compile(r"[★☆♥♡✔✓✚✦✧❤➤▶◀◆◇●○◎■□※☎♨→←↑↓＊]")
DECORATIVE_MAX = 1        # 하나까지는 구분자로 쓸 수 있다고 본다

# 단어 안에 숫자·기호를 끼워 넣어 필터를 피하는 형태. 정책 예시의 f1owers, fl@wers.
_LEETSPEAK = re.compile(r"[A-Za-z]+[0134@$]+[A-Za-z]{2,}|[가-힣]+[@$*]+[가-힣]+")

# 이모지 대역. 정책 문서가 '이모지'를 이름으로 지목하지는 않는다 — 그래서
# 아래 판정도 '기호 남용'으로 묶고 경고에 그친다. 없는 조항을 지어내지 않는다.
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF⬀-⯿]"
)

# --- 대문자 ------------------------------------------------------------------

# 4자 미만은 약어일 가능성이 높아 세지 않는다(AI, SEO, USB…).
_CAPS_WORD = re.compile(r"\b[A-Z]{4,}\b")
_KNOWN_ACRONYMS = frozenset({
    "HTML", "HTTP", "HTTPS", "JSON", "FAQ", "ASAP", "CEO", "CTO", "NASA",
    "KTX", "LTE", "OLED", "QLED", "NFC", "USIM", "KOSPI", "KOSDAQ",
})

# --- 반복 --------------------------------------------------------------------

_WORD = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")
WORD_REPEAT_MAX = 2       # 세 번째부터 '불필요한 반복'으로 본다

# --- 공백 --------------------------------------------------------------------

_MANY_SPACES = re.compile(r"\S {3,}\S")
# 자간을 벌려 탐지를 피하는 형태: "무 료 상 담". 한 글자 토큰이 잇달아 온다.
_SPACED_OUT = re.compile(r"(?:(?<![가-힣A-Za-z])[가-힣A-Za-z]\s+){3,}")


def _make(code: str, evidence: str, *, severity: str = "") -> Finding:
    p = POLICY_BY_CODE[code]
    return Finding(
        code=p.code,
        title=p.title,
        severity=severity or p.severity,
        enforcement=p.enforcement,
        source=Source.RULE,
        detail=p.description,
        evidence=evidence,
        fix=p.fix,
    )


def check_lengths(headlines: list[str], descriptions: list[str]) -> list[Finding]:
    """글자 수. 한도를 넘으면 내용과 무관하게 광고가 나가지 않는다."""
    findings: list[Finding] = []

    over = [(t, width(t)) for t in headlines if width(t) > HEADLINE_LIMIT]
    if over:
        worst = max(over, key=lambda x: x[1])
        findings.append(_make(
            "AD-HEADLINE-TOO-LONG",
            f"{len(over)}개 초과 — 가장 긴 것 {worst[1]}자(한도 {HEADLINE_LIMIT}자): "
            f"「{worst[0][:40]}」",
        ))

    over = [(t, width(t)) for t in descriptions if width(t) > DESCRIPTION_LIMIT]
    if over:
        worst = max(over, key=lambda x: x[1])
        findings.append(_make(
            "AD-DESCRIPTION-TOO-LONG",
            f"{len(over)}개 초과 — 가장 긴 것 {worst[1]}자(한도 {DESCRIPTION_LIMIT}자): "
            f"「{worst[0][:40]}」",
        ))

    return findings


def check_style(text: str) -> list[Finding]:
    """문장부호·대문자·반복·공백. 길이와 달리 어느 필드든 똑같이 적용된다."""
    findings: list[Finding] = []
    if not text.strip():
        return findings

    # 1) 문장부호·기호
    reasons: list[str] = []
    if m := _REPEATED_PUNCT.search(text):
        reasons.append(f"문장부호 반복 「{m.group(0)}」")
    decorations = _DECORATIVE.findall(text)
    if len(decorations) > DECORATIVE_MAX:
        reasons.append(f"장식 기호 {len(decorations)}개 「{''.join(decorations[:6])}」")
    if m := _LEETSPEAK.search(text):
        reasons.append(f"단어에 기호·숫자 치환 「{m.group(0)}」")
    # 장식 기호와 이모지의 유니코드 대역이 겹친다(★는 U+2605). 위에서 이미
    # 센 것을 여기서 또 세면 같은 글자로 두 번 지적하게 된다.
    emojis = [e for e in _EMOJI.findall(text) if not _DECORATIVE.match(e)]
    if emojis:
        reasons.append(f"이모지 {len(emojis)}개 「{''.join(emojis[:6])}」")
    if reasons:
        findings.append(_make("AD-SYMBOL-ABUSE", " · ".join(reasons)))

    # 2) 대문자 — 한글에는 대소문자가 없으므로 영문 구간만 본다
    caps = [w for w in _CAPS_WORD.findall(text) if w not in _KNOWN_ACRONYMS]
    if caps:
        findings.append(_make("AD-CAPS-ABUSE", f"전부 대문자: {', '.join(caps[:5])}"))

    # 3) 불필요한 반복
    counts: dict[str, int] = {}
    for w in _WORD.findall(text):
        key = w.lower()
        counts[key] = counts.get(key, 0) + 1
    repeated = [(w, n) for w, n in counts.items() if n > WORD_REPEAT_MAX]
    if repeated:
        repeated.sort(key=lambda x: -x[1])
        findings.append(_make(
            "AD-REPETITION",
            " · ".join(f"「{w}」 {n}회" for w, n in repeated[:3]),
        ))

    # 4) 공백
    reasons = []
    if _MANY_SPACES.search(text):
        reasons.append("연속 공백 3칸 이상")
    if m := _SPACED_OUT.search(text):
        reasons.append(f"자간 벌리기 「{m.group(0).strip()}」")
    if reasons:
        findings.append(_make("AD-SPACING-ABUSE", " · ".join(reasons)))

    return findings


# ---------------------------------------------------------------------------
# 광고 문구와 랜딩페이지의 언어
#
# TikTok은 둘 **다** 대상 지역의 허용 언어와 맞아야 한다고 요구한다.
#   "Ad's text/caption matches one acceptable language in all the
#    countries/regions targeted by an ad group."
#   "Language on any landing page or app store page linked to your ad matches
#    the acceptable languages in all the countries/regions targeted by an ad group."
#
# 우리는 대상 지역을 모른다. 그래서 "이 광고는 규정 위반"이라고 단정하지 않고,
# **둘이 서로 다르다**는 사실만 알린다. 둘이 다르면 둘 다 같은 지역의 허용
# 언어에 맞기는 어려우므로 확인할 값어치가 있다. 그 이상은 말하지 않는다.
# ---------------------------------------------------------------------------

_SCRIPTS: list[tuple[str, re.Pattern[str]]] = [
    ("한국어", re.compile(r"[가-힣]")),
    ("일본어", re.compile(r"[ぁ-んァ-ヶ]")),
    ("중국어", re.compile(r"[一-鿿]")),
    ("키릴 문자", re.compile(r"[Ѐ-ӿ]")),
    ("태국어", re.compile(r"[฀-๿]")),
    ("아랍 문자", re.compile(r"[؀-ۿ]")),
    ("로마자", re.compile(r"[A-Za-z]")),
]

# 한국어 페이지에도 브랜드명·버튼 라벨 때문에 로마자가 섞인다. 어느 한쪽이
# 이만큼은 차지해야 "이 언어로 쓰였다"고 말한다.
SCRIPT_DOMINANCE = 0.6
# 광고 제목은 원래 짧다(한글 15자). 너무 높게 잡으면 광고 쪽은 늘 '모름'이 된다.
SCRIPT_MIN_CHARS = 10
# 글자 수를 그냥 세면 로마자로 기울어진다 — 한글 한 글자가 담는 뜻을 로마자는
# 여러 글자로 쓰기 때문이다. 길이를 셀 때와 같은 이유로 동아시아 문자를 2로 센다.
_WIDE_SCRIPTS = frozenset({"한국어", "일본어", "중국어"})


def dominant_script(text: str) -> str:
    """이 글이 주로 어떤 문자로 쓰였는가. 확실하지 않으면 빈 문자열."""
    counts = {
        name: len(pat.findall(text)) * (2 if name in _WIDE_SCRIPTS else 1)
        for name, pat in _SCRIPTS
    }
    total = sum(counts.values())
    if total < SCRIPT_MIN_CHARS:
        return ""
    name, top = max(counts.items(), key=lambda kv: kv[1])
    return name if top / total >= SCRIPT_DOMINANCE else ""


def check_language_match(ad_text: str, page_text: str) -> list[Finding]:
    ad_lang = dominant_script(ad_text)
    page_lang = dominant_script(page_text)
    if not ad_lang or not page_lang or ad_lang == page_lang:
        return []
    return [_make(
        "TT-LANGUAGE-MISMATCH",
        f"광고 문구는 {ad_lang}, 랜딩페이지는 {page_lang}",
    )]


def check(ad_copy: str, headlines: list[str], descriptions: list[str]) -> list[Finding]:
    """문구 점검 전체.

    길이는 **제목·설명을 나눠서 준 경우에만** 본다. 뭉뚱그린 ad_copy 한
    덩어리로는 어느 필드인지 알 수 없고, 모르면서 "30자를 넘었다"고 말하면
    거짓이 된다. 나머지 편집 기준은 어느 쪽이든 그대로 적용한다.
    """
    findings = check_lengths(headlines, descriptions)
    joined = "\n".join([ad_copy, *headlines, *descriptions]).strip()
    return findings + check_style(joined)
