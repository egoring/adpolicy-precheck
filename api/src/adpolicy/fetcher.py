"""랜딩 페이지를 가져와 정규화된 스냅샷으로 만든다.

방어적으로 동작한다 — 실패를 예외가 아니라 상태(`fetch_error`)로 다루고,
호출자는 항상 PageSnapshot을 받는다. 페이지가 안 열리는 것 자체가
중요한 판정 결과(LP-UNREACHABLE)이기 때문이다.

SSRF 방어: 사설 IP 대역과 비표준 스킴을 거부한다. 사용자가 임의 URL을
넣는 서비스이므로 내부망 스캔에 악용될 여지를 막아야 한다.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from .models import PageSnapshot

USER_AGENT = "adpolicy-precheck/0.1 (+https://github.com/egoring/adpolicy-precheck)"
MAX_BYTES = 3_000_000
TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

DROP_TAGS = ("script", "style", "noscript", "template", "svg")


class UnsafeURLError(ValueError):
    """내부망·비표준 스킴 등 가져오면 안 되는 URL."""


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"지원하지 않는 스킴입니다: {parsed.scheme or '(없음)'}")
    if not parsed.hostname:
        raise UnsafeURLError("호스트가 없습니다.")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"도메인을 찾을 수 없습니다: {parsed.hostname}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise UnsafeURLError("내부망 주소는 검사할 수 없습니다.")


def _extract(html: str, url: str, final_url: str, status: int) -> PageSnapshot:
    tree = HTMLParser(html)
    for tag in DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()

    title = ""
    if (node := tree.css_first("title")) is not None:
        title = node.text(strip=True)

    meta_desc = ""
    if (node := tree.css_first('meta[name="description"]')) is not None:
        meta_desc = node.attributes.get("content", "") or ""

    body = tree.css_first("body")
    text = body.text(separator="\n", strip=True) if body else ""
    # 빈 줄 정리
    text = "\n".join(s for s in (ln.strip() for ln in text.split("\n")) if s)

    links, link_texts = [], []
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if href:
            links.append(href)
        t = a.text(strip=True)
        if t:
            link_texts.append(t)

    imgs = tree.css("img")
    image_alts = [(i.attributes.get("alt") or "") for i in imgs]

    inputs = tree.css("input, select, textarea")
    input_types = [(i.attributes.get("type") or "text").lower() for i in inputs]

    return PageSnapshot(
        url=url,
        final_url=final_url,
        status_code=status,
        title=title,
        meta_description=meta_desc,
        text=text,
        links=links[:300],
        link_texts=link_texts[:300],
        image_alts=image_alts[:200],
        image_count=len(imgs),
        has_form=bool(tree.css("form")) or bool(inputs),
        form_input_types=input_types[:50],
    )


async def fetch(url: str) -> PageSnapshot:
    """URL을 가져온다. 실패해도 예외를 던지지 않고 fetch_error를 채운다."""
    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        return PageSnapshot(url=url, final_url=url, status_code=0, fetch_error=str(exc))

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"},
            max_redirects=5,
        ) as client:
            resp = await client.get(url)
            content = resp.content[:MAX_BYTES]
            html = content.decode(resp.encoding or "utf-8", errors="replace")
            snap = _extract(html, url, str(resp.url), resp.status_code)
            if resp.status_code >= 400:
                snap.fetch_error = f"HTTP {resp.status_code}"
            return snap
    except httpx.TimeoutException:
        return PageSnapshot(url=url, final_url=url, status_code=0,
                            fetch_error="응답 시간 초과")
    except httpx.HTTPError as exc:
        return PageSnapshot(url=url, final_url=url, status_code=0,
                            fetch_error=f"요청 실패: {type(exc).__name__}")
