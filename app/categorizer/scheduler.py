import os
import time
from typing import List

from app.categorizer.db import fetch_pending_recipe_ids
from app.queue import get_category_queue, claim_category_recipe, clear_category_claim


def _enqueue_batch(recipe_ids: List[int]) -> int:
    q = get_category_queue()
    queued = 0
    for rid in recipe_ids:
        rid = int(rid)
        # Avoid duplicate enqueue while a recipe is in-flight
        if not claim_category_recipe(rid):
            continue

        job_id = f"recipe-category-{rid}"
        try:
            q.enqueue(
                "app.categorizer.tasks.process_recipe_category_job",
                rid,
                job_id=job_id,
                job_timeout=os.getenv("CATEGORY_JOB_TIMEOUT", "20m"),
                result_ttl=int(os.getenv("CATEGORY_RESULT_TTL_S", "86400")),
                failure_ttl=int(os.getenv("CATEGORY_FAILURE_TTL_S", "86400")),
            )
            queued += 1
        except Exception:
            clear_category_claim(rid)
            continue
    return queued


def run_scheduler_forever() -> None:
    every = int(os.getenv("CATEGORY_SCHEDULER_INTERVAL_S", "600"))  # 10 minutes default
    batch = int(os.getenv("CATEGORY_BATCH_SIZE", "10"))

    print(f"[categorizer-scheduler] started. interval={every}s batch={batch}")
    while True:
        try:
            ids = fetch_pending_recipe_ids(limit=max(10, batch))
            n = _enqueue_batch(ids)
            print(f"[categorizer-scheduler] fetched={len(ids)} enqueued={n}")
        except Exception as e:
            print(f"[categorizer-scheduler] error: {e}")
        time.sleep(every)


if __name__ == "__main__":
    run_scheduler_forever()
