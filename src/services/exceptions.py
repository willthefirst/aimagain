import logging

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Base class for service layer errors."""

    def __init__(self, message="An internal service error occurred.", status_code=500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class ConversationNotFoundError(ServiceError):
    def __init__(self, message="Conversation not found."):
        super().__init__(message, status_code=404)


class ParticipantNotFoundError(ServiceError):
    def __init__(self, message="Participant record not found."):
        super().__init__(message, status_code=404)


class UserNotFoundError(ServiceError):
    def __init__(self, message="User not found."):
        super().__init__(message, status_code=404)


class NotAuthorizedError(ServiceError):
    def __init__(self, message="User not authorized for this action."):
        super().__init__(message, status_code=403)


class BusinessRuleError(ServiceError):
    """For violations of specific business rules (e.g., user offline)."""

    def __init__(self, message="Action violates business rules."):
        super().__init__(message, status_code=400)  # Often a Bad Request


class ConflictError(ServiceError):
    """For conflicts like trying to add an existing participant."""

    def __init__(self, message="Operation conflicts with existing state."):
        super().__init__(message, status_code=409)


class DatabaseError(ServiceError):
    """For general database errors during service operations."""

    def __init__(self, message="A database error occurred."):
        super().__init__(message, status_code=500)
