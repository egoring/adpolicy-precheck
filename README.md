# adpolicy-precheck

[![CI](https://github.com/egoring/adpolicy-precheck/actions/workflows/ci.yml/badge.svg)](https://github.com/egoring/adpolicy-precheck/actions/workflows/ci.yml)

> English: [README.en.md](README.en.md)

**광고를 집행하기 전에, 어떤 항목으로 반려될지 미리 알려주는 점검 도구.**

랜딩 페이지 URL과 광고 문구를 넣으면 Google Ads / TikTok Ads 정책 기준으로 위험 항목을 찾아냅니다. 심사에 넣고 반려를 기다리는 대신, 넣기 전에 고칠 수 있게 하는 것이 목적입니다.

> **쉽게 말하면** — 광고 심사관에게 보내기 전에 미리 봐 주는 검토자입니다. "이 문구는 걸립니다", "이 페이지에는 개인정보처리방침이 없습니다" 하고 근거와 함께 짚어 줍니다.

---

## 목차

| | |
|---|---|
| [빠른 시작](#빠른-시작) | Docker 하나로 실행 |
| [핵심 설계](#핵심-설계--판단은-llm-사실-확인은-코드) | **이 저장소에서 가장 볼 만한 부분** — 왜 이렇게 만들었는지 |
| [MCP 서버](#mcp-서버--에이전트-앞에-세우는-게이트) | 광고 문구를 만드는 에이전트가 스스로 검증하게 |
| [정확도 측정](#정확도-측정--골든셋과-재현율) | 예측이 맞았는지 채점하는 장치 |
| [생태계 안에서의 위치](#생태계-안에서의-위치) | 사전 점검 ↔ 사후 모니터링의 경계 |
| [API](#api) · [구조](#구조) · [테스트](#테스트) | 레퍼런스 |
| [하지 않는 것](#이-도구가-하지-않는-것) · [한계](#설계상의-한계) | 경계를 먼저 밝힙니다 |

---

## 빠른 시작

```bash
git clone https://github.com/egoring/adpolicy-precheck
cd adpolicy-precheck
./run.sh                  # Windows: run.bat 을 더블클릭
```

`.env` 생성, 빌드, 기동, 준비 대기, 브라우저 열기까지 한 번에 합니다. Docker Desktop 외에는 아무것도 필요 없습니다.

직접 돌리고 싶다면,

```bash
cp .env.example .env
docker compose up --build
```

`.env`의 `COMPOSE_PROFILES`가 무엇을 함께 띄울지 정하므로 `--profile`을 매번 붙일 필요가 없습니다.

| `COMPOSE_PROFILES` | 뜨는 것 | GPU |
|---|---|---|
| (비움) | api + web — 룰셋·OCR | 불필요 |
| `llm` (기본) | + 로컬 텍스트 모델 | 필요 |
| `llm,vlm` | + 이미지 자체 판정 모델 | 필요 (VRAM 확인) |

- 웹 UI → http://localhost:3000
- 토큰 사용량 → http://localhost:3000/usage
- API 문서 → http://localhost:8080/docs

> 포트가 이미 쓰이고 있으면 `.env`의 `API_PORT`·`WEB_PORT`를 바꾸세요. LLM 연결이 안 되면 결과의 `llm_note`에 이유가 적혀 나옵니다.

**LLM 없이도 동작합니다.** 서버가 없거나 꺼져 있으면 결정적 룰셋 결과만 반환하고, 이유를 `llm_note`에 담아 알려 줍니다. 조용히 실패하지 않습니다.

```bash
# 룰셋만 (빠르고 재현성 100%)
curl -X POST localhost:8080/v1/check -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","use_llm":false}'
```

### LLM 붙이기

OpenAI 호환 엔드포인트면 무엇이든 됩니다.

| 백엔드 | `LLM_BASE_URL` |
|---|---|
| **Claude Code 구독** | `http://host.docker.internal:8787/v1` (`run.bat claude`) |
| compose `llm` 프로필 | `http://llm:8000/v1` |
| 호스트 vLLM | `http://host.docker.internal:8000/v1` |
| Ollama | `http://host.docker.internal:11434/v1` |
| OpenAI | `https://api.openai.com/v1` (+ `LLM_API_KEY`) |

#### GPU 없이 — Claude Code 구독 그대로 (`run.bat claude`)

`bridge/claude_bridge.py`는 `claude -p`를 OpenAI 호환 `/v1/chat/completions`처럼 보이게 하는 표준 라이브러리 한 파일입니다. 호스트에 pip로 아무것도 깔지 않습니다. GPU도, 모델 다운로드도, WSL2 UVA 문제도 없고, **텍스트 분석과 이미지 판정이 같은 엔드포인트로** 갑니다 — `llm`·`vlm` 컨테이너가 통째로 필요 없어집니다.

이 다리가 조심스럽게 만들어진 이유가 있습니다. 여기로 들어가는 프롬프트에는 **점검 대상 페이지의 본문**, 즉 남이 쓴 글이 그대로 실립니다. "앞의 지시를 무시하고 …를 읽어라"가 섞여 들어올 수 있다는 뜻입니다.

| 지점 | 조치 |
|---|---|
| 텍스트 요청 | 도구를 **하나도** 열지 않음 (`--max-turns 1`) |
| 이미지 요청 | `Read`만, 작업 디렉터리를 그 요청 전용 임시 폴더로 고정 |
| 이미지 입력 | `data:` URL만. http(s)를 넘기면 CLI가 그 주소를 직접 가져가 SSRF 가드를 우회 |
| 프롬프트 전달 | argv가 아니라 stdin. 윈도우 명령줄은 약 8191자에서 **조용히** 잘림 |
| 최종 방어 | api 쪽 근거 역검증 — 페이지에 없는 문장을 인용한 지적은 버려짐 |

#### 로컬 vLLM

이미 받아둔 HuggingFace 캐시가 있으면 compose가 그대로 서빙합니다. `.env`에 캐시 **루트**(`hub`의 부모)를 적고 프로필을 켜면 됩니다.

```bash
HF_HOME_HOST=D:/huggingface_cache        # D:\huggingface_cache\hub 인 경우 (Linux/macOS는 ~/.cache/huggingface)
LLM_BASE_URL=http://llm:8000/v1
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ

docker compose up --build      # COMPOSE_PROFILES=llm 이면 llm도 함께 뜹니다
```

`HF_HUB_OFFLINE=1`이 기본이라 캐시에 있는 모델만 쓰고 새로 내려받지 않습니다. NVIDIA GPU가 필요하며, 없으면 Ollama나 룰셋 전용(`use_llm: false`)으로 쓰면 됩니다.

Windows(WSL2)에서는 `VLLM_WSL2_ENABLE_PIN_MEMORY=1`이 필요합니다 — 없으면 `RuntimeError: UVA is not available`로 엔진이 안 뜹니다. compose에 기본으로 들어 있습니다.

---

## 핵심 설계 — 판단은 LLM, 사실 확인은 코드

LLM에게 정책 판단을 맡기면 두 가지 문제가 생깁니다. **없는 문장을 근거라고 지어내고**, 같은 페이지에 매번 다른 답을 냅니다. 이 프로젝트는 그 둘을 구조로 막습니다.

| 계층 | 담당 | 재현성 |
|---|---|---|
| **결정적 룰셋** (`rules.py`) | 부재 감지, 명백한 금지 표현, 기술 요건 | 100% — 같은 입력이면 항상 같은 결과 |
| **LLM 분석** (`analyzer.py`) | 맥락 판단 (과장인가, 오해 소지가 있는가) | 근거 검증을 통과한 것만 채택 |
| **점수·판정** (`scoring.py`) | 종합 점수와 verdict | 코드가 계산 — LLM에게 점수를 묻지 않음 |

### 1. Evidence 역검증 — 이 저장소의 핵심

모델이 *"페이지에 '100% 보장'이라고 적혀 있습니다"* 라고 주장해도, **그 문자열이 실제 페이지에 없으면 그 지적은 폐기**합니다.

```python
def verify_evidence(evidence: str, haystack: str, *, min_len: int = 4) -> bool:
    ev = _normalize(evidence)          # 공백 제거 + NFKC
    if len(ev) < min_len:
        return False                   # 너무 짧으면 우연히 일치할 수 있다
    return ev in _normalize(haystack)
```

공백은 제거하고 비교합니다. 모델은 인용할 때 띄어쓰기를 자주 바꾸는데(`100% 보장` → `100 % 보장`), 그건 환각이 아니라 재포맷이기 때문입니다. 글자 자체가 다르면 여전히 걸러집니다.

폐기 사유는 응답의 `stats`에 그대로 남습니다.

```json
"stats": { "llm_raw": 4, "dropped_no_evidence": 2, "dropped_unknown_code": 1, "llm_findings_kept": 1 }
```

### 2. 클로킹 탐지 — 심사와 사용자에게 다른 콘텐츠가 나가는지

**방향을 분명히 해둡니다.** 이건 클로킹을 *하는* 기능이 아니라 클로킹이 *일어나는지 잡아내는* 기능입니다. 광고 플랫폼이 하는 일과 같은 쪽입니다.

의도적 클로킹만 문제가 아닙니다. 실무에서 더 흔한 건 **사고**입니다.

- WAF·CDN의 봇 차단 규칙이 심사 크롤러를 막음
- 지역 기반 리디렉션으로 크롤러 위치에 따라 다른 페이지가 나감
- JS 전용 렌더링이라 크롤러에는 빈 페이지가 보임
- SEO 목적으로 robots.txt를 막다가 AdsBot까지 차단

같은 URL을 **서로 다른 클라이언트 프로필**(데스크톱·모바일·봇)로 동시에 가져와 본문 유사도를 비교합니다.

```
시나리오 1 — 봇에게만 다른 콘텐츠     → block  유사도 0%
시나리오 2 — WAF가 봇만 차단(403)      → block  "브라우저에는 정상, 봇에는 실패"
시나리오 3 — 반응형으로 약간만 다름     → 정상   유사도 97%
```

**Googlebot UA를 사칭하지 않습니다.** 크롤러를 흉내내는 건 그 자체로 회색지대이고, 애초에 필요가 없습니다 — 프로필 간 *차이*만 보면 UA 분기는 그대로 드러나니까요. 오히려 정직하게 봇임을 밝힌 UA가 더 좋은 탐지 도구입니다. 사이트가 "봇"을 다르게 대우한다면 그게 바로 찾던 행동이기 때문입니다. 이 원칙은 테스트로 고정돼 있습니다.

```python
def test_profiles_do_not_impersonate_search_crawlers():
    for ua in CLIENT_PROFILES.values():
        assert "googlebot" not in ua.lower()
        assert "adsbot" not in ua.lower()
```

`robots.txt`도 확인합니다. **AdsBot-Google은 전역 `User-agent: *` 규칙을 따르지 않는다**는 점이 중요해서, AdsBot을 명시적으로 `Disallow`한 경우만 차단으로 판정합니다.

### 3. 부재 감지 — 대부분의 도구가 놓치는 것

금지어를 찾는 건 쉽습니다. 어려운 건 **있어야 하는데 없는 것**이고, 실무 반려 사유는 오히려 이쪽이 많습니다.

| 코드 | 무엇을 잡는가 | 조건부 판정 |
|---|---|---|
| `DATA-NO-PRIVACY-POLICY` | 개인정보처리방침 없음 | 입력 폼이 개인정보를 수집할 때만 |
| `MIS-BUSINESS-IDENTITY` | 연락처·사업자 정보 없음 | 전화·이메일·사업자번호 전부 없을 때 |
| `MIS-DISHONEST-PRICING` | 가격 미표시 | 구매 유도 문구가 있을 때만 |
| `DEST-INSUFFICIENT-CONTENT` | 독자적 콘텐츠 부족 | 본문 + 이미지 속 글자가 300자 미만 |
| `DEST-IMAGE-ONLY-CONTENT` | 본문이 이미지에만 있음 | 본문은 짧지만 이미지에 내용이 있을 때 |
| `DEST-NOT-WORKING` | 방문 페이지 작동 불가 | 4xx/5xx/타임아웃 |
| `KR-NO-CONSENT` | 수집·이용 동의 절차 없음 | 입력 폼이 개인정보를 수집할 때만 |
| `KR-INCOMPLETE-CONSENT` | 동의 고지사항 누락 | 동의 문구는 있을 때만 |

맥락 없이 무조건 지적하지 않습니다. 회사 소개 페이지에 가격이 없는 건 정상이므로, **구매 유도 문구가 있을 때만** 가격 항목을 올립니다.

#### 처리방침과 동의는 다른 것입니다

국내 랜딩페이지에서 자주 뒤섞이는 지점이라 따로 판정합니다. **개인정보처리방침**은 상시 공개하는 문서고, **수집·이용 동의**는 수집 시점에 받는 행위입니다. 하나가 다른 하나를 대신하지 못합니다.

```
① 방침만 있음 (가장 흔함)
   [block] KR-NO-CONSENT            개인정보 수집·이용 동의 절차 없음

② 체크박스만 있음
   [block] DATA-NO-PRIVACY-POLICY   개인정보처리방침 없음
   [warn ] KR-INCOMPLETE-CONSENT    → 누락: 수집·이용 목적, 수집 항목, 보유·이용 기간, 거부권 고지

③ 동의는 있는데 거부권 누락
   [warn ] KR-INCOMPLETE-CONSENT    → 누락: 거부권 고지

④ 둘 다 갖춤
   (개인정보 관련 지적 없음)
```

"동의"라는 낱말만으로는 잡지 않습니다. 이용약관 동의·마케팅 수신 동의와 섞이기 때문에, `개인정보`와 `수집/이용`이 `동의` 근처에 함께 있을 때만 인정합니다.

### 4. 반려와 계정 정지를 같은 것으로 취급하지 않습니다

광고 하나가 반려되는 것과 계정이 **영구 정지**되는 것은 광고주에게 완전히 다른 사건입니다. 그런데 대부분의 점검 도구는 둘 다 "위반"으로 뭉뚱그립니다. Google은 이 둘을 문서에서 명확히 나눠 두었습니다.

| 등급 | 결과 | 해당 |
|---|---|---|
| `suspend` | **사전 경고 없이 즉시·영구 정지.** 재광고 불가 | 중대한 위반 10개 — 시스템 우회(클로킹 포함), 조직적 기만, 위조품, 악성 소프트웨어 등 |
| `strike` | 주의 → 1차 경고(3일 일시정지) → 2차(7일) → 3차 정지 | 부정 행위 조장, 클릭베이트, 총기·담배, 대가성 성행위 등 18개 |
| `disapprove` | 광고 비승인. 누적 시 최소 7일 전 예고 후 정지 | 나머지 전부 |

등급은 제 판단이 아니라 **정책 문서에 박혀 있는 정형 문장**으로 갈랐습니다. 정지급 문서에는 `"사전 경고 없이 즉시 해당 Google Ads 계정을 정지하며 …"`가, 반려급 문서에는 `"이 정책을 위반해도 사전 경고 없이 바로 계정이 정지되지는 않습니다"`가 들어 있습니다.

그래서 점수를 **두 축**으로 냅니다. 반려 위험 0~100점과, 계정 정지 위험 등급. 반려 20건보다 정지 1건이 치명적인데 한 점수로 합치면 그 사실이 묻히기 때문입니다.

```
등급: suspend | 즉시정지 1건 | 경고누적 1건
코드: ABUSE-AUTO-REDIRECT, ABUSE-HIDDEN-TEXT
"사전 경고 없이 계정이 즉시 정지될 수 있는 항목이 1건입니다. …"
```

한 가지는 일부러 올리지 않습니다. **VLM이 이미지를 보고 한 추측은 절대 정지급으로 보고하지 않습니다.** 인용할 문구 하나 없는 모델 판단을 근거로 "계정이 정지됩니다"라고 말할 수는 없습니다.

#### 클로킹·우회는 추가 요청 없이 HTML에서 봅니다

| 신호 | 근거 조항 | 등급 |
|---|---|---|
| 클라이언트별 콘텐츠 차이 | 시스템 우회: 클로킹 | `suspend` |
| 자동 리디렉션 (meta refresh, 진입 즉시 location 변경) | 시스템 우회 / 도착 페이지 환경 | `suspend` |
| 본문을 덮는 전면 레이어 + 스크롤 잠금 | 클로킹 — "Google이 … 정책 위반 여부를 확인할 수 없는 경우" | `suspend` |
| 숨긴 텍스트·폭 없는 유니코드 | 회피적 광고 콘텐츠 | `strike` |
| 타 도메인 최종 착지 | 도착 페이지 불일치 | `disapprove` |
| 프레임으로 감싼 타 도메인 콘텐츠 | 고유 콘텐츠 부족 — 미러링·프레이밍 | `disapprove` |
| 브리지·도어웨이 페이지 | 고유 콘텐츠 부족 | `disapprove` |

#### 광고 파라미터로 갈라지는 경우 — User-Agent 비교의 사각지대

위 표는 전부 **누가 보느냐(User-Agent)**를 축으로 합니다. 그런데 실무에서 더 자주 쓰이는 축은 **어떻게 들어왔느냐**입니다. 심사 크롤러는 광고를 클릭해서 오지 않으므로 도착 URL에 `gclid`가 붙지 않습니다. 그래서 "`gclid`가 있으면 진짜 페이지, 없으면 얌전한 페이지"로 짜두면 UA를 아무리 바꿔 비교해도 **전부 얌전한 쪽만** 보입니다.

같은 주소를 파라미터 조합별로 가져와 비교합니다. 클릭 ID는 형식만 맞춘 **가짜 값**입니다 — 진짜를 쓰면 남의 광고 통계를 더럽힙니다.

```
[suspend][block] ABUSE-PARAM-CLOAKING
   gclid를 붙였을 때 본문 유사도 0.00 (대조군끼리는 1.00)
```

**대조군이 핵심입니다.** 파라미터를 붙인 쪽과 안 붙인 쪽이 다르다는 것만으로는 아무것도 증명되지 않습니다. 배너가 돌아가는 쇼핑몰은 같은 주소를 두 번 불러도 본문이 달라지기 때문입니다. 그래서 먼저 아무것도 안 바꾸고 한 번 더 불러 **잡음의 크기를 재고**, 파라미터를 붙였을 때의 차이가 그보다 뚜렷하게 클 때만 지적합니다. 잡음이 너무 크면 판정을 포기하고 그 사실을 말합니다 — "문제없음"과 "판정 못 함"은 다릅니다.

```
같은 주소를 두 번 불러도 본문이 달라져(유사도 0.00) 파라미터의 영향을 가려낼 수 없었습니다.
```

요청이 4회 늘어나므로 `probe_params: false`로 끌 수 있습니다.

#### 스크립트로 본문을 갈아끼우는 구조 — 프로필 비교의 사각지대

JS로 콘텐츠를 채우면 데스크톱·모바일·봇 **세 프로필이 전부 똑같은 빈 껍데기**를 받습니다. 유사도 100%라 위 클로킹 검사는 "정상"이라고 말합니다. 실제 내용은 그 뒤 서버가 정하고, 서버는 언제든 다른 걸 내려줄 수 있습니다.

```
[warn][disapprove] ABUSE-SERVER-RENDERED-BODY
   본문 0자인데 서버에서 받아 화면에 꽂는 코드가 있음 · 호출 대상 '/api/getValue.php?lp=12'
[warn][strike]     ABUSE-OBFUSCATED-SCRIPT      eval(atob(...))
```

**여기서 증명되는 건 "바꿔치기했다"가 아니라 "바꿔치기할 수 있는 구조이고 심사 대상 본문이 응답에 없다"까지입니다.** 그래서 등급을 올리지 않습니다. SPA·CMS면 정상일 수 있고, 그 이상을 말하면 거짓이 됩니다.

판단 조건은 **본문이 응답에 없을 때만**입니다. 요즘 사이트는 대부분 `fetch` + `innerHTML`을 쓰므로 그것만 보면 전부 걸립니다. 처음에 기준을 600자로 뒀다가 본문 400자짜리 정상 쇼핑몰(제품 설명은 HTML에 있고 후기만 lazy-load)이 걸려서 300자로 조였습니다.

#### 실제 바꿔치기는 한 번의 점검으로 못 잡습니다

심사만 통과시키고 갈아끼우는 수법은 **시점이 다른 두 번의 점검**으로만 드러납니다. TikTok은 `"캠페인을 생성한 후 광고의 랜딩 페이지에 변경 사항을 적용했습니다"`를 계정 정지로 이어지는 위반으로 명시합니다.

그래서 응답에 본문 지문을 싣습니다. 다음 점검 때 `expect_fingerprint`로 넘기면 그 사이 바뀐 것이 잡힙니다.

```
1차   content_fingerprint: 0869471882115690
2차   (내용 그대로)           변경 없음
3차   (본문을 갈아끼운 뒤)    [suspend][block] ABUSE-CONTENT-CHANGED
                              직전 0869471882115690 → 지금 117eea82a070f120
```

화면에서는 **지난 점검과 비교** 체크박스로 자동화됩니다. 점검할 때마다 결과가 `data/history.jsonl`에 한 줄씩 쌓이고, 같은 URL을 다시 점검하면 지난번과 대조합니다.

같은 장부가 더 자주 쓰이는 일을 합니다 — **수정 전후 비교**입니다. 실제 작업 흐름은 "돌린다 → 고친다 → 다시 돌린다"인데, 그때 알고 싶은 건 전체 목록이 아니라 무엇이 나아졌는지입니다.

```
1차   점수 17 | MIS-CLICKBAIT, MIS-SUPERLATIVE, RESTRICT-CRYPTO, RESTRICT-FINANCIAL …
      (문제 문구를 고친 뒤)
2차   점수 64 | 3건 해결 · 1건 새로 생김 · 점수 17 → 64 · 본문이 바뀌었습니다
       해결됨   MIS-CLICKBAIT, MIS-SUPERLATIVE, RESTRICT-FINANCIAL
       새로 생김 DEST-INSUFFICIENT-CONTENT
```

마지막 줄이 이 기능의 값어치입니다. 문구를 덜어내다 보니 본문이 짧아져 **콘텐츠 부족이 새로 생겼습니다.** 두 결과를 눈으로 대조했다면 놓쳤을 회귀입니다.

비교 정보는 **항상** 보여주지만, `ABUSE-CONTENT-CHANGED` 지적은 체크박스를 켰을 때만 올립니다. "바뀌었다"는 사실이지 위반이 아니고, 오타를 고쳤다고 '계정 정지 위험'이 뜨면 안 되기 때문입니다. 이미 심사를 통과한 페이지일 때만 켜는 스위치입니다.

```
체크박스 끔   →  "본문이 바뀌었습니다" (정보)        계정 위험 strike
체크박스 켬   →  [suspend][block] ABUSE-CONTENT-CHANGED   계정 위험 suspend
```

지문은 OCR까지 끝난 뒤에 뜹니다 — 본문은 그대로 두고 **배너만 갈아끼우는** 국내에서 더 흔한 수법을 잡기 위해서입니다. 공백과 대소문자는 무시합니다. 오타 수정으로 경보가 뜨면 아무도 안 쓰게 되니까요.

오탐을 줄이는 데 대부분의 품이 들어갔습니다. `display:none`을 세면 탭·모달이 있는 멀쩡한 페이지가 전부 걸리므로 **숨긴 텍스트에 정책 패턴이 걸릴 때만** 지적합니다. `location.href`를 찾으면 "버튼 누르면 장바구니로"가 걸리므로 **이벤트 바인딩이 있는 스크립트 블록은 통째로 건너뜁니다.** 그리고 도메인 비교는 공개 접미사를 알아야 합니다 — 뒤 두 칸만 보면 `livelogin.co.kr`과 `livetopic.co.kr`이 둘 다 `co.kr`이 되어 국내 페이지의 도메인 이동을 하나도 못 잡습니다. 실제로 놓쳤고 테스트로 고정했습니다.

### 5. 이미지 점검 — 배너에 박아 넣은 문구

실무 반려의 상당수가 본문이 아니라 **배너 이미지**에서 나옵니다. "100% 보장"을 텍스트로 쓰면 걸리니까 이미지에 박아 넣는 식이죠. 텍스트만 보는 점검기는 이걸 통째로 놓칩니다.

본문은 완전히 깨끗하고 문제가 전부 배너 안에 있는 페이지로 돌려본 결과입니다.

```
[이미지 점검 OFF]  지적 0건 · 점수 100 · pass

[이미지 점검 ON]   지적 3건 · 점수 30 · fail
   [block][ocr ] MIS-UNRELIABLE-CLAIMS   '100% 보장'    ← https://ex.com/img/hero.png
   [block][ocr ] RESTRICT-FINANCIAL      '원금 보장'    ← https://ex.com/img/hero.png
   [warn ][ocr ] MIS-CLICKBAIT           '단 3자리 남'  ← https://ex.com/img/hero.png
```

**새 룰을 하나도 만들지 않았습니다.** 이미지에서 읽은 글자에 본문과 똑같은 `CONTENT_PATTERNS`를 돌립니다. 다만 **어느 이미지에서 나왔는지**를 붙여서, 그 배너를 바로 열어볼 수 있게 합니다.

#### 엔진은 갈아끼웁니다 — 기본은 PaddleOCR 한국어 모델

한국어 배너에서는 tesseract가 눈에 띄게 약합니다. 글자가 사진 위에 얹혀 있거나, 자간이 넓거나, 굵은 고딕이면 절반을 놓칩니다. 그래서 기본 엔진을 **PaddleOCR의 `korean_PP-OCRv4_rec`** 으로 두고, tesseract는 폴백으로 남겼습니다.

```
OCR_ENGINE=auto        PaddleOCR이 준비돼 있으면 그것, 아니면 tesseract  (기본)
OCR_ENGINE=paddle      PaddleOCR만. 없으면 이유를 남기고 실패로 둔다
OCR_ENGINE=tesseract   예전 동작 그대로
```

바꿔 끼우는 지점은 **한 곳**입니다. `ocr_paddle.read()`는 `(줄 텍스트, 0~100 신뢰도)`로, tesseract 경로의 `_read()`와 똑같은 모양을 돌려줍니다. 그래서 뒤쪽의 신뢰도 필터·점수·병합 로직은 엔진이 무엇이든 그대로 돕니다.

한 가지 손이 더 갑니다. PaddleOCR은 "줄"이 아니라 **검출 박스** 단위로 결과를 주기 때문에, 한 줄이 여러 조각으로 쪼개져 나옵니다. y좌표로 다시 줄을 묶지 않으면 `지금 신청하면 50% 할인` 같은 문구를 정책 패턴이 통째로 놓칩니다. 묶는 기준은 절대 픽셀이 아니라 **글자 높이에 대한 상대값**입니다 — 절대값으로 하면 큰 제목과 작은 본문 중 한쪽이 반드시 틀립니다.

의존성이 ~1.5GB 늘어납니다. 모델은 **빌드할 때** 받아 두므로 런타임은 오프라인에서도 돕니다. 빼고 빌드하려면 `WITH_PADDLE=0`.

무엇이 실제로 읽었는지는 결과 화면의 "읽은 엔진" 표시와 `GET /healthz`의 `ocr_engine_active`로 확인합니다. **설정만 바꿔놓고 예전 엔진이 도는 상황**이 제일 나쁩니다.

#### OCR 설정은 고정하지 않습니다 (tesseract 경로)

배너 조건마다 잘 듣는 전처리가 다릅니다. 확대는 작은 글씨에 크게 도움되지만 그라데이션 배경에서는 오히려 떨어집니다. 하나로 고정하면 어떤 배너는 반드시 손해를 봅니다.

그래서 전처리 후보 × PSM 조합을 돌려보고 **tesseract가 가장 확신한 결과**를 택합니다. 확신도는 TSV의 단어별 confidence를 글자 수로 가중 평균해 잽니다. 충분히 확신하면 남은 조합은 돌리지 않습니다.

```
케이스                    고정(psm6)   신뢰도 선택
그라데이션 + JPEG60           100%        100%
얇은 글꼴 + 작게 + JPEG50       88%        100%
사진 배경 + JPEG40           100%        100%
혼합 크기 + 작은 문자            85%        100%
평균                          93%        100%
```

읽는 데 실패한 부분은 **버립니다.** 사진 위 장식 글자처럼 반쯤 읽히는 구간은 `은 ae [버` 같은 쓰레기로 남는데, 그대로 두면 화면이 지저분한 것보다 더 나쁜 일이 생깁니다 — 그 잡음이 정책 패턴에 우연히 걸려 엉뚱한 지적을 만듭니다. 줄마다 tesseract의 신뢰도를 재서 낮은 줄을 걷어내고, 결과 전체가 조각뿐이면 "읽은 게 없다"로 처리합니다.

```
노이즈만 있는 이미지  →  ''        (그럴듯한 쓰레기를 만들지 않는다)
정상 랜딩페이지       →  97%
```

그래도 한국어 OCR은 완벽하지 않습니다. 그래서 **읽어낸 원문을 화면에 그대로 보여줍니다** — 오독이면 사람이 바로 알아볼 수 있어야 하기 때문입니다.

#### 본문이 이미지에만 있는 페이지

국내 랜딩페이지는 내용 전체가 한 장의 긴 이미지인 경우가 흔합니다. HTML 텍스트만 세면 이런 페이지가 전부 `DEST-INSUFFICIENT-CONTENT`(독자적 콘텐츠 부족)로 잡힙니다 — 이미지에서 글자를 읽어놓고 "본문 249자"라고 지적하는 건 앞뒤가 안 맞습니다.

분량 판정에는 OCR 텍스트를 함께 셉니다. 다만 그냥 넘기지도 않습니다.

| 본문 | 이미지 속 글자 | 판정 |
|---|---|---|
| 충분 | — | 없음 |
| 부족 | 충분 | `DEST-IMAGE-ONLY-CONTENT` (info) — 크롤러가 못 읽을 수 있음 |
| 부족 | 부족 | `DEST-INSUFFICIENT-CONTENT` (warn) — 진짜 빈약한 페이지 |

패턴 룰이 `combined_text`만 보는 것과는 다른 문제입니다. 저기서는 근거의 **출처**가 흐려지는 게 문제였고, 여기서는 **분량**을 재는 것뿐이라 이미지 글자를 세는 게 맞습니다.

#### 근거 역검증이 깨지지 않게 하는 지점

이미지를 넣으면서 가장 조심한 부분입니다. 텍스트를 어디에 합치느냐로 결과가 갈립니다.

| | 무엇이 들어가나 | 누가 보나 |
|---|---|---|
| `combined_text` | 페이지 텍스트만 | 결정적 룰 |
| `verification_text` | 페이지 + **OCR 텍스트** | `verify_evidence` |

OCR 텍스트를 `combined_text`에 넣으면 본문 룰이 배너 문구까지 잡아 `source=rule`로 보고하고, **어느 이미지인지가 사라집니다.** 반대로 `verification_text`에 넣지 않으면 "배너에 '100% 보장'이라 적혀 있다"는 모델의 인용을 대조할 수 없어 환각이 통과합니다. 둘 다 테스트로 고정했습니다.

```python
def test_rules_do_not_see_ocr_text():
    assert "100% 보장" not in snap.combined_text

def test_evidence_verification_does_see_ocr_text():
    assert verify_evidence("확정 수익", snap.verification_text)
```

#### 이미지 자체 판정 (선택)

비포·애프터 사진, 노출, 위조품처럼 **글자가 없는** 문제는 OCR로 못 잡습니다. 멀티모달 모델이 필요합니다. `use_vlm: true`로 켭니다.

여기서 이 저장소의 전제가 하나 무너집니다 — **인용할 문구가 없어 역검증이 불가능합니다.** 그래서 숨기지 않고 구조에 반영했습니다.

- `source: "vlm"` 으로 분리하고 점수 가중치를 가장 낮게 (0.5)
- `block`을 `warn`으로 낮춤 — 검증 못 하는 판단으로 게재 거부를 단정하지 않습니다
- 판정한 `image_url`을 반드시 반환 — 사람이 직접 열어 확인해야 합니다
- 우리가 실제로 받지 않은 이미지나, 텍스트 룰이 담당하는 코드를 올리면 폐기

```
source    가중치   역검증
rule       1.0     불필요 (코드가 판정)
ocr        0.85    OCR 텍스트와 대조 가능
llm        0.7     페이지 텍스트와 대조 가능
vlm        0.5     불가능 — 사람이 확인
```

### 6. 광고 ↔ 방문 페이지 대조

공식 정책의 **Unclear relevance**(관련성 부족)와 **Unavailable offers**(약속한 혜택 부재)는 광고 문구와 페이지를 *함께* 봐야만 잡을 수 있습니다.

```
광고: "지금 30% 할인 유기농 원두 커피 로스팅 배송"
페이지: 자동차 정비소 소개

[warn] MIS-UNCLEAR-RELEVANCE   | "로스팅, 배송, 원두, 유기농, 지금"
[warn] MIS-UNAVAILABLE-OFFER   | "30% 할인"
```

### 7. Chain-of-Thought 강제

7B급 모델에 "JSON만 출력하라"고 하면 사고 과정 없이 결론부터 뱉어 환각이 늘어납니다. 스키마에 `analysis`를 **먼저** 두어 근거를 적은 뒤 판정하게 순서를 고정했습니다.

```json
{
  "analysis": "무엇을 근거로 어떻게 판단했는지 2~4문장",
  "findings": [{ "code": "...", "evidence": "원문 그대로", "reason": "..." }]
}
```

### 8. 광고 문구 자체의 편집 기준 — 한국어에서 제목은 15자입니다

내용에 아무 문제가 없어도 **제목이 한 글자 길면 광고가 나가지 않습니다.** 그리고 이 축은 전부 코드가 100% 결정적으로 판정할 수 있습니다 — 이 프로젝트에서 "고치면 반드시 통과한다"고 말할 수 있는 거의 유일한 부분입니다.

Google 문서의 한 문장이 핵심입니다.

> "한국어, 일본어, 중국어와 같은 2바이트 언어의 경우 문자 한 개를 두 자로 계산해 한도를 적용합니다."

즉 **영문 기준 30자인 제목이 한글로는 15자**, 설명은 45자입니다. 영문 기준으로 써 두고 왜 반려됐는지 못 찾는 경우가 실무에서 흔합니다. 화면에서는 타이핑하는 동안 줄마다 글자 수가 바로 보입니다.

```
[block] AD-HEADLINE-TOO-LONG   1개 초과 — 가장 긴 것 32자(한도 30자): 「가나다라마바사아자차카타파하거너」
[warn]  AD-SYMBOL-ABUSE        장식 기호 6개 「★★★★★★」
[warn]  AD-REPETITION          「원두」 3회
[warn]  AD-SPACING-ABUSE       자간 벌리기 「무 료 상 담」
```

**문서에 없는 것은 넣지 않았습니다.** "여기를 클릭" 같은 일반적 유도 문구는 흔히 금지 항목으로 이야기되지만, 편집 기준 문서를 한국어·영문 양쪽 확인한 결과 그런 조항이 없어 넣지 않았습니다. 이모지도 문서가 이름으로 지목하지는 않아 '기호 남용'으로 묶고 그 사실을 설명에 적었습니다. 없는 근거로 지적하면 이 도구의 다른 판정까지 함께 의심받습니다.


---

## API

### `POST /v1/check`

```json
{
  "platform": "google_ads",
  "url": "https://example.com/landing",
  "ad_copy": "지금 신청하면 효과 100% 보장!",
  "use_llm": true
}
```

응답:

```json
{
  "verdict": "fail",
  "score": 41,
  "summary": "게재 거부 위험이 큰 항목 2건이 발견되었습니다.",
  "findings": [
    {
      "code": "MIS-UNRELIABLE-CLAIMS",
      "title": "신뢰할 수 없는 주장",
      "severity": "block",
      "source": "rule",
      "detail": "일어나기 어려운 결과를 유력한 결과인 것처럼 제시해 사용자를 유인하는 표현은 금지된다.",
      "evidence": "100% 보장",
      "fix": "'개인차가 있습니다' 등 한정 표현으로 바꾸거나 근거를 제시하세요."
    }
  ],
  "stats": { "rule_findings": 2, "llm_findings_kept": 0, "dropped_no_evidence": 1, "profiles_probed": 3 }
}
```

`source`를 반드시 확인하세요. `rule`은 코드가 확정한 것이고, `llm`은 근거 검증을 통과한 모델 판단입니다. 점수 계산에서도 가중치가 다릅니다(LLM 0.7배).

#### 근거가 어디 있는지 — `locations`

지적마다 근거 문구가 나타나는 위치가 붙습니다. 고칠 곳을 바로 찾기 위해서입니다.

| 값 | 위치 |
|---|---|
| `title` · `meta_description` | 페이지 제목 · 메타 설명 |
| `link_text` · `image_alt` · `form` | 링크 글자 · 이미지 alt · 입력 폼 |
| `body` | 본문 (위 필드에서 찾았으면 생략 — 본문에 그 글자가 섞여 있으므로) |
| `image_text` | 이미지 속 글자(OCR) |
| `ad_headline` · `ad_description` · `ad_copy` | 광고 제목 · 설명 · 문구 |
| `mobile:…` | 모바일 화면에만 있는 문구 |

비교는 근거 역검증과 같은 기준(공백·전각 무시)입니다. "본문 120자"처럼 설명형 근거는 위치를 지어내지 않고 비워 둡니다.

#### 알고 있는 오탐 무시 — `ignore_codes`

근거를 갖춘 "업계 1위"처럼, 매번 같은 지적을 보고 싶지 않을 때 코드를 넘깁니다.

```json
{ "url": "https://example.com", "ignore_codes": ["MIS-SUPERLATIVE"] }
```

- 무시한 지적은 점수·판정·요약에서 빠지고, **숨기지 않고** `suppressed`에 따로 담깁니다.
- **계정 정지·경고 누적급 코드는 무시할 수 없습니다**(422). 이걸 가릴 수 있으면 이 도구가 있을 이유가 없습니다.
- 없는 코드도 422입니다 — 오타 난 무시 목록이 조용히 효과 없이 남지 않게.
- 이력에는 무시한 코드까지 적습니다. 무시를 켰다고 "해결됨"으로 보이지 않습니다.
- 웹 화면에서는 지적 카드의 "이 지적 무시" 버튼으로 추가하고, 목록은 브라우저에 남습니다.
- MCP 도구에는 **일부러 노출하지 않았습니다.** 에이전트가 불편한 지적을 스스로 끄면 게이트가 아닙니다.

### 정책 코드 체계

코드는 **Google Ads 공식 정책 분류**를 따릅니다. 임의로 만든 이름이 아니라 심사에 실제로 쓰이는 용어입니다.

| 접두사 | 공식 분류 | 출처 |
|---|---|---|
| `DEST-` | 편집 및 기술 요건 → 방문 페이지 요건 | [answer/6368661](https://support.google.com/adspolicy/answer/6368661) |
| `MIS-` | 금지된 행위 → 허위 진술 | [answer/6020955](https://support.google.com/adspolicy/answer/6020955) |
| `ABUSE-` | 금지된 행위 → 광고 네트워크 악용 | [answer/6020954](https://support.google.com/adspolicy/answer/6020954) |
| `DATA-` | 금지된 행위 → 데이터 수집 및 사용 | [answer/6008942](https://support.google.com/adspolicy/answer/6008942) |
| `PROHIB-` / `RESTRICT-` | 금지된 콘텐츠 · 제한된 콘텐츠 | [answer/6008942](https://support.google.com/adspolicy/answer/6008942) |
| `TT-` | TikTok 광고 정책 전용 항목 | [TikTok 광고 정책](https://ads.tiktok.com/resources/help/article/tiktok-advertising-policies?lang=ko) |
| `KR-` | **Google 정책 아님** — 국내 법령 | [개인정보 보호법](https://www.law.go.kr/법령/개인정보보호법) |

각 항목의 `source`는 상위 개요가 아니라 **그 조항이 실제로 적힌 하위 문서**를 가리킵니다. "허위 진술"까지만 가리키면 어느 조항인지 찾는 데 다시 시간이 듭니다.

한 가지는 대조하다가 바로잡았습니다. `TT-BEFORE-AFTER`의 근거를 TikTok 「체중 관리 및 신체 이미지」로 적어 뒀는데, **그 문서 본문에는 전후 비교라는 표현이 없습니다.** 실제 조항은 TikTok 「오해의 소지가 있는 콘텐츠」의 "전후 결과 비교와 같은 제품 효과 비교"와 Google 「클릭베이트 광고」의 "'전후 비교' 이미지를 사용하여 신체의 극적인 변화를 홍보하는 광고"입니다. 후자 때문에 이 항목은 TikTok 전용이 아니라 **양쪽 플랫폼**에 걸립니다. 그리고 TikTok은 "비교에 대한 주장은 관련 증거를 제공하거나 명확한 면책 고지가 있는 경우에 허용된다"고 명시하므로, 이 항목은 차단이 아니라 경고로 둡니다.

`KR-` 항목은 카테고리와 `source`를 분리해 둡니다. Google 공식 분류에 섞으면 "이게 심사 반려 사유인가, 법 위반인가"가 흐려지기 때문입니다. 테스트로 고정돼 있습니다.

```python
def test_kr_items_are_not_labelled_as_google_policy():
    for p in KR_POLICIES:
        assert p.category == "국내 법령"
        assert "support.google.com" not in p.source
```

`GET /v1/policies`가 각 항목의 `official_name`과 `source` URL을 함께 돌려줍니다.


### 그 밖의 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/healthz` | 상태 + 실제로 준비된 OCR 엔진 |
| `GET` | `/v1/policies?platform=google_ads` | 점검 항목 카탈로그 (제재 등급 포함) |
| `GET` | `/v1/usage?hours=24` | Claude 다리가 기록한 토큰 사용량 |
| `GET` | `/v1/history?url=…` | 그 주소의 점검 이력 |
| `POST` | `/v1/batch` | 여러 건 점검 — 바로 `job_id`를 돌려주고 뒤에서 돌린다 |
| `GET` | `/v1/batch/{job_id}` | 배치 진행 상황과 항목별 결과 |

### 배치 점검 — `/v1/batch`

캠페인 단위로 여러 건을 한 번에 넣습니다. 각 항목은 `/v1/check` 요청과 같습니다(최대 50건).

```bash
curl -X POST localhost:8080/v1/batch -H 'Content-Type: application/json' \
  -d '{"items":[{"url":"https://a.example","ad_copy":"업계 1위"},{"url":"https://b.example"}]}'
# → 202 {"job_id":"…","total":2,"status_url":"/v1/batch/…"}
curl localhost:8080/v1/batch/<job_id>   # status: queued → running → done
```

- 항목은 동시에 `BATCH_CONCURRENCY`(기본 2)건씩 돌고, **한 건이 실패해도 나머지는 계속**합니다(`status: error`, `error`에 이유).
- 속도 한도는 항목마다 한 칸씩 가져갑니다. 한도보다 큰 배치도 받지만 **한도 속도로 흘러갑니다** — 배치로 분당 한도를 우회할 수 없습니다.
- 작업은 프로세스 메모리에 1시간(`BATCH_TTL`) 보관하고, 동시에 `BATCH_MAX_JOBS`(기본 20)개까지 둡니다. 재시작하면 사라집니다 — 오래 남길 기록은 이력 장부에 이미 한 줄씩 적힙니다.
- 작업 번호는 추측할 수 없는 무작위 값입니다. 결과에 점검한 URL이 들어 있기 때문입니다.
- 웹 화면: `/batch` — URL, 광고 문구를 한 줄씩(CSV·스프레드시트 붙여넣기 가능) 넣으면 표로 진행 상황을 보여줍니다.

### 접근 제어

기본값은 **이 컴퓨터에서만** 쓰는 구성입니다. docker-compose가 포트를 `127.0.0.1`에만 엽니다.

| 설정 | 기본 | 설명 |
|---|---|---|
| `BIND_ADDR` | `127.0.0.1` | 포트를 열 주소. 다른 기기와 나눠 쓰려면 `0.0.0.0` — 이때는 `API_KEY`를 꼭 거세요 |
| `API_KEY` | (없음) | 넣으면 `/v1/*`가 `X-API-Key` 또는 `Authorization: Bearer` 헤더를 요구합니다. `/healthz`는 열어 둡니다 |
| `RATE_LIMIT_PER_MIN` | `20` | `/v1/check`를 클라이언트 IP당 분당 몇 번까지 받을지. 넘으면 `429` + `Retry-After`. `0`이면 끔 |

`/v1/check` 한 번이 외부 페이지 여러 개를 가져오고 LLM 토큰을 씁니다. 열어 둔 채 노출되면
남의 서버가 대신 크롤러·LLM 프록시가 되고, `/v1/history`는 누가 무엇을 점검했는지 보여줍니다.

웹 화면에는 `API_KEY`가 빌드 때 그대로 들어갑니다(`NEXT_PUBLIC_API_KEY`). 즉 **웹 화면을 열 수 있는
사람은 키도 볼 수 있습니다.** 웹까지 막아야 한다면 앞단 리버스 프록시에서 인증을 거세요.

---

## MCP 서버 — 에이전트 앞에 세우는 게이트

이 도구의 쓸모는 사람이 대시보드를 여는 쪽보다, **광고 문구를 생성하는 에이전트가 내보내기 전에 스스로 검증하는** 쪽에 있습니다. 그래서 MCP 서버로도 띄울 수 있게 했습니다.

```bash
cd api && pip install -e ".[mcp]"
python -m adpolicy.mcp_server          # stdio (Claude Desktop / Cursor)
python -m adpolicy.mcp_server --http   # streamable HTTP
```

```jsonc
// claude_desktop_config.json
{ "mcpServers": {
    "adpolicy-precheck": {
      "command": "python",
      "args": ["-m", "adpolicy.mcp_server"],
      "env": { "PYTHONPATH": "/path/to/adpolicy-precheck/api/src" }
    } } }
```

| 툴 | 하는 일 |
|---|---|
| `precheck_ad(url, ad_copy, headlines, descriptions, platform)` | 게재 전 점검. `verdict` · `score` · `account_risk` · 증거가 붙은 `findings` |
| `list_policies(platform)` | 무엇을 피해야 하는지 — **문구를 만들기 전에** 부를 것 |
| `explain_policy(code)` | 항목 하나의 전문과 공식 문서 링크 |

에이전트 루프는 이렇게 돕니다.

```
문구·랜딩 URL 생성 → precheck_ad → verdict가 fail이면
findings[].fix를 반영해 수정 → 다시 precheck_ad → 통과하면 게재
```

**읽기 전용입니다.** 광고를 만들지도, 고치지도, 올리지도 않습니다. Google Ads 계정에 접근하는 경로도 없습니다. 가드레일은 스스로 행위하지 않아야 신뢰할 수 있다고 봅니다 — 테스트가 이것을 강제합니다.

```python
async def test_no_tool_can_create_modify_or_publish_ads():
    forbidden = ("create", "update", "delete", "publish", "submit",
                 "resubmit", "upload", "appeal", "mutate",
                 "account", "campaign", "budget")
    for t in await mcp.list_tools():
        assert not any(w in t.name.lower() for w in forbidden)
```

그리고 **점검이 실패하면 실패라고 말합니다.** 게이트가 조용히 통과시키면 게이트가 아닙니다.

```python
async def test_precheck_reports_failure_instead_of_silently_passing():
    ...
    assert "error" in res
    assert "verdict" not in res
    assert "통과로 해석하지 마세요" in res["note"]
```

---

## 정확도 측정 — 골든셋과 재현율

예측만 하고 채점표가 없으면 개선할 방향을 알 수 없습니다. 두 개의 측정 장치를 두었습니다. **라벨의 출처가 다르므로 둘은 경쟁하지 않고 보완합니다.**

### 1. 평가 하네스 — 우리가 만든 라벨

```bash
cd api && python -m adpolicy.evalkit --md eval/report.md
# 케이스 24/24 통과  (0.03s)
# micro  P 100.0%  R 100.0%  F1 100.0%   [TP 17 FP 0 FN 0]
```

네트워크도 LLM도 타지 않습니다. 케이스마다 두 축을 라벨링합니다.

- `expect` — 반드시 나와야 하는 코드
- `forbid` — **나오면 오탐인 코드**

두 번째 축이 핵심입니다. "이 코드가 나와야 한다"만 적으면 정상 페이지에서 엉뚱한 코드가 뜨는 오탐을 잡을 수 없습니다. 실제로 정상 쇼핑몰이 계정 정지급으로 보고된 사고가 있었고, 그 회귀 테스트가 골든셋에 들어 있습니다.

라벨이 없는 코드는 **채점하지 않고** `unscored`로 따로 셉니다. 숨기지 않되, 라벨이 없는 것을 틀렸다고 말하지도 않습니다.

트랩 케이스 6건은 과거 오탐의 회귀 테스트입니다 — "오늘 **만든** 빵"(`오늘만` 오탐), "이웃집 **토토**로"(도박 오탐), "상품코드 08123456789"(전화번호 오인), 검색창만 있는 폼(개인정보 수집 오인) 등.

> **하네스가 첫 실행에서 실제 누락을 찾았습니다.** 카탈로그의 `MIS-CLICKBAIT` 설명은 "클릭베이트 기법이나 **선정적 문구**"라고 적혀 있는데, 정작 규칙은 허위 희소성만 구현하고 있었습니다. 카탈로그와 구현이 어긋나 있던 것입니다. 선정적 유인 갈래를 추가했고, 신규 테스트 10건이 옛 패턴에서 실패합니다.

리포트는 **계정 정지급 오탐을 맨 위에 따로** 올립니다. 반려 오탐과 무게가 다르기 때문입니다. 그리고 모든 비율 옆에 표본 수를 붙입니다 — 3건짜리 F1 100%는 정보가 아니라 착시입니다.

### 2. 반려 복구 루프 — Google의 실제 판정

```bash
python -m adpolicy.ads --md eval/recall_report.md
# 계정 1234567890 (ENABLED) — 반려 3건 · 제한 승인 1건(처리 안 함)
# 반려 사유 4건  (대응 3 · 미대응 1)
# 재현율 66.7%  [hit 2 / miss 1]
# ⚠️ 표본 4건 — 비율을 신뢰하지 마세요.
```

Google Ads API가 알려주는 반려 사유를 수집해 내부 규칙으로 매핑하고, 해당 랜딩페이지를 재점검해 **"우리 사전 점검이 그 사유를 예측했는가"** 를 채점합니다. 결과는 세 갈래로 갈립니다.

| 판정 | 의미 | 조치 |
|---|---|---|
| `hit` | 우리도 잡았다 | — |
| `miss` | 규칙은 있는데 못 잡았다 | 민감도 재검토 |
| `no_rule` | **대응 규칙 자체가 없다** | 신규 규칙 후보 |

세 번째 줄이 그대로 로드맵이 됩니다. 모르는 사유를 조용히 버리면 이 목록이 영원히 보이지 않으므로, `UnmappedLedger`에 격리해서 쌓습니다.

**안전장치**가 이 모듈의 본체입니다.

- 계정이 `ENABLED`가 아니면 **소재를 읽지도 않고 중단**합니다. 계정 정지는 이 시스템이 다루는 문제가 아닙니다
- `APPROVED_LIMITED`는 반려가 아니므로 수집만 하고 처리하지 않습니다
- `SeenIndex`는 **(소재, 사유) 단위**입니다 — 같은 사유로 매 폴링마다 재트리거되면 그 끝은 재제출 루프입니다

> ⚠️ **스키마 미검증** — 개발자 토큰이 없어 실제 API 응답으로 확인하지 못했습니다. 필드명·열거값은 문서를 읽고 옮긴 것입니다. 그래서 `GoogleAdsClient`는 **일부러 구현하지 않았고**, 호출하면 "응답을 덤프해 스키마를 교정한 뒤 구현하라"고 거부합니다. 검증하지 않은 추측이 파이프라인 전체로 번지는 것보다 낫다고 봅니다.

전 구간이 픽스처만으로 끝까지 돕니다. 토큰이 생기면 `GoogleAdsClient` 한 파일만 채우면 됩니다.

---

## 생태계 안에서의 위치

광고 정책 문제를 다루는 도구는 이미 여럿 있습니다. **이 도구가 어느 구간을 맡는지** 선을 그어 둡니다.

```
 문구·페이지 작성        게재 신청         심사        집행 후
        │                   │              │            │
        ▼                   ▼              ▼            ▼
 ┌─────────────┐                                 ┌──────────────┐
 │  이 도구     │  ───────────────────────────►  │ 사후 모니터링 │
 │ (사전 점검)  │                                 │ (BigQuery +  │
 └─────────────┘                                 │  대시보드)    │
        ▲                                        └──────┬───────┘
        │              반려 사유 회수 → 골든셋 반영        │
        └────────────────────────────────────────────────┘
                        (이 저장소의 `adpolicy.ads`)
```

| | 이 도구 | [ads-policy-monitor](https://github.com/google-marketing-solutions/ads-policy-monitor) |
|---|---|---|
| 시점 | **게재 전** | 게재 후 (일 단위 스냅샷) |
| 입력 | URL + 광고 문구 | Google Ads 계정 |
| 계정 필요 | ❌ | ✅ (API 토큰) |
| 답하는 질문 | "이대로 내면 걸릴까?" | "무엇이 반려됐고 추세는 어떤가?" |
| 산출 | 항목별 위반 + 증거 + 수정 방향 | BigQuery 테이블 + Looker Studio |

두 도구는 겹치지 않습니다. 이 저장소가 사후 모니터링을 직접 만들지 않는 이유이기도 합니다 — **대신 그쪽이 회수한 반려 사유를 되먹이는 경로**(`adpolicy.ads`)를 만들었습니다.

접근 방식의 차이도 적어 둡니다. 정책 점검을 LLM에 통째로 맡기는 도구들이 있는데, 이 저장소는 반대 방향을 택했습니다.

| | LLM에 판단을 맡기는 방식 | 이 도구 |
|---|---|---|
| 재현성 | 같은 입력에 다른 답이 나올 수 있음 | 룰셋은 100% 결정적 |
| 환각 | 페이지에 없는 문구를 근거로 들 수 있음 | `verify_evidence`가 역검증해 폐기 |
| 근거 제시 | "위반으로 보입니다" | 본문 몇 번째 글자에 무엇이 있는지 |
| 정책 갱신 | 프롬프트 수정 | `policies.py` 카탈로그 + 공식 문서 링크 |
| LLM의 역할 | 판정 전체 | 룰이 못 보는 맥락만. **사실 확인은 코드가** |

---

## 구조

```
adpolicy-precheck/
├── api/                        FastAPI + 정책 엔진
│   ├── src/adpolicy/
│   │   ├── models.py           스키마 — 모든 Finding은 evidence를 가진다
│   │   ├── policies.py         정책 카탈로그 56항목 (무엇을 볼 것인가)
│   │   ├── rules.py            결정적 룰셋 (부재 감지 + 광고↔페이지 대조 + 패턴)
│   │   ├── adcopy.py           광고 문구 편집 기준 (글자 수·기호·반복)
│   │   ├── cloaking.py         클로킹 **탐지** — 프로필·파라미터 분기 비교
│   │   ├── history.py          점검 이력 장부 (수정 전후 비교)
│   │   ├── fetcher.py          페이지 수집 + SSRF 방어
│   │   ├── llm.py              OpenAI 호환 클라이언트 (멀티모달 포함)
│   │   ├── vision.py           이미지 수집·OCR·VLM 판정
│   │   ├── ocr_paddle.py       PaddleOCR 어댑터 (tesseract 폴백)
│   │   ├── analyzer.py         CoT 프롬프트 + evidence 역검증
│   │   ├── scoring.py          점수·판정 (결정적)
│   │   ├── main.py             HTTP API
│   │   ├── mcp_server.py       MCP 서버 (읽기 전용 툴 3개)
│   │   ├── evalkit/            평가 하네스 — 골든셋으로 정확도 측정
│   │   └── ads/                반려 복구 루프 — Google 판정으로 재현율 측정
│   │       ├── client.py       AdsClient 어댑터 (Fake / Google)
│   │       ├── mapping.py      policy topic → rule code + 미매핑 원장
│   │       ├── watcher.py      반려 감지 + 안전장치
│   │       └── recheck.py      v1 재점검 + 채점
│   ├── eval/golden/            라벨링된 케이스 24건 + 페이지 원문
│   └── tests/                  753건 — 네트워크 없이 실행
├── bridge/claude_bridge.py     Claude Code CLI를 OpenAI 호환으로 (표준 라이브러리만)
└── web/                        Next.js 14 (App Router)
```

## 테스트

```bash
cd api && pip install -e ".[dev]" && pytest -q
# 753 passed

cd web && npm ci && npm run lint && npm test
# 12 passed
```

네트워크 없이 돕니다. LLM은 각본형 모의 객체(`ScriptedLLM`)로 대체하고, HTML 추출은 고정 문자열로 검증합니다. 가장 중요한 테스트는 **환각 evidence가 실제로 폐기되는지**입니다.

```python
def test_hallucinated_finding_is_dropped():
    raw = payload([
        {"code": "MIS-UNRELIABLE-CLAIMS", "evidence": "100% 보장", "reason": "신뢰할 수 없는 주장"},
        {"code": "RESTRICT-HEALTHCARE", "evidence": "암을 치료합니다", "reason": "의학적 주장"},
    ])
    found, stats, _ = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)

    assert [f.code for f in found] == ["MIS-UNRELIABLE-CLAIMS"]   # 페이지에 있는 것만 남는다
    assert stats["dropped_no_evidence"] == 1
```

---

## 이 도구가 하지 않는 것

- **심사 통과를 보장하지 않습니다.** 공개된 정책과 실무 반려 사례를 바탕으로 한 사전 점검 보조 도구이며, 최종 판단은 각 플랫폼의 공식 정책과 심사 결과를 따릅니다.
- **심사 회피를 돕지 않습니다.** 클로킹 *탐지*는 넣었지만 클로킹 *수행*은 넣지 않았고 앞으로도 넣지 않습니다. 둘은 정반대 방향입니다 — 전자는 광고주가 사고를 미리 발견하게 하고, 후자는 심사를 속입니다. 크롤러 IP 목록 수집, 심사용/사용자용 페이지 분기 같은 기능은 이 저장소의 범위 밖입니다.
- **법률 자문이 아닙니다.** 표시광고법·의료법 등 국내 규제가 얽힌 사안은 전문가 검토가 필요합니다.

## 설계상의 한계

경계를 먼저 밝혀 두는 편이 낫다고 생각합니다.

- **JS를 실행하지 않습니다.** 응답 HTML만 읽으므로, 렌더링 후에야 갈리는 클로킹은 구조(§4의 파라미터 분기 스크립트)까지만 보이고 실제로 다른 내용이 나갔는지는 증명하지 못합니다. 그래서 그 항목은 경고에 머물고, 브라우저에서 직접 비교하라고 안내합니다. 헤드리스 수집이 다음 단계입니다.
- **지역 기반 클로킹은 못 잡습니다.** 단일 출발지에서만 검사합니다. 다중 리전 프로브가 필요합니다.
- **PaddleOCR 한국어 모델의 정확도를 측정하지 못했습니다.** 개발 환경에서 모델 CDN에 접근할 수 없어 tesseract 대비 수치를 내지 못했습니다. 엔진을 갈아끼울 수 있게만 해 두었고, 어느 엔진이 실제로 돌고 있는지는 `GET /healthz`가 그대로 알려줍니다. 측정하지 않은 것을 좋다고 적지는 않겠습니다.
- **골든셋 24건은 비율을 말하기엔 적습니다.** 코드별 정답 표본이 대부분 1건이라 F1 100%는 자랑이 아닙니다. 이 하네스의 현재 값어치는 정확도 증명이 아니라 **회귀 방지와 누락 발견**에 있습니다(실제로 첫 실행에서 `MIS-CLICKBAIT`의 구현 누락을 찾았습니다). 실계정 반려 데이터로 확장하는 경로는 `adpolicy.ads`에 만들어 두었습니다.
- **Google Ads API 스키마를 실제 응답으로 검증하지 못했습니다.** 개발자 토큰이 없어 `ads/` 모듈의 필드명·열거값은 문서 기준입니다. 픽스처에 경고를 박아 두었고 테스트가 그것을 확인합니다.
- **정책은 수시로 바뀝니다.** `policies.py`의 카탈로그는 2026-09 기준이며 주기적 갱신이 필요합니다.
- **한국어 패턴 중심입니다.** 다국어는 `rules.py`의 정규식 확장이 필요합니다.
- **인증·요청 제한이 없습니다.** 로컬 실행을 전제로 만들었습니다. 공개 배포한다면 rate limit과 API 키가 먼저입니다 — 그대로 띄우면 남의 사이트를 두들기는 프록시가 됩니다.

## 함께 보기

같은 원칙("능력을 주되 부주의를 불가능하게", "실패를 상태로 다루고 조용히 죽지 않기")으로 만든 저장소들입니다.

- [judge-mcp](https://github.com/egoring/judge-mcp) — LLM-as-Judge 평가 MCP. 채점기 자체를 골든셋으로 검증
- [sql-guard-mcp](https://github.com/egoring/sql-guard-mcp) — 읽기 전용 SQL 안전 가드
- [browser-guard-mcp](https://github.com/egoring/browser-guard-mcp) — 가드 내장 브라우저 자동화
- [log-triage-agent](https://github.com/egoring/log-triage-agent) — LangGraph 로그 트리아지
- [llm-sse-gateway](https://github.com/egoring/llm-sse-gateway) — SSE 스트리밍 + 폴백 게이트웨이

## 라이선스

MIT
