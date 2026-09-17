"""MCP 서버 — 광고 문구를 만드는 에이전트 앞에 세우는 게이트.

    python -m adpolicy.mcp_server            # stdio (Claude Desktop / Cursor)
    python -m adpolicy.mcp_server --http     # streamable HTTP

왜 MCP인가
    이 도구의 쓸모는 "사람이 대시보드를 열어 본다"가 아니라 **"광고 문구를
    생성하는 에이전트가 내보내기 전에 스스로 검증한다"** 쪽에 있다.
    그러려면 에이전트가 호출할 수 있는 표면이 필요하다.

    흐름은 이렇게 된다.

        마케팅 에이전트가 문구·랜딩 URL 생성
              ↓  precheck_ad
        위반 항목 + 증거 + 수정 방향
              ↓  에이전트가 문구를 고쳐 다시 호출
        통과하면 그때 광고 시스템에 올린다

설계 원칙 — **읽기 전용**
    이 서버는 광고를 만들지도, 고치지도, 올리지도 않는다. 판정만 돌려준다.
    `sql-guard-mcp`, `judge-mcp`와 같은 태도다 — 가드레일은 스스로 행위하지
    않아야 신뢰할 수 있다. Google Ads 계정에 접근하는 경로도 없다.

설계 판단 — HTTP를 거치지 않는다
    FastAPI 앱을 띄우고 그 위에 MCP를 얹으면 포트·수명주기가 둘로 늘어난다.
    엔진(`main._run_check`)이 이미 순수 async 함수라 직접 부르면 된다.
"""

from __future__ import annotations

import argparse
import logging
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .models import CheckRequest, Platform
from .policies import POLICY_BY_CODE, policies_for

log = logging.getLogger(__name__)

mcp = FastMCP(
    "adpolicy-precheck",
    instructions=(
        "광고 게재 **전에** 랜딩페이지와 광고 문구의 정책 위반을 점검합니다. "
        "Google Ads / TikTok Ads 정책 카탈로그를 기준으로 결정적 룰셋과 "
        "LLM 판정을 함께 돌리고, 모든 지적에 **본문에서 실제로 확인된 증거**를 "
        "붙입니다. 증거가 역검증되지 않은 LLM 판정은 버려집니다.\n\n"
        "읽기 전용입니다 — 광고를 만들거나 수정하거나 게재하지 않습니다.\n\n"
        "광고 문구를 생성했다면 게재 전에 precheck_ad를 부르세요. "
        "verdict가 'fail'이면 올리지 말고, findings의 fix를 반영해 다시 점검하세요."
    ),
)


def _finding_out(f) -> dict:
    return {
        "code": f.code,
        "title": f.title,
        "severity": f.severity.value,
        "enforcement": f.enforcement.value,
        "source": f.source.value,
        "detail": f.detail,
        "evidence": f.evidence,
        "fix": f.fix,
    }


