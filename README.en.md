# adpolicy-precheck

> 한국어: [README.md](README.md) · Design doc: [docs/설계서.md](docs/설계서.md) · Run guide: [docs/실행가이드.md](docs/실행가이드.md)

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

### 2. Cloaking detection — is review seeing something different?

**Direction matters.** This *detects* cloaking; it does not perform it. It sits on the same side as the ad platform.

Deliberate cloaking isn't the common case — accidents are: WAF bot rules blocking review crawlers, geo-redirects, JS-only rendering, or a robots.txt that blocks AdsBot while aiming at SEO scrapers.

The same URL is fetched with **distinct client profiles** (desktop, mobile, bot) and body similarity is compared. A page that answers browsers but fails for the bot is flagged immediately.

**Googlebot's UA is never impersonated.** Detection doesn't need it — divergence between *any* two distinct profiles reveals UA branching. An honestly-identified bot UA is in fact the better probe: if a site treats "a bot" differently, that is exactly the behaviour we're looking for. A test pins this down.

```python
def test_profiles_do_not_impersonate_search_crawlers():
    for ua in CLIENT_PROFILES.values():
        assert "googlebot" not in ua.lower()
```

`robots.txt` is checked separately. AdsBot-Google does **not** follow the global `User-agent: *` rule, so only an explicit AdsBot `Disallow` counts.

### 3. Absence detection — what most tools miss

Finding banned words is easy. Finding **what should be there but isn't** is hard — and in practice that's where most rejections come from.

| Code | Detects | Conditional on |
|---|---|---|
| `DATA-NO-PRIVACY-POLICY` | No privacy policy | Only when a form collects personal data |
| `MIS-BUSINESS-IDENTITY` | No contact / business info | No phone, email or registration number |
| `MIS-DISHONEST-PRICING` | No pricing shown | Only when purchase intent is present |
| `DEST-INSUFFICIENT-CONTENT` | Thin content | Body **plus image text** under 300 chars |
| `DEST-IMAGE-ONLY-CONTENT` | Content lives only in images | Body is short but images carry the content |
| `DEST-NOT-WORKING` | Page not reachable | 4xx / 5xx / timeout |
| `KR-NO-CONSENT` | No collection consent step | Only when a form collects personal data |
| `KR-INCOMPLETE-CONSENT` | Consent missing required disclosures | Only when consent wording exists |

These are context-aware. A company profile page legitimately has no price, so `MIS-DISHONEST-PRICING` fires **only when purchase-intent copy exists**.

**A privacy policy is not consent.** Under Korean law these are separate obligations: the policy is a standing published document, consent is an act performed at the point of collection. Neither substitutes for the other, so they are judged independently — a page with a footer policy link but no consent checkbox still fails. `KR-` items carry their own category and a statute `source`, deliberately kept out of the Google taxonomy so "rejected by review" and "unlawful" don't blur together.

### 4. Image inspection — claims baked into banners

A large share of real rejections come from the **banner, not the body**. "100% guaranteed" as text gets caught, so it goes into the image instead. A text-only checker misses this entirely.

Run against a page whose body is clean and whose problems live only in the banner:

```
[images OFF]  0 findings · score 100 · pass
[images ON]   3 findings · score  30 · fail
   [block][ocr] MIS-UNRELIABLE-CLAIMS  '100% 보장'   ← https://ex.com/img/hero.png
   [block][ocr] RESTRICT-FINANCIAL     '원금 보장'   ← https://ex.com/img/hero.png
   [warn ][ocr] MIS-CLICKBAIT          '단 3자리 남' ← https://ex.com/img/hero.png
```

**No new rules were written.** The same `CONTENT_PATTERNS` run over text read out of the image — with the source image attached so a human can open it.

Where the OCR text is merged decides whether evidence verification survives:

| | Contains | Read by |
|---|---|---|
| `combined_text` | page text only | deterministic rules |
| `verification_text` | page + **OCR text** | `verify_evidence` |

Put OCR text in `combined_text` and body rules claim banner findings as `source=rule`, losing which image it came from. Leave it out of `verification_text` and a model quoting the banner can't be checked, so hallucinations pass. Both directions are pinned by tests.

**Judging the imagery itself** (before/after photos, nudity, counterfeits) needs a VLM and is opt-in via `use_vlm`. There the repo's central premise breaks: **there is no text to quote, so verification is impossible.** That is reflected in the structure rather than hidden — `source: "vlm"`, the lowest scoring weight, `block` downgraded to `warn`, the judged `image_url` always returned, and any finding naming an image we never fetched discarded.

