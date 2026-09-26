"""보안·자원 상한 회귀 테스트.

사용자가 임의 URL을 넣으면 서버가 그 페이지와 **거기 실린 모든 이미지**를
가져온다. 즉 공격자가 응답을 완전히 통제한다. 여기 있는 것들은 전부
실제로 뚫렸던 경로이고, 다시 뚫리면 이 테스트가 먼저 깨져야 한다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from adpolicy import cloaking, vision
from adpolicy.fetcher import (
    UnsafeURLError,
    _is_blocked_ip,
    assert_safe_url,
    fetch,
    safe_client,
    safe_get,
)

# ---------------------------------------------------------------------------
# SSRF — 리디렉션 우회
# ---------------------------------------------------------------------------


class _Redirector(BaseHTTPRequestHandler):
    """/start 로 오면 내부 주소로 302. /internal 은 비밀을 뱉는다."""

    def do_GET(self):  # noqa: N802
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/internal")
            self.end_headers()
        else:
            body = b"<html><title>INTERNAL</title><body>secret-token</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *a):  # noqa: N802
        pass


@pytest.fixture
def redirector():
    srv = HTTPServer(("127.0.0.1", 0), _Redirector)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


@pytest.fixture
def public_looking(monkeypatch, redirector):
    """첫 홉만 공인 IP처럼 보이게 한다 — DNS는 속이되 연결은 로컬로."""
    real = socket.getaddrinfo

    def fake(host, *a, **k):
        if host == "public.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return redirector


async def test_redirect_to_loopback_is_blocked(redirector):
    """302 한 번으로 내부망을 읽던 경로. 홉마다 가드가 다시 걸려야 한다."""
    async with httpx.AsyncClient(follow_redirects=False) as client:
        with pytest.raises(UnsafeURLError):
            await safe_get(client, f"http://127.0.0.1:{redirector}/start")


async def test_guard_runs_on_every_hop_not_just_the_first(public_looking, monkeypatch):
    """첫 홉이 공인 IP여도, 리디렉션 대상이 내부면 거기서 막아야 한다."""
    real = socket.getaddrinfo
    seen: list[str] = []

    def spy(host, *a, **k):
        seen.append(host)
        return real(host, *a, **k) if host != "public.test" else [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", spy)
    async with httpx.AsyncClient(follow_redirects=False) as client:
        with pytest.raises(UnsafeURLError):
            await safe_get(client, f"http://127.0.0.1:{public_looking}/start")
    # 최초 URL이 이미 내부라 첫 검사에서 걸린다 — 그것도 정답이다
    assert seen


@pytest.fixture
def rebinding(monkeypatch, redirector):
    """DNS 재바인딩 — 처음 물으면 공인 IP, 그다음부터는 127.0.0.1.

    TTL 0짜리 레코드로 실제로 할 수 있는 공격이다. 검사 때 한 번,
    연결 때 한 번 따로 물으면 검사는 공인 IP를 보고 연결은 내부로 간다.
    """
    real = socket.getaddrinfo
    calls = {"n": 0}

    def fake(host, *a, **k):
        # anyio는 IDNA 인코딩한 bytes로 묻는다
        name = host.decode() if isinstance(host, bytes) else host
        if name != "rebind.test":
            return real(host, *a, **k)
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return redirector


async def test_dns_rebinding_cannot_reach_internal(rebinding):
    """검사한 IP와 연결하는 IP가 같아야 한다. 두 번 물으면 뚫린다."""
    async with safe_client() as client:
        with pytest.raises(UnsafeURLError):
            await safe_get(client, f"http://rebind.test:{rebinding}/internal")


async def test_guarded_connect_blocks_internal_even_without_precheck(redirector, monkeypatch):
    """사전 검사를 건너뛰어도 연결 단계에서 막힌다 — 가드가 한 겹이 아니다."""
    monkeypatch.setattr("adpolicy.fetcher.assert_safe_url", lambda url: None)
    async with safe_client() as client:
        with pytest.raises(UnsafeURLError):
            await safe_get(client, f"http://127.0.0.1:{redirector}/internal")


async def test_fetch_reports_rebinding_as_error_not_content(rebinding):
    """fetch는 예외 대신 fetch_error로 알린다. 내부 응답 본문이 새면 안 된다."""
    snap = await fetch(f"http://rebind.test:{rebinding}/internal")
    assert snap.fetch_error
    assert "secret-token" not in (snap.text or "")


async def test_redirect_loop_is_bounded(monkeypatch):
    """무한 리디렉션에 매달리지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://example.com/next"})

    monkeypatch.setattr("adpolicy.fetcher.assert_safe_url", lambda url: None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsafeURLError, match="리디렉션"):
            await safe_get(client, "https://example.com/start", max_redirects=3)


# ---------------------------------------------------------------------------
# SSRF — 주소 대역
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
     "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",
     "100.64.0.1", "224.0.0.1"],
)
def test_internal_ranges_are_blocked(ip):
    assert _is_blocked_ip(ipaddress.ip_address(ip)), ip


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert not _is_blocked_ip(ipaddress.ip_address(ip)), ip


