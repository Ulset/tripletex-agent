# PRD: Tripletex AI Agent for NM i AI Competition

## Introduction

Build an autonomous AI agent that receives natural language prompts (in 7 languages) describing accounting tasks, interprets them using an OpenAI LLM, and executes the corresponding Tripletex API calls. The agent exposes a `/solve` HTTPS endpoint, processes attached files (PDFs/images) via OCR, generates a step-by-step execution plan, and carries it out against the Tripletex API proxy. The goal is to maximize correctness across all 30 task types while minimizing API calls and errors for efficiency bonus points.

## Goals

- Handle all 30 Tripletex task types (56 variants each: 7 languages × 8 data sets) across 3 difficulty tiers
- Support prompts in all 7 languages (nb, nn, en, es, pt, de, fr)
- Extract data from PDF/image attachments using OCR
- Achieve perfect correctness scores with minimal API calls and zero 4xx errors
- Earn efficiency bonuses on perfect tasks (up to 2× the tier score — max 6.0 on Tier 3)
- Deploy as a Docker container to GCP
- Comprehensive test suite covering unit, integration, and end-to-end tests

## User Stories

### US-001: Project Scaffolding and Configuration
**Description:** As a developer, I need the Python project structure with dependency management and environment configuration so that I can start building the agent.

**Acceptance Criteria:**
- [ ] Python project with `pyproject.toml` (or `requirements.txt`) using FastAPI, uvicorn, requests, openai, python-dotenv
- [ ] `.env.example` file documenting `OPENAI_API_KEY`, `OPENAI_MODEL` (default: `gpt-4o`), and `PORT` (default: `8000`)
- [ ] `.env` in `.gitignore`
- [ ] `src/` package structure: `main.py`, `config.py`
- [ ] `config.py` loads settings from `.env` using python-dotenv and exposes them as a config object
- [ ] `main.py` creates a FastAPI app and runs with uvicorn
- [ ] App starts successfully with `python -m src.main`

### US-002: /solve Endpoint Skeleton
**Description:** As the competition platform, I need a POST `/solve` endpoint that accepts the competition request format and returns `{"status": "completed"}` so that the agent can receive tasks.

**Acceptance Criteria:**
- [ ] `POST /solve` accepts JSON body with `prompt`, `files`, and `tripletex_credentials`
- [ ] Request body is validated with Pydantic models (`SolveRequest`, `FileAttachment`, `TripletexCredentials`)
- [ ] Optional `Authorization: Bearer <api-key>` header validation (configurable via `.env`)
- [ ] Returns `{"status": "completed"}` with HTTP 200
- [ ] Returns HTTP 500 with error details if agent fails internally
- [ ] Responds within 300 seconds (5-minute timeout)
- [ ] Unit tests for request validation and response format

### US-003: Tripletex API Client
**Description:** As the agent, I need a client to interact with the Tripletex API through the provided proxy URL so that I can create, read, update, and delete entities.

**Acceptance Criteria:**
- [ ] `TripletexClient` class accepting `base_url` and `session_token`
- [ ] Uses Basic Auth with username `0` and session token as password
- [ ] Methods: `get(endpoint, params)`, `post(endpoint, json)`, `put(endpoint, json)`, `delete(endpoint)`
- [ ] All methods use the `fields` parameter when provided
- [ ] Handles pagination with `count` and `from` parameters
- [ ] Returns parsed JSON responses
- [ ] Logs all API calls (method, endpoint, status code) for debugging
- [ ] Raises typed exceptions for 4xx and 5xx errors with the Tripletex error message
- [ ] Unit tests with mocked HTTP responses for all methods and error cases

### US-004: File Processing Pipeline
**Description:** As the agent, I need to extract text and data from PDF and image attachments so that I can include their content when interpreting the task.

**Acceptance Criteria:**
- [ ] Decodes base64 file content from the request
- [ ] Extracts text from PDFs (using a library like `pymupdf`/`pdfplumber`)
- [ ] For image files (PNG, JPG), uses the OpenAI vision API to extract text/data
- [ ] For PDFs with scanned content (no extractable text), falls back to vision API
- [ ] Returns structured text content per file
- [ ] Handles empty files list gracefully
- [ ] Unit tests with sample PDF and image fixtures

### US-005: LLM Integration — Plan Generation
**Description:** As the agent, I need to use an OpenAI LLM to interpret the prompt and generate a structured execution plan so that I know which Tripletex API calls to make and in what order.

