import os
from typing import Dict, List

from app.media.llm_client import ollama_generate
from app.media.json_utils import extract_json_object


SYSTEM = """You are an expert chef and culinary taxonomy assistant.
Return STRICT JSON only. No markdown.
You assign one or more broad categories to a recipe from a provided allowed list.
A recipe can have overlaps (e.g., breakfast+brunch, dinner+lunch leftovers).
"""


def _safe_categories(v) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    return []


def categorize_with_llm(
    recipe: Dict,
    allowed_categories: List[str],
    heuristic_scores: Dict[str, float],
    archetype_context: Dict[str, Dict[str, List[str]]],
) -> List[str]:
    allowed_categories = sorted(set([c.strip().lower() for c in allowed_categories if c and str(c).strip()]))
    prompt = f"""
Allowed broad categories (must choose from this list only):
{allowed_categories}

Recipe:
- Name: {recipe.get('recipe_name')}
- Cook time minutes: {recipe.get('cook_time')}
- Calorie count (may be unknown): {recipe.get('calory_count')}
- Description: {recipe.get('recipe_description')}
- Ingredients: {recipe.get('ingredients')}
- Steps: {recipe.get('steps')}

Chef framework to apply:
1) Total Investment = prep + cook (use cook_time as proxy if prep not provided)
2) Ingredient archetypes and techniques
3) Satiety and portion scale
4) Overlap tagging is allowed
5) Thermal intensity (ambient/cold vs active thermal vs passive thermal)

Ingredient archetype mapping context:
{archetype_context}

Heuristic prior scores (higher = more likely):
{heuristic_scores}

Output schema (STRICT JSON):
{{
  "categories": ["one_or_more_from_allowed_list"],
  "confidence": 0.0_to_1.0,
  "notes": "very brief"
}}
"""

    raw = ollama_generate(system=SYSTEM, prompt=prompt, timeout_s=int(os.getenv("CATEGORY_LLM_TIMEOUT_S", "180")))
    parsed = extract_json_object(raw)
    if isinstance(parsed, dict):
        cats = _safe_categories(parsed.get("categories"))
    elif isinstance(parsed, list):
        cats = _safe_categories(parsed)
    else:
        cats = []

    allowed_set = set(allowed_categories)
    cats = [c for c in cats if c in allowed_set]

    return cats
