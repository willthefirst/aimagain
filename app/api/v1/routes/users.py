from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
# Import Session for type hinting
from sqlalchemy.orm import Session
# Removed unused Connection, select

# Import templates from the new core location
from app.core.templating import templates
# Import DB dependency function and User model
from app.db import get_db
from app.models import User

router = APIRouter()

# Specify HTMLResponse as the default response class for this endpoint
@router.get("/users", response_class=HTMLResponse, tags=["users"])
def list_users(request: Request, db: Session = Depends(get_db)): # Depend on Session
    """Provides an HTML page listing all registered users."""

    # Use the injected ORM session to query User objects
    users = db.query(User).all() # Simple ORM query

    return templates.TemplateResponse(
        name="users/list.html",
        context={"request": request, "users": users} # Pass fetched ORM user objects
    )