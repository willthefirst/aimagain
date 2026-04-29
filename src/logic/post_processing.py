import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import NotFoundError
from src.models import Post, User
from src.repositories.post_repository import PostRepository
from src.schemas.post import PostCreate

logger = logging.getLogger(__name__)


async def handle_list_posts(
    request: Request,
    post_repo: PostRepository,
    requesting_user: User,
):
    """Loads all posts (newest first) and returns the template context."""
    posts = await post_repo.list_posts()
    return {"request": request, "posts": posts, "current_user": requesting_user}


async def handle_get_post_detail(
    request: Request,
    post_id: UUID,
    post_repo: PostRepository,
    requesting_user: User,
):
    """Loads a single post for the detail page; 404s if missing."""
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    return {"request": request, "post": post, "current_user": requesting_user}


async def handle_create_post(
    payload: PostCreate,
    post_repo: PostRepository,
    requesting_user: User,
) -> Post:
    """Creates a post owned by the requesting user; commits on success."""
    post = Post(
        title=payload.title,
        body=payload.body,
        owner_id=requesting_user.id,
    )
    created = await post_repo.create_post(post)
    await post_repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} created post {created.id}")
    return created
