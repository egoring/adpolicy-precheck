# adpolicy-precheck

[![CI](https://github.com/egoring/adpolicy-precheck/actions/workflows/ci.yml/badge.svg)](https://github.com/egoring/adpolicy-precheck/actions/workflows/ci.yml)

> English: [README.en.md](README.en.md) · 설계 문서: [docs/설계서.md](docs/설계서.md)

**광고를 집행하기 전에, 어떤 항목으로 반려될지 미리 알려주는 점검 도구.**

랜딩 페이지 URL과 광고 문구를 넣으면 Google Ads / TikTok Ads 정책 기준으로 위험 항목을 찾아냅니다. 심사에 넣고 반려를 기다리는 대신, 넣기 전에 고칠 수 있게 하는 것이 목적입니다.

> **쉽게 말하면** — 광고 심사관에게 보내기 전에 미리 봐 주는 검토자입니다. "이 문구는 걸립니다", "이 페이지에는 개인정보처리방침이 없습니다" 하고 근거와 함께 짚어 줍니다.

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

### 2. 부재 감지 — 대부분의 도구가 놓치는 것

금지어를 찾는 건 쉽습니다. 어려운 건 **있어야 하는데 없는 것**이고, 실무 반려 사유는 오히려 이쪽이 많습니다.

| 코드 | 무엇을 잡는가 | 조건부 판정 |
|---|---|---|
| `LP-PRIVACY` | 개인정보처리방침 없음 | 입력 폼이 개인정보를 수집할 때만 |
| `LP-CONTACT` | 연락처·사업자 정보 없음 | 전화·이메일·사업자번호 전부 없을 때 |
| `LP-PRICE` | 가격 미표시 | 구매 유도 문구가 있을 때만 |
| `LP-THIN` | 콘텐츠 부족 | 본문 300자 미만 |
| `LP-UNREACHABLE` | 페이지 접근 불가 | 4xx/5xx/타임아웃 |

맥락 없이 무조건 지적하지 않습니다. 회사 소개 페이지에 가격이 없는 건 정상이므로, **구매 유도 문구가 있을 때만** `LP-PRICE`를 올립니다.

### 3. Chain-of-Thought 강제

7B급 모델에 "JSON만 출력하라"고 하면 사고 과정 없이 결론부터 뱉어 환각이 늘어납니다. 스키마에 `analysis`를 **먼저** 두어 근거를 적은 뒤 판정하게 순서를 고정했습니다.

```json
{
  "analysis": "무엇을 근거로 어떻게 판단했는지 2~4문장",
  "findings": [{ "code": "...", "evidence": "원문 그대로", "reason": "..." }]
}
```

---

## 빠른 시작

```bash
git clone https://github.com/egoring/adpolicy-precheck
cd adpolicy-precheck
cp .env.example .env      # LLM 엔드포인트만 맞춰 주세요
docker compose up --build
```

- 웹 UI → http://localhost:3000
- API 문서 → http://localhost:8080/docs

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
| 로컬 vLLM | `http://host.docker.internal:8000/v1` |
| Ollama | `http://host.docker.internal:11434/v1` |
| OpenAI | `https://api.openai.com/v1` (+ `LLM_API_KEY`) |

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
  "summary": "게재 거부 위험이 큰 항목 2건이 발견되었습니다. 가장 시급한 것은 '절대적·보장성 표현'입니다.",
  "findings": [
    {
      "code": "AD-GUARANTEE",
      "title": "절대적·보장성 표현",
      "severity": "block",
      "source": "rule",
      "detail": "'100% 보장' 같은 절대적 효과 주장은 허위·과장 광고로 분류된다.",
      "evidence": "100% 보장",
      "fix": "'개인차가 있습니다' 등 한정 표현으로 바꾸거나 근거를 제시하세요."
    }
  ],
  "stats": { "rule_findings": 2, "llm_findings_kept": 0, "dropped_no_evidence": 1 }
}
```

`source`를 반드시 확인하세요. `rule`은 코드가 확정한 것이고, `llm`은 근거 검증을 통과한 모델 판단입니다. 점수 계산에서도 가중치가 다릅니다(LLM 0.7배).

### 그 밖의 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/healthz` | 상태 + 현재 LLM 설정 |
| `GET` | `/v1/policies?platform=google_ads` | 점검 항목 카탈로그 |

---

## 구조

```
adpolicy-precheck/
├── api/                        FastAPI + 정책 엔진
│   ├── src/adpolicy/
│   │   ├── models.py           스키마 — 모든 Finding은 evidence를 가진다
│   │   ├── policies.py         정책 카탈로그 (무엇을 볼 것인가)
│   │   ├── rules.py            결정적 룰셋 (부재 감지 + 패턴)
│   │   ├── fetcher.py          페이지 수집 + SSRF 방어
│   │   ├── llm.py              OpenAI 호환 클라이언트
│   │   ├── analyzer.py         CoT 프롬프트 + evidence 역검증
│   │   ├── scoring.py          점수·판정 (결정적)
│   │   └── main.py             API
│   └── tests/                  59건 — 네트워크 없이 실행
└── web/                        Next.js 14 (App Router)
```

## 테스트

```bash
cd api && pip install -e ".[dev]" && pytest -q
# 59 passed
```

네트워크 없이 돕니다. LLM은 각본형 모의 객체(`ScriptedLLM`)로 대체하고, HTML 추출은 고정 문자열로 검증합니다. 가장 중요한 테스트는 **환각 evidence가 실제로 폐기되는지**입니다.

```python
def test_hallucinated_finding_is_dropped():
    raw = payload([
        {"code": "AD-GUARANTEE", "evidence": "100% 보장", "reason": "절대적 표현"},
        {"code": "AD-MEDICAL", "evidence": "암을 치료합니다", "reason": "의학적 주장"},
    ])
    found, stats, _ = parse_findings(raw, snap(), "", Platform.GOOGLE_ADS)

    assert [f.code for f in found] == ["AD-GUARANTEE"]   # 페이지에 있는 것만 남는다
    assert stats["dropped_no_evidence"] == 1
```

---

## 이 도구가 하지 않는 것

- **심사 통과를 보장하지 않습니다.** 공개된 정책과 실무 반려 사례를 바탕으로 한 사전 점검 보조 도구이며, 최종 판단은 각 플랫폼의 공식 정책과 심사 결과를 따릅니다.
- **심사 회피를 돕지 않습니다.** 크롤러 탐지, 클로킹, 심사용/사용자용 페이지 분기 같은 기능은 넣지 않았고 앞으로도 넣지 않습니다. 이 도구의 목적은 **정책을 지키도록 돕는 것**이지 우회하는 것이 아닙니다.
- **법률 자문이 아닙니다.** 표시광고법·의료법 등 국내 규제가 얽힌 사안은 전문가 검토가 필요합니다.

## 설계상의 한계

- 정책은 수시로 바뀌므로 `policies.py`의 카탈로그는 주기적 갱신이 필요합니다.
- 현재 텍스트 기반입니다. 이미지 내부 문구(배너에 박힌 "100% 보장")는 잡지 못합니다 — VLM 연동이 다음 과제입니다.
- JS로 렌더링되는 SPA는 초기 HTML만 읽습니다. 헤드리스 브라우저 수집이 필요할 수 있습니다.
- 한국어 패턴 중심입니다. 다국어는 `rules.py`의 정규식 확장이 필요합니다.

## 함께 보기

같은 원칙("능력을 주되 부주의를 불가능하게", "실패를 상태로 다루고 조용히 죽지 않기")으로 만든 저장소들입니다.

- [judge-mcp](https://github.com/egoring/judge-mcp) — LLM-as-Judge 평가 MCP. 채점기 자체를 골든셋으로 검증
- [sql-guard-mcp](https://github.com/egoring/sql-guard-mcp) — 읽기 전용 SQL 안전 가드
- [browser-guard-mcp](https://github.com/egoring/browser-guard-mcp) — 가드 내장 브라우저 자동화
- [log-triage-agent](https://github.com/egoring/log-triage-agent) — LangGraph 로그 트리아지
- [llm-sse-gateway](https://github.com/egoring/llm-sse-gateway) — SSE 스트리밍 + 폴백 게이트웨이

## 라이선스

MIT