```
source   weight   verifiable
rule      1.0     n/a (decided in code)
ocr       0.85    against OCR text
llm       0.7     against page text
vlm       0.5     no — a human must look
```

### 5. Forced chain-of-thought

Asking a 7B model for "JSON only" makes it jump to conclusions and hallucinate more. The schema puts `analysis` **first**, so the model reasons before it judges.

---

## Quick start

```bash
git clone https://github.com/egoring/adpolicy-precheck
cd adpolicy-precheck
./run.sh                 # Windows: double-click run.bat
```

That creates `.env`, builds, starts, waits for readiness and opens the browser. To drive it yourself:

```bash
cp .env.example .env
docker compose up --build
```

`COMPOSE_PROFILES` in `.env` decides what comes up — so no `--profile` flag is needed. **Note the default is `llm`, which starts a vLLM container and needs an NVIDIA GPU.** Set it empty for rules + OCR only, which needs no GPU.

| `COMPOSE_PROFILES` | Starts | GPU |
|---|---|---|
| (empty) | api + web — rules and OCR | not needed |
| `llm` (default) | + local text model | required |
| `llm,vlm` | + multimodal model for image judgement | required |

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
{
  "platform": "google_ads",
  "url": "https://example.com/lp",
  "ad_copy": "...",
  "use_llm": true,
  "check_images": true,
  "use_vlm": false
}
```

The response carries `findings`, `stats`, and `images` — one entry per inspected image with the text OCR read out of it, **including images with no findings**, so "read it, nothing wrong" is distinguishable from "couldn't read it". `vlm_used` / `vlm_note` say whether image judgement actually ran.

Always check `source` on each finding: `rule` was decided by code, `llm` is a model judgement that passed evidence verification. They carry different weight in scoring (LLM ×0.7).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Status + current LLM config |
| `GET` | `/v1/policies` | Policy catalogue |

**Access control.** By default docker-compose publishes ports on `127.0.0.1` only. To share on a LAN set `BIND_ADDR=0.0.0.0` **and** `API_KEY` — then `/v1/*` requires an `X-API-Key` (or `Authorization: Bearer`) header; `/healthz` stays open. `/v1/check` is rate-limited per client IP (`RATE_LIMIT_PER_MIN`, default 20, `0` disables) and answers `429` with `Retry-After`. The web UI embeds the key at build time, so anyone who can open the UI can read it — put a reverse proxy with auth in front if the UI itself must be protected.

---

## Tests

```bash
cd api && pip install -e ".[dev]" && pytest -q
# 753 passed
```

No network required — the LLM is replaced by a scripted mock, HTML extraction is verified against fixed strings. The most important test is whether **hallucinated evidence is actually discarded**.

---

## What this tool does not do

- **It does not guarantee approval.** It is a pre-check aid based on published policies and observed rejection patterns. Platform policy and review decisions are authoritative.
- **It does not help evade review.** It *detects* cloaking; it does not *perform* it. These are opposite directions — detection helps an advertiser find an accident before the platform does; performing it deceives review. Crawler IP harvesting and reviewer/user page branching are out of scope, permanently.
- **It is not legal advice.** Regulated categories need professional review.

## Known limits

- Policy codes follow the official Google Ads taxonomy (`DEST-`, `MIS-`, `ABUSE-`, `DATA-`, `PROHIB-`/`RESTRICT-`, plus `TT-` for TikTok and `TECH-` for advisory items); each carries its `official_name` and `source` URL. `KR-` items are **not** Google policy — they are Korean statute, kept in their own category. Catalogues still drift — `policies.py` needs periodic updates (current as of 2026-09).
- Cloaking detection compares **server responses** only; divergence that appears after JS execution needs headless collection.
- Geo-based cloaking is invisible from a single origin — multi-region probing is the next step.
- JS-rendered SPAs are read as initial HTML only; headless collection may be needed.
- Patterns are Korean-first; other languages need regex extension.

## See also

- [judge-mcp](https://github.com/egoring/judge-mcp) · [sql-guard-mcp](https://github.com/egoring/sql-guard-mcp) · [browser-guard-mcp](https://github.com/egoring/browser-guard-mcp) · [log-triage-agent](https://github.com/egoring/log-triage-agent) · [llm-sse-gateway](https://github.com/egoring/llm-sse-gateway)

## License

MIT
