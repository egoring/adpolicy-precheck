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

from .models import Enforcement, Platform, Severity

POLICY_DOCS = {
    "overview": "https://support.google.com/adspolicy/answer/6008942",
    # 편집 기준(광고소재). 내용이 멀쩡해도 여기서 걸리면 광고가 안 나간다.
    "editorial": "https://support.google.com/adspolicy/answer/6021546",
    # 2바이트 언어의 글자 수 계산 근거
    "text_ads": "https://support.google.com/google-ads/answer/1704389",
    "destination": "https://support.google.com/adspolicy/answer/6368661",
    "misrepresentation": "https://support.google.com/adspolicy/answer/6020955",
    "abuse": "https://support.google.com/adspolicy/answer/6020954",
    # 2025년 개편으로 클로킹이 '시스템 우회' 문서 안의 하위 절로 옮겨졌다.
    "circumvent": "https://support.google.com/adspolicy/answer/15938075",
    "evasive": "https://support.google.com/adspolicy/answer/15938074",
    "coordinated": "https://support.google.com/adspolicy/answer/15938072",
    "unacceptable_business": "https://support.google.com/adspolicy/answer/15938071",
    "suspension": "https://support.google.com/adspolicy/answer/2375414",
    "strikes": "https://support.google.com/adspolicy/answer/10922738",
    "tt_actor": "https://ads.tiktok.com/resources/help/article/actor-policy",
    "tt_suspension":
        "https://ads.tiktok.com/resources/help/article/account-suspensions",
    # 허위 진술의 하위 항목들. 상위 문서만 걸어두면 어느 조항인지 찾을 수 없다.
    "unreliable": "https://support.google.com/adspolicy/answer/15936857",
    "clickbait": "https://support.google.com/adspolicy/answer/15936667",
    "pricing": "https://support.google.com/adspolicy/answer/15938375",
    # 제한·금지 콘텐츠
    "financial": "https://support.google.com/adspolicy/answer/2464998",
    "crypto": "https://support.google.com/adspolicy/answer/14009787",
    "dangerous": "https://support.google.com/adspolicy/answer/6014299",
    "dishonest": "https://support.google.com/adspolicy/answer/6016086",
    "alcohol": "https://support.google.com/adspolicy/answer/6012382",
    "dating": "https://support.google.com/adspolicy/answer/15328393",
    # TikTok
    "tt_weight": "https://ads.tiktok.com/help/article/tiktok-ads-policy-weight-management",
    "tt_misleading":
        "https://ads.tiktok.com/help/article/tiktok-ads-policy-misleading-and-false-content",
    "tt_health":
        "https://ads.tiktok.com/help/article/tiktok-ads-policy-healthcare-pharmaceuticals",
    "tt_deceptive": "https://ads.tiktok.com/help/article/tiktok-ads-policy-deceptive-practices",
    "tt_youth": "https://ads.tiktok.com/help/article/tiktok-ads-policy-youth-safety",
    "tt_language": "https://ads.tiktok.com/help/article/ad-review-checklist-ad-language",
    # 아래는 Google 정책이 아니라 국내 법령이다. KR- 항목 전용.
    "kr_pipa": "https://www.law.go.kr/법령/개인정보보호법",
}


