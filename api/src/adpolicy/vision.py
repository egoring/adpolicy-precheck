"""이미지 점검 — 배너 안의 문구와 이미지 자체를 본다.

실무 반려의 상당수가 **본문이 아니라 배너 이미지**에서 나온다. "100% 보장"을
텍스트로 쓰면 잡히니까 이미지에 박아 넣는 식이다. 텍스트만 보는 점검기는
이걸 통째로 놓친다.

두 층으로 나눈다. 근거의 성격이 완전히 다르기 때문이다.

  1. OCR (`Source.OCR`)  — 이미지에서 글자를 읽어 **기존 결정적 룰**을 그대로 돌린다.
     룰은 결정적이고, 읽어낸 글자는 `PageSnapshot.ocr_text`에 남아
     **근거 역검증의 대상이 된다.** 새 룰을 짤 필요가 없다.

  2. VLM (`Source.VLM`)  — 글자가 없는 문제(비포·애프터 사진, 노출, 위조품 등)를
     모델이 본다. **여기서는 인용할 텍스트가 없어 역검증이 불가능하다.**
     그래서 가중치를 가장 낮게 두고, 판정한 이미지 URL을 반드시 함께 돌려줘
     사람이 직접 열어 보게 한다. 모델이 우리가 받지도 않은 이미지를 지어내면
     그 지적은 폐기한다.

OCR이 깔려 있지 않거나 VLM이 없으면 조용히 빠진다 — 이미지 점검이 안 된다고
페이지 점검 전체가 멈추면 안 된다.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import subprocess
import time
from io import BytesIO

import httpx

from . import ocr_paddle
from .analyzer import _extract_json
from .fetcher import USER_AGENT, UnsafeURLError, safe_client, safe_get
from .llm import LLMClient
from .models import (
    Enforcement,
    Finding,
    ImageAsset,
    ImageReport,
    PageSnapshot,
    Platform,
    Severity,
    Source,
)
from .policies import POLICY_BY_CODE
from .rules import CONTENT_PATTERNS

MAX_IMAGES = int(os.getenv("MAX_IMAGES", "8"))
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", "5000000"))
# 이보다 작으면 아이콘·추적 픽셀·구분선이다. 읽을 문구가 없다.
MIN_IMAGE_BYTES = int(os.getenv("MIN_IMAGE_BYTES", "3000"))
MIN_IMAGE_SIDE = int(os.getenv("MIN_IMAGE_SIDE", "150"))
OCR_LANGS = os.getenv("OCR_LANGS", "kor+eng")
OCR_TIMEOUT = float(os.getenv("OCR_TIMEOUT", "12"))
# 이미지 한 장에 쓸 수 있는 총 시간. 후보 조합을 늘리면 최악의 경우가
# 조합 수 x OCR_TIMEOUT 까지 커지므로, 벽시계로 한 번 더 막는다.
OCR_BUDGET = float(os.getenv("OCR_BUDGET", "25"))
# 한 페이지(이미지 여러 장) 전체에 쓸 수 있는 시간. 요청 데드라인 안에 들어와야 한다.
OCR_PAGE_BUDGET = float(os.getenv("OCR_PAGE_BUDGET", "90"))

VLM_BASE_URL = os.getenv("VLM_BASE_URL", "")
VLM_MODEL = os.getenv("VLM_MODEL", "")

_ALLOWED_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp")

# 한 요청이 이미지로 쓸 수 있는 총량. 장당 상한만 두면 8장 × 5MB가 그대로 들어온다.
MAX_TOTAL_IMAGE_BYTES = int(os.getenv("MAX_TOTAL_IMAGE_BYTES", "20000000"))
# 확대 후 픽셀 수 상한. 작은 파일이 기가픽셀로 부풀어 프로세스를 죽이는 걸 막는다.
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "40000000"))

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def _sniff_image_type(data: bytes) -> str:
    """Content-Type이 없을 때 매직 바이트로 판별한다."""
    for magic, ctype in _MAGIC:
        if data.startswith(magic):
            return ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------


async def _fetch_one(client: httpx.AsyncClient, url: str) -> ImageAsset:
    try:
        # safe_get이 홉마다 SSRF 가드를 걸고 본문을 상한에서 끊는다.
        resp, data, _ = await safe_get(
            client, url, max_bytes=MAX_IMAGE_BYTES, max_redirects=3
        )
    except UnsafeURLError as exc:
        return ImageAsset(url=url, fetch_error=str(exc))
    except httpx.HTTPError as exc:
        return ImageAsset(url=url, fetch_error=f"요청 실패: {type(exc).__name__}")

    if resp.status_code >= 400:
        return ImageAsset(url=url, fetch_error=f"HTTP {resp.status_code}")

    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    # Content-Type이 **없을 때도** 통과시키면 임의 바이트가 OCR과 VLM으로 흘러간다.
    # 헤더가 없으면 매직 바이트로 판별하고, 그것도 아니면 거부한다.
    if not ctype:
        ctype = _sniff_image_type(data)
        if not ctype:
            return ImageAsset(url=url, fetch_error="이미지가 아닙니다 (형식 불명)")
    elif not ctype.startswith("image/"):
        return ImageAsset(url=url, content_type=ctype, fetch_error="이미지가 아닙니다")
    elif ctype not in _ALLOWED_TYPES:
        return ImageAsset(url=url, content_type=ctype,
                          fetch_error=f"지원하지 않는 형식: {ctype}")
    asset = ImageAsset(url=url, content_type=ctype, bytes_len=len(data))
    if len(data) < MIN_IMAGE_BYTES:
        asset.fetch_error = "너무 작아 건너뜀 (아이콘·추적 픽셀)"
        return asset

    asset.width, asset.height = _dimensions(data)
    if asset.width == 0:
        # 열리지 않는 이미지다. 압축 폭탄이면 PIL이 여기서 거부한 것이므로
        # 그대로 통과시키면 안 된다.
        asset.fetch_error = "이미지를 열 수 없습니다"
        return asset
    if asset.width * asset.height > MAX_IMAGE_PIXELS:
        asset.fetch_error = f"픽셀 수 상한 초과 ({asset.width}x{asset.height})"
        return asset
    if max(asset.width, asset.height) < MIN_IMAGE_SIDE:
        asset.fetch_error = f"너무 작아 건너뜀 ({asset.width}x{asset.height})"
        return asset

    asset.data_b64 = base64.b64encode(data).decode("ascii")
    return asset


def _dimensions(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError:
        return 0, 0
    try:
        with Image.open(BytesIO(data)) as im:
            return im.width, im.height
    except Exception:  # noqa: BLE001 — 깨진 이미지는 크기 0으로 두고 계속 간다
        return 0, 0


async def collect(snap: PageSnapshot, limit: int = MAX_IMAGES) -> list[ImageAsset]:
    """페이지의 이미지를 상한 안에서 내려받는다. 실패는 asset에 기록만 한다."""
    urls = snap.image_urls[: limit * 3]  # 작은 것들이 걸러지므로 여유 있게 후보를 잡는다
    if not urls:
        return []

    headers = {"User-Agent": USER_AGENT, "Referer": snap.final_url or snap.url}
    out: list[ImageAsset] = []
    usable = 0
    total_bytes = 0

    async with safe_client(headers=headers) as client:
        for chunk_start in range(0, len(urls), 4):
            batch = urls[chunk_start : chunk_start + 4]
            results = await asyncio.gather(
                *(_fetch_one(client, u) for u in batch), return_exceptions=False
            )
            for asset in results:
                if not asset.ok:
                    out.append(asset)
                    continue
                # 장당 상한만으로는 부족하다. 총량과 장수를 여기서 함께 막는다.
                if usable >= limit:
                    asset.data_b64 = ""
                    asset.fetch_error = f"이미지 상한({limit}장)을 넘어 건너뜀"
                elif total_bytes + asset.bytes_len > MAX_TOTAL_IMAGE_BYTES:
                    asset.data_b64 = ""
                    asset.fetch_error = "이미지 총량 상한을 넘어 건너뜀"
                else:
                    usable += 1
                    total_bytes += asset.bytes_len
                out.append(asset)
            if usable >= limit:
                break
    return out


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


# 어떤 OCR을 쓸지.
#   auto      — PaddleOCR(한국어)이 준비돼 있으면 그걸, 아니면 tesseract
#   paddle    — PaddleOCR만. 없으면 이미지 점검은 실패로 남긴다
#   tesseract — 예전 동작 그대로
OCR_ENGINE = os.getenv("OCR_ENGINE", "auto").strip().lower()


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def active_engine() -> str:
    """이번 실행에 실제로 쓰이는 엔진 이름. 못 쓰면 빈 문자열.

    사용자가 결과를 보고 "무엇이 읽었는지" 알 수 있어야 한다. 설정만
    바꿔놓고 실제로는 예전 엔진이 도는 상황이 제일 나쁘다.
    """
    if OCR_ENGINE == "tesseract":
        return "tesseract" if _tesseract_available() else ""
    if ocr_paddle.available():
        return "paddle"
    if OCR_ENGINE == "paddle":
        return ""
    return "tesseract" if _tesseract_available() else ""


def ocr_available() -> bool:
    return active_engine() != ""


# 조건마다 잘 듣는 전처리가 다르다. 하나로 고정하면 어떤 배너는 반드시 손해를
# 본다 — 확대는 작은 글씨엔 크게 도움되지만 그라데이션 배경에선 오히려 떨어진다.
# 그래서 후보를 몇 개 만들어 돌려보고, **tesseract가 가장 확신한 결과**를 고른다.
# 다만 매번 6번씩 돌릴 수는 없어서, 충분히 확신하면 거기서 멈춘(early exit)다.
OCR_CONFIDENT_ENOUGH = float(os.getenv("OCR_CONFIDENT_ENOUGH", "95"))
OCR_TARGET_WIDTH = int(os.getenv("OCR_TARGET_WIDTH", "1600"))
# 이 신뢰도에 못 미치는 줄은 버린다. 사진 위 장식 글자처럼 반쯤 읽히는 구간이
# 쓰레기 문자열로 남아 화면을 어지럽히고 룰까지 오염시키는 걸 막는다.
OCR_MIN_LINE_CONF = float(os.getenv("OCR_MIN_LINE_CONF", "55"))
# 한글이 없는 줄은 더 높게 본다. 실측으로 잡음·사진 결에서 나온 라틴 조각
# ("OP pt", "mary ar")은 58~69, 실제 영문 배너 문구는 95~97이었다. 한국어는
# 정상 문구도 87 안팎으로 나와 같은 기준을 쓰면 멀쩡한 줄을 버린다.
OCR_MIN_LATIN_CONF = float(os.getenv("OCR_MIN_LATIN_CONF", "75"))


def _variants(data: bytes):
    """(이름, PNG 바이트) 후보들. 싼 것부터 내놓는다."""
    yield "원본", data
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return
    try:
        with Image.open(BytesIO(data)) as im:
            im = im.convert("RGB")
            scale = max(1, min(4, round(OCR_TARGET_WIDTH / max(im.width, 1))))
            if scale <= 1:
                return
            # 확대 결과가 기가픽셀이 되면 프로세스가 죽는다. PIL의 자체 한도는
            # 원본 크기만 보므로 여기서 확대 후 픽셀 수를 직접 막는다.
            if im.width * im.height * scale * scale > MAX_IMAGE_PIXELS:
                return
            big = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
            buf = BytesIO()
            big.save(buf, format="PNG")
            yield f"x{scale}", buf.getvalue()

            # 저대비·사진 배경에서 글자 경계를 살린다
            sharp = ImageOps.autocontrast(big.convert("L"), cutoff=2).filter(
                ImageFilter.UnsharpMask(radius=2, percent=140, threshold=3)
            )
            buf = BytesIO()
            sharp.save(buf, format="PNG")
            yield f"x{scale}+전처리", buf.getvalue()
    except Exception:  # noqa: BLE001 — 전처리 실패는 원본으로 계속 간다
        return


def _line_confidences(png: bytes, psm: int) -> list[float]:
    """줄마다의 신뢰도. 텍스트는 여기서 만들지 않는다.

    TSV의 단어 분리는 한국어에서 엉뚱해서("신청하면" → "신 청 하면") 다시
    붙이려 하면 붙이거나 떼는 쪽 어느 하나가 반드시 어긋난다. 그래서 표시용
    텍스트는 tesseract의 기본 출력을 그대로 쓰고, TSV는 **줄별 신뢰도**를
    재는 데만 쓴다. 두 출력의 줄 순서는 같은 레이아웃 분석에서 나온다.
    """
    try:
        proc = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", OCR_LANGS, "--psm", str(psm), "tsv"],
            input=png, capture_output=True, timeout=OCR_TIMEOUT, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []

    groups: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    for row in proc.stdout.decode("utf-8", "replace").splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12:
            continue
        try:
            key = (int(c[2]), int(c[3]), int(c[4]))
            conf = float(c[10])
        except ValueError:
            continue
        word = c[11].strip()
        if conf >= 0 and word:
            groups.setdefault(key, []).append((word, conf))

    out: list[float] = []
    for key in sorted(groups):
        words = groups[key]
        total = sum(len(w) for w, _ in words)
        out.append(sum(cf * len(w) for w, cf in words) / total)
    return out


def _plain_lines(png: bytes, psm: int) -> list[str]:
    """tesseract 기본 출력. 띄어쓰기가 원본에 가장 가깝다."""
    try:
        proc = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", OCR_LANGS, "--psm", str(psm)],
            input=png, capture_output=True, timeout=OCR_TIMEOUT, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.decode("utf-8", "replace").splitlines()
            if ln.strip()]


def _read(png: bytes, psm: int) -> list[tuple[str, float]]:
    """(줄 텍스트, 줄 신뢰도). 줄 수가 어긋나면 필터를 포기하고 전부 살린다."""
    texts = _plain_lines(png, psm)
    if not texts:
        return []
    confs = _line_confidences(png, psm)
    if len(confs) != len(texts):
        # 정렬이 안 맞는데 억지로 걸러내면 멀쩡한 줄을 버릴 수 있다.
        return [(t, 100.0) for t in texts]
    return list(zip(texts, confs, strict=True))


# 의미 있는 글자 덩어리 — 한글 음절, 또는 두 글자 이상 이어진 영숫자.
# 노이즈에서 나오는 "~", "&", "iN" 같은 조각을 내용으로 세지 않기 위한 것.
_WORDISH = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_HANGUL = re.compile(r"[가-힣]")
# 결과 전체가 이보다 적으면 "읽은 게 없다"로 본다.
OCR_MIN_CONTENT = int(os.getenv("OCR_MIN_CONTENT", "8"))


def _content_len(text: str) -> int:
    return sum(len(m.group()) for m in _WORDISH.finditer(text))


def _keep_line(text: str, conf: float) -> bool:
    if conf < OCR_MIN_LINE_CONF:
        return False
    content = _content_len(text)
    if _HANGUL.search(text):
        return content >= 2
    # 한글이 없는 줄은 더 엄격하게. 노이즈는 대개 한두 글자 라틴 조각으로 나오고,
    # 길게 나와도 신뢰도가 낮다.
    return content >= 4 and conf >= OCR_MIN_LATIN_CONF


def _score(lines: list[tuple[str, float]]) -> float:
    """이 조합이 얼마나 잘 읽었는가. 글자 수로 가중 평균하고 분량을 약간 가산."""
    kept = [(t, c) for t, c in lines if _keep_line(t, c)]
    if not kept:
        return -1.0
    content = sum(_content_len(t) for t, _ in kept)
    if content < OCR_MIN_CONTENT:
        # 조각만 몇 개 건진 것은 읽었다고 볼 수 없다.
        return -1.0
    total = sum(len(t) for t, _ in kept)
    mean = sum(c * len(t) for t, c in kept) / total
    return mean + min(content, 60) * 0.15


def _join(lines: list[tuple[str, float]]) -> str:
    """신뢰도가 낮은 줄은 버린다.

    반쯤 읽힌 줄("은 ae [버", "= hel 0y ea, 7")을 그대로 두면 화면도 지저분하고,
    무엇보다 그 잡음이 정책 패턴에 우연히 걸려 엉뚱한 지적을 만들 수 있다.
    """
    return "\n".join(t for t, c in lines if _keep_line(t, c))


def _paddle_image(data: bytes) -> tuple[str, str]:
    """PaddleOCR 경로.

    tesseract처럼 PSM을 돌려볼 필요가 없다 — 검출망이 글자 영역을 스스로
    찾으므로 조합 탐색은 낭비다. 대신 원본에서 건진 게 없을 때만 확대본을
    한 번 더 본다. 작은 배너에서 실제로 이게 갈린다.
    """
    for _, png in _variants(data):
        lines = ocr_paddle.read(png)
        if lines and _score(lines) >= 0:
            return _join(lines), ""
    return "", "OCR이 읽을 만한 글자를 찾지 못했습니다"


def ocr_image(data: bytes) -> tuple[str, str]:
    """(읽어낸 텍스트, 오류).

    전처리 후보 x PSM 조합을 신뢰도로 겨뤄 이긴 조합의 결과를 쓴다.
    조건마다 잘 듣는 전처리가 달라서 하나로 고정하면 반드시 손해 보는
    배너가 생긴다. 마지막에 신뢰도 낮은 줄을 걷어낸다.
    """
    engine = active_engine()
    if engine == "paddle":
        return _paddle_image(data)
    if engine != "tesseract":
        if OCR_ENGINE == "paddle":
            return "", f"PaddleOCR을 쓸 수 없습니다 ({ocr_paddle.error() or '원인 불명'})"
        return "", "tesseract가 설치되어 있지 않습니다"

    best: list[tuple[str, float]] = []
    best_score = -1.0
    tried = 0
    deadline = time.monotonic() + OCR_BUDGET

    for _, png in _variants(data):
        # 6 = 균일한 블록, 4 = 크기가 제각각인 세로 배치(국내 랜딩페이지),
        # 11 = 흩어진 텍스트. 배너는 셋 다 나온다.
        for psm in (6, 4, 11):
            if tried and time.monotonic() > deadline:
                return (_join(best) if best else ""), ""
            tried += 1
            lines = _read(png, psm)
            if not lines:
                continue
            score = _score(lines)
            if score > best_score:
                best_score, best = score, lines
            if score >= OCR_CONFIDENT_ENOUGH:
                return _join(lines), ""

    if not best or best_score < 0:
        return "", ("OCR이 읽을 만한 글자를 찾지 못했습니다" if tried else "OCR 실행 실패")
    return _join(best), ""


def run_ocr(assets: list[ImageAsset]) -> None:
    """각 asset에 ocr_text를 채운다 (제자리 수정).

    장당 예산만으로는 부족하다 — 8장이면 그 합이 요청 데드라인을 넘긴다.
    페이지 전체 예산을 따로 두고, 넘기면 남은 장은 이유를 적고 건너뛴다.
    """
    deadline = time.monotonic() + OCR_PAGE_BUDGET
    engine = active_engine()
    for a in assets:
        if not a.ok or not a.data_b64:
            continue
        if time.monotonic() > deadline:
            a.ocr_error = "OCR 시간 예산을 넘겨 건너뛰었습니다"
            continue
        a.ocr_engine = engine
        a.ocr_text, a.ocr_error = ocr_image(base64.b64decode(a.data_b64))


def merged_ocr_text(assets: list[ImageAsset]) -> str:
    return "\n".join(a.ocr_text for a in assets if a.ocr_text)


# ---------------------------------------------------------------------------
# 이미지 속 텍스트에 결정적 룰 적용
# ---------------------------------------------------------------------------


def check_image_text(assets: list[ImageAsset], platform: Platform) -> list[Finding]:
    """이미지별로 기존 CONTENT_PATTERNS를 돌린다.

    새 룰을 만들지 않는다 — 본문에서 잡는 것과 같은 기준을 이미지에도
    적용하는 것이 요점이다. 다만 **어느 이미지에서 나왔는지**를 붙여서,
    사용자가 그 배너를 바로 열어 볼 수 있게 한다.
    """
    findings: list[Finding] = []
    seen: set[str] = set()

    for asset in assets:
        if not asset.ocr_text:
            continue
        for code, pattern in CONTENT_PATTERNS:
            if code in seen:
                continue
            policy = POLICY_BY_CODE[code]
            if platform not in policy.platforms:
                continue
            if (m := pattern.search(asset.ocr_text)) is None:
                continue
            seen.add(code)
            findings.append(Finding(
                code=policy.code,
                title=policy.title,
                severity=policy.severity,
                enforcement=policy.enforcement,
                source=Source.OCR,
                detail=(
                    policy.description
                    + " 본문이 아니라 **이미지 안에서** 발견되었습니다 — "
                    "심사도 이미지를 읽습니다."
                ),
                evidence=m.group(0).strip(),
                fix=policy.fix,
                image_url=asset.url,
            ))
    return findings


# ---------------------------------------------------------------------------
# VLM — 이미지 자체 판정
# ---------------------------------------------------------------------------

VLM_SYSTEM = """너는 광고 심사관이다. 주어진 이미지가 광고 정책에 걸릴 소지가 있는지 본다.

