from src.framework.base_repository import BaseRepository


class PostRepository(BaseRepository):
    """Posts have no bespoke read/write methods today — listing falls
    through to `BaseRepository.list_default(Post, order_by=Post.created_at.desc())`
    via `handle_list` (`POST_ENTITY.list_order_by`), and create/update/
    delete go through the public aliases on `BaseRepository`. The class
    exists so dep injection can resolve a typed repo and per-test
    fixtures can subclass it.
    """
