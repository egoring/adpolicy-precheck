"""지적된 문구가 어디에 있는지(C-8).

룰과 역검증은 combined_text 한 덩어리를 본다. 판정에는 그게 맞지만, 고치는
사람은 "100% 보장"이 제목인지 본문인지 링크인지 alt인지 알아야 손댈 곳을
찾는다. 스냅샷은 이미 필드별로 나뉘어 있으니 근거를 필드마다 다시 찾아본다.

비교 기준은 역검증(analyzer._normalize)과 같다 — 띄어쓰기·전각 차이는 같은
문구로 본다. 근거가 어디에도 없으면(예: "본문 120자") 위치를 지어내지 않는다.
"""

from __future__ import annotations

from .analyzer import _normalize
from .models import Finding, PageSnapshot

# scoring.merge가 근거를 이어 붙일 때 쓰는 구분자
_JOIN = " / "
# 이보다 짧은 조각은 어디서나 걸려 위치 정보가 의미 없다
_MIN_LEN = 2

# 본문(text)에는 링크 글자·폼 글자도 섞여 들어간다. 더 구체적인 필드에서
# 찾았으면 본문은 굳이 알리지 않는다.
_SPECIFIC_PAGE = ("title", "meta_description", "link_text", "image_alt", "form")


def _page_fields(snap: PageSnapshot) -> list[tuple[str, str]]:
    return [
        ("title", snap.title),
        ("meta_description", snap.meta_description),
        ("link_text", "\n".join(snap.link_texts)),
        ("image_alt", "\n".join(snap.image_alts)),
        ("form", snap.form_text),
        ("body", snap.text),
        ("image_text", snap.ocr_text),
    ]


def _in_page(piece: str, snap: PageSnapshot) -> list[str]:
    hits = [name for name, text in _page_fields(snap) if text and piece in _normalize(text)]
    if any(h in _SPECIFIC_PAGE for h in hits):
        hits = [h for h in hits if h != "body"]
    return hits


def locate(
    evidence: str,
    snap: PageSnapshot,
    *,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
    ad_copy: str = "",
) -> list[str]:
    """근거가 나타나는 위치들. 페이지 쪽이 먼저, 광고 쪽이 뒤에 온다."""
    ad_fields = [
        ("ad_headline", "\n".join(headlines or [])),
        ("ad_description", "\n".join(descriptions or [])),
        ("ad_copy", ad_copy),
    ]
    found: list[str] = []
    for raw in evidence.split(_JOIN):
        piece = _normalize(raw)
        if len(piece) < _MIN_LEN:
            continue
        hits = _in_page(piece, snap)
        hits += [name for name, text in ad_fields if text and piece in _normalize(text)]
        for h in hits:
            if h not in found:
                found.append(h)
    return found


def annotate(
    findings: list[Finding],
    snap: PageSnapshot,
    *,
    mobile: PageSnapshot | None = None,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
    ad_copy: str = "",
) -> None:
    """지적마다 locations를 채운다 (제자리 수정).

    데스크톱에서 못 찾은 근거는 모바일 스냅샷에서 찾고 'mobile:'을 붙인다 —
    모바일 화면에만 있는 문구는 고칠 곳도 모바일 쪽이다.
    """
    for f in findings:
        if not f.evidence or f.locations:
            continue
        f.locations = locate(f.evidence, snap, headlines=headlines,
                             descriptions=descriptions, ad_copy=ad_copy)
        if not f.locations and mobile is not None:
            f.locations = [f"mobile:{loc}" for loc in locate(f.evidence, mobile)]
