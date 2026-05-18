from typing import TYPE_CHECKING, Any, Callable, List, Optional

from fastapi import APIRouter, Depends

from src.framework.http.decorators import handle_route_errors, log_route_call

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


class BaseRouter:
    def __init__(
        self,
        router: APIRouter,
        default_tags: Optional[List[str]] = None,
    ):
        self.router = router
        self.default_tags = default_tags if default_tags is not None else []

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        dependencies: Optional[List[Depends]] = None,
        apply_common_decorators: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Adds a route to the underlying APIRouter, applying common decorators and defaults.
        """
        route_tags = list(self.default_tags)
        if tags:
            route_tags.extend(tags)

        decorated_endpoint = endpoint
        if apply_common_decorators:
            decorated_endpoint = handle_route_errors(decorated_endpoint)
            decorated_endpoint = log_route_call(decorated_endpoint)

        self.router.add_api_route(
            path,
            decorated_endpoint,
            methods=methods,
            tags=list(set(route_tags)),  # Ensure unique tags
            dependencies=dependencies or [],
            **kwargs,
        )

    # Convenience methods for GET, POST, etc.
    def get(
        self, path: str, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._create_route_decorator(path, methods=["GET"], **kwargs)

    def post(
        self, path: str, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._create_route_decorator(path, methods=["POST"], **kwargs)

    def put(
        self, path: str, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._create_route_decorator(path, methods=["PUT"], **kwargs)

    def delete(
        self, path: str, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._create_route_decorator(path, methods=["DELETE"], **kwargs)

    def patch(
        self, path: str, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._create_route_decorator(path, methods=["PATCH"], **kwargs)

    def _create_route_decorator(
        self,
        path: str,
        methods: List[str],
        apply_common_decorators: bool = True,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(endpoint: Callable[..., Any]) -> Callable[..., Any]:
            self.add_api_route(
                path,
                endpoint,
                methods=methods,
                apply_common_decorators=apply_common_decorators,
                **kwargs,
            )
            return endpoint

        return decorator


def _make_entity_router(entity: "EntitySpec") -> BaseRouter:
    """Build a `BaseRouter` for `entity` with prefix + tags derived from the spec.

    Framework-internal. Route files call
    :func:`src.framework.dispatch.registry.register_entity`, which wraps
    this helper and adds the registry bookkeeping. The prefix is
    ``f"/{entity.url_collection}"`` unless the spec sets
    ``prefix_override`` (favorites lives at ``/users/me/favorites``);
    default tags are ``[entity.url_collection]``.
    """
    prefix = (
        entity.prefix_override
        if entity.prefix_override is not None
        else f"/{entity.url_collection}"
    )
    return BaseRouter(
        router=APIRouter(prefix=prefix),
        default_tags=[entity.url_collection],
    )