@mcp.tool()
async def precheck_ad(
    url: Annotated[str, Field(description="광고가 도착할 랜딩페이지 URL")],
    ad_copy: Annotated[str, Field(description="광고 문구 전문 (선택)")] = "",
    headlines: Annotated[
        list[str] | None,
        Field(description="광고 제목들. 글자 수 한도를 따로 검사합니다 "
                          "(한국어는 15자, 영어는 30자)")] = None,
    descriptions: Annotated[
        list[str] | None, Field(description="광고 설명들 (한국어 45자 / 영어 90자)")
    ] = None,
    platform: Annotated[
        str, Field(description="google_ads 또는 tiktok_ads")] = "google_ads",
    use_llm: Annotated[
        bool, Field(description="LLM 판정을 함께 쓸지. 끄면 결정적 룰셋만 돌아 "
                                "빠르고 재현 가능합니다.")] = True,
    check_images: Annotated[
        bool, Field(description="페이지 이미지의 글자를 OCR로 읽어 함께 점검할지. "
                                "느립니다.")] = False,
) -> dict:
    """광고 문구와 랜딩페이지를 게재 전에 점검한다.

    돌려주는 것:
      verdict       pass / review / fail — fail이면 올리면 안 된다
      score         반려 위험 점수 (100이 가장 안전)
      account_risk  **계정 정지** 위험. 반려와 다른 축이다 —
                    반려 20건보다 정지 1건이 치명적이다
      findings      위반 항목. 각 항목에 evidence(본문에서 확인된 근거)와
                    fix(고치는 방법)가 붙는다
    """
    from .main import _run_check  # 순환 import 회피 — 앱 로딩을 늦춘다

    try:
        plat = Platform(platform)
    except ValueError:
        return {
            "error": f"알 수 없는 platform: {platform}",
            "allowed": [p.value for p in Platform],
        }

    req = CheckRequest(
        platform=plat,
        url=url,
        ad_copy=ad_copy,
        headlines=headlines or [],
        descriptions=descriptions or [],
        use_llm=use_llm,
        check_images=check_images,
    )

    try:
        res = await _run_check(req)
    except Exception as exc:  # noqa: BLE001 — 에이전트에게 실패를 숨기지 않는다
        log.exception("점검 실패")
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "note": "점검을 끝내지 못했습니다. 통과로 해석하지 마세요.",
        }

    return {
        "verdict": res.verdict,
        "score": res.score,
        "summary": res.summary,
        "url": res.url,
        "final_url": res.final_url,
        "account_risk": {
            "level": res.account_risk.level.value,
            "suspend_count": res.account_risk.suspend_count,
            "strike_count": res.account_risk.strike_count,
            "codes": res.account_risk.codes,
            "note": res.account_risk.note,
        },
        "findings": [_finding_out(f) for f in res.findings],
        "llm_used": res.llm_used,
        "note": (
            "verdict가 'fail'이면 게재하지 마세요. account_risk.level이 "
            "'suspend'이면 한 건만으로도 계정이 영구 정지될 수 있습니다 — "
            "문구 수정으로 해결되지 않는 구조적 문제일 가능성이 높으니 "
            "사람에게 확인받으세요."
        ),
    }


@mcp.tool()
def list_policies(
    platform: Annotated[
        str, Field(description="google_ads 또는 tiktok_ads")] = "google_ads",
) -> dict:
    """이 도구가 검사하는 정책 항목 목록.

    광고 문구를 만들기 **전에** 무엇을 피해야 하는지 알고 싶을 때 쓴다.
    """
    try:
        plat = Platform(platform)
    except ValueError:
        return {"error": f"알 수 없는 platform: {platform}"}

    items = policies_for(plat)
    return {
        "platform": plat.value,
        "count": len(items),
        "policies": [
            {
                "code": p.code,
                "title": p.title,
                "category": p.category,
                "official_name": p.official_name,
                "severity": p.severity.value,
                "enforcement": p.enforcement.value,
                "source": p.source,
            }
            for p in items
        ],
        "note": "enforcement가 'suspend'인 항목은 한 건으로도 계정이 "
                "영구 정지될 수 있습니다.",
    }


@mcp.tool()
def explain_policy(
    code: Annotated[str, Field(description="정책 코드 (예: MIS-CLICKBAIT)")],
) -> dict:
    """정책 항목 하나의 전문과 공식 문서 링크."""
    item = POLICY_BY_CODE.get(code.strip().upper())
    if item is None:
        return {
            "error": f"모르는 코드: {code}",
            "hint": "list_policies로 사용 가능한 코드를 확인하세요.",
        }
    return {
        "code": item.code,
        "title": item.title,
        "category": item.category,
        "official_name": item.official_name,
        "severity": item.severity.value,
        "enforcement": item.enforcement.value,
        "description": item.description,
        "fix": item.fix,
        "source": item.source,
        "platforms": [p.value for p in item.platforms],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m adpolicy.mcp_server",
        description="광고 정책 사전 점검 MCP 서버 (읽기 전용).",
    )
    ap.add_argument("--http", action="store_true",
                    help="stdio 대신 streamable HTTP로 띄운다")
    args = ap.parse_args(argv)
    mcp.run(transport="streamable-http" if args.http else "stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
