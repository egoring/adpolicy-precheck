"""재현율 리포트.

평가 하네스의 리포트와 같은 규칙을 따른다 — **비율 옆에 항상 표본 수**를 쓴다.
반려 3건으로 잰 재현율 100%는 정보가 아니다.
"""

from __future__ import annotations

from .mapping import UnmappedLedger
from .models import RecallReport


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_markdown(report: RecallReport,
                    ledger: UnmappedLedger | None = None) -> str:
    L: list[str] = []
    A = L.append  # noqa: N806

    A("# 사전 점검 재현율 (실제 반려 기준)")
    A("")
    A("평가 하네스가 **우리가 만든 라벨**로 재는 것이라면, 이 리포트는 "
      "**Google의 실제 판정**으로 잽니다. 라벨의 출처가 다르므로 둘은 "
      "경쟁하지 않고 보완합니다.")
    A("")

    n = report.total
    if n == 0:
        A("> 아직 반려 사유가 하나도 없습니다. 측정할 것이 없습니다.")
        return "\n".join(L)

    A("## 요약")
    A("")
    A("| 항목 | 값 | 표본 |")
    A("|---|---|---:|")
    A(f"| 수집한 반려 사유 | — | {n} |")
    A(f"| 규칙 대응률 (coverage) | {_pct(report.coverage)} | "
      f"{report.mapped}/{n} |")
    A(f"| **재현율** (매핑된 것 중 우리도 잡은 비율) | "
      f"**{_pct(report.recall_on_mapped)}** | {report.hits}/{report.mapped} |")
    A("")
    A(f"- ✅ 우리도 잡음 (hit): **{report.hits}건**")
    A(f"- ❌ 규칙은 있는데 못 잡음 (miss): **{report.misses}건** — 민감도 문제")
    A(f"- ⬜ 대응 규칙 자체가 없음 (no_rule): **{report.no_rule}건** — 신규 규칙 후보")
    A("")
    if n < 30:
        A(f"> ⚠️ 표본 {n}건은 비율을 신뢰하기에 적습니다. "
          "경향으로만 읽으세요.")
        A("")

    missed = report.missed_topics()
    A("## 못 잡은 사유 (규칙 민감도를 손볼 대상)")
    A("")
    if not missed:
        A("없음.")
    else:
        A("| Google 사유 | 건수 | 대응 규칙 |")
        A("|---|---:|---|")
        for topic, cnt in missed.items():
            codes = next(
                (", ".join(f"`{c}`" for c in o.rule_codes)
                 for o in report.outcomes
                 if o.topic == topic and o.verdict == "miss"), "")
            A(f"| `{topic}` | {cnt} | {codes} |")
    A("")

    unmapped = report.unmapped_topics()
    A("## 대응 규칙이 없는 사유 (신규 규칙 후보)")
    A("")
    A("Google은 반려했는데 우리 규칙 체계에는 대응물이 없는 것들입니다. "
      "**이 목록이 곧 로드맵입니다.**")
    A("")
    if not unmapped:
        A("없음 — 수집된 모든 사유에 대응 규칙이 있습니다.")
    else:
        A("| Google 사유 | 건수 |")
        A("|---|---:|")
        for topic, cnt in unmapped.items():
            A(f"| `{topic}` | {cnt} |")
    A("")

    if ledger is not None and ledger.total:
        A(f"> 누적 미매핑 원장: {ledger.total}건 "
          f"({len(ledger.counts())}종). 버리지 않고 쌓고 있습니다.")
        A("")

    A("## 소재별 상세")
    A("")
    A("| 소재 | 사유 | 판정 | 비고 |")
    A("|---|---|---|---|")
    mark = {"hit": "✅ hit", "miss": "❌ miss", "no_rule": "⬜ no_rule"}
    for o in report.outcomes:
        A(f"| `{o.ad_id}` | `{o.topic}` | {mark[o.verdict]} | {o.note} |")
    A("")
    return "\n".join(L)


def render_console(report: RecallReport) -> str:
    if report.total == 0:
        return "반려 사유 0건 — 측정할 것이 없습니다."
    lines = [
        f"반려 사유 {report.total}건  "
        f"(대응 {report.mapped} · 미대응 {report.no_rule})",
        f"재현율 {_pct(report.recall_on_mapped)}  "
        f"[hit {report.hits} / miss {report.misses}]",
    ]
    if report.total < 30:
        lines.append(f"⚠️ 표본 {report.total}건 — 비율을 신뢰하지 마세요.")
    for topic, cnt in report.missed_topics().items():
        lines.append(f"  ❌ 못 잡음 {topic} ×{cnt}")
    for topic, cnt in report.unmapped_topics().items():
        lines.append(f"  ⬜ 규칙 없음 {topic} ×{cnt}")
    return "\n".join(lines)
