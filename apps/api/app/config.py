from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://coach:coach@localhost:5432/careercoach"
    redis_url: str = "redis://localhost:6379"
    tally_signing_secret: str = ""
    debug: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
