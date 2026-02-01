from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from rq.job import Job

import os
import time
import requests

from app.models import RecipeIn, EnqueueResponse, JobStatus
from app.queue import get_queue, get_redis
from app.tasks import generate_assets_job
from app.progress import load_manifest

app = FastAPI(title="Recipe Media Generator (T2V)", version="2.2")


def _check_redis() -> dict:
    try:
        rds = get_redis()
        start = time.time()
        ok = bool(rds.ping())
        ms = int((time.time() - start) * 1000)
        return {"ok": ok, "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_ollama() -> dict:
    base = os.getenv("OLLAMA_URL", "").strip()
    if not base:
        return {"ok": False, "error": "OLLAMA_URL not set"}
    try:
        start = time.time()
        resp = requests.get(f"{base}/api/tags", timeout=3)
        ms = int((time.time() - start) * 1000)
        if resp.status_code != 200:
            return {"ok": False, "latency_ms": ms, "status_code": resp.status_code}
        data = resp.json()
        return {"ok": True, "latency_ms": ms, "models_count": len(data.get("models", []))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Static asset serving ---
ASSETS_BASE_DIR = os.getenv("ASSETS_BASE_DIR", "/data/assets")
os.makedirs(ASSETS_BASE_DIR, exist_ok=True)
# This exposes e.g. /assets/100/ingredients/0.png
app.mount("/assets", StaticFiles(directory=ASSETS_BASE_DIR), name="assets")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health-check")
def health_check():
    redis_status = _check_redis()
    ollama_status = _check_ollama()
    overall_ok = bool(redis_status.get("ok")) and bool(ollama_status.get("ok"))
    return {"ok": overall_ok, "services": {"redis": redis_status, "ollama": ollama_status}}


@app.post("/v1/recipes/assets", response_model=EnqueueResponse, status_code=202)
def enqueue_assets(recipe: RecipeIn):
    # IMPORTANT: This endpoint is idempotent-ish by recipe id: posting the same id again
    # will RESUME generation by skipping already generated files.
    q = get_queue()
    job = q.enqueue(
        generate_assets_job,
        recipe.model_dump(by_alias=False),
        job_timeout=os.getenv("RQ_JOB_TIMEOUT", "48h"),
        result_ttl=86400,
        failure_ttl=86400,
    )
    return EnqueueResponse(job_id=job.id, status_url=f"/v1/jobs/{job.id}")


@app.get("/v1/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str):
    job = Job.fetch(job_id, connection=get_redis())
    return JobStatus(
        job_id=job.id,
        status=job.get_status(),
        exc_info=job.exc_info,
        result=job.result if job.is_finished else None,
    )


@app.get("/v1/recipes/{recipe_id}/assets")
def recipe_assets(recipe_id: int):
    """Return the current manifest plus convenient web URLs for generated assets."""
    m = load_manifest(ASSETS_BASE_DIR, recipe_id)
    if not m:
        raise HTTPException(status_code=404, detail="manifest not found for recipe id")
    # Build URLs based on manifest file entries
    def url_for(rel_path: str) -> str:
        rel_path = rel_path.lstrip("/")
        return f"/assets/{recipe_id}/{rel_path}"

    out = {
        "recipe_id": recipe_id,
        "manifest": m,
        "urls": {"ingredients": {}, "steps": {}},
    }

    ing = m.get("ingredients") or {}
    for k, item in ing.items():
        files = item.get("files") or []
        if files:
            out["urls"]["ingredients"][k] = [url_for(f) for f in files]

    steps = m.get("steps") or {}
    for k, item in steps.items():
        files = item.get("files") or []
        if files:
            out["urls"]["steps"][k] = [url_for(f) for f in files]

    return out
