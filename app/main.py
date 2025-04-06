from fastapi import FastAPI
# Remove Jinja2Templates import here if no longer needed directly in main
# from fastapi.templating import Jinja2Templates
from .api.v1.routes import users as users_v1
from .api.v1.routes import conversations as conversations_v1

app = FastAPI(title="Chat App")

# Remove templates configuration from here
# templates = Jinja2Templates(directory="templates")

@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"}

# Include the v1 user router
app.include_router(users_v1.router, prefix="/api/v1", tags=["v1", "users"])

# Include the v1 conversations router
app.include_router(conversations_v1.router, prefix="/api/v1", tags=["v1", "conversations"]) 