from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse # Or directly use TemplateResponse
# Import templates from the new core location
from app.core.templating import templates

router = APIRouter()

# Specify HTMLResponse as the default response class for this endpoint
@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(request: Request): # Inject request object
    """Provides an HTML page listing all registered users."""
    # For now, just return the template with an empty list
    # Later, this will query the database.
    return templates.TemplateResponse(
        name="users/list.html", # Correct path within the 'templates' directory
        context={"request": request, "users": []} # Pass request and empty list
    ) 