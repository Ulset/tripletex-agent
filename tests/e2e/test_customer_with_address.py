import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCustomerWithAddress:
    """E2E tests for creating customers with postal addresses."""

    def test_create_customer_with_postal_address(self, tripletex_client):
        """Create a customer with postal address as JSON object."""
        unique = uuid.uuid4().hex[:6]
        name = f"Customer Addr-{unique}"

        data = {
            "name": name,
            "isCustomer": True,
            "postalAddress": {
                "addressLine1": "Nygata 24",
                "postalCode": "3015",
                "city": "Drammen",
            },
        }
        resp = tripletex_client.post("/v2/customer", json=data)

        assert "value" in resp
        customer_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/customer/{customer_id}")
        assert get_resp["value"]["name"] == name

    def test_create_customer_with_org_number_and_address(self, tripletex_client):
        """Create a customer with organizationNumber and address."""
        unique = uuid.uuid4().hex[:6]
        name = f"Customer OrgAddr-{unique}"
        import random
        org_number = str(random.randint(800000000, 899999999))  # 9 digits, numeric only

        data = {
            "name": name,
            "isCustomer": True,
            "organizationNumber": org_number,
            "email": f"cust-{unique}@example.com",
            "phoneNumber": "12345678",
            "postalAddress": {
                "addressLine1": "Karl Johans gate 1",
                "postalCode": "0154",
                "city": "Oslo",
            },
        }
        resp = tripletex_client.post("/v2/customer", json=data)

        assert "value" in resp
        customer_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/customer/{customer_id}")
        assert get_resp["value"]["name"] == name
        assert get_resp["value"]["organizationNumber"] == org_number
