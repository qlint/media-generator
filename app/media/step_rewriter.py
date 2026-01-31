import os
from typing import List
from app.media.llm_client import ollama_generate
from app.media.json_utils import extract_json_object

SYSTEM = """You rewrite recipe steps to be clearer for cooking storyboards.
Rules:
- Keep meaning identical, do not add new ingredients or tools.
- Convert to short, action-first instructions in present tense.
- If the step contains multiple actions, keep it as one sentence separated by 'then' or commas (do NOT split into new steps).
- Avoid vague references like 'do this' - be explicit.
Return STRICT JSON only: {"rewritten_steps": [{"i": int, "text": str}, ...]}
"""

def _chunk(items: List[str], size: int) -> List[List[str]]:
    return [items[i:i+size] for i in range(0, len(items), size)]

def rewrite_steps(ingredients: List[str], steps: List[str]) -> List[str]:
    if not steps:
        return []

    batch_size = int(os.getenv("LLM_BATCH_STEPS", "20"))
    out = [None] * len(steps)

    # If Ollama isn't configured, return original steps
    if not os.getenv("OLLAMA_URL"):
        return steps

    for chunk_start, chunk_steps in enumerate(_chunk(steps, batch_size)):
        idx0 = chunk_start * batch_size
        indexed = [{"i": idx0 + j, "text": s} for j, s in enumerate(chunk_steps)]

        prompt = f"""Ingredients (context only):
{ingredients}

Rewrite the following steps:

{indexed}

Return strict JSON only."""

        try:
            resp = ollama_generate(SYSTEM, prompt, timeout_s=240)
            data = extract_json_object(resp)
            if not isinstance(data, dict) or "rewritten_steps" not in data:
                continue

            for item in data["rewritten_steps"]:
                i = int(item.get("i"))
                t = str(item.get("text") or "").strip()
                if 0 <= i < len(out) and t:
                    out[i] = t
        except Exception:
            # On failure, keep originals for this chunk
            pass

    # Fill gaps with original text
    return [out[i] if out[i] else steps[i] for i in range(len(steps))]
