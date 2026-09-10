# adpolicy-precheck

> 한국어: [README.md](README.md) · Design doc: [docs/설계서.md](docs/설계서.md)

**Find out why your ad would be rejected — before you submit it.**

Give it a landing page URL and your ad copy; it flags policy risks against Google Ads / TikTok Ads rules. The point is to fix problems before review, not to wait for a rejection.

---

## Core design — the LLM judges, the code verifies

Handing policy judgement to an LLM creates two problems: it **invents quotes that aren't on the page**, and it gives different answers for the same input. This project blocks both structurally.

| Layer | Responsibility | Reproducibility |
|---|---|---|
| **Deterministic rules** (`rules.py`) | Absence detection, explicit banned patterns, technical checks | 100% — same input, same output |
| **LLM analysis** (`analyzer.py`) | Contextual judgement (is this exaggerated? misleading?) | Only findings that survive evidence verification |
| **Scoring** (`scoring.py`) | Score and verdict | Computed in code — the LLM is never asked for a score |

### 1. Evidence back-verification — the heart of this repo

If the model claims *"the page says '100% guaranteed'"* but that string isn't actually on the page, **the finding is discarded**.

```python
def verify_evidence(evidence: str, haystack: str, *, min_len: int = 4) -> bool:
    ev = _normalize(evidence)          # strip whitespace + NFKC
    if len(ev) < min_len:
        return False                   # too short — could match by chance
    return ev in _normalize(haystack)
```

Whitespace is stripped before comparison: models routinely reformat spacing when quoting (`100% 보장` → `100 % 보장`), which is reformatting, not hallucination. Different characters are still rejected.

Every discard is reported in `stats`:

```json
"stats": { "llm_raw": 4, "dropped_no_evidence": 2, "dropped_unknown_code": 1, "llm_findings_kept": 1 }
```

### 2. Absence detection — what most tools miss

Finding banned words is easy. Finding **what should be there but isn't** is hard — and in practice that's where most rejections come from.

| Code | Detects | Conditional on |
|---|---|---|
| `LP-PRIVACY` | No privacy policy | Only when a form collects personal data |
| `LP-CONTACT` | No contact / business info | No phone, email or registration number |
| `LP-PRICE` | No pricing shown | Only when purchase intent is present |
| `LP-THIN` | Thin content | Body text under 300 chars |
| `LP-UNREACHABLE` | Page not reachable | 4xx / 5xx / timeout |

These are context-aware. A company profile page legitimately has no price, so `LP-PRICE` fires **only when purchase-intent copy exists**.

### 3. Forced chain-of-thought

Asking a 7B model for "JSON only" makes it jump to conclusions and hallucinate more. The schema puts `analysis` **first**, so the model reasons before it judges.

---

## Quick start

```bash
git clone https://github.com/egoring/adpolicy-precheck
cd adpolicy-precheck
cp .env.example .env
docker compose up --build
```

- Web UI → http://localhost:3000
- API docs → http://localhost:8080/docs

**It works without an LLM.** If none is reachable, it returns deterministic rule findings and explains why in `llm_note`. It does not fail silently.

```bash
curl -X POST localhost:8080/v1/check -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","use_llm":false}'
```

Any OpenAI-compatible endpoint works — local vLLM, Ollama, or OpenAI. Set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`.

---

## API

`POST /v1/check`

```json
{ "platform": "google_ads", "url": "https://example.com/lp", "ad_copy": "...", "use_llm": true }
```

Always check `source` on each finding: `rule` was decided by code, `llm` is a model judgement that passed evidence verification. They carry different weight in scoring (LLM ×0.7).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Status + current LLM config |
| `GET` | `/v1/policies` | Policy catalogue |

---

## Tests

```bash
cd api && pip install -e ".[dev]" && pytest -q
# 59 passed
```

No network required — the LLM is replaced by a scripted mock, HTML extraction is verified against fixed strings. The most important test is whether **hallucinated evidence is actually discarded**.

---

## What this tool does not do

- **It does not guarantee approval.** It is a pre-check aid based on published policies and observed rejection patterns. Platform policy and review decisions are authoritative.
- **It does not help evade review.** No crawler detection, no cloaking, no serving different content to reviewers — not now, not later. The purpose is to help you *comply*, not to get around the rules.
- **It is not legal advice.** Regulated categories need professional review.

## Known limits

- Policy catalogues drift; `policies.py` needs periodic updates.
- Text-only today — claims baked into banner images aren't caught. VLM integration is the next step.
- JS-rendered SPAs are read as initial HTML only; headless collection may be needed.
- Patterns are Korean-first; other languages need regex extension.

## See also

- [judge-mcp](https://github.com/egoring/judge-mcp) · [sql-guard-mcp](https://github.com/egoring/sql-guard-mcp) · [browser-guard-mcp](https://github.com/egoring/browser-guard-mcp) · [log-triage-agent](https://github.com/egoring/log-triage-agent) · [llm-sse-gateway](https://github.com/egoring/llm-sse-gateway)

## License

MIT
