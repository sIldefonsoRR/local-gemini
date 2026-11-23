# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Local sandbox that runs Google Gen AI SDK (`google-genai`) code against a local LLM instead of Google Cloud. No real Gemini/Vertex calls are made.

Request flow:

```
call-gemini.py (google-genai client, base_url=http://localhost:4000, fake API key)
  → gemini-bridge (FastAPI, docker, :4000) — POST /v1/models/{model}:generateContent → Ollama /api/generate with $OLLAMA_MODEL
    → Ollama (docker, host :11500, reached as http://ollama:11434 inside compose network)
```

- `gemini-bridge.py` ignores the requested model name; the Ollama model comes from the `OLLAMA_MODEL` env var (default `llama3.2`, also defaulted in `docker-compose.yml` as `${OLLAMA_MODEL:-llama3.2}`). Swap models with `OLLAMA_MODEL=<model> docker compose up -d gemini-bridge` (or a `.env` file); no rebuild needed, but pull the model into Ollama first.
- The client uses `HttpOptions(api_version="v1", base_url=...)`, so the bridge routes must stay under `/v1/`. Implemented: `:generateContent` and `:streamGenerateContent` (SDK calls it with `?alt=sse`; bridge converts Ollama's NDJSON stream to `data: <json>\n\n` SSE events, `finishReason: STOP` on Ollama's `done` chunk). Only text parts are forwarded, joined into one prompt.
- Errors use the Gemini shape `{"error": {"code", "message", "status"}}`, which the SDK turns into `ClientError`/`ServerError`. Ollama's HTTP status is passed through (e.g. model not pulled → 404 NOT_FOUND); unreachable → 503, timeout → 504. The streaming route opens the Ollama stream before replying so up-front failures are real HTTP errors; errors after the 200 is sent go out as a `data: {"error": ...}` SSE event, which the SDK also raises.
- `OLLAMA_URL` uses the compose service hostname (`ollama`), not `localhost`.
- The bridge image is built from `Dockerfile` (its own deps: fastapi, uvicorn, httpx); `requirements.txt` is for the client only.

## Commands

```bash
# Start stack (rebuild after editing gemini-bridge.py)
docker compose up -d --build

# Pull the backing model into Ollama (required once; volume ollama_data persists it)
docker exec ollama ollama pull llama3.2

# Python env (venv already at .venv)
source .venv/bin/activate
pip install -r requirements.txt

# Run the scripts
python call-gemini.py              # one question, one answer
python call-gemini-with-memory.py  # streaming chat loop; last 5 turns injected into DEFAULT_PROMPT, in-memory only

# Debug bridge / model
docker logs -f gemini-bridge
curl http://localhost:11500/api/tags   # models available in Ollama
```

No tests, linter, or build step exist.
