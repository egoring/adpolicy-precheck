"""클로킹 탐지 — 심사 시스템과 사용자에게 다른 콘텐츠가 나가는지 확인한다.

**방향을 분명히 해둔다.** 이 모듈은 클로킹을 *하는* 코드가 아니라
클로킹이 *일어나고 있는지 잡아내는* 코드다. 광고 플랫폼이 하는 일과 같은 쪽이며,
대행사 입장에서도 필요하다 — 클라이언트 페이지가 의도치 않게 크롤러에
다른 내용을 주면 대행사 계정까지 함께 제재되기 때문이다.

의도적 클로킹만 문제가 아니다. 실무에서 더 흔한 건 **사고**다.
  - WAF·CDN의 봇 차단 규칙이 심사 크롤러를 막음
  - 지역 기반 리디렉션으로 크롤러 위치에 따라 다른 페이지가 나감
  - JS 전용 렌더링이라 크롤러에는 빈 페이지가 보임
  - SEO 목적으로 robots.txt를 막다가 AdsBot까지 차단

## 왜 Googlebot UA를 흉내내지 않는가

크롤러를 사칭해 페이지를 요청하면 그 자체로 회색지대이고, 애초에 필요도 없다.
**서로 다른 클라이언트 프로필 간의 콘텐츠 차이**만 보면 UA 분기는 그대로 드러난다.
오히려 정직하게 봇임을 밝힌 UA가 더 좋은 탐지 도구다 — 사이트가 "봇"을 다르게
대우한다면 그게 바로 우리가 찾는 행동이기 때문이다.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import httpx
from selectolax.parser import HTMLParser

from .fetcher import (
    USER_AGENT,
    UnsafeURLError,
    _extract,
    assert_safe_url,
    registrable_domain,
    safe_client,
    safe_get,
)
from .models import PageSnapshot

# 서로 구분되는 클라이언트 프로필. 실제 크롤러를 사칭하지 않는다.
CLIENT_PROFILES: dict[str, str] = {
    "desktop": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "mobile": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "bot": USER_AGENT,  # 정직하게 봇임을 밝힌다
}

# 이 값 미만이면 "실질적으로 다른 콘텐츠"로 본다.
SIMILARITY_BLOCK = 0.60
SIMILARITY_WARN = 0.85
MIN_TEXT_FOR_COMPARISON = 200

# UA를 읽는 코드. 이것만으로는 아무 의미가 없다 — GA·gtag 스니펫, 반응형
# 처리, 브라우저 호환 코드에 전부 들어 있다. 이걸 그대로 지적으로 올리면
# 거의 모든 실사이트에서 경고가 뜨고, 그러면 아무도 이 도구를 안 믿는다.
UA_READ_PATTERNS = [
    re.compile(r"navigator\.userAgent", re.IGNORECASE),
    re.compile(r"navigator\.webdriver", re.IGNORECASE),
    re.compile(r"HTTP_USER_AGENT", re.IGNORECASE),
]

# UA를 읽은 **같은 스크립트 안에서** 콘텐츠나 행선지를 바꾸는가.
# 이 둘이 같이 있을 때만 '분기'라고 부를 수 있다.
UA_BRANCH_ACTIONS = re.compile(
    r"location\s*\.\s*(?:replace|assign|href)"
    r"|location\s*=\s*[\"']"
    r"|document\.write"
    r"|\.innerHTML\s*="
    r"|document\.body\s*\.\s*(?:innerHTML|replaceChildren)",
    re.IGNORECASE,
)

# robots.txt에서 확인할 심사 크롤러
# **AdsBot만** 넣는다. AdsBot-Google은 전역 `User-agent: *` 규칙도,
# googlebot 규칙도 따르지 않는다. googlebot을 여기 넣으면
# "SEO용으로 Googlebot만 막은 사이트"가 광고 심사 차단으로 잘못 잡힌다.
AD_CRAWLERS = ["adsbot-google", "adsbot-google-mobile"]

AUTO_DOWNLOAD_PATTERNS = [
    re.compile(r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]+\.(zip|exe|dmg|apk|msi)",
               re.IGNORECASE),
    re.compile(r"location\.(href|replace)\s*=\s*[\"'][^\"']+\.(zip|exe|dmg|apk|msi)",
               re.IGNORECASE),
]


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def similarity(a: str, b: str) -> float:
    """두 페이지 본문의 유사도 (0.0 ~ 1.0)."""
    na, nb = _normalize_for_compare(a), _normalize_for_compare(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    # 긴 문서에서 SequenceMatcher가 느려지므로 앞부분만 비교한다.
    #
    # autojunk=False가 **반드시** 필요하다. 기본값(True)은 200자가 넘는 쪽에서
    # 1% 넘게 나오는 요소를 '잡음'으로 보고 빼 버리는데, 상품 목록·후기처럼
    # 같은 구조가 반복되는 페이지에서는 거의 모든 글자가 그 조건에 걸린다.
    # 그러면 90% 닮은 두 페이지의 유사도가 2%로 나오고, 멀쩡한 쇼핑몰이
    # '클로킹(계정 정지급)'으로 보고된다. 실제로 그렇게 나왔다.
    return difflib.SequenceMatcher(None, na[:8000], nb[:8000], autojunk=False).ratio()


def detect_ua_sniffing(raw_html: str) -> str:
    """UA를 읽고 **그 결과로 내용을 바꾸는** 스크립트가 있으면 근거를 돌려준다.

    'navigator.userAgent가 있다'만으로는 지적하지 않는다. Google Analytics
    스니펫 한 줄이면 걸리기 때문이다. UA를 읽은 같은 스크립트 블록 안에서
    행선지나 DOM을 바꿀 때만 분기로 본다.
    """
    for block in _SCRIPT_BLOCK.findall(raw_html):
        read = next((m for pat in UA_READ_PATTERNS if (m := pat.search(block))), None)
        if not read:
            continue
        if action := UA_BRANCH_ACTIONS.search(block):
            return f"{read.group(0)} → {action.group(0)}"

    # 서버 코드가 응답에 그대로 섞여 나온 경우. 정상 페이지에서는 일어나지
    # 않는 일이고, 그 안에 UA 분기가 보이면 그것만으로 근거가 된다.
    for block in _PHP_BLOCK.findall(raw_html):
        if m := re.search(r"HTTP_USER_AGENT", block, re.IGNORECASE):
            return f"응답에 노출된 서버 코드에서 {m.group(0)} 분기"
    return ""


# ---------------------------------------------------------------------------
# HTML만 보고 알 수 있는 우회 신호
#
# 여기 있는 것들은 추가 요청 없이 이미 받아 온 HTML에서 읽어낸다. 점검이
# 느려지지 않는 대신, 렌더링(JS 실행) 후에야 드러나는 클로킹은 못 잡는다.
# 그건 브라우저를 띄워야 하는 일이고 지금은 범위 밖이다.
# ---------------------------------------------------------------------------

# "0; url=..." 처럼 지체 없이 넘어가는 것만 본다. 30초짜리 안내 페이지는 아니다.
_META_REFRESH = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*"""
    r"""["']\s*(\d+)\s*;\s*url\s*=\s*([^"'>]+)""",
    re.IGNORECASE,
)
META_REFRESH_MAX_DELAY = 5

