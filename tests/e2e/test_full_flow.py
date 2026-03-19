import uuid

import pytest

from src.config import Settings
from src.models import SolveRequest, TripletexCredentials
from src.orchestrator import TaskOrchestrator
from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestFullFlow:
    """E2E tests running the full orchestrator flow against the Tripletex sandbox."""

    def test_full_flow_create_employee(self, sandbox_credentials, openai_api_key):
        """Send a full SolveRequest through the orchestrator and verify entity creation."""
        base_url, session_token = sandbox_credentials
        unique_id = uuid.uuid4().hex[:6]
        first_name = f"TestAgent-{unique_id}"
        last_name = f"Fullflow-{unique_id}"

        config = Settings(
            openai_api_key=openai_api_key,
            openai_model="gpt-4o",
            port=8000,
            api_key="",
        )
        orchestrator = TaskOrchestrator(config)

        request = SolveRequest(
            prompt=f"Opprett en ansatt med fornavn '{first_name}' og etternavn '{last_name}'",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url=base_url,
                session_token=session_token,
            ),
        )

        response = orchestrator.solve(request)

        # Competition requires status=completed regardless of outcome
        assert response.status == "completed"

        # Verify the employee was actually created by searching
        from src.tripletex_client import TripletexClient

        client = TripletexClient(base_url=base_url, session_token=session_token)
        search_result = client.get(
            "/v2/employee",
            params={"firstName": first_name},
        )

        # Check that at least one employee with our unique name was found
        assert search_result.get("fullResultSize", 0) > 0
        found = any(
            emp["firstName"] == first_name
            for emp in search_result.get("values", [])
        )
        assert found, f"Employee '{first_name}' not found in sandbox after orchestrator run"
