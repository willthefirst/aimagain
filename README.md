# Aimagain

A **modern chat application** built with FastAPI and server-side rendering, featuring real-time conversations, user presence tracking, and a clean architectural separation between development tooling and application runtime.

## 🎯 Project overview

Aimagain demonstrates **modern web application architecture** with:

- **Server-side rendering** with HTMX for progressive enhancement
- **Clean architecture** with clear separation of concerns (API, Services, Repositories)
- **Real-time features** including user presence and conversation updates
- **Comprehensive testing** with unit, integration, and contract testing
- **Production-ready deployment** with Docker and CI/CD automation

### ✨ Key features

- **User authentication** with secure session management
- **Real-time conversations** between multiple participants
- **User presence tracking** showing who's online
- **Progressive enhancement** - works without JavaScript, enhanced with HTMX
- **Responsive design** that works on desktop and mobile
- **Invite system** for controlled conversation participation

### 🏗️ technical architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Templates     │    │   API Routes    │    │   Services      │
│                 │    │                 │    │                 │
│ • Jinja2 HTML   │◄───┤ • FastAPI       │◄───┤ • Business      │
│ • HTMX forms    │    │ • Route logic   │    │   logic         │
│ • Progressive   │    │ • Auth handling │    │ • Data          │
│   enhancement   │    │                 │    │   coordination  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Middleware    │    │   Logic Layer   │    │  Repositories   │
│                 │    │                 │    │                 │
│ • User presence │    │ • Processing    │    │ • Data access   │
│ • Request       │    │ • Coordination  │    │ • Database      │
│   tracking      │    │ • Error         │    │   operations    │
│                 │    │   handling      │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
                                            ┌─────────────────┐
                                            │    Database     │
                                            │                 │
                                            │ • PostgreSQL    │
                                            │ • SQLAlchemy    │
                                            │ • Alembic       │
                                            │   migrations    │
                                            └─────────────────┘
```

## 🔧 Development workflow

1. **Install CLI**: `pip install -e .`
2. **Setup environment**: `aim setup`
3. **Start development**: `aim dev up`
4. **Run tests**: `aim test`

### 📋 Quick commands

```bash
# Development
aim dev up              # Start development server with hot reload
aim dev down            # Stop development environment
aim dev logs            # View development logs

# Testing
aim test                # Run all tests
aim test unit           # Run unit tests only
aim test integration    # Run integration tests only
aim test contract       # Run contract tests only

# Database
aim db migrate          # Run database migrations
aim db reset            # Reset database to clean state
aim db seed             # Add sample data for development

# Production
aim deploy              # Deploy to production
aim status              # Check deployment status
```

## 📚 Documentation architecture

This project follows **LLM-optimized documentation** standards with comprehensive READMEs at every level:

### 🎯 Core architecture documentation

- **[src/README.md](src/README.md)** - Application architecture overview
- **[src/api/README.md](src/api/README.md)** - API layer design and patterns
- **[src/services/README.md](src/services/README.md)** - Business logic organization
- **[src/models/README.md](src/models/README.md)** - Data model design principles
- **[src/repositories/README.md](src/repositories/README.md)** - Data access patterns

### 🔧 Specialized documentation

- **[src/api/routes/README.md](src/api/routes/README.md)** - Route organization and patterns
- **[src/api/common/README.md](src/api/common/README.md)** - Shared API utilities
- **[src/schemas/README.md](src/schemas/README.md)** - Request/response schemas
- **[src/middleware/README.md](src/middleware/README.md)** - Middleware patterns
- **[src/logic/README.md](src/logic/README.md)** - Processing logic organization
- **[src/templates/README.md](src/templates/README.md)** - Template structure and patterns

### 📖 Supporting documentation

- **[tests/README.md](tests/README.md)** - Testing strategy and organization
- **[tests/test_contract/README.md](tests/test_contract/README.md)** - Contract testing approach
- **[notes/README.md](notes/README.md)** - Development notes and planning
- **[src/core/README.md](src/core/README.md)** - Core configuration and utilities
- **[alembic/README.md](alembic/README.md)** - Database migration processes
- **[deployment/README.md](deployment/README.md)** - Deployment procedures

## 🚀 Getting started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for development tools)
- **PostgreSQL 14+** (or SQLite for development)
- **Docker** (for containerized deployment)

### Local development setup

1. **Clone the repository**:

```bash
git clone https://github.com/your-org/aimagain.git
cd aimagain
```

2. **Install the development CLI**:

```bash
pip install -e .
```

3. **Setup your environment**:

```bash
aim setup
# This creates .env file and sets up local database
```

4. **Start development server**:

```bash
aim dev up
# Starts server with hot reload at http://localhost:8000
```

5. **Run the test suite**:

```bash
aim test
# Ensures everything is working correctly
```

### Production deployment

1. **Prepare for deployment**:

```bash
aim deploy prepare
# Validates configuration and builds production assets
```

2. **Deploy to production**:

```bash
aim deploy
# Deploys using configured deployment method
```

For detailed deployment instructions, see [deployment/README.md](deployment/README.md).

## 🧪 Testing strategy

Aimagain uses a **comprehensive testing approach** with multiple layers:

### Test types

- **Unit tests** (`tests/test_api/`) - Test individual components in isolation
- **Integration tests** (`tests/test_api/`) - Test component interactions
- **Contract tests** (`tests/test_contract/`) - Test API contracts and UI interactions

### Running tests

```bash
# All tests
aim test

