import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.post_processing import (
    handle_create_post,
    handle_delete_post,
    handle_get_edit_post_form,
    handle_get_new_post_form,
    handle_get_post,
    handle_list_posts,
    handle_update_post,
)
from src.models import User
from src.schemas.post import PostType
from src.services.dependencies import get_post_service
from src.services.post_service import PostService

logger = logging.getLogger(__name__)
posts_router_instance = APIRouter()
router = BaseRouter(router=posts_router_instance)


@router.get("/posts", tags=["posts"])
async def list_posts(
    request: Request,
    post_type: PostType | None = None,
    user: User = Depends(current_active_user),
    post_service: PostService = Depends(get_post_service),
):
    """Provides an HTML page listing all posts with optional filtering."""
    posts = await handle_list_posts(
        post_type=post_type,
        post_service=post_service,
    )
    return APIResponse.html_response(
        template_name="posts/list.html",
        context={"posts": posts, "current_user": user, "selected_type": post_type},
        request=request,
    )


@router.get("/posts/new", name="get_new_post_form", tags=["posts"])
async def get_new_post_form(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Serves the form for creating a new post."""
    context = await handle_get_new_post_form(request=request)
    context["current_user"] = user
    return APIResponse.html_response(
        template_name="posts/new.html",
        context=context,
        request=request,
    )


@router.post("/posts", tags=["posts"])
async def create_post(
    title: str = Form(...),
    content: str = Form(...),
    post_type: PostType = Form(...),
    user: User = Depends(current_active_user),
    post_service: PostService = Depends(get_post_service),
):
    """Creates a new post and redirects to the posts list."""
    await handle_create_post(
        title=title,
        content=content,
        post_type=post_type,
        user=user,
        post_service=post_service,
    )

    return RedirectResponse(url="/posts", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/posts/{post_id}", tags=["posts"])
async def get_post(
    post_id: UUID,
    request: Request,
    user: User = Depends(current_active_user),
    post_service: PostService = Depends(get_post_service),
):
    """Displays a single post."""
    post = await handle_get_post(
        post_id=post_id,
        post_service=post_service,
    )
    if not post:
        return APIResponse.html_response(
            template_name="errors/404.html",
            context={"message": "Post not found"},
            request=request,
            status_code=404,
        )

    return APIResponse.html_response(
        template_name="posts/detail.html",
        context={"post": post, "current_user": user},
        request=request,
    )


@router.get("/posts/{post_id}/edit", tags=["posts"])
async def get_edit_post_form(
    post_id: UUID,
    request: Request,
    user: User = Depends(current_active_user),
    post_service: PostService = Depends(get_post_service),
):
    """Serves the form for editing a post."""
    post, is_authorized = await handle_get_edit_post_form(
        post_id=post_id,
        user=user,
        post_service=post_service,
    )

    if not post:
        return APIResponse.html_response(
            template_name="errors/404.html",
            context={"message": "Post not found"},
            request=request,
            status_code=404,
        )

    if not is_authorized:
        return APIResponse.html_response(
            template_name="errors/403.html",
            context={"message": "You can only edit your own posts"},
            request=request,
            status_code=403,
        )

    return APIResponse.html_response(
        template_name="posts/edit.html",
        context={"post": post, "current_user": user},
        request=request,
    )


@router.put("/posts/{post_id}", tags=["posts"])
async def update_post(
    post_id: UUID,
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    user: User = Depends(current_active_user),
    post_service: PostService = Depends(get_post_service),
):
    """Updates a post via PUT method."""
    updated_post = await handle_update_post(
        post_id=post_id,
        title=title,
        content=content,
        user=user,
        post_service=post_service,
    )

    if not updated_post:
        return APIResponse.html_response(
            template_name="errors/404.html",
            context={"message": "Post not found"},
            request=request,
            status_code=404,
        )

    return RedirectResponse(
        url=f"/posts/{post_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.delete("/posts/{post_id}", tags=["posts"])
async def delete_post(
    post_id: UUID,
    request: Request,
    user: User = Depends(current_active_user),
    post_service: PostService = Depends(get_post_service),
):
    """Deletes a post via DELETE method."""
    deleted = await handle_delete_post(
        post_id=post_id,
        user=user,
        post_service=post_service,
    )

    if not deleted:
        return APIResponse.html_response(
            template_name="errors/404.html",
            context={"message": "Post not found"},
            request=request,
            status_code=404,
        )

    return RedirectResponse(url="/posts", status_code=status.HTTP_303_SEE_OTHER)
