"""Regression tests derived from real competition submission failures.

Each test reproduces a specific failure scenario we hit during NM i AI submissions,
mocking OpenAI to simulate the LLM making correct decisions (or recovering from errors)
and verifying the agent produces the expected API calls.
"""

import json
from unittest.mock import MagicMock, patch

import responses

from src.config import Settings
from src.models import SolveRequest, TripletexCredentials


TRIPLETEX_BASE = "https://api.tripletex.io/v2"


def _settings():
    return Settings(
        openai_api_key="test-key",
        openai_model="gpt-4o",
        port=8000,
        api_key="",
    )


def _solve_request(prompt: str):
    return SolveRequest(
        prompt=prompt,
        files=[],
        tripletex_credentials=TripletexCredentials(
            base_url=TRIPLETEX_BASE,
            session_token="test-session",
        ),
    )


def _make_text_response(content="Task complete"):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call_response(method, endpoint, body=None, params=None, tool_call_id="call_1"):
    args = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if params is not None:
        args["params"] = params

    tool_call = MagicMock()
    tool_call.id = tool_call_id
    tool_call.function.name = "call_api"
    tool_call.function.arguments = json.dumps(args)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_doc_search_response(query, tool_call_id="call_doc"):
    """Make a tool call response for search_api_docs."""
    args = {"query": query}

    tool_call = MagicMock()
    tool_call.id = tool_call_id
    tool_call.function.name = "search_api_docs"
    tool_call.function.arguments = json.dumps(args)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


class TestPostalAddressFormat:
    """Regression: postalAddress must be an object, not a string.

    Real failure: Agent sent "postalAddress": "Nygata 24, 3015 Drammen"
    instead of {"addressLine1": "Nygata 24", "postalCode": "3015", "city": "Drammen"}.
    Got 422 from Tripletex.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_postal_address_is_object_not_string(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={
                "name": "Drammen Regnskap AS",
                "postalAddress": {
                    "addressLine1": "Nygata 24",
                    "postalCode": "3015",
                    "city": "Drammen",
                },
            }),
            _make_text_response("Created customer"),
        ]

        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/customer",
            json={"value": {"id": 1, "name": "Drammen Regnskap AS"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett kunde Drammen Regnskap AS, adresse Nygata 24, 3015 Drammen")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1
        body = json.loads(responses.calls[0].request.body)
        # postalAddress must be an object with structured fields
        assert isinstance(body["postalAddress"], dict)
        assert body["postalAddress"]["addressLine1"] == "Nygata 24"
        assert body["postalAddress"]["postalCode"] == "3015"
        assert body["postalAddress"]["city"] == "Drammen"


class TestEmployeeRequiredFields:
    """Regression: Employee creation requires userType, department, and email.

    Real failure: Agent sent {"firstName": "Arthur", "lastName": "Martin"} without
    userType/department/email. Got 422 "Brukertype kan ikke være 0 eller tom".
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_employee_includes_all_required_fields(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            # First get a department
            _make_tool_call_response("GET", "/v2/department", params={"fields": "id", "count": "1"}, tool_call_id="c1"),
            # Then create employee with all required fields
            _make_tool_call_response("POST", "/v2/employee", body={
                "firstName": "Arthur",
                "lastName": "Martin",
                "userType": "STANDARD",
                "email": "arthur.martin@example.no",
                "department": {"id": 10},
            }, tool_call_id="c2"),
            _make_text_response("Created employee Arthur Martin"),
        ]

        responses.add(
            responses.GET, f"{TRIPLETEX_BASE}/department",
            json={"values": [{"id": 10, "name": "Default"}]},
            status=200,
        )
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 42, "firstName": "Arthur", "lastName": "Martin"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Arthur Martin med e-post arthur.martin@example.no")
        )

        assert result.status == "completed"
        # Should have GET department + POST employee
        post_calls = [c for c in responses.calls if c.request.method == "POST"]
        assert len(post_calls) == 1
        body = json.loads(post_calls[0].request.body)
        assert body["firstName"] == "Arthur"
        assert body["lastName"] == "Martin"
        assert body["userType"] == "STANDARD"
        assert body["email"] == "arthur.martin@example.no"
        assert "department" in body
        assert body["department"]["id"] == 10