def test_malformed_hostname_is_rejected_not_crashed():
    """63자를 넘는 라벨은 gaierror가 아니라 UnicodeError로 온다.

    놓치면 /v1/check가 그대로 500이 됐다.
    """
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://" + "a" * 70 + ".com/")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/", "ftp://x/"])
def test_non_http_schemes_rejected(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


# ---------------------------------------------------------------------------
# 자원 상한
# ---------------------------------------------------------------------------


async def test_body_is_cut_at_the_cap_while_streaming(monkeypatch):
    """압축 폭탄 대비. resp.content는 이미 다 풀린 뒤라 뒤에서 자르면 늦다."""
    huge = b"A" * 10_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=huge)

    monkeypatch.setattr("adpolicy.fetcher.assert_safe_url", lambda url: None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        _, content, _ = await safe_get(client, "https://example.com/", max_bytes=100_000)
    assert len(content) == 100_000


def test_pixel_bomb_is_rejected_before_resize():
    """작은 파일이 확대 뒤 기가픽셀이 되어 프로세스를 죽이던 경로."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (400, 20000), "white").save(buf, format="PNG")
    variants = list(vision._variants(buf.getvalue()))
    # 원본만 나오고, 확대본은 만들지 않아야 한다
    assert [name for name, _ in variants] == ["원본"]


def test_oversized_image_is_not_fetched_into_ocr():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (9000, 9000), "white").save(buf, format="PNG")
    w, h = vision._dimensions(buf.getvalue())
    assert w * h > vision.MAX_IMAGE_PIXELS or w == 0


async def test_total_image_bytes_are_capped(monkeypatch):
    """장당 상한만 두면 8장 × 5MB가 그대로 들어온다."""
    from adpolicy.models import ImageAsset, PageSnapshot

    big = 6_000_000

    async def fake_fetch_one(client, url):
        return ImageAsset(url=url, content_type="image/png", bytes_len=big,
                          width=800, height=600, data_b64="x")

    monkeypatch.setattr(vision, "_fetch_one", fake_fetch_one)
    monkeypatch.setattr(vision, "MAX_TOTAL_IMAGE_BYTES", 10_000_000)
    snap = PageSnapshot(url="u", final_url="u", status_code=200,
                        image_urls=[f"https://ex.com/{i}.png" for i in range(8)])
    assets = await vision.collect(snap, limit=8)
    usable = [a for a in assets if a.ok]
    assert sum(a.bytes_len for a in usable) <= 10_000_000
    assert any("총량" in a.fetch_error for a in assets if a.fetch_error)


async def test_image_count_never_exceeds_the_limit(monkeypatch):
    """배치 단위로만 검사해 상한을 넘겨 가져오던 문제."""
    from adpolicy.models import ImageAsset, PageSnapshot

    async def fake_fetch_one(client, url):
        return ImageAsset(url=url, content_type="image/png", bytes_len=5000,
                          width=800, height=600, data_b64="x")

    monkeypatch.setattr(vision, "_fetch_one", fake_fetch_one)
    snap = PageSnapshot(url="u", final_url="u", status_code=200,
                        image_urls=[f"https://ex.com/{i}.png" for i in range(30)])
    assets = await vision.collect(snap, limit=4)
    assert sum(1 for a in assets if a.ok) <= 4


def test_content_type_absent_does_not_bypass_type_check():
    """헤더가 없으면 두 검사를 모두 건너뛰어 임의 바이트가 통과했다."""
    assert vision._sniff_image_type(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert vision._sniff_image_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert vision._sniff_image_type(b"<html>not an image</html>") == ""


# ---------------------------------------------------------------------------
# 이벤트 루프
# ---------------------------------------------------------------------------


async def test_ocr_does_not_block_the_event_loop(monkeypatch):
    """OCR이 도는 동안 서버가 다른 요청을 못 받으면 안 된다."""
    import time

    from adpolicy import main
    from adpolicy.models import ImageAsset, PageSnapshot

    def slow_ocr(assets):
        time.sleep(0.4)
        for a in assets:
            a.ocr_text = "읽음"

    async def fake_collect(snap, limit=8):
        return [ImageAsset(url="https://ex.com/a.png", content_type="image/png",
                           bytes_len=9999, data_b64="x")]

    monkeypatch.setattr(vision, "collect", fake_collect)
    monkeypatch.setattr(vision, "run_ocr", slow_ocr)
    monkeypatch.setattr(vision, "ocr_available", lambda: True)

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    snap = PageSnapshot(url="u", final_url="u", status_code=200, image_urls=["a"])
    await main._prepare_images(snap)
    beat.cancel()
    # 루프가 멈췄다면 tick이 거의 0이다
    assert ticks >= 5, f"이벤트 루프가 막혔다 (tick={ticks})"


# ---------------------------------------------------------------------------
# robots.txt 도 같은 가드를 거치는가
# ---------------------------------------------------------------------------


async def test_robots_fetch_is_guarded():
    """예전엔 여기만 가드가 아예 없어 내부망 통로가 열려 있었다."""
    blocked, evidence = await cloaking.check_robots("http://127.0.0.1:1/x")
    assert blocked is False and evidence == ""
