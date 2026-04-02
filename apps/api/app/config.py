from pathlib import Path
from pydantic_settings import BaseSettings

_env_file = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://coach:coach@localhost:5432/careercoach"
    redis_url: str = "redis://localhost:6379"
    tally_signing_secret: str = ""
    debug: bool = False

    model_config = {"env_file": str(_env_file), "extra": "ignore"}


settings = Settings()
