# Makes 'models' a package and simplifies imports

from .base import BaseModel, metadata
from .user import User
from .conversation import Conversation
from .message import Message
from .participant import Participant

# Define __all__ for explicit public interface (optional but good practice)
__all__ = [
    "BaseModel",
    "metadata",
    "User",
    "Conversation",
    "Message",
    "Participant",
]
