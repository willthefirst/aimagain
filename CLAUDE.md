# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential commands

**Development Server:**
```bash
uvicorn app.main:app --reload
```
Access at http://127.0.0.1:8000 (Swagger UI at /docs)

**Database Migrations:**
```bash
# Apply migrations
alembic upgrade head

# Create new migration after model changes
alembic revision --autogenerate -m "Description"
```

**Testing:**
```bash
# Run all tests
pytest

# Run specific test types
pytest -m api           # API tests only
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m consumer      # Contract tests (frontend)
pytest -m provider      # Contract tests (API verification)

# Run tests for specific modules
pytest tests/test_api/test_conversation_routes.py
```

**Code Quality:**
```bash
# Format code
black .
isort .

# Remove unused imports
autoflake --remove-all-unused-imports --recursive --in-place .
```

## Architecture overview

**Tech Stack:**
- FastAPI with Jinja2 templating
- SQLAlchemy ORM with SQLite database
- FastAPI-Users for authentication
- Server-Sent Events (SSE) for real-time updates
- HTMX for dynamic frontend interactions

**Core Models:**
- `User`: Auto-generated usernames (e.g., "witty-walrus"), tracks online status
- `Conversation`: Has unique slug, tracks last activity
- `Message`: Content linked to conversation and user
- `Participant`: Junction table with status (invited/joined/rejected/left)

**Key Features:**
- Conversation invitations with preview messages
- Real-time presence tracking via middleware
- Access control based on participant status
- Public conversation listings

## Project structure

**Core Application (`app/`):**
- `main.py`: FastAPI app with middleware and route registration
- `auth_config.py`: FastAPI-Users authentication setup
- `db.py`: SQLAlchemy session management
- `core/config.py`: Environment-based settings with .env support

**API Layer (`app/api/`):**
- `routes/`: RESTful endpoints organized by domain
- `common/`: Shared decorators, exceptions, and responses

**Business Logic (`app/logic/`):**
- Domain-specific processing functions
- Separated from API routes for testability

**Data Layer:**
- `models/`: SQLAlchemy ORM models with UUID primary keys
- `repositories/`: Data access layer with dependency injection
- `services/`: Business logic services
- `schemas/`: Pydantic models for request/response validation

**Middleware (`app/middleware/`):**
- `presence.py`: Tracks user online status automatically

## Development guidelines

**Always run pytest before committing changes** - the test suite ensures API contracts and business logic remain intact.

**Environment Setup:**
- Requires Python 3.11+
- Create `.env` file with required variables (SECRET, DATABASE_URL)
- Use `pip install .` for dependencies

**Testing Strategy:**
- Comprehensive API test coverage in `tests/test_api/`
- Contract tests for frontend/backend interaction in `tests/test_contract/`
- Pytest markers for selective test running
- Async test support with `pytest-asyncio`

**Authentication:**
- FastAPI-Users handles registration, login, password reset
- Current user context available via dependency injection
- Presence middleware automatically tracks user activity

**Database:**
- Alembic manages schema migrations
- UUID primary keys with readable prefixes (user_, conv_, msg_, part_)
- SQLite for local development, production-ready

**API Design:**
- RESTful endpoints following conversation-centric design
- JSON responses for API, HTML templates for pages
- Comprehensive error handling with appropriate HTTP status codes
