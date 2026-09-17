"""PaddleOCR 어댑터 회귀 테스트.

여기서 검증하는 것은 **어댑터**다 — PaddleOCR이 준 박스를 줄로 되돌리고,
엔진을 갈아끼우고, 못 쓸 때 tesseract로 내려가는 부분. 한국어 인식
정확도 자체는 모델 가중치가 필요해서 이 테스트로는 잴 수 없다.

입력으로 쓰는 구조는 paddleocr 2.9.1의 `PaddleOCR.ocr()`이 실제로
만드는 모양 그대로다 (paddleocr.py:  `[[box.tolist(), res] for box, res
in zip(dt_boxes, rec_res)]` 를 페이지 리스트에 담아 반환, 글자를 못
찾으면 그 자리에 None).
"""

from __future__ import annotations

import pytest

from adpolicy import ocr_paddle, vision


def box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    """PaddleOCR이 주는 4점 박스 (좌상 → 우상 → 우하 → 좌하)."""
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def page(*items) -> list:
    """실제 반환 모양: 페이지 리스트로 한 겹 감싼다."""
    return [list(items)]


# ---------------------------------------------------------------------------
# 출력 파싱
# ---------------------------------------------------------------------------


def test_parses_the_real_2x_shape():
    raw = page(
        [box(10, 10, 200, 50), ("지금 신청하면", 0.98)],
        [box(210, 12, 320, 48), ("50% 할인", 0.91)],
    )
    cells = ocr_paddle._cells(raw)
    assert [c[3] for c in cells] == ["지금 신청하면", "50% 할인"]
    assert cells[0][0] == 30.0  # y 중심
    assert cells[0][2] == 40.0  # 높이


def test_no_text_found_returns_nothing_not_a_crash():
    """글자를 못 찾으면 paddleocr은 [None]을 준다."""
    assert ocr_paddle._cells([None]) == []
    assert ocr_paddle._cells(None) == []
    assert ocr_paddle._cells([]) == []


def test_unwrapped_single_item_page_is_not_mistaken_for_a_wrapper():
    """항목이 하나뿐인 페이지를 한 겹 더 벗기면 결과가 통째로 사라졌다."""
    flat = [[box(0, 0, 100, 30), ("단독 문구", 0.9)]]
    assert [c[3] for c in ocr_paddle._cells(flat)] == ["단독 문구"]
    assert [c[3] for c in ocr_paddle._cells(page(*flat))] == ["단독 문구"]


def test_broken_entries_are_skipped_not_raised():
    """이미지 한 장이 이상하다고 점검 전체가 500이 되면 안 된다."""
    raw = page(
        ["not-a-box", ("무시", 0.9)],
        [box(0, 0, 10, 10), ("점수가 이상", "nan-ish")],
        [box(0, 0, 10, 10), ("", 0.99)],           # 빈 문자열
        [box(0, 20, 100, 50), ("살아남는 줄", 0.95)],
    )
    assert [c[3] for c in ocr_paddle._cells(raw)] == ["살아남는 줄"]


# ---------------------------------------------------------------------------
# 박스를 줄로 되돌리기 — 이걸 안 하면 줄을 넘나드는 문구를 룰이 놓친다
# ---------------------------------------------------------------------------


def test_boxes_on_one_visual_line_become_one_line_left_to_right():
    raw = page(
        [box(300, 10, 420, 50), ("50% 할인", 0.90)],   # 일부러 오른쪽 것을 먼저
        [box(10, 12, 280, 48), ("지금 신청하면", 0.98)],
    )
    lines = ocr_paddle._group(ocr_paddle._cells(raw))
    assert [t for t, _ in lines] == ["지금 신청하면 50% 할인"]


def test_separate_lines_stay_separate_and_are_ordered_top_down():
    raw = page(
        [box(10, 200, 300, 240), ("아래 줄", 0.9)],
        [box(10, 10, 300, 50), ("위 줄", 0.9)],
        [box(10, 100, 300, 140), ("가운데 줄", 0.9)],
    )
    lines = ocr_paddle._group(ocr_paddle._cells(raw))
    assert [t for t, _ in lines] == ["위 줄", "가운데 줄", "아래 줄"]


