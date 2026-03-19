import logging
import re

from src.models import ExecutionPlan, ExecutionResult
from src.plan_generator import PlanGenerator
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\$step(\d+)\.(.+)")


class PlanExecutor:
    def __init__(self, client: TripletexClient):
        self.client = client

    def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        context: dict[int, dict] = {}
        results: list[dict] = []
        errors: list[str] = []
        steps_completed = 0

        for step in plan.steps:
            try:
                payload = _resolve_placeholders(step.payload, context) if step.payload else None
                params = _resolve_placeholders(step.params, context) if step.params else None

                action = step.action.upper()
                if action == "GET":
                    result = self.client.get(step.endpoint, params=params)
                elif action == "POST":
                    result = self.client.post(step.endpoint, json=payload)
                elif action == "PUT":
                    result = self.client.put(step.endpoint, json=payload)
                elif action == "DELETE":
                    result = self.client.delete(step.endpoint)
                else:
                    raise ValueError(f"Unknown action: {action}")

                context[step.step_number] = result
                results.append(result)
                steps_completed += 1
                logger.info("Step %d completed: %s %s", step.step_number, action, step.endpoint)

            except TripletexAPIError as e:
                error_msg = f"Step {step.step_number} failed: {e}"
                errors.append(error_msg)
                logger.error(error_msg)
                return ExecutionResult(
                    steps_completed=steps_completed,
                    results=results,
                    errors=errors,
                    success=False,
                )

        return ExecutionResult(
            steps_completed=steps_completed,
            results=results,
            errors=errors,
            success=True,
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
        replans = 0

        while not result.success and replans < max_replans:
            replans += 1
            error_context = "\n".join(result.errors)
            logger.info("Re-plan attempt %d/%d", replans, max_replans)

            new_plan = generator.replan(
                original_prompt=original_prompt,
                file_contents=file_contents,
                execution_result=result,
                error_context=error_context,
            )
            result = self.execute(new_plan)

        return result


def _resolve_placeholders(obj, context: dict[int, dict]):
    """Recursively resolve $stepN.path.to.value placeholders."""
    if isinstance(obj, str):
        match = PLACEHOLDER_RE.fullmatch(obj)
        if match:
            step_num = int(match.group(1))
            path = match.group(2)
            return _traverse(context[step_num], path)
        return obj
    if isinstance(obj, dict):
        return {k: _resolve_placeholders(v, context) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_placeholders(item, context) for item in obj]
    return obj


def _traverse(data: dict, path: str):
    """Traverse a nested dict/list using dot-notation path."""
    current = data
    for key in path.split("."):
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise KeyError(f"Cannot traverse into {type(current)} with key '{key}'")
    return current
