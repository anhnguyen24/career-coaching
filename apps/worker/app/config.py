from pathlib import Path
from pydantic_settings import BaseSettings

_env_file = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://coach:coach@localhost:5432/careercoach"
    redis_url: str = "redis://localhost:6379"
    anthropic_api_key: str = ""
    resend_api_key: str = ""
    from_email: str = "Career Coaching <onboarding@resend.dev>"
    debug: bool = False
    mock_ai: bool = False

    model_config = {"env_file": str(_env_file), "extra": "ignore"}


settings = Settings()
