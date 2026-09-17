"""PaddleOCR 한국어 엔진 어댑터.

왜 따로 두는가
--------------
tesseract는 한국어 랜딩페이지 배너에서 잘 못 읽는다. 글자가 사진 위에
얹혀 있거나, 자간이 넓거나, 굵은 고딕이면 절반을 놓친다. PaddleOCR의
`korean_PP-OCRv4_rec`는 같은 조건에서 눈에 띄게 낫다.

다만 의존성이 무겁고(paddlepaddle) 모델을 런타임에 내려받는 게 기본이라,
**엔진을 갈아끼우는 형태**로 넣는다. 못 쓰는 환경이면 tesseract로 조용히
돌아간다. 그래서 이 모듈은 vision.py의 `_read()`와 **똑같은 모양**
(줄 텍스트, 0~100 신뢰도)을 돌려준다. 뒤쪽의 `_keep_line`/`_score`/`_join`
필터가 엔진과 무관하게 그대로 동작해야 하기 때문이다.

PaddleOCR은 "줄"이 아니라 **검출 박스** 단위로 결과를 준다. 한 줄이
여러 박스로 쪼개져 나오는 일이 흔해서(예: "지금  신청하면  50% 할인"이
세 박스), 여기서 y좌표로 다시 줄을 묶어 준다. 이 과정을 건너뛰면
정책 패턴이 줄을 넘나드는 문구를 놓친다.
"""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

# paddleocr의 lang 코드. 한국어 모델은 det=Multilingual_PP-OCRv3,
# rec=korean_PP-OCRv4 조합으로 내려온다.
PADDLE_LANG = os.getenv("PADDLE_LANG", "korean")
# 세로로 뒤집힌 글자 보정. 광고 배너에는 거의 없고, 켜면 느려진다.
PADDLE_USE_ANGLE_CLS = os.getenv("PADDLE_USE_ANGLE_CLS", "0") == "1"
PADDLE_USE_GPU = os.getenv("PADDLE_USE_GPU", "0") == "1"
# 검출 박스를 한 줄로 볼지 판단하는 세로 겹침 비율.
PADDLE_LINE_OVERLAP = float(os.getenv("PADDLE_LINE_OVERLAP", "0.45"))

_lock = threading.Lock()
_engine = None
_engine_error = ""
_tried = False


def _build():
    """PaddleOCR 인스턴스 하나. 버전마다 인자 이름이 달라 관대하게 만든다."""
    from paddleocr import PaddleOCR  # noqa: PLC0415 — 무거워서 지연 임포트

    wanted = {
        "lang": PADDLE_LANG,
        "use_angle_cls": PADDLE_USE_ANGLE_CLS,
        "use_gpu": PADDLE_USE_GPU,
        "show_log": False,
    }
    # 2.x와 3.x가 받는 인자가 다르다. 거절당한 인자만 떼고 다시 시도한다.
    while True:
        try:
            return PaddleOCR(**wanted)
        except TypeError as exc:
            dropped = next(
                (k for k in list(wanted) if k != "lang" and k in str(exc)), None
            )
            if dropped is None:
                raise
            wanted.pop(dropped)


def engine():
    """준비된 엔진, 또는 None. 실패는 한 번만 겪고 기억한다.

    모델 다운로드까지 포함해 수십 초가 걸릴 수 있어서, 매 요청마다
    다시 시도하면 서버가 그대로 멈춘다.
    """
    global _engine, _engine_error, _tried
    if _tried:
        return _engine
    with _lock:
        if _tried:  # 락 밖에서 앞질러 온 스레드
            return _engine
        try:
            _engine = _build()
        except Exception as exc:  # noqa: BLE001 — 임포트·다운로드·CPU명령어 등
            _engine, _engine_error = None, f"{type(exc).__name__}: {exc}"
            log.warning("PaddleOCR을 쓸 수 없습니다: %s", _engine_error)
        finally:
            _tried = True
    return _engine


def available() -> bool:
    return engine() is not None


# 빌드 때 모델을 못 받으면 Dockerfile이 여기에 이유를 남긴다. 그 사실을
# 알리지 않으면 "왜 OCR이 이것밖에 안 되지"를 사용자가 영영 알 수 없다.
BUILD_NOTE_PATH = os.getenv("PADDLE_BUILD_NOTE", "/app/.paddle_unavailable")


