"""플랫폼별 정책 카탈로그.

**주의** — 여기 정리된 항목은 공개된 정책 문서와 실무에서 반복 관찰되는
반려 사유를 정리한 *휴리스틱*이다. 플랫폼 정책은 수시로 바뀌므로
최종 판단은 각 플랫폼의 공식 정책 문서를 따라야 한다.

이 파일은 "무엇을 볼 것인가"의 목록이고,
실제 판정 로직은 rules.py(결정적)와 analyzer.py(LLM)에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Platform, Severity


@dataclass(frozen=True)
class PolicyItem:
    code: str
    title: str
    severity: Severity
    description: str
    fix: str
    platforms: tuple[Platform, ...] = (Platform.GOOGLE_ADS, Platform.TIKTOK_ADS)


# ---------------------------------------------------------------------------
# 1. 랜딩페이지 요건 — "있어야 하는데 없는 것" (부재 감지)
#
# 실무에서 가장 흔한 반려 사유인데, 대부분의 점검 도구가 놓친다.
# "금지어가 있는가"는 잡기 쉽지만 "필수 요소가 없는가"는 잡기 어렵기 때문.
# 이 카테고리는 전적으로 결정적 룰셋(rules.py)이 담당한다.
# ---------------------------------------------------------------------------

ABSENCE_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="LP-PRIVACY",
        title="개인정보처리방침 없음",
        severity=Severity.BLOCK,
        description=(
            "페이지에서 개인정보를 수집(폼·전화·이메일)하는데 "
            "개인정보처리방침 링크가 없다. 데이터 수집 정책 위반에 해당한다."
        ),
        fix="푸터에 개인정보처리방침 페이지 링크를 추가하세요.",
    ),
    PolicyItem(
        code="LP-CONTACT",
        title="연락처·사업자 정보 없음",
        severity=Severity.WARN,
        description=(
            "전화번호·이메일·사업자등록번호 중 어느 것도 확인되지 않는다. "
            "신뢰성 검토에서 반려되는 대표적 사유이며, "
            "국내 전자상거래법상 사업자 정보 표시 의무와도 연결된다."
        ),
        fix="푸터에 상호·사업자등록번호·연락처를 표기하세요.",
    ),
    PolicyItem(
        code="LP-PRICE",
        title="가격·거래 조건 미표시",
        severity=Severity.WARN,
        description=(
            "판매·구매를 유도하는 문구가 있는데 가격 정보가 페이지에 없다. "
            "거래 조건 불명확으로 반려될 수 있다."
        ),
        fix="가격, 배송비, 환불 조건을 페이지에 명시하세요.",
    ),
    PolicyItem(
        code="LP-THIN",
        title="콘텐츠 부족 (thin content)",
        severity=Severity.WARN,
        description=(
            "본문 텍스트가 지나치게 적다. 실질적 가치가 없는 페이지로 "
            "판단되어 방문 페이지 품질 기준에서 반려될 수 있다."
        ),
        fix="제품·서비스 설명, 이용 방법, FAQ 등 실질적인 내용을 채우세요.",
    ),
    PolicyItem(
        code="LP-UNREACHABLE",
        title="페이지 접근 불가",
        severity=Severity.BLOCK,
        description="랜딩 페이지가 열리지 않는다(4xx/5xx/타임아웃). 즉시 게재 거부 사유.",
        fix="URL과 서버 상태를 확인하세요. 리디렉션 체인도 점검이 필요합니다.",
    ),
]


# ---------------------------------------------------------------------------
# 2. 금지·제한 표현 — "있으면 안 되는 것"
# ---------------------------------------------------------------------------

CONTENT_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="AD-GUARANTEE",
        title="절대적·보장성 표현",
        severity=Severity.BLOCK,
        description=(
            "'100% 보장', '완치', '무조건' 같은 절대적 효과 주장은 "
            "허위·과장 광고(misrepresentation)로 분류된다."
        ),
        fix="'개인차가 있습니다' 등 한정 표현으로 바꾸거나 근거를 제시하세요.",
    ),
    PolicyItem(
        code="AD-MEDICAL",
        title="의학적 효능 주장",
        severity=Severity.BLOCK,
        description=(
            "질병의 예방·치료 효과를 주장하는 표현. 국내에서는 의료광고 "
            "사전심의 대상이며, 식품·화장품은 표시광고법 위반 소지가 크다."
        ),
        fix="의약품이 아닌 경우 치료·예방 표현을 제거하세요.",
    ),
    PolicyItem(
        code="AD-FINANCIAL",
        title="수익 보장·투자 유인 표현",
        severity=Severity.BLOCK,
        description=(
            "'원금 보장', '월 수익 확정' 같은 표현은 금융 서비스 정책 "
            "위반이자 유사수신 소지가 있다."
        ),
        fix="수익률 보장 표현을 제거하고 원금 손실 가능성을 고지하세요.",
    ),
    PolicyItem(
        code="AD-URGENCY",
        title="과도한 긴급성·압박 문구",
        severity=Severity.WARN,
        description=(
            "'딱 1자리 남음', '오늘 마감' 등 허위 희소성은 "
            "오도성 광고로 판단될 수 있다."
        ),
        fix="실제 재고·기간과 일치하지 않는 긴급성 표현을 제거하세요.",
    ),
    PolicyItem(
        code="AD-SUPERLATIVE",
        title="객관적 근거 없는 최상급 표현",
        severity=Severity.WARN,
        description="'업계 1위', '최고', '유일' 등은 출처 없이 사용하면 반려될 수 있다.",
        fix="공신력 있는 출처와 기준 시점을 함께 표기하세요.",
    ),
    PolicyItem(
        code="AD-PERSONAL",
        title="민감정보 타겟팅 암시",
        severity=Severity.BLOCK,
        description=(
            "건강 상태, 재정 곤란, 신념 등 개인의 민감한 속성을 "
            "직접 지목하는 문구는 개인 맞춤 광고 정책 위반이다."
        ),
        fix="'당신의 ○○ 때문에' 식의 단정 대신 일반적 서술로 바꾸세요.",
    ),
    PolicyItem(
        code="AD-BEFORE-AFTER",
        title="비포·애프터 표현",
        severity=Severity.WARN,
        description=(
            "체중·외모 변화의 전후 비교는 TikTok에서 명시적으로 제한되며, "
            "Google도 비현실적 결과 묘사로 반려할 수 있다."
        ),
        fix="전후 비교 이미지·문구를 제거하세요.",
        platforms=(Platform.TIKTOK_ADS, Platform.GOOGLE_ADS),
    ),
    PolicyItem(
        code="AD-ADULT",
        title="성인·선정적 표현",
        severity=Severity.BLOCK,
        description="성적 암시 표현은 대부분의 플랫폼에서 제한 또는 금지 대상이다.",
        fix="해당 표현을 제거하세요.",
    ),
    PolicyItem(
        code="AD-GAMBLING",
        title="도박·사행성 표현",
        severity=Severity.BLOCK,
        description="도박·사행성 콘텐츠는 사전 인증 없이는 게재할 수 없다.",
        fix="플랫폼 사전 인증을 받거나 해당 표현을 제거하세요.",
    ),
    PolicyItem(
        code="AD-COUNTERFEIT",
        title="모조품·브랜드 무단 사용 정황",
        severity=Severity.BLOCK,
        description="'정품급', '이미테이션' 등 모조품 판매 정황은 즉시 계정 정지 사유다.",
        fix="해당 표현과 상품을 제거하세요.",
    ),
]


# ---------------------------------------------------------------------------
# 3. 기술적 요건
# ---------------------------------------------------------------------------

TECHNICAL_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="TECH-HTTPS",
        title="HTTPS 미사용",
        severity=Severity.WARN,
        description="개인정보를 수집하는 페이지가 HTTP를 쓰고 있다.",
        fix="TLS 인증서를 적용하고 HTTPS로 전환하세요.",
    ),
    PolicyItem(
        code="TECH-REDIRECT",
        title="도메인 간 리디렉션",
        severity=Severity.WARN,
        description=(
            "입력한 URL과 최종 도착 도메인이 다르다. 심사에서 "
            "표시 URL 불일치로 반려될 수 있다."
        ),
        fix="광고의 표시 URL과 최종 도착 도메인을 일치시키세요.",
    ),
    PolicyItem(
        code="TECH-NO-ALT",
        title="이미지 대체 텍스트 없음",
        severity=Severity.INFO,
        description=(
            "이미지에 alt가 없어 자동 심사에서 내용을 판별하기 어렵다. "
            "접근성 측면에서도 감점 요인이다."
        ),
        fix="주요 이미지에 alt 속성을 채우세요.",
    ),
]


ALL_POLICIES: list[PolicyItem] = ABSENCE_POLICIES + CONTENT_POLICIES + TECHNICAL_POLICIES

POLICY_BY_CODE: dict[str, PolicyItem] = {p.code: p for p in ALL_POLICIES}


def policies_for(platform: Platform) -> list[PolicyItem]:
    return [p for p in ALL_POLICIES if platform in p.platforms]


def catalog_for_prompt(platform: Platform) -> str:
    """LLM 프롬프트에 넣을 정책 목록. 코드를 반드시 함께 준다 —
    모델이 임의의 코드를 지어내면 후처리에서 폐기하기 위함."""
    lines = []
    for p in policies_for(platform):
        if p.code.startswith("LP-") or p.code.startswith("TECH-"):
            continue  # 부재·기술 항목은 코드가 결정적으로 판정한다
        lines.append(f"- {p.code} | {p.title} | {p.description}")
    return "\n".join(lines)