# Specific test categories
aim test unit
aim test integration
aim test contract

# Specific test files
aim test tests/test_api/test_conversations.py
aim test tests/test_contract/tests/consumer/test_conversation_form.py

# With coverage
aim test --coverage
```

For detailed testing documentation, see [tests/README.md](tests/README.md).

## 🔒 Security considerations

- **Authentication** using FastAPI-Users with secure session management
- **CSRF protection** built into form handling
- **SQL injection prevention** through SQLAlchemy ORM
- **Input validation** using Pydantic schemas
- **Environment-based configuration** for secrets management

## 🏗️ architecture decisions

### Why server-side rendering?

- **SEO friendly** - Content is rendered on the server
- **Fast initial load** - No client-side rendering wait time
- **Progressive enhancement** - Works without JavaScript
- **Reduced complexity** - Less client-side state management

### Why htmx?

- **Minimal JavaScript** while maintaining interactivity
- **Server-side control** of UI updates and validation
- **Progressive enhancement** - degrades gracefully
- **Simple mental model** - HTML attributes drive behavior

### Why FastAPI?

- **Modern Python** with async/await support
- **Automatic API documentation** with OpenAPI/Swagger
- **Type safety** with Pydantic integration
- **High performance** comparable to Node.js and Go

### Why this architecture?

- **Clear separation of concerns** makes the codebase maintainable
- **Testable components** enable confident refactoring
- **Documentation-driven** approach aids onboarding and maintenance
- **Production-ready** with proper error handling and monitoring

## 🔄 Development workflow details

### Code organization principles

1. **Dependency direction**: Dependencies flow inward (API → Services → Repositories → Database)
2. **Single responsibility**: Each module has a clear, focused purpose
3. **Interface segregation**: Small, focused interfaces between layers
4. **Dependency injection**: Services receive dependencies rather than creating them

### Development practices

- **Test-driven development** for core business logic
- **Documentation-first** for new features and modules
- **Code review** for all changes with testing requirements
- **Continuous integration** with automated testing and deployment

### Adding new features

1. **Plan** in `notes/` directory with architectural decisions
2. **Models** - Add data models if needed (`src/models/`)
3. **Repositories** - Add data access patterns (`src/repositories/`)
4. **Services** - Implement business logic (`src/services/`)
5. **Schemas** - Define API contracts (`src/schemas/`)
6. **Routes** - Add HTTP endpoints (`src/api/routes/`)
7. **Templates** - Create user interface (`src/templates/`)
8. **Tests** - Add comprehensive test coverage
9. **Documentation** - Update relevant READMEs

For detailed patterns and examples, see the module-specific documentation.

## 🤝 Contributing

1. **Read the documentation** - Start with this README and relevant module docs
2. **Follow the architecture** - Respect the established patterns and boundaries
3. **Write tests** - All changes should include appropriate test coverage
4. **Update documentation** - Keep READMEs current with your changes
5. **Use the CLI tools** - Leverage `aim` commands for development workflow

### Code style

- **Type hints** - Use Python type hints throughout
- **Docstrings** - Document all public functions and classes
- **Error handling** - Provide clear error messages and proper exception handling
- **Logging** - Use structured logging for debugging and monitoring

## 📊 Project status

- **Current version**: Development
- **Python version**: 3.11+
- **Framework**: FastAPI 0.104+
- **Database**: PostgreSQL 14+ (SQLite for development)
- **Testing**: pytest with comprehensive coverage
- **Deployment**: Docker with Railway/DigitalOcean support

## 📞 Support

- **Documentation**: Start with module-specific READMEs
- **Issues**: Use GitHub issues for bug reports and feature requests
- **Discussions**: Use GitHub discussions for questions and ideas
- **Development**: See [notes/README.md](notes/README.md) for development planning

---

**Next steps**: Start with [src/README.md](src/README.md) for application architecture overview, then explore the specific modules you need to work with.
