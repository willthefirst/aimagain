from fastapi import FastAPI
# Remove Jinja2Templates import here if no longer needed directly in main
# from fastapi.templating import Jinja2Templates
from .api.routes import users
from .api.routes import conversations
from .api.routes import me
from .api.routes import participants

app = FastAPI(title="Chat App")

# Remove templates configuration from here
# templates = Jinja2Templates(directory="templates")

@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"}

# Include the v1 user router
app.include_router(users.router, tags=["users"])

# Include the v1 conversations router
app.include_router(conversations.router, tags=["conversations"])

# Include the v1 me router
app.include_router(me.router, tags=["me"])

# Include the v1 participants router
app.include_router(participants.router, tags=["participants"]) 