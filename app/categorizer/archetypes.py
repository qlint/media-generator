import json
import os
from functools import lru_cache
from typing import Dict, List


DEFAULT_FILE = os.getenv(
    "ARCHETYPE_MAP_FILE",
    os.path.join(os.path.dirname(__file__), "config", "ingredient_archetypes.json"),
)

@lru_cache(maxsize=1)
def load_archetype_map() -> Dict[str, Dict[str, List[str]]]:
    """Load ingredient archetype mapping keyed by broad category name (lowercase)."""
    path = DEFAULT_FILE
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    out = {}
    for row in data:
        cat = (row.get("category") or "").strip().lower()
        if not cat:
            continue
        out[cat] = {
            "primary_archetypes": [x.strip().lower() for x in row.get("primary_archetypes", []) if str(x).strip()],
            "typical_techniques": [x.strip().lower() for x in row.get("typical_techniques", []) if str(x).strip()],
        }
    return out
