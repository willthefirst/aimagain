import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.models import Post, User
from src.repositories.post_repository import PostRepository
from src.schemas.post import PostCreate, PostUpdate

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


async def handle_get_post_form(
    request: Request,
    requesting_user: User,
):
    """Builds the template context for the create-post form."""
    return {"request": request, "current_user": requesting_user}


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


async def handle_update_post(
    post_id: UUID,
    payload: PostUpdate,
    post_repo: PostRepository,
    requesting_user: User,
) -> Post:
    """Patches a post owned by the requesting user (or by anyone, if the
    requester is a superuser). 404 if missing, 403 if not authorized.
    """
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    if post.owner_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(detail="Only the owner or an admin can edit this post")

    updated = await post_repo.update_post(post, title=payload.title, body=payload.body)
    await post_repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} updated post {updated.id}")
    return updated
