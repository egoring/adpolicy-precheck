"""C-4 배치 점검 — URL·문구 여러 건을 한 번에 넘기고 작업 번호로 결과를 받는다.

대행사는 캠페인 단위로 수십 건을 점검한다. 단건 동기 요청 하나가 LLM 포함
최대 수 분을 잡고 있으므로, 받자마자 작업 번호를 돌려주고 뒤에서 돌린다.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from adpolicy import batch, main
from adpolicy.models import CheckResponse


def _fake_response(req) -> CheckResponse:
    return CheckResponse(
        platform=req.platform, url=str(req.url), final_url=str(req.url),
        verdict="pass", score=100, summary="ok", findings=[],
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(batch, "store", batch.JobStore())
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")

    async def fake_run(req):
        if "boom" in str(req.url):
            raise RuntimeError("engine died")
        await asyncio.sleep(0)
        return _fake_response(req)

    monkeypatch.setattr(main, "_run_check", fake_run)
    with TestClient(main.app) as c:
        yield c


def _items(*urls):
    return {"items": [{"url": u, "use_llm": False} for u in urls]}


def _wait_done(client, job_id, tries=200):
    for _ in range(tries):
        body = client.get(f"/v1/batch/{job_id}").json()
        if body["status"] == "done":
            return body
    raise AssertionError(f"작업이 끝나지 않았습니다: {body}")


def test_submit_returns_job_immediately(client):
    r = client.post("/v1/batch", json=_items("https://a.example", "https://b.example"))
    assert r.status_code == 202
    body = r.json()
    assert body["total"] == 2
    assert len(body["job_id"]) >= 20  # 추측할 수 없어야 한다


def test_results_come_back_in_input_order(client):
    urls = [f"https://site{i}.example/" for i in range(5)]
    job = client.post("/v1/batch", json=_items(*urls)).json()["job_id"]
    body = _wait_done(client, job)
    assert body["done"] == 5
    assert [it["url"] for it in body["items"]] == urls
    assert all(it["status"] == "ok" and it["result"]["verdict"] == "pass"
               for it in body["items"])


def test_one_failure_does_not_sink_the_batch(client):
    job = client.post("/v1/batch", json=_items(
        "https://ok.example/", "https://boom.example/", "https://ok2.example/",
    )).json()["job_id"]
    body = _wait_done(client, job)
    statuses = [it["status"] for it in body["items"]]
    assert statuses == ["ok", "error", "ok"]
    assert "RuntimeError" in body["items"][1]["error"]
    assert body["failed"] == 1


def test_unknown_job_is_404(client):
    assert client.get("/v1/batch/does-not-exist").status_code == 404


def test_empty_and_oversized_batches_are_rejected(client):
    assert client.post("/v1/batch", json={"items": []}).status_code == 422
    too_many = _items(*[f"https://s{i}.example" for i in range(batch.MAX_ITEMS + 1)])
    assert client.post("/v1/batch", json=too_many).status_code == 422


def test_item_validation_applies(client):
    """배치 안의 항목도 단건과 같은 검증을 받는다 (예: 무시할 수 없는 코드)."""
    r = client.post("/v1/batch", json={"items": [
        {"url": "https://a.example", "ignore_codes": ["ABUSE-CLOAKING"]},
    ]})
    assert r.status_code == 422


def test_batch_is_paced_by_rate_limit_not_rejected(client, monkeypatch):
    """한도보다 큰 배치도 받는다. 다만 한도만큼만 돌고 나머지는 기다린다 —
    그 사이 같은 클라이언트의 단건 요청은 429다(배치로 한도를 우회할 수 없다)."""
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    r = client.post("/v1/batch", json=_items(
        "https://a.example", "https://b.example", "https://c.example"))
    assert r.status_code == 202
    job = r.json()["job_id"]
    for _ in range(200):
        body = client.get(f"/v1/batch/{job}").json()
        if body["done"] == 2:
            break
    assert body["done"] == 2
    assert body["status"] == "running"
    assert body["items"][2]["status"] in ("queued", "running")
    single = client.post("/v1/check", json={"url": "https://d.example", "use_llm": False})
    assert single.status_code == 429


def test_api_key_protects_batch(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "k")
    assert client.post("/v1/batch", json=_items("https://a.example")).status_code == 401
    ok = client.post("/v1/batch", json=_items("https://a.example"), headers={"X-API-Key": "k"})
    assert ok.status_code == 202
    job = ok.json()["job_id"]
    assert client.get(f"/v1/batch/{job}").status_code == 401


# ---------------------------------------------------------------------------
# 저장소 — 메모리가 무한정 늘지 않는다
# ---------------------------------------------------------------------------


def test_store_expires_old_jobs():
    s = batch.JobStore(ttl=10, max_jobs=100)
    job = s.create(1, now=0.0)
    assert s.get(job.id, now=5.0) is job
    assert s.get(job.id, now=11.0) is None


def test_store_refuses_when_full_of_running_jobs():
    s = batch.JobStore(ttl=1000, max_jobs=2)
    s.create(1, now=0.0)
    s.create(1, now=0.0)
    with pytest.raises(batch.StoreFull):
        s.create(1, now=0.0)


def test_store_evicts_finished_jobs_first_when_full():
    s = batch.JobStore(ttl=1000, max_jobs=2)
    a = s.create(1, now=0.0)
    a.finished_at = 1.0
    s.create(1, now=0.0)
    s.create(1, now=2.0)  # 끝난 a를 밀어내고 들어간다
    assert s.get(a.id, now=2.0) is None