@dataclass(frozen=True)
class PolicyItem:
    code: str
    title: str
    category: str          # 공식 상위 분류
    official_name: str     # 공식 정책 문서상의 항목명
    severity: Severity     # 이 광고가 나갈 수 있는가
    description: str
    fix: str
    source: str = POLICY_DOCS["overview"]
    platforms: tuple[Platform, ...] = (Platform.GOOGLE_ADS, Platform.TIKTOK_ADS)
    # 계정에 미치는 결과. 기본은 광고 반려다 — 정지급은 문서가 명시한 것만 올린다.
    # 판별 근거는 Google 정책 문서에 박혀 있는 정형 문장이다:
    #   정지급 "사전 경고 없이 즉시 해당 Google Ads 계정을 정지하며 …"
    #   반려급 "이 정책을 위반해도 사전 경고 없이 바로 계정이 정지되지는 않습니다."
    enforcement: Enforcement = Enforcement.DISAPPROVE


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
        code="DEST-IMAGE-ONLY-CONTENT",
        title="본문이 이미지 안에만 있음",
        category="편집 및 기술 요건",
        official_name="Destination requirements",
        severity=Severity.INFO,
        description=(
            "페이지 내용이 대부분 이미지 안에 들어 있어 HTML 텍스트가 적다. "
            "내용 자체는 있으므로 콘텐츠 부족은 아니지만, 심사 크롤러가 "
            "이미지를 읽지 못하면 빈 페이지로 볼 수 있고 접근성도 떨어진다."
        ),
        fix=(
            "핵심 문구만이라도 HTML 텍스트로 함께 두고, "
            "이미지에는 alt를 채우세요."
        ),
        source=POLICY_DOCS["destination"],
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
        official_name="시스템 우회: 클로킹 (Circumventing systems: Cloaking)",
        severity=Severity.BLOCK,
        enforcement=Enforcement.SUSPEND,
        description=(
            "\"Google 규정 위반을 숨기기 위해 웹사이트에서 Google을 포함해 "
            "사용자에 따라 다른 콘텐츠를 게시해서는 안 됩니다.\" 언어·지역·회선 속도에 "
            "따라 조금 다르게 보이는 것은 허용되지만, \"홍보하는 상품이나 서비스는 "
            "모든 사용자에게 동일하게 표시되어야\" 한다. "
            "**의도치 않은 경우도 같은 제재를 받는다** — 봇 차단 WAF, 지역 리디렉션, "
            "JS 전용 렌더링이 흔한 원인이다."
        ),
        fix=(
            "모든 클라이언트에 동일한 콘텐츠를 제공하세요. WAF·CDN의 봇 차단 규칙, "
            "지역 리디렉션, User-Agent 분기 로직을 점검해야 합니다. "
            "Chrome 개발자도구에서 User-Agent를 AdsBot-Google로 바꿔 열어보면 "
            "Google이 보는 화면을 그대로 확인할 수 있습니다."
        ),
        source=POLICY_DOCS["circumvent"],
    ),
    # -----------------------------------------------------------------------
    # 편집 기준 — 문구 자체의 형식. 랜딩페이지가 아니라 광고 텍스트를 본다.
    #
    # 전부 코드가 100% 결정적으로 판정한다. 내용 판단이 아니라 형식이라서,
    # 여기서 걸린 것은 "고치면 반드시 통과한다"고 말할 수 있는 유일한 축이다.
    # -----------------------------------------------------------------------
    PolicyItem(
        code="AD-HEADLINE-TOO-LONG",
        title="광고 제목 글자 수 초과",
        category="편집 기준",
        official_name="광고소재: 글자 수 제한 (Editorial requirements)",
        severity=Severity.BLOCK,
        description=(
            "\"2바이트 언어에 적용되는 글자 수 제한을 초과하는 광고\"는 게재되지 않는다. "
            "**한국어는 문자 한 개를 두 자로 계산한다** — 영문 기준 30자인 제목이 "
            "한글로는 15자다. 영문 기준으로 써 두고 반려 사유를 못 찾는 경우가 흔하다."
        ),
        fix=(
            "한글 기준 15자(영문 30자) 안으로 줄이세요. 숫자·영문·기호는 한 자로 "
            "세므로 「3만원 할인」처럼 숫자를 섞으면 같은 길이에 더 담깁니다."
        ),
        source=POLICY_DOCS["text_ads"],
    ),
    PolicyItem(
        code="AD-DESCRIPTION-TOO-LONG",
        title="광고 설명 글자 수 초과",
        category="편집 기준",
        official_name="광고소재: 글자 수 제한 (Editorial requirements)",
        severity=Severity.BLOCK,
        description=(
            "설명은 영문 기준 90자이고, 한국어는 문자 한 개가 두 자로 계산되므로 "
            "한글 45자다. 한도를 넘으면 내용과 무관하게 게재되지 않는다."
        ),
        fix="한글 기준 45자(영문 90자) 안으로 줄이세요.",
        source=POLICY_DOCS["text_ads"],
    ),
    PolicyItem(
        code="AD-SYMBOL-ABUSE",
        title="문장부호·기호 남용",
        category="편집 기준",
        official_name="광고소재: 문장 부호 및 기호 (Editorial requirements)",
        severity=Severity.WARN,
        description=(
            "\"올바르게 또는 본래 용도로 사용되지 않는 문장 부호나 기호\"는 "
            "허용되지 않는다. 정책 문서가 드는 예시가 \"flowers!!\", \"f1owers\", "
            "\"fl@wers\"다. 별표·하트 같은 장식 기호를 시선 끌기용으로 붙이는 것도 "
            "같은 조항에 걸린다. "
            "(이모지는 정책 문서가 이름으로 지목하지는 않는다 — 기호 남용으로 "
            "판단될 소지가 크다는 뜻이지 명시된 금지 조항은 아니다.)"
        ),
        fix=(
            "느낌표는 한 번만, 문장 끝에만 쓰세요. 장식 기호(★♥▶)는 빼고, "
            "단어에 숫자·기호를 끼워 넣지 마세요."
        ),
        source=POLICY_DOCS["editorial"],
    ),
    PolicyItem(
        code="AD-CAPS-ABUSE",
        title="대문자 남용",
        category="편집 기준",
        official_name="광고소재: 대문자 사용 (Editorial requirements)",
        severity=Severity.WARN,
        description=(
            "\"올바르게 사용되지 않거나 본래의 용도를 벗어난 대문자 사용\"은 "
            "허용되지 않는다. 약어가 아닌 단어를 전부 대문자로 쓰는 것이 여기 해당한다. "
            "한글에는 대소문자가 없으므로 영문 구간에만 적용된다."
        ),
        fix="첫 글자만 대문자로 쓰세요. 약어(HTML, FAQ)는 그대로 두어도 됩니다.",
        source=POLICY_DOCS["editorial"],
    ),
    PolicyItem(
        code="AD-REPETITION",
        title="불필요한 반복",
        category="편집 기준",
        official_name="광고소재: 반복 (Editorial requirements)",
        severity=Severity.WARN,
        description=(
            "\"이름, 단어, 구문을 표준이 아니거나 변칙적으로 또는 불필요하게 반복\"하는 "
            "것은 허용되지 않는다. 키워드를 욱여넣으려고 같은 말을 되풀이하는 경우가 "
            "대부분이다."
        ),
        fix="같은 단어는 한 번만 쓰고, 남는 자리에는 다른 정보를 넣으세요.",
        source=POLICY_DOCS["editorial"],
    ),
    PolicyItem(
        code="AD-SPACING-ABUSE",
        title="공백 사용 이상",
        category="편집 기준",
        official_name="광고소재: 공백 (Editorial requirements)",
        severity=Severity.WARN,
        description=(
            "\"공백 생략 또는 불필요한 공백 추가\", \"공백을 과도하게 또는 변칙적으로 "
            "사용\"하는 것은 허용되지 않는다. 자간을 벌려 쓰는 것(무 료 상 담)은 "
            "탐지를 피하려는 형태로도 읽힌다."
        ),
        fix="일반적인 띄어쓰기로 쓰세요. 강조는 공백이 아니라 단어 선택으로 하세요.",
        source=POLICY_DOCS["editorial"],
    ),
    PolicyItem(
        code="ABUSE-PARAM-CLOAKING",
        title="광고 파라미터에 따라 다른 페이지",
        category="금지된 행위",
        official_name="시스템 우회: 클로킹 (Circumventing systems: Cloaking)",
        severity=Severity.BLOCK,
        enforcement=Enforcement.SUSPEND,
        description=(
            "광고 클릭 파라미터(gclid·ttclid·utm 등)가 붙었을 때와 붙지 않았을 때 "
            "서로 다른 콘텐츠가 나가고 있다. 심사 크롤러는 광고를 클릭해서 오지 "
            "않으므로 파라미터가 없는 쪽만 보게 되는데, 이는 \"Google을 포함해 "
            "사용자에 따라 다른 콘텐츠를 게시\"하는 것에 해당한다. "
            "**의도치 않은 경우도 같은 제재를 받는다** — 유입 경로별 랜딩 스위치, "
            "제휴 링크 분기, A/B 테스트 도구가 흔한 원인이다."
        ),
        fix=(
            "유입 파라미터로 본문이나 상품 구성을 바꾸지 마세요. 경로별로 다른 "
            "페이지를 보여야 한다면 파라미터로 갈아끼우지 말고 각각 별도 URL로 "
            "만들어 그 URL을 광고 최종 도착 URL로 등록해야 합니다. "
            "브라우저에서 gclid를 붙였을 때와 뗐을 때를 직접 비교해 보세요."
        ),
        source=POLICY_DOCS["circumvent"],
    ),
    PolicyItem(
        code="ABUSE-PARAM-BRANCH-SCRIPT",
        title="광고 파라미터로 화면을 바꾸는 스크립트",
        category="금지된 행위",
        official_name="시스템 우회: 클로킹 (Circumventing systems: Cloaking)",
        severity=Severity.WARN,
        description=(
            "페이지 스크립트가 주소에서 광고 클릭 파라미터(gclid·ttclid 등)를 읽어 "
            "**화면 내용이나 행선지를 바꾼다.** 심사 크롤러는 광고를 클릭해서 오지 "
            "않으므로 파라미터 없는 쪽만 보게 된다. "
            "**여기서 증명되는 것은 \"그런 구조가 있다\"까지다** — 서버 응답은 "
            "어느 파라미터로 불러도 같으므로, 실제로 다른 내용이 나가는지는 "
            "브라우저에서 직접 열어봐야 확인된다. 그래서 경고로 둔다. "
            "gclid를 히든 필드에 넣어 전환을 추적하는 것은 정상이며 여기 걸리지 않는다."
        ),
        fix=(
            "브라우저에서 주소 끝에 `?gclid=test`를 붙였을 때와 뗐을 때를 직접 "
            "비교해 보세요. 내용이 달라진다면 파라미터로 갈아끼우지 말고 경로별로 "
            "별도 URL을 만들어 각각을 광고 최종 도착 URL로 등록해야 합니다. "
            "확인되면 이것은 계정 정지로 이어지는 클로킹입니다."
        ),
        source=POLICY_DOCS["circumvent"],
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
        source=POLICY_DOCS["circumvent"],
    ),
    PolicyItem(
        code="ABUSE-AUTO-REDIRECT",
        title="자동 리디렉션",
        category="금지된 행위",
        official_name="시스템 우회: 클로킹 / 도착 페이지 환경",
        severity=Severity.BLOCK,
        enforcement=Enforcement.SUSPEND,
        description=(
            "사용자 동작 없이 페이지가 스스로 다른 주소로 넘어간다. 도착한 곳이 "
            "정책을 어기는 사이트라면 \"전혀 다른 웹사이트로 사용자를 보내는 "
            "행위(동일한 도메인인 경우도 마찬가지)\"로 클로킹에 해당하고, "
            "그렇지 않더라도 \"사용자 작업 없이 페이지를 자동으로 리디렉션하는 "
            "웹사이트\"는 도착 페이지 환경 위반이다."
        ),
        fix="meta refresh와 진입 즉시 실행되는 location 변경을 제거하고, "
            "최종 목적지를 광고의 최종 URL로 직접 지정하세요.",
        source=POLICY_DOCS["circumvent"],
    ),
    PolicyItem(
        code="ABUSE-HIDDEN-TEXT",
        title="숨긴 텍스트·보이지 않는 문자",
        category="금지된 행위",
        official_name="광고 네트워크 악용: 회피적 광고 콘텐츠",
        severity=Severity.WARN,
        enforcement=Enforcement.STRIKE,
        description=(
            "화면에 보이지 않게 처리된 텍스트나 폭 없는 유니코드 문자가 들어 있다. "
            "Google은 \"광고 비승인을 피하기 위해 금지된 단어 또는 구문에 오자를 섞어 "
            "입력하는 행위\", \"사용자에게 아무 가치도 제공하지 않는 보이지 않는 "
            "유니코드 문자\"를 심사 회피로 본다. "
            "다만 이 항목은 \"사전 경고 없이 바로 계정이 정지되지는 않습니다\"."
        ),
        fix="숨긴 텍스트와 폭 없는 문자를 제거하세요. 접근성 목적이라면 "
            "aria-label이나 스크린리더 전용 클래스를 쓰는 편이 안전합니다.",
        source=POLICY_DOCS["evasive"],
    ),
    PolicyItem(
        code="ABUSE-CRAWLER-BLOCKING-OVERLAY",
        title="본문을 가리는 전면 레이어",
        category="금지된 행위",
        official_name="시스템 우회: 클로킹 (심사 접근 차단)",
        severity=Severity.WARN,
        enforcement=Enforcement.SUSPEND,
        description=(
            "화면 전체를 덮는 레이어가 본문 접근을 막고 있다. Google은 "
            "\"'사용자 경험을 방해하는 전면 광고'로 웹사이트의 콘텐츠 대부분에 대한 "
            "액세스를 차단하는 경우(즉, Google이 방문 페이지나 광고 도착 페이지에 "
            "액세스하여 정책 위반 여부를 확인할 수 없는 경우)\"를 클로킹으로 본다."
        ),
        fix="진입 즉시 뜨는 전면 레이어를 없애거나, 최소한 본문이 크롤러에 "
            "그대로 노출되게 하세요.",
        source=POLICY_DOCS["circumvent"],
    ),
    PolicyItem(
        code="ABUSE-FRAMED-CONTENT",
        title="다른 도메인 콘텐츠를 그대로 감쌈",
        category="금지된 행위",
        official_name="도착 페이지 요건: 고유 콘텐츠 부족 (미러링·프레이밍)",
        severity=Severity.WARN,
        description=(
            "페이지가 다른 도메인의 콘텐츠를 프레임으로 감싸 보여주고 있다. "
            "\"다른 소스의 콘텐츠를 미러링, 프레이밍 또는 스크래핑하는 경우\"는 "
            "고유 콘텐츠 부족으로 반려된다. 수정 안내도 명시돼 있다 — "
            "\"광고의 방문 페이지 도메인이 아닌 도메인에서 콘텐츠를 복사하는 "
            "HTML frameset를 모두 제거하세요.\""
        ),
        fix="프레임 대신 해당 도메인을 최종 URL로 직접 쓰거나, 고유 콘텐츠를 채우세요.",
        source=POLICY_DOCS["destination"],
    ),
    PolicyItem(
        code="ABUSE-SERVER-RENDERED-BODY",
        title="본문을 서버에서 받아 채우는 구조",
        category="금지된 행위",
        official_name="시스템 우회: 클로킹 (심사 대상 콘텐츠 부재)",
        severity=Severity.WARN,
        # 등급을 올리지 않는다. 여기서 증명되는 건 '바꿔치기했다'가 아니라
        # '바꿔치기할 수 있는 구조'까지다. 그걸로 계정 정지를 말하면 거짓이다.
        description=(
            "응답 HTML에 본문이 거의 없고, 서버에서 내용을 받아 화면에 꽂는 "
            "코드가 있습니다. 심사 크롤러는 JS를 끝까지 실행하지 않으므로 "
            "**심사 대상이 되는 내용이 응답에 없는 상태**입니다. Google은 "
            "\"Google이 방문 페이지에 액세스하여 정책 위반 여부를 확인할 수 "
            "없는 경우\"를 클로킹으로 봅니다.\n\n"
            "이 지적은 위반의 증거가 아니라 **구조의 문제**입니다. 서버가 "
            "심사 때와 다른 내용을 내려줄 수 있고, 그렇게 되면 클로킹이 됩니다. "
            "SPA·CMS라면 정상일 수 있으니 직접 확인하세요."
        ),
        fix=(
            "핵심 문구는 서버가 처음 응답하는 HTML에 담으세요(SSR·프리렌더). "
            "그러면 심사가 실제 내용을 보고, 나중에 바꿔치기했다는 의심도 받지 않습니다."
        ),
        source=POLICY_DOCS["circumvent"],
    ),
    PolicyItem(
        code="ABUSE-OBFUSCATED-SCRIPT",
        title="감춘 스크립트",
        category="금지된 행위",
        official_name="광고 네트워크 악용: 회피적 광고 콘텐츠",
        severity=Severity.WARN,
        enforcement=Enforcement.STRIKE,
        description=(
            "코드를 읽지 못하게 감춰 두었습니다(eval+atob, 긴 \\x 이스케이프, "
            "String.fromCharCode 체인 등). 무엇을 하는지는 알 수 없지만, "
            "**감췄다는 사실 자체**가 심사 회피 정황입니다. Google은 "
            "\"정책 위반 콘텐츠를 숨기기 위해\" 조작하는 행위를 회피적 광고 "
            "콘텐츠로 봅니다."
        ),
        fix="난독화를 풀거나, 광고 랜딩페이지에서는 해당 스크립트를 제거하세요.",
        source=POLICY_DOCS["evasive"],
    ),
    PolicyItem(
        code="ABUSE-CONTENT-CHANGED",
        title="심사 시점 이후 내용이 바뀜",
        category="금지된 행위",
        official_name="TikTok 계정 정지 사유 / 시스템 우회",
        severity=Severity.BLOCK,
        enforcement=Enforcement.SUSPEND,
        description=(
            "직전 점검 때와 본문이 달라졌습니다. TikTok은 \"캠페인을 생성한 후 "
            "광고의 랜딩 페이지에 변경 사항을 적용했습니다\"를 계정 정지로 이어지는 "
            "위반으로 명시하고, Google도 심사 통과 뒤 콘텐츠를 바꾸는 것을 시스템 "
            "우회로 봅니다.\n\n"
            "정상적인 업데이트일 수도 있습니다. 다만 광고가 이미 집행 중이라면 "
            "바뀐 내용으로 다시 심사를 받아야 합니다."
        ),
        fix="광고 집행 중이라면 변경 내용이 심사를 통과할 수 있는지 확인하고, "
            "필요하면 광고를 내린 뒤 재심사를 받으세요.",
        source=POLICY_DOCS["tt_suspension"],
    ),
    PolicyItem(
        code="DEST-BRIDGE-PAGE",
        title="브리지·도어웨이 페이지",
        category="편집 및 기술 요건",
        official_name="도착 페이지 요건: 고유 콘텐츠 부족",
        severity=Severity.WARN,
        description=(
            "\"사용자를 다른 곳으로 보내는 용도로만 만들어진 도착 페이지\"로 보인다. "
            "정책 문서가 드는 예가 \"브리지 페이지, 도어웨이, 게이트웨이 및 기타 "
            "중간 페이지\"다. 본문은 거의 없는데 외부로 나가는 링크만 있는 구조가 "
            "전형이다."
        ),
        fix="사용자가 여기서 얻을 수 있는 고유한 내용을 채우거나, "
            "광고의 최종 URL을 실제 목적지로 바로 지정하세요.",
        source=POLICY_DOCS["destination"],
    ),
]