def build_note() -> str:
    try:
        with open(BUILD_NOTE_PATH, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def error() -> str:
    engine()
    if _engine_error and (note := build_note()):
        return f"{_engine_error} · 빌드 단계: {note}"
    return _engine_error or build_note()


def reset() -> None:
    """테스트용. 다음 호출에서 다시 만들게 한다."""
    global _engine, _engine_error, _tried
    with _lock:
        _engine, _engine_error, _tried = None, "", False


# ---------------------------------------------------------------------------
# 결과 정리
# ---------------------------------------------------------------------------


def _is_item(node) -> bool:
    """`[[[x,y]x4], (텍스트, 점수)]` 한 덩어리인가."""
    if not isinstance(node, (list, tuple)) or len(node) != 2:
        return False
    box, payload = node
    if not isinstance(payload, (list, tuple)) or not payload:
        return False
    if not isinstance(payload[0], str):
        return False
    return isinstance(box, (list, tuple)) and bool(box) and isinstance(box[0], (list, tuple))


def _iter_items(node, depth: int = 0):
    """중첩이 몇 겹이든 항목만 골라낸다.

    2.9는 `[page]`로 한 겹 감싸고, 글자를 못 찾으면 `[None]`을 준다.
    3.x나 다른 래퍼는 또 다르다. 겹수를 세는 대신 **모양으로** 찾는 편이
    버전을 따라다니지 않아도 되고, 깨진 값에도 안 터진다.
    """
    if depth > 3 or node is None:
        return
    if _is_item(node):
        yield node
        return
    if isinstance(node, (list, tuple)):
        for child in node:
            yield from _iter_items(child, depth + 1)


def _cells(raw) -> list[tuple[float, float, float, str, float]]:
    """PaddleOCR 출력 → (y중심, x왼쪽, 높이, 텍스트, 신뢰도 0~1).

    이상한 항목은 건너뛴다 — 여기서 터지면 이미지 한 장 때문에 점검
    전체가 500이 된다.
    """
    out: list[tuple[float, float, float, str, float]] = []
    for box, payload in _iter_items(raw):
        try:
            text, score = payload[0], float(payload[1])
            ys = [float(p[1]) for p in box]
            xs = [float(p[0]) for p in box]
        except (TypeError, ValueError, IndexError):
            continue
        text = text.strip()
        if not text or not ys:
            continue
        top, bottom = min(ys), max(ys)
        out.append(((top + bottom) / 2, min(xs), max(bottom - top, 1.0), text, score))
    return out


def _group(cells) -> list[tuple[str, float]]:
    """세로로 겹치는 박스끼리 한 줄로 묶는다.

    같은 줄인지는 "두 박스의 세로 겹침이 더 작은 글자 높이의 절반 이상인가"로
    본다. 절대 픽셀값으로 판단하면 큰 제목과 작은 본문 중 한쪽이 반드시
    틀린다.
    """
    if not cells:
        return []
    cells = sorted(cells, key=lambda c: (c[0], c[1]))

    lines: list[list] = []
    anchors: list[tuple[float, float]] = []  # (기준 y, 기준 높이)
    for cell in cells:
        y, _, h, _, _ = cell
        # 기준을 줄의 "평균"으로 잡으면 한 칸씩 조금씩 밀리면서 아래 줄까지
        # 빨려 들어간다. 줄을 연 첫 박스에 고정한다.
        if lines and abs(y - anchors[-1][0]) <= min(h, anchors[-1][1]) * PADDLE_LINE_OVERLAP:
            lines[-1].append(cell)
        else:
            lines.append([cell])
            anchors.append((y, h))

    out: list[tuple[str, float]] = []
    for line in lines:
        line.sort(key=lambda c: c[1])  # 왼쪽부터
        text = " ".join(c[3] for c in line).strip()
        if not text:
            continue
        total = sum(len(c[3]) for c in line) or 1
        conf = sum(c[4] * len(c[3]) for c in line) / total
        out.append((text, max(0.0, min(1.0, conf)) * 100.0))
    return out


def read(data: bytes) -> list[tuple[str, float]]:
    """이미지 바이트 → [(줄 텍스트, 0~100 신뢰도)].

    바이트를 그대로 넘긴다. 문자열을 넘기면 paddleocr이 그걸 경로나
    **URL로 보고 직접 내려받는다** — 우리 SSRF 가드를 우회하는 통로가
    되므로 절대 하지 않는다.
    """
    eng = engine()
    if eng is None:
        return []
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("read()는 이미지 바이트만 받습니다")
    try:
        raw = eng.ocr(bytes(data), cls=PADDLE_USE_ANGLE_CLS)
    except Exception as exc:  # noqa: BLE001 — 깨진 이미지 한 장이 요청을 죽이면 안 된다
        log.warning("PaddleOCR 인식 실패: %s", exc)
        return []
    return _group(_cells(raw))
