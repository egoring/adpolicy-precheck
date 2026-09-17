"""결과를 사람이 읽는 형태로 낸다 (터미널 + 마크다운).

리포트가 반드시 보여야 하는 것
    1. **표본 수** — 모든 비율 옆에 몇 건짜리인지 붙인다. 3건짜리 F1 1.00은
       정보가 아니라 착시다.
    2. **정지급 오탐** — 계정 정지 등급(suspend)의 오탐은 다른 오탐과 무게가
       다르다. v1에서 정상 쇼핑몰이 ABUSE-CLOAKING으로 보고된 사고가 있었다.
       따로 세어서 맨 위에 올린다.
    3. **채점 안 된 코드** — scope 밖이라 채점하지 않은 것을 숨기지 않는다.
       "라벨이 없어서 판단하지 않았다"와 "맞았다"는 다른 말이다.
"""

from __future__ import annotations

from ..models import Enforcement
from ..policies import POLICY_BY_CODE
from .models import EvalReport, GoldenCase


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _enforcement(code: str) -> Enforcement | None:
    item = POLICY_BY_CODE.get(code)
    return item.enforcement if item else None


def critical_false_alarms(report: EvalReport) -> list[tuple[str, str]]:
    """(케이스 id, 코드) — 계정 정지급 코드의 오탐만 추린다."""
    out: list[tuple[str, str]] = []
    for res in report.results:
        for code in sorted(res.false_alarm):
            if _enforcement(code) == Enforcement.SUSPEND:
                out.append((res.case_id, code))
    return out


