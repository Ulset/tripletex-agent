# Tripletex AI Agent — NM i AI 2026

## Competition
- **Task**: Build an AI agent that completes accounting tasks in Tripletex
- **30 task types**, 56 variants each (7 languages × 8 data sets)
- **Languages**: Norwegian (nb), English, Spanish, Portuguese, Nynorsk, German, French
- **Timeout**: 5 minutes per task
- **Submission URL**: https://app.ainm.no/submit/tripletex
- **Endpoint**: https://tripletex-agent-rzkmnmpmpq-lz.a.run.app/solve
- **Each submission = fresh Tripletex account** — always start from scratch

## Scoring System

### Field-by-Field Verification
After agent responds, the platform queries Tripletex API to verify what was created/modified. Each task has specific checks worth different point values. Example "Create employee" (max 10 pts):
- Employee found: 2 pts
- Correct first name: 1 pt
- Correct last name: 1 pt
- Correct email: 1 pt
- Administrator role assigned: 5 pts

Raw score normalized to 0–1: `correctness = points_earned / max_points`

### Tier Multiplier
| Tier | Multiplier | Examples |
|------|-----------|----------|
| Tier 1 | ×1 | Create employee, create customer |
| Tier 2 | ×2 | Create invoice, register payment |
| Tier 3 | ×3 | Complex multi-step workflows |

### Efficiency Bonus (ONLY on perfect correctness = 1.0)
If correctness is perfect, efficiency bonus can **up to double** the tier score:
- **Call efficiency** — fewer API calls vs best known solution = higher bonus
- **Error cleanliness** — fewer 4xx errors (400, 404, 422) = higher bonus

| Scenario (Tier 2 task) | Score |
|------------------------|-------|
| Failed all checks | 0.0 |
| 80% checks passed | 1.6 |
| Perfect, many errors + extra calls | ~2.1 |
| Perfect, efficient, few errors | ~2.6 |
| Perfect, best efficiency, zero errors | 4.0 |

Non-perfect submissions score `correctness × tier` only — NO efficiency bonus.

**Max score per task**: Tier 1 = 2.0, Tier 2 = 4.0, Tier 3 = 6.0
**Efficiency benchmarks recalculated every 12 hours** — as teams improve, the bar rises.

### Best Score Per Task
- **All-time best** per task is kept — bad runs never lower your score
- **Leaderboard = sum of best scores across all 30 task types**
- Max theoretical leaderboard score depends on tier distribution

### Task Assignment
- Each submission = one task, weighted toward tasks you've attempted less
- Over many submissions you'll encounter all task types

### Tier Release Schedule
- **Tier 1** — available from competition start
- **Tier 2** — opens early Friday
- **Tier 3** — opens early Saturday

### Rate Limits
| Limit | Verified teams | Unverified teams |
|-------|---------------|-----------------|
| Concurrent submissions | 3 | 1 |
| Per task per day | 4 | 2 |

## Maximizing Score — Strategy
1. **Correctness first** — include ALL data from the prompt, every field matters for points
2. **Minimize API calls** — plan before calling, don't fetch entities you don't need
3. **Zero 4xx errors** — avoid trial-and-error; validate inputs before sending
4. **Use POST response IDs** — don't GET after creating, you already have the ID
5. **Batch where possible** — some endpoints accept lists
6. **Parse error messages** — fix in one retry, not several
7. **Handle all 7 languages** — LLM must parse nb, en, es, pt, nn, de, fr prompts
8. **Handle file attachments** — some tasks include PDFs/images with invoice data etc.

## Submission Results — How to Read Them
- The **x/7** or **x/8** scores in "Recent Results" are **preliminary checks** (health, format, etc.)
- They are NOT the actual task score
- **7/7 = all checks passed** → task was actually scored on the leaderboard
- **Anything less = task was never scored**, counts as 0
- The **30 real test scenarios** are shown at the top of the page (Tasks Solved: x/30)
- The first ~7 entries from 07:52–08:15 PM are from old broken code, ignore them

## GCP Infrastructure
- **Project**: `ainm26osl-716` (unlimited compute)
- **User**: `devstar7161@gcplab.me`
- **Service account**: `59268370848-compute@developer.gserviceaccount.com`
- **Cloud Run service**: `tripletex-agent` in `europe-north1`
- **Service URL**: https://tripletex-agent-rzkmnmpmpq-lz.a.run.app
- **LLM**: Gemini 2.5 Flash via Vertex AI (OpenAI-compatible endpoint), env var `LLM_MODEL`
- **Auth**: Service account on Cloud Run, `gcloud auth print-access-token` locally — no API keys needed
- **Secret Manager**: `tripletex-session-token` — Tripletex sandbox session token
- **gcloud profile**: `nmiai-unlimited`

## Deploying
```bash
gcloud run deploy tripletex-agent \
  --source . \
  --region europe-north1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 300 \
  --port 8080 \
  --project ainm26osl-716
```
- No `--set-env-vars` needed — Vertex AI uses service account auth automatically
- Model is Gemini 2.5 Flash by default, change via `--set-env-vars "LLM_MODEL=google/gemini-2.5-pro"` for more reasoning power
- Don't deploy while a submission is in-flight — the request can get lost

## Reading Logs
```bash
# All task logs from latest revision
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="tripletex-agent" AND jsonPayload.message=~"NEW TASK|Tool call|API response|API error|Agent done|Agent summary|Docs search"' \
  --project ainm26osl-716 --limit 60 \
  --format "table(timestamp,jsonPayload.message)"
```