# 진입 즉시 주소를 바꾸는 형태만 본다. location 대입은 클릭 핸들러에서도
# 흔히 쓰여서, 그냥 'location.href'를 찾으면 멀쩡한 쇼핑몰이 다 걸린다.
_JS_REDIRECT = re.compile(
    r"""(?:window\.)?location(?:\s*\.\s*(?:replace|assign))?\s*"""
    r"""(?:\(\s*|\.\s*href\s*=\s*|=\s*)["'](https?://[^"']+)["']""",
    re.IGNORECASE,
)
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_PHP_BLOCK = re.compile(r"<\?php(.*?)\?>", re.IGNORECASE | re.DOTALL)
# 이 말들이 있는 스크립트는 '사용자가 뭔가 했을 때' 도는 코드다. 통째로 건너뛴다.
# 앞서 "</script> 직전이면 즉시 실행"이라는 기준을 썼다가, addEventListener
# 콜백의 닫는 괄호가 정확히 그 모양이라 클릭 핸들러를 자동 이동으로 잡았다.
_EVENT_BOUND = re.compile(
    r"addEventListener|attachEvent|onclick|onsubmit|\.click\s*\(|\.on\s*\(|jQuery|\$\(",
    re.IGNORECASE,
)

# 폭이 없어 화면에 안 보이는 문자들. 금지어 사이에 끼워 넣어 탐지를 피하는 데 쓰인다.
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")
ZERO_WIDTH_MIN = 3

# 인라인 스타일로 숨긴 요소
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?!\.)"
    r"|font-size\s*:\s*0|text-indent\s*:\s*-\s*\d{3,}|left\s*:\s*-\s*\d{4,}",
    re.IGNORECASE,
)
HIDDEN_TEXT_MIN_CHARS = 20

# 본문을 덮는 레이어. 세 조건이 다 맞을 때만 본다 — 하나만 보면 흔한 배너가 걸린다.
_OVERLAY_FIXED = re.compile(r"position\s*:\s*(?:fixed|absolute)", re.IGNORECASE)
_OVERLAY_FULL_W = re.compile(r"width\s*:\s*(?:100%|100vw)", re.IGNORECASE)
_OVERLAY_FULL_H = re.compile(r"height\s*:\s*(?:100%|100vh)", re.IGNORECASE)
_SCROLL_LOCK = re.compile(
    r"(?:body|html)[^{]{0,40}\{[^}]{0,200}overflow\s*:\s*hidden", re.IGNORECASE
)

BRIDGE_MAX_CHARS = 400

# ---------------------------------------------------------------------------
# 본문을 서버에서 끌어와 채우는 구조
#
# 이게 현재 프로필 비교의 사각지대다. JS로 콘텐츠를 갈아끼우면 데스크톱·모바일·봇
# **세 프로필이 전부 똑같은 빈 껍데기**를 받는다. 유사도 100%라 "정상"으로 나온다.
# 실제 내용은 그 뒤 서버가 정하고, 서버는 언제든 다른 걸 줄 수 있다.
#
# 여기서 증명할 수 있는 건 "그렇게 바꿔치기했다"가 아니라 **"바꿔치기할 수 있는
# 구조이고, 심사 대상 본문이 응답에 없다"**까지다. 그 이상을 말하면 거짓이 된다.
# ---------------------------------------------------------------------------

