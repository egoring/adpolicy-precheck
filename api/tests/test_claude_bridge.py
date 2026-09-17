"""Claude CLI 다리 회귀 테스트.

이 다리로 들어오는 프롬프트에는 **공격자가 통제하는 텍스트**(점검 대상
랜딩페이지 본문)가 그대로 실린다. 그래서 여기서 지키는 것은 대부분
"열어주지 않는 것"이다 — 도구, 임의 URL, 잘린 프롬프트.
"""

from __future__ import annotations

import base64
import json
import os

import claude_bridge as cb
import pytest


def data_url(raw: bytes = b"\x89PNG\r\n\x1a\n", mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


# ---------------------------------------------------------------------------
# 이미지 입력 — 여기가 제일 위험하다
# ---------------------------------------------------------------------------


def test_data_url_is_decoded():
    mime, raw = cb.decode_data_url(data_url(b"hello"))
    assert mime == "image/png" and raw == b"hello"


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "https://example.com/a.png",
    "file:///etc/passwd",
    "/etc/shadow",
])
def test_non_data_urls_are_refused(url):
    """http(s)를 그대로 넘기면 CLI가 그 주소를 직접 가져간다 —
    api 쪽 SSRF 가드를 통째로 우회하는 통로다."""
    with pytest.raises(cb.BridgeError):
        cb.decode_data_url(url)


@pytest.mark.parametrize("url", [
    "data:image/png;base64,!!!not-base64!!!",
    "data:image/png;base64,",
])
def test_broken_payloads_are_refused(url):
    with pytest.raises(cb.BridgeError):
        cb.decode_data_url(url)


def test_images_are_written_with_a_matching_extension(tmp_path):
    paths = cb.write_images(
        [data_url(b"a" * 20, "image/jpeg"), data_url(b"b" * 20, "image/png")],
        str(tmp_path),
    )
    assert [p.rsplit(".", 1)[-1] for p in paths] == ["jpg", "png"]
    assert all((tmp_path / p.rsplit("/", 1)[-1]).exists() for p in paths)


# ---------------------------------------------------------------------------
# messages → 프롬프트
# ---------------------------------------------------------------------------


def test_system_is_separated_and_turns_are_joined():
    system, user, images = cb.build_prompt([
        {"role": "system", "content": "너는 광고 심사관이다."},
        {"role": "user", "content": "이 페이지를 판정해라."},
    ])
    assert system == "너는 광고 심사관이다."
    assert user == "이 페이지를 판정해라."
    assert images == []


def test_multimodal_parts_are_split_into_text_and_images():
    system, user, images = cb.build_prompt([
        {"role": "system", "content": "심사관"},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url()}},
            {"type": "text", "text": "이 이미지를 판정해라."},
        ]},
    ])
    assert user == "이 이미지를 판정해라."
    assert len(images) == 1 and images[0].startswith("data:image/png")


def test_empty_messages_are_rejected():
    for bad in ([], None, "nope"):
        with pytest.raises(cb.BridgeError):
            cb.build_prompt(bad)


def test_image_paths_are_named_in_the_prompt():
    """경로를 안 적으면 Read를 열어줘도 무엇을 열지 모른다."""
    out = cb.compose_stdin("시스템", "판정해라", ["/tmp/x/image_0.png"])
    assert "/tmp/x/image_0.png" in out
    assert "시스템" in out and "판정해라" in out


def test_prompt_is_not_truncated_for_long_pages():
    """윈도우 명령줄은 약 8191자에서 잘린다. stdin으로 넣으므로 온전해야 한다."""
    body = "가" * 50_000
    out = cb.compose_stdin("", body, [])
    assert len(out) >= 50_000 and out.endswith("가")


# ---------------------------------------------------------------------------
# 실행 인자 — 필요할 때만 도구를 연다
# ---------------------------------------------------------------------------


def test_text_requests_get_no_tools_at_all():
    """도구를 막는 진짜 장치는 --allowedTools를 주지 않는 것이다."""
    argv = cb.build_argv("sonnet", has_images=False, cli="claude")
    assert "--allowedTools" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"


def test_text_requests_get_room_to_finish_a_long_answer():
    """max-turns 1로 두었더니 긴 정책 분석에서 error_max_turns가 나
    LLM 단계가 통째로 죽었다. 실제로 겪은 실패다."""
    argv = cb.build_argv("sonnet", has_images=False, cli="claude")
    assert int(argv[argv.index("--max-turns") + 1]) >= 2