**글자가 아니라 그림 자체**를 본다. 글자는 다른 단계에서 이미 처리했다.

반드시 아래 JSON만 출력한다. analysis를 먼저 쓰고 그 다음 findings를 쓴다.

{
  "analysis": "이미지에 무엇이 보이는지, 왜 그렇게 판단했는지 2~3문장",
  "findings": [
    {"code": "정책코드", "reason": "이미지의 어느 부분이 왜 문제인지"}
  ]
}

확실하지 않으면 findings를 비운다. 애매한 것을 올리는 것보다 놓치는 편이 낫다.
사용 가능한 코드:
"""

# 시각적으로만 판별 가능한 항목들. 텍스트 룰이 이미 잡는 것은 넣지 않는다.
VLM_CODES = (
    "TT-BEFORE-AFTER",
    # 체형 비하는 글자보다 그림으로 하는 경우가 많다 — 배 잡고 한숨 쉬는 사진,
    # 체형에 X 표시. 텍스트 룰이 닿지 않는 영역이라 여기 넣는다.
    "TT-BODY-IMAGE",
    "RESTRICT-SEXUAL",
    "RESTRICT-HEALTHCARE",
    "PROHIB-COUNTERFEIT",
    "RESTRICT-GAMBLING",
    "PROHIB-DANGEROUS",
)

def _vlm_catalog(platform: Platform) -> str:
    lines = []
    for code in VLM_CODES:
        p = POLICY_BY_CODE[code]
        if platform in p.platforms:
            lines.append(f"  {p.code} — {p.title}: {p.description}")
    return "\n".join(lines)


async def _judge_one(
    client: LLMClient, asset: ImageAsset, platform: Platform
) -> tuple[list[dict], str]:
    payload_image = f"data:{asset.content_type or 'image/png'};base64,{asset.data_b64}"
    messages = [
        {"role": "system", "content": VLM_SYSTEM + _vlm_catalog(platform)},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": payload_image}},
            {"type": "text", "text": "이 이미지를 판정해라."},
        ]},
    ]
    raw, err = await client.complete_messages(messages, max_tokens=700)
    if err:
        return [], err
    if not raw:
        return [], "VLM이 빈 응답을 반환했습니다"
    # analyzer와 같은 파서를 쓴다. 예전의 탐욕적 정규식은 첫 { 부터 마지막 }
    # 까지를 통째로 집어서, 뒤에 중괄호가 섞인 문장이 한 줄만 붙어도 JSON 파싱이
    # 깨지고 findings가 통째로 사라졌다 — 오류도 통계도 없이.
    data = _extract_json(raw)
    if data is None:
        return [], "UNPARSEABLE"
    items = data.get("findings") or []
    return [i for i in items if isinstance(i, dict)], ""


async def analyze_images(
    assets: list[ImageAsset], platform: Platform, client: LLMClient | None = None
) -> tuple[list[Finding], dict[str, int], str]:
    """이미지 자체를 VLM으로 판정한다.

    Returns: (findings, stats, error)
    """
    usable = [a for a in assets if a.ok and a.data_b64]
    if not usable:
        return [], {}, ""
    if not VLM_BASE_URL:
        return [], {}, "VLM_BASE_URL이 설정되지 않아 이미지 자체 판정을 건너뛰었습니다."

    client = client or LLMClient(base_url=VLM_BASE_URL, model=VLM_MODEL or None)
    stats = {"vlm_images": len(usable), "vlm_raw": 0, "vlm_dropped_unknown_code": 0}
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    first_error = ""

    for asset in usable:
        items, err = await _judge_one(client, asset, platform)
        if err == "UNPARSEABLE":
            # 응답은 왔는데 JSON이 아니다. 조용히 0건으로 두면 "문제 없음"과
            # 구분이 안 되므로 통계에 남긴다.
            stats["vlm_unparseable"] = stats.get("vlm_unparseable", 0) + 1
            continue
        if err and not first_error:
            first_error = err
            continue
        for item in items:
            stats["vlm_raw"] += 1
            code = str(item.get("code", "")).strip().upper()
            policy = POLICY_BY_CODE.get(code)
            # 카탈로그에 없거나, 애초에 VLM에게 물어보지 않은 코드는 폐기한다.
            if policy is None or code not in VLM_CODES:
                stats["vlm_dropped_unknown_code"] += 1
                continue
            if platform not in policy.platforms:
                stats["vlm_dropped_unknown_code"] += 1
                continue
            if (code, asset.url) in seen:
                continue
            seen.add((code, asset.url))

            reason = str(item.get("reason", "")).strip()
            findings.append(Finding(
                code=policy.code,
                title=policy.title,
                # 역검증이 불가능하므로 block으로 올리지 않는다. 사람이 확인할 일이다.
                severity=Severity.WARN if policy.severity == Severity.BLOCK
                else policy.severity,
                # 같은 이유로 정지 등급도 올리지 않는다. 인용할 문구 하나 없는
                # 모델 추측을 근거로 "계정이 정지됩니다"라고 말할 수는 없다.
                enforcement=Enforcement.DISAPPROVE,
                source=Source.VLM,
                detail=(
                    policy.description
                    + " 이미지 자체에 대한 모델 판단입니다 — "
                    "인용할 문구가 없어 자동 검증이 불가능하니 직접 확인하세요."
                ),
                evidence=reason[:300],
                fix=policy.fix,
                image_url=asset.url,
            ))

    stats["vlm_findings_kept"] = len(findings)
    return findings, stats, first_error


# ---------------------------------------------------------------------------
# 보고 — 무엇을 읽었는지 사용자에게 그대로 보여준다
# ---------------------------------------------------------------------------

OCR_TEXT_PREVIEW = int(os.getenv("OCR_TEXT_PREVIEW", "600"))


def build_reports(assets: list[ImageAsset], findings: list[Finding]) -> list[ImageReport]:
    """이미지별 보고를 만든다.

    지적이 없는 이미지도 포함한다. "읽었는데 걸리는 문구가 없었다"와
    "아예 못 읽었다"는 완전히 다른 정보이고, 무엇을 읽었는지 보여줘야
    사용자가 결과를 신뢰하거나 반박할 수 있다.
    """
    by_image: dict[str, list[str]] = {}
    for f in findings:
        if f.image_url:
            by_image.setdefault(f.image_url, []).append(f.code)

    out: list[ImageReport] = []
    for a in assets:
        text = a.ocr_text.strip()
        if len(text) > OCR_TEXT_PREVIEW:
            text = text[:OCR_TEXT_PREVIEW].rstrip() + " …"

        note = a.fetch_error or a.ocr_error
        if not note and a.ok and not text:
            note = "읽어낼 글자가 없었습니다 (사진·도형 위주)"

        out.append(ImageReport(
            url=a.url,
            width=a.width,
            height=a.height,
            ocr_engine=a.ocr_engine,
            ocr_text=text,
            note=note,
            finding_codes=by_image.get(a.url, []),
        ))
    return out
