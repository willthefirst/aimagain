# 🔧 Configuration directory

This directory contains environment and infrastructure configuration files.

## 📁 Current files

- `alembic.ini` - Database migration configuration for Alembic

## 🎯 What belongs here

Configuration files for:

- Database connections and migration settings
- Environment-specific configurations
- Infrastructure settings (when not in Docker)
- External service configurations

## 🚫 What doesn't belong here

- Application source code configuration (belongs in `pyproject.toml`)
- Docker-specific files (belong at root level)
- Scripts (belong in `scripts/` directory)
- Documentation (belongs at root level or in module READMEs)
