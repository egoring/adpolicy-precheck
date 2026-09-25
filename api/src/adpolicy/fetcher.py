"""랜딩 페이지를 가져와 정규화된 스냅샷으로 만든다.

방어적으로 동작한다 — 실패를 예외가 아니라 상태(`fetch_error`)로 다루고,
호출자는 항상 PageSnapshot을 받는다. 페이지가 안 열리는 것 자체가
중요한 판정 결과(DEST-NOT-WORKING)이기 때문이다.

SSRF 방어: 사설 IP 대역과 비표준 스킴을 거부한다. 사용자가 임의 URL을
넣는 서비스이므로 내부망 스캔에 악용될 여지를 막아야 한다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
from selectolax.parser import HTMLParser

from .models import PageSnapshot

USER_AGENT = "adpolicy-precheck/0.1 (+https://github.com/egoring/adpolicy-precheck)"
MAX_BYTES = 3_000_000
TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

DROP_TAGS = ("script", "style", "noscript", "template", "svg")


class UnsafeURLError(ValueError):
    """내부망·비표준 스킴 등 가져오면 안 되는 URL."""


# 공개 접미사 목록 전체를 들고 오지는 않는다(의존성이 커진다).
# 국내 광고 페이지에서 실제로 쓰이는 접미사만 알면 충분하다.
_MULTI_LABEL_SUFFIXES = frozenset({
    "co.kr", "or.kr", "ne.kr", "re.kr", "pe.kr", "go.kr", "ac.kr", "hs.kr",
    "ms.kr", "es.kr", "sc.kr", "kg.kr", "seoul.kr", "busan.kr",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
    "com.au", "net.au", "org.au", "com.cn", "net.cn", "org.cn",
    "com.br", "com.tw", "com.hk", "com.sg", "com.mx", "co.in", "co.nz", "co.za",
})


def registrable_domain(host: str) -> str:
    """등록 가능한 도메인. '같은 사이트'의 범위를 정하는 한 가지 기준이다.

    여기 두는 이유는 rules와 cloaking이 **같은 기준**을 써야 하기 때문이다.
    각자 따로 판단하면 한쪽은 www 이동을 지적하고 다른 쪽은 안 하는,
    설명할 수 없는 결과가 나온다.
    """
    host = (host or "").lower().rstrip(".")
    parts = host.split(".")
    if len(parts) < 2:
        return host
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_LABEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# 100.64.0.0/10 (CGNAT)는 ipaddress의 is_private가 잡지 않는다.
_EXTRA_BLOCKED = (ipaddress.ip_network("100.64.0.0/10"),)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    return any(ip in net for net in _EXTRA_BLOCKED if ip.version == net.version)


def _resolve(host: str):
    """이름 풀이. 테스트에서 이 한 곳만 갈아끼우면 된다."""
    return socket.getaddrinfo(host, None)


async def assert_safe_url_async(url: str) -> None:
    """이름 풀이를 스레드로 넘긴 버전.

    `socket.getaddrinfo`는 블로킹이다. 이벤트 루프에서 그대로 부르면 응답이
    느린 DNS 하나가 서버 전체를 세운다. 동시에 여러 페이지를 가져오는
    구조라 이 차이가 그대로 드러난다.
    """
    await asyncio.to_thread(assert_safe_url, url)


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"지원하지 않는 스킴입니다: {parsed.scheme or '(없음)'}")
    if not parsed.hostname:
        raise UnsafeURLError("호스트가 없습니다.")

    try:
        infos = _resolve(parsed.hostname)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"도메인을 찾을 수 없습니다: {parsed.hostname}") from exc
    except (UnicodeError, ValueError) as exc:
        # 라벨이 63자를 넘는 등 형식이 깨진 호스트명은 gaierror가 아니라
        # UnicodeError로 온다. 놓치면 그대로 500이 된다.
        raise UnsafeURLError(f"호스트명 형식이 올바르지 않습니다: {parsed.hostname}") from exc

    for info in infos:
        if _is_blocked_ip(ipaddress.ip_address(info[4][0])):
            raise UnsafeURLError("내부망 주소는 검사할 수 없습니다.")


class TooLargeError(ValueError):
    """상한을 넘는 응답."""


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int = MAX_BYTES,
    max_redirects: int = 5,
) -> tuple[httpx.Response, bytes, str]:
    """SSRF 가드를 **모든 홉에** 적용하며 가져오고, 본문을 상한에서 끊는다.

    두 가지를 동시에 막는다.

    1. 리디렉션 우회 — `follow_redirects=True`로 맡기면 가드는 최초 URL에만
       걸리고, 302 한 번으로 127.0.0.1이든 169.254.169.254든 그대로 읽힌다.
       그래서 직접 홉을 돌며 매번 검사한다.
    2. 압축 폭탄 — `resp.content`는 이미 전부 풀린 뒤라 뒤에서 자르는 건
       의미가 없다. 스트리밍으로 받으며 세다가 상한에서 끊는다.

    Returns: (마지막 응답, 본문 바이트, 최종 URL)
    """
    current = url
    for _ in range(max_redirects + 1):
        await assert_safe_url_async(current)
        req = client.build_request("GET", current)
        resp = await client.send(req, stream=True, follow_redirects=False)
        try:
            if resp.is_redirect and (location := resp.headers.get("location")):
                current = str(resp.url.join(location))
                continue
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= max_bytes:
                    break          # 상한까지만 읽고 연결을 닫는다
            return resp, b"".join(chunks)[:max_bytes], str(resp.url)
        finally:
            await resp.aclose()

    raise UnsafeURLError("리디렉션이 너무 많습니다.")


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """연결 직전에 이름을 풀고, **검사한 그 IP로** 접속한다.

    assert_safe_url만으로는 DNS 재바인딩을 못 막는다. 검사할 때 한 번,
    httpx가 연결할 때 또 한 번 이름을 물으므로 TTL 0 레코드가 첫 번째엔
    공인 IP, 두 번째엔 127.0.0.1을 주면 검사는 통과하고 연결은 내부로 간다.
    여기서 한 번만 풀어 검사와 연결에 같은 IP를 쓴다. TLS의 SNI·인증서
    검증은 httpcore가 URL의 호스트명으로 따로 하므로 IP로 붙어도 그대로다.
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        try:
            infos = await asyncio.to_thread(_resolve, host)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        except (UnicodeError, ValueError) as exc:
            raise UnsafeURLError(f"호스트명 형식이 올바르지 않습니다: {host}") from exc
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
        # 하나라도 내부면 거부한다 — assert_safe_url과 같은 기준.
        if not ips or any(_is_blocked_ip(ip) for ip in ips):
            raise UnsafeURLError("내부망 주소는 검사할 수 없습니다.")
        return await self._inner.connect_tcp(
            str(ips[0]), port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise UnsafeURLError("유닉스 소켓 연결은 허용하지 않습니다.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _GuardedTransport(httpx.AsyncHTTPTransport):
    """연결 계층에 _GuardedBackend를 끼운 기본 전송."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # httpx는 백엔드를 바꾸는 공개 인자가 없다. 이 속성 이름이 바뀌면
        # test_guarded_connect_blocks_internal_even_without_precheck가 깨진다.
        self._pool._network_backend = _GuardedBackend(self._pool._network_backend)


def safe_client(**kwargs) -> httpx.AsyncClient:
    """리디렉션을 절대 자동으로 따라가지 않는 클라이언트. safe_get과 함께 쓴다.

    연결도 _GuardedTransport를 거쳐, 검사한 IP로만 붙는다(DNS 재바인딩 방어).
    """
    kwargs.setdefault("transport", _GuardedTransport())
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("headers", {"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"})
    kwargs["follow_redirects"] = False
    return httpx.AsyncClient(**kwargs)


def _image_urls(tree: HTMLParser, imgs: list, base: str) -> list[str]:
    """페이지에 실린 이미지 주소를 절대 URL로 모은다.

    lazy-load가 흔해서 src만 보면 플레이스홀더만 잡힌다. data-src 계열도 본다.
    srcset은 가장 앞 후보 하나만 — 같은 그림의 해상도 변형이라 전부 받을 이유가 없다.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        raw = (raw or "").strip()
        # data:·blob:은 네트워크로 받을 대상이 아니고, 추적 픽셀은 볼 것이 없다.
        if not raw or raw.startswith(("data:", "blob:", "javascript:")):
            return
        try:
            absolute = urljoin(base, raw)
        except ValueError:
            return
        if urlparse(absolute).scheme not in ("http", "https"):
            return
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)

    # og:image — 대개 대표 배너라 우선순위가 높다.
    for sel in ('meta[property="og:image"]', 'meta[name="twitter:image"]'):
        if (node := tree.css_first(sel)) is not None:
            add(node.attributes.get("content", "") or "")

    for i in imgs:
        attrs = i.attributes
        add(attrs.get("src", "") or "")
        for lazy in ("data-src", "data-original", "data-lazy-src"):
            add(attrs.get(lazy, "") or "")
        if srcset := (attrs.get("srcset") or attrs.get("data-srcset") or ""):
            first = srcset.split(",")[0].strip().split(" ")[0]
            add(first)

    return out


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
    image_urls = _image_urls(tree, imgs, final_url)

    inputs = tree.css("input, select, textarea")
    input_types = [(i.attributes.get("type") or "text").lower() for i in inputs]

    # 폼 **안쪽** 텍스트를 따로 모은다. 개인정보 수집 여부를 페이지 전체
    # 텍스트로 판단하면, 푸터의 '주소: 서울시…' 한 줄 때문에 검색창만 있는
    # 페이지가 개인정보 수집 페이지로 잡힌다.
    form_parts: list[str] = []
    for form in tree.css("form"):
        t = form.text(separator=" ", strip=True)
        if t:
            form_parts.append(t)
    for field in inputs:
        for attr in ("placeholder", "name", "aria-label"):
            if v := (field.attributes.get(attr) or "").strip():
                form_parts.append(v)
    for lab in tree.css("label"):
        if t := lab.text(strip=True):
            form_parts.append(t)

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
        image_urls=image_urls[:60],
        image_count=len(imgs),
        has_form=bool(tree.css("form")) or bool(inputs),
        form_input_types=input_types[:50],
        form_text=" ".join(form_parts)[:4000],
    )


async def fetch(url: str) -> PageSnapshot:
    """URL을 가져온다. 실패해도 예외를 던지지 않고 fetch_error를 채운다."""
    try:
        async with safe_client() as client:
            resp, content, final_url = await safe_get(client, url)
            html = content.decode(resp.encoding or "utf-8", errors="replace")
            snap = _extract(html, url, final_url, resp.status_code)
            if resp.status_code >= 400:
                snap.fetch_error = f"HTTP {resp.status_code}"
            return snap
    except UnsafeURLError as exc:
        return PageSnapshot(url=url, final_url=url, status_code=0, fetch_error=str(exc))
    except httpx.TimeoutException:
        return PageSnapshot(url=url, final_url=url, status_code=0,
                            fetch_error="응답 시간 초과")
    except httpx.HTTPError as exc:
        return PageSnapshot(url=url, final_url=url, status_code=0,
                            fetch_error=f"요청 실패: {type(exc).__name__}")
