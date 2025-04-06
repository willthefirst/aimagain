from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select # Add select import

# Import templates from the new core location
from app.core.templating import templates
# Import DB engine and User model
from app.db import engine
from app.models import User

router = APIRouter()

# Specify HTMLResponse as the default response class for this endpoint
@router.get("/users", response_class=HTMLResponse, tags=["users"])
def list_users(request: Request): # Changed to sync def
    """Provides an HTML page listing all registered users."""
    users = []
    # Connect to DB and fetch users
    with engine.connect() as connection:
        query = select(User)
        result = connection.execute(query)
        # Fetchall returns Row objects, which work like tuples/objects
        users = result.fetchall()

    return templates.TemplateResponse(
        name="users/list.html",
        context={"request": request, "users": users} # Pass fetched users
    )