def test_line_grouping_is_relative_to_glyph_height_not_absolute_pixels():
    """큰 제목과 작은 본문이 섞여도 각자 제 줄로 간다.

    절대 픽셀로 판단하면 제목 기준으론 본문이 다 붙고, 본문 기준으론
    제목 한 줄이 쪼개진다.
    """
    raw = page(
        [box(10, 0, 400, 80), ("큰 제목", 0.95)],       # 높이 80, 중심 40
        [box(420, 20, 600, 60), ("옆 배지", 0.95)],     # 높이 40, 중심 40 → 같은 줄
        [box(10, 100, 200, 118), ("작은 본문 첫줄", 0.9)],   # 높이 18, 중심 109
        [box(10, 122, 200, 140), ("작은 본문 둘째줄", 0.9)],  # 높이 18, 중심 131
    )
    lines = [t for t, _ in ocr_paddle._group(ocr_paddle._cells(raw))]
    assert lines == ["큰 제목 옆 배지", "작은 본문 첫줄", "작은 본문 둘째줄"]


def test_grouping_does_not_drift_into_the_next_line():
    """기준을 줄 평균으로 잡으면 한 칸씩 밀리며 아래 줄까지 빨려 들어갔다."""
    # 높이 20짜리 박스가 y중심 100, 104, 108, 112 … 로 촘촘히 이어진다.
    raw = page(*[
        [box(0, y - 10, 50, y + 10), (f"조각{i}", 0.9)]
        for i, y in enumerate((100, 104, 108, 112, 116, 120))
    ])
    lines = ocr_paddle._group(ocr_paddle._cells(raw))
    # 기준(=첫 박스 y=100)에서 20*0.45=9 이내인 104, 108만 같은 줄
    assert lines[0][0] == "조각0 조각1 조각2"
    assert len(lines) > 1


def test_confidence_is_length_weighted_and_scaled_to_0_100():
    raw = page(
        [box(0, 0, 100, 30), ("가" * 9, 1.0)],
        [box(110, 0, 200, 30), ("나", 0.0)],
    )
    (_, conf), = ocr_paddle._group(ocr_paddle._cells(raw))
    assert conf == pytest.approx(90.0)  # (1.0*9 + 0.0*1) / 10 * 100


# ---------------------------------------------------------------------------
# read() — 엔진이 없거나 터져도 조용히 비어야 한다
# ---------------------------------------------------------------------------


class _FakeEngine:
    def __init__(self, result=None, boom: Exception | None = None):
        self.result, self.boom, self.calls = result, boom, []

    def ocr(self, img, cls=False):
        self.calls.append(img)
        if self.boom:
            raise self.boom
        return self.result


@pytest.fixture
def fake_paddle(monkeypatch):
    """ocr_paddle이 준비된 것처럼 보이게 만든다."""

    def install(engine):
        monkeypatch.setattr(ocr_paddle, "_engine", engine)
        monkeypatch.setattr(ocr_paddle, "_tried", True)
        monkeypatch.setattr(ocr_paddle, "_engine_error", "")
        return engine

    return install


def test_read_returns_nothing_when_engine_is_unavailable(monkeypatch):
    monkeypatch.setattr(ocr_paddle, "_engine", None)
    monkeypatch.setattr(ocr_paddle, "_tried", True)
    assert ocr_paddle.read(b"\x89PNG") == []


def test_read_refuses_a_string(fake_paddle):
    """문자열을 넘기면 paddleocr이 그걸 URL로 보고 직접 내려받는다 —
    우리 SSRF 가드를 통째로 우회하는 통로다."""
    fake_paddle(_FakeEngine(page()))
    with pytest.raises(TypeError):
        ocr_paddle.read("http://169.254.169.254/latest/meta-data/")  # type: ignore[arg-type]


def test_read_passes_raw_bytes_through(fake_paddle):
    eng = fake_paddle(_FakeEngine(page([box(0, 0, 90, 30), ("문구", 0.9)])))
    assert ocr_paddle.read(b"\x89PNG-data") == [("문구", pytest.approx(90.0))]
    assert eng.calls == [b"\x89PNG-data"]


def test_read_swallows_engine_errors(fake_paddle):
    fake_paddle(_FakeEngine(boom=RuntimeError("모델이 깨졌다")))
    assert ocr_paddle.read(b"\x89PNG") == []


