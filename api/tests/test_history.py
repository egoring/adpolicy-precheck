"""점검 이력 — 수정 전후 비교와 심사 후 바꿔치기.

실제로 이 도구를 쓰는 흐름은 "돌린다 → 고친다 → 다시 돌린다"다. 그때
알고 싶은 건 전체 목록이 아니라 무엇이 해결됐고 무엇이 새로 생겼는지다.
같은 장부가 "심사 통과 뒤 갈아끼웠는가"도 답한다.

**이력 기록이 실패해도 점검 결과는 나가야 한다.** 부가 기능 때문에
본래 기능이 죽으면 안 된다.
"""

from __future__ import annotations

import json
import time

import pytest

from adpolicy import history


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_LOG", str(tmp_path / "history.jsonl"))
    return tmp_path / "history.jsonl"


# ---------------------------------------------------------------------------
# 주소를 무엇으로 같다고 볼 것인가
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("a", "b"), [
    ("https://ex.com/lp", "https://ex.com/lp/"),
    ("https://EX.com/lp", "https://ex.com/lp"),
    ("https://ex.com/lp#top", "https://ex.com/lp"),
    ("  https://ex.com/lp  ", "https://ex.com/lp"),
])
def test_trivially_different_urls_are_the_same_page(a, b):
    assert history.url_key(a) == history.url_key(b)


def test_the_query_string_makes_it_a_different_page():
    """국내 랜딩페이지는 ?lp=12 하나로 완전히 다른 페이지가 된다.

    쿼리를 버리면 전혀 다른 두 페이지의 이력이 뒤섞인다.
    """
    assert history.url_key("https://ex.com/lp?id=1") != history.url_key(
        "https://ex.com/lp?id=2")


# ---------------------------------------------------------------------------
# 기록과 조회
# ---------------------------------------------------------------------------


def put(url: str, score: int, codes: list[str], fingerprint: str) -> None:
    history.record({
        "url_key": history.url_key(url), "url": url, "score": score,
        "codes": codes, "fingerprint": fingerprint, "verdict": "review",
    })


def test_the_latest_check_for_a_url_comes_back():
    put("https://ex.com/lp", 40, ["A"], "aaa")
    time.sleep(0.01)
    put("https://ex.com/lp", 70, ["B"], "bbb")
    last = history.last_for("https://ex.com/lp")
    assert last["score"] == 70 and last["fingerprint"] == "bbb"


def test_other_urls_do_not_leak_into_the_comparison():
    put("https://ex.com/a", 10, ["A"], "aaa")
    put("https://ex.com/b", 90, ["B"], "bbb")
    assert history.last_for("https://ex.com/a")["score"] == 10


def test_a_first_check_has_nothing_to_compare_against():
    assert history.last_for("https://ex.com/new") is None


def test_a_half_written_line_does_not_break_the_ledger():
    """파일에 직접 쓰므로 중간에 끊길 수 있다. 그 한 줄만 건너뛴다."""
    put("https://ex.com/lp", 40, ["A"], "aaa")
    with open(history.HISTORY_LOG, "a", encoding="utf-8") as fh:
        fh.write('{"url_key": "https://ex.com/lp", "sco\n')
    assert history.last_for("https://ex.com/lp")["score"] == 40


def test_the_ledger_does_not_grow_forever(monkeypatch):
    monkeypatch.setattr(history, "HISTORY_MAX_LINES", 10)
    for i in range(25):
        put("https://ex.com/lp", i, [], f"fp{i}")
    with open(history.HISTORY_LOG, encoding="utf-8") as fh:
        lines = fh.readlines()
    assert len(lines) <= 10
    # 잘라내도 최신은 남아야 한다
    assert json.loads(lines[-1])["score"] == 24


def test_a_failed_write_does_not_raise(monkeypatch):
    """디스크가 차도 점검 결과는 나가야 한다."""
    monkeypatch.setattr(history, "HISTORY_LOG", "/이런/경로는/없다/h.jsonl")
    history.record({"url_key": "x", "score": 1})   # 예외가 나면 안 된다


def test_history_can_be_turned_off():
    history.HISTORY_LOG = ""
    try:
        history.record({"url_key": "x"})
        assert history.last_for("https://ex.com/lp") is None
    finally:
        pass  # fixture가 다음 테스트에서 다시 세팅한다


# ---------------------------------------------------------------------------
# 비교 — 이게 실제로 쓰는 기능이다
# ---------------------------------------------------------------------------


def test_fixing_things_shows_up_as_resolved():
    prev = {"ts": 1.0, "score": 40, "fingerprint": "aaa",
            "codes": ["MIS-CLICKBAIT", "RESTRICT-FINANCIAL", "MIS-SUPERLATIVE"]}
    diff = history.compare(prev, ["MIS-SUPERLATIVE"], 78, "bbb")
    assert diff["resolved_codes"] == ["MIS-CLICKBAIT", "RESTRICT-FINANCIAL"]
    assert diff["new_codes"] == []
    assert diff["score_delta"] == 38
    assert "2건 해결" in diff["note"] and "점수 40 → 78" in diff["note"]


def test_breaking_things_shows_up_as_new():
    prev = {"ts": 1.0, "score": 80, "fingerprint": "aaa", "codes": ["MIS-SUPERLATIVE"]}
    diff = history.compare(prev, ["MIS-SUPERLATIVE", "RESTRICT-CRYPTO"], 60, "bbb")
    assert diff["new_codes"] == ["RESTRICT-CRYPTO"]
    assert diff["score_delta"] == -20
    assert "1건 새로 생김" in diff["note"]


def test_no_change_says_so_plainly():
    prev = {"ts": 1.0, "score": 70, "fingerprint": "aaa", "codes": ["A"]}
    diff = history.compare(prev, ["A"], 70, "aaa")
    assert diff["resolved_codes"] == [] and diff["new_codes"] == []
    assert "그대로" in diff["note"]
    assert diff["content_changed"] is False


def test_a_changed_body_is_reported_even_when_the_findings_match():
    """지적 목록이 같아도 본문이 바뀌었으면 알려야 한다.

    심사 통과 뒤 갈아끼우는 경우가 정확히 이 모양이 될 수 있다.
    """
    prev = {"ts": 1.0, "score": 70, "fingerprint": "aaa", "codes": ["A"]}
    diff = history.compare(prev, ["A"], 70, "bbb")
    assert diff["content_changed"] is True
    assert "본문이 바뀌었습니다" in diff["note"]


def test_an_old_record_without_a_fingerprint_does_not_cry_wolf():
    """지문이 없던 시절의 기록과 비교해 '바뀌었다'고 하면 거짓이다."""
    prev = {"ts": 1.0, "score": 70, "codes": ["A"]}
    diff = history.compare(prev, ["A"], 70, "bbb")
    assert diff["content_changed"] is False
