# Tripletex AI Agent — NM i AI 2026

## Competition
- **Task**: Build an AI agent that completes accounting tasks in Tripletex
- **30 task types**, 56 variants each (7 languages × 8 data sets)
- **Timeout**: 5 minutes per task
- **Submission URL**: https://app.ainm.no/submit/tripletex
- **Endpoint**: https://tripletex-agent-6wzdpvze4a-lz.a.run.app/solve

## Submission Results — How to Read Them
- The **x/7** or **x/8** scores in "Recent Results" are **preliminary checks** (health, format, etc.)
- They are NOT the actual task score
- **7/7 = all checks passed** → task was actually scored on the leaderboard
- **Anything less = task was never scored**, counts as 0
- The **30 real test scenarios** are shown at the top of the page (Tasks Solved: x/30)
- The first ~7 entries from 07:52–08:15 PM are from old broken code, ignore them

## Deploying
```bash
gcloud run deploy tripletex-agent \
  --source . \
  --region europe-north1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 300 \
  --port 8080 \
  --project nm-i-ai-944963 \
  --set-env-vars "OPENAI_API_KEY=<key>"
```
- API key is NOT in the Dockerfile (GitHub push protection blocks it)
- Must pass `--set-env-vars` on every deploy
- Don't deploy while a submission is in-flight — the request can get lost

## Reading Logs
```bash
# All task logs from latest revision
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="tripletex-agent" AND jsonPayload.message=~"NEW TASK|Tool call|API response|API error|Agent done|Agent summary|Docs search"' \
  --project nm-i-ai-944963 --limit 60 \
  --format "table(timestamp,jsonPayload.message)"
```

## Browser / Submission
- If the browser session expires, open a new Chrome window — user will log in
- Fill endpoint URL: `https://tripletex-agent-6wzdpvze4a-lz.a.run.app/solve`
- Click Submit

## Architecture
- **Agentic loop** (ReAct pattern) — NOT plan-then-execute
- LLM gets two tools: `call_api` and `search_api_docs`
- Each iteration: LLM decides one action → execute → show result → repeat
- LLM responds with text (no tool call) when done
- Max 15 iterations per task

## Key Gotchas
- **Include ALL data from the prompt** — the LLM must put every mentioned value in the payload
- **Validation errors must include field details** — "startDate: required" not just "Validation failed"
- **Double /v2 prefix** — TripletexClient auto-strips /v2 when base_url already has it
- **Employee creation** requires: firstName, lastName, userType("STANDARD"), email, department(id)
- **Project creation** requires: name, projectManager(id), number, startDate
- **Invoice GET** requires: invoiceDateFrom, invoiceDateTo params (both mandatory)
- **Payment**: PUT /v2/invoice/{id}/:payment with paymentDate, paymentTypeId, paidAmount
- **GET returns** `{"values": [...]}`, **POST returns** `{"value": {...}}`
- **Don't use `async def` for /solve** — blocks event loop with sync HTTP calls

## Running Tests
```bash
python3 -m pytest --tb=short           # unit + integration (93 tests)
python3 -m pytest tests/e2e/ -m e2e -v  # e2e against sandbox (needs env vars)
```

## Sandbox
- API: https://kkpqfuj-amager.tripletex.dev/v2
- Auth: Basic 0:<session_token>
- Token expires: March 31, 2026