class TestEmploymentSeparateEntity:
    """Regression: Employment (start date) is a separate entity from employee.

    Real failure: Agent tried employmentStartDate on the employee object, got 422
    "field doesn't exist". Then searched docs 12 times and hit max iterations.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_employment_created_separately(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            # Get department
            _make_tool_call_response("GET", "/v2/department", params={"fields": "id", "count": "1"}, tool_call_id="c1"),
            # Create employee
            _make_tool_call_response("POST", "/v2/employee", body={
                "firstName": "Eva",
                "lastName": "Andersen",
                "userType": "STANDARD",
                "email": "eva.andersen@example.no",
                "department": {"id": 10},
            }, tool_call_id="c2"),
            # Create employment separately
            _make_tool_call_response("POST", "/v2/employee/employment", body={
                "employee": {"id": 99},
                "startDate": "2026-03-01",
            }, tool_call_id="c3"),
            _make_text_response("Created employee with employment"),
        ]

        responses.add(
            responses.GET, f"{TRIPLETEX_BASE}/department",
            json={"values": [{"id": 10, "name": "Default"}]},
            status=200,
        )
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 99, "firstName": "Eva", "lastName": "Andersen"}},
            status=201,
        )
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/employee/employment",
            json={"value": {"id": 200, "startDate": "2026-03-01"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Eva Andersen, startdato 2026-03-01, e-post eva.andersen@example.no")
        )

        assert result.status == "completed"
        post_calls = [c for c in responses.calls if c.request.method == "POST"]
        assert len(post_calls) == 2

        # First POST is employee
        assert "/employee" in post_calls[0].request.url
        assert "/employment" not in post_calls[0].request.url

        # Second POST is employment (separate endpoint)
        assert "/employee/employment" in post_calls[1].request.url
        employment_body = json.loads(post_calls[1].request.body)
        assert employment_body["startDate"] == "2026-03-01"
        assert employment_body["employee"]["id"] == 99


class TestProjectRequiresStartDate:
    """Regression: Project creation requires startDate.

    Real failure: Agent created project without startDate, got 422, then retried.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_project_includes_start_date(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/project", body={
                "name": "Webside Redesign",
                "number": "P-001",
                "projectManager": {"id": 1},
                "startDate": "2026-01-15",
            }),
            _make_text_response("Created project"),
        ]

        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/project",
            json={"value": {"id": 50, "name": "Webside Redesign"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett prosjekt Webside Redesign, nummer P-001, startdato 2026-01-15")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1
        body = json.loads(responses.calls[0].request.body)
        assert body["name"] == "Webside Redesign"
        assert body["startDate"] == "2026-01-15"
        assert body["projectManager"]["id"] == 1
        assert body["number"] == "P-001"


class TestSelfHealFromValidationError:
    """Regression: Agent must read 422 error messages and retry with correct fields.

    Real failure: Various 422 errors where the agent needed to read the error
    and add the missing field on retry.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_agent_retries_after_422_with_missing_field(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            # First attempt: missing startDate
            _make_tool_call_response("POST", "/v2/project", body={
                "name": "Alpha",
                "number": "A-1",
                "projectManager": {"id": 1},
            }, tool_call_id="c1"),
            # Second attempt: with startDate after reading 422 error
            _make_tool_call_response("POST", "/v2/project", body={
                "name": "Alpha",
                "number": "A-1",
                "projectManager": {"id": 1},
                "startDate": "2026-01-01",
            }, tool_call_id="c2"),
            _make_text_response("Created project Alpha"),
        ]

        # First call fails
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/project",
            json={"message": "Validation failed", "details": "startDate: required field missing"},
            status=422,
        )
        # Second call succeeds
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/project",
            json={"value": {"id": 60, "name": "Alpha"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett prosjekt Alpha, nummer A-1, startdato 2026-01-01")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 2

        # First call missing startDate
        first_body = json.loads(responses.calls[0].request.body)
        assert "startDate" not in first_body

        # Second call has startDate
        second_body = json.loads(responses.calls[1].request.body)
        assert second_body["startDate"] == "2026-01-01"


class TestDocSearchNotExcessive:
    """Regression: Agent must not waste iterations on excessive doc searches.

    Real failure: Agent searched docs 9-12 times after a single error,
    hitting max iterations without making a useful API call.
    """

    @responses.activate
    @patch("src.agent.search_api_docs")
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_agent_limits_doc_searches(self, mock_file_openai, mock_agent_openai, mock_search_docs):
        from src.orchestrator import TaskOrchestrator

        mock_search_docs.return_value = "Found 1 endpoint: POST /v2/supplier ..."

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            # One doc search
            _make_doc_search_response("supplier", tool_call_id="d1"),
            # Then the correct API call
            _make_tool_call_response("POST", "/v2/supplier", body={
                "name": "Leverandør AS",
                "isSupplier": True,
            }, tool_call_id="c1"),
            _make_text_response("Created supplier"),
        ]

        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/supplier",
            json={"value": {"id": 70, "name": "Leverandør AS"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett leverandør Leverandør AS")
        )

        assert result.status == "completed"
        # Total LLM calls should be 3 (doc search + api call + final text), not 15
        assert mock_openai.chat.completions.create.call_count == 3


class TestSupplierIncludesOrgNumber:
    """Regression: Supplier creation must include organizationNumber.

    Real failure: Agent created supplier without organizationNumber.
    Scored 0 because the field was missing from the payload.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_supplier_has_organization_number(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/supplier", body={
                "name": "Oslo Leverandør AS",
                "organizationNumber": "987654321",
                "email": "post@osloleverandor.no",
                "isSupplier": True,
            }),
            _make_text_response("Created supplier"),
        ]

        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/supplier",
            json={"value": {"id": 80, "name": "Oslo Leverandør AS"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett leverandør Oslo Leverandør AS, org.nr 987654321, epost post@osloleverandor.no")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1
        body = json.loads(responses.calls[0].request.body)
        assert body["name"] == "Oslo Leverandør AS"
        assert body["organizationNumber"] == "987654321"
        assert body["email"] == "post@osloleverandor.no"
        assert body["isSupplier"] is True


class TestPaymentUsesQueryParams:
    """Regression: PUT /v2/invoice/{id}/:payment requires query params, not body.

    Real failure: _execute_api_call passed params only to GET, silently dropped
    them on PUT. Tripletex got nulls → 422.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_put_payment_sends_query_params(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("PUT", "/v2/invoice/123/:payment", params={
                "paymentDate": "2026-03-19",
                "paymentTypeId": "1",
                "paidAmount": "15000",
                "paidAmountCurrency": "15000",
            }),
            _make_text_response("Payment registered"),
        ]

        responses.add(
            responses.PUT, f"{TRIPLETEX_BASE}/invoice/123/:payment",
            json={"value": {"id": 500}},
            status=200,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Registrer betaling for faktura 123")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 1
        req = responses.calls[0].request
        # Params must be in the URL query string, not the body
        assert "paymentDate=2026-03-19" in req.url
        assert "paymentTypeId=1" in req.url
        assert "paidAmount=15000" in req.url


class TestDocSearchLimitEnforced:
    """Regression: Doc search must be capped at 2 in code, not just prompt.

    Real failure: LLM ignored the "max 2" instruction and searched 9-12 times,
    burning all iterations without making API calls.
    """

    @responses.activate
    @patch("src.agent.search_api_docs")
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_third_doc_search_returns_limit_message(self, mock_file_openai, mock_agent_openai, mock_search_docs):
        from src.orchestrator import TaskOrchestrator

        mock_search_docs.return_value = "Found endpoint info..."

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_doc_search_response("employee", tool_call_id="d1"),
            _make_doc_search_response("employment", tool_call_id="d2"),
            _make_doc_search_response("employee fields", tool_call_id="d3"),  # 3rd — should be blocked
            _make_tool_call_response("POST", "/v2/employee", body={
                "firstName": "Test",
                "lastName": "User",
                "userType": "STANDARD",
                "email": "test@example.no",
                "department": {"id": 1},
            }, tool_call_id="c1"),
            _make_text_response("Done"),
        ]

        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/employee",
            json={"value": {"id": 1}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett ansatt Test User")
        )

        assert result.status == "completed"
        # search_api_docs should only have been called twice (3rd was blocked)
        assert mock_search_docs.call_count == 2


class TestPaymentFullWorkflow:
    """Regression: Payment requires finding customer, invoice, paymentType first.

    Real failure: Agent tried GET /v2/invoice without date params → 422.
    Or couldn't find invoice because it didn't filter by customerId.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_payment_workflow_find_and_pay(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            # Step 1: Find customer
            _make_tool_call_response("GET", "/v2/customer", params={
                "organizationNumber": "999888777",
            }, tool_call_id="c1"),
            # Step 2: Find invoices with date params
            _make_tool_call_response("GET", "/v2/invoice", params={
                "invoiceDateFrom": "2000-01-01",
                "invoiceDateTo": "2030-12-31",
                "customerId": "50",
            }, tool_call_id="c2"),
            # Step 3: Get payment types
            _make_tool_call_response("GET", "/v2/invoice/paymentType", tool_call_id="c3"),
            # Step 4: Register payment with query params
            _make_tool_call_response("PUT", "/v2/invoice/200/:payment", params={
                "paymentDate": "2026-03-19",
                "paymentTypeId": "3",
                "paidAmount": "25000",
                "paidAmountCurrency": "25000",
            }, tool_call_id="c4"),
            _make_text_response("Payment registered"),
        ]

        responses.add(responses.GET, f"{TRIPLETEX_BASE}/customer",
                       json={"values": [{"id": 50, "name": "Firma AS"}]}, status=200)
        responses.add(responses.GET, f"{TRIPLETEX_BASE}/invoice",
                       json={"values": [{"id": 200, "amountOutstanding": 25000}]}, status=200)
        responses.add(responses.GET, f"{TRIPLETEX_BASE}/invoice/paymentType",
                       json={"values": [{"id": 3, "description": "Bankinnskudd"}]}, status=200)
        responses.add(responses.PUT, f"{TRIPLETEX_BASE}/invoice/200/:payment",
                       json={"value": {"id": 600}}, status=200)

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Registrer full betaling for kunde med org.nr 999888777")
        )

        assert result.status == "completed"
        assert len(responses.calls) == 4

        # Verify invoice GET had required date params
        invoice_req = responses.calls[1].request
        assert "invoiceDateFrom" in invoice_req.url
        assert "invoiceDateTo" in invoice_req.url

        # Verify payment PUT used query params
        payment_req = responses.calls[3].request
        assert "paymentDate=2026-03-19" in payment_req.url
        assert "paymentTypeId=3" in payment_req.url
        assert "paidAmount=25000" in payment_req.url


class TestMultipleDepartments:
    """Regression: Agent can create multiple departments in a single task.

    Not a failure case, but a good regression test for multi-entity tasks.
    """

    @responses.activate
    @patch("src.agent.OpenAI")
    @patch("src.file_processor.OpenAI")
    def test_creates_three_departments(self, mock_file_openai, mock_agent_openai):
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/department", body={
                "name": "Salg",
                "departmentNumber": "100",
            }, tool_call_id="c1"),
            _make_tool_call_response("POST", "/v2/department", body={
                "name": "Økonomi",
                "departmentNumber": "200",
            }, tool_call_id="c2"),
            _make_tool_call_response("POST", "/v2/department", body={
                "name": "IT",
                "departmentNumber": "300",
            }, tool_call_id="c3"),
            _make_text_response("Created 3 departments"),
        ]

        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/department",
            json={"value": {"id": 1, "name": "Salg"}},
            status=201,
        )
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/department",
            json={"value": {"id": 2, "name": "Økonomi"}},
            status=201,
        )
        responses.add(
            responses.POST, f"{TRIPLETEX_BASE}/department",
            json={"value": {"id": 3, "name": "IT"}},
            status=201,
        )

        result = TaskOrchestrator(_settings()).solve(
            _solve_request("Opprett tre avdelinger: Salg (100), Økonomi (200), IT (300)")
        )

        assert result.status == "completed"
        post_calls = [c for c in responses.calls if c.request.method == "POST"]
        assert len(post_calls) == 3

        names = [json.loads(c.request.body)["name"] for c in post_calls]
        assert "Salg" in names
        assert "Økonomi" in names
        assert "IT" in names

        numbers = [json.loads(c.request.body)["departmentNumber"] for c in post_calls]
        assert "100" in numbers
        assert "200" in numbers
        assert "300" in numbers