def test_image_requests_open_read_and_nothing_else():
    argv = cb.build_argv("sonnet", has_images=True, cli="claude")
    assert argv[argv.index("--allowedTools") + 1] == "Read"
    # 여유는 주되 상한은 둔다 — 도구 루프가 무한히 돌면 안 된다.
    assert int(argv[argv.index("--max-turns") + 1]) <= 12


def test_max_turns_failure_names_the_knob_to_turn():
    with pytest.raises(cb.BridgeError) as exc:
        cb.parse_cli_json(json.dumps({"subtype": "error_max_turns", "result": ""}))
    assert "CLAUDE_BRIDGE_MAX_TURNS" in str(exc.value)


def test_model_reaches_the_command_line():
    argv = cb.build_argv("opus", has_images=False, cli="/usr/bin/claude")
    assert argv[0] == "/usr/bin/claude"
    assert argv[argv.index("--model") + 1] == "opus"


# ---------------------------------------------------------------------------
# CLI 출력 파싱
# ---------------------------------------------------------------------------


def test_result_is_extracted():
    out = json.dumps({"type": "result", "is_error": False, "result": "판정 결과"})
    text, model, _usage = cb.parse_cli_json(out)
    assert (text, model) == ("판정 결과", "")


def test_warning_lines_before_the_json_are_tolerated():
    out = "npm warn 어쩌고\n" + json.dumps({"is_error": False, "result": "ok"})
    assert cb.parse_cli_json(out)[:2] == ("ok", "")


def test_the_model_that_actually_answered_is_reported():
    """별칭을 그대로 되돌려주면 증거가 못 된다 — 무엇이 답했든 'sonnet'이다.

    Claude Code는 제목 생성 같은 잡일에 haiku를 같이 쓴다.
    """
    out = json.dumps({
        "is_error": False,
        "result": "판정 결과",
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"inputTokens": 500, "outputTokens": 12},
            "claude-sonnet-5": {"inputTokens": 2000, "outputTokens": 940},
        },
    })
    assert cb.parse_cli_json(out, "sonnet")[:2] == ("판정 결과", "claude-sonnet-5")


def test_short_answers_do_not_credit_the_housekeeping_model():
    """실제로 여기서 틀렸다.

    답이 "2" 한 글자면 판정 모델의 **출력** 토큰은 3인데, 제목을 지어내는
    haiku 쪽이 12다. 출력만 보면 haiku가 답한 것으로 보고된다. 캐시 읽기까지
    포함한 총량으로 봐야 실제로 일한 쪽이 나온다.
    """
    out = json.dumps({
        "is_error": False,
        "result": "2",
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"inputTokens": 300, "outputTokens": 12},
            "claude-sonnet-5": {
                "inputTokens": 2, "outputTokens": 3,
                "cacheReadInputTokens": 32556, "cacheCreationInputTokens": 16695,
            },
        },
    })
    assert cb.parse_cli_json(out, "sonnet")[1] == "claude-sonnet-5"


@pytest.mark.parametrize("usage", [None, {}, "쓰레기", {"x": "쓰레기"}])
def test_model_falls_back_to_the_alias_when_usage_is_unusable(usage):
    payload = {"is_error": False, "result": "ok"}
    if usage is not None:
        payload["modelUsage"] = usage
    _text, model, _usage = cb.parse_cli_json(json.dumps(payload), "sonnet")
    assert model in ("sonnet", "x")


@pytest.mark.parametrize("payload", [
    {"is_error": True, "result": "인증 실패"},
    {"subtype": "error_max_turns", "result": ""},
    {"is_error": False, "result": ""},
    {"is_error": False},
])
def test_failures_are_reported_not_swallowed(payload):
    """빈 응답을 조용히 넘기면 '지적 없음'으로 보인다 — 최악이다."""
    with pytest.raises(cb.BridgeError):
        cb.parse_cli_json(json.dumps(payload))


def test_garbage_output_is_reported():
    with pytest.raises(cb.BridgeError):
        cb.parse_cli_json("Segmentation fault")
    with pytest.raises(cb.BridgeError):
        cb.parse_cli_json("")


# ---------------------------------------------------------------------------
# 응답 모양 — api 클라이언트가 이 모양만 안다
# ---------------------------------------------------------------------------


