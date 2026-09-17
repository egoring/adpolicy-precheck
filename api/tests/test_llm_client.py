"""LLMClient의 실패 경로 — 어떤 실패든 예외가 아니라 (텍스트, 오류)로 나와야 한다.

여기서 예외가 새어 나가면 API가 500을 뱉고, 결정적 룰셋 결과까지 같이 죽는다.
LLM은 보조 수단이므로 LLM의 실패가 전체 점검을 못 죽이게 하는 것이 요점이다.
"""

from __future__ import annotations

import httpx
import pytest

from adpolicy.llm import LLMClient


async def _run(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    client = LLMClient(base_url="http://llm:8000/v1", model="test-model")
    return await client.complete("sys", "user")


async def test_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "정상 응답"}}]}
        )

    text, err = await _run(monkeypatch, handler)
    assert text == "정상 응답"
    assert err == ""


async def test_non_200_reports_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "404" in err
    assert "test-model" in err


async def test_connection_refused_points_at_a_starting_container(monkeypatch):
    """포트가 닫힌 것 — 컨테이너는 있는데 아직 로딩 중이거나 죽었다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 111] Connection refused", request=request)

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "거부" in err
    assert "로딩" in err          # 첫 기동이 느린 경우를 먼저 짚어준다
    assert "logs llm" in err


async def test_dns_failure_points_at_a_missing_container(monkeypatch):
    """이름 해석 실패 — --profile llm을 안 붙여 컨테이너가 아예 없다.

    둘 다 httpx.ConnectError로 오지만 조치가 완전히 다르다.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "컨테이너가 없습니다" in err
    assert "COMPOSE_PROFILES" in err
    assert "llm" in err          # 어느 서비스가 빠졌는지 이름으로 말해준다
    assert "거부" not in err


async def test_timeout_names_the_limit(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "시간 초과" in err
    assert "LLM_TIMEOUT" in err


async def test_protocol_error_does_not_escape(monkeypatch):
    """ReadError·RemoteProtocolError는 예전에 잡히지 않아 500으로 새어 나갔다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("half-closed", request=request)

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "통신 오류" in err
    assert "RemoteProtocolError" in err


async def test_empty_content_is_an_error_not_silence(monkeypatch):
    """content가 비면 findings가 통째로 사라져 '위반 없음'처럼 보인다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": None}}]}
        )

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "빈 응답" in err


async def test_malformed_shape_is_reported(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert "형식" in err


async def test_api_key_header_only_when_real(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    await LLMClient(model="m", api_key="not-needed").complete("s", "u")
    assert "authorization" not in seen

    seen.clear()
    await LLMClient(model="m", api_key="sk-real").complete("s", "u")
    assert seen.get("authorization") == "Bearer sk-real"


@pytest.mark.parametrize("code", [400, 401, 422, 500, 503])
async def test_every_error_status_returns_tuple(monkeypatch, code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"error": "x"})

    text, err = await _run(monkeypatch, handler)
    assert text == ""
    assert str(code) in err


async def test_missing_vlm_names_vlm_not_llm(monkeypatch):
    """호스트가 vlm인데 'llm을 띄우세요'라고 하면 엉뚱한 곳을 고치게 된다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    _, err = await LLMClient(base_url="http://vlm:8000/v1", model="m").complete("s", "u")
    assert "'vlm' 컨테이너가 없습니다" in err
    assert "COMPOSE_PROFILES" in err
