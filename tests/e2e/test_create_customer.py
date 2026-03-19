import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCreateCustomer:
    """E2E tests for creating customers via the Tripletex sandbox API."""

    def _unique_name(self, prefix: str = "Customer") -> str:
        short_id = uuid.uuid4().hex[:6]
        return f"{prefix} E2E-{short_id}"

    def test_create_and_verify_customer(self, tripletex_client):
        """Create a customer via POST, then verify it exists via GET."""
        name = self._unique_name("Acme Corp")

        customer_data = {
            "name": name,
            "isCustomer": True,
        }
        create_response = tripletex_client.post("/v2/customer", json=customer_data)

        assert "value" in create_response
        customer_id = create_response["value"]["id"]
        assert customer_id is not None

        # Verify via GET
        get_response = tripletex_client.get(f"/v2/customer/{customer_id}")

        assert get_response["value"]["id"] == customer_id
        assert get_response["value"]["name"] == name

    def test_create_customer_with_details(self, tripletex_client):
        """Create a customer with additional fields and verify."""
        name = self._unique_name("Norsk Bedrift")

        customer_data = {
            "name": name,
            "isCustomer": True,
            "email": f"e2e-{uuid.uuid4().hex[:6]}@example.com",
            "phoneNumber": "12345678",
        }
        create_response = tripletex_client.post("/v2/customer", json=customer_data)
        customer_id = create_response["value"]["id"]

        get_response = tripletex_client.get(f"/v2/customer/{customer_id}")

        assert get_response["value"]["name"] == name
        assert get_response["value"]["email"] == customer_data["email"]
