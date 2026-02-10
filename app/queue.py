import os
import redis
from rq import Queue


def get_redis():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url)


def get_queue() -> Queue:
    # existing queue for asset generation
    return Queue("recipe-assets", connection=get_redis())


def get_category_queue() -> Queue:
    return Queue(os.getenv("CATEGORY_QUEUE_NAME", "recipe-categorizer"), connection=get_redis())


def _claim_ttl_s() -> int:
    return int(os.getenv("CATEGORY_CLAIM_TTL_S", "7200"))


def _claim_key(recipe_id: int) -> str:
    return f"recipe-categorizer:inflight:{int(recipe_id)}"


def claim_category_recipe(recipe_id: int) -> bool:
    """Return True if claimed (not currently in-flight), False otherwise."""
    r = get_redis()
    return bool(r.set(_claim_key(recipe_id), "1", nx=True, ex=_claim_ttl_s()))


def clear_category_claim(recipe_id: int) -> None:
    get_redis().delete(_claim_key(recipe_id))
