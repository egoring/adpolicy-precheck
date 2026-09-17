"""평가 하네스 자체의 테스트.

하네스가 틀리면 모든 숫자가 거짓말이 된다. 채점 규칙과 골든셋 검증을
먼저 못 박아 둔다.
"""

from __future__ import annotations

import json

import pytest

from adpolicy.evalkit import (
    GoldenCase,
    GoldenError,
    build_scope,
    critical_false_alarms,
    load_cases,
    render_markdown,
    run_all,
    run_case,
)
from adpolicy.evalkit.loader import DEFAULT_GOLDEN_DIR
from adpolicy.evalkit.models import CodeMetric, EvalReport

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>t</title></head><body><p>{}</p></body></html>"""


def case(**kw) -> GoldenCase:
    base = dict(id="c", html=PAGE.format("가" * 800))
    base.update(kw)
    return GoldenCase(**base)


# --- 채점 규칙 -------------------------------------------------------------

def test_expected_code_that_appears_is_a_hit():
    c = case(html=PAGE.format("짧음"), expect=("DEST-INSUFFICIENT-CONTENT",))
    res = run_case(c, build_scope([c]))
    assert res.hit == {"DEST-INSUFFICIENT-CONTENT"}
    assert not res.missed
    assert res.ok


def test_expected_code_that_is_absent_is_a_miss():
    c = case(expect=("PROHIB-COUNTERFEIT",))
    res = run_case(c, build_scope([c]))
    assert res.missed == {"PROHIB-COUNTERFEIT"}
    assert not res.ok


def test_forbidden_code_that_appears_is_a_false_alarm():
    c = case(html=PAGE.format("짧음"), forbid=("DEST-INSUFFICIENT-CONTENT",))
    res = run_case(c, build_scope([c]))
    assert res.false_alarm == {"DEST-INSUFFICIENT-CONTENT"}
    assert not res.ok


def test_codes_outside_scope_are_not_scored():
    """라벨이 없는 코드를 틀렸다고 말하지 않는다 — 대신 unscored로 드러낸다."""
    c = case(html=PAGE.format("짧음"))          # expect도 forbid도 비어 있다
    scope = build_scope([c])                    # 따라서 scope는 공집합
    res = run_case(c, scope)
    assert res.ok                               # 채점할 게 없으니 통과
    assert "DEST-INSUFFICIENT-CONTENT" in res.unscored


def test_scope_is_built_from_both_expect_and_forbid():
    a = case(id="a", expect=("MIS-SUPERLATIVE",))
    b = case(id="b", forbid=("ABUSE-CLOAKING",))
    assert build_scope([a, b]) == {"MIS-SUPERLATIVE", "ABUSE-CLOAKING"}


def test_runner_records_error_instead_of_crashing(monkeypatch):
    """케이스 하나가 터져도 전체 실행이 멈추면 안 된다."""
    import adpolicy.evalkit.runner as R

    def boom(*_a, **_k):
        raise RuntimeError("terrible")

    monkeypatch.setattr(R, "_extract", boom)
    c = case(expect=("MIS-SUPERLATIVE",))
    report = run_all([c, c], build_scope([c]))
    assert len(report.results) == 2
    assert all("terrible" in r.error for r in report.results)
    # 실행 실패한 케이스는 지표를 오염시키지 않는다
    assert report.totals() == (0, 0, 0)


# --- 지표 -----------------------------------------------------------------

def test_metric_returns_none_instead_of_zero_when_undefined():
    """분모가 0일 때 0.0을 돌려주면 '정밀도 0%'로 읽혀 오해를 부른다."""
    m = CodeMetric(code="X")
    assert m.precision is None
    assert m.recall is None
    assert m.f1 is None


def test_support_is_exposed_so_small_samples_are_visible():
    m = CodeMetric(code="X", tp=1, fn=1, fp=3, tn=5)
    assert m.support == 2          # 정답으로 등장한 횟수
    assert m.scored == 10          # 채점된 횟수
    assert m.precision == 0.25


def test_macro_and_micro_differ_when_one_code_dominates():
    rep = EvalReport(per_code={
        "A": CodeMetric(code="A", tp=90, fp=10),   # 흔한 코드, P=0.9
        "B": CodeMetric(code="B", tp=0, fp=2),     # 드문 코드, P=0.0
    })
    micro_p, _, _ = rep.micro()
    macro_p, _, _ = rep.macro()
    assert micro_p == pytest.approx(90 / 102)
    assert macro_p == pytest.approx(0.45)
    assert micro_p > macro_p


# --- 골든셋 검증 ------------------------------------------------------------

def _write(tmp_path, rows, pages=("c",)):
    (tmp_path / "pages").mkdir(parents=True, exist_ok=True)
    for p in pages:
        (tmp_path / "pages" / f"{p}.html").write_text(PAGE.format("x"), "utf-8")
    (tmp_path / "cases.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    return tmp_path


def test_duplicate_id_is_rejected(tmp_path):
    d = _write(tmp_path, [{"id": "c"}, {"id": "c"}])
    with pytest.raises(GoldenError, match="중복"):
        load_cases(d)


def test_unknown_key_is_rejected(tmp_path):
    """오타를 조용히 무시하면 라벨이 사라진 줄도 모르게 된다."""
    d = _write(tmp_path, [{"id": "c", "expcet": ["X"]}])
    with pytest.raises(GoldenError, match="모르는 키"):
        load_cases(d)


def test_code_in_both_expect_and_forbid_is_rejected(tmp_path):
    d = _write(tmp_path, [{"id": "c", "expect": ["X"], "forbid": ["X"]}])
    with pytest.raises(GoldenError, match="expect와 forbid"):
        load_cases(d)


def test_missing_page_file_is_rejected(tmp_path):
    d = _write(tmp_path, [{"id": "c", "html_file": "nope.html"}])
    with pytest.raises(GoldenError, match="페이지 파일이 없습니다"):
        load_cases(d)


# --- 실제 골든셋 ------------------------------------------------------------

def test_repo_golden_set_loads_and_has_both_polarities():
    cases = load_cases(DEFAULT_GOLDEN_DIR)
    assert len(cases) >= 20
    assert any(c.expect for c in cases), "위반 케이스가 있어야 한다"
    assert any(c.forbid for c in cases), "오탐 트랩이 있어야 한다"


def test_repo_golden_set_has_no_suspend_level_false_alarms():
    """계정 정지급 오탐은 다른 오탐과 무게가 다르다. 하나도 없어야 한다."""
    cases = load_cases(DEFAULT_GOLDEN_DIR)
    report = run_all(cases, build_scope(cases))
    assert critical_false_alarms(report) == []


def test_repo_golden_set_runs_without_errors():
    cases = load_cases(DEFAULT_GOLDEN_DIR)
    report = run_all(cases, build_scope(cases))
    assert report.errored == [], [r.error for r in report.errored]


def test_markdown_report_shows_sample_counts():
    """표본 수 없는 비율은 착시를 만든다. 리포트에 반드시 들어가야 한다."""
    cases = load_cases(DEFAULT_GOLDEN_DIR)
    report = run_all(cases, build_scope(cases))
    md = render_markdown(report, cases)
    assert "정답 표본" in md
    assert "계정 정지급 오탐" in md
