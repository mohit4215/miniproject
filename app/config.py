import json
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _bool(v: str) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
    dev_auth: bool = _bool(os.getenv("DEV_AUTH", "0"))
    admin_uids: list = field(default_factory=lambda: [
        u.strip() for u in os.getenv("ADMIN_UIDS", "").split(",") if u.strip()
    ])

    firebase_config: dict = field(
        default_factory=lambda: json.loads(os.getenv("FIREBASE_CONFIG_JSON", "{}") or "{}")
    )
    firebase_sa_json: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    firebase_sa_path: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

    context_budget_tokens: int = int(os.getenv("CONTEXT_BUDGET_TOKENS", "6000"))
    max_output_tokens: int = int(os.getenv("MAX_OUTPUT_TOKENS", "1200"))
    max_source_chars: int = int(os.getenv("MAX_SOURCE_CHARS", "200000"))

    quiz_points_per_correct: int = int(os.getenv("QUIZ_POINTS_PER_CORRECT", "10"))
    focus_points_per_minute: int = int(os.getenv("FOCUS_POINTS_PER_MINUTE", "2"))
    focus_points_cap: int = int(os.getenv("FOCUS_POINTS_CAP", "100"))
    violation_penalty: int = int(os.getenv("VIOLATION_PENALTY", "5"))
    participation_points: int = int(os.getenv("PARTICIPATION_POINTS", "5"))


settings = Settings()