def render_markdown(report: EvalReport, cases: list[GoldenCase]) -> str:
    by_id = {c.id: c for c in cases}
    mp, mr, mf = report.micro()
    Mp, Mr, Mf = report.macro()  # noqa: N806
    tp, fp, fn = report.totals()
    crit = critical_false_alarms(report)

    L: list[str] = []
    A = L.append  # noqa: N806

    A("# 사전 점검 정확도 리포트")
    A("")
    A(f"- 케이스 **{report.total}건** · 전부 통과 **{report.passed}건** "
      f"({report.passed / report.total * 100:.0f}%)" if report.total else "- 케이스 없음")
    A(f"- 채점 대상 코드 **{len(report.scope)}개** "
      f"(전체 {len(POLICY_BY_CODE)}개 중 라벨이 있는 것만)")
    A(f"- 실행 시간 {report.elapsed_sec:.2f}초 — 네트워크·LLM 사용 안 함")
    A("")

    # --- 가장 먼저 봐야 하는 것 -------------------------------------------
    A("## ⚠️ 계정 정지급 오탐")
    A("")
    if crit:
        A(f"**{len(crit)}건.** 광고 반려와 달리 계정이 즉시 정지될 수 있다고 "
          "보고한 것이므로, 다른 어떤 지표보다 먼저 고쳐야 합니다.")
        A("")
        A("| 케이스 | 코드 |")
        A("|---|---|")
        for cid, code in crit:
            A(f"| `{cid}` | **{code}** |")
    else:
        A("없음. 정상 페이지를 계정 정지급으로 보고한 사례가 없습니다.")
    A("")

    # --- 전체 지표 --------------------------------------------------------
    A("## 전체 지표")
    A("")
    A("| 방식 | 정밀도 | 재현율 | F1 | 비고 |")
    A("|---|---|---|---|---|")
    A(f"| micro | {_pct(mp)} | {_pct(mr)} | {_pct(mf)} | "
      f"TP {tp} · FP {fp} · FN {fn} |")
    A(f"| macro | {_pct(Mp)} | {_pct(Mr)} | {_pct(Mf)} | "
      "코드별 평균 — 표본 적은 코드도 같은 무게 |")
    A("")
    A("> micro는 흔한 코드가 전체 숫자를 끌고 갑니다. macro와 벌어지면 "
      "특정 코드만 잘 맞히고 있다는 뜻입니다.")
    A("")

    # --- 코드별 ------------------------------------------------------------
    A("## 코드별")
    A("")
    A("| 코드 | 등급 | 정답 표본 | TP | FP | FN | 정밀도 | 재현율 | F1 |")
    A("|---|---|---:|---:|---:|---:|---|---|---|")
    rows = sorted(
        report.per_code.values(),
        key=lambda m: (-(m.fp + m.fn), -m.support, m.code),
    )
    for m in rows:
        enf = _enforcement(m.code)
        badge = {
            Enforcement.SUSPEND: "🔴 정지",
            Enforcement.STRIKE: "🟠 경고",
            Enforcement.DISAPPROVE: "· 반려",
        }.get(enf, "—") if enf else "—"
        flag = " ⚠️" if (m.fp or m.fn) else ""
        A(f"| `{m.code}`{flag} | {badge} | {m.support} | {m.tp} | {m.fp} | "
          f"{m.fn} | {_pct(m.precision)} | {_pct(m.recall)} | {_pct(m.f1)} |")
    A("")
    A("> **정답 표본**이 5 미만인 줄의 비율은 신뢰하지 마세요. "
      "케이스를 더 넣어야 의미가 생깁니다.")
    A("")

    # --- 실패한 케이스 ------------------------------------------------------
    failed = [r for r in report.results if not r.ok]
    A("## 틀린 케이스")
    A("")
    if not failed:
        A("없음.")
    else:
        for r in failed:
            c = by_id.get(r.case_id)
            A(f"### `{r.case_id}`")
            if c and c.note:
                A(f"> {c.note}")
            A("")
            if r.error:
                A(f"- 💥 실행 실패: `{r.error}`")
            if r.missed:
                A(f"- ❌ 못 잡음 (FN): {', '.join(f'`{x}`' for x in sorted(r.missed))}")
            if r.false_alarm:
                A(f"- ❌ 오탐 (FP): {', '.join(f'`{x}`' for x in sorted(r.false_alarm))}")
            if r.produced:
                A(f"- 실제 출력: {', '.join(f'`{x}`' for x in sorted(r.produced))}")
            A("")

    # --- 채점하지 않은 것 ---------------------------------------------------
    unscored: dict[str, int] = {}
    for r in report.results:
        for code in r.unscored:
            unscored[code] = unscored.get(code, 0) + 1
    A("## 채점하지 않은 코드")
    A("")
    if not unscored:
        A("없음 — 출력된 코드가 전부 라벨 범위 안에 있습니다.")
    else:
        A("골든셋에 라벨이 없어서 맞았는지 틀렸는지 **판단하지 않은** 것들입니다. "
          "자주 뜨는 것부터 라벨을 붙이면 채점 범위가 넓어집니다.")
        A("")
        A("| 코드 | 등장 케이스 수 |")
        A("|---|---:|")
        for code, n in sorted(unscored.items(), key=lambda kv: -kv[1]):
            A(f"| `{code}` | {n} |")
    A("")

    A("---")
    A("")
    A("생성: `python -m adpolicy.evalkit` · 골든셋을 늘릴수록 숫자가 의미를 갖습니다.")
    return "\n".join(L)


def render_console(report: EvalReport) -> str:
    mp, mr, mf = report.micro()
    tp, fp, fn = report.totals()
    crit = critical_false_alarms(report)
    lines = [
        f"케이스 {report.passed}/{report.total} 통과  ({report.elapsed_sec:.2f}s)",
        f"micro  P {_pct(mp)}  R {_pct(mr)}  F1 {_pct(mf)}   "
        f"[TP {tp} FP {fp} FN {fn}]",
    ]
    if crit:
        lines.append(f"⚠️  계정 정지급 오탐 {len(crit)}건: " +
                     ", ".join(f"{c}/{k}" for c, k in crit))
    for r in report.results:
        if r.error:
            lines.append(f"  💥 {r.case_id}: {r.error}")
        elif not r.ok:
            bits = []
            if r.missed:
                bits.append("FN " + ",".join(sorted(r.missed)))
            if r.false_alarm:
                bits.append("FP " + ",".join(sorted(r.false_alarm)))
            lines.append(f"  ✗ {r.case_id}: " + " | ".join(bits))
    return "\n".join(lines)