_FETCH_CALLS = re.compile(
    r"\bfetch\s*\(|XMLHttpRequest|\$\.(?:ajax|get|post|getJSON)\s*\(|axios\s*\.\s*\w+\s*\("
    r"|\.send\s*\(\s*\)|new\s+EventSource\s*\(",
    re.IGNORECASE,
)
# 받아온 걸 화면에 꽂는 지점. 이게 없으면 그냥 통계 전송일 수 있다.
_DOM_WRITES = re.compile(
    r"\.innerHTML\s*=|\.outerHTML\s*=|document\.write\s*\(|insertAdjacentHTML\s*\("
    r"|\.html\s*\(|createContextualFragment\s*\(",
    re.IGNORECASE,
)
# 국내 랜딩페이지에서 본문을 내려주는 흔한 이름들. 있으면 근거로 같이 보여준다.
_CONTENT_ENDPOINT = re.compile(
    r"""["'/]([\w./-]*(?:get(?:Value|Config|Content|Contents|Data|Info|Html|Text|Page|List)"""
    r"""|(?:proc|view|lp|ajax|data|content|config)\.(?:php|asp|jsp|do))[\w./?=&-]*)""",
    re.IGNORECASE,
)
# 감춘 코드. 정상 페이지에는 거의 없고, 있으면 십중팔구 탐지를 피하려는 것이다.
_OBFUSCATED = [
    ("eval(atob(...))", re.compile(r"eval\s*\(\s*(?:atob|unescape|decodeURIComponent)\s*\(",
                                   re.IGNORECASE)),
    ("new Function(atob(...))", re.compile(
        r"new\s+Function\s*\(\s*(?:atob|unescape|decodeURIComponent)\s*\(", re.IGNORECASE)),
    ("String.fromCharCode 체인", re.compile(
        r"String\.fromCharCode\s*\(\s*\d+\s*(?:,\s*\d+\s*){15,}\)")),
    ("긴 \\x 이스케이프", re.compile(r"(?:\\x[0-9a-fA-F]{2}){40,}")),
    ("document.write(unescape(...))", re.compile(
        r"document\.write\s*\(\s*unescape\s*\(", re.IGNORECASE)),
]

# 이 길이 미만이면 "심사 대상 본문이 응답에 없다"로 본다.
#
# 처음에 600으로 뒀다가 본문 400자짜리 정상 쇼핑몰(제품 설명은 HTML에 있고
# 후기만 fetch로 붙이는 흔한 구조)이 걸렸다. 잡아야 하는 건 껍데기뿐인
# 페이지이고, 진짜 클로킹 셸은 본문이 0~100자다. 콘텐츠 부족 판정선과
# 같은 값으로 맞춰, **이미 "내용이 없다"고 본 페이지에서만** 추가로 본다.
DYNAMIC_BODY_MAX_CHARS = 300


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    # lstrip("www.")는 문자 집합을 벗겨서 "wwe.com"의 w까지 먹는다.
    return host[4:] if host.startswith("www.") else host


# 뒤 두 칸이 통째로 접미사인 것들. 이걸 모르면 co.kr 도메인이 전부 같은
# 사이트로 묶여 국내 페이지의 도메인 이동을 하나도 못 잡는다 —
# livelogin.co.kr 과 livetopic.co.kr 이 둘 다 'co.kr'이 된다. 실제로 놓쳤다.
# 같은 기준을 rules도 쓴다. 두 곳이 따로 판단하면 한쪽만 www 이동을
# 지적하는, 설명할 수 없는 결과가 나온다.
_registrable = registrable_domain


def detect_meta_refresh(raw_html: str, base_url: str) -> str:
    """사용자 동작 없이 넘어가는 meta refresh. 목적지가 같은 페이지면 무시한다."""
    m = _META_REFRESH.search(raw_html)
    if not m:
        return ""
    try:
        delay = int(m.group(1))
    except ValueError:
        return ""
    if delay > META_REFRESH_MAX_DELAY:
        return ""
    target = urljoin(base_url, m.group(2).strip().strip("'\""))
    if target.rstrip("/") == base_url.rstrip("/"):
        return ""  # 자기 자신 새로고침
    return f"meta refresh {delay}초 → {target[:120]}"


def detect_js_redirect(raw_html: str) -> str:
    """진입 즉시 다른 주소로 넘기는 스크립트.

    이벤트 바인딩이 들어 있는 스크립트 블록은 통째로 건너뛴다. 그런 블록의
    location 대입은 "버튼을 누르면 장바구니로" 같은 정상 동작이다.
    """
    for block in _SCRIPT_BLOCK.findall(raw_html):
        if _EVENT_BOUND.search(block):
            continue
        if (m := _JS_REDIRECT.search(block)):
            return m.group(1)[:120]
    return ""


def detect_cross_domain_landing(url: str, final_url: str) -> str:
    """광고가 가리킨 주소와 실제로 도착한 도메인이 다른 경우.

    추가 요청이 필요 없다 — 이미 받아 온 응답의 final_url만 보면 된다.
    """
    start, end = _host(url), _host(final_url)
    if not start or not end:
        return ""
    if _registrable(start) == _registrable(end):
        return ""
    return f"{start} → {end}"


def detect_zero_width(text: str) -> str:
    hits = _ZERO_WIDTH.findall(text)
    if len(hits) < ZERO_WIDTH_MIN:
        return ""
    names = {"​": "ZWSP", "‌": "ZWNJ", "‍": "ZWJ",
             "⁠": "WJ", "﻿": "BOM", "­": "SHY"}
    kinds = sorted({names.get(h, "?") for h in hits})
    return f"보이지 않는 문자 {len(hits)}개 ({', '.join(kinds)})"


def detect_hidden_text(raw_html: str, keywords: list[re.Pattern[str]]) -> str:
    """숨긴 요소 안에 **정책에 걸릴 문구**가 들어 있는 경우만 본다.

    그냥 display:none을 세면 탭·모달·드롭다운이 있는 멀쩡한 페이지가 전부
    걸린다. 정책이 금지하는 건 '숨기는 것' 자체가 아니라 "정책 위반 콘텐츠를
    숨기기 위해" 조작하는 것이다. 그래서 숨긴 텍스트에 룰 패턴이 걸릴 때만
    지적한다.
    """
    tree = HTMLParser(raw_html)
    for node in tree.css("[style]"):
        style = node.attributes.get("style") or ""
        if not _HIDDEN_STYLE.search(style):
            continue
        text = node.text(separator=" ", strip=True)
        if len(text) < HIDDEN_TEXT_MIN_CHARS:
            continue
        for pat in keywords:
            if (m := pat.search(text)):
                return f"숨겨진 문구 '{m.group(0)[:40]}'"
    return ""


