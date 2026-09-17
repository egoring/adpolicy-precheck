"""골든셋 로더.

케이스는 `cases.jsonl` 한 줄에 하나, 페이지 원문은 `pages/<id>.html`에 둔다.
HTML을 JSON 안에 넣지 않는 이유는 단순하다 — 이스케이프된 HTML은 사람이
읽을 수도 고칠 수도 없고, diff도 의미가 없어진다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import GoldenCase

# 이 파일 기준 ../../../../eval/golden  (api/eval/golden)
DEFAULT_GOLDEN_DIR = Path(__file__).resolve().parents[3] / "eval" / "golden"

_ALLOWED_KEYS = {
    "id", "url", "final_url", "status_code", "ad_copy", "headlines",
    "descriptions", "platform", "expect", "forbid", "note", "source", "html_file",
}


class GoldenError(ValueError):
    """골든셋이 잘못 작성되었을 때. 조용히 넘어가지 않는다."""


def load_cases(golden_dir: Path | str | None = None) -> list[GoldenCase]:
    root = Path(golden_dir) if golden_dir else DEFAULT_GOLDEN_DIR
    manifest = root / "cases.jsonl"
    if not manifest.exists():
        raise GoldenError(f"골든셋 목록이 없습니다: {manifest}")

    cases: list[GoldenCase] = []
    seen: set[str] = set()

    for lineno, line in enumerate(manifest.read_text("utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldenError(f"{manifest}:{lineno} JSON 파싱 실패 — {exc}") from exc

        unknown = set(raw) - _ALLOWED_KEYS
        if unknown:
            raise GoldenError(
                f"{manifest}:{lineno} 모르는 키 {sorted(unknown)} — "
                "오타이거나 스키마가 바뀐 것입니다."
            )

        cid = raw.get("id")
        if not cid:
            raise GoldenError(f"{manifest}:{lineno} id가 없습니다.")
        if cid in seen:
            raise GoldenError(f"{manifest}:{lineno} id 중복: {cid}")
        seen.add(cid)

        html_file = raw.pop("html_file", f"{cid}.html")
        page = root / "pages" / html_file
        if not page.exists():
            raise GoldenError(f"{manifest}:{lineno} 페이지 파일이 없습니다: {page}")

        expect = tuple(raw.get("expect", ()))
        forbid = tuple(raw.get("forbid", ()))
        overlap = set(expect) & set(forbid)
        if overlap:
            raise GoldenError(
                f"{manifest}:{lineno} expect와 forbid에 같은 코드가 있습니다: "
                f"{sorted(overlap)}"
            )

        cases.append(GoldenCase(
            id=cid,
            html=page.read_text("utf-8"),
            url=raw.get("url", "https://example.com/lp"),
            final_url=raw.get("final_url", ""),
            status_code=int(raw.get("status_code", 200)),
            ad_copy=raw.get("ad_copy", ""),
            headlines=tuple(raw.get("headlines", ())),
            descriptions=tuple(raw.get("descriptions", ())),
            platform=raw.get("platform", "google_ads"),
            expect=expect,
            forbid=forbid,
            note=raw.get("note", ""),
            source=raw.get("source", ""),
        ))

    if not cases:
        raise GoldenError(f"{manifest} 에 케이스가 하나도 없습니다.")
    return cases


def build_scope(cases: list[GoldenCase]) -> set[str]:
    """채점 범위 = 골든셋에서 expect 또는 forbid로 한 번이라도 언급된 코드.

    언급되지 않은 코드는 라벨이 없다는 뜻이므로 채점하지 않는다.
    "라벨이 없는 것을 틀렸다고 말하지 않는다" — v1의 증거 원칙과 같은 태도다.
    """
    scope: set[str] = set()
    for c in cases:
        scope.update(c.expect)
        scope.update(c.forbid)
    return scope
