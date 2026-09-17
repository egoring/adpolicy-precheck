"""결정적 룰셋 — 코드가 판정한다.

여기서 나온 Finding은 LLM을 거치지 않으므로 **재현성 100%**다.
같은 페이지를 100번 검사하면 100번 같은 결과가 나온다.

세 종류를 다룬다.
  1. 부재 감지 — 있어야 하는데 없는 것 (실무 반려 사유 1위)
  2. 광고↔페이지 대조 — 관련성, 약속한 혜택의 존재 여부
  3. 패턴 매칭 — 명백한 금지 표현

애매한 판단(맥락상 과장인가, 오해 소지가 있는가)은 여기서 하지 않는다.
그건 analyzer.py의 LLM 몫이다.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .fetcher import registrable_domain
from .models import Finding, PageSnapshot, Platform, Source
from .policies import POLICY_BY_CODE

# ---------------------------------------------------------------------------
# 탐지 패턴
# ---------------------------------------------------------------------------

PRIVACY_HINTS = [
    "개인정보처리방침", "개인정보 처리방침", "개인정보취급방침", "개인정보 취급방침",
    "개인정보보호정책", "개인정보 보호정책", "개인정보방침", "프라이버시 정책",
    "privacy policy", "privacy-policy", "/privacy", "privacy",
]

# --- 개인정보 수집·이용 동의 (개인정보 보호법) ---
#
# 개인정보처리방침과 다른 것이다. 방침은 상시 공개하는 문서고, 동의는 수집
# 시점의 행위다. 방침 링크가 있어도 동의 절차가 없으면 별개의 미비다.
#
# "동의"만으로는 못 잡는다 — 이용약관 동의·마케팅 수신 동의와 섞이기 때문에,
# '개인정보'와 '수집/이용'이 '동의' 근처에 함께 있어야 인정한다.
CONSENT_PATTERNS = [
    re.compile(r"개인정보[^\n]{0,30}?(수집|이용|제공)[^\n]{0,30}?동의"),
    re.compile(r"동의[^\n]{0,20}?개인정보[^\n]{0,30}?(수집|이용)"),
    re.compile(r"(수집|이용)\s*[·ㆍ‧\-및,/]+\s*(이용|제공)[^\n]{0,20}?동의"),
]

# 동의를 받을 때 함께 알려야 하는 것들. 거부권 고지가 가장 자주 빠진다.
CONSENT_ITEM_HINTS: dict[str, list[str]] = {
    "수집·이용 목적": ["수집 목적", "수집·이용 목적", "수집ㆍ이용 목적", "이용 목적", "수집목적",
                  "이용목적", "수집 및 이용 목적"],
    "수집 항목": ["수집 항목", "수집항목", "수집하는 항목", "수집하는 개인정보",
              "수집하려는 개인정보", "수집 정보"],
    "보유·이용 기간": ["보유 기간", "보유기간", "보유·이용 기간", "보유ㆍ이용 기간",
                  "이용 기간", "보관 기간", "보관기간", "파기"],
    "거부권 고지": ["동의를 거부", "거부할 권리", "거부하실 수 있", "거부할 수 있",
               "동의하지 않을", "거부 시", "거부시"],
}

CONTACT_PATTERNS = [
    # 경계가 없으면 '상품코드 08123456789' 같은 숫자열이 전화번호로 인정된다.
    re.compile(r"(?<!\d)0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}(?!\d)"),
    re.compile(r"(?<!\d)01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"),
    re.compile(r"(?<!\d)1[5-9]\d{2}[-.\s]?\d{4}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"사업자\s*등록\s*번호"),
    re.compile(r"\d{3}-\d{2}-\d{5}"),
]

PRICE_PATTERNS = [
    re.compile(r"\d[\d,]*\s*원"),
    re.compile(r"₩\s*\d[\d,]*"),
    re.compile(r"\$\s*\d[\d,.]*"),
    re.compile(r"무료|free\b", re.IGNORECASE),
]

COMMERCE_INTENT = [
    "구매", "주문", "결제", "장바구니", "신청하기", "가입하기",
    "buy now", "add to cart", "checkout", "order",
]

# 광고가 약속하는 혜택 — 페이지에서 확인되어야 한다.
OFFER_PATTERNS = [
    re.compile(r"(\d+)\s*%\s*(할인|세일|off)", re.IGNORECASE),
    re.compile(r"무료\s*(배송|체험|상담|시식)"),
    re.compile(r"(\d[\d,]*)\s*원\s*(할인|쿠폰|캐시백)"),
    re.compile(r"1\s*\+\s*1|2\s*\+\s*1"),
]

PII_INPUT_TYPES = {"email", "tel", "password"}
PII_FIELD_HINTS = ["이름", "성함", "연락처", "전화", "이메일", "생년월일", "주소"]

CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("MIS-UNRELIABLE-CLAIMS", re.compile(
        r"100\s*%\s*(보장|성공|환급)|완치|무조건\s*(성공|보장)|반드시\s*낫", re.IGNORECASE)),
    ("RESTRICT-HEALTHCARE", re.compile(
        r"(암|당뇨|고혈압|아토피|탈모|불면증)\s*(치료|완치|예방)|질병\s*치료|의학적으로\s*입증"
        # TikTok 의료·제약: "'기적' 또는 '비밀이나 치료법을 보유'한 제품임을 주장",
        # "제품/서비스가 처방약과 동등하거나 더 우수하다는 암시"
        r"|기적의?\s*(성분|효과|치료|약)|만병통치"
        r"|(처방)?약\s*(보다|대신)\s*(낫|좋|효과)")),
    # TikTok 체중 관리: "식단 조절이나 운동 없이 제품만으로 …", "쉽거나 보장된다고 암시"
    # Google 신뢰할 수 없는 주장: "특정 기간 내에 또는 적은 노력으로 비현실적인 체중 감량"
    #
    # '운동 없이'만 보면 안마의자·마사지 광고가 통째로 걸린다. 체중 맥락이
    # 같은 줄 가까이에 있을 때만 인정한다.
    ("TT-WEIGHT-UNREALISTIC", re.compile(
        r"(?:운동|식단|다이어트|굶)[^\n]{0,12}?(?:없이|안\s*하고|않고)[^\n]{0,20}?"
        r"(?:감량|체중|살|\d\s*(?:kg|킬로))"
        r"|(?:감량|체중|살|\d\s*(?:kg|킬로))[^\n]{0,20}?"
        r"(?:운동|식단|다이어트)\s*(?:없이|안\s*하고|않고)"
        # '만에'를 필수로 둔다. 빼면 "6개월 5kg 원두 정기배송" 같은 문구가 걸린다.
        # 기간은 "3주"만이 아니라 "한 달"처럼 한글 수사로도 온다 — 실제로 놓쳤다.
        r"|(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
        r"(?:일|주|주일|개월|달)\s*만에\s*\d+\s*(?:kg|킬로)"
        r"|\d+\s*(?:kg|킬로)\s*감량\s*(?:보장|확실)")),
    # TikTok 신체 이미지: "특정 외모로 보이면 더욱 매력적이 되거나 성공할 수 있거나
    # 행복하거나 유명해질 수 있다는 주장", "노골적으로 수치심을 유발"
    ("TT-BODY-IMAGE", re.compile(
        r"(?:뚱뚱|비만|살찐|통통)[^\n]{0,16}?(?:때문에|탓에)[^\n]{0,16}?"
        r"(?:자신감|우울|창피|부끄|위축)"
        r"|(?:날씬|마르|예뻐지|살\s*만?\s*빼)[^\n]{0,8}?(?:면|지면)[^\n]{0,24}?"
        r"(?:인기|연애|취업|인생|성공|사랑받|달라진)")),
    ("RESTRICT-FINANCIAL", re.compile(
        r"원금\s*보장|수익\s*보장|확정\s*수익|월\s*\d+\s*%\s*수익|손실\s*없")),
    # 두 갈래다. 카탈로그 설명이 "클릭베이트 기법이나 **선정적 문구**"라고
    # 적고 있는데 오래도록 앞쪽(허위 희소성)만 구현되어 있었다. 평가 하네스가
    # `clickbait` 케이스에서 이 누락을 잡아냈다.
    #
    # (1) 허위 희소성·긴급성
    #     '오늘만'은 한 낱말일 때만. '오늘 만나보세요', '오늘 만든'이 걸리면 안 된다.
    # (2) 선정적 유인 — 내용을 감춰 클릭을 강요하는 정형 문구.
    #     '충격'은 낱말만으로는 기사 제목과 구분이 안 되므로 감탄부호나
    #     '충격적인 사실/진실'처럼 갈고리 형태일 때만 인정한다.
    ("MIS-CLICKBAIT", re.compile(
        r"단\s*\d+\s*(자리|명)\s*남|오늘만(?![가-힣])|마감\s*임박|지금\s*아니면"
        r"|충격\s*[!！]|충격적인\s*(사실|진실|결과)|경악[\s!！]"
        r"|(의사|전문가|업계|병원|약사)\w*\s*(들)?\w*\s*(이|가|는)?\s*"
        r"(숨긴|숨기는|감춘|감추는|알려주지\s*않는|말\s*(안|하지)\s*않는)"
        r"|당신만\s*(모르는|몰랐던)"
        r"|아무도\s*(알려주지|말해주지|가르쳐주지)\s*않"
        r"|클릭하지\s*않으면\s*후회"
        r"|(이것|이거|단\s*하나)만\s*(알면|하면)[^\n]{0,12}(해결|끝)")),
    ("MIS-SUPERLATIVE", re.compile(
        r"(업계|국내|세계)\s*(1위|최고|최초|유일)|넘버\s*원|No\.?\s*1", re.IGNORECASE)),
    ("MIS-NEGATIVE-LIFE-EVENTS", re.compile(
        r"당신의\s*(우울|비만|탈모|빚|파산|질병)|당신은\s*\S*\s*환자|파산\s*직전")),
    ("TT-BEFORE-AFTER", re.compile(
        r"비포\s*[&·/]?\s*애프터|before\s*[&/]\s*after|전\s*후\s*사진", re.IGNORECASE)),
    ("RESTRICT-SEXUAL", re.compile(r"성인용품|19금|야한|은밀한\s*만남")),
    # '토토'만 보면 '이웃집 토토로'가 걸린다. 도박 맥락이 함께 있어야 인정한다.
    ("RESTRICT-GAMBLING", re.compile(
        r"스포츠\s*토토|토토\s*(사이트|배팅|추천|가입)|안전\s*놀이터"
        r"|바카라|슬롯\s*머신|배팅\s*사이트|온라인\s*카지노|카지노\s*(사이트|가입)")),
    # '정품급'은 모조품 표현이지만 '정품 급속'은 정상 문구다. 붙여 쓴 경우만 본다.
    ("PROHIB-COUNTERFEIT", re.compile(
        r"정품급(?![가-힣])|이미테이션|짝퉁|A급\s*미러|미러\s*급")),
    # 암호화폐 — 한국 타겟은 VASP 인가 + Google 인증이 있어야 한다.
    # '코인'만 보면 코인노래방·코인세탁이 걸린다. 투자 맥락이 붙을 때만 본다.
    ("RESTRICT-CRYPTO", re.compile(
        r"비트코인|이더리움|암호\s*화폐|가상\s*자산|알트코인"
        r"|코인\s*(투자|거래|선물|리딩|채굴|시세)"
        r"|(?:ICO|에어드[랍롭]|스테이킹|디파이|DeFi)", re.IGNORECASE)),
    # Google 부정 행위 조장 — 문서가 드는 예시를 그대로 옮겼다.
    ("PROHIB-ENABLING-DISHONEST", re.compile(
        r"대리\s*시험|시험\s*대리|논문\s*대필|(?:리포트|과제)\s*(?:대필|대행)"
        r"|(?:후기|리뷰|평점|별점)\s*(?:조작|대행|구매|알바|작업)"
        r"|위조\s*(?:여권|졸업장|서류|신분증|증명서)|졸업장\s*제작"
        r"|해킹\s*(?:대행|의뢰|프로그램)|계정\s*(?:도용|해킹)"
        r"|(?:카톡|카카오톡|문자)\s*(?:해킹|감시|염탐)")),
    # Google 위험한 제품 — 판매·구매 맥락이 있을 때만. '금연'·'흡연 예방'을 잡으면 안 된다.
    ("PROHIB-DANGEROUS", re.compile(
        r"(?:전자\s*담배|액상\s*니코틴|연초|담배)\s*[^\n]{0,8}?(?:판매|구매|주문|배송|최저가|직구)"
        r"|(?:대마초?|필로폰|엑스터시|케타민|아이스)\s*[^\n]{0,8}?(?:판매|구입|구매|거래)"
        r"|(?:총기|권총|소총|사제\s*총)\s*[^\n]{0,8}?(?:판매|부품|제작|도면)"
        r"|(?:전기\s*충격기|삼단봉|가스총)\s*[^\n]{0,8}?(?:판매|구매)"
        r"|폭발물\s*(?:제조|제작)")),
    # Google 데이팅 — 정책 문서가 한국어 표현을 직접 금지 사례로 든다.
    # '성행위'만 두면 성교육·보건 페이지가 통째로 걸린다. 거래 맥락만 본다.
    ("RESTRICT-DATING", re.compile(
        r"원조\s*교제|조건\s*만남|애인\s*대행|에스코트\s*(?:서비스|알바)|성매매"
        r"|스폰서\s*(?:구함|만남|알바)|유사\s*성행위")),
    # Google 주류 — 주류 광고 자체가 아니라 '무책임한' 표현만 본다.
    # "술을 줄이면 건강에 좋습니다"가 걸리면 안 된다. 사이에 절주·금주 말이
    # 끼면 매치를 포기하도록 틈을 막았다.
    ("RESTRICT-ALCOHOL", re.compile(
        r"(?:술|음주|한\s*잔)(?:(?!줄이|끊|금주|절주|자제|않|말)[^\n]){0,14}?"
        r"(?:건강|피로\s*회복|혈액\s*순환)[^\n]{0,4}?(?:좋|도움)"
        r"|(?:술|음주)(?:(?!줄이|끊|금주|절주|자제|않|말)[^\n]){0,14}?"
        r"(?:인기|매력|자신감|능력)[^\n]{0,6}?(?:올라|높아|생[긴겨])"
        r"|폭탄주|말아\s*마시|끝까지\s*원샷")),
    # Google 신뢰할 수 없는 주장 — "구체적인 성과를 주장하는 사용 후기에는 …
    # 면책 조항을 명시해야 합니다". 수치를 단정하는 후기만 본다.
    # '줄었'은 뺐다 — "재고가 5kg 줄었습니다"가 걸린다.
    ("MIS-FAKE-TESTIMONIAL", re.compile(
        r"\d+\s*(?:kg|킬로)\s*(?:이상\s*)?(?:빠졌|감량했|뺐)"
        r"|(?:후기|체험담)[^\n]{0,12}?\d+\s*(?:kg|킬로)")),
]

THIN_CONTENT_CHARS = 300
IP_HOST = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
KEYWORD_MIN_LEN = 2
RELEVANCE_THRESHOLD = 0.3


def _make(code: str, *, evidence: str = "", detail_suffix: str = "") -> Finding:
    p = POLICY_BY_CODE[code]
    return Finding(
        code=p.code,
        title=p.title,
        severity=p.severity,
        enforcement=p.enforcement,
        source=Source.RULE,
        detail=p.description + (f" {detail_suffix}" if detail_suffix else ""),
        evidence=evidence,
        fix=p.fix,
    )


def _contains_any(haystack: str, needles: list[str]) -> str:
    low = haystack.lower()
    for n in needles:
        if n.lower() in low:
            return n
    return ""


def _search_any(text: str, patterns: list[re.Pattern[str]]) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(0)
    return ""


# ---------------------------------------------------------------------------
# 부재 감지
# ---------------------------------------------------------------------------

def check_absence(snap: PageSnapshot, ad_copy: str) -> list[Finding]:
    findings: list[Finding] = []

    if snap.fetch_error or snap.status_code >= 400:
        reason = snap.fetch_error or f"HTTP {snap.status_code}"
        findings.append(_make("DEST-NOT-WORKING", evidence=reason))
        return findings  # 페이지를 못 읽었으면 나머지 판정은 의미가 없다

    text = snap.combined_text
    haystack = text + "\n" + " ".join(snap.links)

    # 개인정보를 실제로 받는가. 페이지 전체 텍스트로 판단하면 푸터의
    # '주소: 서울시…' 때문에 검색창만 있는 페이지가 전부 걸린다.
    # 입력 타입(email/tel/password)이거나, **폼 안쪽** 문구에 단서가 있을 때만.
    collects_pii = snap.has_form and (
        bool(PII_INPUT_TYPES & set(snap.form_input_types))
        or bool(_contains_any(snap.form_text, PII_FIELD_HINTS))
    )

    if collects_pii:
        # 1) 개인정보처리방침 — 상시 공개하는 문서가 있는가
        if not _contains_any(haystack, PRIVACY_HINTS):
            findings.append(_make(
                "DATA-NO-PRIVACY-POLICY",
                detail_suffix="입력 폼이 감지되었으나 방침 링크를 찾지 못했습니다.",
            ))

        # 2) 수집·이용 동의 — 수집 시점에 받는 행위가 있는가.
        #    방침이 있어도 이건 따로 필요하다. 둘은 대체 관계가 아니다.
        consent = _search_any(text, CONSENT_PATTERNS)
        if not consent:
            findings.append(_make(
                "KR-NO-CONSENT",
                detail_suffix="입력 폼이 감지되었으나 동의 문구를 찾지 못했습니다.",
            ))
        else:
            missing = [
                label for label, hints in CONSENT_ITEM_HINTS.items()
                if not _contains_any(text, hints)
            ]
            if missing:
                findings.append(_make(
                    "KR-INCOMPLETE-CONSENT",
                    evidence=consent,
                    detail_suffix=f"확인되지 않은 항목: {', '.join(missing)}.",
                ))

    has_commerce_intent = bool(_contains_any(text + " " + ad_copy, COMMERCE_INTENT))

    # 사업자 정보는 **거래를 하는 페이지**에 있어야 하는 것이다. 가격·방침은
    # 조건부로 판정하면서 이것만 모든 페이지에 무조건 걸면, 정보성 블로그형
    # 랜딩이 전부 지적을 받는다.
    if (has_commerce_intent or collects_pii) and not _search_any(text, CONTACT_PATTERNS):
        findings.append(_make(
            "MIS-BUSINESS-IDENTITY",
            detail_suffix=("거래를 유도하거나 개인정보를 받는 페이지입니다."),
        ))

    if has_commerce_intent and not _search_any(text, PRICE_PATTERNS):
        findings.append(_make(
            "MIS-DISHONEST-PRICING",
            detail_suffix="구매 유도 문구는 있으나 가격 표기를 찾지 못했습니다.",
        ))

    findings += _check_thin_content(snap)

    return findings


def _check_thin_content(snap: PageSnapshot) -> list[Finding]:
    """콘텐츠가 실제로 빈약한가, 아니면 이미지 안에 있는가.

    국내 랜딩페이지는 본문 전체가 한 장의 긴 이미지인 경우가 흔하다.
    HTML 텍스트만 세면 그런 페이지가 전부 '독자적 콘텐츠 부족'으로 잡힌다 —
    이미지에서 글자를 읽어놓고 "본문 249자"라고 지적하는 건 앞뒤가 안 맞는다.

    그렇다고 그냥 넘길 것도 아니다. 글자가 이미지에만 있으면 심사 크롤러가
    못 읽을 수 있고 접근성도 0이라, 별개의 (더 낮은) 항목으로 알려준다.

    이 함수는 길이만 재므로 ocr_text를 봐도 된다. 패턴 룰이 combined_text만
    보는 것과는 다른 문제다 — 저기서는 근거의 출처가 흐려지는 게 문제였다.
    """
    body = len(snap.text.strip())
    if body >= THIN_CONTENT_CHARS:
        return []

    from_images = len(snap.ocr_text.strip())
    if body + from_images >= THIN_CONTENT_CHARS:
        # 내용은 있다. 다만 HTML이 아니라 이미지 안에 있다.
        return [_make(
            "DEST-IMAGE-ONLY-CONTENT",
            evidence=f"본문 {body}자 · 이미지에서 읽은 글자 {from_images}자",
        )]

    return [_make(
        "DEST-INSUFFICIENT-CONTENT",
        evidence=(f"본문 {body}자" if not from_images
                  else f"본문 {body}자 · 이미지 포함 {body + from_images}자"),
    )]


# ---------------------------------------------------------------------------
# 광고 ↔ 방문 페이지 대조
# ---------------------------------------------------------------------------

# 붙여 쓰는 조사·어미. 긴 것부터 떼어내야 '에서'가 '에'로 잘리지 않는다.
_PARTICLES = (
    "으로써", "으로서", "에서는", "이라는", "에게서", "까지는",
    "으로", "에서", "에게", "부터", "까지", "라는", "이나", "하고",
    "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "과", "와", "로",
)
# 이보다 짧아지면 떼지 않는다. '주를' → '주'는 남는 게 없다.
_STEM_MIN = 2


def _strip_particle(token: str) -> str:
    """'원두를' → '원두'. 조사가 붙은 채로 비교하면 같은 말이 안 맞는다.

    형태소 분석기를 쓰면 정확하지만 무거운 의존성이 붙는다. 광고 문구와
    랜딩 본문을 맞춰보는 데는 빈출 조사 몇 개를 떼는 것으로 충분하다.
    """
    for p in _PARTICLES:
        if token.endswith(p) and len(token) - len(p) >= _STEM_MIN:
            return token[: -len(p)]
    return token


def _keywords(text: str) -> set[str]:
    """한글·영문 토큰. 조사를 떼어 어간만 남긴다."""
    tokens = re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", text)
    out = set()
    for t in tokens:
        stem = _strip_particle(t) if _is_hangul(t) else t
        if len(stem) >= KEYWORD_MIN_LEN:
            out.add(stem.lower())
    return out


def _is_hangul(token: str) -> bool:
    return "가" <= token[0] <= "힣"


def check_ad_page_match(snap: PageSnapshot, ad_copy: str) -> list[Finding]:
    """공식 정책의 Unclear relevance / Unavailable offers 대응."""
    findings: list[Finding] = []
    if snap.fetch_error or not ad_copy.strip():
        return findings

    page_text = snap.combined_text.lower()

    # 1) 관련성 — 광고 키워드가 페이지에서 얼마나 확인되는가
    ad_keywords = _keywords(ad_copy)
    if len(ad_keywords) >= 3:
        found = sum(1 for k in ad_keywords if k in page_text)
        ratio = found / len(ad_keywords)
        if ratio < RELEVANCE_THRESHOLD:
            missing = sorted(k for k in ad_keywords if k not in page_text)[:5]
            findings.append(_make(
                "MIS-UNCLEAR-RELEVANCE",
                evidence=", ".join(missing),
                detail_suffix=(
                    f"광고 키워드 {len(ad_keywords)}개 중 {found}개만 페이지에서 확인됩니다."
                ),
            ))

    # 2) 약속한 혜택 — 광고에 있는 할인·혜택이 페이지에도 있는가
    for pat in OFFER_PATTERNS:
        m = pat.search(ad_copy)
        if not m:
            continue
        offer = m.group(0)
        if not pat.search(snap.combined_text):
            findings.append(_make(
                "MIS-UNAVAILABLE-OFFER",
                evidence=offer,
                detail_suffix="광고에는 있으나 방문 페이지에서 확인되지 않습니다.",
            ))
            break

    return findings


# ---------------------------------------------------------------------------
# 기술 요건
# ---------------------------------------------------------------------------

def check_technical(snap: PageSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    if snap.fetch_error:
        return findings

    parsed_final = urlparse(snap.final_url)
    parsed_orig = urlparse(snap.url)

    if parsed_final.scheme != "https" and snap.has_form:
        findings.append(_make("DATA-INSECURE-COLLECTION", evidence=snap.final_url))

    # netloc을 그대로 비교하면 example.com → www.example.com 이 지적된다.
    # 이건 거의 모든 사이트의 정상 구성이다. 같은 사이트 안에서의 이동은
    # 문제가 아니고, 우리가 잡아야 하는 건 **다른 사이트로 보내는 것**이다.
    orig_site = registrable_domain(parsed_orig.hostname or "")
    final_site = registrable_domain(parsed_final.hostname or "")
    if orig_site and final_site and orig_site != final_site:
        findings.append(_make(
            "DEST-MISMATCH",
            evidence=f"{parsed_orig.netloc} → {parsed_final.netloc}",
        ))

    host = (parsed_final.hostname or "")
    if IP_HOST.match(host):
        findings.append(_make("DEST-UNACCEPTABLE-URL", evidence=host))

    if snap.image_count >= 3 and not any(a.strip() for a in snap.image_alts):
        findings.append(_make("TECH-NO-ALT", evidence=f"이미지 {snap.image_count}개"))

    return findings


# ---------------------------------------------------------------------------
# 금지 표현 패턴
# ---------------------------------------------------------------------------

def check_content_patterns(
    snap: PageSnapshot, ad_copy: str, platform: Platform
) -> list[Finding]:
    findings: list[Finding] = []
    haystack = f"{ad_copy}\n{snap.combined_text}"

    for code, pattern in CONTENT_PATTERNS:
        policy = POLICY_BY_CODE[code]
        if platform not in policy.platforms:
            continue
        m = pattern.search(haystack)
        if m:
            findings.append(_make(code, evidence=m.group(0).strip()))

    return findings


def run_all(snap: PageSnapshot, ad_copy: str, platform: Platform) -> list[Finding]:
    """결정적 룰 전체 실행."""
    findings = check_absence(snap, ad_copy)
    if any(f.code == "DEST-NOT-WORKING" for f in findings):
        return findings
    findings += check_technical(snap)
    findings += check_ad_page_match(snap, ad_copy)
    findings += check_content_patterns(snap, ad_copy, platform)
    return findings