def detect_blocking_overlay(raw_html: str) -> str:
    """본문을 덮는 전면 레이어 + 스크롤 잠금이 함께 있을 때만."""
    if not _SCROLL_LOCK.search(raw_html):
        return ""
    tree = HTMLParser(raw_html)
    for node in tree.css("[style]"):
        style = node.attributes.get("style") or ""
        if (_OVERLAY_FIXED.search(style)
                and _OVERLAY_FULL_W.search(style)
                and _OVERLAY_FULL_H.search(style)):
            return f"전면 레이어 style='{style[:80]}'"
    return ""


def detect_framed_content(raw_html: str, base_url: str) -> str:
    """다른 도메인 콘텐츠를 프레임으로 감싼 경우."""
    tree = HTMLParser(raw_html)
    if tree.css_first("frameset") is not None:
        return "frameset 사용"
    here = _registrable(_host(base_url))
    for node in tree.css("iframe"):
        src = node.attributes.get("src") or ""
        if not src.startswith(("http://", "https://")):
            continue
        there = _registrable(_host(src))
        if not there or there == here:
            continue
        style = (node.attributes.get("style") or "").lower()
        w = (node.attributes.get("width") or "").lower()
        h = (node.attributes.get("height") or "").lower()
        full = (
            ("100%" in w and "100%" in h)
            or (_OVERLAY_FULL_W.search(style) and _OVERLAY_FULL_H.search(style))
        )
        if full:
            return f"iframe으로 {there} 콘텐츠를 전체 화면에 표시"
    return ""


def detect_bridge_page(snap: PageSnapshot) -> str:
    """본문은 거의 없고 밖으로 내보내는 링크만 있는 중간 페이지."""
    if len(snap.text) > BRIDGE_MAX_CHARS:
        return ""
    here = _registrable(_host(snap.final_url))
    outbound = inbound = 0
    target = ""
    for href in snap.links:
        if not href.startswith(("http://", "https://")):
            inbound += 1
            continue
        there = _registrable(_host(href))
        if there and there != here:
            outbound += 1
            target = target or there
        else:
            inbound += 1
    if outbound == 0 or outbound < max(1, inbound):
        return ""
    return f"본문 {len(snap.text)}자 · 외부 링크 {outbound}개(예: {target})"


def detect_server_rendered_body(raw_html: str, snap: PageSnapshot) -> str:
    """본문이 응답에 없고, 서버에서 받아 DOM에 꽂는 코드가 있는가.

    둘 다 있어야 인정한다. fetch만 보면 통계·챗봇·폼 전송이 다 걸리고,
    innerHTML만 보면 요즘 사이트가 전부 걸린다. **본문이 비어 있다**는
    조건이 핵심이다 — 심사 크롤러가 볼 게 없다는 뜻이기 때문이다.
    """
    if len(snap.text) > DYNAMIC_BODY_MAX_CHARS:
        return ""  # 본문이 응답에 이미 들어 있다. 나중에 뭘 더 붙이든 심사는 된다.
    if not _FETCH_CALLS.search(raw_html) or not _DOM_WRITES.search(raw_html):
        return ""

    parts = [f"본문 {len(snap.text)}자인데 서버에서 받아 화면에 꽂는 코드가 있음"]
    if (m := _CONTENT_ENDPOINT.search(raw_html)):
        parts.append(f"호출 대상 '{m.group(1)[:60]}'")
    return " · ".join(parts)


def detect_obfuscated_script(raw_html: str) -> str:
    """감춘 코드. 무엇을 하는지는 모르지만, 감췄다는 사실 자체가 근거다."""
    for name, pat in _OBFUSCATED:
        if pat.search(raw_html):
            return name
    return ""


# ---------------------------------------------------------------------------
# 브라우저에서 광고 파라미터를 보고 갈아끼우는 경우
#
# probe_params는 **서버가** 다른 HTML을 줄 때만 잡는다. 요즘 흔한 쪽은 서버는
# 늘 같은 HTML을 주고 브라우저에서 gclid를 읽어 내용을 바꾸는 방식이다.
# 그러면 파라미터를 어떻게 바꿔 찔러도 응답 바이트가 똑같아서 유사도 100%가
# 나온다. 실제로 그렇게 나온다 — 확인했다.
#
# HTML만으로 증명되는 것은 **"그런 구조가 있다"**까지다. 그래서 기본은 경고이고,
# 갈아끼우는 내용이 스크립트 안에 문자열로 박혀 있고 그게 정책 위반 문구이면
# 그때는 실제 문구를 근거로 보여준다.
# ---------------------------------------------------------------------------

