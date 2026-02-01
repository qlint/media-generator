# Installation Guide — Recipe Media T2V

This project generates **ingredient images** and **step images/videos** from recipe text.

- **API** returns immediately (HTTP **202**) and enqueues background work.
- Background workers generate assets into `./assets/<recipe_id>/{ingredients,steps}/`.
- **Observability dashboard**: RQ Dashboard.

---

## 1) Prerequisites

### Required
- Docker + Docker Compose (Compose v2 recommended)

### Strongly recommended
- NVIDIA GPU + drivers + NVIDIA Container Toolkit (for SDXL + LTX-Video speed)

> You *can* run CPU-only, but generation will be extremely slow.

---

## 2) Start the stack (single command)

From the project root:

```bash
docker compose up --build
```

This starts:
- FastAPI on `http://localhost:8000`
- RQ Dashboard on `http://localhost:9181` (built locally; no Docker Hub image pull)
- Redis queue (host port **6380** → container 6379)
- Ollama LLM server (host port **11435** → container 11434)

### Model pulling happens automatically (via Ollama HTTP API)
On first boot, a one-shot container `ollama-init` waits for Ollama's **HTTP API** (`GET /api/tags`) to be ready, then pulls the planner model defined by `LLM_MODEL` in `.env` (default: `phi4-mini:3.8b`) using `POST /api/pull`. It also checks whether the model is already present to avoid re-downloading.  
No extra commands are required.

---

## 3) Generate assets (POST endpoint)

Open FastAPI docs:
- `http://localhost:8000/docs`

Or call via curl:

```bash
curl -X POST http://localhost:8000/v1/recipes/assets \
  -H "Content-Type: application/json" \
  -d @examples/sample_request.json
```

You will get an immediate response like:

```json
{ "job_id": "...", "status_url": "/v1/jobs/..." }
```

Check status:

```bash
curl http://localhost:8000/v1/jobs/<job_id>
```

Monitor queue/jobs/workers in your browser:
- `http://localhost:9181`

---

## 4) Output structure

Assets are written to:

```
./assets/<id>/
  ingredients/
    0.png
    1.png
    ...
  steps/
    0.png   (if image step)
    1.mp4   (if video step)
    1.png   (cover image for video step)
    ...
```

- Ingredient filenames are the ingredient index.
- Step filenames are the step index.

---

## 5) Configuration

Edit `.env`:

- `LLM_MODEL` defaults to `phi4-mini:3.8b`
- `VIDEO_MODEL` defaults to `Lightricks/LTX-Video`
- `DEVICE=cuda` recommended

---

## 6) Notes on first run

The first run downloads:
- Ollama planner model (via `ollama-init`)
- SDXL + LTX-Video models into the `hf_cache` volume

This can take time depending on bandwidth.

---

## 7) Troubleshooting

### GPU not detected
- Ensure you can run:
  ```bash
  docker run --rm --gpus all nvidia/cuda:12.1.0-runtime-ubuntu22.04 nvidia-smi
  ```
- If that fails, install NVIDIA Container Toolkit.

### Out of memory (OOM)
- Reduce generation sizes in `.env`:
  - lower `VIDEO_BASE_WIDTH/HEIGHT`
  - lower `VIDEO_INFERENCE_STEPS`
  - lower `IMAGE_WIDTH/HEIGHT` (but keep >= 300)

### Port conflicts
This project maps:
- Redis → `localhost:6380`
- Ollama → `localhost:11435`

If those are still in use on your VPS, change them in `docker-compose.yml`.

### CPU-only run
Set `DEVICE=cpu` in `.env` and run:
```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
```

---

## 8) Stop the stack

```bash
docker compose down
```


### RQ Dashboard binding note
The dashboard is configured using environment variables inside its container (`RQ_DASHBOARD_BIND=0.0.0.0`, `RQ_DASHBOARD_PORT=9181`, `RQ_DASHBOARD_REDIS_URL=redis://redis:6379/0`) to ensure it is reachable from outside the container.


## Health checks
- Liveness: `GET /health`
- Dependency check (Redis + Ollama): `GET /health-check`

Example:
```bash
curl http://localhost:8000/health-check
```
