import json
import logging
import time
import uuid

from src.api_docs import generate_endpoint_reference, get_endpoint_schema, search_api_docs
from src.vertex_auth import get_openai_client
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

_SYSTEM_PROMPT_HEADER = """You are a Tripletex API agent. You receive a task description (which may be in Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French) and must complete it by making API calls to Tripletex.

## Common Endpoints — USE THESE DIRECTLY, do NOT search docs for these.
## (REQ) = required field. Field names are from the official OpenAPI spec.

"""

_SYSTEM_PROMPT_FOOTER = """

## Workflows

- EMPLOYEE WORKFLOW: (1) GET /v2/department?fields=id&count=1 → departmentId. (2) POST /v2/employee with firstName, lastName, userType("STANDARD"), email, department(id), dateOfBirth. (3) IF start date given: POST /v2/employee/employment with employee(id), startDate. Employment is ALWAYS a separate POST — never put startDate or employment fields on the employee object.
- PROJECT WORKFLOW: (1) GET /v2/employee?email=X → projectManager ID. (2) If customer link needed: GET /v2/customer?organizationNumber=X → customerId. (3) POST /v2/project with name, number, projectManager(id), startDate, and customer(id) if given. NEVER use /v2/project/list — always POST to /v2/project directly.
- PAYMENT WORKFLOW: (1) GET /v2/customer?organizationNumber=X → customerId. (2) GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → invoice ID + amountOutstanding. (3) GET /v2/invoice/paymentType → paymentTypeId for "Bankinnskudd". (4) PUT /v2/invoice/{id}/:payment with QUERY PARAMS paymentDate=YYYY-MM-DD, paymentTypeId=X, paidAmount=amountOutstanding, paidAmountCurrency=amountOutstanding.
- ORDER + INVOICE WORKFLOW: (1) Create product if needed: POST /v2/product with name, number, priceExcludingVatCurrency. (2) If customer lookup needed: GET /v2/customer?organizationNumber=X → customerId. (3) POST /v2/order with customer(id), deliveryDate, orderDate, orderLines: [{product: {id}, count, unitPriceExcludingVatCurrency}]. Price goes on OrderLine as unitPriceExcludingVatCurrency OR on Product — NEVER as priceExcludingVatCurrency on OrderLine. (4) To invoice: PUT /v2/order/{orderId}/:invoice with query param invoiceDate=YYYY-MM-DD. Do NOT use POST /v2/invoice.
- ADDRESSES: postalAddress is ALWAYS a JSON object: {"addressLine1": "...", "postalCode": "...", "city": "..."}. NEVER send it as a string.

## How to Work

1. Read the task prompt. Identify ALL entities to create/modify and ALL data values.
2. Make API calls using call_api. Use the common endpoints above for standard operations.
3. If you encounter an unfamiliar endpoint or get a validation error you can't resolve, use search_api_docs to look up the correct fields.
4. You see each API response before deciding the next action. Use actual IDs from responses — never guess.
5. When ALL data from the prompt has been set, respond with a short text message (NO tool call).

## CRITICAL Rules

- Include EVERY piece of data from the prompt in API payloads. Every value is scored.
- Some data requires separate linked entities (employment is separate from employee, etc.).
- GET returns {"values": [...]}, POST/PUT returns {"value": {...}}.
- Dates use YYYY-MM-DD format. Preserve Norwegian characters (æ, ø, å) exactly as given.
- Minimize API calls. Reuse IDs from POST responses.
- If an API call fails, read the error message and fix it directly. Do NOT search docs — the error already tells you what's wrong (e.g., "field X is required" means add field X, "wrong type" means fix the format).
- Only use search_api_docs if the error mentions an UNKNOWN endpoint or you need to discover a sub-resource you've never seen.
- Never give up on data from the prompt. Never call search_api_docs more than twice per task.
"""


_SYSTEM_PROMPT_CACHE: str | None = None