def test_response_is_an_openai_chat_completion():
    r = cb.shape_response("내용", "sonnet")
    assert r["object"] == "chat.completion"
    assert r["choices"][0]["message"] == {"role": "assistant", "content": "내용"}
    assert r["choices"][0]["finish_reason"] == "stop"
    # usage를 빼면 이걸 읽는 클라이언트가 KeyError로 죽는다
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(r["usage"])


def test_real_token_counts_reach_the_response():
    """예전에는 0으로 채워 보냈다. 그러면 구독을 얼마나 쓰는지 알 수 없다."""
    usage = cb.usage_of({
        "total_cost_usd": 0.0731,
        "modelUsage": {
            "claude-sonnet-5": {
                "inputTokens": 2, "outputTokens": 3,
                "cacheReadInputTokens": 32556, "cacheCreationInputTokens": 16695,
            },
            "claude-haiku-4-5": {"inputTokens": 300, "outputTokens": 12},
        },
    })
    # 캐시 읽기를 빼고 세면 49253 대신 317이 된다 — 사용량을 150배 낮잡는다
    assert usage["total_tokens"] == 2 + 3 + 32556 + 16695 + 300 + 12
    assert usage["cache_read_tokens"] == 32556
    assert usage["cost_usd"] == 0.0731

    r = cb.shape_response("내용", "claude-sonnet-5", usage)
    assert r["usage"]["total_tokens"] == usage["total_tokens"]
    assert r["usage"]["cost_usd"] == 0.0731


def test_usage_survives_a_cli_that_reports_nothing():
    usage = cb.usage_of({})
    assert usage["total_tokens"] == 0 and usage["cost_usd"] == 0.0
    assert cb.shape_response("내용", "sonnet", usage)["usage"]["total_tokens"] == 0


def test_broken_usage_numbers_do_not_crash_the_request():
    usage = cb.usage_of({
        "total_cost_usd": "많이",
        "modelUsage": {"m": {"inputTokens": None, "outputTokens": "?"}, "n": "쓰레기"},
    })
    assert usage["total_tokens"] == 0 and usage["cost_usd"] == 0.0


def test_the_ledger_aggregates_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(cb, "_ledger", cb.deque(maxlen=50))
    for i in range(3):
        cb.record_usage({
            "ts": 1_700_000_000 + i, "model": "claude-sonnet-5",
            "total_tokens": 1000, "input_tokens": 100, "output_tokens": 200,
            "cost_usd": 0.01, "duration_ms": 500, "images": 1,
        })
    cb.record_usage({"ts": 1_700_000_009, "model": "claude-sonnet-5",
                     "error": "타임아웃", "duration_ms": 100})

    rep = cb.usage_report()
    assert rep["totals"]["calls"] == 4
    # 실패한 호출도 센다 — 구독은 소진되고, 나중에 되짚으려면 기록이 있어야 한다
    assert rep["totals"]["errors"] == 1
    assert rep["totals"]["total_tokens"] == 3000
    assert rep["totals"]["cost_usd"] == 0.03
    assert rep["by_model"]["claude-sonnet-5"]["calls"] == 4
    # 최신이 위로
    assert rep["recent"][0]["ts"] == 1_700_000_009


def test_the_ledger_can_be_filtered_by_time(monkeypatch, tmp_path):
    import time as _time

    monkeypatch.setattr(cb, "USAGE_LOG", str(tmp_path / "u.jsonl"))
    monkeypatch.setattr(cb, "_ledger", cb.deque(maxlen=50))
    now = _time.time()
    cb.record_usage({"ts": now - 86_400 * 3, "total_tokens": 500})   # 3일 전
    cb.record_usage({"ts": now - 60, "total_tokens": 700})           # 1분 전

    assert cb.usage_report()["totals"]["total_tokens"] == 1200
    assert cb.usage_report(since_hours=1)["totals"]["total_tokens"] == 700


def test_a_failed_ledger_write_does_not_break_the_request(monkeypatch):
    """디스크가 차도 판정은 나가야 한다."""
    monkeypatch.setattr(cb, "USAGE_LOG", "/이런/경로는/없다/usage.jsonl")
    monkeypatch.setattr(cb, "_ledger", cb.deque(maxlen=5))
    cb.record_usage({"ts": 1.0, "total_tokens": 10})
    assert cb.usage_report()["totals"]["calls"] == 1


