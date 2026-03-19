import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCreateEmployee:
    """E2E tests for creating employees via the Tripletex sandbox API."""

    def _unique_name(self, prefix: str = "Test") -> str:
        short_id = uuid.uuid4().hex[:6]
        return f"{prefix} E2E-{short_id}"

    def test_create_and_verify_employee(self, tripletex_client):
        """Create an employee via POST, then verify it exists via GET."""
        first_name = self._unique_name("Ola")
        last_name = self._unique_name("Nordmann")

        # Create employee
        employee_data = {
            "firstName": first_name,
            "lastName": last_name,
        }
        create_response = tripletex_client.post("/v2/employee", json=employee_data)

        assert "value" in create_response
        employee_id = create_response["value"]["id"]
        assert employee_id is not None

        # Verify via GET
        get_response = tripletex_client.get(f"/v2/employee/{employee_id}")

        assert get_response["value"]["id"] == employee_id
        assert get_response["value"]["firstName"] == first_name
        assert get_response["value"]["lastName"] == last_name

    def test_create_employee_with_norwegian_characters(self, tripletex_client):
        """Verify Norwegian special characters are preserved."""
        first_name = f"Bjørn-{uuid.uuid4().hex[:4]}"
        last_name = f"Ødegård-{uuid.uuid4().hex[:4]}"

        employee_data = {
            "firstName": first_name,
            "lastName": last_name,
        }
        create_response = tripletex_client.post("/v2/employee", json=employee_data)
        employee_id = create_response["value"]["id"]

        get_response = tripletex_client.get(f"/v2/employee/{employee_id}")

        assert get_response["value"]["firstName"] == first_name
        assert get_response["value"]["lastName"] == last_name
