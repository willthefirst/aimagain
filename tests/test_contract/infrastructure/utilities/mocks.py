"""Mock and patching utilities for contract tests."""

import logging
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from src.models import User


def create_mock_user(email: str, username: str, user_id: uuid.UUID = None) -> User:
    """Helper function to create a mock User instance."""
    return User(
        id=user_id if user_id else uuid.uuid4(),
        email=email,
        username=username,
        is_active=True,
    )


def convert_string_ids_to_uuid(data: Any) -> Any:
    """Recursively convert string IDs to UUID objects in data structures."""
    if isinstance(data, dict):
        if "id" in data and isinstance(data["id"], str):
            try:
                data["id"] = uuid.UUID(data["id"])
            except ValueError:
                pass  # Keep as string if not a valid UUID
        return {k: convert_string_ids_to_uuid(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_string_ids_to_uuid(item) for item in data]
    return data


def create_async_mock_from_config(mock_config: Dict[str, Any]) -> AsyncMock:
    """Create an AsyncMock instance from configuration."""
    if "return_value_config" in mock_config:
        return_data = mock_config["return_value_config"]
        return_data = convert_string_ids_to_uuid(return_data)
        return AsyncMock(return_value=return_data)
    else:
        return AsyncMock()


def apply_patches_via_monkeypatch(
    mp: pytest.MonkeyPatch, override_config: Dict[str, Dict], logger: logging.Logger
) -> None:
    """Apply patches using pytest's MonkeyPatch."""
    if not override_config:
        return

    for patch_target_path, mock_config in override_config.items():
        try:
            mock_instance = create_async_mock_from_config(mock_config)
            mp.setattr(patch_target_path, mock_instance)
            logger.info(
                f"Applied patch for '{patch_target_path}' with mock: {mock_instance}"
            )
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.error(f"Failed to setup mock/patch for '{patch_target_path}': {e}")
            raise RuntimeError(
                f"Failed to setup mock/patch for '{patch_target_path}'"
            ) from e


def apply_patches_via_import(
    override_config: Dict[str, Dict], logger: logging.Logger
) -> None:
    """Apply patches by directly modifying imported modules."""
    if not override_config:
        return

    for patch_target_path, mock_config in override_config.items():
        try:
            mock_instance = create_async_mock_from_config(mock_config)

            # Apply the patch by modifying the module directly
            module_path, function_name = patch_target_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[function_name])
            setattr(module, function_name, mock_instance)

            logger.info(
                f"Applied patch for '{patch_target_path}' with mock: {mock_instance}"
            )
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.error(f"Failed to setup mock/patch for '{patch_target_path}': {e}")
            raise RuntimeError(
                f"Failed to setup mock/patch for '{patch_target_path}'"
            ) from e


class MockAuthManager:
    """Manages mock authentication for test servers."""

    @staticmethod
    def create_mock_user_dependency(user: User):
        """Create a dependency override function for mock authentication."""

        async def get_mock_current_user():
            return user

        return get_mock_current_user

    @staticmethod
    def setup_mock_auth(app, user: User, dependency_to_override):
        """Set up mock authentication on a FastAPI app."""
        mock_dependency = MockAuthManager.create_mock_user_dependency(user)
        app.dependency_overrides[dependency_to_override] = mock_dependency
        return mock_dependency
