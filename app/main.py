from fastapi import FastAPI
from rq.job import Job

import os
import time
import requests

from app.models import RecipeIn, EnqueueResponse, JobStatus
from app.queue import get_queue, get_redis
from app.tasks import generate_assets_job

app = FastAPI(title="Recipe Media Generator (T2V)", version="2.1")


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
    # Inside docker network, API and worker talk to ollama at http://ollama:11434
    base = os.getenv("OLLAMA_URL", "").strip()
    if not base:
        return {"ok": False, "error": "OLLAMA_URL not set"}
    try:
        start = time.time()
        # /api/tags lists local models; lightweight for health check
        resp = requests.get(f"{base}/api/tags", timeout=3)
        ms = int((time.time() - start) * 1000)
        if resp.status_code != 200:
            return {"ok": False, "latency_ms": ms, "status_code": resp.status_code}
        data = resp.json()
        # Not requiring the model to be present, just that the service is responsive.
        return {"ok": True, "latency_ms": ms, "models_count": len(data.get("models", []))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/health")
def health():
    # Simple liveness probe
    return {"ok": True}


@app.get("/health-check")
def health_check():
    # Readiness-ish probe (checks key dependencies)
    redis_status = _check_redis()
    ollama_status = _check_ollama()

    overall_ok = bool(redis_status.get("ok")) and bool(ollama_status.get("ok"))
    return {
        "ok": overall_ok,
        "services": {
            "redis": redis_status,
            "ollama": ollama_status,
        }
    }


@app.post("/v1/recipes/assets", response_model=EnqueueResponse, status_code=202)
def enqueue_assets(recipe: RecipeIn):
    q = get_queue()
    job = q.enqueue(
        generate_assets_job,
        recipe.model_dump(by_alias=False),
        job_timeout="6h",
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
