"""`python -m adpolicy.ads` — 반려 복구 루프 1~4단계를 한 번 돌린다.

기본은 픽스처 모드다. 개발자 토큰이 없어도 파이프라인 전체가 끝까지 돈다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import DEFAULT_FIXTURE_DIR, FakeAdsClient
from .mapping import UnmappedLedger, validate_table
from .recheck import make_offline_checker, recheck_all
from .report import render_console, render_markdown
from .watcher import AccountHalted, SeenIndex, collect


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m adpolicy.ads",
        description="반려 사유를 수집해 사전 점검 재현율을 측정한다 "
                    "(기본: 픽스처 모드, 네트워크 사용 안 함).",
    )
    ap.add_argument("--customer", default="1234567890", help="계정 ID")
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_DIR,
                    help=f"픽스처 폴더 (기본: {DEFAULT_FIXTURE_DIR})")
    ap.add_argument("--md", type=Path, default=None, help="마크다운 리포트 경로")
    ap.add_argument("--unmapped-log", type=Path, default=None,
                    help="미매핑 사유를 append할 jsonl 경로")
    ap.add_argument("--live", action="store_true",
                    help="실제 Ads API 사용 (아직 구현되지 않았습니다)")
    args = ap.parse_args(argv)

    if args.live:
        print(
            "실제 Ads API 어댑터는 아직 구현되지 않았습니다.\n"
            "개발자 토큰과 테스트 계정으로 응답을 한 번 덤프해 "
            f"{args.fixtures} 에 넣고 스키마를 교정한 뒤 구현하세요.\n"
            "자세한 순서는 ads/client.py의 GoogleAdsClient 주석을 보십시오.",
            file=sys.stderr,
        )
        return 2

    if bad := validate_table():
        print("매핑표가 카탈로그에 없는 코드를 가리킵니다:", file=sys.stderr)
        for line in bad:
            print(f"  - {line}", file=sys.stderr)
        return 2

    client = FakeAdsClient(args.fixtures)
    try:
        watch = collect(client, args.customer, seen=SeenIndex())
    except AccountHalted as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 1

    print(f"계정 {watch.account.customer_id} "
          f"({watch.account.status.value}) — {watch.note}")

    pages_file = args.fixtures / "landing_pages.json"
    pages = json.loads(pages_file.read_text("utf-8")) if pages_file.exists() else {}
    if not pages:
        print("⚠️ landing_pages.json이 없어 재점검을 건너뜁니다.", file=sys.stderr)

    ledger = UnmappedLedger(args.unmapped_log)
    report = recheck_all(watch.actionable, make_offline_checker(pages),
                         ledger=ledger)
    print()
    print(render_console(report))

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(render_markdown(report, ledger), "utf-8")
        print(f"\n리포트: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
