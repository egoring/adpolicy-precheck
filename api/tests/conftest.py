from __future__ import annotations

import pytest

from adpolicy import access


@pytest.fixture(autouse=True)
def _reset_rate_limiter(monkeypatch):
    """속도 제한은 프로세스 전역이다. 테스트끼리 한도를 나눠 쓰면 순서에 따라 429가 난다."""
    monkeypatch.setattr(access, "check_limiter", access.RateLimiter())
