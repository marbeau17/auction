# Finance Assessment (LLM-extraction) — Design Sketch

*Drafted 2026-04-23. Not committed. Not scheduled. Review + iterate, then decide.*

## Context

The rule-based `app/core/financial_analyzer.py::FinancialAnalyzer` takes a fully-structured `FinancialInput` dataclass (26 Japanese line items: 売上高, 営業利益, 総資産…) and returns a deterministic `FinancialDiagnosisResult` (A–D grade, max monthly lease, recommendations). **Today, someone has to type every number in by hand from a 決算書 PDF.** That's the friction this feature removes.

The feature: **upload a 決算書 / TDB / TSR PDF → get the same `FinancialDiagnosisResult` back**, with the LLM doing only the extraction step and the existing rule engine doing all the scoring. Optional second LLM call produces narrative commentary beside the deterministic score.

## Non-goals

- Replacing `FinancialAnalyzer`. The rule engine remains the source of truth for grades/thresholds.
- Free-form financial advice from the LLM. The LLM extracts numbers and (optionally) writes a paragraph of context. It does not output scores.
- OCR of scanned image-only PDFs (handled as a separate follow-up if demand exists — Gemini's vision path can do this, but it doubles token cost; gate behind a flag).

## Architecture

```
[PDF upload]
    │
    ▼
[app/core/pdf_text_extractor.py]        ← new; pypdf for text-layer PDFs
    │  (raw text, ~5–30 KB per 決算書)
    ▼
[app/core/finance_llm_extractor.py]     ← new; wraps google-genai
    │  prompt: "Extract these 26 fields as JSON..."
    │  model: gemini-flash-latest
    │  response_mime_type: application/json
    │  response_schema: FinancialInputSchema (Pydantic)
    │
    ▼
[Pydantic validation]                    ← reject if required fields missing
    │
    ▼
[FinancialInput]
    │
    ▼
[FinancialAnalyzer.analyze()]            ← unchanged rule engine
    │
    ▼
[FinancialDiagnosisResult]  +  optional narrative (second LLM call)
    │
    ▼
[Persist to finance_assessments table]   ← for history + re-download
    │
    ▼
[HTTP 200 JSON response]
```

## API shape

New route in `app/api/financial.py`:

```
POST /api/v1/financial/assess-document
    multipart/form-data
        file:     UploadFile (PDF, max 10 MB)
        company_name: str (required; LLM can't reliably infer this)
        narrative:    bool = false (include narrative commentary)
    → 200 {
        diagnosis:        FinancialDiagnosisResult  (existing shape)
        extracted_input:  FinancialInput           (for audit/edit)
        narrative:        str | null
        extraction_warnings: list[str]              (fields the LLM couldn't find)
        llm_tokens_used: { prompt: int, completion: int }
      }
    → 422 if required fields absent from PDF (surface missing list)
    → 413 if file > 10 MB
    → 429 if rate limit hit
```

New route for re-reading:

```
GET /api/v1/financial/assessments/{id}
    → the persisted diagnosis + input + narrative
```

Permission: `require_permission("financial", "write")` for the POST (matches existing `/analyze`); `"read"` for GET, fund-scoped once the invoice-scoping pattern from `301abb9` is ported here.

## Prompt (sketch)

```
System: You extract Japanese financial-statement line items into structured
JSON. Return ONLY the JSON matching the given schema. If a field is not
present in the document, set it to null — do not invent values. Numbers
must be in yen (convert 千円/百万円 units if the source uses them).

User: Company: {{company_name}}
Document text:
---
{{pdf_text}}
---
Return a JSON object with the schema provided.
```

Gemini's structured-output mode (`response_schema` + `response_mime_type="application/json"`) enforces the shape — no free-text JSON-repair needed.

The narrative pass (optional) is a separate call with the extracted data + diagnosis result as context: *"In 2–3 paragraphs, explain this transport company's financial health for a non-specialist reader. Do not contradict the grade of {{grade}}."*

## Reuse vs. new code

| Exists | Reuse |
|---|---|
| `FinancialInput` dataclass (26 fields) | Mirror as a Pydantic `FinancialInputSchema` for the Gemini `response_schema` — same fields, same Japanese semantics |
| `FinancialAnalyzer.analyze()` | Called unchanged with the LLM-extracted input |
| `FinancialDiagnosisResult` | Returned unchanged in the response |
| Existing `POST /analyze` (manual-input) | Keeps working; new route is the additive one |
| RBAC via `require_permission("financial", …)` | Re-use, matching the invoice scoping pattern |

New code (roughly 400 LOC total):
- `app/core/pdf_text_extractor.py` (~60 LOC, pypdf + error handling)
- `app/core/finance_llm_extractor.py` (~150 LOC, Gemini client + prompt + validation + retries)
- `app/db/repositories/finance_assessment_repo.py` (~80 LOC, CRUD)
- `app/api/financial.py` additions (~100 LOC for two routes)
- DB migration for `finance_assessments` table (~30 LOC SQL)

## Dependencies to add

`pyproject.toml` main deps:
- `google-genai>=1.0.0` — current Google SDK (replaces the older `google-generativeai`)
- `pypdf>=5.0.0` — text extraction; MIT license, pure Python, Vercel-lambda-safe

If OCR is later enabled:
- Skip `pytesseract`/Tesseract binary (too heavy for Vercel's 50 MB lambda cap). Use Gemini's native vision input instead — pass the PDF bytes directly.

## Config / env vars

Add to `Settings`:
- `GEMINI_API_KEY` (required; secret)
- `GEMINI_MODEL` default `"gemini-flash-latest"` (override for testing)
- `FINANCE_LLM_ENABLED` default `false` — feature flag for dark launch
- `FINANCE_LLM_MAX_PDF_MB` default `10`
- `FINANCE_LLM_MONTHLY_BUDGET_USD` default `50` — hard cap, fail-closed at the repo layer

## Storage

New Supabase table:
```
finance_assessments
  id              uuid pk
  fund_id         uuid fk → funds(id)       (nullable; for tenant scoping)
  user_id         uuid fk → auth.users(id)
  company_name    text
  pdf_sha256      text                      (dedup hits skip the LLM call — cost saver)
  extracted_input jsonb                     (FinancialInput fields)
  diagnosis       jsonb                     (FinancialDiagnosisResult)
  narrative       text | null
  model           text                      ("gemini-flash-latest@2026-04-23" snapshot)
  prompt_tokens   int
  completion_tokens int
  cost_usd        numeric(10,4)
  created_at      timestamptz default now()
```

`pdf_sha256` dedup: the second upload of the same PDF short-circuits to the cached result. This matters because a sales demo will re-upload the same sample file repeatedly.

## Cost model (rough)

Gemini Flash latest as of 2026-04: ~$0.10 / 1M input tokens, ~$0.40 / 1M output.

Per 決算書 (~20 KB text ≈ 6 K tokens in + 1 K tokens out):
- Extraction: ~$0.0011
- Narrative (optional): ~$0.0006
- **Total: ~$0.0017 per document**

At 1 000 documents / month that's ~$2. The $50/month hard cap in config is a safety net, not a realistic target.

## RBAC / security

- POST requires `("financial", "write")` — admin / operator only (matches `/analyze`).
- GET requires `("financial", "read")` + `fund_id` scoping via the same `_accessible_fund_ids` helper pattern as invoices (`app/api/invoices.py` after `301abb9`). Non-admin users see only their own fund's assessments.
- `pdf_sha256` is hashed, not the PDF itself — do NOT store the PDF bytes (privacy + Supabase storage cost).
- API key lives in Vercel/Render env only. Never echo it to logs.

## Testing

- Unit: `pdf_text_extractor` with fixture 決算書 PDFs (valid, scanned-only, corrupt, password-protected).
- Unit: `finance_llm_extractor` with a stubbed Gemini client that returns canned responses — assert the Pydantic validation catches bad JSON, missing required fields, currency-unit mismatches.
- Integration: full flow with Gemini monkey-patched; assert response shape matches existing `/analyze` contract byte-for-byte in the `diagnosis` key.
- Smoke (manual, pre-merge): one real call to `gemini-flash-latest` with a real PDF to confirm the prompt holds up. Record the result for cost-model calibration.

## Failure modes + mitigation

| Failure | Mitigation |
|---|---|
| LLM invents numbers | Structured output schema + Pydantic validation + cross-check total_assets == total_liabilities + equity (within 1 %) — flag and 422 |
| PDF is image-only (no text layer) | Detect via pypdf (text length < 100 chars), return 422 with message "scanned PDFs are not yet supported" |
| Rate limit | slowapi 60/min per user; Gemini's own limits bubble up as 429 |
| Budget blown | Repo-layer check against `FINANCE_LLM_MONTHLY_BUDGET_USD` before every call; fail-closed |
| LLM response too long (token limit) | Pre-truncate PDF text to 30 K tokens; log if truncation occurs |
| Japanese-vs-English company name mismatches | User supplies `company_name` explicitly — don't trust LLM to extract it |

## Rollout

1. **Phase 0 (this PR):** design doc review + feature-flag scaffolding (`FINANCE_LLM_ENABLED=false`). Zero user impact.
2. **Phase 1:** implementation + tests behind flag. Toggle on for admin users only in staging.
3. **Phase 2:** enable for all operator+ in production. Monitor cost dashboard for a week.
4. **Phase 3:** narrative-commentary opt-in. OCR / image-only PDFs remain deferred.

## Decisions (2026-04-23)

1. **Narrative commentary** — **enabled** as an opt-in (`narrative=true` on the POST). Costs ~$0.0006/doc extra.
2. **PDF sources** — **決算書 only** in Phase 1. TDB/TSR/bank/tax deferred; revisit once real usage data exists.
3. **Fund scoping** — **cross-fund**. Any operator+ can assess any company. No `_accessible_fund_ids` filter on this feature. `fund_id` on the table is a loose tag, nullable, no authorization effect.
4. **Budget cap** — $50/month hard cap in config. Fail-closed at the repo layer.
5. **OCR / image-only PDFs** — **included in Phase 1** via Gemini's native vision path (pass PDF bytes directly when the text layer is empty). No Tesseract, no pytesseract — keeps the Vercel lambda under the 50 MB cap. Cost roughly 2× a text-layer doc (~$0.003 per page-heavy scan), still well under the budget cap.
6. **Regulatory retention** — acknowledged. Japanese accounting records are subject to a 7-year retention rule; add `retention_until` (date) to the table defaulting to `created_at + 7 years` and a nightly job at `scripts/cron/purge_expired_assessments.py` that no-ops anything not yet expired. Phase-1 deliverable.

## Phase-1 scope adjustments based on the decisions above

- `pdf_text_extractor.py` gains a branch: if `len(text) < 100` chars → flag as `needs_vision=True` and return the raw PDF bytes instead.
- `finance_llm_extractor.py` gains a vision mode: when `needs_vision=True`, pass `inline_data: application/pdf` to Gemini instead of text.
- `finance_assessments` table gains `retention_until timestamptz not null default (now() + interval '7 years')` and `needs_vision boolean default false`.
- Cron purge job + a manual `DELETE /api/v1/financial/assessments/{id}` route for user-requested deletion (GDPR-adjacent, not regulatory, but cheap to add).

## Files / paths (at a glance)

New:
- `app/core/pdf_text_extractor.py`
- `app/core/finance_llm_extractor.py`
- `app/db/repositories/finance_assessment_repo.py`
- `docs/finance_assessment_design.md` (this file)
- `tests/unit/test_pdf_text_extractor.py`
- `tests/unit/test_finance_llm_extractor.py`
- `tests/integration/test_api_finance_assessment.py`
- `supabase/migrations/YYYYMMDDHHMMSS_finance_assessments.sql`

Modified:
- `app/api/financial.py` (two new routes)
- `app/config.py` (5 new settings)
- `pyproject.toml` (two new deps)
- `app/middleware/rbac.py::RBAC_MATRIX` — confirm `("financial","read")` + `("financial","write")` already cover it (they do per the matrix)

## Next step

Answer the 6 open questions above, and I'll turn this into an implementation plan with TaskCreate entries + agent grouping. No code lands until that plan is reviewed.
