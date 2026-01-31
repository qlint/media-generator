import os
import re
from typing import List, Dict, Any

from app.media.llm_client import ollama_generate
from app.media.json_utils import extract_json_object
from app.media.prompts import NEGATIVE_DEFAULT, STYLE_FOOD_PHOTO, STYLE_COOKING_VIDEO

SYSTEM = """You are a media planner for recipe assets.
You must output STRICT JSON only.

Goals:
- Ingredient assets: one studio-quality photo each.
- Step assets:
  - Use "video" for active actions (mixing, frying, chopping, whisking, kneading, stirring, pouring, flipping, sautéing).
  - Use "image" for passive/waiting/transfer/resting/cooling/refrigerating/serving.
- For every "video" step, create 1-3 storyboard shots.
- Prompts must be professional, well-lit, minimal clutter, no text/logos/watermarks.
- Videos must be silent (no audio mentioned), instructional framing.
Return strict JSON schema:

{
  "ingredients": [{"prompt": str, "negative_prompt": str}],
  "steps": [{
      "media_type": "image"|"video",
      "prompt": str,
      "negative_prompt": str,
      "target_seconds": int,
      "shots": [{"duration_s": int, "prompt": str}]
  }]
}
"""

def _heuristic_step_type(step: str) -> str:
    s = step.lower()
    passive = ["refrigerate", "cool", "rest", "let it", "set aside", "transfer", "store", "serve", "wait", "chill"]
    active = ["mix", "stir", "whisk", "beat", "fry", "saute", "sauté", "chop", "slice", "knead",
              "pour", "boil", "simmer", "bake", "grill", "roast", "sear", "fold", "flip", "sautee"]
    if any(w in s for w in passive) and not any(w in s for w in active):
        return "image"
    if any(w in s for w in active):
        return "video"
    return "image"

def _strip_quantity(ingredient: str) -> str:
    # Remove leading quantities like "2 tbsp", "1/2 cup", etc.
    t = ingredient.strip()
    t = re.sub(r"^\s*[\d/\.\-]+\s*(tbsp|tsp|cup|cups|g|kg|ml|l|oz|lb|pounds|pinch|dash)?\s*", "", t, flags=re.I)
    return t.strip() or ingredient.strip()

def plan_recipe_media(recipe_id: int, ingredients: List[str], original_steps: List[str], rewritten_steps: List[str]) -> Dict[str, Any]:
    default_seconds = int(os.getenv("VIDEO_TARGET_SECONDS_DEFAULT", "12"))
    max_shots = int(os.getenv("VIDEO_MAX_SHOTS_PER_STEP", "3"))

    # Fallback if LLM unavailable
    if not os.getenv("OLLAMA_URL"):
        return _fallback_plan(ingredients, rewritten_steps, default_seconds)

    prompt = f"""Recipe id: {recipe_id}

Ingredients:
{ingredients}

Original steps:
{original_steps}

Rewritten steps (use these for storyboarding):
{rewritten_steps}

Constraints:
- Ingredient prompts should NOT include quantities; focus on the ingredient itself.
- Use: {STYLE_FOOD_PHOTO}
- Use for video shots: {STYLE_COOKING_VIDEO}
- No audio.

For each step:
- Decide media_type image vs video.
- If video: provide 1..{max_shots} shots and per-shot duration_s.
- Keep prompts concise but specific (camera angle, lighting, key objects).

Return strict JSON only."""

    try:
        resp = ollama_generate(SYSTEM, prompt, timeout_s=240)
        data = extract_json_object(resp)
        if not isinstance(data, dict):
            return _fallback_plan(ingredients, rewritten_steps, default_seconds)

        # sanitize
        ing = []
        for i, item in enumerate(data.get("ingredients", [])):
            p = (item.get("prompt") or "").strip()
            if not p:
                name = _strip_quantity(ingredients[i]) if i < len(ingredients) else f"ingredient {i}"
                p = f"{STYLE_FOOD_PHOTO}. Studio photo of {name}."
            ing.append({"prompt": p, "negative_prompt": item.get("negative_prompt") or NEGATIVE_DEFAULT})

        steps_out = []
        for i, st in enumerate(data.get("steps", [])):
            mt = st.get("media_type")
            if mt not in ("image", "video"):
                mt = _heuristic_step_type(rewritten_steps[i] if i < len(rewritten_steps) else "")
            neg = st.get("negative_prompt") or NEGATIVE_DEFAULT
            step_prompt = (st.get("prompt") or "").strip()
            if not step_prompt:
                step_prompt = f"{STYLE_FOOD_PHOTO}. {rewritten_steps[i] if i < len(rewritten_steps) else ''}"

            target = int(st.get("target_seconds") or (default_seconds if mt == "video" else 0))

            shots = []
            if mt == "video":
                raw_shots = st.get("shots") or []
                for sh in raw_shots[:max_shots]:
                    dur = int(sh.get("duration_s") or 6)
                    sp = (sh.get("prompt") or "").strip()
                    if sp:
                        shots.append({"duration_s": dur, "prompt": sp})
                if not shots:
                    shots = [{"duration_s": min(6, target or 6), "prompt": f"{STYLE_COOKING_VIDEO}. {rewritten_steps[i]}"}]

            steps_out.append({
                "media_type": mt,
                "prompt": step_prompt,
                "negative_prompt": neg,
                "target_seconds": target,
                "shots": shots
            })

        # Ensure lengths match (ingredients count + step count)
        if len(ing) != len(ingredients):
            ing = _fallback_plan(ingredients, rewritten_steps, default_seconds)["ingredients"]
        if len(steps_out) != len(rewritten_steps):
            steps_out = _fallback_plan(ingredients, rewritten_steps, default_seconds)["steps"]

        return {"ingredients": ing, "steps": steps_out}

    except Exception:
        return _fallback_plan(ingredients, rewritten_steps, default_seconds)

def _fallback_plan(ingredients: List[str], steps: List[str], default_seconds: int) -> Dict[str, Any]:
    ing = []
    for item in ingredients:
        name = _strip_quantity(item)
        ing.append({
            "prompt": f"{STYLE_FOOD_PHOTO}. Studio photo of {name}, clean neutral background.",
            "negative_prompt": NEGATIVE_DEFAULT
        })
    step_items = []
    for st in steps:
        mt = _heuristic_step_type(st)
        if mt == "image":
            step_items.append({
                "media_type": "image",
                "prompt": f"{STYLE_FOOD_PHOTO}. {st}",
                "negative_prompt": NEGATIVE_DEFAULT,
                "target_seconds": 0,
                "shots": []
            })
        else:
            step_items.append({
                "media_type": "video",
                "prompt": f"{STYLE_FOOD_PHOTO}. {st}",
                "negative_prompt": NEGATIVE_DEFAULT,
                "target_seconds": default_seconds,
                "shots": [{"duration_s": min(6, default_seconds), "prompt": f"{STYLE_COOKING_VIDEO}. {st}"}]
            })
    return {"ingredients": ing, "steps": step_items}
