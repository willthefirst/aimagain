from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.engine import Connection

from app.core.templating import templates
from app.db import get_db
# Import Conversation model later when needed
# from app.models import Conversation

router = APIRouter()

@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
def list_conversations(request: Request, db: Connection = Depends(get_db)):
    """Provides an HTML page listing all public conversations."""
    # For now, fetch nothing and return an empty list
    conversations = []

    return templates.TemplateResponse(
        name="conversations/list.html", # Template path
        context={"request": request, "conversations": conversations}
    ) 