def get_system_prompt() -> str:
    """Build the system prompt with spec-generated endpoint reference. Cached after first call."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is not None:
        return _SYSTEM_PROMPT_CACHE
    try:
        ref = generate_endpoint_reference()
    except Exception:
        ref = "(Could not load endpoint reference from OpenAPI spec)"
    _SYSTEM_PROMPT_CACHE = _SYSTEM_PROMPT_HEADER + ref + _SYSTEM_PROMPT_FOOTER
    return _SYSTEM_PROMPT_CACHE


def _reset_system_prompt_cache():
    """Reset prompt cache — used in tests."""
    global _SYSTEM_PROMPT_CACHE
    _SYSTEM_PROMPT_CACHE = None

CALL_API_TOOL = {
    "type": "function",
    "function": {
        "name": "call_api",
        "description": "Make an API call to the Tripletex API",
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP method",
                },
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint path, e.g. /v2/customer",
                },
                "body": {
                    "type": ["object", "null"],
                    "description": "JSON body for POST/PUT requests",
                },
                "params": {
                    "type": ["object", "null"],
                    "description": "Query parameters (used for GET and PUT requests)",
                },
            },
            "required": ["method", "endpoint"],
        },
    },
}


SEARCH_API_DOCS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_api_docs",
        "description": "Search the official Tripletex OpenAPI specification for endpoint details, required fields, parameters, and schemas. Use this when you need to discover the correct endpoint, field names, or required parameters for an API call.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term — e.g. 'invoice', 'payment', 'employee', 'vatType', 'project'",
                },
            },
            "required": ["query"],
        },
    },
}


class TripletexAgent:
    def __init__(
        self,
        model: str,
        tripletex_client: TripletexClient,
        file_contents: list[dict] | None = None,
    ):
        self.openai = get_openai_client()
        self.model = model
        self.client = tripletex_client
        self.file_contents = file_contents

    def solve(self, prompt: str) -> None:
        task_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        api_calls = 0
        errors = 0
        doc_searches = 0
        logger.info("[%s] Starting agent for prompt: %s", task_id, _truncate(prompt, 200))

        # Build the initial user message
        user_message = f"Task: {prompt}"
        if self.file_contents:
            file_text = "\n\n".join(
                f"--- {f['filename']} ---\n{f['extracted_text']}"
                for f in self.file_contents
            )
            user_message += f"\n\nAttached file contents:\n{file_text}"

        messages = [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": user_message},
        ]

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info("Agent iteration %d/%d", iteration, MAX_ITERATIONS)

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=[CALL_API_TOOL, SEARCH_API_DOCS_TOOL],
                temperature=0,
            )

            choice = response.choices[0]

            # If no tool calls, the LLM considers the task done
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                final_message = choice.message.content or ""
                logger.info("[%s] Agent done: %s", task_id, final_message)
                duration = time.time() - start_time
                logger.info(
                    "[%s] Agent summary: api_calls=%d, errors=%d, doc_searches=%d, iterations=%d, duration=%.2fs",
                    task_id, api_calls, errors, doc_searches, iteration, duration,
                )
                return

            # Process tool calls
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if func_name == "search_api_docs":
                    query = args.get("query", "")
                    doc_searches += 1
                    logger.info("Docs search: %s (count=%d)", query, doc_searches)
                    if doc_searches > 2:
                        result_str = "Doc search limit reached (max 2). Use the common endpoints from your instructions and fix based on the error message."
                    else:
                        result_str = search_api_docs(query)
                    logger.info("Docs result: %s", _truncate(result_str))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })
                    continue

                if func_name != "call_api":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": f"Unknown tool: {func_name}"}),
                    })
                    continue

                method = args["method"]
                endpoint = args["endpoint"]
                body = args.get("body")
                params = args.get("params")

                logger.info(
                    "Tool call: %s %s body=%s params=%s",
                    method, endpoint,
                    _truncate(json.dumps(body, ensure_ascii=False)) if body else "null",
                    _truncate(json.dumps(params, ensure_ascii=False)) if params else "null",
                )

                api_calls += 1
                try:
                    result = self._execute_api_call(method, endpoint, body, params)
                    result_str = json.dumps(result, ensure_ascii=False)
                    logger.info("API response: %s", _truncate(result_str))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })
                except TripletexAPIError as e:
                    errors += 1
                    error_dict = {"error": str(e)}
                    if e.status_code == 422:
                        schema_hint = get_endpoint_schema(method, endpoint)
                        if schema_hint:
                            error_dict["schema_hint"] = schema_hint
                    error_msg = json.dumps(error_dict, ensure_ascii=False)
                    logger.warning("API error: %s", error_msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": error_msg,
                    })

        # Max iterations reached
        duration = time.time() - start_time
        logger.warning(
            "[%s] Agent reached max iterations (%d). api_calls=%d, errors=%d, doc_searches=%d, duration=%.2fs",
            task_id, MAX_ITERATIONS, api_calls, errors, doc_searches, duration,
        )

    def _execute_api_call(
        self, method: str, endpoint: str, body: dict | None, params: dict | None
    ) -> dict:
        method = method.upper()
        if method == "GET":
            return self.client.get(endpoint, params=params)
        elif method == "POST":
            return self.client.post(endpoint, json=body)
        elif method == "PUT":
            return self.client.put(endpoint, json=body, params=params)
        elif method == "DELETE":
            return self.client.delete(endpoint)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")


def _truncate(s: str, max_len: int = 500) -> str:
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
