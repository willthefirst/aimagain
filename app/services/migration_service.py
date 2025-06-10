import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


async def run_migrations():
    """Run database migrations using alembic programmatically."""
    try:
        logger.info("Running database migrations...")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
        )
        logger.info("Migrations completed successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed: {e}")
        raise RuntimeError("Database migration failed") from e
