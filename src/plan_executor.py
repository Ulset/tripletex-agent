import json
import logging
import re

from src.models import ExecutionPlan, ExecutionResult
from src.plan_generator import PlanGenerator
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\$step(\d+)([\.\[].+)")


class PlanExecutor:
    def __init__(self, client: TripletexClient):
        self.client = client
        self.replan_count = 0

    def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        context: dict[int, dict] = {}
        results: list[dict] = []
        errors: list[str] = []
        steps_completed = 0
        api_calls = 0

        for step in plan.steps:
            try:
                endpoint = _resolve_placeholders(step.endpoint, context)
                payload = _resolve_placeholders(step.payload, context) if step.payload else None
                params = _resolve_placeholders(step.params, context) if step.params else None

                logger.info(
                    "Executing step %d: %s %s | resolved_payload=%s",
                    step.step_number, step.action, endpoint,
                    json.dumps(payload, ensure_ascii=False) if payload else "null",
                )

                action = step.action.upper()
                if action == "GET":
                    result = self.client.get(endpoint, params=params)
                elif action == "POST":
                    result = self.client.post(endpoint, json=payload)
                elif action == "PUT":
                    result = self.client.put(endpoint, json=payload)
                elif action == "DELETE":
                    result = self.client.delete(endpoint)
                else:
                    raise ValueError(f"Unknown action: {action}")

                api_calls += 1
                context[step.step_number] = result
                results.append(result)
                steps_completed += 1
                logger.info("Step %d completed: %s %s", step.step_number, action, endpoint)

            except TripletexAPIError as e:
                api_calls += 1
                error_msg = f"Step {step.step_number} failed: {e}"
                errors.append(error_msg)
                logger.error(error_msg)
                return ExecutionResult(
                    steps_completed=steps_completed,
                    results=results,
                    errors=errors,
                    success=False,
                    total_api_calls=api_calls,
                    error_count=len(errors),
                )
            except (KeyError, IndexError, ValueError) as e:
                error_msg = f"Step {step.step_number} failed (resolution): {e}"
                errors.append(error_msg)
                logger.error(error_msg)
                return ExecutionResult(
                    steps_completed=steps_completed,
                    results=results,
                    errors=errors,
                    success=False,
                    total_api_calls=api_calls,
                    error_count=len(errors),
                )

        logger.info(
            "Execution complete: total_api_calls=%d, error_count=%d",
            api_calls, len(errors),
        )
        return ExecutionResult(
            steps_completed=steps_completed,
            results=results,
            errors=errors,
            success=True,
            total_api_calls=api_calls,
            error_count=len(errors),
        )

    def execute_with_replan(
        self,
        plan: ExecutionPlan,
        generator: PlanGenerator,
        original_prompt: str,
        file_contents: list[dict] | None = None,
        max_replans: int = 2,
    ) -> ExecutionResult:
        """Execute a plan with automatic re-planning on failure."""
        result = self.execute(plan)
        self.replan_count = 0
        total_api_calls = result.total_api_calls
        total_errors = result.error_count

        while not result.success and self.replan_count < max_replans:
            self.replan_count += 1
            error_context = "\n".join(result.errors)
            logger.info("Re-plan attempt %d/%d", self.replan_count, max_replans)

            new_plan = generator.replan(
                original_prompt=original_prompt,
                file_contents=file_contents,
                execution_result=result,
                error_context=error_context,
            )
            result = self.execute(new_plan)
            total_api_calls += result.total_api_calls
            total_errors += result.error_count

        result.total_api_calls = total_api_calls
        result.error_count = total_errors
        return result


def _resolve_placeholders(obj, context: dict[int, dict]):
    """Recursively resolve $stepN.path.to.value placeholders."""
    if isinstance(obj, str):
        # Full-string match: return the actual typed value (int, dict, etc.)
        match = PLACEHOLDER_RE.fullmatch(obj)
        if match:
            step_num = int(match.group(1))
            path = match.group(2)
            return _traverse(context[step_num], path)
        # Partial/embedded match: substitute within the string
        def _replacer(m):
            step_num = int(m.group(1))
            path = m.group(2)
            return str(_traverse(context[step_num], path))
        return PLACEHOLDER_RE.sub(_replacer, obj)
    if isinstance(obj, dict):
        return {k: _resolve_placeholders(v, context) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_placeholders(item, context) for item in obj]
    return obj


def _normalize_path(path: str) -> list[str]:
    """Normalize a path like 'values[0].id' or 'values.0.id' into ['values', '0', 'id']."""
    # Replace bracket notation with dot notation: values[0] -> values.0
    normalized = re.sub(r'\[(\w+)\]', r'.\1', path)
    return [k for k in normalized.split(".") if k]


def _traverse(data: dict, path: str):
    """Traverse a nested dict/list using dot-notation or bracket-notation path."""
    current = data
    for key in _normalize_path(path):
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise KeyError(f"Cannot traverse into {type(current)} with key '{key}'")
    return current
