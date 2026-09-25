"""API 접근 제어 — API 키와 점검 요청 속도 제한.

/v1/check 한 번이 외부 페이지 여러 개를 가져오고 LLM 토큰을 쓴다. 열어 둔
채로 네트워크에 노출되면 남의 서버가 대신 크롤러·LLM 프록시가 되고,
/v1/history는 누가 무엇을 점검했는지 그대로 보여준다.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from adpolicy import access, main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # 한도 초기화는 conftest가 한다
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MIN", raising=False)


# ---------------------------------------------------------------------------
# API 키
# ---------------------------------------------------------------------------


def test_without_api_key_configured_everything_is_open():
    """키를 안 걸면 지금처럼 동작한다 — 로컬 단독 사용이 기본이다."""
    assert client.get("/v1/policies").status_code == 200


def test_api_key_blocks_requests_without_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    for path in ("/v1/policies", "/v1/history", "/v1/usage"):
        resp = client.get(path)
        assert resp.status_code == 401, path
    assert client.post("/v1/check", json={"url": "https://example.com"}).status_code == 401


def test_api_key_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    assert client.get("/v1/policies", headers={"X-API-Key": "nope"}).status_code == 401


@pytest.mark.parametrize("headers", [
    {"X-API-Key": "s3cret"},
    {"Authorization": "Bearer s3cret"},
])
def test_api_key_accepts_header_or_bearer(monkeypatch, headers):
    monkeypatch.setenv("API_KEY", "s3cret")
    assert client.get("/v1/policies", headers=headers).status_code == 200


def test_healthz_stays_open_for_container_healthcheck(monkeypatch):
    """도커 healthcheck는 키 없이 부른다. 여기까지 잠그면 컨테이너가 안 뜬다."""
    monkeypatch.setenv("API_KEY", "s3cret")
    assert client.get("/healthz").status_code == 200


def test_cors_preflight_is_not_blocked_by_api_key(monkeypatch):
    """브라우저 preflight(OPTIONS)는 커스텀 헤더를 싣지 못한다."""
    monkeypatch.setenv("API_KEY", "s3cret")
    resp = client.options("/v1/check", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-api-key,content-type",
    })
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 속도 제한
# ---------------------------------------------------------------------------


def test_limiter_allows_up_to_limit_then_blocks():
    lim = access.RateLimiter()
    now = 1000.0
    assert all(lim.hit("1.2.3.4", limit=3, now=now + i) == 0 for i in range(3))
    wait = lim.hit("1.2.3.4", limit=3, now=now + 3)
    assert wait > 0


def test_limiter_is_per_client():
    lim = access.RateLimiter()
    for i in range(3):
        lim.hit("a", limit=3, now=100.0 + i)
    assert lim.hit("a", limit=3, now=103.0) > 0
    assert lim.hit("b", limit=3, now=103.0) == 0


def test_limiter_window_slides():
    lim = access.RateLimiter()
    for i in range(3):
        lim.hit("a", limit=3, now=100.0 + i)
    assert lim.hit("a", limit=3, now=103.0) > 0
    # 첫 요청이 60초 창을 벗어나면 다시 한 자리가 난다
    assert lim.hit("a", limit=3, now=160.5) == 0


def test_limiter_forgets_idle_clients():
    """오래 조용한 IP까지 계속 들고 있으면 메모리가 끝없이 는다."""
    lim = access.RateLimiter()
    for i in range(50):
        lim.hit(f"ip{i}", limit=5, now=100.0)
    lim.hit("late", limit=5, now=1000.0)
    assert set(lim._hits) == {"late"}


def test_check_endpoint_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")

    async def fake_run(req):
        # 418 = 제한을 통과해 본 점검까지 들어왔다는 표시
        raise HTTPException(status_code=418)

    monkeypatch.setattr(main, "_run_check", fake_run)
    body = {"url": "https://example.com"}
    assert client.post("/v1/check", json=body).status_code == 418
    assert client.post("/v1/check", json=body).status_code == 418
    resp = client.post("/v1/check", json=body)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1


def test_rate_limit_zero_disables(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")

    async def fake_run(req):
        # 418 = 제한을 통과해 본 점검까지 들어왔다는 표시
        raise HTTPException(status_code=418)

    monkeypatch.setattr(main, "_run_check", fake_run)
    for _ in range(30):
        assert client.post("/v1/check", json={"url": "https://example.com"}).status_code == 418
