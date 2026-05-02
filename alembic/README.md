# Alembic: Database migration management

The `alembic/` directory contains **database migration scripts** and configuration for managing schema changes in the Bedlam Connect application, providing version control for the database schema through incremental migration files.

## 🎯 Core philosophy: Version-controlled database evolution

Alembic provides **database schema version control**, ensuring all environments (development, testing, production) can be synchronized to the same database state through reproducible, incremental migrations.

### What we do ✅

- **Schema versioning**: Track database schema changes through numbered migration files
- **Incremental updates**: Apply changes progressively from any version to any other version
- **Environment synchronization**: Ensure all deployments have consistent database schema
- **Rollback capability**: Revert database changes when needed
- **Model synchronization**: Generate migrations automatically from SQLAlchemy model changes

**Example**: Generating and applying a migration. Day-to-day, use the [`dev migrate`](../scripts/README.md#available-commands) wrappers — they handle the `DATABASE_URL` and config-path boilerplate for you:

```bash
# Generate new migration from model changes
dev migrate generate "add user email_verified column"

# Apply migrations to the host DB
dev migrate up

# Roll back the last migration
dev migrate down

# Sanity-check upgrade ↔ downgrade against a throwaway sqlite DB
dev migrate roundtrip
```

Raw `alembic` is still available for introspection commands that don't have a `dev migrate` wrapper (e.g. `alembic -c config/alembic.ini current`, `alembic ... history`).

### What we don't do ❌

- **Data manipulation**: Migrations handle schema changes, not data processing
- **Application logic**: Business logic belongs in application code, not migrations
- **Environment-specific changes**: Migrations should work across all environments
- **Non-reversible operations**: Always ensure migrations can be rolled back

**Example**: Don't put application logic in migrations:

```python
# ❌ Wrong - application logic in migration
def upgrade():
    # Don't process business data in migrations
    connection = op.get_bind()
    users = connection.execute("SELECT * FROM users").fetchall()
    for user in users:
        # Complex business logic processing
        processed_data = calculate_user_score(user)
        connection.execute(f"UPDATE users SET score = {processed_data} WHERE id = {user.id}")

# ✅ Correct - schema changes only in migrations
def upgrade():
    # Add new column for calculated scores
    op.add_column('users', sa.Column('score', sa.Integer(), nullable=True))

    # Note: Use data migration script separately for populating scores
```

## 🏗️ Architecture: Database schema version control system

**Models → Alembic Detection → Migration Generation → Database Application**

Alembic bridges SQLAlchemy models and database schema through versioned migrations.

## 📋 Migration responsibility matrix

| Component          | Purpose                             | Key Files                              |
| ------------------ | ----------------------------------- | -------------------------------------- |
| **env.py**         | Migration environment configuration | Database connection, model imports     |
| **script.py.mako** | Migration template                  | Template for generating new migrations |
| **versions/**      | Migration history                   | Numbered migration files               |
| **alembic.ini**    | Configuration file                  | Database URL, logging, file paths      |

## 📁 Directory structure

```
alembic/
├── env.py                    # Migration environment setup and configuration
├── script.py.mako           # Template for generating new migration files
├── versions/                # Directory containing all migration files
│   ├── 615021cc5b23_first_migration.py          # Initial schema (users table)
│   └── b2dbe3136387_drop_chat_tables_and_columns.py  # Remove chat features
└── ../config/alembic.ini    # Alembic configuration (in config/ directory)
```

## 🔧 Implementation patterns

### Environment configuration pattern

The `env.py` file configures alembic for the application:

```python
import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure application modules can be imported
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

# Import model metadata for autogeneration
from src.models import metadata

# Configure database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    # Convert async URLs to sync for alembic compatibility
    if "sqlite+aiosqlite://" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

if DATABASE_URL is None and not config.get_main_option("sqlalchemy.url"):
    raise RuntimeError(
        "DATABASE_URL is not set. For local development, run `dev setup` "
        "to create a .env file, or export DATABASE_URL directly."
    )

target_metadata = metadata
```

### Migration generation workflow

1. **Make model changes** in `/src/models/`
2. **Generate migration** with a descriptive message via [`dev migrate generate`](../scripts/README.md#available-commands):

```bash
dev migrate generate "add user profile fields"
```

   Always review the generated file before applying — alembic's autogenerate isn't perfect at detection.

3. **Review and edit** the generated migration:

```python
"""add user profile fields

Revision ID: abc123def456
Revises: b2dbe3136387
Create Date: 2024-01-15 10:30:00.123456

"""
from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = 'abc123def456'
down_revision = 'b2dbe3136387'
branch_labels = None
depends_on = None

def upgrade():
    # Add profile fields to users table
    op.add_column('users', sa.Column('bio', sa.Text(), nullable=True))

def downgrade():
    # Remove profile fields
    op.drop_column('users', 'bio')
```

4. **Apply migration** to the host DB via [`dev migrate up`](../scripts/README.md#available-commands):

```bash
dev migrate up
```

### Migration file structure pattern

All migration files follow this structure:

```python
"""Brief description of changes

Revision ID: [auto-generated unique ID]
Revises: [previous migration ID]
Create Date: [timestamp]
"""
from alembic import op
import sqlalchemy as sa

# Migration metadata
revision = '[unique_id]'
down_revision = '[parent_migration_id]'
branch_labels = None
depends_on = None

def upgrade():
    """Apply the migration changes."""
    # Schema changes to apply
    op.create_table(
        'new_table',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    """Reverse the migration changes."""
    # Undo the schema changes
    op.drop_table('new_table')
```

### Database URL handling pattern

Handle different database URLs across environments:

```python
def get_database_url():
    """Get database URL with environment-specific handling."""
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")

    # Convert async SQLite URLs for alembic compatibility
    if "sqlite+aiosqlite://" in DATABASE_URL:
        return DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")

    # Convert async PostgreSQL URLs if needed
    if "postgresql+asyncpg://" in DATABASE_URL:
        return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    return DATABASE_URL
```

## 🚨 Common migration issues and solutions

### Issue: Autogeneration missing changes

**Problem**: Alembic doesn't detect all model changes automatically
**Solution**: Review and manually edit generated migrations

```python
# ✅ Always review generated migrations
def upgrade():
    # Autogenerated: Add column
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=True))

    # Manually added: Set default value for existing rows
    op.execute("UPDATE users SET email_verified = false WHERE email_verified IS NULL")

    # Manually added: Make column non-nullable after setting defaults
    op.alter_column('users', 'email_verified', nullable=False)
```

### Issue: Migration dependencies and conflicts

**Problem**: Multiple developers creating migrations simultaneously
**Solution**: Use proper branching and merging strategies

```bash
# If migration conflicts occur, create merge migration
alembic revision --message="merge migrations" --head=abc123@def456

# Or rebase your migrations on latest main branch
# 1. reset your migration
# 2. pull latest main
# 3. regenerate migration
```

### Issue: rollback safety

**Problem**: Some operations can't be safely rolled back
**Solution**: Design migrations with rollback in mind

```python
def upgrade():
    # ✅ Safe: Adding nullable column
    op.add_column('users', sa.Column('new_field', sa.String(255), nullable=True))

def downgrade():
    # ✅ Safe: Can remove column
    op.drop_column('users', 'new_field')

# ❌ Unsafe: Dropping column with data
def upgrade():
    op.drop_column('users', 'important_data')  # Data loss!

def downgrade():
    op.add_column('users', sa.Column('important_data', sa.String(255)))  # Data gone!

# ✅ Safe approach: Two-step migration
# Migration 1: Add new column, migrate data
# Migration 2: Remove old column after confirming data migration
```

### Issue: environment synchronization

**Problem**: Different environments have different migration states
**Solution**: Use consistent migration workflow

```bash
# Check current migration status
alembic current

# See migration history
alembic history

# Upgrade to specific migration
alembic upgrade abc123def456

# Stamp database with specific migration (for initialization)
alembic stamp head
```

## 🔧 Development workflow

### Local development workflow

1. **Make model changes** in your development environment
2. **Generate migration** with a descriptive name (see [`scripts/README.md`](../scripts/README.md#available-commands) for the full `dev migrate` reference):

```bash
dev migrate generate "add user profile fields"
```

3. **Review generated file** in `alembic/versions/`
4. **Test migration** locally — `dev migrate roundtrip` does the upgrade/downgrade/upgrade cycle in one step against a throwaway sqlite DB:

```bash
dev migrate roundtrip
```

   Or step through manually:

```bash
dev migrate up      # apply
dev migrate down    # roll back one revision
dev migrate up      # reapply to confirm
```

5. **Commit migration file** with your code changes

### Production deployment workflow

1. **Backup database** before migration
2. **Apply migrations** during deployment:

```bash
# In deployment script
alembic upgrade head
```

3. **Verify application** works with new schema
4. **Monitor** for any issues

### Testing migration workflow

```python
# Test migrations in your test suite
import pytest
from alembic import command
from alembic.config import Config

def test_migrations_apply_cleanly():
    """Test that migrations can be applied and rolled back."""
    alembic_cfg = Config("alembic.ini")

    # Apply all migrations
    command.upgrade(alembic_cfg, "head")

    # Rollback one migration
    command.downgrade(alembic_cfg, "-1")

    # Reapply
    command.upgrade(alembic_cfg, "head")
```

## 📊 Migration best practices

### Migration naming conventions

Use descriptive migration messages:

```bash
# Good migration names
dev migrate generate "add user email verification fields"
dev migrate generate "add index on users username"
dev migrate generate "add user profile bio column"

# ❌ Poor migration names
dev migrate generate "changes"
dev migrate generate "fix"
dev migrate generate "update"
```

### Data migration strategy

For complex data transformations, use separate scripts:

```python
# In migration file - schema only
def upgrade():
    op.add_column('users', sa.Column('full_name', sa.String(255)))

# Separate data migration script (run after schema migration)
def migrate_user_names():
    """Populate full_name from first_name and last_name."""
    from src.db import get_db_session

    async with get_db_session() as session:
        users = await session.execute("SELECT id, first_name, last_name FROM users")
        for user in users:
            full_name = f"{user.first_name} {user.last_name}".strip()
            await session.execute(
                "UPDATE users SET full_name = :name WHERE id = :id",
                {"name": full_name, "id": user.id}
            )
```

## 📚 Related documentation

- [../src/models/README.md](../src/models/README.md) - Data models that generate migrations
- [../src/db.py](../src/db.py) - Database configuration used by migrations
- [../config/alembic.ini](../config/alembic.ini) - Alembic configuration file
- [../deployment/README.md](../deployment/README.md) - Deployment procedures including migrations
