import os
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import ConfigDict, ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET: str
    DATABASE_URL: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ONLINE_TIMEOUT_MINUTES: int = (
        10  # Users are considered online if active within this many minutes
    )

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

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
        try:
            # Try to initialize normally - pydantic_settings will try .env file first, then environment variables
            super().__init__(**kwargs)
        except ValidationError as e:
            # If validation fails, provide helpful error message
            env_file = Path(".env")
            required_fields = self.get_required_fields()

            # Check which required fields are missing
            missing_fields = []
            for field in required_fields:
                if not os.getenv(field):
                    missing_fields.append(field)

            if missing_fields:
                fields_str = "\n".join(f"- {field}" for field in missing_fields)
                example_env = "\n".join(
                    f"{field}=your_{field.lower()}_here" for field in missing_fields
                )

                if not env_file.exists():
                    error_msg = (
                        f"\n\nError: Missing required environment variables!"
                        f"\nMissing variables: {fields_str}"
                        f"\n\nFor local development, create a .env file with:"
                        f"\n{example_env}"
                        f"\n\nFor production, set these as environment variables in Railway."
                    )
                else:
                    error_msg = (
                        f"\n\nError: Missing required environment variables!"
                        f"\nMissing variables: {fields_str}"
                        f"\n\nPlease add these to your .env file or set as environment variables."
                    )

                raise ValueError(error_msg) from e
            else:
                # Re-raise the original validation error if it's not about missing fields
                raise


settings = Settings()