**Acceptance Criteria:**
- [ ] `PlanGenerator` class using the OpenAI chat completions API
- [ ] System prompt that describes all available Tripletex API endpoints, their methods, required fields, and common patterns
- [ ] Accepts the task prompt, extracted file content, and optionally existing entity context
- [ ] Returns a structured plan as a list of steps, each with: `action` (GET/POST/PUT/DELETE), `endpoint`, `payload`/`params`, and `description`
- [ ] Plan accounts for dependencies (e.g., "create customer first, then use customer_id in invoice")
- [ ] Uses placeholder references for IDs from previous steps (e.g., `$step1.id`)
- [ ] LLM response is parsed and validated into Pydantic models
- [ ] Configurable model via `OPENAI_MODEL` env var
- [ ] Unit tests with mocked OpenAI responses

### US-006: Plan Execution Engine
**Description:** As the agent, I need to execute the generated plan step-by-step against the Tripletex API, resolving dependencies between steps, so that the task is completed correctly.

**Acceptance Criteria:**
- [ ] `PlanExecutor` class that takes a plan and a `TripletexClient`
- [ ] Executes steps sequentially, collecting results from each step
- [ ] Resolves placeholder references (`$step1.id`) with actual values from previous step responses
- [ ] Stores execution context (created entity IDs, response data) for reference
- [ ] Handles step failures: logs the error and includes it in context for potential re-planning
- [ ] Returns execution summary (steps completed, results, any errors)
- [ ] Unit tests with mocked TripletexClient

### US-007: Re-planning on Failure
**Description:** As the agent, I need to recover from API errors by sending the error context back to the LLM for a corrected plan so that transient issues don't cause task failure.

**Acceptance Criteria:**
- [ ] When a step fails with a 4xx error, the error message and current execution context are sent back to the LLM
- [ ] LLM generates a corrected plan for the remaining steps
- [ ] Maximum 2 re-planning attempts to avoid excessive API calls and LLM costs
- [ ] If all retries fail, execution stops gracefully and returns `{"status": "completed"}`
- [ ] Unit tests for re-planning flow with mocked LLM and API responses

### US-008: Orchestrator — Tying It All Together
**Description:** As the `/solve` endpoint, I need an orchestrator that coordinates file processing, plan generation, plan execution, and error recovery into a single workflow.

**Acceptance Criteria:**
- [ ] `TaskOrchestrator` class that wires together all components
- [ ] Flow: decode files -> extract content -> generate plan -> execute plan -> (re-plan if needed)
- [ ] Passes tripletex credentials to the client
- [ ] Handles the full 5-minute timeout budget (reserves time for re-planning)
- [ ] Logs the full workflow for debugging (prompt, plan, execution results)
- [ ] Integration test with mocked LLM and mocked Tripletex API testing the full flow

### US-009: Tripletex API Knowledge Base
**Description:** As the LLM, I need a comprehensive knowledge base of Tripletex API endpoints, required fields, and common patterns so that I generate correct plans on the first attempt.

**Acceptance Criteria:**
- [ ] Document covering all key Tripletex v2 endpoints used in the competition
- [ ] For each endpoint: URL, method, required fields, optional fields, example payloads
- [ ] Common task patterns documented (create employee, create invoice with customer+order, register payment, delete/reverse entries, enable modules, etc.)
- [ ] Module enablement patterns documented (e.g., enabling department accounting before creating departments)
- [ ] Field naming conventions and data types (dates as `YYYY-MM-DD`, IDs as integers, etc.)
- [ ] Common errors documented (missing prerequisites, duplicate entities, required field omissions, Norwegian character handling)
- [ ] This knowledge base is included in the LLM system prompt
- [ ] Kept as a separate file (`src/knowledge/tripletex_api.py` or `.txt`) for easy updating
- [ ] Validate that knowledge base fits within OpenAI context window alongside task prompts

### US-010: Multi-Language Prompt Handling
**Description:** As the agent, I need to correctly interpret prompts in all 7 supported languages so that I can handle any task variant.

**Acceptance Criteria:**
- [ ] LLM system prompt instructs the model to handle Norwegian Bokmal, Norwegian Nynorsk, English, Spanish, Portuguese, German, and French
- [ ] Task type detection works regardless of prompt language
- [ ] Entity names, field values, and special characters (ae, oe, aa) are preserved correctly in API calls
- [ ] Unit tests with sample prompts in at least 3 different languages

### US-011: Dockerfile and Docker Compose
**Description:** As a developer, I need a Docker setup so I can build, test, and deploy the agent as a container to GCP.

