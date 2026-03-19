import json
import logging

from openai import OpenAI

from src.knowledge import TRIPLETEX_API_REFERENCE
from src.models import ExecutionPlan, ExecutionResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are a Tripletex API planning agent. Given a task description (which may be in Norwegian Bokmal, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French), generate a structured execution plan of Tripletex API calls.

{TRIPLETEX_API_REFERENCE}

## Output Format
Respond ONLY with a valid JSON object matching this schema:
{{
  "steps": [
    {{
      "step_number": 1,
      "action": "POST",
      "endpoint": "/v2/employee",
      "payload": {{"firstName": "Ola", "lastName": "Nordmann"}},
      "params": null,
      "description": "Create the employee"
    }}
  ]
}}

## Placeholder Syntax
Use $stepN.path.to.value to reference results from previous steps.
Example: $step1.value.id refers to the id field from step 1's response.

## Efficiency Guidelines
- Reuse IDs from POST responses — do NOT call GET for entities you just created.
- Minimize total API calls.
- Validate required fields before generating calls.
- Batch where possible.
- Preserve Norwegian characters (ae, oe, aa) exactly as given.
"""


class PlanGenerator:
    def __init__(self, openai_api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=openai_api_key)
        self.model = model

    def generate_plan(
        self,
        prompt: str,
        file_contents: list[dict] | None = None,
        error_context: str | None = None,
    ) -> ExecutionPlan:
        user_message = f"Task: {prompt}"

        if file_contents:
            file_text = "\n\n".join(
                f"--- {f['filename']} ---\n{f['extracted_text']}"
                for f in file_contents
            )
            user_message += f"\n\nAttached file contents:\n{file_text}"

        if error_context:
            user_message += f"\n\nPrevious error context:\n{error_context}"

        logger.info("Generating plan for prompt: %s", prompt[:100])

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        plan = ExecutionPlan.model_validate(data)

        logger.info("Generated plan with %d steps", len(plan.steps))
        return plan

    def replan(
        self,
        original_prompt: str,
        file_contents: list[dict] | None,
        execution_result: ExecutionResult,
        error_context: str,
    ) -> ExecutionPlan:
        """Generate a corrected plan after a failed execution attempt."""
        completed_summary = ""
        for i, result in enumerate(execution_result.results, 1):
            completed_summary += f"Step {i} succeeded: {json.dumps(result)}\n"

        error_summary = "\n".join(execution_result.errors)

        user_message = f"Task: {original_prompt}"

        if file_contents:
            file_text = "\n\n".join(
                f"--- {f['filename']} ---\n{f['extracted_text']}"
                for f in file_contents
            )
            user_message += f"\n\nAttached file contents:\n{file_text}"

        user_message += f"\n\nPrevious execution partially completed ({execution_result.steps_completed} steps succeeded)."
        if completed_summary:
            user_message += f"\n\nCompleted steps and their results:\n{completed_summary}"
        user_message += f"\n\nErrors encountered:\n{error_summary}"
        user_message += f"\n\nAdditional error context:\n{error_context}"
        user_message += "\n\nGenerate a corrected plan for the REMAINING work only. Do NOT re-do steps that already succeeded."

        logger.info("Re-planning after %d completed steps", execution_result.steps_completed)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        plan = ExecutionPlan.model_validate(data)

        logger.info("Re-plan generated with %d steps", len(plan.steps))
        return plan