def test_build_failure_is_remembered_not_retried(monkeypatch):
    """모델 다운로드까지 포함하면 수십 초다. 매 요청마다 다시 시도하면 서버가 멈춘다."""
    ocr_paddle.reset()
    tries = []

    def boom():
        tries.append(1)
        raise ImportError("paddle이 없다")

    monkeypatch.setattr(ocr_paddle, "_build", boom)
    assert ocr_paddle.available() is False
    assert ocr_paddle.available() is False
    assert ocr_paddle.available() is False
    assert len(tries) == 1
    assert "paddle이 없다" in ocr_paddle.error()
    ocr_paddle.reset()


# ---------------------------------------------------------------------------
# vision 쪽 배선 — 어떤 엔진이 실제로 도는가
# ---------------------------------------------------------------------------


@pytest.fixture
def engines(monkeypatch):
    """(paddle 사용 가능, tesseract 사용 가능, OCR_ENGINE) 을 세팅한다."""

    def setup(paddle: bool, tesseract: bool, engine: str = "auto"):
        monkeypatch.setattr(ocr_paddle, "available", lambda: paddle)
        monkeypatch.setattr(vision, "_tesseract_available", lambda: tesseract)
        monkeypatch.setattr(vision, "OCR_ENGINE", engine)

    return setup


@pytest.mark.parametrize(
    ("paddle", "tess", "setting", "expected"),
    [
        (True, True, "auto", "paddle"),        # 둘 다 있으면 paddle
        (False, True, "auto", "tesseract"),    # paddle이 없으면 조용히 내려간다
        (True, True, "tesseract", "tesseract"),  # 명시하면 그대로 따른다
        (True, False, "paddle", "paddle"),
        (False, True, "paddle", ""),           # paddle만 쓰라 했으면 몰래 바꾸지 않는다
        (False, False, "auto", ""),
    ],
)
def test_active_engine(engines, paddle, tess, setting, expected):
    engines(paddle, tess, setting)
    assert vision.active_engine() == expected
    assert vision.ocr_available() is bool(expected)


def test_paddle_only_setting_reports_why_instead_of_silently_using_tesseract(engines, monkeypatch):
    engines(paddle=False, tesseract=True, engine="paddle")
    monkeypatch.setattr(ocr_paddle, "error", lambda: "paddlepaddle이 없습니다")
    text, err = vision.ocr_image(b"\x89PNG")
    assert text == ""
    assert "paddlepaddle이 없습니다" in err


def test_paddle_path_applies_the_same_low_confidence_filter(engines, monkeypatch):
    """엔진이 바뀌어도 잡음 줄을 걸러내는 규칙은 그대로여야 한다."""
    engines(paddle=True, tesseract=False, engine="auto")
    monkeypatch.setattr(vision, "_variants", lambda data: [("원본", data)])
    monkeypatch.setattr(ocr_paddle, "read", lambda png: [
        ("지금 신청하면 50% 할인", 96.0),
        ("은 ae [버", 21.0),          # 반쯤 읽힌 잡음 — 신뢰도로 걸러진다
        ("정품급 가방 판매합니다", 93.0),
    ])
    text, err = vision.ocr_image(b"\x89PNG")
    assert err == ""
    assert text == "지금 신청하면 50% 할인\n정품급 가방 판매합니다"


def test_paddle_path_falls_back_to_the_upscaled_variant(engines, monkeypatch):
    """원본에서 못 건지면 확대본을 한 번 더 본다. 작은 배너에서 이게 갈린다."""
    engines(paddle=True, tesseract=False, engine="auto")
    monkeypatch.setattr(vision, "_variants", lambda data: [("원본", b"small"), ("x2", b"big")])
    monkeypatch.setattr(ocr_paddle, "read", lambda png: (
        [] if png == b"small" else [("확대해서 읽어낸 문구입니다", 94.0)]
    ))
    text, err = vision.ocr_image(b"\x89PNG")
    assert text == "확대해서 읽어낸 문구입니다" and err == ""


def test_paddle_path_reports_when_nothing_is_readable(engines, monkeypatch):
    engines(paddle=True, tesseract=False, engine="auto")
    monkeypatch.setattr(vision, "_variants", lambda data: [("원본", data)])
    monkeypatch.setattr(ocr_paddle, "read", lambda png: [])
    text, err = vision.ocr_image(b"\x89PNG")
    assert text == "" and "찾지 못했" in err


