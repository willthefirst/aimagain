import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_migrations():
    """Run database migrations using alembic programmatically."""
    try:
        logger.info("Running database migrations...")

        # Ensure database directory exists for SQLite databases
        database_url = os.getenv("DATABASE_URL", "")
        if "sqlite" in database_url and not database_url.startswith(
            "sqlite:///:memory:"
        ):
            # Extract database path from URL
            if database_url.startswith("sqlite+aiosqlite://"):
                db_path = database_url.replace("sqlite+aiosqlite://", "")
            elif database_url.startswith("sqlite://"):
                db_path = database_url.replace("sqlite://", "")
            else:
                db_path = database_url

            # Create directory if it doesn't exist
            db_dir = Path(db_path).parent
            if not db_dir.exists():
                logger.info(f"Creating database directory: {db_dir}")
                db_dir.mkdir(parents=True, exist_ok=True)

        # Run alembic upgrade
        # First try to find alembic executable
        alembic_cmd = None
        try:
            # Try using alembic directly
            result = subprocess.run(
                ["alembic", "--version"],
                check=True,
                capture_output=True,
                text=True,
            )
            alembic_cmd = ["alembic"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fall back to python -m alembic
            alembic_cmd = [sys.executable, "-m", "alembic"]

        # Set working directory to project root where alembic.ini is located
        project_root = Path(__file__).parent.parent.parent

        result = subprocess.run(
            alembic_cmd + ["upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        logger.info("Migrations completed successfully")
        if result.stdout:
            logger.info(f"Alembic output: {result.stdout}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed with exit code {e.returncode}")
        if e.stdout:
            logger.error(f"Stdout: {e.stdout}")
        if e.stderr:
            logger.error(f"Stderr: {e.stderr}")
        raise RuntimeError("Database migration failed") from e
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}")
        raise RuntimeError("Database migration failed") from e
