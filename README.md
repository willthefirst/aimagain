# Aimagain

A chat application with a clear separation between development tooling and application runtime.

## 🚀 Quick start

### For developers (cli only)

If you just want to use the `aim` CLI for development:

```bash
pip install -e .
```

This installs only the minimal dependencies needed for the CLI, not the full application stack.

### For full development environment

If you need to run tests or work with the full codebase:

```bash
pip install -e .[all]
```

### For application deployment

The application itself runs in Docker and installs only production dependencies:

```bash
# This happens automatically in Docker
pip install -e .[app]
```

## 📦 Dependency groups

| Group       | Purpose                          | Install Command          |
| ----------- | -------------------------------- | ------------------------ |
| **Default** | Minimal CLI dependencies only    | `pip install -e .`       |
| **`app`**   | Application runtime dependencies | `pip install -e .[app]`  |
| **`dev`**   | Development utilities            | `pip install -e .[dev]`  |
| **`test`**  | Testing framework                | `pip install -e .[test]` |
| **`lint`**  | Code quality tools               | `pip install -e .[lint]` |
| **`all`**   | All development dependencies     | `pip install -e .[all]`  |
| **`full`**  | Everything (app + dev)           | `pip install -e .[full]` |

## 🎯 Design philosophy

This project maintains a clear separation between:

- **Development tooling** (the `aim` CLI and related utilities)
- **Application runtime** (FastAPI, SQLAlchemy, etc.)

This allows developers to install just the CLI without pulling in the entire application stack, since the actual application runs in Docker containers.

## 🔧 Development workflow

1. **Install CLI**: `pip install -e .`
2. **Setup environment**: `aim setup`
3. **Start development**: `aim dev up`
4. **Run tests**: `aim test`

The Docker containers handle the application dependencies automatically.