**Acceptance Criteria:**
- [ ] `Dockerfile` with Python 3.12 slim base image
- [ ] Installs dependencies, copies source code
- [ ] Runs uvicorn on configurable port (default 8000)
- [ ] `docker-compose.yml` for local development with `.env` file mounting
- [ ] Image builds successfully and app starts in container
- [ ] Container responds to `POST /solve` requests

### US-012: Integration Tests with Mocked Tripletex API
**Description:** As a developer, I need integration tests that simulate the full agent flow with a mocked Tripletex API so I can verify correctness without hitting real services.

**Acceptance Criteria:**
- [ ] Test fixtures with realistic task prompts for each task pattern (create employee, create customer, create invoice, modify entity, delete entity)
- [ ] Mocked Tripletex API responses using `responses` or `respx` library
- [ ] Mocked OpenAI API responses with realistic plan outputs
- [ ] Tests verify the correct Tripletex API calls are made in the right order
- [ ] Tests verify request payloads contain correct field values from the prompt
- [ ] Tests cover error recovery flow (4xx -> re-plan -> retry)
- [ ] All tests pass with `pytest`

### US-013: End-to-End Tests with Tripletex Sandbox
**Description:** As a developer, I need end-to-end tests against the real Tripletex sandbox API so I can validate the agent works against the actual API.

**Acceptance Criteria:**
- [ ] Test configuration for sandbox credentials (separate `.env.test` or env vars)
- [ ] E2E tests for at least 5 common task types: create employee, create customer, create product, create invoice (with prerequisites), modify existing entity
- [ ] Tests create entities and verify them via GET requests
- [ ] Tests are marked/tagged so they can be run separately from unit tests (`pytest -m e2e`)
- [ ] Tests clean up created entities after running (where possible)
- [ ] Documentation on how to set up and run e2e tests

### US-014: Efficiency Optimization
**Description:** As a competitor, I need the agent to minimize API calls and avoid errors so that I earn the efficiency bonus on perfect tasks.

