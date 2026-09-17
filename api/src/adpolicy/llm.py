"""OpenAI 호환 LLM 클라이언트.

vLLM · Ollama · OpenAI · Anthropic 호환 게이트웨이 어디든 붙는다.
로컬 모델을 기본으로 두되, 키를 넣으면 상용 API로 바꿀 수 있게 했다.

실패는 예외가 아니라 (텍스트, 오류) 튜플로 돌려준다 —
LLM이 죽어도 결정적 룰셋 결과는 사용자에게 나가야 하기 때문이다.
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")
DEFAULT_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))

_DNS_MARKERS = (
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "getaddrinfo",
)


def _is_dns_failure(exc: Exception) -> bool:
    """호스트 이름을 못 찾은 것인가, 포트가 닫힌 것인가.

    둘 다 httpx.ConnectError로 오지만 원인과 조치가 완전히 다르다.
    이름 해석 실패는 '컨테이너가 아예 없다'는 뜻이고,
    연결 거부는 '컨테이너는 있는데 아직 안 떴거나 죽었다'는 뜻이다.
    """
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, socket.gaierror):
            return True
        cause = cause.__cause__
    return any(m in str(exc).lower() for m in _DNS_MARKERS)


def connect_hint(base_url: str, exc: Exception) -> str:
    host = urlparse(base_url).hostname or base_url
    if _is_dns_failure(exc):
        # 어느 서비스가 없는지는 호스트명이 말해준다. 'llm'을 찾는데 없는 것과
        # 'vlm'을 찾는데 없는 것은 고칠 곳이 다르므로 그대로 되돌려준다.
        if host in ("llm", "vlm"):
            return (
                f"'{host}' 컨테이너가 없습니다. "
                f"`.env`의 COMPOSE_PROFILES에 `{host}`를 넣고 다시 띄우세요 "
                f"(예: COMPOSE_PROFILES=llm,vlm). "
                "VLM_BASE_URL만 채우고 프로필을 빼면 이 오류가 납니다."
            )
        return (
            f"호스트 '{host}'를 찾을 수 없습니다 — 그 주소에 컨테이너가 없습니다. "
            "compose가 띄운 서비스라면 서비스 이름을, "
            "호스트에서 도는 서버라면 host.docker.internal을 쓰세요."
        )
    return (
        f"LLM 서버({base_url})가 연결을 거부했습니다 — 호스트는 있는데 포트가 닫혀 있습니다. "
        "모델 로딩 중이거나(첫 기동에 1~3분) 기동에 실패한 경우입니다. "
        "`docker compose logs llm | tail -30`으로 확인하세요."
    )


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.api_key = api_key or DEFAULT_API_KEY
        self.timeout = timeout or DEFAULT_TIMEOUT

    async def complete(
        self, system: str, user: str, *, max_tokens: int = 1600, temperature: float = 0.1
    ) -> tuple[str, str]:
        """(응답 텍스트, 오류 메시지). 성공하면 오류는 빈 문자열."""
        return await self.complete_messages(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def complete_messages(
        self, messages: list[dict], *, max_tokens: int = 1600, temperature: float = 0.1
    ) -> tuple[str, str]:
        """messages를 그대로 보낸다.

        content가 문자열이 아니라 파트 배열이어도 된다 — 멀티모달(image_url)
        요청이 이 경로로 나간다. 오류 처리는 텍스트 요청과 완전히 같다.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                if resp.status_code != 200:
                    return "", (
                        f"LLM 응답 오류 {resp.status_code}. "
                        f"LLM_BASE_URL({self.base_url})과 모델({self.model})을 확인하세요."
                    )
                data = resp.json()
                content = data["choices"][0]["message"].get("content")
                if not content:
                    # 추론형 모델이 reasoning_content에만 쓰거나, max_tokens에서
                    # 잘려 content가 비는 경우가 있다. 조용히 넘기면 findings가
                    # 통째로 사라져 "LLM이 아무것도 못 찾았다"로 보인다.
                    return "", (
                        "LLM이 빈 응답을 반환했습니다. "
                        f"모델({self.model})이 chat completions를 지원하는지, "
                        "max_tokens가 충분한지 확인하세요."
                    )
                return content, ""
        except httpx.ConnectError as exc:
            return "", connect_hint(self.base_url, exc)
        except httpx.TimeoutException:
            return "", f"LLM 응답 시간 초과 ({self.timeout:.0f}s). LLM_TIMEOUT을 늘려보세요."
        except httpx.HTTPError as exc:
            # ReadError·RemoteProtocolError 등. 여기서 막지 않으면 예외가
            # 그대로 올라가 API가 500을 뱉고, 룰셋 결과까지 같이 죽는다.
            return "", f"LLM 통신 오류: {type(exc).__name__}. LLM_BASE_URL({self.base_url}) 확인."
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return "", f"LLM 응답 형식이 올바르지 않습니다: {type(exc).__name__}"
