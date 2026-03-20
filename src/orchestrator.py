import json
import logging
import time

from src.agent import TripletexAgent
from src.config import Settings
from src.file_processor import FileProcessor
from src.models import SolveRequest, SolveResponse
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
            for f in request.files:
                logger.info("  File: %s (%s, %d bytes)", f.filename, f.mime_type, len(f.content_base64))
            logger.info("Base URL: %s", request.tripletex_credentials.base_url)
            # Log the raw request for test case reproduction
            logger.info("Raw request payload:\n%s", json.dumps(request.model_dump(), ensure_ascii=False, default=str)[:2000])
            logger.info("=" * 60)

            # 1) Process files
            processor = FileProcessor()
            file_contents = processor.process_files(
                request.files,
                self.config.llm_model,
            )
            logger.info("Processed %d files", len(file_contents))

            # 2) Run agent loop
            client = TripletexClient(
                base_url=request.tripletex_credentials.base_url,
                session_token=request.tripletex_credentials.session_token,
            )
            agent = TripletexAgent(
                model=self.config.llm_model,
                tripletex_client=client,
                file_contents=file_contents if file_contents else None,
            )
            agent.solve(request.prompt)

            duration = time.time() - start_time
            logger.info("Workflow complete: duration=%.2fs", duration)

        except Exception:
            duration = time.time() - start_time
            logger.exception("Workflow failed after %.2fs", duration)

        # Competition requires status=completed regardless of outcome
        return SolveResponse(status="completed")
