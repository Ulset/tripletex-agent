import json
import logging
import time
import uuid

from src.api_docs import get_endpoint_schema, search_api_docs
from src.vertex_auth import get_openai_client
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

_PRE_PARSE_PROMPT = """You are a task parser for a Tripletex accounting agent. Your job is to translate and normalize incoming task prompts (which may be in nb, nn, en, es, pt, de, fr) into a structured English plan.

Output format (plain text, NOT JSON):
TASK TYPE: <type>
RECIPE: <letter> (<name>)

FIELDS:
- fieldName: value
- fieldName: value

STEPS:
1. First API call description
2. Second API call description

FILE DATA: <extracted data from attachments, or "(none)">

Rules:
- Extract EVERY value from the prompt — names, emails, dates, amounts, org numbers, addresses, etc.
- Preserve exact spelling, numbers, and Norwegian characters (æ, ø, å)
- Map to one of these recipes: A(DEPARTMENT), B(EMPLOYEE), C(CUSTOMER/SUPPLIER), D(PROJECT), E(PRODUCT), F(INVOICE), G(PAYMENT), H(TRAVEL EXPENSE), I(VOUCHER), J(CORRECTIONS), K(TIMESHEET), L(PAYROLL)
- If the task doesn't match a recipe, use your best judgment for TASK TYPE and STEPS
- Include ALL file attachment data in FILE DATA section
- Be concise — no explanations, just the structured output"""

