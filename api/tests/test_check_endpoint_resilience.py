"""/v1/check는 LLM이 어떻게 망가지든 500을 내면 안 된다.

LLM은 보조 수단이고 결정적 룰셋이 본체다. LLM 쪽 예외가 올라가 전체 응답이
죽으면, 사용자는 멀쩡히 계산된 룰셋 결과까지 잃는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adpolicy import analyzer, cloaking, main
from adpolicy.models import PageSnapshot

client = TestClient(main.app)

HTML = "<html><body>지금 신청하면 효과 100% 보장!</body></html>"

PAGE = PageSnapshot(
    url="https://example.com",
    final_url="https://example.com",
    status_code=200,
    title="테스트 페이지",
    text="지금 신청하면 효과 100% 보장! 문의 010-0000-0000 " + "내용 " * 200,
    fetch_error="",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """페이지 수집과 robots 조회를 고정값으로 대체 — 네트워크를 타지 않는다."""

    async def fake_probe(url: str):
        return {"desktop": PAGE}, {"desktop": HTML}

    async def fake_robots(url: str):
        return False, ""

    async def fake_params(url: str):
        # 파라미터 조합도 실제 요청이다. 안 막으면 테스트가 밖으로 나간다.
        return dict.fromkeys(cloaking.PARAM_PROFILES, PAGE)

    monkeypatch.setattr(cloaking, "probe_profiles", fake_probe)
    monkeypatch.setattr(cloaking, "check_robots", fake_robots)
    monkeypatch.setattr(cloaking, "probe_params", fake_params)


def _post(use_llm: bool = True):
    return client.post(
        "/v1/check",
        json={
            "platform": "google_ads",
            "url": "https://example.com",
            "ad_copy": "지금 신청하면 효과 100% 보장!",
            "use_llm": use_llm,
        },
    )


def test_rules_only_baseline():
    """LLM을 끄면 룰셋 결과가 나온다 — 아래 테스트들의 기준선."""
    r = _post(use_llm=False)
    assert r.status_code == 200
    assert r.json()["stats"]["rule_findings"] > 0


@pytest.mark.parametrize(
    "boom",
    [
        RuntimeError("engine died"),
        ValueError("bad json"),
        TypeError("expected string or bytes-like object, got 'NoneType'"),
        KeyError("choices"),
    ],
    ids=["runtime", "value", "type-none", "key"],
)
def test_llm_exception_does_not_kill_the_check(monkeypatch, boom):
    async def exploding(*args, **kwargs):
        raise boom

    monkeypatch.setattr(analyzer, "analyze", exploding)

    r = _post()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_used"] is False
    assert type(boom).__name__ in body["llm_note"]
    # 핵심: 룰셋 결과는 그대로 살아 있어야 한다
    assert body["stats"]["rule_findings"] > 0
    assert body["findings"]


def test_llm_returning_none_content_is_survivable(monkeypatch):
    """예전에 500을 냈던 실제 경로 — content가 None인 응답."""

    async def none_complete(self, system, user, **kwargs):
        return None, ""

    monkeypatch.setattr("adpolicy.llm.LLMClient.complete", none_complete)

    r = _post()
    assert r.status_code == 200, r.text
    assert r.json()["stats"]["rule_findings"] > 0


def test_llm_returning_prose_is_reported_as_unparseable(monkeypatch):
    """JSON이 아닌 산문을 뱉으면 '위반 없음'과 구분되게 통계에 남는다."""

    async def prose(self, system, user, **kwargs):
        return "죄송합니다. 해당 요청은 도와드릴 수 없습니다.", ""

    monkeypatch.setattr("adpolicy.llm.LLMClient.complete", prose)

    r = _post()
    assert r.status_code == 200
    assert r.json()["stats"].get("llm_unparseable") == 1
