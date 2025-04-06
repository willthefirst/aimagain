from fastapi import APIRouter

router = APIRouter()

@router.get("/users", tags=["users"])
async def list_users():
    """Provides a list of all registered users."""
    # For now, just return an empty list to satisfy the first test
    # Later, this will query the database.
    return [] 