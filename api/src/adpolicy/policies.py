"""정책 카탈로그 — Google Ads 공식 정책 분류를 따른다.

각 항목은 공식 정책 문서의 실제 분류·명칭에 매핑되어 있고 `source`에 출처를 둔다.
임의로 만든 이름이 아니라 심사에 실제로 쓰이는 용어를 쓰는 것이 목적이다.

출처
  정책 개요        https://support.google.com/adspolicy/answer/6008942
  방문 페이지 요건  https://support.google.com/adspolicy/answer/6368661
  허위 진술        https://support.google.com/adspolicy/answer/6020955
  광고 네트워크 악용 https://support.google.com/adspolicy/answer/6020954

**주의** — 정책은 수시로 개정된다. 이 카탈로그는 작성 시점(2026-09) 기준이며
최종 판단은 위 공식 문서를 따라야 한다. TikTok 항목은 별도 정책 문서 기준이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Platform, Severity

POLICY_DOCS = {
    "overview": "https://support.google.com/adspolicy/answer/6008942",
    "destination": "https://support.google.com/adspolicy/answer/6368661",
    "misrepresentation": "https://support.google.com/adspolicy/answer/6020955",
    "abuse": "https://support.google.com/adspolicy/answer/6020954",
}


@dataclass(frozen=True)
class PolicyItem:
    code: str
    title: str
    category: str          # 공식 상위 분류
    official_name: str     # 공식 정책 문서상의 항목명
    severity: Severity
    description: str
    fix: str
    source: str = POLICY_DOCS["overview"]
    platforms: tuple[Platform, ...] = (Platform.GOOGLE_ADS, Platform.TIKTOK_ADS)


# ---------------------------------------------------------------------------
# 방문 페이지 요건 (Editorial and technical → Destination requirements)
# ---------------------------------------------------------------------------

DESTINATION_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="DEST-NOT-WORKING",
        title="방문 페이지 작동 불가",
        category="편집 및 기술 요건",
        official_name="Destination not working",
        severity=Severity.BLOCK,
        description=(
            "일반적인 브라우저·기기에서 페이지가 열리지 않거나 HTTP 오류를 반환한다. "
            "즉시 게재 거부 사유다."
        ),
        fix="URL과 서버 상태를 확인하세요. 리디렉션 체인도 점검이 필요합니다.",
        source=POLICY_DOCS["destination"],
    ),
    PolicyItem(
        code="DEST-MISMATCH",
        title="표시 URL과 최종 도착지 불일치",
        category="편집 및 기술 요건",
        official_name="Destination mismatch",
        severity=Severity.WARN,
        description=(
            "표시 URL과 최종 도착 도메인이 일치해야 한다. 다른 도메인으로의 "
            "리디렉션, 부적절한 서브도메인 사용이 여기 해당한다."
        ),
        fix="광고의 표시 URL과 최종 도착 도메인을 일치시키세요.",
        source=POLICY_DOCS["destination"],
    ),
    PolicyItem(
        code="DEST-NOT-CRAWLABLE",
        title="AdsBot 크롤링 차단",
        category="편집 및 기술 요건",
        official_name="Destination not crawlable",
        severity=Severity.BLOCK,
        description=(
            "robots.txt가 Google AdsBot의 접근을 막고 있다. 심사 시스템이 "
            "콘텐츠를 확인할 수 없어 거부된다. **의도치 않게 발생하는 경우가 매우 많다** — "
            "SEO 목적으로 크롤러를 막다가 AdsBot까지 함께 막히는 사례가 대표적이다."
        ),
        fix=(
            "robots.txt에서 AdsBot-Google, AdsBot-Google-Mobile을 허용하세요. "
            "AdsBot은 전역 User-agent:* 규칙을 따르지 않으므로 별도 명시가 필요합니다."
        ),
        source=POLICY_DOCS["destination"],
        platforms=(Platform.GOOGLE_ADS,),
    ),
    PolicyItem(
        code="DEST-INSUFFICIENT-CONTENT",
        title="독자적 콘텐츠 부족",
        category="편집 및 기술 요건",
        official_name="Insufficient original content",
        severity=Severity.WARN,
        description=(
            "광고 노출을 주목적으로 만들어졌거나, 독자적 가치가 없거나, "
            "단순 리디렉션 역할만 하는 페이지는 거부된다."
        ),
        fix="제품·서비스 설명, 이용 방법, FAQ 등 실질적인 내용을 채우세요.",
        source=POLICY_DOCS["destination"],
    ),
    PolicyItem(
        code="DEST-UNACCEPTABLE-URL",
        title="사용할 수 없는 URL 형식",
        category="편집 및 기술 요건",
        official_name="Unacceptable URL",
        severity=Severity.WARN,
        description=(
            "비표준 문법, IP 주소를 그대로 노출한 URL, 허용되지 않는 문자가 "
            "포함된 URL은 거부된다."
        ),
        fix="정상적인 도메인 기반 URL을 사용하세요.",
        source=POLICY_DOCS["destination"],
    ),
    PolicyItem(
        code="DEST-AUTO-DOWNLOAD",
        title="자동 다운로드 유발",
        category="편집 및 기술 요건",
        official_name="Destination experience",
        severity=Severity.BLOCK,
        description=(
            "페이지 진입 시 파일 다운로드가 자동으로 시작되면 "
            "방문 페이지 경험 위반으로 거부된다."
        ),
        fix="사용자가 명시적으로 클릭했을 때만 다운로드가 시작되게 하세요.",
        source=POLICY_DOCS["destination"],
    ),
]


# ---------------------------------------------------------------------------
# 광고 네트워크 악용 (Prohibited practices → Abusing the ad network)
# ---------------------------------------------------------------------------

ABUSE_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="ABUSE-CLOAKING",
        title="콘텐츠 분기 정황 (클로킹 의심)",
        category="금지된 행위",
        official_name="Abusing the ad network — evasive ad content",
        severity=Severity.BLOCK,
        description=(
            "클라이언트에 따라 서로 다른 콘텐츠를 제공하고 있다. 심사 회피 목적이면 "
            "계정 영구 정지 사유이며, **의도치 않은 경우도 동일하게 제재된다** — "
            "지역 리디렉션, 봇 차단 WAF, JS 전용 렌더링이 흔한 원인이다."
        ),
        fix=(
            "모든 클라이언트에 동일한 콘텐츠를 제공하세요. WAF·CDN의 봇 차단 규칙, "
            "지역 리디렉션, User-Agent 분기 로직을 점검해야 합니다."
        ),
        source=POLICY_DOCS["abuse"],
    ),
    PolicyItem(
        code="ABUSE-UA-BRANCHING",
        title="User-Agent 분기 스크립트 감지",
        category="금지된 행위",
        official_name="Abusing the ad network — circumventing systems",
        severity=Severity.WARN,
        description=(
            "페이지 스크립트가 User-Agent를 검사해 동작을 바꾸고 있다. "
            "정당한 용도(모바일 대응)일 수 있으나, 심사 시스템에 다른 콘텐츠가 "
            "노출되지 않는지 확인이 필요하다."
        ),
        fix="UA 분기가 콘텐츠 자체를 바꾸지 않는지 확인하세요. 반응형 CSS를 권장합니다.",
        source=POLICY_DOCS["abuse"],
    ),
]


# ---------------------------------------------------------------------------
# 허위 진술 (Prohibited practices → Misrepresentation)
# ---------------------------------------------------------------------------

MISREPRESENTATION_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="MIS-UNRELIABLE-CLAIMS",
        title="신뢰할 수 없는 주장",
        category="금지된 행위",
        official_name="Unreliable claims",
        severity=Severity.BLOCK,
        description=(
            "부정확한 주장이나, 일어나기 어려운 결과를 유력한 결과인 것처럼 "
            "제시해 사용자를 유인하는 표현은 금지된다."
        ),
        fix="'개인차가 있습니다' 등 한정 표현으로 바꾸거나 근거를 제시하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-SUPERLATIVE",
        title="근거 없는 최상급 표현",
        category="금지된 행위",
        official_name="Unreliable claims",
        severity=Severity.WARN,
        description="'업계 1위', '최고', '유일' 등은 객관적 출처 없이 사용하면 반려될 수 있다.",
        fix="공신력 있는 출처와 기준 시점을 함께 표기하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-DISHONEST-PRICING",
        title="불투명한 가격 표시",
        category="금지된 행위",
        official_name="Dishonest pricing practices",
        severity=Severity.WARN,
        description=(
            "구매 전후로 사용자가 부담할 결제 방식과 총비용을 명확히 공개해야 한다. "
            "비용에 대해 잘못된 인상을 주는 가격 표시는 금지된다."
        ),
        fix="가격, 배송비, 정기결제 여부, 환불 조건을 페이지에 명시하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-CLICKBAIT",
        title="클릭베이트·선정적 유인",
        category="금지된 행위",
        official_name="Clickbait ads",
        severity=Severity.WARN,
        description=(
            "트래픽 유도를 위한 클릭베이트 기법이나 선정적 문구·이미지는 금지된다. "
            "허위 희소성('단 1자리 남음')도 여기 해당한다."
        ),
        fix="실제 재고·기간과 일치하지 않는 긴급성 표현을 제거하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-NEGATIVE-LIFE-EVENTS",
        title="부정적 생애 사건 이용",
        category="금지된 행위",
        official_name="Clickbait ads — negative life events",
        severity=Severity.BLOCK,
        description=(
            "사망·사고·질병·체포·파산 등 부정적 생애 사건을 이용해 "
            "행동을 압박하는 광고는 금지된다."
        ),
        fix="개인의 불행을 지목하는 표현 대신 일반적 서술로 바꾸세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-BUSINESS-IDENTITY",
        title="사업자 정보 불명확",
        category="금지된 행위",
        official_name="Misleading representation",
        severity=Severity.WARN,
        description=(
            "신원·소속·자격에 대한 중요 정보를 누락하거나 불명확하게 하는 것은 금지된다. "
            "국내 전자상거래법상 사업자 정보 표시 의무와도 연결된다."
        ),
        fix="푸터에 상호·사업자등록번호·연락처를 표기하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-UNCLEAR-RELEVANCE",
        title="광고와 방문 페이지 관련성 부족",
        category="금지된 행위",
        official_name="Unclear relevance",
        severity=Severity.WARN,
        description=(
            "광고 내용이 방문 페이지와 관련이 없으면 거부된다. "
            "광고 문구의 핵심 키워드가 페이지에서 확인되지 않는 상태다."
        ),
        fix="광고 문구의 핵심 내용이 방문 페이지에도 드러나게 하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
    PolicyItem(
        code="MIS-UNAVAILABLE-OFFER",
        title="약속한 혜택을 페이지에서 찾을 수 없음",
        category="금지된 행위",
        official_name="Unavailable offers",
        severity=Severity.WARN,
        description=(
            "광고에서 약속한 제품·서비스·프로모션이 방문 페이지에 없거나 "
            "쉽게 찾을 수 없으면 금지된다."
        ),
        fix="광고에서 언급한 할인·혜택을 방문 페이지에 명확히 표시하세요.",
        source=POLICY_DOCS["misrepresentation"],
    ),
]


# ---------------------------------------------------------------------------
# 데이터 수집 및 사용 (Prohibited practices → Data collection and use)
# ---------------------------------------------------------------------------

DATA_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="DATA-NO-PRIVACY-POLICY",
        title="개인정보처리방침 없음",
        category="금지된 행위",
        official_name="Data collection and use",
        severity=Severity.BLOCK,
        description=(
            "개인정보를 수집하면서 개인정보처리방침을 제공하지 않는 것은 "
            "데이터 수집 정책 위반이다."
        ),
        fix="푸터에 개인정보처리방침 페이지 링크를 추가하세요.",
    ),
    PolicyItem(
        code="DATA-INSECURE-COLLECTION",
        title="비보안 연결에서 개인정보 수집",
        category="금지된 행위",
        official_name="Data collection and use",
        severity=Severity.BLOCK,
        description="개인정보를 수집하는 페이지가 HTTPS를 쓰지 않는다.",
        fix="TLS 인증서를 적용하고 HTTPS로 전환하세요.",
    ),
]


# ---------------------------------------------------------------------------
# 금지 / 제한 콘텐츠 (Prohibited content · Restricted content)
# ---------------------------------------------------------------------------

CONTENT_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="PROHIB-COUNTERFEIT",
        title="위조 상품",
        category="금지된 콘텐츠",
        official_name="Counterfeit goods",
        severity=Severity.BLOCK,
        description="'정품급', '이미테이션' 등 모조품 판매 정황은 즉시 계정 정지 사유다.",
        fix="해당 표현과 상품을 제거하세요.",
    ),
    PolicyItem(
        code="RESTRICT-HEALTHCARE",
        title="의약품·의료 관련 제한",
        category="제한된 콘텐츠",
        official_name="Healthcare and medicines",
        severity=Severity.BLOCK,
        description=(
            "질병의 예방·치료 효과 주장은 사전 인증 없이 게재할 수 없다. "
            "국내에서는 의료광고 사전심의 대상이며, 식품·화장품은 표시광고법 위반 소지가 크다."
        ),
        fix="의약품이 아닌 경우 치료·예방 표현을 제거하세요.",
    ),
    PolicyItem(
        code="RESTRICT-FINANCIAL",
        title="금융 상품·서비스 제한",
        category="제한된 콘텐츠",
        official_name="Financial products and services",
        severity=Severity.BLOCK,
        description=(
            "'원금 보장', '확정 수익' 같은 표현은 금융 서비스 정책 위반이며 "
            "국내에서는 유사수신 소지가 있다."
        ),
        fix="수익률 보장 표현을 제거하고 원금 손실 가능성을 고지하세요.",
    ),
    PolicyItem(
        code="RESTRICT-GAMBLING",
        title="도박 및 게임 제한",
        category="제한된 콘텐츠",
        official_name="Gambling and games",
        severity=Severity.BLOCK,
        description="도박·사행성 콘텐츠는 사전 인증 없이는 게재할 수 없다.",
        fix="플랫폼 사전 인증을 받거나 해당 표현을 제거하세요.",
    ),
    PolicyItem(
        code="RESTRICT-SEXUAL",
        title="성적 콘텐츠 제한",
        category="제한된 콘텐츠",
        official_name="Sexual content",
        severity=Severity.BLOCK,
        description="성적 암시 표현은 제한 또는 금지 대상이다.",
        fix="해당 표현을 제거하세요.",
    ),
    PolicyItem(
        code="TT-BEFORE-AFTER",
        title="비포·애프터 표현",
        category="TikTok 광고 정책",
        official_name="TikTok — Before/After imagery",
        severity=Severity.WARN,
        description=(
            "체중·외모 변화의 전후 비교는 TikTok에서 명시적으로 제한된다. "
            "Google도 비현실적 결과 묘사(Unreliable claims)로 반려할 수 있다."
        ),
        fix="전후 비교 이미지·문구를 제거하세요.",
    ),
]


# ---------------------------------------------------------------------------
# 기술 (참고 수준)
# ---------------------------------------------------------------------------

TECHNICAL_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="TECH-NO-ALT",
        title="이미지 대체 텍스트 없음",
        category="편집 및 기술 요건",
        official_name="Technical requirements",
        severity=Severity.INFO,
        description=(
            "이미지에 alt가 없어 자동 심사에서 내용을 판별하기 어렵다. "
            "접근성 측면에서도 감점 요인이다."
        ),
        fix="주요 이미지에 alt 속성을 채우세요.",
    ),
]


ALL_POLICIES: list[PolicyItem] = (
    DESTINATION_POLICIES
    + ABUSE_POLICIES
    + MISREPRESENTATION_POLICIES
    + DATA_POLICIES
    + CONTENT_POLICIES
    + TECHNICAL_POLICIES
)

POLICY_BY_CODE: dict[str, PolicyItem] = {p.code: p for p in ALL_POLICIES}

# 코드가 결정적으로 판정하는 항목 — LLM에게 묻지 않는다.
CODE_DECIDED_PREFIXES = ("DEST-", "DATA-", "TECH-", "ABUSE-")


def policies_for(platform: Platform) -> list[PolicyItem]:
    return [p for p in ALL_POLICIES if platform in p.platforms]


def catalog_for_prompt(platform: Platform) -> str:
    """LLM 프롬프트에 넣을 정책 목록.

    코드를 반드시 함께 준다 — 모델이 임의의 코드를 지어내면 후처리에서 폐기하기 위함.
    결정적으로 판정 가능한 항목은 애초에 목록에서 뺀다.
    """
    lines = []
    for p in policies_for(platform):
        if p.code.startswith(CODE_DECIDED_PREFIXES):
            continue
        lines.append(f"- {p.code} | {p.title} | {p.description}")
    return "\n".join(lines)
