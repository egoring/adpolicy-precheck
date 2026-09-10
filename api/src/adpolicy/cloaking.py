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

import difflib
import re
from urllib.parse import urljoin, urlparse

import httpx

from .fetcher import TIMEOUT, USER_AGENT, UnsafeURLError, _extract, assert_safe_url
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

# UA를 검사해 분기하는 스크립트 패턴
UA_SNIFF_PATTERNS = [
    re.compile(r"navigator\.userAgent", re.IGNORECASE),
    re.compile(r"navigator\.webdriver", re.IGNORECASE),
    re.compile(r"HTTP_USER_AGENT", re.IGNORECASE),
]

# robots.txt에서 확인할 심사 크롤러
AD_CRAWLERS = ["adsbot-google", "adsbot-google-mobile", "googlebot"]

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
    return difflib.SequenceMatcher(None, na[:8000], nb[:8000]).ratio()


def detect_ua_sniffing(raw_html: str) -> str:
    """UA 분기 스크립트가 있으면 그 근거 문자열을 돌려준다."""
    for pat in UA_SNIFF_PATTERNS:
        m = pat.search(raw_html)
        if m:
            return m.group(0)
    return ""


def detect_auto_download(raw_html: str) -> str:
    for pat in AUTO_DOWNLOAD_PATTERNS:
        m = pat.search(raw_html)
        if m:
            return m.group(0)[:120]
    return ""


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

    for name, ua in CLIENT_PROFILES.items():
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=TIMEOUT,
                headers={"User-Agent": ua, "Accept-Language": "ko,en;q=0.8"},
                max_redirects=5,
            ) as client:
                resp = await client.get(url)
                html = resp.content[:3_000_000].decode(
                    resp.encoding or "utf-8", errors="replace"
                )
                snap = _extract(html, url, str(resp.url), resp.status_code)
                if resp.status_code >= 400:
                    snap.fetch_error = f"HTTP {resp.status_code}"
                snaps[name] = snap
                raws[name] = html
        except httpx.HTTPError as exc:
            snaps[name] = PageSnapshot(
                url=url, final_url=url, status_code=0,
                fetch_error=f"요청 실패: {type(exc).__name__}",
            )

    return snaps, raws


async def check_robots(url: str) -> tuple[bool, str]:
    """robots.txt가 심사 크롤러를 막고 있는가.

    AdsBot-Google은 전역 `User-agent: *` 규칙을 따르지 않는다는 점이 중요하다.
    따라서 AdsBot을 **명시적으로** Disallow한 경우만 차단으로 판정한다.

    Returns: (차단 여부, 근거)
    """
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return False, ""
            body = resp.text[:100_000]
    except httpx.HTTPError:
        return False, ""

    current_agent = ""
    for line in body.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()

        if key == "user-agent":
            current_agent = value.lower()
        elif key == "disallow" and current_agent in AD_CRAWLERS:
            if value == "/":
                return True, f"User-agent: {current_agent} / Disallow: /"
    return False, ""


def analyze_divergence(snaps: dict[str, PageSnapshot]) -> tuple[str, float, str]:
    """프로필 간 콘텐츠 차이를 분석한다.

    Returns: (심각도 'block'|'warn'|'', 최저 유사도, 근거 문자열)
    """
    usable = {
        name: s for name, s in snaps.items()
        if not s.fetch_error and len(s.text) >= MIN_TEXT_FOR_COMPARISON
    }

    # 봇에게만 실패가 나는 것 자체가 강한 신호다.
    bot = snaps.get("bot")
    desktop = snaps.get("desktop")
    if bot and desktop and bot.fetch_error and not desktop.fetch_error:
        return "block", 0.0, (
            f"브라우저에는 정상 응답하지만 봇에는 실패합니다 ({bot.fetch_error})"
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

    if worst < SIMILARITY_BLOCK:
        return "block", worst, (
            f"{worst_pair[0]}와 {worst_pair[1]} 응답의 본문 유사도 {worst:.0%}"
        )
    if worst < SIMILARITY_WARN:
        return "warn", worst, (
            f"{worst_pair[0]}와 {worst_pair[1]} 응답의 본문 유사도 {worst:.0%}"
        )
    return "", worst, ""
