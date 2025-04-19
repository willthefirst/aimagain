from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    SECRET: str
    DATABASE_URL: str  # Add database URL setting
    ALGORITHM: str = "HS256"  # Default algorithm for JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour

    model_config = ConfigDict(env_file=".env")


settings = Settings()