# ---------------------------------------------------------------------------
# 허위 진술 (Prohibited practices → Misrepresentation)
# ---------------------------------------------------------------------------

MISREPRESENTATION_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="MIS-UNACCEPTABLE-BUSINESS",
        title="허용되지 않는 비즈니스 관행",
        category="금지된 행위",
        official_name="허위 진술: 허용되지 않는 비즈니스 관행",
        severity=Severity.BLOCK,
        enforcement=Enforcement.SUSPEND,
        description=(
            "중대한 위반 10개 중 하나로, 발견 즉시 계정이 정지된다. 금지 행위는 "
            "\"다른 브랜드, 조직 또는 정부 기관의 지원을 받지 않지만 받고 있는 것처럼 "
            "가장하는 행위\", \"보유하지 않거나 실제로 제공할 수 없는 제품이나 서비스를 "
            "제공하는 것처럼 가장하는 행위(적절한 라이선스나 자격 요건을 갖추지 않는 "
            "경우 포함)\", \"의료 서비스를 제공하지 않으면서 의료 서비스를 제공하는 "
            "것으로 가장하는 등 사람들의 건강이나 안전을 위험에 빠뜨릴 수 있는 서비스에 "
            "대해 거짓말을 하는 행위\", \"다른 브랜드나 비즈니스의 명의를 도용하는 행위\"."
        ),
        fix="공식 제휴·인증·자격을 실제로 보유한 것만 표시하고, 근거를 함께 공개하세요. "
            "보유하지 않은 자격은 문구에서 즉시 제거해야 합니다.",
        source=POLICY_DOCS["unacceptable_business"],
    ),
    PolicyItem(
        code="MIS-COORDINATED-DECEPTION",
        title="조직적 기만 행위",
        category="금지된 행위",
        official_name="허위 진술: 조직적 기만 행위",
        severity=Severity.BLOCK,
        enforcement=Enforcement.SUSPEND,
        description=(
            "중대한 위반 10개 중 하나. \"콘텐츠가 정치, 사회 문제 또는 공적인 사안과 "
            "관련된 경우 다른 사이트 또는 계정과 협력하여 광고주의 신원 또는 기타 주요 "
            "정보를 은폐하거나 허위로 표시하는 행위\"와, 출신 국가를 숨기고 다른 나라 "
            "사용자에게 그 나라의 정치·사회 문제 콘텐츠를 게시하는 행위가 대상이다."
        ),
        fix="정치·사회 이슈를 다루는 페이지라면 운영 주체와 소재 국가를 "
            "명확히 밝히세요.",
        source=POLICY_DOCS["coordinated"],
    ),
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
        enforcement=Enforcement.STRIKE,
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
        enforcement=Enforcement.SUSPEND,
        description="'정품급', '이미테이션' 등 모조품 판매 정황은 즉시 계정 정지 사유다.",
        fix="해당 표현과 상품을 제거하세요.",
    ),
    PolicyItem(
        code="PROHIB-DANGEROUS",
        title="위험한 제품 또는 서비스",
        category="금지된 콘텐츠",
        official_name="Dangerous products or services",
        severity=Severity.BLOCK,
        enforcement=Enforcement.STRIKE,
        description=(
            "총기·총기 부품, 폭발물, 상해 목적의 칼, 기분전환용 약물과 그 도구, "
            "담배 및 흡연 대용 제품(전자담배 포함)은 홍보할 수 없다. "
            "'제조·구매·사용 방법을 안내하는 콘텐츠'도 같은 취급이다."
        ),
        fix="해당 제품·서비스와 사용법 안내를 제거하세요. 광고로는 다룰 수 없는 품목입니다.",
        source=POLICY_DOCS["dangerous"],
    ),
    PolicyItem(
        code="PROHIB-ENABLING-DISHONEST",
        title="부정 행위 조장",
        category="금지된 콘텐츠",
        official_name="Enabling dishonest behavior",
        severity=Severity.BLOCK,
        enforcement=Enforcement.STRIKE,
        description=(
            "Google은 '논문 대필 또는 대리 시험 서비스', '무효 클릭·리뷰·소셜 "
            "미디어 추천 등 조작된 사용자 활동의 판매', 문서 위조, 해킹 서비스, "
            "동의 없는 위치 추적을 금지한다."
        ),
        fix="해당 서비스 홍보를 제거하세요.",
        source=POLICY_DOCS["dishonest"],
    ),
    PolicyItem(
        code="RESTRICT-CRYPTO",
        title="암호화폐 및 관련 상품",
        category="제한된 콘텐츠",
        official_name="Cryptocurrencies and related products",
        severity=Severity.WARN,
        description=(
            "한국을 타겟팅하는 암호화폐 거래소·지갑 광고는 금융정보분석원(KoFIU)의 "
            "가상자산사업자(VASP) 인가와 Google 인증을 모두 받아야 허용된다. "
            "ICO·암호화폐 대출·DeFi·미호스팅 지갑은 인증과 무관하게 금지이고, "
            "'암호화폐 투자 조언·거래 신호'를 모아 보여주는 도착 페이지도 금지다. "
            "투자 조언 없는 순수 교육 자료는 신청 없이 허용된다."
        ),
        fix="VASP 인가와 Google 금융 서비스 인증 여부를 확인하세요. "
            "인증 전이라면 투자 권유·수익 관련 표현을 먼저 빼야 합니다.",
        source=POLICY_DOCS["crypto"],
    ),
    PolicyItem(
        code="RESTRICT-DATING",
        title="금지된 데이트·교제 서비스",
        category="금지된 콘텐츠",
        official_name="Dating and companionship services — 금지된 서비스",
        severity=Severity.BLOCK,
        enforcement=Enforcement.STRIKE,
        description=(
            "Google 정책은 금지 사례로 한국어 표현을 직접 명시한다 — "
            "'원조 교제', '조건 만남', '스폰서', '성매매, 애인 대행, 호스티스, "
            "에스코트 서비스'. 금전·재정적 지원을 대가로 한 교제 홍보가 대상이다."
        ),
        fix="해당 표현과 서비스를 제거하세요. 인증으로 허용되지 않는 금지 항목입니다.",
        source=POLICY_DOCS["dating"],
    ),
    PolicyItem(
        code="RESTRICT-ALCOHOL",
        title="무책임한 주류 광고",
        category="제한된 콘텐츠",
        official_name="Alcohol — 무책임한 주류 광고",
        severity=Severity.WARN,
        description=(
            "주류 광고 자체는 한국에서 허용되지만, '음주로 사회적 또는 직업적 "
            "입지가 강화되거나, 성적 매력이 높아지거나, 지적 수준이 높아지거나, "
            "운동 능력이 향상된다고 암시하는 광고', '음주가 건강이나 치료에 "
            "도움이 된다고 암시하는 광고', '과도한 음주를 미화'하는 광고는 "
            "허용되지 않는다."
        ),
        fix="음주의 효익을 암시하는 표현과 폭음 묘사를 제거하세요.",
        source=POLICY_DOCS["alcohol"],
    ),
    PolicyItem(
        code="MIS-FAKE-TESTIMONIAL",
        title="근거·면책 없는 후기",
        category="금지된 관행",
        official_name="Unreliable claims — 사용 후기 면책 요건 / Enabling dishonest behavior",
        severity=Severity.WARN,
        description=(
            "Google은 '구체적인 성과를 주장하는 사용 후기에는 특정한 결과를 "
            "보장할 수 없으며 결과는 다양할 수 있다는 내용의 면책 조항을 명시해야 "
            "한다'고 요구한다. 조작된 리뷰의 판매·구매는 부정 행위 조장으로 금지이고, "
            "TikTok도 '허위 추천을 하거나 허위로 추천받는 경우'를 금지한다."
        ),
        fix="후기에 개인차 면책 고지를 붙이거나, 수치를 단정하는 후기를 빼세요.",
        source=POLICY_DOCS["unreliable"],
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
        code="TT-LANGUAGE-MISMATCH",
        title="광고 문구와 랜딩페이지의 언어가 다름",
        category="광고 심사 기준",
        official_name="Review Ad Language",
        severity=Severity.WARN,
        description=(
            "TikTok은 광고 문구와 랜딩페이지가 **둘 다** 타겟 지역의 허용 언어와 "
            "맞아야 한다고 요구한다 — \"Ad's text/caption matches one acceptable "
            "language in all the countries/regions targeted by an ad group\", "
            "\"Language on any landing page or app store page linked to your ad "
            "matches the acceptable languages…\". 둘이 서로 다르면 둘 다 같은 지역의 "
            "허용 언어에 맞기 어렵다. "
            "**타겟 지역을 알 수 없으므로 위반으로 단정하지는 않는다** — 확인이 "
            "필요하다는 뜻이다."
        ),
        fix=(
            "타겟 지역의 허용 언어로 광고 문구와 랜딩페이지를 맞추세요. 지역별로 "
            "다른 언어를 쓴다면 광고 그룹을 지역별로 나누고 각각에 맞는 랜딩페이지를 "
            "연결해야 합니다."
        ),
        source=POLICY_DOCS["tt_language"],
        platforms=(Platform.TIKTOK_ADS,),
    ),
    PolicyItem(
        code="TT-BEFORE-AFTER",
        title="비포·애프터 표현",
        category="제한된 콘텐츠",
        # 근거를 바로잡았다. TikTok「체중 관리」문서 본문에는 전후 비교라는
        # 표현이 아예 없다. 실제 조항은 아래 둘이다.
        official_name="TikTok 오해의 소지가 있는 콘텐츠 / Google 클릭베이트 광고",
        severity=Severity.WARN,
        description=(
            "TikTok은 '전후 결과 비교와 같은 제품 효과 비교'를, "
            "Google은 클릭베이트 조항에서 \"'전후 비교' 이미지를 사용하여 신체의 "
            "극적인 변화를 홍보하는 광고\"를 금지한다. "
            "다만 TikTok은 '비교에 대한 주장은 관련 증거를 제공하거나 명확한 "
            "면책 고지가 있는 경우에 허용된다'고 명시한다."
        ),
        fix="전후 비교를 빼거나, 근거 자료와 '결과는 개인차가 있습니다' 수준의 "
            "명확한 면책 고지를 함께 표시하세요.",
        source=POLICY_DOCS["clickbait"],
    ),
    PolicyItem(
        code="TT-WEIGHT-UNREALISTIC",
        title="비현실적 체중·근육 변화 주장",
        category="제한된 콘텐츠",
        official_name="TikTok 체중 관리 / Google 신뢰할 수 없는 주장",
        severity=Severity.BLOCK,
        description=(
            "TikTok은 '식단 조절이나 운동 없이 제품만으로 체중 감량 또는 근육 "
            "증량이 가능하다고 주장하는 내용', '체중 감량이나 근육 증량이 쉽거나 "
            "보장된다고 암시하는 내용'을 금지한다. Google도 '특정 기간 내에 또는 "
            "적은 노력으로 비현실적인 체중 감량이 가능하다고 주장'을 신뢰할 수 "
            "없는 주장으로 본다."
        ),
        fix="기간·수치 보장과 '운동 없이·굶지 않고' 류의 표현을 빼고, "
            "실제 근거와 개인차 고지를 넣으세요.",
        source=POLICY_DOCS["tt_weight"],
    ),
    PolicyItem(
        code="TT-BODY-IMAGE",
        title="부정적 신체 이미지",
        category="제한된 콘텐츠",
        official_name="TikTok 체중 관리 및 신체 이미지 — 신체 이미지",
        severity=Severity.BLOCK,
        description=(
            "TikTok은 '사용자의 신체에 대해 노골적으로 수치심을 유발하거나, "
            "이상적인 신체 유형이 존재한다고 암시하거나, 외모 또는 체중 변화로 "
            "인해 삶의 환경이나 자아상이 개선된다고 홍보'하는 것을 금지한다. "
            "'특정 외모로 보이면 더욱 매력적이 되거나 성공할 수 있거나 행복하거나 "
            "유명해질 수 있다는 주장'이 명시적 금지 사례다."
        ),
        fix="외모·체형으로 자존감이나 인생이 달라진다는 표현을 제거하세요.",
        source=POLICY_DOCS["tt_weight"],
        platforms=(Platform.TIKTOK_ADS,),
    ),
    PolicyItem(
        code="TT-YOUTH-PRESSURE",
        title="청소년 대상 구매 압박",
        category="제한된 콘텐츠",
        official_name="TikTok 10대의 안전과 웰빙",
        severity=Severity.WARN,
        description=(
            "TikTok은 '10대에게 구매를 강권하거나 구매하도록 압박을 가하는 행위', "
            "'10대들에게 홍보 제품을 소유하면 인기가 많아질 것이라고 암시하는 "
            "행위'를 금지한다. 한국에서 '10대'는 만 19세 미만을 뜻한다 — "
            "다른 시장(만 18세)과 기준이 다르다."
        ),
        fix="미성년 대상 구매 압박·또래 압력 표현을 제거하고 타겟 연령을 확인하세요.",
        source=POLICY_DOCS["tt_youth"],
        platforms=(Platform.TIKTOK_ADS,),
    ),
]


