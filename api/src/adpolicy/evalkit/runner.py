"""골든 케이스 실행기 — 네트워크도 LLM도 타지 않는다.

무엇을 재는가
    결정적 룰셋(`rules.run_all`)과 문구 편집 기준(`adcopy.check`)만 돌린다.
    LLM·VLM·OCR·클로킹 프로브는 제외한다. 이유는 셋이다.

    1. 재현성 — 같은 입력에 같은 출력이 나와야 지표가 의미를 갖는다.
       LLM은 온도를 0으로 둬도 완전히 결정적이지 않다.
    2. 비용 — 골든셋을 돌릴 때마다 토큰을 쓰면 자주 못 돌린다.
    3. 책임 분리 — LLM 판정의 품질은 별도로 재야 한다.
       여기에 섞으면 "룰이 틀린 건지 모델이 틀린 건지" 구분이 사라진다.

    **여러 번 요청해야** 알 수 있는 판정(프로필 간 유사도 비교, 파라미터
    프로브, robots.txt)은 제외한다. 반면 응답 HTML 하나만 보면 되는 판정
    (숨긴 텍스트, 자동 리디렉션, 난독화 스크립트 등)은 결정적이고 오프라인이라
    여기에 포함한다 — 경계는 "네트워크를 쓰는가"가 아니라 "재현 가능한가"다.
"""

from __future__ import annotations

import time

from .. import adcopy, cloaking, rules
from ..fetcher import _extract
from ..models import Finding, PageSnapshot, Platform
from ..policies import POLICY_BY_CODE
from .models import CaseResult, CodeMetric, EvalReport, GoldenCase

_CONTENT_PATTERNS = [pat for _code, pat in rules.CONTENT_PATTERNS]


def _f(code: str, evidence: str) -> Finding:
    """main.py의 `_finding`과 같은 일을 하되, 여기서는 코드만 쓰이므로
    카탈로그에서 제목·등급만 채운다."""
    item = POLICY_BY_CODE[code]
    return Finding(
        code=code, title=item.title, severity=item.severity,
        enforcement=item.enforcement, source=rules.Source.RULE,
        detail=item.description, evidence=evidence[:300], fix=item.fix,
    )


def html_only_findings(html: str, snap: PageSnapshot, url: str) -> list[Finding]:
    """응답 HTML 하나로 끝나는 결정적 판정들.

    `main.run_cloaking_checks`에서 **추가 요청이 필요 없는 것만** 추렸다.
    빠진 것: ABUSE-CLOAKING(프로필 비교), DEST-NOT-CRAWLABLE(robots.txt),
    ABUSE-PARAM-CLOAKING(파라미터 프로브). 이 셋은 골든셋으로 잴 수 없다.
    """
    out: list[Finding] = []
    if not html:
        return out

    if sniff := cloaking.detect_ua_sniffing(html):
        out.append(_f("ABUSE-UA-BRANCHING", sniff))
    if dl := cloaking.detect_auto_download(html):
        out.append(_f("DEST-AUTO-DOWNLOAD", dl))

    base = snap.final_url or url
    if redirect := (cloaking.detect_meta_refresh(html, base)
                    or cloaking.detect_js_redirect(html)):
        out.append(_f("ABUSE-AUTO-REDIRECT", redirect))
    if hidden := (cloaking.detect_hidden_text(html, _CONTENT_PATTERNS)
                  or cloaking.detect_zero_width(html)):
        out.append(_f("ABUSE-HIDDEN-TEXT", hidden))
    if overlay := cloaking.detect_blocking_overlay(html):
        out.append(_f("ABUSE-CRAWLER-BLOCKING-OVERLAY", overlay))
    if framed := cloaking.detect_framed_content(html, base):
        out.append(_f("ABUSE-FRAMED-CONTENT", framed))
    if branch := cloaking.detect_param_branch_script(html, _CONTENT_PATTERNS):
        out.append(_f("ABUSE-PARAM-BRANCH-SCRIPT", branch))
    if hidden_js := cloaking.detect_obfuscated_script(html):
        out.append(_f("ABUSE-OBFUSCATED-SCRIPT", hidden_js))

    if hop := cloaking.detect_cross_domain_landing(url, snap.final_url):
        out.append(_f("DEST-MISMATCH", hop))
    if bridge := cloaking.detect_bridge_page(snap):
        out.append(_f("DEST-BRIDGE-PAGE", bridge))
    if dyn := cloaking.detect_server_rendered_body(html, snap):
        out.append(_f("ABUSE-SERVER-RENDERED-BODY", dyn))
    return out


def run_case(case: GoldenCase, scope: set[str]) -> CaseResult:
    res = CaseResult(case_id=case.id)
    try:
        snap = _extract(
            case.html, case.url, case.resolved_final_url, case.status_code
        )
        platform = Platform(case.platform)

        findings = rules.run_all(snap, case.ad_copy, platform)
        findings += adcopy.check(
            case.ad_copy, list(case.headlines), list(case.descriptions)
        )
        if platform == Platform.TIKTOK_ADS and not snap.fetch_error:
            ad_text = "\n".join(
                [case.ad_copy, *case.headlines, *case.descriptions]
            )
            findings += adcopy.check_language_match(ad_text, snap.combined_text)

        # 페이지를 못 열었으면 HTML 판정은 의미가 없다 — rules 쪽 규칙과 같은 태도.
        if not snap.fetch_error and snap.status_code < 400:
            body_codes = {f.code for f in findings}
            findings += [
                f for f in html_only_findings(case.html, snap, case.url)
                if f.code not in body_codes
            ]

        produced = {f.code for f in findings}
    except Exception as exc:  # noqa: BLE001 — 어떤 예외든 케이스 하나만 죽인다
        res.error = f"{type(exc).__name__}: {exc}"
        return res

    expect, forbid = set(case.expect), set(case.forbid)
    res.produced = produced
    res.hit = expect & produced
    res.missed = expect - produced
    res.false_alarm = forbid & produced
    res.unscored = produced - scope
    return res


def _update_metrics(
    per_code: dict[str, CodeMetric], case: GoldenCase, res: CaseResult,
    scope: set[str],
) -> None:
    """케이스 하나의 결과를 코드별 혼동행렬에 반영한다.

    채점 규칙 (scope 안의 코드에 대해서만)
        expect에 있고 나왔다     → TP
        expect에 있는데 안 나왔다 → FN
        forbid에 있는데 나왔다    → FP
        forbid에 있고 안 나왔다   → TN
        둘 다 아니다             → 채점하지 않는다 (라벨 없음)
    """
    expect, forbid = set(case.expect), set(case.forbid)
    for code in scope:
        m = per_code.setdefault(code, CodeMetric(code=code))
        appeared = code in res.produced
        if code in expect:
            if appeared:
                m.tp += 1
            else:
                m.fn += 1
        elif code in forbid:
            if appeared:
                m.fp += 1
            else:
                m.tn += 1
        # 라벨이 없는 코드는 건드리지 않는다.


def run_all(cases: list[GoldenCase], scope: set[str]) -> EvalReport:
    started = time.monotonic()
    report = EvalReport(scope=set(scope))
    for case in cases:
        res = run_case(case, scope)
        report.results.append(res)
        if not res.error:
            _update_metrics(report.per_code, case, res, scope)
    report.elapsed_sec = time.monotonic() - started
    return report
