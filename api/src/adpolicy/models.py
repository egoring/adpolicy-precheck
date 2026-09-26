"""요청·응답 스키마.

설계 원칙 — 모든 지적(Finding)은 반드시 `evidence`를 가진다.
근거 없는 지적은 `analyzer.verify_evidence`에서 폐기된다.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Platform(str, Enum):
    GOOGLE_ADS = "google_ads"
    TIKTOK_ADS = "tiktok_ads"


class Severity(str, Enum):
    """이 광고가 나갈 수 있는가."""

    BLOCK = "block"      # 게재 거부
    WARN = "warn"        # 반려 가능성 있음, 수정 권장
    INFO = "info"        # 개선하면 좋음


class Enforcement(str, Enum):
    """위반이 **계정에** 어떤 결과로 이어지는가. 심각도와는 다른 축이다.

    광고 하나가 반려되는 것과 계정이 영구 정지되는 것은 광고주에게 완전히
    다른 사건인데, severity만으로는 구분되지 않았다. Google은 이 둘을 문서에서
    명확히 나눠 두었고, 각 정책 문서에 등급을 알려주는 정형 문장이 박혀 있다.

    SUSPEND  "정책 위반 발견 시 Google은 사전 경고 없이 즉시 해당 Google Ads
             계정을 정지하며 해당 광고주는 다시는 Google Ads를 통해 광고를
             운영할 수 없습니다." — 중대한 위반 10개가 여기 해당한다.
    STRIKE   경고 누적형. 주의 → 1차 경고(3일 일시정지) → 2차(7일) → 3차 정지.
    DISAPPROVE 광고 비승인. 누적되면 최소 7일 전 예고 후 정지될 수 있다.
    """

    SUSPEND = "suspend"
    STRIKE = "strike"
    DISAPPROVE = "disapprove"


ENFORCEMENT_LABEL = {
    Enforcement.SUSPEND: "계정 즉시 정지",
    Enforcement.STRIKE: "경고 누적 (3진 아웃)",
    Enforcement.DISAPPROVE: "광고 반려",
}


class Source(str, Enum):
    """지적이 어디서 나왔는지. 신뢰도 차이가 크므로 반드시 구분한다.

    아래로 갈수록 근거가 약하고, scoring에서 가중치도 낮아진다.
    """

    RULE = "rule"        # 결정적 룰셋 — 코드가 판정, 재현성 100%
    OCR = "ocr"          # 이미지에서 읽은 텍스트에 결정적 룰을 적용.
                         # 룰 자체는 결정적이지만 OCR이 오독할 수 있다.
    LLM = "llm"          # 모델 판단 — evidence 역검증을 통과한 것만
    VLM = "vlm"          # 이미지 자체에 대한 시각적 판단.
                         # **인용할 텍스트가 없어 역검증이 불가능하다.**
                         # 그래서 가장 낮은 가중치를 주고, 판정 대상 이미지
                         # URL을 반드시 함께 돌려줘 사람이 확인하게 한다.


class Finding(BaseModel):
    code: str = Field(description="정책 코드 (예: DATA-NO-PRIVACY-POLICY)")
    title: str
    severity: Severity
    enforcement: Enforcement = Field(
        default=Enforcement.DISAPPROVE,
        description="계정에 미치는 결과. 광고 반려와 계정 정지는 완전히 다른 사건이다.",
    )
    source: Source
    detail: str = Field(description="왜 문제인지")
    evidence: str = Field(
        default="",
        description="페이지·문구에서 실제로 발견된 근거. 룰 판정은 비어 있을 수 있다.",
    )
    fix: str = Field(default="", description="어떻게 고치면 되는지")
    image_url: str = Field(
        default="",
        description="이미지에서 나온 지적이면 어느 이미지인지. 사람이 직접 확인할 수 있어야 한다.",
    )
    image_urls: list[str] = Field(
        default_factory=list,
        description=(
            "같은 지적이 여러 이미지에서 나온 경우 전부. 병원 랜딩페이지처럼 배너 "
            "8장이 모두 같은 항목에 걸리면 카드를 8장 만드는 대신 여기에 모은다."
        ),
    )


class AccountRisk(BaseModel):
    """계정에 무슨 일이 생길 수 있는지. 반려 점수와는 별개의 축이다."""

    level: Enforcement = Field(
        default=Enforcement.DISAPPROVE, description="가장 높은 등급의 제재"
    )
    suspend_count: int = Field(default=0, description="즉시 정지급 항목 수")
    strike_count: int = Field(default=0, description="경고 누적급 항목 수")
    codes: list[str] = Field(default_factory=list, description="해당 항목 코드")
    note: str = Field(default="", description="사람이 읽을 설명")

    @property
    def label(self) -> str:
        return ENFORCEMENT_LABEL[self.level]


class ImageAsset(BaseModel):
    """페이지에서 내려받은 이미지 하나.

    실패도 상태로 다룬다 — 이미지 하나가 안 열린다고 점검 전체가 멈추면 안 된다.
    """

    url: str
    content_type: str = ""
    bytes_len: int = 0
    width: int = 0
    height: int = 0
    ocr_text: str = ""
    ocr_error: str = ""
    ocr_engine: str = ""
    fetch_error: str = ""
    data_b64: str = Field(default="", exclude=True)  # VLM 전달용, 응답에는 싣지 않는다

    @property
    def ok(self) -> bool:
        return not self.fetch_error and self.bytes_len > 0


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
    image_urls: list[str] = Field(default_factory=list)
    image_count: int = 0
    ocr_text: str = Field(
        default="",
        description="이미지에서 읽어낸 텍스트. verification_text에 합쳐져 역검증 대상이 된다.",
    )
    has_form: bool = False
    form_input_types: list[str] = Field(default_factory=list)
    form_text: str = Field(
        default="",
        description="폼 안쪽 텍스트·label·placeholder. 개인정보 수집 판정은 여기만 본다.",
    )
    fetch_error: str = ""

    @property
    def combined_text(self) -> str:
        """**페이지에서** 나온 텍스트. 결정적 룰이 보는 대상이다.

        ocr_text는 일부러 넣지 않는다. 넣으면 본문 룰이 배너 문구까지 잡아
        `source=rule`로 보고하게 되고, 어느 이미지에서 나왔는지가 사라진다.
        이미지 쪽은 `vision.check_image_text`가 이미지 단위로 따로 판정한다.
        """
        parts = [self.title, self.meta_description, self.text]
        parts += self.link_texts + self.image_alts
        return "\n".join(p for p in parts if p)

    @property
    def verification_text(self) -> str:
        """근거 역검증에 쓰는 텍스트 풀 — 페이지 + 이미지에서 읽은 글자.

        여기에 ocr_text가 들어가는 것이 중요하다. 그래야 "배너에 '100% 보장'이라고
        적혀 있다"는 모델의 주장을 실제 문자열과 대조할 수 있다. 이미지 기능을
        넣으면서 근거 역검증이 무력화되지 않게 하는 지점이다.
        """
        return f"{self.combined_text}\n{self.ocr_text}" if self.ocr_text \
            else self.combined_text


class CheckRequest(BaseModel):
    platform: Platform = Platform.GOOGLE_ADS
    url: HttpUrl
    ad_copy: str = Field(default="", max_length=5000, description="광고 문구 (선택)")
    use_llm: bool = Field(default=True, description="LLM 분석 사용 여부")
    headlines: list[str] = Field(
        default_factory=list,
        description=(
            "광고 제목을 하나씩. 넣으면 글자 수 한도를 판정합니다 — **한국어는 "
            "문자 한 개가 두 자로 계산되어 실질 15자**입니다. ad_copy 한 덩어리로는 "
            "어느 필드인지 알 수 없어 길이를 판정하지 않습니다."
        ),
        max_length=15,
    )
    descriptions: list[str] = Field(
        default_factory=list,
        description="광고 설명을 하나씩. 한도는 영문 90자 = 한글 45자입니다.",
        max_length=8,
    )
    check_images: bool = Field(
        default=True,
        description="이미지 속 텍스트를 OCR로 읽어 판정할지. GPU 불필요.",
    )
    expect_fingerprint: str = Field(
        default="",
        description=(
            "직전 점검의 content_fingerprint. 넣으면 그 사이 본문이 바뀌었는지 "
            "확인합니다. 심사 통과 뒤 페이지를 갈아끼우는 수법은 한 번의 점검으로는 "
            "절대 잡을 수 없습니다."
        ),
        max_length=64,
    )
    compare_with_last: bool = Field(
        default=False,
        description=(
            "지난 점검과 비교할지. 켜면 그 사이 본문이 바뀐 경우를 지적으로 올립니다. "
            "끄면 비교 정보만 보여주고 지적은 만들지 않습니다 — 오타를 고쳤다고 "
            "'계정 정지 위험'이 뜨면 안 되기 때문입니다."
        ),
    )
    probe_params: bool = Field(
        default=True,
        description=(
            "gclid·ttclid·utm을 붙였을 때 페이지가 달라지는지 확인할지. "
            "심사 크롤러는 광고를 클릭해서 오지 않으므로 파라미터 없는 쪽만 봅니다 — "
            "User-Agent 비교로는 잡히지 않는 축입니다. 요청이 4회 늘어납니다."
        ),
    )
    use_vlm: bool = Field(
        default=False,
        description=(
            "이미지 자체를 VLM으로 판정할지. 멀티모달 엔드포인트가 필요하고, "
            "근거 역검증이 불가능해 가중치가 가장 낮다. 기본 꺼짐."
        ),
    )
    ignore_codes: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "무시할 지적 코드. 근거를 갖춘 '업계 1위'처럼 알고 있는 오탐을 매번 "
            "보지 않게 한다. 무시한 지적은 점수·판정에서 빠지지만 suppressed로 "
            "그대로 돌려준다. 계정 정지·경고 누적급 코드는 무시할 수 없다."
        ),
    )

    @field_validator("ignore_codes")
    @classmethod
    def _known_and_ignorable(cls, codes: list[str]) -> list[str]:
        # policies가 이 모듈을 import하므로 여기서 늦게 가져온다.
        from .policies import POLICY_BY_CODE

        norm = list(dict.fromkeys(c.strip().upper() for c in codes if c.strip()))
        unknown = [c for c in norm if c not in POLICY_BY_CODE]
        if unknown:
            raise ValueError(f"알 수 없는 정책 코드: {', '.join(unknown)}")
        # 계정에 번지는 위반을 가릴 수 있으면 이 도구의 핵심이 무너진다.
        locked = [c for c in norm
                  if POLICY_BY_CODE[c].enforcement is not Enforcement.DISAPPROVE]
        if locked:
            raise ValueError(
                f"계정 정지·경고 누적급 항목은 무시할 수 없습니다: {', '.join(locked)}"
            )
        return norm


class ImageReport(BaseModel):
    """점검한 이미지 한 장에 대한 보고.

    지적이 없더라도 반드시 돌려준다. "읽었는데 문제가 없었다"와
    "아예 못 읽었다"는 사용자에게 완전히 다른 정보이고,
    OCR이 무엇을 읽었는지 보여줘야 결과를 신뢰하거나 반박할 수 있다.
    """

    url: str
    width: int = 0
    height: int = 0
    ocr_text: str = Field(default="", description="이미지에서 읽어낸 문구 (일부 잘릴 수 있음)")
    note: str = Field(default="", description="못 읽었거나 건너뛴 이유")
    finding_codes: list[str] = Field(
        default_factory=list, description="이 이미지에서 나온 지적 코드"
    )
    ocr_engine: str = Field(
        default="", description="실제로 읽은 OCR 엔진 (paddle | tesseract)"
    )


class CheckHistory(BaseModel):
    """지난 점검과의 차이. 고치고 다시 돌렸을 때 무엇이 나아졌는지 보여준다."""

    previous_at: float = Field(default=0.0, description="지난 점검 시각 (epoch 초)")
    previous_fingerprint: str = ""
    previous_score: int = 0
    score_delta: int = Field(default=0, description="점수 변화. 양수면 나아진 것")
    content_changed: bool = Field(
        default=False, description="지난 점검 이후 본문이 바뀌었는가"
    )
    resolved_codes: list[str] = Field(
        default_factory=list, description="지난번엔 있었는데 이번엔 없는 지적"
    )
    new_codes: list[str] = Field(
        default_factory=list, description="지난번엔 없었는데 이번에 생긴 지적"
    )
    note: str = ""


class CheckResponse(BaseModel):
    platform: Platform
    url: str
    final_url: str
    verdict: Literal["pass", "review", "fail"]
    score: int = Field(ge=0, le=100, description="광고 반려 위험. 100이 가장 안전")
    account_risk: AccountRisk = Field(
        default_factory=AccountRisk,
        description=(
            "계정 정지 위험. 반려 점수와 다른 축이다 — "
            "반려 20건보다 정지 1건이 치명적이다."
        ),
    )
    content_fingerprint: str = Field(
        default="",
        description=(
            "이번에 본 본문의 지문. 다음 점검 때 expect_fingerprint로 넘기면 "
            "그 사이 내용이 바뀌었는지 알 수 있습니다."
        ),
    )
    history: CheckHistory | None = Field(
        default=None,
        description="지난 점검과의 비교. 이 URL의 첫 점검이면 없습니다.",
    )
    summary: str
    findings: list[Finding]
    suppressed: list[Finding] = Field(
        default_factory=list,
        description="ignore_codes로 무시한 지적. 점수·판정에는 들어가지 않는다.",
    )
    stats: dict[str, int] = Field(default_factory=dict)
    images: list[ImageReport] = Field(
        default_factory=list, description="점검한 이미지와 거기서 읽어낸 문구"
    )
    llm_used: bool = False
    llm_note: str = ""
    vlm_used: bool = False
    vlm_note: str = Field(default="", description="이미지 자체 판정의 상태·건너뛴 이유")
