import os
import redis
from rq import Queue

def get_redis():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url)

def get_queue() -> Queue:
    return Queue("recipe-assets", connection=get_redis())
