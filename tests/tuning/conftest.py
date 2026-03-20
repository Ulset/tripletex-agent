"""Fixtures for agent tuning tests.

These tests use the REAL LLM (Gemini via Vertex AI) with a mock Tripletex API
to measure agent behavior: API call count, error rate, and data completeness.

Requires Vertex AI credentials (gcloud auth locally, service account on Cloud Run).
"""

import os

import pytest

from tests.tuning.mock_client import AgentTestResult, MockTripletexClient

pytestmark = pytest.mark.tuning


def _vertex_ai_available() -> bool:
    try:
        from src.vertex_auth import get_openai_client
        get_openai_client()
        return True
    except Exception:
        return False


skip_no_vertex = pytest.mark.skipif(
    not _vertex_ai_available(),
    reason="Vertex AI credentials not available (run gcloud auth print-access-token)",
)


@pytest.fixture
def run_agent():
    """Fixture that returns a function to run the agent with a mock client.

    Usage:
        def test_something(run_agent):
            mock = MockTripletexClient()
            mock.register_entity("employee", {"id": 1, "email": "test@example.org"})
            result = run_agent("Create an employee...", mock)
            assert result.error_count == 0
    """
    def _run(
        prompt: str,
        mock_client: MockTripletexClient,
        model: str | None = None,
        file_contents: list[dict] | None = None,
    ) -> AgentTestResult:
        from src.agent import TripletexAgent

        if model is None:
            model = os.getenv("LLM_MODEL", "google/gemini-2.5-pro")

        agent = TripletexAgent(
            model=model,
            tripletex_client=mock_client,
            file_contents=file_contents,
        )
        agent.solve(prompt)
        return mock_client.get_result()

    return _run
