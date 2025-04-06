import os
from sqlalchemy import create_engine # Keep create_engine
# Import Session and sessionmaker for ORM
from sqlalchemy.orm import sessionmaker, Session
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

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency function to get an ORM Session per request
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Optional: Function to get a DB connection (can be useful later)
# def get_db_connection():
#     return engine.connect() 

# Note: Metadata is now defined in app.models as Base.metadata
# If needed elsewhere, import from app.models 