# 스크립트 안에 광고 클릭 파라미터 이름이 문자열로 등장하는가.
_AD_PARAM_NAME = re.compile(
    r"""['"](gclid|gbraid|wbraid|dclid|ttclid|fbclid|msclkid|yclid"""
    r"""|utm_source|utm_medium|utm_campaign)['"]""",
    re.IGNORECASE,
)
# 주소에서 값을 읽는 코드.
_URL_PARAM_READ = re.compile(
    r"URLSearchParams|location\.search|location\.href|document\.referrer"
    r"|\.searchParams", re.IGNORECASE,
)
# 읽은 결과로 **보이는 내용**을 바꾸는가.
#
# `.value =`(폼 히든 필드), document.cookie, dataLayer/gtag는 일부러 뺐다.
# gclid를 히든 필드에 넣어 전환 추적에 쓰는 것은 표준 관행이고 위반이 아니다.
# 그걸 잡으면 전환 추적을 제대로 붙인 광고주가 전부 걸린다.
_PARAM_CONTENT_ACTION = re.compile(
    r"\.innerHTML\s*=|\.outerHTML\s*=|document\.write\s*\(|insertAdjacentHTML\s*\("
    r"|replaceChildren\s*\(|location\s*\.\s*(?:replace|assign)\s*\("
    r"|location\s*\.\s*href\s*=|location\s*=\s*[\"']",
    re.IGNORECASE,
)
# 문자열 리터럴. **길이 조건을 정규식 안에 넣으면 안 된다** — 짧은 문자열을
# 건너뛰면서 따옴표 짝이 어긋나, `'gclid')) { document.getElementById('` 같은
# **코드 조각**을 문자열로 읽는다. 실제로 그렇게 읽고 있었다.
# 순서대로 전부 집고 길이는 나중에 거른다.
_STRING_LITERAL = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"")
LITERAL_MIN_CHARS = 12


def detect_param_branch_script(raw_html: str, patterns: list[re.Pattern[str]]) -> str:
    """광고 파라미터를 읽어 화면을 바꾸는 스크립트.

    patterns: 정책 위반 문구 패턴. 갈아끼우는 내용이 문자열로 박혀 있고 그게
      여기 걸리면 실제 문구를 근거로 돌려준다 — 구조만 있는 것과 내용까지
      확인된 것은 말할 수 있는 범위가 다르다.
    """
    for block in _SCRIPT_BLOCK.findall(raw_html):
        param = _AD_PARAM_NAME.search(block)
        if not param or not _URL_PARAM_READ.search(block):
            continue
        action = _PARAM_CONTENT_ACTION.search(block)
        if not action:
            continue

        # 갈아끼우려는 내용이 스크립트에 그대로 있으면 그것부터 본다.
        literals = " ".join(
            text for m in _STRING_LITERAL.finditer(block)
            if len(text := (m.group(1) or m.group(2) or "")) >= LITERAL_MIN_CHARS
        )
        for pat in patterns:
            if hit := pat.search(literals):
                return (
                    f"{param.group(1)}가 있을 때 화면을 바꾸는 스크립트 — "
                    f"바꿔 넣는 내용에 「{hit.group(0)[:40]}」"
                )
        return (
            f"{param.group(1)}를 읽어 {action.group(0).strip()} 로 화면을 바꿉니다"
        )
    return ""


def content_fingerprint(snap: PageSnapshot) -> str:
    """심사 시점의 본문 지문.

    다음에 같은 URL을 점검할 때 이 값을 넘기면 **그 사이 내용이 바뀌었는지**
    알 수 있다. TikTok은 "캠페인을 생성한 후 광고의 랜딩 페이지에 변경 사항을
    적용했습니다"를 계정 정지 사유로 명시한다 — 심사만 통과시키고 갈아끼우는
    수법이고, 한 번의 점검만으로는 절대 잡을 수 없다.

    공백과 대소문자는 무시한다. 오타 수정이나 줄바꿈 정리로 경보가 뜨면
    아무도 안 쓰게 된다.
    """
    body = _normalize_for_compare(f"{snap.title}\n{snap.text}\n{snap.ocr_text}")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def detect_auto_download(raw_html: str) -> str:
    for pat in AUTO_DOWNLOAD_PATTERNS:
        m = pat.search(raw_html)
        if m:
            return m.group(0)[:120]
    return ""


async def _fetch_as(url: str, ua: str) -> tuple[PageSnapshot, str]:
    """UA 하나로 한 번 가져온다. 실패는 예외가 아니라 fetch_error로 돌려준다."""
    try:
        headers = {"User-Agent": ua, "Accept-Language": "ko,en;q=0.8"}
        async with safe_client(headers=headers) as client:
            # safe_get이 홉마다 SSRF 가드를 다시 걸고 본문을 상한에서 끊는다
            resp, content, final_url = await safe_get(client, url)
            html = content.decode(resp.encoding or "utf-8", errors="replace")
            snap = _extract(html, url, final_url, resp.status_code)
            if resp.status_code >= 400:
                snap.fetch_error = f"HTTP {resp.status_code}"
            return snap, html
    except UnsafeURLError as exc:
        return PageSnapshot(url=url, final_url=url, status_code=0,
                            fetch_error=str(exc)), ""
    except httpx.HTTPError as exc:
        return PageSnapshot(url=url, final_url=url, status_code=0,
                            fetch_error=f"요청 실패: {type(exc).__name__}"), ""


async def probe_profiles(url: str) -> tuple[dict[str, PageSnapshot], dict[str, str]]:
    """여러 클라이언트 프로필로 같은 URL을 가져온다.

    Returns: (프로필별 스냅샷, 프로필별 원본 HTML)
    """
    snaps: dict[str, PageSnapshot] = {}
    raws: dict[str, str] = {}

    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        snaps["desktop"] = PageSnapshot(
            url=url, final_url=url, status_code=0, fetch_error=str(exc)
        )
        return snaps, raws

    # 순차로 돌면 응답 시간이 프로필 수만큼 곱해진다. 문서에도 "동시에
    # 가져온다"고 써 있으니 실제로 그렇게 해야 한다.
    names = list(CLIENT_PROFILES)
    results = await asyncio.gather(
        *(_fetch_as(url, CLIENT_PROFILES[n]) for n in names)
    )
    for name, (snap, html) in zip(names, results, strict=True):
        snaps[name] = snap
        if html:
            raws[name] = html

    # 봇 프로필만 실패했으면 한 번 더 준다. 순간 장애 한 번으로 계정 정지급
    # 판정을 확정하는 것이 이 검사에서 가장 비싼 오탐이다.
    bot = snaps.get("bot")
    if bot is not None and bot.fetch_error and not snaps.get("desktop", bot).fetch_error:
        retry, html = await _fetch_as(url, CLIENT_PROFILES["bot"])
        if not retry.fetch_error:
            snaps["bot"] = retry
            if html:
                raws["bot"] = html

    return snaps, raws