## Browser / Submission
- If the browser session expires, open a new Chrome window — user will log in
- Fill endpoint URL: `https://tripletex-agent-rzkmnmpmpq-lz.a.run.app/solve`
- Click Submit

## Task Categories
- **Employees** — Create employees, set roles, update contact info
- **Customers & Products** — Register customers, create products
- **Invoicing** — Create invoices, register payments, issue credit notes
- **Travel Expenses** — Register or delete travel expense reports
- **Projects** — Create projects linked to customers
- **Corrections** — Delete or reverse incorrect entries
- **Departments** — Create departments, enable accounting modules

### Common Task Patterns
| Pattern | Example | API Flow |
|---------|---------|----------|
| Create single entity | "Create employee Ola Nordmann" | POST /employee |
| Create with linking | "Create invoice for customer" | GET /customer → POST /order → POST /invoice |
| Modify existing | "Add phone to contact" | GET /customer → PUT /customer/{id} |
| Delete/reverse | "Delete travel expense" | GET /travelExpense → DELETE /travelExpense/{id} |
| Multi-step setup | "Register payment" | POST /customer → POST /invoice → POST /payment |

## Request/Response Format
### Request to /solve
```json
{
  "prompt": "Opprett en ansatt med navn Ola Nordmann...",
  "files": [{"filename": "faktura.pdf", "content_base64": "...", "mime_type": "application/pdf"}],
  "tripletex_credentials": {"base_url": "https://tx-proxy.ainm.no/v2", "session_token": "abc123..."}
}
```
- `base_url` is a **proxy URL** — all API calls must go through it (not direct Tripletex)
- Auth: Basic Auth with username `0` and session_token as password

### Response from /solve
```json
{"status": "completed"}
```

## Tripletex API Reference
| Endpoint | Methods | Description |
|----------|---------|-------------|
| `/employee` | GET, POST, PUT | Manage employees |
| `/customer` | GET, POST, PUT | Manage customers |
| `/product` | GET, POST | Manage products |
| `/invoice` | GET, POST | Create and query invoices |
| `/order` | GET, POST | Manage orders |
| `/travelExpense` | GET, POST, PUT, DELETE | Travel expense reports |
| `/project` | GET, POST | Manage projects |
| `/department` | GET, POST | Manage departments |
| `/ledger/account` | GET | Query chart of accounts |
| `/ledger/posting` | GET | Query ledger postings |
| `/ledger/voucher` | GET, POST, DELETE | Manage vouchers |
| `/ledger/vatType` | GET | VAT type lookup |

### API Tips
- `?fields=id,firstName,lastName,*` to select specific fields
- `?from=0&count=100` for pagination
- List responses: `{"fullResultSize": N, "values": [...]}`
- POST/PUT responses: `{"value": {...}}`

## Architecture
- **Agentic loop** (ReAct pattern) — NOT plan-then-execute
- LLM gets two tools: `call_api` and `search_api_docs`
- Each iteration: LLM decides one action → execute → show result → repeat
- LLM responds with text (no tool call) when done
- Max 15 iterations per task

## Common API Errors
| Error | Cause | Fix |
|-------|-------|-----|
| 401 Unauthorized | Wrong auth format | Basic Auth: username `0`, password = session token |
| 404 Not Found | Wrong endpoint path | Check Tripletex v2 API docs for correct paths |
| 422 Validation Error | Missing required fields | Read error message — it specifies which fields |
| Empty `values` array | No results found | Broaden search parameters |
| Timeout (5 min) | Agent too slow | Optimize API calls, reduce unnecessary requests |

## Key Gotchas
- **Include ALL data from the prompt** — the LLM must put every mentioned value in the payload
- **Validation errors must include field details** — "startDate: required" not just "Validation failed"
- **Double /v2 prefix** — TripletexClient auto-strips /v2 when base_url already has it
- **Employee creation** requires: firstName, lastName, userType("STANDARD"), email, department(id)
- **Project creation** requires: name, projectManager(id), number, startDate
- **Invoice GET** requires: invoiceDateFrom, invoiceDateTo params (both mandatory)
- **Payment**: PUT /v2/invoice/{id}/:payment with paymentDate, paymentTypeId, paidAmount
- **Employment requires dateOfBirth** — employee must have dateOfBirth before creating employment
- **organizationNumber** must be digits only (9-digit Norwegian org numbers)
- **VAT types** are at GET /v2/ledger/vatType (NOT /v2/product/vatType)
- **GET returns** `{"values": [...]}`, **POST returns** `{"value": {...}}`
- **Don't use `async def` for /solve** — blocks event loop with sync HTTP calls

## Git Commits
- **NEVER add Co-Authored-By lines** to commit messages — no Claude attribution in commits

## Running Tests
```bash
python3 -m pytest --tb=short                       # unit + integration (108 tests)
python3 -m pytest tests/e2e/ -m e2e -v             # e2e against sandbox (needs env vars)
python3 -m pytest tests/tuning -v -n auto          # tuning tests in PARALLEL (fast, ~1-2 min)
python3 -m pytest tests/tuning -v -s --capture=no  # tuning tests sequential with output (slow, ~6 min)
```

### Tuning Tests
Tests in `tests/tuning/` use the **real LLM** with a **MockTripletexClient** to measure agent efficiency. They assert on zero API errors and minimal call counts. Use these to tune the system prompt for perfect submissions (efficiency bonus = 0 errors + minimal calls).

## Sandbox
- API: https://kkpqfuj-amager.tripletex.dev/v2
- Auth: Basic 0:<session_token>
- Token expires: March 31, 2026
