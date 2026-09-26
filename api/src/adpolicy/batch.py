"""배치 점검(C-4) — 여러 건을 받아 작업 번호를 돌려주고 뒤에서 돌린다.

대행사는 캠페인 단위로 수십 건을 점검한다. 단건 요청 하나가 LLM 포함 수 분을
잡을 수 있어, 한 요청 안에서 다 끝내려 하면 프록시·브라우저가 먼저 끊는다.

저장은 프로세스 메모리다. 재시작하면 진행 중인 작업은 사라진다 — 결과를
오래 보관하는 용도가 아니라 '돌려 놓고 몇 분 뒤 가져가는' 용도다. 오래 남길
것은 이력 장부(history.jsonl)에 이미 한 줄씩 적힌다.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .models import CheckRequest, CheckResponse

MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", "50"))
CONCURRENCY = max(1, int(os.getenv("BATCH_CONCURRENCY", "2")))
TTL = float(os.getenv("BATCH_TTL", "3600"))
MAX_JOBS = int(os.getenv("BATCH_MAX_JOBS", "20"))


class BatchRequest(BaseModel):
    items: list[CheckRequest] = Field(
        min_length=1, max_length=MAX_ITEMS,
        description=f"점검할 항목들. 각 항목은 /v1/check 요청과 같다. 최대 {MAX_ITEMS}건.",
    )


class BatchItem(BaseModel):
    index: int
    url: str
    status: Literal["queued", "running", "ok", "error"] = "queued"
    result: CheckResponse | None = None
    error: str = ""


class BatchStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done"]
    total: int
    done: int = Field(description="끝난 항목 수 (성공+실패)")
    failed: int
    items: list[BatchItem]


class StoreFull(Exception):
    """진행 중인 작업이 상한에 찼다."""


@dataclass
class Job:
    id: str
    created_at: float
    items: list[BatchItem] = field(default_factory=list)
    finished_at: float | None = None
    task: asyncio.Task | None = None  # 참조를 쥐고 있어야 GC가 중간에 거두지 않는다

    def snapshot(self) -> BatchStatus:
        done = sum(1 for it in self.items if it.status in ("ok", "error"))
        started = any(it.status != "queued" for it in self.items)
        status = "done" if self.finished_at is not None else ("running" if started else "queued")
        return BatchStatus(
            job_id=self.id, status=status, total=len(self.items), done=done,
            failed=sum(1 for it in self.items if it.status == "error"),
            items=self.items,
        )


class JobStore:
    """만료·상한이 있는 작업 보관소. 메모리가 무한정 늘지 않게 한다."""

    def __init__(self, ttl: float = TTL, max_jobs: int = MAX_JOBS) -> None:
        self.ttl = ttl
        self.max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}

    def _sweep(self, now: float) -> None:
        for jid in [j.id for j in self._jobs.values() if now - j.created_at > self.ttl]:
            del self._jobs[jid]

    def create(self, n: int, *, now: float | None = None) -> Job:
        now = time.monotonic() if now is None else now
        self._sweep(now)
        if len(self._jobs) >= self.max_jobs:
            finished = sorted((j for j in self._jobs.values() if j.finished_at is not None),
                              key=lambda j: j.finished_at)
            if not finished:
                raise StoreFull
            del self._jobs[finished[0].id]
        # 결과에 점검한 URL이 들어 있다. 번호를 추측해 남의 결과를 보지 못하게.
        job = Job(id=secrets.token_urlsafe(18), created_at=now)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str, *, now: float | None = None) -> Job | None:
        self._sweep(time.monotonic() if now is None else now)
        return self._jobs.get(job_id)


store = JobStore()

Runner = Callable[[CheckRequest], Awaitable[CheckResponse]]


async def run(job: Job, reqs: list[CheckRequest], runner: Runner) -> None:
    """항목을 CONCURRENCY건씩 돌린다. 한 건이 실패해도 나머지는 계속한다."""
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(item: BatchItem, req: CheckRequest) -> None:
        async with gate:
            item.status = "running"
            try:
                item.result = await runner(req)
                item.status = "ok"
            except Exception as exc:  # noqa: BLE001 — 항목 하나가 배치를 죽이면 안 된다
                item.status = "error"
                detail = getattr(exc, "detail", "") or str(exc)
                item.error = f"{type(exc).__name__}: {detail}"[:500]

    try:
        await asyncio.gather(*(one(it, rq) for it, rq in zip(job.items, reqs, strict=True)))
    finally:
        job.finished_at = time.monotonic()
