"""점검 이력 장부.

두 가지를 해결한다.

1. **심사 후 바꿔치기.** 한 번의 점검으로는 원리적으로 못 잡는다. 지난번에
   본 본문의 지문을 들고 있어야 "그 사이 바뀌었다"를 말할 수 있다.

2. **수정 전후 비교.** 사실 이쪽을 더 자주 쓰게 된다. 고치고 다시 돌렸을 때
   "3건 해결, 1건 새로 생김, 점수 42 → 78"이 바로 나와야 작업이 된다.
   매번 두 결과를 눈으로 대조하게 만들면 아무도 안 한다.

파일 한 줄에 한 점검. DB를 두지 않는다 — 로컬 도구이고, 이력은 사람이
직접 열어볼 수 있는 편이 낫다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)

HISTORY_LOG = os.getenv("CHECK_HISTORY_LOG", "/app/data/history.jsonl")
# 한 URL당 들고 있을 개수. 넘으면 오래된 것부터 잊는다.
HISTORY_KEEP_PER_URL = int(os.getenv("CHECK_HISTORY_KEEP", "20"))
# 파일 전체 상한. 이걸 넘으면 앞부분을 잘라낸다.
HISTORY_MAX_LINES = int(os.getenv("CHECK_HISTORY_MAX_LINES", "5000"))

_lock = threading.Lock()


def url_key(url: str) -> str:
    """비교 기준이 되는 주소.

    프래그먼트와 끝 슬래시는 버리고 호스트는 소문자로. **쿼리는 남긴다** —
    국내 랜딩페이지는 `?lp=12` 하나로 완전히 다른 페이지가 되기 때문이다.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def _read_all() -> list[dict]:
    if not HISTORY_LOG or not os.path.exists(HISTORY_LOG):
        return []
    try:
        with open(HISTORY_LOG, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        log.warning("점검 이력을 읽지 못했습니다: %s", exc)
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # 쓰다 만 줄은 조용히 건너뛴다
        if isinstance(row, dict):
            out.append(row)
    return out


def record(entry: dict) -> None:
    """한 번의 점검을 적는다. 실패해도 점검 결과는 나가야 한다."""
    if not HISTORY_LOG:
        return
    entry = {"ts": time.time(), **entry}
    try:
        with _lock:
            os.makedirs(os.path.dirname(HISTORY_LOG) or ".", exist_ok=True)
            with open(HISTORY_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _trim_if_needed()
    except OSError as exc:
        log.warning("점검 이력을 남기지 못했습니다: %s", exc)


def _trim_if_needed() -> None:
    """파일이 무한정 자라지 않게 한다. 호출부가 이미 락을 잡고 있다."""
    try:
        with open(HISTORY_LOG, encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) <= HISTORY_MAX_LINES:
            return
        with open(HISTORY_LOG, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-HISTORY_MAX_LINES:])
    except OSError:
        return


def for_url(url: str, limit: int = HISTORY_KEEP_PER_URL) -> list[dict]:
    """그 주소의 점검 이력, 최신이 앞."""
    key = url_key(url)
    rows = [r for r in _read_all() if r.get("url_key") == key]
    return rows[::-1][:limit]


def recent(limit: int = 20) -> list[dict]:
    """주소 구분 없이 최근 점검, 최신이 앞."""
    return _read_all()[::-1][:limit]


def last_for(url: str) -> dict | None:
    rows = for_url(url, limit=1)
    return rows[0] if rows else None


def compare(previous: dict, codes: list[str], score: int, fingerprint: str) -> dict:
    """지난 점검과 이번 점검의 차이.

    지적 코드의 집합 차이를 본다. 같은 코드가 근거만 바뀐 경우는 '그대로'로
    보는데, 사용자 입장에서 "아직 안 고쳐졌다"가 맞는 표현이기 때문이다.
    """
    before = set(previous.get("codes") or [])
    after = set(codes)
    prev_score = int(previous.get("score") or 0)
    changed = bool(previous.get("fingerprint")) and previous["fingerprint"] != fingerprint

    resolved = sorted(before - after)
    added = sorted(after - before)

    bits = []
    if resolved:
        bits.append(f"{len(resolved)}건 해결")
    if added:
        bits.append(f"{len(added)}건 새로 생김")
    if not resolved and not added:
        bits.append("지적 목록은 그대로")
    bits.append(f"점수 {prev_score} → {score}")
    if changed:
        bits.append("본문이 바뀌었습니다")

    return {
        "previous_at": float(previous.get("ts") or 0),
        "previous_fingerprint": str(previous.get("fingerprint") or ""),
        "previous_score": prev_score,
        "score_delta": score - prev_score,
        "content_changed": changed,
        "resolved_codes": resolved,
        "new_codes": added,
        "note": " · ".join(bits),
    }
