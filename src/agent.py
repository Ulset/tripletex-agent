import json
import logging
import time
import uuid

from openai import OpenAI

from src.api_docs import search_api_docs
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

SYSTEM_PROMPT = """You are a Tripletex API agent. You receive a task description (which may be in Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French) and must complete it by making API calls to Tripletex.

## Common Endpoints — USE THESE DIRECTLY, do NOT search docs for these. All fields listed are REQUIRED unless marked optional.

- POST /v2/employee — create employee. Include: firstName, lastName, userType("STANDARD"), email, department(id), dateOfBirth if given.
- POST /v2/employee/employment — create employment (start date). Include: employee(id), startDate.
- GET /v2/department?fields=id&count=1 — get a department ID (needed for employee creation).
- EMPLOYEE WORKFLOW: (1) GET /v2/department?fields=id&count=1 → departmentId. (2) POST /v2/employee with firstName, lastName, userType("STANDARD"), email, department(id), dateOfBirth. (3) IF start date given: POST /v2/employee/employment with employee(id), startDate. Employment is ALWAYS a separate POST — never put startDate or employment fields on the employee object.
- POST /v2/customer — create customer. Include: name, organizationNumber, email, phoneNumber.
- ADDRESSES: postalAddress is ALWAYS a JSON object: {"addressLine1": "...", "postalCode": "...", "city": "..."}. NEVER send it as a string.
- POST /v2/supplier — create supplier. Include: name, organizationNumber, email, isSupplier(true). For addresses use postalAddress: {"addressLine1": "...", "postalCode": "...", "city": "..."}.
- POST /v2/product — create product. Include: name, number, priceExcludingVatCurrency.
- POST /v2/project — create project. Include: name, number, projectManager(id), startDate. NEVER use /v2/project/list — always POST to /v2/project directly.
- PROJECT WORKFLOW: (1) GET /v2/employee?email=X → projectManager ID. (2) If customer link needed: GET /v2/customer?organizationNumber=X → customerId. (3) POST /v2/project with name, number, projectManager(id), startDate, and customer(id) if given.
- POST /v2/department — create department. Include: name, departmentNumber.
- POST /v2/order — create order. Include: customer(id), deliveryDate, orderLines.
- POST /v2/invoice — create invoice from order. Include: orderId, invoiceDate, sendMethod.
- PUT /v2/invoice/{id}/:payment — register payment. Use QUERY PARAMS (not body): paymentDate, paymentTypeId, paidAmount, paidAmountCurrency.
- GET /v2/invoice/paymentType — list payment types. Use "Bankinnskudd" (bank deposit) by default.
- GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31 — list invoices. Both date params are REQUIRED.
- PAYMENT WORKFLOW: (1) GET /v2/customer?organizationNumber=X → customerId. (2) GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → invoice ID + amountOutstanding. (3) GET /v2/invoice/paymentType → paymentTypeId for "Bankinnskudd". (4) PUT /v2/invoice/{id}/:payment with QUERY PARAMS paymentDate=YYYY-MM-DD, paymentTypeId=X, paidAmount=amountOutstanding, paidAmountCurrency=amountOutstanding.
- GET /v2/employee?email=x — find employee by email.
- GET /v2/customer?organizationNumber=x — find customer by org number.

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
        openai_api_key: str,
        model: str,
        tripletex_client: TripletexClient,
        file_contents: list[dict] | None = None,
    ):
        self.openai = OpenAI(api_key=openai_api_key)
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
            {"role": "system", "content": SYSTEM_PROMPT},
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
                    error_msg = json.dumps({"error": str(e)})
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
