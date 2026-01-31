import os
import requests

def ollama_generate(system: str, prompt: str, timeout_s: int = 180) -> str:
    ollama = os.getenv("OLLAMA_URL", "").strip()
    model = os.getenv("LLM_MODEL", "phi4-mini:3.8b")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))

    if not ollama:
        raise RuntimeError("OLLAMA_URL not set")

    r = requests.post(
        f"{ollama}/api/generate",
        json={
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                # Ollama uses num_predict for token limit
                "num_predict": max_tokens,
            },
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    return (r.json().get("response") or "").strip()
