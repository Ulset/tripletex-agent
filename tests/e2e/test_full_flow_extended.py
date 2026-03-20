import uuid

import pytest

from src.config import Settings
from src.models import SolveRequest, TripletexCredentials
from src.orchestrator import TaskOrchestrator
from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestFullFlowExtended:
    """Extended e2e tests running full agent flows against the Tripletex sandbox."""

    def _make_request(self, prompt, base_url, session_token):
        config = Settings(llm_model="google/gemini-2.5-flash", port=8000, api_key="")
        orchestrator = TaskOrchestrator(config)
        request = SolveRequest(
            prompt=prompt,
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url=base_url,
                session_token=session_token,
            ),
        )
        return orchestrator.solve(request)

    def test_full_flow_create_department(self, sandbox_credentials):
        """Agent creates a department from Norwegian prompt."""
        base_url, session_token = sandbox_credentials
        unique = uuid.uuid4().hex[:6]
        dept_name = f"Avdeling-{unique}"

        response = self._make_request(
            f"Opprett en avdeling med navn '{dept_name}' og avdelingsnummer 'A{unique[:4]}'",
            base_url, session_token,
        )
        assert response.status == "completed"

        from src.tripletex_client import TripletexClient
        client = TripletexClient(base_url=base_url, session_token=session_token)
        result = client.get("/v2/department", params={"query": dept_name})
        found = any(d["name"] == dept_name for d in result.get("values", []))
        assert found, f"Department '{dept_name}' not found after agent run"

    def test_full_flow_create_customer_with_address(self, sandbox_credentials):
        """Agent creates a customer with postal address from Spanish prompt."""
        base_url, session_token = sandbox_credentials
        unique = uuid.uuid4().hex[:6]
        cust_name = f"Empresa-{unique}"

        response = self._make_request(
            f"Registre un nuevo cliente llamado '{cust_name}' con dirección postal Nygata 24, 3015 Drammen.",
            base_url, session_token,
        )
        assert response.status == "completed"

    def test_full_flow_create_supplier(self, sandbox_credentials):
        """Agent creates a supplier from English prompt."""
        base_url, session_token = sandbox_credentials
        unique = uuid.uuid4().hex[:6]
        supplier_name = f"Supplier-{unique}"

        response = self._make_request(
            f"Create a supplier named '{supplier_name}' with organization number 987654321 and email contact@example.com",
            base_url, session_token,
        )
        assert response.status == "completed"

    def test_full_flow_create_product_with_price(self, sandbox_credentials):
        """Agent creates a product with price from German prompt."""
        base_url, session_token = sandbox_credentials
        unique = uuid.uuid4().hex[:6]
        product_name = f"Produkt-{unique}"

        response = self._make_request(
            f"Erstellen Sie ein Produkt mit dem Namen '{product_name}', Produktnummer 'P{unique}', und Preis 250,00 NOK.",
            base_url, session_token,
        )
        assert response.status == "completed"
