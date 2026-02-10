import re
from collections import defaultdict
from typing import Dict, List, Tuple

from app.categorizer.archetypes import load_archetype_map
from app.categorizer.llm import categorize_with_llm


ACTIVE_KEYWORDS = {
    "mix", "stir", "whisk", "beat", "fry", "saute", "sauté", "chop", "slice", "knead",
    "pour", "boil", "simmer", "bake", "grill", "roast", "sear", "fold", "flip", "stir-fry",
}
PASSIVE_KEYWORDS = {
    "refrigerate", "cool", "rest", "let it", "set aside", "transfer", "store", "chill", "wait", "serve",
}
HEAVY_FOOD = {
    "beef", "lamb", "pork", "cream", "butter", "cheese", "potato", "pasta", "rice", "bread", "stew", "roast",
}
LIGHT_FOOD = {
    "salad", "lettuce", "cucumber", "fruit", "berries", "yogurt", "nuts", "smoothie", "dip",
}


def _join_text(recipe: Dict) -> str:
    return " ".join(
        [
            str(recipe.get("recipe_name") or ""),
            str(recipe.get("recipe_description") or ""),
            " ".join(recipe.get("ingredients") or []),
            " ".join(recipe.get("steps") or []),
        ]
    ).lower()


def _cook_time_score(cook_time: int, scores: Dict[str, float]) -> None:
    t = max(0, int(cook_time or 0))
    if t and t < 15:
        scores["snack"] += 2.0
        scores["breakfast"] += 1.5
        scores["lunch"] += 0.5
    if 30 <= t <= 60:
        scores["lunch"] += 1.8
        scores["dinner"] += 1.8
    if t > 90:
        scores["dinner"] += 2.3
        scores["brunch"] += 1.3


def _thermal_score(recipe: Dict, scores: Dict[str, float]) -> None:
    steps = " ".join(recipe.get("steps") or []).lower()
    active_hits = sum(1 for w in ACTIVE_KEYWORDS if w in steps)
    passive_hits = sum(1 for w in PASSIVE_KEYWORDS if w in steps)

    no_heat = any(x in steps for x in ["no-heat", "no heat", "assemble", "assembly"]) or (
        active_hits == 0 and passive_hits > 0
    )

    if no_heat:
        scores["snack"] += 1.2
        scores["lunch"] += 1.0
        scores["supper"] += 0.8

    if active_hits >= 2:
        scores["dinner"] += 1.8
        scores["lunch"] += 0.7

    if passive_hits >= 2:
        scores["brunch"] += 0.8
        scores["dinner"] += 0.8


def _archetype_score(recipe: Dict, scores: Dict[str, float], archetypes: Dict[str, Dict[str, List[str]]]) -> None:
    text = _join_text(recipe)
    for cat, row in archetypes.items():
        hits = 0
        for token in row.get("primary_archetypes", []):
            if token and token in text:
                hits += 1
        for token in row.get("typical_techniques", []):
            if token and token in text:
                hits += 1
        if hits > 0:
            scores[cat] += min(2.5, 0.7 * hits)


def _satiety_score(recipe: Dict, scores: Dict[str, float]) -> None:
    text = _join_text(recipe)
    heavy_hits = sum(1 for w in HEAVY_FOOD if w in text)
    light_hits = sum(1 for w in LIGHT_FOOD if w in text)

    cal_str = str(recipe.get("calory_count") or "").lower()
    cal_num = None
    m = re.search(r"(\d+)", cal_str)
    if m:
        try:
            cal_num = int(m.group(1))
        except Exception:
            cal_num = None

    if heavy_hits >= 2 or (cal_num is not None and cal_num >= 650):
        scores["dinner"] += 2.0
        scores["supper"] += 1.2
        scores["lunch"] += 0.5

    if light_hits >= 2 or (cal_num is not None and cal_num <= 300):
        scores["snack"] += 1.7
        scores["lunch"] += 1.1
        scores["breakfast"] += 0.8


def _overlap_rules(recipe: Dict, scores: Dict[str, float]) -> None:
    text = _join_text(recipe)
    cook = int(recipe.get("cook_time") or 0)

    if ("egg" in text) and (cook >= 35):
        scores["breakfast"] += 1.5
        scores["brunch"] += 1.5

    if any(k in text for k in ["stew", "curry", "roast", "braise"]):
        scores["dinner"] += 1.3
        scores["lunch"] += 0.9

    if any(k in text for k in ["cold", "charcuterie", "chicken salad", "tuna salad"]) and not any(
        k in text for k in ["fry", "bake", "roast", "grill"]
    ):
        scores["lunch"] += 1.2
        scores["supper"] += 1.2


def heuristic_scores(recipe: Dict, available_categories: List[str]) -> Dict[str, float]:
    catset = {c.strip().lower() for c in available_categories}
    scores = defaultdict(float)

    _cook_time_score(int(recipe.get("cook_time") or 0), scores)
    _thermal_score(recipe, scores)
    _archetype_score(recipe, scores, load_archetype_map())
    _satiety_score(recipe, scores)
    _overlap_rules(recipe, scores)

    out = {c: float(scores.get(c, 0.0)) for c in catset}
    return out


def _fallback_pick(scores: Dict[str, float]) -> List[str]:
    if not scores:
        return []
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best = ranked[0][1]
    if best <= 0:
        return [ranked[0][0]]
    chosen = [cat for cat, sc in ranked if sc >= max(0.6, best * 0.7)]
    return chosen[:3] if chosen else [ranked[0][0]]


def categorize_recipe(recipe: Dict, available_categories: List[str]) -> Tuple[List[str], Dict[str, float]]:
    allowed = [c.strip().lower() for c in available_categories if c and str(c).strip()]
    scores = heuristic_scores(recipe, allowed)
    archetypes = load_archetype_map()
    llm_cats = categorize_with_llm(
        recipe=recipe,
        allowed_categories=allowed,
        heuristic_scores=scores,
        archetype_context=archetypes,
    )

    if llm_cats:
        high_score = _fallback_pick(scores)
        final = []
        for c in llm_cats + high_score:
            c = c.strip().lower()
            if c in allowed and c not in final:
                final.append(c)
        return final[:4], scores

    return _fallback_pick(scores), scores
