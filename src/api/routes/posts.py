import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.post_processing import handle_get_post_detail, handle_list_posts
from src.models import User
from src.repositories.dependencies import get_post_repository
from src.repositories.post_repository import PostRepository

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_posts(
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page listing all posts (newest first).
    Requires authentication.
    """
    context = await handle_list_posts(
        request=request,
        post_repo=post_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="posts/list.html", context=context, request=request
    )


@router.get("/{post_id}")
async def get_post(
    post_id: UUID,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML detail page for a single post."""
    context = await handle_get_post_detail(
        request=request,
        post_id=post_id,
        post_repo=post_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="posts/detail.html", context=context, request=request
    )
