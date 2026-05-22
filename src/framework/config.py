import os
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import ConfigDict, ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET: str
    DATABASE_URL: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ENVIRONMENT: str = "production"
    # Seed-user email the dev-only auto-login route logs in as. Read
    # by `src.domain.routes.dev_auth` when `ENVIRONMENT="development"`
    # — the route is not mounted in any other environment so this
    # value is inert in production. Defaults to the admin user
    # `seed.py` creates so a fresh `dev seed` + `dev up` lands the
    # developer (or the Playwright MCP agent) authenticated without
    # extra config.
    DEV_LOGIN_EMAIL: str = "admin@example.com"

    # Transactional email — see `src/framework/email/README.md` for the
    # backend dispatch rule. `console` is the safe default: no real
    # mail sent without an explicit env-var flip. `EMAIL_FROM` is read
    # by every backend (including `console`, which prints it). The
    # `APP_BASE_URL` is needed to build absolute links in emails
    # (verify, password reset) — relative paths don't work outside the
    # request scope.
    EMAIL_BACKEND: str = "console"
    EMAIL_FROM: str = "no-reply@bedlamconnect.com"
    APP_BASE_URL: str = "http://localhost:8000"
    RESEND_API_KEY: str | None = None

    # Error tracking. Empty string disables Sentry entirely — app starts
    # normally without it. Set in production via the `.env` file on the
    # droplet or as a CI/CD secret.
    SENTRY_DSN: str = ""

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
