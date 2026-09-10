"""요청·응답 스키마.

설계 원칙 — 모든 지적(Finding)은 반드시 `evidence`를 가진다.
근거 없는 지적은 `analyzer.verify_evidence`에서 폐기된다.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Platform(str, Enum):
    GOOGLE_ADS = "google_ads"
    TIKTOK_ADS = "tiktok_ads"


class Severity(str, Enum):
    """심각도. 광고 심사에서 실제로 어떤 결과로 이어지는지 기준."""

    BLOCK = "block"      # 게재 거부 / 계정 정지 위험
    WARN = "warn"        # 반려 가능성 있음, 수정 권장
    INFO = "info"        # 개선하면 좋음


class Source(str, Enum):
    """지적이 어디서 나왔는지. 신뢰도 차이가 크므로 반드시 구분한다."""

    RULE = "rule"        # 결정적 룰셋 — 코드가 판정, 재현성 100%
    LLM = "llm"          # 모델 판단 — evidence 역검증을 통과한 것만


class Finding(BaseModel):
    code: str = Field(description="정책 코드 (예: GA-LP-PRIVACY)")
    title: str
    severity: Severity
    source: Source
    detail: str = Field(description="왜 문제인지")
    evidence: str = Field(
        default="",
        description="페이지·문구에서 실제로 발견된 근거. 룰 판정은 비어 있을 수 있다.",
    )
    fix: str = Field(default="", description="어떻게 고치면 되는지")


class PageSnapshot(BaseModel):
    """가져온 랜딩 페이지의 정규화된 스냅샷."""

    url: str
    final_url: str
    status_code: int
    title: str = ""
    meta_description: str = ""
    text: str = ""
    links: list[str] = Field(default_factory=list)
    link_texts: list[str] = Field(default_factory=list)
    image_alts: list[str] = Field(default_factory=list)
    image_count: int = 0
    has_form: bool = False
    form_input_types: list[str] = Field(default_factory=list)
    fetch_error: str = ""

    @property
    def combined_text(self) -> str:
        """evidence 역검증에 쓰는 전체 텍스트 풀."""
        parts = [self.title, self.meta_description, self.text]
        parts += self.link_texts + self.image_alts
        return "\n".join(p for p in parts if p)


class CheckRequest(BaseModel):
    platform: Platform = Platform.GOOGLE_ADS
    url: HttpUrl
    ad_copy: str = Field(default="", max_length=5000, description="광고 문구 (선택)")
    use_llm: bool = Field(default=True, description="LLM 분석 사용 여부")


class CheckResponse(BaseModel):
    platform: Platform
    url: str
    final_url: str
    verdict: Literal["pass", "review", "fail"]
    score: int = Field(ge=0, le=100, description="100이 가장 안전")
    summary: str
    findings: list[Finding]
    stats: dict[str, int] = Field(default_factory=dict)
    llm_used: bool = False
    llm_note: str = ""
