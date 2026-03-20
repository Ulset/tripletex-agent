import uuid

import pytest

from tests.e2e.conftest import skip_no_credentials


@skip_no_credentials
@pytest.mark.e2e
class TestCreateProject:
    """E2E tests for creating projects via the Tripletex sandbox API."""

    def _get_employee_id(self, client):
        """Get the first available employee ID for use as project manager."""
        resp = client.get("/v2/employee", params={"count": 1, "fields": "id"})
        assert resp.get("fullResultSize", 0) > 0
        return resp["values"][0]["id"]

    def test_create_project_basic(self, tripletex_client):
        """Create a project with required fields."""
        unique = uuid.uuid4().hex[:6]
        name = f"Project E2E-{unique}"
        number = f"PRJ{unique}"
        manager_id = self._get_employee_id(tripletex_client)

        data = {
            "name": name,
            "number": number,
            "projectManager": {"id": manager_id},
            "startDate": "2026-01-01",
        }
        resp = tripletex_client.post("/v2/project", json=data)

        assert "value" in resp
        project_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/project/{project_id}")
        assert get_resp["value"]["name"] == name
        assert get_resp["value"]["number"] == number

    def test_create_project_with_customer(self, tripletex_client):
        """Create a project linked to a customer."""
        unique = uuid.uuid4().hex[:6]

        # Create a customer first
        customer_name = f"ProjCust-{unique}"
        cust_resp = tripletex_client.post("/v2/customer", json={
            "name": customer_name,
            "isCustomer": True,
        })
        customer_id = cust_resp["value"]["id"]

        manager_id = self._get_employee_id(tripletex_client)

        data = {
            "name": f"Project WithCust-{unique}",
            "number": f"PC{unique}",
            "projectManager": {"id": manager_id},
            "startDate": "2026-01-01",
            "customer": {"id": customer_id},
        }
        resp = tripletex_client.post("/v2/project", json=data)

        assert "value" in resp
        project_id = resp["value"]["id"]

        get_resp = tripletex_client.get(f"/v2/project/{project_id}")
        assert get_resp["value"]["name"] == data["name"]
