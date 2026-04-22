---
name: monkey-test
description: Run randomised / fuzzed HTTP traffic against the CVLPOS FastAPI app to surface 500s, broken links, unguarded template renders, and CSRF gaps. Read-only — never modifies files.
---

# monkey-test

Exercise the CVLPOS app with random and adversarial inputs to find crashes that the
curated integration tests miss. This is _smoke fuzzing_, not load testing — the
target is correctness, not throughput.

## Usage

Invoke directly with a scope hint (optional):

- `/monkey-test` — walk the whole app
- `/monkey-test dashboard` — focus a single area (dashboard / simulation / invoice / contract / auth)

## Execution pattern

All traffic goes through an in-process `httpx TestClient` with
`raise_server_exceptions=False` so tracebacks surface as HTTP 500s rather than
crashing the driver. Auth is stubbed by monkey-patching
`app.api.pages._get_optional_user` — monkey tests do not exercise the real Supabase
auth path.

Standard boilerplate:

```python
import os, logging, structlog
logging.getLogger().setLevel(logging.CRITICAL)
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
os.environ.setdefault('APP_ENV', 'test')

import app.api.pages as pmod
async def _fake(request):
    return {'id': 'u1', 'email': 'a@b', 'role': 'admin',
            'plan': 'matsu', 'display_name': 'Admin', 'stakeholder_role': 'admin'}
pmod._get_optional_user = _fake

from app.main import create_app
from fastapi.testclient import TestClient

client = TestClient(create_app(), raise_server_exceptions=False)
```

Then hit routes with random / adversarial payloads.

## Attack surfaces

For each page or endpoint, try at least:

1. **Happy path**: valid GET.
2. **Bad UUIDs**: `/simulation/{id}/contracts`, `/invoices/{id}`, `/proposals/preview/{id}`
   with `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`, `00000000-...`, garbage like
   `"; DROP TABLE x"`, empty strings, very long strings.
3. **Missing form fields**: POST to HTMX form endpoints with subsets of required fields.
4. **Wrong content-type**: send JSON body to endpoints expecting form, and vice versa.
5. **Method substitution**: GET something that only accepts POST, PUT something expecting GET.
6. **CSRF tamper**: omit `X-CSRF-Token`, send wrong value, stale cookie.
7. **Japanese encoding edges**: values with mixed ASCII + 全角 + emoji + zero-width characters.
8. **Extreme numbers**: `mileage_km=0`, `mileage_km=99999999999`, `target_yield_rate=-0.5`,
   `lease_term_months=0`, negatives, NaN-ish strings.
9. **Query param fuzz**: add unknown params, duplicate params, %-encoded garbage.
10. **HTMX/non-HTMX toggle**: same request with and without `HX-Request: true` header to
    catch code paths that only one branch exercises.

## Report format

Findings must be deterministic and actionable. Use this structure:

```
## Scope
<which surfaces were tested>

## Bugs found (HTTP 500 or broken behaviour)

### Finding 1 — <one-line title>
- Repro: `<method> <path>` with payload `...`
- Response: 500 / 404 / unexpected 200 with body `<snippet>`
- Probable cause: <file:line guess>
- Severity: P0 (crash / security) / P1 (UX broken) / P2 (polish)

### Finding 2 — ...

## Requests made: <N>
## Time: <seconds>
```

## Rules

- **Never** edit files, run git, or hit the live prod URL (`auction-ten-iota.vercel.app`).
  Use only the local TestClient.
- If a run takes more than 60 seconds, cap the sample size — monkey testing should
  be fast smoke-level, not exhaustive.
- Do not mutate shared state across agents (Supabase is mocked, but sample_data
  mutations would leak between tests). Prefer pure GETs and stateless POSTs.
- Keep output under 600 words so the orchestrator can aggregate results.
