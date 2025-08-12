import logging
from uuid import UUID

from fastapi import Request

from src.models import User
from src.models.post import Post
from src.schemas.post import PostCreateRequest, PostType, PostUpdateRequest
from src.services.post_service import PostService

logger = logging.getLogger(__name__)


async def handle_list_posts(
    post_type: PostType | None,
    post_service: PostService,
) -> list[Post]:
    """
    Handles the core logic for listing posts with optional filtering.

    Args:
        post_type: Optional filter for post type.
        post_service: The post service dependency.

    Returns:
        List of posts matching the filter criteria.

    Raises:
        ServiceError: For generic service-level errors.
    """
    logger.info(f"Handling list posts request with type filter: {post_type}")

    posts = await post_service.list_posts(post_type=post_type)

    logger.info(f"Successfully retrieved {len(posts)} posts")
    return posts


async def handle_get_new_post_form(request: Request) -> dict:
    """
    Handles the logic for displaying the new post form.

    Args:
        request: The HTTP request object.

    Returns:
        Context dictionary for the template.
    """
    logger.info("Handling new post form request")

    # Just return empty context for now - could include form options, validation rules, etc.
    context = {}

    logger.info("Successfully prepared new post form context")
    return context


async def handle_create_post(
    title: str,
    content: str,
    post_type: PostType,
    user: User,
    post_service: PostService,
) -> Post:
    """
    Handles the core logic for creating a new post.

    Args:
        title: The post title.
        content: The post content.
        post_type: The type of post.
        user: The user creating the post.
        post_service: The post service dependency.

    Returns:
        The newly created post.

    Raises:
        ServiceError: For generic service-level errors.
    """
    logger.info(f"Handling create post request by user {user.id} with title: {title}")

    request_data = PostCreateRequest(title=title, content=content, post_type=post_type)
    post = await post_service.create_post(request_data, user)

    logger.info(f"Successfully created post with ID: {post.id}")
    return post


async def handle_get_post(
    post_id: UUID,
    post_service: PostService,
) -> Post | None:
    """
    Handles the core logic for retrieving a single post.

    Args:
        post_id: The UUID of the post to retrieve.
        post_service: The post service dependency.

    Returns:
        The post if found, None otherwise.

    Raises:
        ServiceError: For generic service-level errors.
    """
    logger.info(f"Handling get post request for ID: {post_id}")

    post = await post_service.get_post(post_id)

    if post:
        logger.info(f"Successfully retrieved post with ID: {post_id}")
    else:
        logger.warning(f"Post not found with ID: {post_id}")

    return post


async def handle_get_edit_post_form(
    post_id: UUID,
    user: User,
    post_service: PostService,
) -> tuple[Post | None, bool]:
    """
    Handles the logic for displaying the edit post form.

    Args:
        post_id: The UUID of the post to edit.
        user: The user requesting to edit the post.
        post_service: The post service dependency.

    Returns:
        Tuple of (post, is_authorized) where:
        - post: The post if found, None otherwise
        - is_authorized: True if user can edit this post, False otherwise

    Raises:
        ServiceError: For generic service-level errors.
    """
    logger.info(f"Handling edit post form request for ID: {post_id} by user {user.id}")

    post = await post_service.get_post(post_id)

    if not post:
        logger.warning(f"Post not found with ID: {post_id}")
        return None, False

    is_authorized = post.created_by_user_id == user.id

    if not is_authorized:
        logger.warning(f"User {user.id} not authorized to edit post {post_id}")
    else:
        logger.info(f"User {user.id} authorized to edit post {post_id}")

    return post, is_authorized


async def handle_update_post(
    post_id: UUID,
    title: str,
    content: str,
    user: User,
    post_service: PostService,
) -> Post | None:
    """
    Handles the core logic for updating a post.

    Args:
        post_id: The UUID of the post to update.
        title: The updated title.
        content: The updated content.
        user: The user updating the post.
        post_service: The post service dependency.

    Returns:
        The updated post if successful, None if post not found or unauthorized.

    Raises:
        ServiceError: For generic service-level errors.
    """
    logger.info(f"Handling update post request for ID: {post_id} by user {user.id}")

    request_data = PostUpdateRequest(title=title, content=content)
    updated_post = await post_service.update_post(post_id, request_data, user)

    if updated_post:
        logger.info(f"Successfully updated post with ID: {post_id}")
    else:
        logger.warning(
            f"Failed to update post with ID: {post_id} - not found or unauthorized"
        )

    return updated_post


async def handle_delete_post(
    post_id: UUID,
    user: User,
    post_service: PostService,
) -> bool:
    """
    Handles the core logic for deleting a post.

    Args:
        post_id: The UUID of the post to delete.
        user: The user deleting the post.
        post_service: The post service dependency.

    Returns:
        True if post was successfully deleted, False if not found or unauthorized.

    Raises:
        ServiceError: For generic service-level errors.
    """
    logger.info(f"Handling delete post request for ID: {post_id} by user {user.id}")

    deleted = await post_service.delete_post(post_id, user)

    if deleted:
        logger.info(f"Successfully deleted post with ID: {post_id}")
    else:
        logger.warning(
            f"Failed to delete post with ID: {post_id} - not found or unauthorized"
        )

    return deleted
