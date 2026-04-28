# Core: Application configuration and foundation utilities

The `core/` directory contains **fundamental configuration** and utility modules that provide the foundation for the entire application, including environment-based settings, template configuration, and shared utilities used across all layers.

## Core philosophy: Centralized configuration with environment awareness

Core modules provide **single source of truth** for application configuration, ensuring consistent behavior across development, testing, and production environments while providing developer-friendly error messages and validation.

### What we do

- **Environment configuration**: Centralized settings management with validation
- **Template system setup**: Global template configuration and context
- **Foundation utilities**: Shared utilities used across the application
- **Development tools**: Environment-aware features like auto-reload and live reload
- **Configuration validation**: Clear error messages for missing or invalid config

**Example**: Environment-aware configuration with helpful error messages:

```python
class Settings(BaseSettings):
    SECRET: str
    DATABASE_URL: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    def __init__(self, **kwargs):
        try:
            super().__init__(**kwargs)
        except ValidationError as e:
            missing_fields = self._get_missing_required_fields()
            if missing_fields:
                self._raise_helpful_error(missing_fields)
            raise
```

### What we don't do

- **Business logic**: Business rules belong in services, not configuration
- **Data models**: Data structures belong in models, not core utilities
- **Route definitions**: HTTP routing stays in API layer
- **Database operations**: Data access belongs in repositories

**Example**: Don't put business logic in configuration:

```python
# Bad - business logic in core config
class Settings(BaseSettings):
    MAX_ITEMS_PER_USER: int = 10

    def can_user_create_item(self, user):
        return user.item_count < self.MAX_ITEMS_PER_USER

# Good - configuration values only in core
class Settings(BaseSettings):
    MAX_ITEMS_PER_USER: int = 10

# Business logic belongs in services:
class [Entity]Service:
    def can_create_item(self, user: User) -> bool:
        return user.item_count < settings.MAX_ITEMS_PER_USER
```

## Architecture: Foundation layer for entire application

**Core -> Services -> API Routes -> HTTP Responses**

Core modules are imported and used throughout the application stack.

## Core module responsibility matrix

| Module            | Purpose                             | Key Functionality                                 |
| ----------------- | ----------------------------------- | ------------------------------------------------- |
| **config.py**     | Application settings and validation | Environment variables, validation, error handling |
| **templating.py** | Template system configuration       | Jinja2 setup, global context, auto-reload         |

## Directory structure

```
core/
├── config.py       # Application settings with environment validation
├── templating.py   # Template system configuration and global context
└── __init__.py     # Package exports
```

## Implementation patterns

### Environment-based configuration pattern

All configuration uses environment variables with sensible defaults:

```python
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    # Required settings (no default values)
    SECRET: str
    DATABASE_URL: str

    # Optional settings with defaults
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ENVIRONMENT: str = "development"

    # Pydantic configuration
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

# Singleton instance used throughout application
settings = Settings()
```

### Configuration validation with helpful errors

Provide clear error messages for configuration issues:

```python
class Settings(BaseSettings):
    @classmethod
    def get_required_fields(cls) -> list[str]:
        """Get all required fields (those without default values)."""
        hints = get_type_hints(cls)
        return [
            field for field, _ in hints.items()
            if not hasattr(cls, field) or getattr(cls, field) is Any
        ]

    def __init__(self, **kwargs):
        try:
            super().__init__(**kwargs)
        except ValidationError as e:
            missing_fields = self._check_missing_fields()
            if missing_fields:
                self._provide_helpful_guidance(missing_fields)
            raise

    def _provide_helpful_guidance(self, missing_fields: list[str]):
        """Provide environment-specific setup guidance."""
        env_file = Path(".env")

        if not env_file.exists():
            example_env = "\n".join(
                f"{field}=your_{field.lower()}_here"
                for field in missing_fields
            )
            error_msg = (
                f"Missing required environment variables: {missing_fields}\n"
                f"For local development, create a .env file with:\n{example_env}"
            )
        else:
            error_msg = (
                f"Missing required environment variables: {missing_fields}\n"
                f"Please add these to your .env file or environment."
            )

        raise ValueError(error_msg)
```

### Template system configuration pattern

Set up templates with environment-aware features:

```python
import os
from fastapi.templating import Jinja2Templates

# Environment-aware configuration
auto_reload = os.getenv("ENVIRONMENT", "development") == "development"

# Configure template system
templates = Jinja2Templates(
    directory="src/templates",
    auto_reload=auto_reload
)

def get_template_context() -> dict:
    """Get global template context with environment information."""
    return {
        "is_development": os.getenv("ENVIRONMENT") == "development",
        "livereload_port": os.getenv("LIVERELOAD_PORT", "35729"),
    }

# Usage in routes:
@router.get("/some-page")
async def render_page(request: Request):
    context = {
        "request": request,
        **get_template_context(),  # Add global context
        "page_data": {...}         # Add page-specific data
    }
    return templates.TemplateResponse("page.html", context)
```

### Configuration access pattern

Import and use configuration consistently across the application:

```python
# In any module that needs configuration
from src.core.config import settings

# Use configuration values
async def some_service_function():
    token_expiry = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # ... use token_expiry

# For testing, override settings
def test_with_custom_config():
    with patch('src.core.config.settings') as mock_settings:
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 5
        # Test with custom timeout value
```

### Development vs production configuration

Handle environment differences gracefully:

```python
# Development-specific features
if settings.ENVIRONMENT == "development":
    # Enable auto-reload for templates
    templates.env.auto_reload = True

    # Add debug information to template context
    def get_debug_context():
        return {
            "debug_mode": True,
            "template_auto_reload": True,
        }
else:
    # Production optimizations
    templates.env.auto_reload = False

    def get_debug_context():
        return {}

# Environment-aware template context
def get_template_context():
    base_context = {
        "is_development": settings.ENVIRONMENT == "development",
    }

    if settings.ENVIRONMENT == "development":
        base_context.update(get_debug_context())

    return base_context
```

## Common configuration issues and solutions

### Issue: Configuration scattered across modules

**Problem**: Settings defined in multiple places, making it hard to track
**Solution**: Centralize all configuration in core/config.py

```python
# Bad - settings scattered across modules
# In services/some_service.py
MAX_ITEMS = 10

# In api/routes/auth.py
TOKEN_EXPIRE_MINUTES = 60

# Good - centralized configuration
# In core/config.py
class Settings(BaseSettings):
    MAX_ITEMS_PER_USER: int = 10
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

# Use throughout application
from src.core.config import settings
```

### Issue: Missing environment validation

**Problem**: Application fails at runtime with cryptic errors
**Solution**: Validate configuration at startup with helpful messages

```python
# Bad - no validation, fails at runtime
DATABASE_URL = os.getenv("DATABASE_URL")  # Could be None
engine = create_engine(DATABASE_URL)     # Fails with cryptic error

# Good - validation with helpful error
class Settings(BaseSettings):
    DATABASE_URL: str  # Required, will validate at startup

    def __init__(self):
        try:
            super().__init__()
        except ValidationError:
            raise ValueError(
                "Missing DATABASE_URL environment variable. "
                "Please set it in your .env file or environment."
            )
```

### Issue: Template configuration inconsistency

**Problem**: Template features work differently in development vs production
**Solution**: Environment-aware template configuration

```python
# Bad - inconsistent template behavior
templates = Jinja2Templates(directory="src/templates", auto_reload=True)  # Always auto-reload

# Good - environment-aware template setup
auto_reload = settings.ENVIRONMENT == "development"
templates = Jinja2Templates(
    directory="src/templates",
    auto_reload=auto_reload
)
```

## Usage patterns across the application

### In services

```python
from src.core.config import settings

class UserService:
    def get_token_expiry(self) -> timedelta:
        return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
```

### In routes

```python
from src.core.config import settings
from src.core.templating import templates, get_template_context

@router.get("/login")
async def login_page(request: Request):
    context = {
        "request": request,
        **get_template_context(),
    }
    return templates.TemplateResponse("auth/login.html", context)
```

### In tests

```python
import pytest
from unittest.mock import patch
from src.core.config import settings

def test_with_custom_config():
    with patch.object(settings, 'ACCESS_TOKEN_EXPIRE_MINUTES', 5):
        # Test with custom timeout value
        assert service.get_token_expiry() == timedelta(minutes=5)
```

## Tests

**TODO** — no colocated tests yet. When changing config loading or templating utilities, add `src/core/test_<file>.py`. Config tests should cover env var precedence and validation error messages; templating tests should cover URL building and any Jinja globals/filters.

## Related documentation

- [Main Architecture](../README.md) - Application architecture that uses these core modules
- [Services Layer](../services/README.md) - Services that consume configuration
- [Templates Layer](../templates/README.md) - Template system configured by core/templating.py
