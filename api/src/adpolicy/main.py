"""FastAPI 진입점."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import (
    access,
    adcopy,
    analyzer,
    batch,
    cloaking,
    history,
    locate,
    ocr_paddle,
    rules,
    scoring,
    vision,
)
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMClient
from .models import (
    CheckHistory,
    CheckRequest,
    CheckResponse,
    Finding,
    Platform,
    Source,
)
from .policies import POLICY_BY_CODE, policies_for

# OCR은 CPU를 물고 늘어지는 동기 작업이다. 이벤트 루프에서 직접 돌리면
# 그동안 서버가 다른 요청을 하나도 못 받는다. 스레드로 넘기고, 동시에
# 도는 개수를 제한해 한 요청이 CPU를 독점하지 못하게 한다.
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "2"))
_ocr_gate = asyncio.Semaphore(OCR_CONCURRENCY)

# 한 번의 점검이 무한정 길어지지 않게 전체 상한을 둔다.
CHECK_DEADLINE = float(os.getenv("CHECK_DEADLINE", "180"))

log = logging.getLogger("adpolicy")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """OCR 엔진을 미리 깨워 둔다.

    PaddleOCR은 첫 호출에서 모델을 메모리에 올리느라 몇 초가 걸린다.
    그 비용을 첫 사용자에게 떠넘기지 않는다. 백그라운드로 돌리므로
    실패하든 느리든 서버는 바로 뜬다 — 실패하면 tesseract로 내려간다.
    """

    async def warm():
        engine = await asyncio.to_thread(vision.active_engine)
        if engine:
            log.info("OCR 엔진: %s (요청값 %s)", engine, vision.OCR_ENGINE)
        else:
            log.warning("쓸 수 있는 OCR 엔진이 없습니다: %s", ocr_paddle.error())

    task = asyncio.create_task(warm())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="adpolicy-precheck",
    description="광고 게재 전 랜딩페이지·문구 정책 위반 사전 점검",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # 공백을 안 떼면 " http://localhost:3000" 이 오리진 불일치로 조용히 막힌다.
    allow_origins=[o.strip() for o in
                   os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
                   if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict:
    """설정이 아니라 **실제로 준비된 것**을 돌려준다.

    OCR_ENGINE=paddle로 켜 놓고 모델이 없어 tesseract로 내려가 있는데
    그걸 모르는 상황이 제일 나쁘다. 여기서 바로 확인할 수 있어야 한다.
    """
    engine = vision.active_engine()
    return {
        "ok": True,
        "llm_base_url": DEFAULT_BASE_URL,
        "llm_model": DEFAULT_MODEL,
        "ocr_engine_requested": vision.OCR_ENGINE,
        "ocr_engine_active": engine,
        "ocr_note": "" if engine else (ocr_paddle.error() or "OCR을 쓸 수 없습니다"),
    }


@app.get("/v1/usage", dependencies=[Depends(access.require_api_key)])
async def usage(hours: float = 0.0) -> dict:
    """Claude 다리가 기록한 토큰 사용량을 그대로 넘겨준다.

    프런트가 다리를 직접 부르지 않고 여기를 거치게 한 이유는 두 가지다.
    브라우저에서 오리진이 하나로 유지되고(CORS 설정이 이미 여기 있다),
    다리에 토큰을 걸어 둔 경우 그 토큰이 브라우저까지 내려가지 않는다.
    """
    base = DEFAULT_BASE_URL.rstrip("/")
    if not base:
        return {"available": False, "note": "LLM_BASE_URL이 비어 있습니다."}

    headers = {}
    key = os.getenv("LLM_API_KEY", "")
    if key and key != "not-needed":
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/usage", params={"hours": hours},
                                    headers=headers)
        if resp.status_code != 200:
            return {
                "available": False,
                "note": f"사용량을 가져오지 못했습니다 (HTTP {resp.status_code}). "
                        "현재 LLM 백엔드가 Claude 다리가 아닐 수 있습니다.",
            }
        return {"available": True, **resp.json()}
    except httpx.HTTPError as exc:
        return {
            "available": False,
            "note": f"다리에 연결할 수 없습니다 ({type(exc).__name__}). "
                    f"{base} 가 bridge/claude_bridge.py 인지 확인하세요.",
        }


@app.get("/v1/history", dependencies=[Depends(access.require_api_key)])
async def check_history(url: str = "", limit: int = 20) -> dict:
    """그 주소의 점검 이력. url을 비우면 전체 최근 순.

    DB가 아니라 파일 한 줄씩이라, 사람이 직접 열어볼 수도 있다.
    """
    limit = max(1, min(limit, 200))
    rows = history.for_url(url, limit) if url else history.recent(limit)
    return {"url": url, "count": len(rows), "items": rows,
            "log_path": history.HISTORY_LOG}


@app.get("/v1/policies", dependencies=[Depends(access.require_api_key)])
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
                "enforcement": p.enforcement,
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
        enforcement=p.enforcement,
        source=Source.RULE,
        detail=p.description + (f" {detail_suffix}" if detail_suffix else ""),
        evidence=evidence,
        fix=p.fix,
    )


# 숨긴 텍스트 탐지는 '숨겼다'가 아니라 '정책 위반 문구를 숨겼다'를 본다.
# 그냥 display:none을 세면 탭·모달이 있는 멀쩡한 페이지가 전부 걸린다.
_CONTENT_PATTERNS = [pat for _code, pat in rules.CONTENT_PATTERNS]


def check_mobile_only(snaps: dict, desktop_findings: list[Finding],
                      ad_copy: str, platform: Platform) -> list[Finding]:
    """모바일 화면에만 있는 위반.

    모바일 스냅샷은 클로킹 비교용으로 **이미 받아 뒀는데** 룰셋은 데스크톱만
    보고 있었다. m.도메인이나 모바일 전용 랜딩에서 가격·방침이 빠지는 일이
    실제로 흔한데 그게 전부 통과했다. 추가 네트워크 비용은 0이다.

    데스크톱에서 이미 나온 코드는 올리지 않는다. 같은 지적이 두 번 보이면
    심각도만 부풀려지고, 어느 화면의 문제인지도 흐려진다.
    """
    mobile = snaps.get("mobile")
    if mobile is None or mobile.fetch_error:
        return []

    seen = {f.code for f in desktop_findings}
    out: list[Finding] = []
    for f in rules.run_all(mobile, ad_copy, platform):
        if f.code in seen:
            continue
        seen.add(f.code)
        # 어느 화면에서 나왔는지 밝히지 않으면 사용자가 데스크톱을 열어보고
        # "없는데?" 하게 된다.
        out.append(f.model_copy(update={
            "detail": f"{f.detail} **모바일 화면에서만 확인된 항목입니다.**",
            "evidence": f"[모바일] {f.evidence}" if f.evidence else "[모바일]",
        }))
    return out


async def run_param_probe(
    url: str, baseline
) -> tuple[list[Finding], dict[str, int], str, float]:
    """광고 파라미터를 붙였을 때 페이지가 갈라지는지 본다.

    요청이 늘어나는 축이라 실패해도 점검 전체를 세우지 않는다.

    Returns: (findings, stats, note, 자기 유사도) — 마지막 값은 같은 프로필로
      두 번 불렀을 때의 유사도다. 클로킹 판정의 잡음 기준선으로 쓴다.
    """
    try:
        probes = await cloaking.probe_params(url)
    except Exception as exc:  # noqa: BLE001
        return [], {}, f"파라미터 점검 중 오류: {type(exc).__name__}", 1.0

    severity, evidence, note, variant = cloaking.param_divergence(baseline, probes)
    stats = {
        "param_probes": len(probes),
        "param_probes_ok": sum(1 for s in probes.values() if not s.fetch_error),
    }

    noise = 1.0
    control = probes.get("control")
    if (baseline is not None and not baseline.fetch_error
            and control is not None and not control.fetch_error
            and len(baseline.text) >= cloaking.MIN_TEXT_FOR_COMPARISON):
        noise = cloaking.similarity(baseline.text, control.text)
        stats["self_similarity_pct"] = round(noise * 100)

    if not severity:
        return [], stats, note, noise

    # **계정 정지급 판정을 한 번의 관찰로 확정하지 않는다.**
    # 여기까지 오는 동안 프로필 3개 + 파라미터 4개를 몰아서 보냈다. 속도
    # 제한이 걸리는 서버에서는 그중 하나만 안내 페이지를 받는 일이 실제로
    # 일어나고, 그러면 분기가 전혀 없는 페이지가 정지급으로 보고된다.
    # 이번에는 몰아 보내지 않고 사이를 두고 둘만 다시 부른다.
    try:
        confirmed, why = await cloaking.reconfirm_param_divergence(url, variant)
    except Exception as exc:  # noqa: BLE001
        confirmed, why = False, f"재확인 중 오류: {type(exc).__name__}"
    stats["param_reconfirmed"] = int(confirmed)
    if not confirmed:
        return [], stats, (note + " " + why).strip(), noise

    f = _finding("ABUSE-PARAM-CLOAKING", f"{evidence} · {why}")
    if severity == "warn":
        f = f.model_copy(update={"severity": "warn"})
    return [f], stats, note, noise


async def run_cloaking_checks(url: str, raws: dict[str, str],
                              snaps: dict, noise: float = 1.0) -> list[Finding]:
    """클로킹 관련 결정적 판정 — 탐지이지 수행이 아니다."""
    findings: list[Finding] = []

    severity, ratio, evidence = cloaking.analyze_divergence(snaps, noise)
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
    desktop_snap = snaps.get("desktop")
    if desktop_html:
        if sniff := cloaking.detect_ua_sniffing(desktop_html):
            findings.append(_finding("ABUSE-UA-BRANCHING", sniff))
        if dl := cloaking.detect_auto_download(desktop_html):
            findings.append(_finding("DEST-AUTO-DOWNLOAD", dl))

        base = desktop_snap.final_url if desktop_snap else url
        # 사용자 동작 없이 넘어가는가
        redirect = (cloaking.detect_meta_refresh(desktop_html, base)
                    or cloaking.detect_js_redirect(desktop_html))
        if redirect:
            findings.append(_finding("ABUSE-AUTO-REDIRECT", redirect))
        # 탐지를 피하려고 숨긴 것이 있는가
        hidden = (cloaking.detect_hidden_text(desktop_html, _CONTENT_PATTERNS)
                  or cloaking.detect_zero_width(desktop_html))
        if hidden:
            findings.append(_finding("ABUSE-HIDDEN-TEXT", hidden))
        if overlay := cloaking.detect_blocking_overlay(desktop_html):
            findings.append(_finding("ABUSE-CRAWLER-BLOCKING-OVERLAY", overlay))
        if framed := cloaking.detect_framed_content(desktop_html, base):
            findings.append(_finding("ABUSE-FRAMED-CONTENT", framed))

        # 파라미터 분기가 **브라우저 안에서** 일어나는 경우. 서버 응답은
        # 어느 파라미터로 불러도 같아서 probe_params가 못 잡는 사각지대다.
        if branch := cloaking.detect_param_branch_script(
                desktop_html, _CONTENT_PATTERNS):
            findings.append(_finding("ABUSE-PARAM-BRANCH-SCRIPT", branch))

        # 감췄다는 사실 자체가 근거다
        if hidden_js := cloaking.detect_obfuscated_script(desktop_html):
            findings.append(_finding("ABUSE-OBFUSCATED-SCRIPT", hidden_js))

    if desktop_snap is not None:
        # 광고가 가리킨 도메인과 실제로 도착한 도메인이 다른가.
        # 추가 요청 없이 final_url만 보면 된다.
        if hop := cloaking.detect_cross_domain_landing(url, desktop_snap.final_url):
            findings.append(_finding("DEST-MISMATCH", hop))
        if bridge := cloaking.detect_bridge_page(desktop_snap):
            findings.append(_finding("DEST-BRIDGE-PAGE", bridge))
        # 프로필 비교의 사각지대 — JS로 채우면 세 프로필이 전부 같은 빈 껍데기라
        # 유사도 100%가 나온다. 본문이 응답에 있는지를 따로 본다.
        if desktop_html and (dyn := cloaking.detect_server_rendered_body(
                desktop_html, desktop_snap)):
            findings.append(_finding("ABUSE-SERVER-RENDERED-BODY", dyn))

    return findings


async def _prepare_images(snap) -> tuple[list, dict[str, int], str]:
    """이미지를 받아 OCR을 돌리고 snap.ocr_text를 채운다.

    이미지 점검이 실패해도 페이지 점검은 계속되어야 하므로 여기서 전부 막는다.
    """
    try:
        assets = await vision.collect(snap)
    except Exception as exc:  # noqa: BLE001
        return [], {}, f"이미지 수집 중 오류: {type(exc).__name__}"

    if not assets:
        return [], {"images_found": 0}, ""

    note = ""
    if vision.ocr_available():
        try:
            # to_thread로 넘기지 않으면 tesseract가 도는 내내 이벤트 루프가 멈춘다.
            async with _ocr_gate:
                await asyncio.to_thread(vision.run_ocr, assets)
            snap.ocr_text = vision.merged_ocr_text(assets)
        except Exception as exc:  # noqa: BLE001
            note = f"OCR 중 오류: {type(exc).__name__}"
    else:
        note = "tesseract가 없어 이미지 속 문구는 읽지 못했습니다."

    stats = {
        "images_found": len(snap.image_urls),
        "images_fetched": sum(1 for a in assets if a.ok),
        "images_with_text": sum(1 for a in assets if a.ocr_text),
        "ocr_chars": len(snap.ocr_text),
    }
    return assets, stats, note


@app.post(
    "/v1/check",
    response_model=CheckResponse,
    # 키 검사가 먼저다 — 키 없는 요청이 남의 속도 한도를 깎으면 안 된다.
    dependencies=[Depends(access.require_api_key), Depends(access.limit_checks)],
)
async def check(req: CheckRequest) -> CheckResponse:
    """전체 상한을 걸고 실행한다. 안쪽 단계마다 타임아웃이 있어도
    합쳐지면 얼마든지 길어질 수 있어서, 바깥에서 한 번 더 막는다."""
    try:
        return await asyncio.wait_for(_run_check(req), timeout=CHECK_DEADLINE)
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"점검이 {CHECK_DEADLINE:.0f}초를 넘겨 중단했습니다. "
                   "이미지가 많은 페이지라면 check_images=false로 다시 시도하세요.",
        ) from None


@app.post(
    "/v1/batch",
    status_code=202,
    dependencies=[Depends(access.require_api_key)],
)
async def submit_batch(body: batch.BatchRequest, request: Request) -> dict:
    """여러 건을 받아 작업 번호를 바로 돌려준다. 결과는 GET /v1/batch/{job_id}.

    항목마다 속도 한도에서 한 칸씩 가져간다. 자리가 없으면 기다린다 —
    배치로 분당 한도를 우회하지 못하게.
    """
    client = access.client_of(request)
    try:
        job = batch.store.create(len(body.items))
    except batch.StoreFull:
        raise HTTPException(
            status_code=503,
            detail="진행 중인 배치가 너무 많습니다. 끝난 뒤 다시 보내세요.",
            headers={"Retry-After": "60"},
        ) from None
    job.items = [batch.BatchItem(index=i, url=str(r.url)) for i, r in enumerate(body.items)]

    async def runner(req: CheckRequest) -> CheckResponse:
        await access.wait_for_slot(client)
        # 단건과 같은 전체 상한. _run_check는 호출 때 찾는다(테스트에서 갈아끼움).
        return await asyncio.wait_for(_run_check(req), timeout=CHECK_DEADLINE)

    job.task = asyncio.create_task(batch.run(job, body.items, runner))
    return {"job_id": job.id, "total": len(job.items),
            "status_url": f"/v1/batch/{job.id}"}


@app.get(
    "/v1/batch/{job_id}",
    response_model=batch.BatchStatus,
    dependencies=[Depends(access.require_api_key)],
)
async def batch_status(job_id: str) -> batch.BatchStatus:
    job = batch.store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="없는 작업입니다. 만료됐거나(1시간) 서버가 재시작됐을 수 있습니다.",
        )
    return job.snapshot()


async def _run_check(req: CheckRequest) -> CheckResponse:
    # 여러 클라이언트 프로필로 동시에 가져온다 — 클로킹 탐지를 겸한다.
    snaps, raws = await cloaking.probe_profiles(str(req.url))
    snap = snaps.get("desktop") or next(iter(snaps.values()))

    # 이미지: 먼저 OCR로 글자를 읽어 snap에 합친다. 순서가 중요하다 —
    # 역검증(verification_text)이 배너 문구까지 보게 하려면 룰 실행 전에 채워야 한다.
    assets: list = []
    image_stats: dict[str, int] = {}
    image_note = ""
    if req.check_images:
        assets, image_stats, image_note = await _prepare_images(snap)

    rule_findings = rules.run_all(snap, req.ad_copy, req.platform)

    # 문구 자체의 편집 기준. 페이지를 못 열어도 이건 판정할 수 있다 —
    # 광고 텍스트만 보면 되는 일이라 랜딩 상태와 무관하다.
    rule_findings += adcopy.check(req.ad_copy, req.headlines, req.descriptions)

    # 모바일 화면에만 있는 위반. 스냅샷은 이미 받아 뒀으므로 추가 요청이 없다.
    rule_findings += check_mobile_only(snaps, rule_findings, req.ad_copy, req.platform)

    # 언어 일치는 TikTok만의 요건이다. Google에는 같은 조항이 없다.
    if req.platform == Platform.TIKTOK_ADS and not snap.fetch_error:
        ad_text = "\n".join([req.ad_copy, *req.headlines, *req.descriptions])
        rule_findings += adcopy.check_language_match(ad_text, snap.combined_text)

    # 본문에서 이미 잡힌 코드는 이미지에서 또 올리지 않는다. 같은 지적이 두 번
    # 보이면 심각도만 부풀려진다 — 본문 쪽이 근거가 더 확실하므로 그쪽을 남긴다.
    body_codes = {f.code for f in rule_findings}
    rule_findings += [
        f for f in vision.check_image_text(assets, req.platform)
        if f.code not in body_codes
    ]

    unreachable = any(f.code == "DEST-NOT-WORKING" for f in rule_findings)

    # 파라미터 축이 먼저다. 여기서 나오는 대조군(같은 프로필 재요청)이
    # 클로킹 판정의 잡음 기준선이 된다 — 배너가 도는 페이지를 프로필 차이로
    # 오해하지 않으려면 "이 페이지가 스스로 얼마나 변하는지"를 알아야 한다.
    param_stats: dict[str, int] = {}
    param_note = ""
    noise = 1.0
    if req.probe_params and not unreachable:
        param_findings, param_stats, param_note, noise = await run_param_probe(
            str(req.url), snap
        )
        rule_findings += param_findings

    if not unreachable and req.platform == Platform.GOOGLE_ADS:
        rule_findings += await run_cloaking_checks(str(req.url), raws, snaps, noise)

    llm_findings: list[Finding] = []
    stats: dict[str, int] = {}
    llm_note = ""
    llm_used = False

    if req.use_llm and not unreachable:
        try:
            llm_findings, stats, analysis, err = await analyzer.analyze(
                snap, req.ad_copy, req.platform, LLMClient()
            )
        except Exception as exc:  # noqa: BLE001 — 마지막 그물
            # LLM은 보조 수단이다. 여기서 예외가 올라가면 결정적 룰셋 결과까지
            # 500으로 함께 죽는다. 원인은 llm_note로 알리고 점검은 계속한다.
            llm_findings, stats, err = [], {}, (
                f"LLM 분석 중 오류가 발생해 룰셋 결과만 반환합니다: {type(exc).__name__}"
            )
        if err:
            llm_note = err
        else:
            llm_used = True
            llm_note = analysis

    # 이미지 자체 판정 — 글자가 없는 문제를 본다. 기본 꺼짐.
    vlm_findings: list[Finding] = []
    vlm_used = False
    vlm_note = ""
    if not req.use_vlm:
        vlm_note = "이미지 자체 판정을 끈 상태입니다."
    elif not req.check_images:
        vlm_note = "이미지 점검이 꺼져 있어 건너뛰었습니다."
    elif not assets:
        vlm_note = "판정할 이미지가 없습니다."
    elif not unreachable:
        try:
            vlm_findings, vlm_stats, vlm_err = await vision.analyze_images(
                assets, req.platform
            )
            image_stats.update(vlm_stats)
            vlm_note = vlm_err
            vlm_used = not vlm_err
        except Exception as exc:  # noqa: BLE001
            vlm_note = f"이미지 판정 중 오류: {type(exc).__name__}"
    if vlm_used and not vlm_findings:
        vlm_note = "이미지를 살펴봤지만 시각적으로 걸리는 항목은 없었습니다."

    # 지문은 OCR까지 끝난 뒤에 뜬다 — 배너만 갈아끼우는 경우도 잡아야 하기 때문이다.
    fingerprint = cloaking.content_fingerprint(snap)
    previous = None if unreachable else history.last_for(str(req.url))

    # 비교 대상: 호출자가 직접 준 지문 > 장부의 마지막 점검.
    baseline = req.expect_fingerprint
    if not baseline and req.compare_with_last and previous:
        baseline = str(previous.get("fingerprint") or "")
    if baseline and not unreachable and baseline != fingerprint:
        rule_findings.append(_finding(
            "ABUSE-CONTENT-CHANGED", f"직전 {baseline} → 지금 {fingerprint}",
        ))

    detected = scoring.merge(rule_findings, llm_findings + vlm_findings, stats)
    # 근거가 제목·본문·링크·alt 중 어디 있는지. 합친 뒤에 찾아야 이어 붙인
    # 근거 조각마다 위치가 나온다.
    mobile = snaps.get("mobile")
    locate.annotate(
        detected, snap, mobile=mobile if mobile is not snap else None,
        headlines=req.headlines, descriptions=req.descriptions, ad_copy=req.ad_copy,
    )
    # 무시는 합친 뒤에 가른다. 먼저 가르면 같은 코드가 다른 근거로 되살아난다.
    ignored = set(req.ignore_codes)
    findings = [f for f in detected if f.code not in ignored]
    suppressed = [f for f in detected if f.code in ignored]
    v = scoring.verdict(findings)
    risk = scoring.account_risk(findings)

    stats.update(image_stats)
    stats.update(param_stats)
    stats.update({
        "rule_findings": len(rule_findings),
        "llm_findings_kept": len(llm_findings),
        "page_chars": len(snap.text),
        "profiles_probed": len(snaps),
        # 숫자가 맞아떨어져야 한다. 이게 없으면 rule+llm+vlm 합과 최종 건수가
        # 어긋나는데 왜 어긋나는지 알 길이 없다.
        "findings_total": len(findings),
        "suppressed": len(suppressed),
    })
    # 판정을 못 한 것과 문제가 없는 것은 다르다. 못 했으면 그 이유를 남긴다.
    for extra in (image_note, param_note):
        if extra:
            llm_note = (llm_note + "\n" + extra).strip() if llm_note else extra

    # 이력에는 무시한 것까지 적는다. 무시를 켰다고 '해결됨'으로 보이면 안 된다 —
    # 페이지는 그대로다.
    codes = [f.code for f in detected]
    score = scoring.score(findings)

    # 지난 점검과의 차이. 비교 자체는 항상 보여준다 — "바뀌었다"는 사실이지
    # 위반이 아니므로, 지적으로 올릴지는 위에서 compare_with_last가 정한다.
    diff = None
    if previous and not unreachable:
        diff = CheckHistory(**history.compare(previous, codes, score, fingerprint))

    # 기록은 마지막에. 먼저 적으면 자기 자신과 비교하게 된다.
    if not unreachable:
        history.record({
            "url_key": history.url_key(str(req.url)),
            "url": str(req.url),
            "final_url": snap.final_url,
            "platform": req.platform.value,
            "fingerprint": fingerprint,
            "verdict": v,
            "score": score,
            "account_risk": risk.level.value,
            "codes": codes,
        })

    return CheckResponse(
        platform=req.platform,
        url=str(req.url),
        final_url=snap.final_url,
        verdict=v,
        score=score,
        account_risk=risk,
        content_fingerprint=fingerprint,
        history=diff,
        summary=scoring.summarize(findings, v),
        findings=findings,
        suppressed=suppressed,
        stats=stats,
        images=vision.build_reports(assets, findings),
        llm_used=llm_used,
        llm_note=llm_note,
        vlm_used=vlm_used,
        vlm_note=vlm_note,
    )
