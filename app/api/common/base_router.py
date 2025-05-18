from functools import wraps
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, Depends

from app.api.common.decorators import handle_route_errors, log_route_call


class BaseRouter:
    def __init__(
        self,
        router: APIRouter,
        default_tags: Optional[List[str]] = None,
        default_dependencies: Optional[List[Depends]] = None,
    ):
        self.router = router
        self.default_tags = default_tags if default_tags is not None else []
        self.default_dependencies = (
            default_dependencies if default_dependencies is not None else []
        )

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

        route_dependencies = list(self.default_dependencies)
        if dependencies:
            route_dependencies.extend(dependencies)

        decorated_endpoint = endpoint
        if apply_common_decorators:
            decorated_endpoint = handle_route_errors(decorated_endpoint)
            decorated_endpoint = log_route_call(decorated_endpoint)

        self.router.add_api_route(
            path,
            decorated_endpoint,
            methods=methods,
            tags=list(set(route_tags)),  # Ensure unique tags
            dependencies=route_dependencies,
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


# Example of how to use this BaseRouter:
# from fastapi import FastAPI
# app = FastAPI()
#
# # In your main app or a specific module router setup
# main_router_instance = APIRouter(prefix="/api/v1")
# base_router_helper = BaseRouter(router=main_router_instance, default_tags=["API_V1"])
#
# # In a specific route file, e.g., items_routes.py
# # items_api_router = APIRouter() # This APIRouter instance is passed to BaseRouter
# # items_router = BaseRouter(router=items_api_router, default_tags=["Items"])
#
# @base_router_helper.get("/items/{item_id}")
# async def read_item(item_id: int, q: Optional[str] = None):
#     return {"item_id": item_id, "q": q}
#
# @base_router_helper.post("/items", status_code=201)
# async def create_item(item_name: str):
#     return {"name": item_name}
#
# app.include_router(main_router_instance)