_SYSTEM_PROMPT = """You are a Tripletex API agent. Complete accounting tasks via API calls. The task has been pre-parsed into English with extracted fields — trust the parsed plan.

## Rules
1. API success IS confirmation. NEVER GET after POST/PUT/DELETE — you already have the response.
2. Include EVERY value from the task prompt. Every field is scored.
3. Follow the matching recipe below. Do not add verification steps.
4. On error, read the message and fix in ONE retry. Do not search docs.
5. GET returns {values:[...]}, POST/PUT returns {value:{...}}. Reuse returned IDs.
6. Dates: YYYY-MM-DD. For vouchers/journal entries, use current fiscal year 2026 (convert older dates). Addresses: {addressLine1, postalCode, city} — never a string.
7. GET paymentType/vatType/costCategory ONCE with no filters. Pick from the full response.
8. If the task says to create/register/add/update/delete, you MUST make a mutation call. Never finish with only GETs.
9. Preserve Norwegian characters (æ, ø, å) exactly as given.

## Recipes

A. DEPARTMENT [1 call]: POST /v2/department {name, departmentNumber}. For multiple departments, separate POSTs.

B. EMPLOYEE [2-3 calls]: (1) GET /v2/department?fields=id&count=1 → deptId. (2) POST /v2/employee {firstName, lastName, userType:"STANDARD", email, department:{id}, dateOfBirth}. Include dateOfBirth if given — required before employment. (3) If start date given: POST /v2/employee/employment {employee:{id}, startDate}. Employment is always a separate POST.

C. CUSTOMER/SUPPLIER [1 call]: POST /v2/customer {name, isCustomer:true, ...all fields} or POST /v2/supplier {name, isSupplier:true, ...all fields}. Include organizationNumber, email, phoneNumber, postalAddress, physicalAddress as given.

D. PROJECT [3-4 calls]: (1) GET /v2/employee?email=X → managerId. (2) If customer: GET /v2/customer?organizationNumber=X → custId. (3) POST /v2/project {name, projectManager:{id}, startDate, customer:{id}}. Do NOT set "number" — auto-generated. Fixed price: add isFixedPrice:true, fixedprice:amount (lowercase "fixedprice", NOT "fixedPriceAmount"). (4) To invoice partial: GET /v2/ledger/account?isBankAccount=true → PUT with bankAccountNumber:"12345678903" (11 digits), POST /v2/product, POST /v2/order with orderLines (unitPriceExcludingVatCurrency=partial amount), PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD.

E. PRODUCT [1-2 calls]: (1) If VAT mentioned: GET /v2/ledger/vatType → find match. (2) POST /v2/product {name, number, priceExcludingVatCurrency, vatType:{id}}.

F. INVOICE [5-9 calls]: (1) GET /v2/customer?organizationNumber=X → custId. (2) Products: if numbers given like "(1234)", GET /v2/product?number=1234 (they exist). Otherwise POST /v2/product. (3) GET /v2/ledger/account?isBankAccount=true → PUT with bankAccountNumber:"12345678903". (4) POST /v2/order — MUST include orderDate AND deliveryDate: {customer:{id}, orderDate:"YYYY-MM-DD", deliveryDate:"YYYY-MM-DD", orderLines:[{product:{id}, count, unitPriceExcludingVatCurrency}]}. (5) PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD. For payment after invoice: GET /v2/invoice/paymentType (no filters) → find "Bankinnskudd", PUT /v2/invoice/{id}/:payment with query params only: paymentDate, paymentTypeId, paidAmount, paidAmountCurrency.

G. PAYMENT [4 calls]: (1) GET /v2/customer?organizationNumber=X. (2) GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → id, amountOutstanding. (3) GET /v2/invoice/paymentType (no filters) → find "Bankinnskudd". (4) PUT /v2/invoice/{id}/:payment with QUERY PARAMS ONLY: paymentDate, paymentTypeId, paidAmount=amountOutstanding, paidAmountCurrency=amountOutstanding.

H. TRAVEL EXPENSE [3-8 calls]: (1) GET /v2/employee?email=X. (2) GET /v2/travelExpense/paymentType + GET /v2/travelExpense/costCategory (no filters). (3) POST /v2/travelExpense {employee:{id}, title, date, travelDetails:{departureDate, returnDate, destination, purpose, departureFrom}}. (4) Per cost: POST /v2/travelExpense/cost {travelExpense:{id:parentId}, date, amountCurrencyIncVat, comments, isPaidByEmployee:true, paymentType:{id}, costCategory:{id}}. (5) Accommodation: POST /v2/travelExpense/accommodationAllowance {travelExpense:{id}, location, count, rate, amount}. (6) Per diem: POST /v2/travelExpense/perDiemCompensation {travelExpense:{id}, location, count, rate, amount}. DELETE: GET /v2/travelExpense?employeeId=X → DELETE /v2/travelExpense/{id}.

I. VOUCHER [3-8 calls]: (1) GET /v2/ledger/account?number=XXXX for each account. (2) POST /v2/ledger/voucher {date (2026), description, postings:[{account:{id}, amountGross:X, amountGrossCurrency:X, row:1}, {account:{id}, amountGross:-X, amountGrossCurrency:-X, row:2}]}. Row starts at 1 (NOT 0). Postings must balance. EVERY posting MUST have BOTH amountGross AND amountGrossCurrency (same value). Never use "amount"/"isDebit"/"debit"/"credit".
  DIMENSIONS: POST /v2/ledger/accountingDimensionName {dimensionName, description, dimensionIndex:1, active:true}. Per value: POST /v2/ledger/accountingDimensionValue {dimensionIndex, displayName, number, active:true, showInVoucherRegistration:true, position}. Link via freeAccountingDimension1:{id} on posting (or 2/3 for other indices). NEVER use "dimensions"/"dimensionValue1"/"freeDimension1".
  SUPPLIER INVOICE: GET /v2/supplier?organizationNumber=X, GET accounts (expense + 2400), GET /v2/ledger/vatType. POST /v2/ledger/voucher {date(2026), description, vendorInvoiceNumber, postings: [{account:{id:expense}, amountGross:totalInclVat, amountGrossCurrency:totalInclVat, vatType:{id}, supplier:{id}, row:1}, {account:{id:2400}, amountGross:-totalInclVat, amountGrossCurrency:-totalInclVat, supplier:{id}, row:2}]}.

J. CORRECTIONS [2-4 calls]: CREDIT NOTE (invoice is wrong): GET /v2/invoice → PUT /v2/invoice/{id}/:createCreditNote?date=YYYY-MM-DD (date >= invoiceDate). PAYMENT REVERSAL (bank returned payment): GET /v2/customer → GET /v2/invoice → GET /v2/ledger/voucher?dateFrom=2000-01-01&dateTo=2030-12-31 → DELETE /v2/ledger/voucher/{id}. Use DELETE voucher, NOT createCreditNote.

K. TIMESHEET [4-14 calls]: (1) GET /v2/employee?email=X. (2) GET /v2/project → projectId, note startDate and customer. (3) GET /v2/activity?name=X or POST /v2/activity {name, isProjectActivity:true, isChargeable:true}. (4) POST /v2/timesheet/entry {employee:{id}, project:{id}, activity:{id}, date (use project startDate, not past date), hours, hourlyRate}. If task says to invoice: (5) GET /v2/ledger/account?isBankAccount=true → PUT with bankAccountNumber:"12345678903" (MUST be 11 digits). (6) POST /v2/product. (7) POST /v2/order {customer:{id}, project:{id}, orderLines:[{product:{id}, count, unitPriceExcludingVatCurrency}]}. (8) PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD. CRITICAL: steps 5-8 must ALL be done. Set up bank BEFORE invoice.

L. PAYROLL [3-8 calls]: Prerequisites: employee needs dateOfBirth, employment, and employment must have a division.
  (1) GET /v2/employee?email=X → check if dateOfBirth is set. If not: PUT /v2/employee/{id} with dateOfBirth (use prompt value or "1990-01-01").
  (2) Check employment: if employee has no employment, create one. POST /v2/employee/employment {employee:{id}, startDate}. Employment needs a division — if none exists: GET /v2/municipality?count=1 → POST /v2/division {name, displayName, organizationNumber:"987654321", startDate:"2026-01-01", municipality:{id}, municipalityDate:"2026-01-01"} → PUT /v2/employee/employment/{id} {division:{id}}.
  (3) GET /v2/salary/type → find salary type IDs (e.g. "Fastlønn" for base salary, "Bonus" for bonus).
  (4) POST /v2/salary/transaction {date, year, month, payslips:[{employee:{id}, date, year, month, specifications:[{salaryType:{id}, amount, rate, count:1}]}]}. MUST include year field. Use fiscal year 2026. Do NOT use vouchers for payroll.

## Action
You MUST use call_api to complete the task. Start immediately — identify the matching recipe, then make the first API call. Never respond with only text. On 403 auth errors, retry — they are transient. NEVER give up or say you cannot complete the task.
"""


