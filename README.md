# Bedlam CONNECT

A **FastAPI skeleton/boilerplate** with server-side rendering, providing a clean architectural foundation for building web applications with user authentication, layered architecture, and modern development tooling.

## Project overview

Bedlam Connect provides a **production-ready project skeleton** with:

- **Server-side rendering** with HTMX for progressive enhancement
- **Clean architecture** with clear separation of concerns (Routes, Logic, Services, Repositories)
- **User authentication** using FastAPI-Users with JWT cookie-based sessions
- **Production-ready deployment** with Docker and CI/CD automation

### Key features

- **User authentication** with JWT cookie-based session management
- **User profiles** with username support
- **Progressive enhancement** — works without JavaScript, enhanced with HTMX
- **Responsive design** that works on desktop and mobile

## Quick start

```bash
git clone https://github.com/your-org/bedlam-connect.git
cd bedlam-connect
pip install -e .          # installs the project + the `dev` CLI
dev setup                 # creates .env and the local database
dev up                    # starts the dev server at http://localhost:8000
dev test                  # runs the test suite
```

For the full list of `dev` commands and their flags, see [`scripts/README.md`](scripts/README.md).

## Documentation

This project follows a **single-source-of-truth** documentation convention: each fact lives in the README closest to the code it describes, and other docs link to it rather than restating it. See [`CLAUDE.md`](CLAUDE.md) for the contract.

### Where to start

- **[`CLAUDE.md`](CLAUDE.md)** — the agent/contributor contract: definition of done, doc/test/code coupling, where to look for what
- **[`src/README.md`](src/README.md)** — application architecture and layer responsibilities
- **[`scripts/README.md`](scripts/README.md)** — the `dev` CLI command reference
- **[`tests/README.md`](tests/README.md)** — testing conventions and shared fixtures

### Module-level documentation

Every `src/<module>/` has its own README describing what it does, what it doesn't do, and its tests:

- [`src/api/README.md`](src/api/README.md) — API layer
  - [`src/api/routes/README.md`](src/api/routes/README.md) — route organization
  - [`src/api/common/README.md`](src/api/common/README.md) — shared API utilities
- [`src/services/README.md`](src/services/README.md) — business logic
- [`src/repositories/README.md`](src/repositories/README.md) — data access
- [`src/models/README.md`](src/models/README.md) — SQLAlchemy models
- [`src/schemas/README.md`](src/schemas/README.md) — Pydantic request/response
- [`src/logic/README.md`](src/logic/README.md) — processing functions
- [`src/middleware/README.md`](src/middleware/README.md) — middleware
- [`src/core/README.md`](src/core/README.md) — config + templating
- [`src/templates/README.md`](src/templates/README.md) — Jinja2 + HTMX templates

### Supporting documentation

- [`alembic/README.md`](alembic/README.md) — database migrations
- [`deployment/README.md`](deployment/README.md) — deployment procedures, including [bootstrapping the first admin user](deployment/README.md#bootstrapping-an-admin)
- [`notes/README.md`](notes/README.md) — development notes and planning

## Prerequisites

- **Python 3.11+**
- **Docker** (for the Docker Compose dev environment and production builds)

The project uses SQLite for local development and Postgres in production; you don't need Postgres installed locally.

## Architecture decisions

### Why server-side rendering?

- **SEO friendly** — content is rendered on the server
- **Fast initial load** — no client-side rendering wait time
- **Progressive enhancement** — works without JavaScript
- **Reduced complexity** — less client-side state management

### Why htmx?

- **Minimal JavaScript** while maintaining interactivity
- **Server-side control** of UI updates and validation
- **Simple mental model** — HTML attributes drive behavior

### Why FastAPI?

- **Modern Python** with async/await support
- **Automatic API documentation** with OpenAPI/Swagger
- **Type safety** with Pydantic integration
- **High performance** comparable to Node.js and Go

### Why a layered architecture?

- **Clear separation of concerns** makes the codebase maintainable
- **Testable components** enable confident refactoring
- **Documentation-driven** approach aids onboarding and maintenance

For the layer responsibilities and dependency rules, see [`src/README.md`](src/README.md).

## Security considerations

- **Authentication** via FastAPI-Users with JWT cookie-based sessions
- **CSRF protection** built into form handling
- **SQL injection prevention** through SQLAlchemy ORM
- **Input validation** through Pydantic schemas
- **Environment-based configuration** for secrets

## Contributing

1. Read [`CLAUDE.md`](CLAUDE.md) — it documents the doc/test/code coupling contract that every change must satisfy.
2. Follow the established architecture (see [`src/README.md`](src/README.md)).
3. Use `dev lint` and `dev test` before committing; pre-commit runs the same checks.

## Project status

- **Current version**: Development (skeleton)
- **Python version**: 3.11+
- **Framework**: FastAPI
- **Database**: PostgreSQL in production, SQLite for development
- **Deployment**: Docker, with DigitalOcean blue-green deployment

## Support

- **Issues**: GitHub issues for bug reports and feature requests
- **Discussions**: GitHub discussions for questions and ideas
- **Development planning**: [`notes/README.md`](notes/README.md)
