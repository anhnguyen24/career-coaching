from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    resend_api_key: str = ""
    from_email: str = "Career Coaching <results@yourdomain.com>"
    debug: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