# ---------------------------------------------------------------------------
# 국내 법령 (개인정보 보호법)
#
# 여기서부터는 **Google Ads 정책이 아니다.** 위 항목들이 공식 정책 분류에
# 매핑돼 있는 것과 달리, KR- 항목은 국내 법령 기준이라 카테고리와 source를
# 분리해 둔다. 섞으면 "이게 심사 반려 사유인가, 법 위반인가"가 흐려진다.
#
# 개인정보처리방침(DATA-NO-PRIVACY-POLICY)과 수집·이용 동의(KR-)는 다른
# 것이다. 방침은 상시 공개하는 문서고, 동의는 수집 시점의 행위다.
# 랜딩페이지에 폼이 있으면 실무상 둘 다 필요하고, 하나가 다른 하나를
# 대신하지 못한다.
#
# **법률 자문이 아니다.** 규제 업종은 반드시 전문가 검토를 받아야 한다.
# ---------------------------------------------------------------------------

KR_POLICIES: list[PolicyItem] = [
    PolicyItem(
        code="KR-NO-CONSENT",
        title="개인정보 수집·이용 동의 절차 없음",
        category="국내 법령",
        official_name="개인정보 보호법 — 개인정보의 수집·이용 동의",
        severity=Severity.BLOCK,
        description=(
            "개인정보를 수집하는 폼이 있으나 수집·이용에 대한 동의를 받는 절차가 "
            "보이지 않는다. 개인정보처리방침을 게시했더라도 동의를 대신하지 못한다 — "
            "방침은 상시 공개하는 문서고, 동의는 수집 시점에 받는 행위다."
        ),
        fix=(
            "폼에 '[필수] 개인정보 수집·이용 동의' 체크박스를 두고, "
            "동의 내용을 확인할 수 있게 하세요."
        ),
        source=POLICY_DOCS["kr_pipa"],
    ),
    PolicyItem(
        code="KR-INCOMPLETE-CONSENT",
        title="동의 고지사항 누락",
        category="국내 법령",
        official_name="개인정보 보호법 — 동의를 받는 방법",
        severity=Severity.WARN,
        description=(
            "동의를 받고는 있으나 고지해야 할 항목이 보이지 않는다. "
            "수집·이용 목적, 수집 항목, 보유·이용 기간, "
            "그리고 동의를 거부할 권리와 거부 시 불이익을 함께 알려야 한다."
        ),
        fix="동의 문구에 누락된 항목을 채우세요. 특히 거부권 고지가 자주 빠집니다.",
        source=POLICY_DOCS["kr_pipa"],
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
    + KR_POLICIES
    + TECHNICAL_POLICIES
)

POLICY_BY_CODE: dict[str, PolicyItem] = {p.code: p for p in ALL_POLICIES}

# 코드가 결정적으로 판정하는 항목 — LLM에게 묻지 않는다.
CODE_DECIDED_PREFIXES = ("DEST-", "DATA-", "TECH-", "ABUSE-", "KR-")


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
