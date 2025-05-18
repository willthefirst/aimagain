import logging
from typing import Any, Dict, Type, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class ServiceProvider:
    """
    A simple service provider that manages singleton instances of services.
    Services are instantiated once and reused.
    """

    _instances: Dict[Type[T], T] = {}

    @classmethod
    def get_service(cls, service_class: Type[T], **dependencies: Any) -> T:
        """
        Retrieves or creates a singleton instance of the given service class.
        Dependencies for the service are passed as keyword arguments.
        """
        if service_class not in cls._instances:
            try:
                logger.debug(
                    f"Creating new instance of service: {service_class.__name__}"
                )
                cls._instances[service_class] = service_class(**dependencies)
            except Exception as e:
                logger.error(
                    f"Failed to initialize service {service_class.__name__}: {e}",
                    exc_info=True,
                )
                # Consider raising a specific ServiceInitializationError if needed
                raise
        return cls._instances[service_class]

    @classmethod
    def clear(cls) -> None:
        """
        Clears all cached service instances.
        Primarily useful for testing to ensure fresh services for each test case.
        """
        logger.debug("Clearing all cached service instances.")
        cls._instances.clear()
