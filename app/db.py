import os
from sqlalchemy import create_engine, MetaData
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use environment variable or default to a file named chat_app.db
# Example: DATABASE_URL="sqlite:///./chat_app.db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chat_app.db")

# The connect_args is specific to SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} # Needed only for SQLite
)

# SQLAlchemy MetaData object. Tables will be associated with this.
metadata = MetaData()

# Dependency function to get a DB connection per request
def get_db():
    connection = None
    try:
        connection = engine.connect()
        yield connection
    finally:
        if connection is not None:
            connection.close()

# Optional: Function to get a DB connection (can be useful later)
# def get_db_connection():
#     return engine.connect() 