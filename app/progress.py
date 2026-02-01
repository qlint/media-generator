import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def inputs_hash(payload: dict) -> str:
    canonical = {
        "id": payload.get("id"),
        "ingredients": payload.get("ingredients") or [],
        "recipe_steps": payload.get("recipe_steps") or payload.get("cooking_steps") or [],
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def recipe_root(base_dir: str, recipe_id: int) -> str:
    return os.path.join(base_dir, str(recipe_id))


def manifest_path(base_dir: str, recipe_id: int) -> str:
    return os.path.join(recipe_root(base_dir, recipe_id), "manifest.json")


def ensure_dirs(base_dir: str, recipe_id: int) -> Dict[str, str]:
    root = recipe_root(base_dir, recipe_id)
    ingredients_dir = os.path.join(root, "ingredients")
    steps_dir = os.path.join(root, "steps")
    os.makedirs(ingredients_dir, exist_ok=True)
    os.makedirs(steps_dir, exist_ok=True)
    return {"root": root, "ingredients": ingredients_dir, "steps": steps_dir}


def load_manifest(base_dir: str, recipe_id: int) -> Optional[Dict[str, Any]]:
    path = manifest_path(base_dir, recipe_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_manifest(base_dir: str, recipe_id: int, manifest: Dict[str, Any]) -> None:
    path = manifest_path(base_dir, recipe_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def init_manifest(base_dir: str, payload: dict) -> Dict[str, Any]:
    rid = int(payload["id"])
    h = inputs_hash(payload)
    now = utcnow_iso()
    m = load_manifest(base_dir, rid)

    if m and m.get("inputs_hash") == h:
        m["updated_at"] = now
        return m

    return {
        "recipe_id": rid,
        "inputs_hash": h,
        "created_at": now,
        "updated_at": now,
        "ingredients": {},       # index -> {status, files, prompt, error}
        "steps": {},             # index -> {type, status, files, prompt/shots, error}
        "rewritten_steps": None, # cached rewritten steps
        "plan": None,            # cached plan from planner (ingredients+steps)
    }


def mark_item(manifest: Dict[str, Any], section: str, idx: int, **fields: Any) -> None:
    key = str(idx)
    bucket = manifest.setdefault(section, {})
    item = bucket.get(key, {})
    item.update(fields)
    bucket[key] = item
    manifest["updated_at"] = utcnow_iso()