def test_vllm_model_names_fall_back_to_the_configured_claude_model(monkeypatch):
    """`.env`에 Qwen/... 이 남아 있어도 동작해야 한다. claude는 그런 모델을 모른다."""
    seen = {}

    def fake_run(system, user, images, model):
        seen["model"] = model
        return "ok", model, {}

    monkeypatch.setattr(cb, "run_claude", fake_run)
    monkeypatch.setattr(cb, "DEFAULT_MODEL", "sonnet")
    cb.handle_completion({
        "model": "Qwen/Qwen2.5-7B-Instruct-AWQ",
        "messages": [{"role": "user", "content": "안녕"}],
    })
    assert seen["model"] == "sonnet"


def test_completion_end_to_end_with_a_fake_cli(monkeypatch):
    calls = {}

    def fake_run(argv, input, capture_output, timeout, cwd, check):
        calls["argv"] = argv
        calls["stdin"] = input.decode()
        calls["cwd"] = cwd

        class P:
            returncode = 0
            stdout = json.dumps({
                "is_error": False,
                "result": "판정 완료",
                "modelUsage": {"claude-sonnet-5": {"outputTokens": 300}},
            }).encode()
            stderr = b""

        return P()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    monkeypatch.setattr(cb, "find_cli", lambda: "/usr/bin/claude")

    out = cb.handle_completion({
        "model": "sonnet",
        "messages": [
            {"role": "system", "content": "너는 광고 심사관이다."},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url()}},
                {"type": "text", "text": "판정해라."},
            ]},
        ],
    })

    assert out["choices"][0]["message"]["content"] == "판정 완료"
    # 요청은 'sonnet' 이었지만 응답에는 실제로 답한 모델이 실린다
    assert out["model"] == "claude-sonnet-5"
    # 이미지가 있으니 Read만 열렸다
    assert calls["argv"][calls["argv"].index("--allowedTools") + 1] == "Read"
    # 작업 디렉터리가 요청 전용 임시 폴더로 못박혔다 — 프롬프트에 실린 남의
    # 페이지 본문이 Read를 꼬드겨도 여기 밖은 못 본다
    assert "adpolicy-bridge-" in calls["cwd"]
    assert "너는 광고 심사관이다." in calls["stdin"]
    assert "image_0.png" in calls["stdin"]


def test_cli_crash_is_turned_into_an_error_not_an_empty_answer(monkeypatch):
    def fake_run(argv, input, capture_output, timeout, cwd, check):
        class P:
            returncode = 1
            stdout = b""
            stderr = "로그인이 필요합니다".encode()

        return P()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    monkeypatch.setattr(cb, "find_cli", lambda: "/usr/bin/claude")
    with pytest.raises(cb.BridgeError) as exc:
        cb.handle_completion({"messages": [{"role": "user", "content": "안녕"}]})
    assert "로그인이 필요합니다" in str(exc.value)


# ---------------------------------------------------------------------------
# 설정 읽기 — 다리는 호스트에서 돌아서 compose가 .env를 넣어 주지 않는다
# ---------------------------------------------------------------------------


def test_dotenv_is_read_but_never_overrides_the_shell(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# 주석\n"
        "CLAUDE_BRIDGE_TOKEN=from-file\n"
        "CLAUDE_BRIDGE_PORT=8787   # 뒤에 붙은 주석은 값이 아니다\n"
        "CLAUDE_BRIDGE_MODEL=\"opus\"\n"
        "쓰레기줄\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CLAUDE_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("CLAUDE_BRIDGE_MODEL", "sonnet")  # 셸이 이겨야 한다

    cb.load_dotenv(str(env))

    assert os.environ["CLAUDE_BRIDGE_TOKEN"] == "from-file"
    assert os.environ["CLAUDE_BRIDGE_PORT"] == "8787"
    assert os.environ["CLAUDE_BRIDGE_MODEL"] == "sonnet"


def test_missing_dotenv_is_not_an_error(tmp_path):
    cb.load_dotenv(str(tmp_path / "없는파일.env"))


def test_timeout_is_reported_with_the_knob_to_turn(monkeypatch):
    import subprocess as sp

    def fake_run(*a, **k):
        raise sp.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    monkeypatch.setattr(cb, "find_cli", lambda: "/usr/bin/claude")
    with pytest.raises(cb.BridgeError) as exc:
        cb.handle_completion({"messages": [{"role": "user", "content": "안녕"}]})
    assert exc.value.status == 504
    assert "CLAUDE_BRIDGE_TIMEOUT" in str(exc.value)
