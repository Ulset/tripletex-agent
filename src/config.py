from dataclasses import dataclass, field
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "google/gemini-2.5-flash"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))


settings = Settings()
