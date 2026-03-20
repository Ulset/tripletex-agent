import json
from unittest.mock import MagicMock, patch

from tests.fixtures.sample_prompts import SAMPLE_PROMPTS


def _make_text_response(content="Done"):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


class TestMultiLanguagePrompts:
    """Verify agent handles prompts in multiple languages with special characters."""

    def test_sample_prompts_cover_all_languages(self):
        """Verify the fixture contains all 7 required languages."""
        required = {"nb", "nn", "en", "es", "pt", "de", "fr"}
        assert set(SAMPLE_PROMPTS.keys()) == required

    def test_all_prompts_have_special_characters(self):
        """Verify each prompt includes names with non-ASCII characters."""
        for lang, sample in SAMPLE_PROMPTS.items():
            name = sample["expected_first_name"] + sample["expected_last_name"]
            has_special = any(ord(c) > 127 for c in name)
            assert has_special, f"Language {lang} prompt missing special characters in name"

    @patch("src.agent.get_openai_client")
    def test_norwegian_bokmal_prompt(self, mock_openai_cls):
        from src.agent import TripletexAgent

        sample = SAMPLE_PROMPTS["nb"]
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Created Bjørn Ødegård")

        agent = TripletexAgent(model="google/gemini-2.5-flash", tripletex_client=MagicMock())
        agent.solve(sample["prompt"])

        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = [m for m in messages if m["role"] == "user"][0]
        assert "Bjørn" in user_msg["content"]
        assert "Ødegård" in user_msg["content"]

    @patch("src.agent.get_openai_client")
    def test_english_prompt(self, mock_openai_cls):
        from src.agent import TripletexAgent

        sample = SAMPLE_PROMPTS["en"]
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        agent = TripletexAgent(model="google/gemini-2.5-flash", tripletex_client=MagicMock())
        agent.solve(sample["prompt"])

        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = [m for m in messages if m["role"] == "user"][0]
        assert "François" in user_msg["content"]

    @patch("src.agent.get_openai_client")
    def test_spanish_prompt(self, mock_openai_cls):
        from src.agent import TripletexAgent

        sample = SAMPLE_PROMPTS["es"]
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        agent = TripletexAgent(model="google/gemini-2.5-flash", tripletex_client=MagicMock())
        agent.solve(sample["prompt"])

        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = [m for m in messages if m["role"] == "user"][0]
        assert "José" in user_msg["content"]
        assert "Muñoz" in user_msg["content"]

    @patch("src.agent.get_openai_client")
    def test_special_characters_preserved_in_all_languages(self, mock_openai_cls):
        """Verify special characters are preserved for every supported language."""
        from src.agent import TripletexAgent

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = _make_text_response("Done")

        agent = TripletexAgent(model="google/gemini-2.5-flash", tripletex_client=MagicMock())

        for lang, sample in SAMPLE_PROMPTS.items():
            mock_openai.chat.completions.create.reset_mock()
            agent.solve(sample["prompt"])

            call_args = mock_openai.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            user_msg = [m for m in messages if m["role"] == "user"][0]
            assert sample["expected_first_name"] in user_msg["content"], (
                f"firstName not preserved for {lang}"
            )
