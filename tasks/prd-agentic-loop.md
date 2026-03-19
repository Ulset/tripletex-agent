# PRD: Agentic Loop — Replace Plan-Execute with Reason-Act-Observe

## Introduction

Replace the current plan-then-execute architecture with a ReAct-style agentic loop. Currently, the LLM generates an entire execution plan upfront (endpoints, payloads, placeholder syntax), and a separate executor blindly follows it. This is brittle — the LLM has to guess API response shapes, required fields, and ID values without seeing any real data. When it guesses wrong (which is frequent), the task fails.

The new approach: give the LLM a single tool (`call_api`) and let it decide one action at a time, observing each API response before choosing the next action. The LLM never has to guess — it sees real data and adapts.

## Goals

- Eliminate placeholder syntax and response-shape guessing entirely
- Let the LLM self-heal from API errors by seeing the actual error message
- Simplify the codebase by removing PlanGenerator, PlanExecutor, ExecutionPlan models, and replan machinery
- Score >0% on competition submissions consistently
- Keep the existing TripletexClient, FileProcessor, config, logging, and /solve endpoint

## User Stories

### US-001: Agent loop core with call_api tool
**Description:** As the orchestrator, I need a ReAct-style agent loop that gives the LLM a `call_api` tool and iterates until the LLM says it's done, so the agent can adaptively complete any Tripletex task.

**Acceptance Criteria:**
- [ ] New `src/agent.py` with `TripletexAgent` class
- [ ] Constructor takes `openai_api_key`, `model`, `tripletex_client`, and optional `file_contents`
- [ ] `solve(prompt: str) -> None` method that runs the agent loop
- [ ] System prompt includes the Tripletex API knowledge base and instructions
- [ ] LLM has one tool: `call_api(method: str, endpoint: str, body: dict|null, params: dict|null)` — defined as an OpenAI function/tool
- [ ] Each iteration: send conversation to LLM → if tool call, execute it via TripletexClient, append result to conversation → repeat
- [ ] Loop ends when LLM responds with a text message (no tool call) — this means it considers the task done
- [ ] Maximum 15 iterations to prevent runaway loops
- [ ] All API calls and LLM responses are logged
- [ ] Tests pass

### US-002: Update orchestrator to use agent loop
**Description:** As the /solve endpoint, I need the orchestrator to use the new TripletexAgent instead of PlanGenerator/PlanExecutor so that competition tasks use the agentic approach.

**Acceptance Criteria:**
- [ ] `TaskOrchestrator.solve()` creates a `TripletexAgent` and calls `agent.solve(prompt)`
- [ ] File processing still happens before the agent loop (extracted text is passed to the agent)
- [ ] Time budget management preserved (agent gets remaining time after file processing)
- [ ] Always returns `{"status": "completed"}` regardless of agent outcome
- [ ] Error handling: if agent raises any exception, catch it, log it, still return completed
- [ ] Tests pass

### US-003: Agent system prompt with knowledge base and tool instructions
**Description:** As the LLM, I need a system prompt that tells me how to use the Tripletex API, how to interpret task prompts, and when I'm done, so I can complete accounting tasks correctly.

**Acceptance Criteria:**
- [ ] System prompt includes the full Tripletex API knowledge base
- [ ] Instructs the LLM to include ALL data from the task prompt in API payloads
- [ ] Instructs the LLM to use `call_api` tool for every API interaction
- [ ] Instructs the LLM to respond with a text message (no tool call) when the task is complete
- [ ] Instructs the LLM that GET returns `{"values": [...]}` and POST/PUT returns `{"value": {...}}`
- [ ] Includes efficiency guidelines: minimize calls, don't re-fetch what you just created
- [ ] Instructs the LLM to handle all 7 languages
- [ ] Instructs the LLM to preserve Norwegian characters exactly
- [ ] Tests pass

### US-004: Delete old plan-based code
**Description:** As a developer, I need the old plan-generate-execute code removed so the codebase is clean and there's no confusion about which path is active.

**Acceptance Criteria:**
- [ ] Delete `src/plan_generator.py`
- [ ] Delete `src/plan_executor.py`
- [ ] Remove `PlanStep`, `ExecutionPlan`, `ExecutionResult` from `src/models.py`
- [ ] Remove placeholder resolution code
- [ ] Delete `tests/test_plan_generator.py`
- [ ] Delete `tests/test_plan_executor.py`
- [ ] Update `tests/test_orchestrator.py` to test the new agent-based flow
- [ ] Update `tests/test_integration.py` to test the new agent-based flow
- [ ] All remaining tests pass
- [ ] Tests pass

### US-005: Comprehensive logging for the agent loop
**Description:** As a developer debugging competition submissions, I need detailed logging of every agent loop iteration so I can see exactly what the LLM decided, what API call was made, and what response came back.

**Acceptance Criteria:**
- [ ] Log each iteration number and total count
- [ ] Log the LLM's tool call: method, endpoint, body, params
- [ ] Log the API response (truncated if >500 chars)
- [ ] Log when the LLM decides it's done (final text message)
- [ ] Log if max iterations reached
- [ ] Log total API calls made and any errors
- [ ] Log total duration of the agent loop
- [ ] Tests pass

## Functional Requirements

- FR-1: The agent must use OpenAI's function calling / tool use API to give the LLM a `call_api` tool
- FR-2: The `call_api` tool must accept `method` (GET/POST/PUT/DELETE), `endpoint`, `body` (optional), and `params` (optional)
- FR-3: The agent must execute the tool call via TripletexClient and return the result to the LLM as the tool response
- FR-4: The agent must stop when the LLM responds with a regular text message (no tool call)
- FR-5: The agent must stop after 15 iterations maximum
- FR-6: The agent must handle API errors gracefully — return the error message to the LLM so it can adapt
- FR-7: The orchestrator must always return `{"status": "completed"}` regardless of agent outcome
- FR-8: File contents (from PDFs/images) must be included in the initial user message to the LLM

## Non-Goals

- No typed/per-entity tools — single generic `call_api` only
- No verification step after the LLM says done — trust the LLM
- No caching of API responses between iterations
- No parallel tool calls — one action at a time

## Technical Considerations

- **OpenAI tool use API**: Use `tools` parameter with function definitions, handle `tool_calls` in the response
- **Conversation management**: Maintain a messages list that grows with each iteration (system + user + assistant + tool responses)
- **Token budget**: The conversation grows each iteration. With GPT-4o's 128K context, 15 iterations should fit comfortably even with the knowledge base in the system prompt
- **Existing code to keep**: TripletexClient (with /v2 dedup and timeout), FileProcessor, config, models (SolveRequest/Response, FileAttachment, TripletexCredentials), logging_config, main.py endpoint
- **Existing code to delete**: plan_generator.py, plan_executor.py, PlanStep/ExecutionPlan/ExecutionResult models, placeholder resolution

## Success Metrics

- Agent scores >0% on competition submissions (i.e., at least some checks pass)
- Agent completes simple tasks (create single entity) in 1-2 API calls
- Agent self-recovers from 422 errors by reading the error message and retrying
- Agent handles multi-step tasks (lookup entity → create linked entity) without placeholder syntax
- Total response time under 60 seconds for simple tasks

## Open Questions

- Should we include a condensed version of the knowledge base to save tokens, or the full version for maximum accuracy?
- Should the agent verify its work by doing a final GET after creating entities, or trust the POST response?
