import logging
import time

from src.config import Settings
from src.file_processor import FileProcessor
from src.models import SolveRequest, SolveResponse
from src.plan_executor import PlanExecutor
from src.plan_generator import PlanGenerator
from src.tripletex_client import TripletexClient

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    def __init__(self, config: Settings):
        self.config = config

    def solve(self, request: SolveRequest) -> SolveResponse:
        start_time = time.time()
        try:
            logger.info("=" * 60)
            logger.info("NEW TASK RECEIVED")
            logger.info("Full prompt:\n%s", request.prompt)
            logger.info("Files: %d attached", len(request.files))
            logger.info("Base URL: %s", request.tripletex_credentials.base_url)
            logger.info("=" * 60)

            # 1) Process files
            processor = FileProcessor()
            file_contents = processor.process_files(
                request.files,
                self.config.openai_api_key,
                self.config.openai_model,
            )
            logger.info("Processed %d files", len(file_contents))

            # 2) Generate plan
            generator = PlanGenerator(
                openai_api_key=self.config.openai_api_key,
                model=self.config.openai_model,
            )
            plan = generator.generate_plan(
                prompt=request.prompt,
                file_contents=file_contents if file_contents else None,
            )
            logger.info("Generated plan with %d steps", len(plan.steps))

            # 3) Execute plan with re-planning on failure
            client = TripletexClient(
                base_url=request.tripletex_credentials.base_url,
                session_token=request.tripletex_credentials.session_token,
            )
            executor = PlanExecutor(client)
            elapsed = time.time() - start_time
            # Reserve 60s buffer for re-planning; cap replans based on time budget
            max_replans = 2 if elapsed < 180 else (1 if elapsed < 240 else 0)
            result = executor.execute_with_replan(
                plan=plan,
                generator=generator,
                original_prompt=request.prompt,
                file_contents=file_contents if file_contents else None,
                max_replans=max_replans,
            )

            duration = time.time() - start_time
            logger.info(
                "Workflow complete: steps_completed=%d, errors=%d, success=%s, duration=%.2fs",
                result.steps_completed,
                len(result.errors),
                result.success,
                duration,
            )
            logger.info(
                "Efficiency summary: total_api_calls=%d, error_count=%d, replan_count=%d",
                result.total_api_calls,
                result.error_count,
                executor.replan_count,
            )

        except Exception:
            duration = time.time() - start_time
            logger.exception("Workflow failed after %.2fs", duration)

        # Competition requires status=completed regardless of outcome
        return SolveResponse(status="completed")
