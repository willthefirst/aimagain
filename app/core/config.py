import os
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET: str
    DATABASE_URL: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ONLINE_TIMEOUT_MINUTES: int = (
        10  # Users are considered online if active within this many minutes
    )

    model_config = ConfigDict(env_file=".env")

    @classmethod
    def get_required_fields(cls) -> list[str]:
        """Get all required fields (those without default values)."""
        hints = get_type_hints(cls)
        return [
            field
            for field, _ in hints.items()
            if not hasattr(cls, field) or getattr(cls, field) is Any
        ]

    def __init__(self, **kwargs):
        env_file = Path(".env")
        if not env_file.exists():
            required_fields = self.get_required_fields()
            fields_str = "\n".join(f"- {field}" for field in required_fields)
            example_env = "\n".join(
                f"{field}=your_{field.lower()}_here" for field in required_fields
            )

            raise FileNotFoundError(
                f"\n\nError: .env file not found!"
                f"\nPlease create a .env file in the root directory with the following required variables:"
                f"\n{fields_str}"
                f"\n\nExample .env file:"
                f"\n{example_env}"
            )
        super().__init__(**kwargs)


settings = Settings()
