"""`python -m adpolicy.evalkit` 진입점."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loader import DEFAULT_GOLDEN_DIR, GoldenError, build_scope, load_cases
from .report import critical_false_alarms, render_console, render_markdown
from .runner import run_all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m adpolicy.evalkit",
        description="골든셋으로 사전 점검 정확도를 측정한다 (네트워크·LLM 사용 안 함).",
    )
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_DIR,
                    help=f"골든셋 폴더 (기본: {DEFAULT_GOLDEN_DIR})")
    ap.add_argument("--md", type=Path, default=None,
                    help="마크다운 리포트를 쓸 경로")
    ap.add_argument("--fail-under", type=float, default=None, metavar="F1",
                    help="micro F1이 이 값 미만이면 종료 코드 1 (CI용)")
    ap.add_argument("--no-critical", action="store_true",
                    help="계정 정지급 오탐이 하나라도 있으면 종료 코드 1")
    args = ap.parse_args(argv)

    try:
        cases = load_cases(args.golden)
    except GoldenError as exc:
        print(f"골든셋 오류: {exc}", file=sys.stderr)
        return 2

    scope = build_scope(cases)
    report = run_all(cases, scope)
    print(render_console(report))

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(render_markdown(report, cases), "utf-8")
        print(f"\n리포트: {args.md}")

    failed = 0
    if report.errored:
        print(f"\n실행 실패 {len(report.errored)}건 — 코드 문제입니다.", file=sys.stderr)
        failed = 1
    if args.no_critical and critical_false_alarms(report):
        print("계정 정지급 오탐이 있습니다.", file=sys.stderr)
        failed = 1
    if args.fail_under is not None:
        _, _, f1 = report.micro()
        if f1 is None or f1 < args.fail_under:
            print(f"micro F1 {f1} < 기준 {args.fail_under}", file=sys.stderr)
            failed = 1
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
