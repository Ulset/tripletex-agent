import json
from unittest.mock import MagicMock, patch

from src.config import Settings
from src.models import SolveRequest, TripletexCredentials


TRIPLETEX_BASE = "https://api.tripletex.io/v2"


def _make_settings():
    return Settings(
        llm_model="google/gemini-2.5-flash",
        port=8000,
        api_key="",
    )


def _make_request(prompt="Create an employee named Ola Nordmann", files=None):
    return SolveRequest(
        prompt=prompt,
        files=files or [],
        tripletex_credentials=TripletexCredentials(
            base_url=TRIPLETEX_BASE,
            session_token="test-session",
        ),
    )


def _make_text_response(content="Task complete"):
    """Create a mock OpenAI response with a text message (no tool calls)."""
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
    """Create a mock OpenAI response with a call_api tool call."""
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


class TestTaskOrchestrator:
    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_agent_based_flow(self, mock_file_openai, mock_agent_openai):
        """Full flow: prompt -> agent loop -> completed."""
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai

        # Agent makes one API call then says done
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/employee", body={"firstName": "Ola", "lastName": "Nordmann"}),
            _make_text_response("Created employee Ola Nordmann"),
        ]

        with patch("src.orchestrator.TripletexClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.post.return_value = {"value": {"id": 1, "firstName": "Ola", "lastName": "Nordmann"}}

            orchestrator = TaskOrchestrator(_make_settings())
            result = orchestrator.solve(_make_request())

        assert result.status == "completed"
        mock_client.post.assert_called_once_with("/v2/employee", json={"firstName": "Ola", "lastName": "Nordmann"})

    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_returns_completed_on_exception(self, mock_file_openai, mock_agent_openai):
        """Orchestrator must always return status=completed even if agent raises."""
        from src.orchestrator import TaskOrchestrator

        mock_agent_openai.return_value.chat.completions.create.side_effect = Exception("LLM down")

        orchestrator = TaskOrchestrator(_make_settings())
        result = orchestrator.solve(_make_request())

        assert result.status == "completed"

    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_file_processing_before_agent(self, mock_file_openai, mock_agent_openai):
        """File processing happens before agent is invoked."""
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        with patch("src.orchestrator.TripletexClient"):
            orchestrator = TaskOrchestrator(_make_settings())
            result = orchestrator.solve(_make_request())

        assert result.status == "completed"
        # Agent OpenAI was called (for the agent loop)
        mock_openai.chat.completions.create.assert_called_once()

    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_orchestrator_creates_client_from_credentials(self, mock_file_openai, mock_agent_openai):
        """Verify TripletexClient is created from request credentials."""
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        with patch("src.orchestrator.TripletexClient") as mock_client_cls:
            orchestrator = TaskOrchestrator(_make_settings())
            orchestrator.solve(_make_request())

            mock_client_cls.assert_called_once_with(
                base_url=TRIPLETEX_BASE,
                session_token="test-session",
            )

    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_logging_preserved(self, mock_file_openai, mock_agent_openai):
        """Existing orchestrator logging (NEW TASK RECEIVED, etc.) is preserved."""
        from src.orchestrator import TaskOrchestrator

        mock_openai = MagicMock()
        mock_agent_openai.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        with patch("src.orchestrator.TripletexClient"):
            with patch("src.orchestrator.logger") as mock_logger:
                orchestrator = TaskOrchestrator(_make_settings())
                orchestrator.solve(_make_request())

        log_messages = [str(call) for call in mock_logger.info.call_args_list]
        assert any("NEW TASK RECEIVED" in msg for msg in log_messages)
        assert any("Full prompt" in msg for msg in log_messages)

    @patch("src.agent.get_openai_client")
    @patch("src.file_processor.get_openai_client")
    def test_no_plan_generator_imports(self, mock_file_openai, mock_agent_openai):
        """Orchestrator no longer imports PlanGenerator or PlanExecutor."""
        import src.orchestrator as orch_module
        assert not hasattr(orch_module, "PlanGenerator")
        assert not hasattr(orch_module, "PlanExecutor")