**Acceptance Criteria:**
- [ ] Plan generator is instructed to use minimal API calls
- [ ] Agent reuses IDs from POST responses instead of re-fetching via GET
- [ ] Agent validates payloads before sending to reduce 4xx errors
- [ ] LLM system prompt includes efficiency guidelines (don't fetch what you already know, batch where possible)
- [ ] Logging tracks total API call count and error count per task for monitoring

### US-015: Health Check and Observability
**Description:** As an operator, I need a health check endpoint and structured logging so I can monitor the deployed agent.

**Acceptance Criteria:**
- [ ] `GET /health` returns `{"status": "ok"}` with HTTP 200
- [ ] Structured JSON logging (timestamp, level, message, context)
- [ ] Each `/solve` request logs: prompt summary, plan generated, steps executed, total API calls, errors, duration
- [ ] Logs do not contain sensitive data (no session tokens or API keys)

## Functional Requirements

- FR-1: The agent must expose a `POST /solve` endpoint accepting JSON with `prompt`, `files`, and `tripletex_credentials`
- FR-2: The agent must return `{"status": "completed"}` with HTTP 200 within 300 seconds
- FR-3: The agent must authenticate with Tripletex using Basic Auth (username `0`, password = session token)
- FR-4: The agent must route all Tripletex API calls through the provided `base_url` proxy
- FR-5: The agent must use an OpenAI LLM (configurable model) to interpret prompts and generate execution plans
- FR-6: The agent must extract text/data from PDF and image file attachments
- FR-7: The agent must handle prompts in 7 languages: nb, nn, en, es, pt, de, fr
- FR-8: The agent must support all 30 task types including: create/update/delete employees, customers, products, invoices, orders, projects, departments, travel expenses, vouchers, payments, and corrections/reversals
- FR-9: The agent must handle tasks requiring module enablement (e.g., department accounting) as a prerequisite step
- FR-10: The agent must recover from API errors by re-planning with error context (max 2 retries)
- FR-11: The agent must minimize total API calls and 4xx errors for efficiency scoring
- FR-12: The agent must validate incoming requests and protect the endpoint with an optional API key
- FR-13: The agent must run in a Docker container deployable to GCP
- FR-14: The agent must handle sandbox accounts that start empty — creating prerequisites (customers, products) before dependent entities (invoices)

## Non-Goals (Out of Scope)

- No web UI or dashboard — this is a headless API agent
- No persistent storage or database — each `/solve` request is stateless
- No custom fine-tuned models — uses OpenAI's standard API
- No automatic deployment pipeline (CI/CD) — manual GCP deployment
- No real-time monitoring/alerting dashboard — just structured logs

## Technical Considerations

- **Framework:** FastAPI (async, fast, good Pydantic integration)
- **LLM:** OpenAI API via `openai` Python SDK — model configurable via `OPENAI_MODEL` env var
- **PDF Extraction:** `pymupdf` (fitz) for text extraction, OpenAI vision API as fallback for scanned documents
- **HTTP Client:** `requests` for Tripletex API calls (sync is fine given sequential execution)
- **Testing:** `pytest` with `pytest-asyncio`, `responses`/`respx` for HTTP mocking, `pytest-cov` for coverage
- **Docker:** Python 3.12-slim base, multi-stage build for smaller image
- **Structured Logging:** Python `logging` with JSON formatter
- **Timeout Management:** Track elapsed time and reserve budget for re-planning
- **Sandbox:** Each submission gets a fresh empty Tripletex account — agent must create all prerequisites from scratch
- **API Proxy:** All API calls must go through the provided `base_url` proxy (calls are logged for debugging and scoring)
- **UTF-8:** Norwegian characters (æ, ø, å) must be handled correctly in all API payloads

## Project Structure

```
tripletex-agent/
  src/
    __init__.py
    main.py              # FastAPI app and /solve endpoint
    config.py            # Environment config loading
    models.py            # Pydantic request/response models
    tripletex_client.py  # Tripletex API client
    file_processor.py    # PDF/image extraction
    plan_generator.py    # LLM-based plan generation
    plan_executor.py     # Step-by-step plan execution
    orchestrator.py      # Wires everything together
    knowledge/
      __init__.py
      tripletex_api.py   # API knowledge base for LLM system prompt
  tests/
    __init__.py
    conftest.py          # Shared fixtures
    test_models.py
    test_tripletex_client.py
    test_file_processor.py
    test_plan_generator.py
    test_plan_executor.py
    test_orchestrator.py
    e2e/
      __init__.py
      conftest.py        # Sandbox credentials
      test_create_employee.py
      test_create_customer.py
      test_create_invoice.py
      test_modify_entity.py
      test_full_flow.py
    fixtures/
      sample_prompts.py
      sample_pdf.pdf
      sample_image.png
  Dockerfile
  docker-compose.yml
  .env.example
  .gitignore
  pyproject.toml
  README.md
```

## Scoring Reference

| Scenario (Tier 2 example) | Score |
|---|---|
| Failed all checks | 0.0 |
| 80% checks passed | 1.6 (0.8 × 2) |
| Perfect with trial-and-error | ~2.1 |
| Perfect, efficient, minimal errors | ~2.6 |
| Perfect, best-in-class efficiency, zero errors | 4.0 (2 × 2.0) |

- **Tier 1**: max 1.0 base, up to 2.0 with efficiency
- **Tier 2**: max 2.0 base, up to 4.0 with efficiency
- **Tier 3**: max 3.0 base, up to 6.0 with efficiency
- Efficiency bonus only applies to perfect (1.0 correctness) submissions
- Best score per task is kept — bad runs never lower your score
- Benchmarks recalculated every 12 hours

## Success Metrics

- Agent handles all 30 task types with >80% correctness on first attempt
- Perfect correctness (1.0) on Tier 1 tasks consistently
- Efficiency bonus earned on majority of perfect tasks (score > tier multiplier)
- Total leaderboard score competitive (top 50% at minimum)
- Test suite covers >90% of code paths
- Agent responds within 60 seconds for simple tasks, within 180 seconds for complex tasks

## Task Categories

Based on the competition docs, tasks include:

- **Employees** — Create employees, set roles, update contact info
- **Customers & Products** — Register customers, create products
- **Invoicing** — Create invoices, register payments, issue credit notes
- **Travel Expenses** — Register or delete travel expense reports
- **Projects** — Create projects linked to customers
- **Corrections** — Delete or reverse incorrect entries
- **Departments** — Create departments, enable accounting modules

Task complexity ranges:
- **Simple** — single API call (e.g., create an employee)
- **Medium** — 2-3 API calls with linking (e.g., create customer + invoice)
- **Complex** — multi-step with setup verification and module enablement

## Open Questions

- Are there rate limits on the Tripletex proxy API beyond the competition submission limits?
- What is the exact distribution of task types (how many Tier 1 vs Tier 2 vs Tier 3)?
- Should we use GPT-4o specifically for vision tasks and a cheaper model for text-only prompts to save costs?
