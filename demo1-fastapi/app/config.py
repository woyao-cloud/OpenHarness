from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://root:root@localhost:5432/user_admin"
    jwt_secret: str = "your-256-bit-secret-key-for-jwt-signing-must-be-at-least-32-characters"
    jwt_expiration: int = 86400  # seconds
    jwt_refresh_expiration: int = 604800  # seconds

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()