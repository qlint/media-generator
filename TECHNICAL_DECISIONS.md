# Technical Decisions

## 1) Asynchronous processing + observability

**Decision:** Redis + RQ + RQ Dashboard  
**Why:**  
- The API must respond immediately while heavy generation runs in the background.
- RQ is simple, reliable, and lightweight for Python.
- RQ Dashboard provides a browser UI showing queues, jobs, runtimes, failures, and workers.

## 1b) RQ Dashboard container image

**Decision:** Build the RQ Dashboard container locally (via `Dockerfile.rq-dashboard`) and configure it via `RQ_DASHBOARD_*` environment variables.  
**Why:**  
- Some third-party Docker Hub images may be missing/renamed or require authentication.  
- Building from the upstream Python package (`rq-dashboard`) is deterministic and works with a single `docker compose up --build`.

## 2) Single-command deployment on VPS

**Decision:** Add an `ollama-init` one-shot container in Docker Compose that pulls the planner model automatically.  
**Why:**  
- VPS deployments benefit from **one command** (`docker compose up --build`) with no manual post-steps.
- The init container waits until Ollama's **HTTP API** is reachable (`/api/tags`), pulls `LLM_MODEL` via `/api/pull`, and exits successfully.
- Models are stored in the persistent `ollama` volume so subsequent restarts do not re-download.

## 3) Port conflict avoidance for shared VPS

**Decision:** Map Redis and Ollama to alternative host ports.  
**Why:**  
- On shared VPS environments, host ports `6379` and `11434` are often already in use.
- This project maps:
  - Redis container port 6379 → host **6380**
  - Ollama container port 11434 → host **11435**
- Internal service-to-service traffic uses Docker networking (`redis:6379`, `ollama:11434`). The `ollama` container is explicitly set to `OLLAMA_HOST=0.0.0.0:11434` so it listens on all interfaces inside the container, ensuring other containers can reach it.

## 4) LLM choice: phi4-mini in Ollama

**Decision:** Use `phi4-mini` via Ollama for:
- step rewording/formatting
- media type classification (image vs video)
- storyboard/shot list generation
- prompt authoring with constraints (lighting, background, no watermark)

**Why:**
- Local, free model execution with a stable HTTP API.
- Strong instruction-following for structured JSON outputs and consistent prompt style.

Fallback behavior:
- If Ollama is unavailable or parsing fails, the system falls back to heuristic classification and simple prompts.

## 5) Step rewording before planning

**Decision:** Reword recipe steps into cleaner, action-oriented instructions before video planning.

**Why:**
- Raw recipe text is often inconsistent in tense, detail, or clarity.
- Video prompts benefit from explicit subject/action/object phrasing.
- Rewording also improves step classification (passive vs active) and makes shot decomposition easier.

The rewriter runs in chunks to support recipes with many steps.

## 6) Video generation: text-to-video (LTX-Video)

**Decision:** Use LTX-Video in Diffusers (`LTXPipeline`) for **text-to-video**.

**Why:**
- Pure image-to-video often struggles to introduce new objects or state changes.
- Text-to-video is more appropriate for multi-action steps.
- LTX-Video has Diffusers integration for local Python usage.

## 7) 1080p requirement

**Decision:** Generate at a model-friendly base resolution and encode a 1080p output.

**Why:**
- Many open T2V models generate best at specific native resolutions.
- Upscaling at encode-time reliably outputs 1920×1080 (no audio) while keeping generation stable.
- The pipeline uses ffmpeg to scale and encode with H.264.

## 8) Storyboarding / shot list per step

**Decision:** For each “video step”, the planner emits 1–3 **shots** (prompts + durations).

**Why:**
- Complex steps often contain multiple actions.
- Decomposing a step yields more accurate and controllable video outputs.
- Each shot is generated as a short clip and concatenated.

## 9) Professional visual constraints

All prompts enforce:
- professional, well-lit, minimal clutter
- no text, no watermarks/logos
- clean framing (overhead/45°) appropriate for cooking actions
- no audio in final output videos

## 10) Containerization

**Decision:** Docker Compose stack with isolated services.

**Why:**
- Reproducibility and easier deployment.
- Separates API, worker, queue, dashboard, and LLM runtime.
- Model caches persisted using Docker volumes.


## GPU optionality
**Decision:** Keep GPU usage optional via `docker-compose.gpu.yml`.
**Why:**
- Many VPS environments have no GPU; forcing `gpus: all` causes Docker to error.
- The default stack runs on CPU without special drivers.
- GPU can be enabled with a single command using an override compose file.


## Compose variable expansion in init scripts
**Decision:** Escape shell variables in `docker-compose.yml` init scripts using `$$`.
**Why:**
- Docker Compose performs its own variable expansion on `$VAR`/`${VAR}`.
- Using `$$VAR` ensures the shell in the container receives `$VAR` as intended.


## Dependency pinning for stability
**Decision:** Pin `numpy==1.26.4` and `transformers==4.44.2`.
**Why:**
- Some prebuilt ML base images ship with NumPy 2.x, which can break binary extensions compiled against NumPy 1.x.
- Diffusers 0.32.x expects `FLAX_WEIGHTS_NAME` from Transformers; newer Transformers releases removed it.
- Pinning avoids runtime import/ABI issues on fresh VPS deployments.


## Resumability and idempotent generation
**Decision:** Checkpoint generation with a per-recipe `manifest.json` and deterministic filenames.
**Why:**
- If a long-running job fails mid-way, re-running should not waste time regenerating completed assets.
- Deterministic output paths allow simple file-existence checks to skip completed work.
- Manifest provides observability (what was generated, what failed) and powers an API endpoint to list asset URLs.


## Serving assets over HTTP
**Decision:** Mount the assets directory using FastAPI `StaticFiles` at `/assets`.
**Why:**
- Simple, zero additional infrastructure.
- Works well behind a reverse proxy (nginx/caddy) on a VPS.
- Keeps asset URLs stable and directly derivable from `{id}/{index}`.


## Recipe categorizer queue and DB-first taxonomy
- Added a separate RQ queue `recipe-categorizer` to isolate classification workloads from media generation.
- Scheduler polls every 10 minutes and enqueues unprocessed recipes in batches (default 10).
- Category definitions are loaded dynamically from `app.broad_categories` (no hard-coded IDs), allowing future extension without code changes.
- Classification uses:
  1. heuristic priors (time, thermal intensity, satiety, overlap rules),
  2. ingredient archetype map, and
  3. Ollama LLM finalization with strict allowed-category constraints.
- Persistence is idempotent: relation rows for a recipe are replaced atomically and `processed_categories` is set to true.
