"""API 접근 제어 — 선택적 API 키와 /v1/check 속도 제한.

기본값은 로컬 단독 사용이다. 키를 안 걸면 지금처럼 열려 있고, 포트는
docker-compose가 127.0.0.1에만 묶는다. 다른 기기와 나눠 쓰려고 포트를
열 때 API_KEY를 걸면 된다.

속도 제한은 키와 무관하게 켜 둔다. 점검 한 번이 외부 페이지 여러 개를
가져오고 LLM 토큰을 쓰므로, 키를 가진 쪽이라도 무한정 돌리게 두면 안 된다.
"""

from __future__ import annotations

import hmac
import math
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

WINDOW = 60.0


def _configured_key() -> str:
    # 요청마다 읽는다 — 테스트와 재시작 없는 설정 변경 둘 다 단순해진다.
    return os.getenv("API_KEY", "").strip()


def _presented_key(request: Request) -> str:
    key = request.headers.get("x-api-key", "")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


async def require_api_key(request: Request) -> None:
    """API_KEY가 설정돼 있으면 X-API-Key 또는 Bearer 토큰을 요구한다."""
    expected = _configured_key()
    if not expected:
        return
    # 길이·내용 차이가 응답 시간으로 새지 않게 상수 시간 비교.
    if not hmac.compare_digest(_presented_key(request).encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="API 키가 필요합니다. X-API-Key 헤더로 보내세요.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class RateLimiter:
    """클라이언트별 60초 슬라이딩 창. 프로세스 하나 안에서만 센다.

    uvicorn 워커를 여러 개 띄우면 워커마다 따로 센다 — 이 서비스는 워커
    하나로 도는 걸 전제로 한다(Dockerfile 기본값).
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def hit(self, client: str, *, limit: int, now: float | None = None) -> float:
        """요청 한 번을 센다. 허용이면 0, 초과면 기다려야 할 초를 돌려준다."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._sweep(now)
            q = self._hits.setdefault(client, deque())
            while q and q[0] <= now - WINDOW:
                q.popleft()
            if len(q) >= limit:
                return max(q[0] + WINDOW - now, 0.001)
            q.append(now)
            return 0.0

    def _sweep(self, now: float) -> None:
        # 한동안 조용한 클라이언트를 버린다. 안 그러면 IP마다 영원히 쌓인다.
        if now - self._last_sweep < WINDOW:
            return
        self._last_sweep = now
        for key in [k for k, q in self._hits.items() if not q or q[-1] <= now - WINDOW]:
            del self._hits[key]


check_limiter = RateLimiter()


def _limit_per_min() -> int:
    try:
        return int(os.getenv("RATE_LIMIT_PER_MIN", "20"))
    except ValueError:
        return 20


async def limit_checks(request: Request) -> None:
    """/v1/check 전용. RATE_LIMIT_PER_MIN=0이면 끈다."""
    limit = _limit_per_min()
    if limit <= 0:
        return
    client = request.client.host if request.client else "unknown"
    wait = check_limiter.hit(client, limit=limit)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"점검 요청이 너무 많습니다. 분당 {limit}회까지입니다.",
            headers={"Retry-After": str(math.ceil(wait))},
        )
