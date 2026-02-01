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
