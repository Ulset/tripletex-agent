from unittest.mock import MagicMock, patch

import pytest

from src.agent import TripletexAgent, CALL_API_TOOL, MAX_ITERATIONS
from src.tripletex_client import TripletexAPIError


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
    import json

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


class TestTripletexAgent:
    def setup_method(self):
        self.client = MagicMock()
        self.agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )

    @patch("src.agent.OpenAI")
    def test_loop_completes_on_text_response(self, mock_openai_cls):
        """Agent should stop when LLM responds with text (no tool calls)."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done!")

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )
        agent.solve("Create a customer named Acme")

        mock_openai.chat.completions.create.assert_called_once()
        self.client.get.assert_not_called()
        self.client.post.assert_not_called()

    @patch("src.agent.OpenAI")
    def test_tool_call_executed_and_result_sent_back(self, mock_openai_cls):
        """Agent should execute tool calls and return result to LLM."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # First call: LLM makes a tool call, second call: LLM says done
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/customer", body={"name": "Acme"}),
            _make_text_response("Created customer Acme"),
        ]
        self.client.post.return_value = {"value": {"id": 1, "name": "Acme"}}

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )
        agent.solve("Create a customer named Acme")

        self.client.post.assert_called_once_with("/v2/customer", json={"name": "Acme"})
        assert mock_openai.chat.completions.create.call_count == 2

    @patch("src.agent.OpenAI")
    def test_max_iterations_stops_loop(self, mock_openai_cls):
        """Agent should stop after MAX_ITERATIONS even if LLM keeps making tool calls."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # Always return a tool call — agent should still stop at MAX_ITERATIONS
        mock_openai.chat.completions.create.return_value = _make_tool_call_response(
            "GET", "/v2/customer", params={"name": "Acme"}
        )
        self.client.get.return_value = {"values": []}

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )
        agent.solve("Find customer Acme")

        assert mock_openai.chat.completions.create.call_count == MAX_ITERATIONS
        assert self.client.get.call_count == MAX_ITERATIONS

    @patch("src.agent.OpenAI")
    def test_api_error_returned_to_llm(self, mock_openai_cls):
        """API errors should be sent back to LLM as tool results so it can adapt."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # First call: tool call that will fail, second call: LLM gives up
        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("POST", "/v2/employee", body={"firstName": "Ola"}),
            _make_text_response("Could not create employee"),
        ]
        self.client.post.side_effect = TripletexAPIError(422, "Missing required field: lastName")

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )
        agent.solve("Create an employee named Ola")

        assert mock_openai.chat.completions.create.call_count == 2
        # Verify the error was appended as a tool result
        second_call_messages = mock_openai.chat.completions.create.call_args_list[1].kwargs.get(
            "messages", mock_openai.chat.completions.create.call_args_list[1][1].get("messages", [])
            if len(mock_openai.chat.completions.create.call_args_list[1]) > 1 else []
        )
        if not second_call_messages:
            second_call_messages = mock_openai.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_results = [m for m in second_call_messages if isinstance(m, dict) and m.get("role") == "tool"]
        assert len(tool_results) == 1
        assert "error" in tool_results[0]["content"]

    @patch("src.agent.OpenAI")
    def test_file_contents_included_in_prompt(self, mock_openai_cls):
        """File contents should be appended to the user message."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        file_contents = [{"filename": "invoice.pdf", "extracted_text": "Invoice #123"}]

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
            file_contents=file_contents,
        )
        agent.solve("Process this invoice")

        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        user_msg = [m for m in messages if m["role"] == "user"][0]
        assert "invoice.pdf" in user_msg["content"]
        assert "Invoice #123" in user_msg["content"]

    @patch("src.agent.OpenAI")
    def test_get_call_uses_params(self, mock_openai_cls):
        """GET calls should pass params to TripletexClient.get()."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("GET", "/v2/department", params={"fields": "id", "count": "1"}),
            _make_text_response("Found department"),
        ]
        self.client.get.return_value = {"values": [{"id": 5}]}

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )
        agent.solve("Look up departments")

        self.client.get.assert_called_once_with("/v2/department", params={"fields": "id", "count": "1"})

    @patch("src.agent.OpenAI")
    def test_delete_call(self, mock_openai_cls):
        """DELETE calls should use TripletexClient.delete()."""
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        mock_openai.chat.completions.create.side_effect = [
            _make_tool_call_response("DELETE", "/v2/travelExpense/42"),
            _make_text_response("Deleted"),
        ]
        self.client.delete.return_value = {}

        agent = TripletexAgent(
            openai_api_key="test-key",
            model="gpt-4o",
            tripletex_client=self.client,
        )
        agent.solve("Delete travel expense 42")

        self.client.delete.assert_called_once_with("/v2/travelExpense/42")

    def test_call_api_tool_schema(self):
        """Verify the call_api tool definition has correct schema."""
        assert CALL_API_TOOL["type"] == "function"
        func = CALL_API_TOOL["function"]
        assert func["name"] == "call_api"
        props = func["parameters"]["properties"]
        assert "method" in props
        assert "endpoint" in props
        assert "body" in props
        assert "params" in props
        assert set(func["parameters"]["required"]) == {"method", "endpoint"}


class TestSystemPrompt:
    """Tests for US-002: System prompt content verification."""

    def test_includes_api_reference(self):
        from src.agent import SYSTEM_PROMPT
        from src.knowledge import TRIPLETEX_API_REFERENCE
        assert TRIPLETEX_API_REFERENCE in SYSTEM_PROMPT

    def test_instructs_include_all_data(self):
        from src.agent import SYSTEM_PROMPT
        assert "EVERY piece of data" in SYSTEM_PROMPT or "ALL data" in SYSTEM_PROMPT
        assert "organizationNumber" in SYSTEM_PROMPT
        assert "email" in SYSTEM_PROMPT

    def test_instructs_use_call_api_tool(self):
        from src.agent import SYSTEM_PROMPT
        assert "call_api" in SYSTEM_PROMPT

    def test_instructs_text_response_when_done(self):
        from src.agent import SYSTEM_PROMPT
        assert "text message" in SYSTEM_PROMPT.lower() or "no tool call" in SYSTEM_PROMPT.lower()

    def test_documents_response_shapes(self):
        from src.agent import SYSTEM_PROMPT
        assert "values" in SYSTEM_PROMPT
        assert "value" in SYSTEM_PROMPT

    def test_includes_efficiency_guidelines(self):
        from src.agent import SYSTEM_PROMPT
        assert "Minimize" in SYSTEM_PROMPT or "minimize" in SYSTEM_PROMPT
        assert "Reuse IDs" in SYSTEM_PROMPT or "reuse IDs" in SYSTEM_PROMPT

    def test_handles_all_seven_languages(self):
        from src.agent import SYSTEM_PROMPT
        for lang in ["Norwegian Bokmål", "Norwegian Nynorsk", "English", "Spanish", "Portuguese", "German", "French"]:
            assert lang in SYSTEM_PROMPT, f"Missing language: {lang}"

    def test_preserves_norwegian_characters(self):
        from src.agent import SYSTEM_PROMPT
        assert "æ" in SYSTEM_PROMPT
        assert "ø" in SYSTEM_PROMPT
        assert "å" in SYSTEM_PROMPT
