import os
from unittest.mock import patch

from src.config import Settings


def test_settings_defaults():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings()
        assert s.llm_model == "google/gemini-2.5-flash"
        assert s.port == 8000
        assert s.api_key == ""


def test_settings_from_env():
    env = {
        "LLM_MODEL": "google/gemini-2.5-pro",
        "PORT": "9000",
        "API_KEY": "secret",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.llm_model == "google/gemini-2.5-pro"
        assert s.port == 9000
        assert s.api_key == "secret"
