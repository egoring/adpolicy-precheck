"""MCP 서버 — 에이전트 앞에 세우는 게이트.

가드레일 도구는 **스스로 행위하지 않아야** 신뢰할 수 있다. 그래서 가장
중요한 테스트는 "무엇을 노출하지 않는가"다.
"""

from __future__ import annotations

import json

import pytest

from adpolicy.mcp_server import mcp
from adpolicy.models import Platform
from adpolicy.policies import ALL_POLICIES


async def call(name: str, args: dict) -> dict:
    """버전에 따라 (content, structured) 또는 content만 온다. 둘 다 받는다."""
    out = await mcp.call_tool(name, args)
    if isinstance(out, tuple):
        structured = out[1]
        return structured.get("result", structured)
    text = out[0].text  # TextContent
    return json.loads(text)


# --- 노출 표면 --------------------------------------------------------------

async def test_exposes_exactly_three_read_only_tools():
    names = {t.name for t in await mcp.list_tools()}
    assert names == {"precheck_ad", "list_policies", "explain_policy"}


async def test_no_tool_can_create_modify_or_publish_ads():
    """가드레일이 광고를 만들거나 올릴 수 있으면 가드레일이 아니다."""
    forbidden = ("create", "update", "delete", "publish", "submit", "resubmit",
                 "upload", "appeal", "mutate", "account", "campaign", "budget")
    for t in await mcp.list_tools():
        low = t.name.lower()
        assert not any(w in low for w in forbidden), f"쓰기로 읽히는 툴: {t.name}"


async def test_instructions_state_read_only():
    assert "읽기 전용" in (mcp.instructions or "")


async def test_precheck_tool_declares_the_inputs_an_agent_needs():
    tool = next(t for t in await mcp.list_tools() if t.name == "precheck_ad")
    props = set((tool.inputSchema or {}).get("properties", {}))
    assert {"url", "ad_copy", "headlines", "descriptions", "platform"} <= props
    assert "url" in (tool.inputSchema or {}).get("required", ["url"])


# --- 카탈로그 조회 ----------------------------------------------------------

async def test_list_policies_returns_the_whole_catalog_for_google():
    res = await call("list_policies", {"platform": "google_ads"})
    expected = sum(1 for p in ALL_POLICIES if Platform.GOOGLE_ADS in p.platforms)
    assert res["count"] == expected
    assert len(res["policies"]) == expected


async def test_list_policies_is_platform_scoped():
    g = await call("list_policies", {"platform": "google_ads"})
    t = await call("list_policies", {"platform": "tiktok_ads"})
    gcodes = {p["code"] for p in g["policies"]}
    tcodes = {p["code"] for p in t["policies"]}
    assert "TT-LANGUAGE-MISMATCH" in tcodes
    assert "TT-LANGUAGE-MISMATCH" not in gcodes


async def test_policy_entries_carry_enforcement_so_agents_can_rank_risk():
    res = await call("list_policies", {"platform": "google_ads"})
    entry = next(p for p in res["policies"] if p["code"] == "ABUSE-CLOAKING")
    assert entry["enforcement"] == "suspend"
    assert entry["source"].startswith("https://")


async def test_explain_policy_is_case_insensitive():
    res = await call("explain_policy", {"code": "mis-clickbait"})
    assert res["code"] == "MIS-CLICKBAIT"
    assert res["fix"]
    assert res["source"].startswith("https://")


async def test_unknown_code_returns_error_not_a_guess():
    res = await call("explain_policy", {"code": "NOT-A-REAL-CODE"})
    assert "error" in res
    assert "list_policies" in res["hint"]


async def test_unknown_platform_is_rejected_with_allowed_values():
    res = await call("list_policies", {"platform": "naver_ads"})
    assert "error" in res


# --- 점검 툴 ----------------------------------------------------------------

async def test_precheck_reports_failure_instead_of_silently_passing(monkeypatch):
    """점검이 실패했는데 통과처럼 보이면 게이트가 무너진다."""
    import adpolicy.main as M

    async def boom(_req):
        raise RuntimeError("네트워크 끊김")

    monkeypatch.setattr(M, "_run_check", boom)
    res = await call("precheck_ad", {"url": "https://example.com/lp"})
    assert "error" in res
    assert "verdict" not in res
    assert "통과로 해석하지 마세요" in res["note"]


async def test_precheck_surfaces_account_risk_separately(monkeypatch):
    """반려와 정지는 다른 축이다. 한 숫자로 뭉뚱그리면 안 된다."""
    import adpolicy.main as M
    from adpolicy.models import (
        AccountRisk,
        CheckResponse,
        Enforcement,
        Finding,
        Severity,
        Source,
    )

    async def fake(req):
        f = Finding(
            code="ABUSE-CLOAKING", title="클로킹", severity=Severity.BLOCK,
            enforcement=Enforcement.SUSPEND, source=Source.RULE,
            detail="d", evidence="유사도 0.31", fix="분기 제거",
        )
        return CheckResponse(
            platform=req.platform, url=str(req.url), final_url=str(req.url),
            verdict="fail", score=10,
            account_risk=AccountRisk(level=Enforcement.SUSPEND, suspend_count=1,
                                     codes=["ABUSE-CLOAKING"], note="즉시 정지 가능"),
            summary="s", findings=[f],
        )

    monkeypatch.setattr(M, "_run_check", fake)
    res = await call("precheck_ad", {"url": "https://example.com/lp"})

    assert res["verdict"] == "fail"
    assert res["account_risk"]["level"] == "suspend"
    assert res["account_risk"]["suspend_count"] == 1
    assert "영구 정지" in res["note"]


async def test_every_finding_carries_evidence_and_fix(monkeypatch):
    """증거 없는 지적은 에이전트가 고칠 수 없다."""
    import adpolicy.main as M
    from adpolicy.models import CheckResponse, Enforcement, Finding, Severity, Source

    async def fake(req):
        return CheckResponse(
            platform=req.platform, url=str(req.url), final_url=str(req.url),
            verdict="review", score=70, summary="s",
            findings=[Finding(
                code="MIS-SUPERLATIVE", title="최상급", severity=Severity.WARN,
                enforcement=Enforcement.DISAPPROVE, source=Source.RULE,
                detail="d", evidence="업계 1위", fix="근거를 표기하세요",
            )],
        )

    monkeypatch.setattr(M, "_run_check", fake)
    res = await call("precheck_ad", {"url": "https://example.com/lp"})
    for f in res["findings"]:
        assert f["evidence"], f"증거 없는 지적: {f['code']}"
        assert f["fix"], f"수정 방법 없는 지적: {f['code']}"
        assert f["enforcement"] in ("disapprove", "strike", "suspend")


async def test_bad_platform_in_precheck_does_not_reach_the_engine(monkeypatch):
    import adpolicy.main as M

    called = False

    async def spy(_req):
        nonlocal called
        called = True
        raise AssertionError("도달하면 안 된다")

    monkeypatch.setattr(M, "_run_check", spy)
    res = await call("precheck_ad",
                     {"url": "https://example.com/lp", "platform": "naver_ads"})
    assert "error" in res
    assert res["allowed"] == [p.value for p in Platform]
    assert not called


@pytest.mark.parametrize("code", [p.code for p in ALL_POLICIES])
async def test_every_catalog_entry_is_explainable(code):
    """카탈로그에 있는데 설명이 안 나오는 코드가 있으면 안 된다."""
    res = await call("explain_policy", {"code": code})
    assert "error" not in res
    assert res["description"]
