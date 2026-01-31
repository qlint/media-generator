from fastapi import FastAPI
from rq.job import Job

from app.models import RecipeIn, EnqueueResponse, JobStatus
from app.queue import get_queue, get_redis
from app.tasks import generate_assets_job

app = FastAPI(title="Recipe Media Generator (T2V)", version="2.0")

@app.get("/health")
def health():
    return {"ok": True}

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