# ---------------------------------------------------------------------------
# 광고 파라미터로 갈라지는가
#
# UA 분기는 위에서 잡는다. 그런데 실무에서 더 자주 쓰이는 건 **쿼리 파라미터**다.
# 심사 크롤러는 광고를 클릭해서 오지 않으므로 최종 URL에 gclid가 붙지 않는다.
# 그래서 "gclid가 있으면 진짜 페이지, 없으면 얌전한 페이지"로 짜두면 세 프로필을
# 아무리 비교해도 전부 얌전한 쪽만 본다. UA 축과 완전히 다른 사각지대다.
#
# 여기서 쓰는 클릭 ID는 **우리가 만든 가짜 값**이다. 실제 클릭 ID를 쓰면 남의
# 광고 통계를 더럽히게 된다. 형식만 그럴듯하면 분기 코드는 똑같이 반응한다.
# ---------------------------------------------------------------------------

_PROBE_TOKEN = "adpolicyPrecheckProbe"

# 이미 붙어 있으면 떼어낸다 — 사용자가 gclid가 달린 URL을 그대로 붙여넣는
# 경우가 흔한데, 그러면 "파라미터 없는 쪽"이 없어져 비교 자체가 성립하지 않는다.
AD_PARAM_KEYS = frozenset({
    "gclid", "gbraid", "wbraid", "dclid", "gad_source", "gclsrc",
    "ttclid", "fbclid", "msclkid", "yclid", "li_fat_id", "twclid",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
})

PARAM_PROFILES: dict[str, dict[str, str]] = {
    # 대조군. 같은 주소를 한 번 더 부른다 — 아래 "왜 대조군이 필요한가" 참고.
    "control": {},
    "google_click": {"gclid": _PROBE_TOKEN},
    "tiktok_click": {"ttclid": _PROBE_TOKEN},
    "utm_paid": {"utm_source": "google", "utm_medium": "cpc"},
}

PARAM_LABELS = {
    "control": "파라미터 없음(대조군)",
    "google_click": "gclid",
    "tiktok_click": "ttclid",
    "utm_paid": "utm_source=google&utm_medium=cpc",
}

# 왜 대조군이 필요한가.
#
# 파라미터를 붙인 페이지와 안 붙인 페이지가 다르다는 것만으로는 아무것도
# 증명하지 못한다. 배너가 돌아가거나 추천 상품이 섞이는 페이지는 **같은 주소를
# 두 번 불러도** 본문이 달라지기 때문이다. 그 차이를 gclid 탓으로 돌리면
# 멀쩡한 쇼핑몰이 계정 정지 위험으로 뜬다.
#
# 그래서 먼저 "아무것도 안 바꾸고 한 번 더" 불러 잡음의 크기를 잰다.
# 파라미터를 붙였을 때의 차이가 그 잡음보다 뚜렷하게 클 때만 지적한다.
# 이 두 값은 파라미터 축과 프로필 축이 함께 쓴다. 판단의 기준이 축마다
# 다르면 "왜 저쪽은 넘어갔는데 이쪽은 걸리나"를 설명할 수 없다.
NOISE_MARGIN = 0.05
# 대조군끼리도 이만큼 안 닮았으면 페이지가 스스로 계속 변하는 것이다.
# 이때는 무엇 때문에 달라졌는지 가려낼 수 없으므로 **판정하지 않는다.**
NOISE_FLOOR = 0.85


