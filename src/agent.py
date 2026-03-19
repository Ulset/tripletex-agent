import json
import logging
import time

from openai import OpenAI

from src.knowledge import TRIPLETEX_API_REFERENCE
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

SYSTEM_PROMPT = f"""You are a Tripletex API agent. You receive a task description (which may be in Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French) and must complete it by making API calls to Tripletex.

{TRIPLETEX_API_REFERENCE}

## How to Work

- Use the call_api tool to make API calls to Tripletex.
- You see each API response before deciding the next action. Use actual data from responses — never guess IDs or field values.
- When the task is fully complete, respond with a short text message (NO tool call) confirming what you did.

## CRITICAL: Include ALL Data From the Prompt

- You MUST include EVERY piece of data mentioned in the task prompt as a field in the API payload.
- If the prompt mentions an organization number, include "organizationNumber" in the payload.
- If the prompt mentions an email, include "email" in the payload.
- If the prompt mentions an address, include "postalAddress" with addressLine1, postalCode, city.
- If the prompt mentions a phone number, include "phoneNumber" or "phoneNumberMobile".
- If the prompt mentions any value, find the matching API field name and include it.
- NEVER skip data from the prompt. Every value mentioned is being scored.

## API Response Shapes

- GET requests return: {{"values": [...]}} (a list of matching entities)
- POST/PUT requests return: {{"value": {{...}}}} (the created/updated entity with its id)
- Use the actual response data for subsequent calls. Do not guess.

## Efficiency Guidelines

- Minimize total API calls — fewer calls = higher efficiency score.
- Reuse IDs from POST responses — do NOT call GET for entities you just created.
- Include all required fields to avoid 4xx errors and costly retries.
- Preserve Norwegian characters (æ, ø, å) exactly as given.

## Error Handling

- If an API call returns an error, read the error message carefully and adapt.
- Common fixes: add missing required fields, fix field formats, create prerequisite entities first.
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
                    "description": "Query parameters for GET requests",
                },
            },
            "required": ["method", "endpoint"],
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
        start_time = time.time()
        api_calls = 0
        errors = 0

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
                tools=[CALL_API_TOOL],
                temperature=0,
            )

            choice = response.choices[0]

            # If no tool calls, the LLM considers the task done
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                final_message = choice.message.content or ""
                logger.info("Agent done: %s", final_message)
                duration = time.time() - start_time
                logger.info(
                    "Agent summary: api_calls=%d, errors=%d, iterations=%d, duration=%.2fs",
                    api_calls, errors, iteration, duration,
                )
                return

            # Process tool calls
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                if tool_call.function.name != "call_api":
                    # Unknown tool — skip
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": f"Unknown tool: {tool_call.function.name}"}),
                    })
                    continue

                args = json.loads(tool_call.function.arguments)
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
            "Agent reached max iterations (%d). api_calls=%d, errors=%d, duration=%.2fs",
            MAX_ITERATIONS, api_calls, errors, duration,
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
            return self.client.put(endpoint, json=body)
        elif method == "DELETE":
            return self.client.delete(endpoint)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")


def _truncate(s: str, max_len: int = 500) -> str:
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
