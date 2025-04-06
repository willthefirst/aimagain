from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.engine import Connection

# Import templates from the new core location
from app.core.templating import templates
# Import DB dependency function and User model
from app.db import get_db
from app.models import User

router = APIRouter()

# Specify HTMLResponse as the default response class for this endpoint
@router.get("/users", response_class=HTMLResponse, tags=["users"])
def list_users(request: Request, db: Connection = Depends(get_db)):
    """Provides an HTML page listing all registered users."""

    # Use the injected database connection
    query = select(User)
    result = db.execute(query)
    users = result.fetchall()

    return templates.TemplateResponse(
        name="users/list.html",
        context={"request": request, "users": users} # Pass fetched users
    )