"""OpenAI 호환 LLM 클라이언트.

vLLM · Ollama · OpenAI · Anthropic 호환 게이트웨이 어디든 붙는다.
로컬 모델을 기본으로 두되, 키를 넣으면 상용 API로 바꿀 수 있게 했다.

실패는 예외가 아니라 (텍스트, 오류) 튜플로 돌려준다 —
LLM이 죽어도 결정적 룰셋 결과는 사용자에게 나가야 하기 때문이다.
"""

from __future__ import annotations

import os

import httpx

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")
DEFAULT_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))


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
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
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
                return data["choices"][0]["message"]["content"], ""
        except httpx.ConnectError:
            return "", (
                f"LLM 서버에 연결할 수 없습니다 ({self.base_url}). "
                "서버가 떠 있는지 확인하거나 use_llm=false로 룰셋만 실행하세요."
            )
        except httpx.TimeoutException:
            return "", "LLM 응답 시간 초과"
        except (KeyError, ValueError) as exc:
            return "", f"LLM 응답 형식이 올바르지 않습니다: {type(exc).__name__}"
