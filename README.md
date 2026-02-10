# Recipe Media Generator (Text-to-Video)

See:
- `INSTALLATION_GUIDE.md`
- `TECHNICAL_DECISIONS.md`

Single command:

```bash
docker compose up --build
```

Quick links:
- API docs: http://localhost:8000/docs
- RQ Dashboard: http://localhost:9181 (built locally)
- Redis (host-mapped): localhost:6380
- Ollama (host-mapped): localhost:11435


Health:
- http://localhost:8000/health
- http://localhost:8000/health-check


Notes:
- `ollama-init` automatically pulls the model defined by `LLM_MODEL` (default `phi4-mini:3.8b`) before the API/worker start.


GPU (optional):
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```


Watch Ollama model pull progress:
```bash
docker compose logs -f ollama-init
```


Notes:
- Requirements pin `numpy==1.26.4` and `transformers==4.44.2` for runtime compatibility.


Resumability:
- If a job fails, POST again with the same `id`. Existing assets are skipped and generation resumes.


Access assets:
- http://localhost:8000/assets/<id>/ingredients/0.png
- http://localhost:8000/assets/<id>/steps/0.png
- http://localhost:8000/assets/<id>/steps/1.mp4
- Manifest + URLs: http://localhost:8000/v1/recipes/<id>/assets


## New: Recipe Categorizer Queue
- Queue name: `recipe-categorizer`
- Scheduler service polls DB every 10 minutes and enqueues at least 10 unprocessed recipes (if available)
- Worker classifies into dynamic broad categories from `app.broad_categories`
- Saves relations into `app.recipe_broad_categories` and sets `app.recipes.processed_categories=true`
