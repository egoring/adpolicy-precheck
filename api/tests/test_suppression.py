"""C-5 오탐 무시(ignore_codes).

근거 있는 "업계 1위" 광고주는 매번 MIS-SUPERLATIVE를 본다. 요청에서 그 코드를
무시하면 점수·판정에서 빠지되, **숨기지는 않는다** — suppressed로 따로 돌려준다.
계정 정지·경고 누적급은 무시할 수 없다. 그걸 가릴 수 있으면 이 도구가 존재할
이유가 사라진다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from adpolicy import cloaking, history, main
from adpolicy.models import CheckRequest, PageSnapshot

client = TestClient(main.app)

HTML = "<html><body>업계 1위 원두 브랜드</body></html>"

PAGE = PageSnapshot(
    url="https://example.com",
    final_url="https://example.com",
    status_code=200,
    title="원두",
    text=("업계 1위 원두 브랜드. 문의 010-0000-0000 사업자등록번호 123-45-67890 "
          + "로스팅 후 7일 이내 발송합니다. " * 30),
    fetch_error="",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path):
    async def fake_probe(url: str):
        return {"desktop": PAGE}, {"desktop": HTML}

    async def fake_robots(url: str):
        return False, ""

    async def fake_params(url: str):
        return dict.fromkeys(cloaking.PARAM_PROFILES, PAGE)

    monkeypatch.setattr(cloaking, "probe_profiles", fake_probe)
    monkeypatch.setattr(cloaking, "check_robots", fake_robots)
    monkeypatch.setattr(cloaking, "probe_params", fake_params)
    monkeypatch.setattr(history, "HISTORY_LOG", str(tmp_path / "history.jsonl"))


def _post(**extra):
    body = {"url": "https://example.com", "use_llm": False, "check_images": False}
    body.update(extra)
    return client.post("/v1/check", json=body)


def _codes(items):
    return [f["code"] for f in items]


def test_baseline_reports_superlative():
    """기준선 — 무시하지 않으면 최상급 표현이 지적된다."""
    body = _post().json()
    assert "MIS-SUPERLATIVE" in _codes(body["findings"])
    assert body["suppressed"] == []


def test_ignored_code_leaves_findings_but_is_reported_as_suppressed():
    base = _post().json()
    body = _post(ignore_codes=["MIS-SUPERLATIVE"]).json()

    assert "MIS-SUPERLATIVE" not in _codes(body["findings"])
    # 숨기지 않는다 — 무엇을 뺐는지 그대로 보여준다
    assert _codes(body["suppressed"]) == ["MIS-SUPERLATIVE"]
    assert body["stats"]["suppressed"] == 1
    # 점수에서 빠진다
    assert body["score"] > base["score"]


def test_ignore_codes_are_case_and_whitespace_insensitive():
    body = _post(ignore_codes=["  mis-superlative "]).json()
    assert _codes(body["suppressed"]) == ["MIS-SUPERLATIVE"]


def test_ignoring_a_code_that_did_not_fire_is_harmless():
    body = _post(ignore_codes=["MIS-DISHONEST-PRICING"]).json()
    assert body["suppressed"] == []


def test_unknown_code_is_rejected():
    """오타 난 무시 목록이 조용히 아무 효과 없이 남으면 안 된다."""
    r = _post(ignore_codes=["MIS-SUPERLATIV"])
    assert r.status_code == 422
    assert "MIS-SUPERLATIV" in r.text


@pytest.mark.parametrize("code", ["ABUSE-CLOAKING", "MIS-CLICKBAIT", "PROHIB-COUNTERFEIT"])
def test_account_level_codes_cannot_be_ignored(code):
    """계정 정지·경고 누적급은 가릴 수 없다."""
    r = _post(ignore_codes=[code])
    assert r.status_code == 422
    assert code in r.text


def test_validation_applies_outside_http_too():
    """MCP 서버는 CheckRequest를 직접 만든다. 같은 검증이 걸려야 한다."""
    with pytest.raises(ValidationError):
        CheckRequest(url="https://example.com", ignore_codes=["ABUSE-CLOAKING"])


def test_toggling_ignore_does_not_read_as_resolved():
    """무시 설정을 켰다고 '해결됨'으로 보이면 안 된다 — 페이지는 그대로다."""
    _post()
    body = _post(ignore_codes=["MIS-SUPERLATIVE"]).json()
    assert body["history"] is not None
    assert "MIS-SUPERLATIVE" not in body["history"]["resolved_codes"]
