"""광고 파라미터로 페이지를 갈아끼우는 경우.

심사 크롤러는 광고를 클릭해서 오지 않는다. 그래서 최종 URL에 gclid가 붙지
않고, "gclid가 있으면 진짜 페이지"로 짜두면 UA를 아무리 바꿔봐도 전부 얌전한
쪽만 보인다. User-Agent 축과는 완전히 다른 사각지대다.

**여기서 제일 조심할 것은 오탐이다.** 배너가 돌아가는 쇼핑몰은 같은 주소를
두 번 불러도 본문이 달라진다. 그 차이를 gclid 탓으로 돌리면 멀쩡한 페이지가
계정 정지 위험으로 뜬다. 그래서 대조군을 먼저 재고, 그보다 뚜렷하게 클 때만
지적한다 — 아래 테스트 절반이 그걸 지킨다.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from adpolicy import cloaking
from adpolicy.models import PageSnapshot

# ---------------------------------------------------------------------------
# 찔러볼 주소를 어떻게 만드는가
# ---------------------------------------------------------------------------


def q(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def test_the_parameter_is_added():
    url = cloaking.build_param_url("https://ex.com/lp", {"gclid": "abc"})
    assert q(url)["gclid"] == ["abc"]


def test_the_pages_own_parameters_survive():
    """?lp=12 하나로 완전히 다른 페이지가 된다. 떼면 엉뚱한 페이지를 비교한다."""
    url = cloaking.build_param_url("https://ex.com/lp?lp=12&ref=blog", {"gclid": "abc"})
    assert q(url)["lp"] == ["12"] and q(url)["ref"] == ["blog"]


def test_an_existing_click_id_is_stripped_first():
    """사용자가 gclid 달린 주소를 그대로 붙여넣는 경우가 흔하다.

    그대로 두면 '파라미터 없는 쪽'이 존재하지 않아 비교가 성립하지 않는다.
    """
    url = cloaking.build_param_url("https://ex.com/lp?gclid=real&utm_source=naver", {})
    assert "gclid" not in q(url)
    assert "utm_source" not in q(url)


def test_the_probe_token_is_not_a_real_click_id():
    """남의 광고 통계를 더럽히면 안 된다. 형식만 그럴듯하면 분기는 똑같이 반응한다."""
    for params in cloaking.PARAM_PROFILES.values():
        for value in params.values():
            assert "adpolicy" in value.lower() or value in ("google", "cpc")


def test_the_control_group_changes_nothing():
    assert cloaking.PARAM_PROFILES["control"] == {}


def test_the_fragment_does_not_leak_into_the_query():
    url = cloaking.build_param_url("https://ex.com/lp#section", {"gclid": "abc"})
    assert urlsplit(url).fragment == "section"
    assert q(url)["gclid"] == ["abc"]


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------

CLEAN = "정상적인 쇼핑몰 본문입니다. " * 40
DIRTY = "지금 입금하면 원금 보장 수익률 300% 확정 지급합니다. " * 40


def snap(text: str, *, final_url: str = "https://ex.com/lp", error: str = "") -> PageSnapshot:
    return PageSnapshot(url="https://ex.com/lp", final_url=final_url,
                        status_code=200, text=text, fetch_error=error)


def probes(**kw: PageSnapshot) -> dict[str, PageSnapshot]:
    base = {"control": snap(CLEAN), "google_click": snap(CLEAN),
            "tiktok_click": snap(CLEAN), "utm_paid": snap(CLEAN)}
    base.update(kw)
    return base


def test_a_page_that_does_not_branch_is_not_flagged():
    sev, _evidence, note = cloaking.analyze_param_divergence(snap(CLEAN), probes())
    assert sev == "" and note == ""


def test_swapping_the_page_for_ad_clicks_is_caught():
    sev, evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(google_click=snap(DIRTY)))
    assert sev == "block"
    assert "gclid" in evidence


def test_the_tiktok_click_id_is_probed_too():
    sev, evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(tiktok_click=snap(DIRTY)))
    assert sev == "block" and "ttclid" in evidence


def test_utm_based_branching_is_caught():
    sev, evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(utm_paid=snap(DIRTY)))
    assert sev == "block" and "utm_source" in evidence


def test_sending_ad_clicks_to_another_domain_is_caught():
    """본문이 같아도 도착지가 다르면 그것으로 끝이다."""
    sev, evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN),
        probes(google_click=snap(CLEAN, final_url="https://other-site.co.kr/real")))
    assert sev == "block"
    assert "other-site.co.kr" in evidence


def test_a_path_change_on_the_same_domain_is_not_a_domain_hop():
    """/lp → /lp/v2는 같은 사이트다. 도메인 이동으로 부르면 거짓이 된다."""
    sev, _evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(google_click=snap(CLEAN, final_url="https://ex.com/lp/v2")))
    assert sev == ""


# --- 오탐 방어 -------------------------------------------------------------


def test_a_page_that_shuffles_its_own_content_is_not_blamed_on_the_parameter():
    """배너가 돌아가는 페이지. 대조군끼리도 다르면 판정하지 않는다.

    이걸 지적으로 올리면 멀쩡한 쇼핑몰이 계정 정지 위험으로 뜬다.
    """
    sev, _evidence, note = cloaking.analyze_param_divergence(
        snap(CLEAN),
        probes(control=snap(DIRTY), google_click=snap(DIRTY)))
    assert sev == ""
    assert "가려낼 수 없" in note   # 문제없음이 아니라 '판정 못 함'이라고 말해야 한다


def test_noise_smaller_than_the_control_gap_is_ignored():
    """타임스탬프 한 줄이 바뀌는 정도는 분기가 아니다."""
    a = CLEAN + "\n오늘 방문자 1023명"
    b = CLEAN + "\n오늘 방문자 1024명"
    sev, _evidence, _ = cloaking.analyze_param_divergence(
        snap(a), probes(control=snap(b), google_click=snap(b)))
    assert sev == ""


def test_a_short_page_is_not_judged():
    """본문이 몇 글자뿐이면 유사도 숫자에 의미가 없다."""
    sev, _evidence, note = cloaking.analyze_param_divergence(
        snap("짧다"), probes(control=snap("짧다"), google_click=snap(DIRTY)))
    assert sev == "" and "짧아" in note


def test_a_failed_probe_does_not_become_a_verdict():
    sev, _evidence, note = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(control=snap("", error="응답 시간 초과")))
    assert sev == "" and "대조군" in note


def test_one_failed_variant_does_not_stop_the_others():
    sev, evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN),
        probes(tiktok_click=snap("", error="요청 실패: ConnectError"),
               google_click=snap(DIRTY)))
    assert sev == "block" and "gclid" in evidence


def test_an_unreachable_baseline_is_not_judged():
    sev, _evidence, _ = cloaking.analyze_param_divergence(
        snap("", error="HTTP 500"), probes())
    assert sev == ""


def test_a_partial_difference_is_a_warning_not_a_block():
    """절반쯤 다른 건 A/B 테스트일 수 있다. 정지 위험으로 단정하지 않는다."""
    half = CLEAN[:len(CLEAN) // 2] + DIRTY[:len(DIRTY) // 4]
    sev, _evidence, _ = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(google_click=snap(half)))
    assert sev in ("warn", "block")
    if sev == "warn":
        assert cloaking.similarity(CLEAN, half) >= cloaking.SIMILARITY_BLOCK


# ---------------------------------------------------------------------------
# 실제로 가져오는 부분
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_profile_is_fetched_with_the_same_user_agent(monkeypatch):
    """축이 하나여야 한다. UA까지 같이 바뀌면 무엇 때문인지 말할 수 없다."""
    seen: list[tuple[str, str]] = []

    async def fake(url: str, ua: str):
        seen.append((url, ua))
        return snap(CLEAN), "<html></html>"

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    out = await cloaking.probe_params("https://ex.com/lp")

    assert set(out) == set(cloaking.PARAM_PROFILES)
    assert len({ua for _url, ua in seen}) == 1
    assert any("gclid" in url for url, _ in seen)
    assert any("ttclid" in url for url, _ in seen)


# ---------------------------------------------------------------------------
# 분기가 전혀 없는 페이지가 계정 정지급으로 보고되던 문제
#
# 점검 한 번에 프로필 3개 + 파라미터 4개를 몰아서 보낸다. 속도 제한이 걸리는
# 서버는 그중 하나에 "잠시 후 다시 시도" 안내를 **200으로** 준다. 그걸 본문
# 비교에 넣으면 유사도 0.02가 나오고, 멀쩡한 페이지가 정지급이 된다.
# ---------------------------------------------------------------------------

THROTTLED = "요청이 많습니다. 잠시 후 다시 시도해 주세요."


def test_a_short_block_page_is_not_treated_as_different_content():
    sev, _evidence, note = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(google_click=snap(THROTTLED)))
    assert sev == ""
    assert "차단·과부하" in note      # 조용히 넘기지 않고 이유를 말한다


def test_the_other_variants_are_still_judged():
    """하나가 안내 페이지라고 나머지 판정까지 포기하면 안 된다."""
    sev, evidence, _note = cloaking.analyze_param_divergence(
        snap(CLEAN), probes(google_click=snap(THROTTLED), tiktok_click=snap(DIRTY)))
    assert sev == "block" and "ttclid" in evidence


def test_the_offending_variant_is_named_for_reconfirmation():
    _sev, _ev, _note, variant = cloaking.param_divergence(
        snap(CLEAN), probes(google_click=snap(DIRTY)))
    assert variant == "google_click"


# --- 재확인 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_difference_that_does_not_repeat_is_not_reported(monkeypatch):
    """일시적 응답 차이로 계정 정지급을 확정하지 않는다."""
    async def fake(url: str, ua: str):
        return snap(CLEAN), ""          # 다시 부르니 둘 다 정상

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    monkeypatch.setattr(cloaking, "RECONFIRM_DELAY", 0)
    confirmed, why = await cloaking.reconfirm_param_divergence("https://ex.com/lp",
                                                               "google_click")
    assert not confirmed
    assert "다시 확인되지 않아" in why


@pytest.mark.asyncio
async def test_a_real_difference_survives_the_recheck(monkeypatch):
    async def fake(url: str, ua: str):
        return snap(DIRTY if "gclid" in url else CLEAN), ""

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    monkeypatch.setattr(cloaking, "RECONFIRM_DELAY", 0)
    confirmed, why = await cloaking.reconfirm_param_divergence("https://ex.com/lp",
                                                               "google_click")
    assert confirmed and "다시 불러도 같았습니다" in why


@pytest.mark.asyncio
async def test_a_short_response_on_the_recheck_holds_the_verdict(monkeypatch):
    async def fake(url: str, ua: str):
        return snap(THROTTLED if "gclid" in url else CLEAN), ""

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    monkeypatch.setattr(cloaking, "RECONFIRM_DELAY", 0)
    confirmed, why = await cloaking.reconfirm_param_divergence("https://ex.com/lp",
                                                               "google_click")
    assert not confirmed and "요청을 제한" in why


@pytest.mark.asyncio
async def test_the_recheck_does_not_burst(monkeypatch):
    """몰아 보내는 것이 원인일 수 있으므로 순서대로 하나씩 부른다."""
    import asyncio
    running, peak = 0, 0

    async def fake(url: str, ua: str):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return snap(CLEAN), ""

    monkeypatch.setattr(cloaking, "_fetch_as", fake)
    monkeypatch.setattr(cloaking, "RECONFIRM_DELAY", 0)
    await cloaking.reconfirm_param_divergence("https://ex.com/lp", "google_click")
    assert peak == 1
