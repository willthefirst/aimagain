from fastapi import FastAPI
from .api.v1.routes import users as users_v1 # Import the user router

app = FastAPI(title="Chat App")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"}

# Include the v1 user router
app.include_router(users_v1.router, prefix="/api/v1", tags=["v1"]) 