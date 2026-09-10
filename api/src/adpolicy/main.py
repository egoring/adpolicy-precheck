"""FastAPI 진입점."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import analyzer, fetcher, rules, scoring
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMClient
from .models import CheckRequest, CheckResponse, Platform
from .policies import policies_for

app = FastAPI(
    title="adpolicy-precheck",
    description="광고 게재 전 랜딩페이지·문구 정책 위반 사전 점검",
    version="0.1.0",
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
                "severity": p.severity,
                "description": p.description,
                "fix": p.fix,
            }
            for p in policies_for(platform)
        ],
    }


@app.post("/v1/check", response_model=CheckResponse)
async def check(req: CheckRequest) -> CheckResponse:
    snap = await fetcher.fetch(str(req.url))

    rule_findings = rules.run_all(snap, req.ad_copy, req.platform)

    llm_findings: list = []
    stats: dict[str, int] = {}
    llm_note = ""
    llm_used = False

    unreachable = any(f.code == "LP-UNREACHABLE" for f in rule_findings)
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