def build_param_url(url: str, params: dict[str, str]) -> str:
    """기존 광고 파라미터를 떼어내고 주어진 것만 붙인 URL."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in AD_PARAM_KEYS]
    kept += list(params.items())
    return urlunsplit(parts._replace(query=urlencode(kept)))


async def probe_params(url: str) -> dict[str, PageSnapshot]:
    """광고 파라미터 조합별로 같은 페이지를 가져온다.

    데스크톱 UA로 고정한다 — 여기서 보려는 축은 파라미터 하나다.
    프로필까지 같이 바꾸면 무엇 때문에 달라졌는지 말할 수 없게 된다.
    """
    ua = CLIENT_PROFILES["desktop"]
    names = list(PARAM_PROFILES)
    results = await asyncio.gather(
        *(_fetch_as(build_param_url(url, PARAM_PROFILES[n]), ua) for n in names)
    )
    return {n: snap for n, (snap, _html) in zip(names, results, strict=True)}


def param_divergence(
    baseline: PageSnapshot | None, probes: dict[str, PageSnapshot]
) -> tuple[str, str, str, str]:
    """파라미터 때문에 페이지가 갈라지는가.

    Returns: (severity, evidence, note, 문제가 된 변형 이름)
      severity가 비어 있으면 지적할 것이 없다는 뜻이고, 그 이유는 note에 담긴다.
      판정을 못 한 것과 문제가 없는 것은 다르므로 구분해서 돌려준다.
    """
    if baseline is None or baseline.fetch_error:
        return "", "", "", ""

    control = probes.get("control")
    if control is None or control.fetch_error:
        return "", "", "대조군을 가져오지 못해 파라미터 분기는 판정하지 않았습니다.", ""

    base_text = baseline.text
    if len(base_text) < MIN_TEXT_FOR_COMPARISON:
        return "", "", "본문이 짧아 파라미터 분기는 판정하지 않았습니다.", ""

    noise = similarity(base_text, control.text)
    if noise < NOISE_FLOOR:
        return "", "", (
            f"같은 주소를 두 번 불러도 본문이 달라져(유사도 {noise:.2f}) "
            "파라미터의 영향을 가려낼 수 없었습니다."
        ), ""

    base_host = urlparse(baseline.final_url).hostname or ""
    base_domain = _registrable(base_host)

    notes: list[str] = []
    worst_sev, worst_evidence, worst_name, worst_sim = "", "", "", 1.0
    for name, snap in probes.items():
        if name == "control" or snap.fetch_error:
            continue
        label = PARAM_LABELS.get(name, name)

        # 도착 도메인이 바뀌면 본문 비교를 할 것도 없다.
        hop = _registrable(urlparse(snap.final_url).hostname or "")
        if base_domain and hop and hop != base_domain:
            return ("block",
                    f"{label}를 붙이면 {base_domain} → {hop} 로 이동합니다", "", name)

        # **응답을 제대로 못 받은 것과 다른 내용이 온 것은 다르다.**
        # 국내 호스팅은 요청이 몰리면 "잠시 후 다시 시도" 안내를 200으로 준다.
        # 그걸 본문 비교에 넣으면 유사도 0.02가 나오고, 분기가 전혀 없는
        # 페이지가 계정 정지급으로 보고된다. 실제로 그렇게 나왔다.
        if len(snap.text) < MIN_TEXT_FOR_COMPARISON:
            notes.append(
                f"{label}를 붙였을 때 본문이 {len(snap.text)}자밖에 오지 않아 "
                "판정하지 않았습니다 — 차단·과부하 안내 페이지일 수 있습니다."
            )
            continue

        sim = similarity(base_text, snap.text)
        if sim >= noise - NOISE_MARGIN:
            continue  # 잡음 범위 안이다. 파라미터 탓으로 돌릴 수 없다.
        if sim < worst_sim:
            worst_sim, worst_name = sim, name
            worst_sev = "block" if sim < SIMILARITY_BLOCK else "warn"
            worst_evidence = (
                f"{label}를 붙였을 때 본문 유사도 {sim:.2f} "
                f"(대조군끼리는 {noise:.2f})"
            )

    return worst_sev, worst_evidence, " ".join(notes), worst_name


def analyze_param_divergence(
    baseline: PageSnapshot | None, probes: dict[str, PageSnapshot]
) -> tuple[str, str, str]:
    """param_divergence에서 변형 이름만 뺀 것."""
    severity, evidence, note, _name = param_divergence(baseline, probes)
    return severity, evidence, note


# 다시 확인할 때 두는 간격. 과부하·속도 제한이 원인이면 이 사이에 풀린다.
RECONFIRM_DELAY = 1.5


async def reconfirm_param_divergence(url: str, variant: str) -> tuple[bool, str]:
    """같은 차이가 다시 나오는지 **순서대로** 한 번 더 확인한다.

    계정 정지급 판정을 한 번의 관찰로 확정하면 안 된다. 앞선 점검은 프로필
    3개 + 파라미터 4개를 몰아서 보내므로, 속도 제한이 걸리는 서버에서는
    그중 하나만 안내 페이지를 받는 일이 실제로 일어난다.

    이번에는 몰아 보내지 않고 대조군과 변형을 사이를 두고 하나씩 부른다.
    두 응답을 **서로** 비교한다 — 같은 시점, 같은 조건이라 가장 공정하다.
    """
    ua = CLIENT_PROFILES["desktop"]
    control, _ = await _fetch_as(build_param_url(url, PARAM_PROFILES["control"]), ua)
    await asyncio.sleep(RECONFIRM_DELAY)
    again, _ = await _fetch_as(build_param_url(url, PARAM_PROFILES[variant]), ua)

    label = PARAM_LABELS.get(variant, variant)
    if control.fetch_error or again.fetch_error:
        return False, f"다시 확인하려 했으나 응답을 받지 못해 {label} 판정을 보류했습니다."
    if (len(control.text) < MIN_TEXT_FOR_COMPARISON
            or len(again.text) < MIN_TEXT_FOR_COMPARISON):
        return False, (
            f"다시 부르자 본문이 짧게 와서 {label} 판정을 보류했습니다 — "
            "서버가 요청을 제한하고 있을 수 있습니다."
        )

    sim = similarity(control.text, again.text)
    if sim >= SIMILARITY_WARN:
        return False, (
            f"{label} 차이가 다시 확인되지 않아 지적하지 않았습니다 "
            f"(다시 부르니 유사도 {sim:.2f}). 일시적인 응답 차이로 보입니다."
        )
    return True, f"다시 불러도 같았습니다 (유사도 {sim:.2f})"


async def check_robots(url: str) -> tuple[bool, str]:
    """robots.txt가 심사 크롤러를 막고 있는가.

    AdsBot-Google은 전역 `User-agent: *` 규칙을 따르지 않는다는 점이 중요하다.
    따라서 AdsBot을 **명시적으로** Disallow한 경우만 차단으로 판정한다.

    Returns: (차단 여부, 근거)
    """
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")

    try:
        # robots.txt도 같은 가드를 거쳐야 한다. 여기만 열어두면 리디렉션으로
        # 내부망을 읽는 통로가 그대로 남는다.
        async with safe_client(headers={"User-Agent": USER_AGENT}) as client:
            resp, content, _ = await safe_get(client, robots_url, max_bytes=100_000)
            if resp.status_code != 200:
                return False, ""
            body = content.decode("utf-8", errors="replace")
    except (UnsafeURLError, httpx.HTTPError):
        return False, ""

    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    return _robots_blocks(body, path)


def _robots_blocks(body: str, path: str) -> tuple[bool, str]:
    """robots.txt 본문이 이 경로에 대해 심사 크롤러를 막는가.

    두 가지를 제대로 처리한다.

    1. **그룹형 레코드** — `User-agent:`가 여러 줄 연속으로 오면 그 뒤의
       규칙은 그 전부에 적용된다. 마지막 한 줄만 기억하면 앞의 UA에 걸린
       규칙을 통째로 놓친다.
    2. **경로 단위 차단** — `Disallow: /landing`이 랜딩 URL을 막고 있는데
       `/`만 차단으로 치면 정작 잡아야 할 경우를 전부 놓친다.

    Allow가 더 길게 일치하면 Allow가 이긴다(표준 규칙).
    """
    agents: list[str] = []          # 지금 규칙이 적용되는 UA들
    rules: list[tuple[str, str]] = []   # (allow|disallow, 경로)
    expecting_agent = True

    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()

        if key == "user-agent":
            if not expecting_agent:      # 새 그룹이 시작됐다
                agents, expecting_agent = [], True
            agents.append(value.lower())
        elif key in ("disallow", "allow"):
            expecting_agent = False
            if any(a in AD_CRAWLERS for a in agents):
                rules.append((key, value))

    # 가장 길게 일치하는 규칙이 이긴다. 같은 길이면 Allow 우선.
    best: tuple[int, str, str] | None = None
    for kind, rule_path in rules:
        if not rule_path:                # `Disallow:` (빈 값)은 '전부 허용'
            continue
        if not path.startswith(rule_path.rstrip("*")):
            continue
        length = len(rule_path)
        if best is None or length > best[0] or (length == best[0] and kind == "allow"):
            best = (length, kind, rule_path)

    if best and best[1] == "disallow":
        return True, f"robots.txt — Disallow: {best[2]} (AdsBot 대상, 경로 {path})"
    return False, ""


# 타임아웃은 '거부'가 아니라 '모름'이다. 순간 네트워크 장애 한 번으로
# 계정 정지급 판정을 확정하면 안 된다.
_UNCERTAIN_ERRORS = ("시간 초과", "요청 실패")


def analyze_divergence(snaps: dict[str, PageSnapshot],
                       noise: float = 1.0) -> tuple[str, float, str]:
    """프로필 간 콘텐츠 차이를 분석한다.

    noise: 같은 프로필로 두 번 불렀을 때의 자기 유사도. 배너가 돌아가는
      페이지는 클로킹이 없어도 프로필 간 유사도가 낮게 나오므로, 그 잡음보다
      뚜렷하게 낮을 때만 판정한다. 1.0이면 기존과 같게 동작한다.

    Returns: (심각도 'block'|'warn'|'', 최저 유사도, 근거 문자열)
    """
    usable = {
        name: s for name, s in snaps.items()
        if not s.fetch_error and len(s.text) >= MIN_TEXT_FOR_COMPARISON
    }

    # 봇에게만 실패가 나는 것 자체가 강한 신호다. 다만 왜 실패했는지는 구분한다 —
    # 4xx는 사이트가 명시적으로 거부한 것이고, 타임아웃은 그냥 못 받은 것이다.
    bot = snaps.get("bot")
    desktop = snaps.get("desktop")
    if bot and desktop and bot.fetch_error and not desktop.fetch_error:
        uncertain = any(k in bot.fetch_error for k in _UNCERTAIN_ERRORS)
        return ("warn" if uncertain else "block"), 0.0, (
            f"브라우저에는 정상 응답하지만 봇에는 실패합니다 ({bot.fetch_error})"
            + ("  ※ 일시적 장애일 수 있어 경고로 낮췄습니다" if uncertain else "")
        )

    # 200을 주면서 **내용만 비워** 보내는 경우. 이게 이 모듈이 잡겠다고 한
    # 대표 시나리오(JS 전용 렌더링, 대기 페이지)인데, 짧다는 이유로 usable에서
    # 빠지면 desktop·mobile만 남아 '차이 없음'으로 끝나 버린다.
    if bot is not None and not bot.fetch_error:
        others = [
            s for name, s in snaps.items()
            if name != "bot" and not s.fetch_error
            and len(s.text) >= MIN_TEXT_FOR_COMPARISON
        ]
        if others and len(bot.text) < MIN_TEXT_FOR_COMPARISON:
            shortest = min(len(s.text) for s in others)
            return "block", 0.0, (
                f"브라우저에는 본문 {shortest}자가 나오는데 "
                f"봇에는 {len(bot.text)}자만 나옵니다 (HTTP {bot.status_code})"
            )

    if len(usable) < 2:
        return "", 1.0, ""

    worst = 1.0
    worst_pair = ("", "")
    names = list(usable)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            ratio = similarity(usable[a].text, usable[b].text)
            if ratio < worst:
                worst, worst_pair = ratio, (a, b)

    # 페이지가 스스로 변하는 만큼은 빼고 본다. 같은 프로필로 두 번 불러도
    # 0.7밖에 안 닮는 페이지라면, 프로필 간 0.7은 아무것도 말해주지 않는다.
    where = f"{worst_pair[0]}와 {worst_pair[1]} 응답의 본문 유사도 {worst:.0%}"
    if noise < 1.0:
        # 페이지가 스스로 이만큼도 유지하지 못하면 프로필 차이를 읽어낼 수 없다.
        if noise < NOISE_FLOOR:
            return "", worst, ""
        where += f" (같은 프로필끼리는 {noise:.0%})"
        if worst >= noise - NOISE_MARGIN:
            return "", worst, ""

    if worst < SIMILARITY_BLOCK:
        return "block", worst, where
    if worst < SIMILARITY_WARN:
        return "warn", worst, where
    return "", worst, ""
