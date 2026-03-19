from unittest.mock import patch

from fastapi.testclient import TestClient

from src.main import app
from src.models import SolveResponse

client = TestClient(app)


def test_root_returns_ok():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


VALID_SOLVE_BODY = {
    "prompt": "Create an employee named Ola Nordmann",
    "files": [],
    "tripletex_credentials": {
        "base_url": "https://api.tripletex.io/v2",
        "session_token": "test-token-123",
    },
}


@patch("src.main.TaskOrchestrator")
class TestSolveEndpoint:
    def test_valid_request_returns_200(self, mock_orch_cls):
        mock_orch_cls.return_value.solve.return_value = SolveResponse(status="completed")
        response = client.post("/solve", json=VALID_SOLVE_BODY)
        assert response.status_code == 200
        assert response.json() == {"status": "completed"}

    def test_invalid_body_returns_422(self, mock_orch_cls):
        response = client.post("/solve", json={"bad": "data"})
        assert response.status_code == 422

    @patch("src.main.settings")
    def test_wrong_api_key_returns_401(self, mock_settings, mock_orch_cls):
        mock_settings.api_key = "secret-key"
        response = client.post(
            "/solve",
            json=VALID_SOLVE_BODY,
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert response.status_code == 401

    @patch("src.main.settings")
    def test_correct_api_key_returns_200(self, mock_settings, mock_orch_cls):
        mock_orch_cls.return_value.solve.return_value = SolveResponse(status="completed")
        mock_settings.api_key = "secret-key"
        response = client.post(
            "/solve",
            json=VALID_SOLVE_BODY,
            headers={"Authorization": "Bearer secret-key"},
        )
        assert response.status_code == 200

    @patch("src.main.settings")
    def test_no_api_key_configured_skips_auth(self, mock_settings, mock_orch_cls):
        mock_orch_cls.return_value.solve.return_value = SolveResponse(status="completed")
        mock_settings.api_key = ""
        response = client.post("/solve", json=VALID_SOLVE_BODY)
        assert response.status_code == 200

    def test_request_with_files(self, mock_orch_cls):
        mock_orch_cls.return_value.solve.return_value = SolveResponse(status="completed")
        body = {
            **VALID_SOLVE_BODY,
            "files": [
                {
                    "filename": "invoice.pdf",
                    "content_base64": "dGVzdA==",
                    "mime_type": "application/pdf",
                }
            ],
        }
        response = client.post("/solve", json=body)
        assert response.status_code == 200
        assert response.json() == {"status": "completed"}

    def test_alternative_field_names_task_prompt(self, mock_orch_cls):
        """Competition may send task_prompt instead of prompt."""
        mock_orch_cls.return_value.solve.return_value = SolveResponse(status="completed")
        body = {
            "task_prompt": "Create an employee named Ola Nordmann",
            "attachments": [],
            "tripletex_credentials": {
                "base_url": "https://api.tripletex.io/v2",
                "session_token": "test-token-123",
            },
        }
        response = client.post("/solve", json=body)
        assert response.status_code == 200
        assert response.json() == {"status": "completed"}
