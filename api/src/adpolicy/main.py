"""FastAPI 진입점."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import analyzer, cloaking, rules, scoring
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMClient
from .models import CheckRequest, CheckResponse, Finding, Platform, Source
from .policies import POLICY_BY_CODE, policies_for

app = FastAPI(
    title="adpolicy-precheck",
    description="광고 게재 전 랜딩페이지·문구 정책 위반 사전 점검",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "llm_base_url": DEFAULT_BASE_URL, "llm_model": DEFAULT_MODEL}


@app.get("/v1/policies")
async def list_policies(platform: Platform = Platform.GOOGLE_ADS) -> dict:
    return {
        "platform": platform,
        "items": [
            {
                "code": p.code,
                "title": p.title,
                "category": p.category,
                "official_name": p.official_name,
                "severity": p.severity,
                "description": p.description,
                "fix": p.fix,
                "source": p.source,
            }
            for p in policies_for(platform)
        ],
    }


def _finding(code: str, evidence: str, detail_suffix: str = "") -> Finding:
    p = POLICY_BY_CODE[code]
    return Finding(
        code=p.code,
        title=p.title,
        severity=p.severity,
        source=Source.RULE,
        detail=p.description + (f" {detail_suffix}" if detail_suffix else ""),
        evidence=evidence,
        fix=p.fix,
    )


async def run_cloaking_checks(url: str, raws: dict[str, str],
                              snaps: dict) -> list[Finding]:
    """클로킹 관련 결정적 판정 — 탐지이지 수행이 아니다."""
    findings: list[Finding] = []

    severity, ratio, evidence = cloaking.analyze_divergence(snaps)
    if severity:
        f = _finding("ABUSE-CLOAKING", evidence)
        # 유사도가 애매한 구간이면 경고로 낮춘다
        if severity == "warn":
            f = f.model_copy(update={"severity": "warn"})
        findings.append(f)

    blocked, robots_evidence = await cloaking.check_robots(url)
    if blocked:
        findings.append(_finding("DEST-NOT-CRAWLABLE", robots_evidence))

    desktop_html = raws.get("desktop", "")
    if desktop_html:
        if sniff := cloaking.detect_ua_sniffing(desktop_html):
            findings.append(_finding("ABUSE-UA-BRANCHING", sniff))
        if dl := cloaking.detect_auto_download(desktop_html):
            findings.append(_finding("DEST-AUTO-DOWNLOAD", dl))

    return findings


@app.post("/v1/check", response_model=CheckResponse)
async def check(req: CheckRequest) -> CheckResponse:
    # 여러 클라이언트 프로필로 동시에 가져온다 — 클로킹 탐지를 겸한다.
    snaps, raws = await cloaking.probe_profiles(str(req.url))
    snap = snaps.get("desktop") or next(iter(snaps.values()))

    rule_findings = rules.run_all(snap, req.ad_copy, req.platform)

    unreachable = any(f.code == "DEST-NOT-WORKING" for f in rule_findings)
    if not unreachable and req.platform == Platform.GOOGLE_ADS:
        rule_findings += await run_cloaking_checks(str(req.url), raws, snaps)

    llm_findings: list[Finding] = []
    stats: dict[str, int] = {}
    llm_note = ""
    llm_used = False

    if req.use_llm and not unreachable:
        llm_findings, stats, analysis, err = await analyzer.analyze(
            snap, req.ad_copy, req.platform, LLMClient()
        )
        if err:
            llm_note = err
        else:
            llm_used = True
            llm_note = analysis

    findings = scoring.merge(rule_findings, llm_findings)
    v = scoring.verdict(findings)

    stats.update({
        "rule_findings": len(rule_findings),
        "llm_findings_kept": len(llm_findings),
        "page_chars": len(snap.text),
        "profiles_probed": len(snaps),
    })

    return CheckResponse(
        platform=req.platform,
        url=str(req.url),
        final_url=snap.final_url,
        verdict=v,
        score=scoring.score(findings),
        summary=scoring.summarize(findings, v),
        findings=findings,
        stats=stats,
        llm_used=llm_used,
        llm_note=llm_note,
    )
