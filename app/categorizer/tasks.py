from typing import Dict, Any, List

from app.categorizer.db import (
    fetch_recipe_payload,
    fetch_broad_categories,
    save_recipe_categories,
)
from app.categorizer.logic import categorize_recipe
from app.queue import clear_category_claim


def process_recipe_category_job(recipe_id: int) -> Dict[str, Any]:
    """RQ task: classify one recipe and persist relation rows.

    Queue: recipe-categorizer
    """
    rid = int(recipe_id)
    try:
        recipe = fetch_recipe_payload(rid)
        if not recipe:
            return {"ok": False, "recipe_id": rid, "message": "recipe_not_found"}

        category_map = fetch_broad_categories()  # dynamic, not hardcoded
        if not category_map:
            raise RuntimeError("No rows found in app.broad_categories")

        available_names = sorted(category_map.keys())
        selected_names, scores = categorize_recipe(recipe, available_names)

        if not selected_names:
            if scores:
                selected_names = [sorted(scores.items(), key=lambda x: x[1], reverse=True)[0][0]]
            else:
                return {"ok": False, "recipe_id": rid, "message": "no_categories_selected"}

        category_ids: List[int] = [category_map[name] for name in selected_names if name in category_map]
        save_recipe_categories(rid, category_ids)

        return {
            "ok": True,
            "recipe_id": rid,
            "category_names": selected_names,
            "category_ids": category_ids,
            "score_snapshot": scores,
        }
    finally:
        # release scheduler claim so it can be re-queued in edge cases
        clear_category_claim(rid)