def get_system_prompt() -> str:
    return _SYSTEM_PROMPT

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

    def _pre_parse(self, prompt: str) -> str | None:
        """Translate and normalize the task prompt into a structured English plan."""
        parse_start = time.time()
        try:
            user_input = f"Task prompt:\n{prompt}"
            if self.file_contents:
                file_text = "\n\n".join(
                    f"--- {f['filename']} ---\n{f['extracted_text']}"
                    for f in self.file_contents
                )
                user_input += f"\n\nAttached file contents:\n{file_text}"

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _PRE_PARSE_PROMPT},
                    {"role": "user", "content": user_input},
                ],
                temperature=0,
            )
            parsed = response.choices[0].message.content or ""
            duration = time.time() - parse_start
            logger.info("Pre-parse completed in %.2fs:\n%s", duration, parsed)
            return parsed
        except Exception as e:
            duration = time.time() - parse_start
            logger.warning("Pre-parse failed in %.2fs: %s — falling back to raw prompt", duration, e)
            return None

    def solve(self, prompt: str) -> None:
        task_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        api_calls = 0
        errors = 0
        doc_searches = 0
        logger.info("[%s] Starting agent for prompt: %s", task_id, _truncate(prompt, 200))

        # Pre-parse the task prompt
        parsed_plan = self._pre_parse(prompt)

        if parsed_plan:
            user_message = f"Pre-parsed task plan:\n{parsed_plan}\n\nOriginal prompt (for reference only):\n{prompt}"
        else:
            # Fallback: use raw prompt with file contents
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
                    # Retry once on 403 (token may be temporarily invalid)
                    if e.status_code == 403:
                        logger.warning("Got 403, retrying once...")
                        time.sleep(1)
                        try:
                            result = self._execute_api_call(method, endpoint, body, params)
                            result_str = json.dumps(result, ensure_ascii=False)
                            logger.info("API response (retry): %s", _truncate(result_str))
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result_str,
                            })
                            continue
                        except TripletexAPIError:
                            pass  # Fall through to normal error handling
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