# ---------------------------------------------------------------------------
# 사용자가 "무엇이 읽었는지" 볼 수 있어야 한다
# ---------------------------------------------------------------------------


def test_engine_name_reaches_the_response(engines, monkeypatch):
    """설정만 바꿔놓고 실제로는 예전 엔진이 도는 상황이 제일 나쁘다."""
    import base64

    from adpolicy.models import ImageAsset

    engines(paddle=True, tesseract=True, engine="auto")
    monkeypatch.setattr(vision, "ocr_image", lambda data: ("배너 문구", ""))

    asset = ImageAsset(url="https://ex.com/a.png", content_type="image/png",
                       bytes_len=9999, width=800, height=400,
                       data_b64=base64.b64encode(b"x").decode())
    vision.run_ocr([asset])
    assert asset.ocr_engine == "paddle"

    report, = vision.build_reports([asset], [])
    assert report.ocr_engine == "paddle"
    assert report.ocr_text == "배너 문구"


def test_healthz_reports_the_engine_actually_in_use(engines):
    """OCR_ENGINE=paddle로 켜 놓고 tesseract가 도는 걸 모르면 안 된다."""
    from fastapi.testclient import TestClient

    from adpolicy.main import app

    engines(paddle=False, tesseract=True, engine="paddle")
    with TestClient(app) as client:
        body = client.get("/healthz").json()
    assert body["ocr_engine_requested"] == "paddle"
    assert body["ocr_engine_active"] == ""
    assert body["ocr_note"]


# ---------------------------------------------------------------------------
# 빌드 때 모델을 못 받은 경우
#
# PaddleOCR은 '더 잘 읽는 선택지'이지 이 도구가 도는 조건이 아니다. 모델 CDN이
# 막힌 사내망에서 빌드가 통째로 실패하면 tesseract로 충분히 돌 수 있는 도구를
# 아예 못 쓰게 된다. 대신 **왜 못 받았는지는 반드시 보여야** 한다.
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_engine():
    """엔진 캐시를 앞뒤로 비운다.

    monkeypatch는 `_build`를 원래대로 돌려놓지만 `engine()`이 캐싱한 결과는
    그대로 남는다. 그러면 뒤에 오는 테스트가 이 가짜 엔진을 쓰게 된다 —
    실제로 test_vision 두 건이 이것 때문에 깨졌다.
    """
    ocr_paddle.reset()
    yield
    ocr_paddle.reset()


def test_the_build_note_reaches_healthz(tmp_path, monkeypatch, clean_engine):
    note = tmp_path / ".paddle_unavailable"
    note.write_text("모델을 받지 못했습니다. tesseract로 동작합니다", encoding="utf-8")
    monkeypatch.setattr(ocr_paddle, "BUILD_NOTE_PATH", str(note))
    ocr_paddle.reset()
    monkeypatch.setattr(ocr_paddle, "_build", lambda: (_ for _ in ()).throw(
        ImportError("No module named 'paddleocr'")))

    message = ocr_paddle.error()
    assert "빌드 단계" in message
    assert "tesseract로 동작" in message
    # 원래의 실패 이유도 같이 남아야 한다. 하나로 덮으면 진단이 어려워진다.
    assert "paddleocr" in message


def test_no_note_means_no_extra_noise(tmp_path, monkeypatch, clean_engine):
    monkeypatch.setattr(ocr_paddle, "BUILD_NOTE_PATH", str(tmp_path / "없음"))
    ocr_paddle.reset()
    monkeypatch.setattr(ocr_paddle, "_build", lambda: (_ for _ in ()).throw(
        ImportError("No module named 'paddleocr'")))
    assert "빌드 단계" not in ocr_paddle.error()


def test_a_working_engine_reports_nothing(tmp_path, monkeypatch, clean_engine):
    """빌드 노트가 없고 엔진도 멀쩡하면 조용해야 한다."""
    monkeypatch.setattr(ocr_paddle, "BUILD_NOTE_PATH", str(tmp_path / "없음"))
    ocr_paddle.reset()
    monkeypatch.setattr(ocr_paddle, "_build", lambda: object())
    assert ocr_paddle.error() == ""
