import json
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
OLLAMA_URL = "http://ollama:11434/api/generate"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL") or "llama3.2"

# HTTP status -> Google API status string, as used in Gemini error bodies.
GOOGLE_STATUS = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "ABORTED",
    429: "RESOURCE_EXHAUSTED",
    499: "CANCELLED",
    500: "INTERNAL",
    501: "UNIMPLEMENTED",
    503: "UNAVAILABLE",
    504: "DEADLINE_EXCEEDED",
}


def extract_prompt(body: dict) -> str:
    """Join all text parts from a Gemini SDK payload into one prompt."""
    prompt_parts = []
    for content in body.get("contents", []):
        for part in content.get("parts", []):
            if "text" in part:
                prompt_parts.append(part["text"])
    return "\n".join(prompt_parts)


def gemini_response(text: str, finish_reason: str | None = None) -> dict:
    """Build a response shaped like the google-genai SDK expects."""
    candidate = {"content": {"parts": [{"text": text}], "role": "model"}}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    return {"candidates": [candidate]}


def gemini_error(code: int, message: str) -> dict:
    """Build a Gemini-style error body; the SDK raises ClientError/ServerError from it."""
    if code not in GOOGLE_STATUS:
        code = 500 if code >= 500 or code < 400 else 400
    return {"error": {"code": code, "message": message, "status": GOOGLE_STATUS[code]}}


def error_response(code: int, message: str) -> JSONResponse:
    body = gemini_error(code, message)
    return JSONResponse(body, status_code=body["error"]["code"])


def ollama_error_message(raw: bytes | str) -> str:
    """Pull the message out of an Ollama error body ({"error": "..."}), else return it raw."""
    text = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text or "Unknown Ollama error"
    if isinstance(data, dict) and data.get("error"):
        return f"Ollama: {data['error']}"
    return text


def ollama_request(prompt: str, stream: bool) -> dict:
    return {"model": OLLAMA_MODEL, "prompt": prompt, "stream": stream}


@app.post("/v1/models/{model}:generateContent")
async def generate_content(model: str, request: Request):
    prompt = extract_prompt(await request.json())

    # Forward to Ollama (any requested model is served by OLLAMA_MODEL)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(OLLAMA_URL, json=ollama_request(prompt, False))
    except httpx.TimeoutException as exc:
        return error_response(504, f"Ollama timed out: {exc!r}")
    except httpx.HTTPError as exc:
        return error_response(503, f"Ollama unreachable at {OLLAMA_URL}: {exc!r}")

    if resp.status_code != 200:
        return error_response(resp.status_code, ollama_error_message(resp.content))

    ollama_data = resp.json()
    if ollama_data.get("error"):
        return error_response(500, ollama_error_message(resp.content))

    return gemini_response(ollama_data.get("response", ""), "STOP")


@app.post("/v1/models/{model}:streamGenerateContent")
async def stream_generate_content(model: str, request: Request):
    prompt = extract_prompt(await request.json())

    # Open the Ollama stream before replying, so failures that happen up front
    # (unreachable, model not pulled) become a normal HTTP error response.
    client = httpx.AsyncClient(timeout=120.0)
    try:
        resp = await client.send(
            client.build_request("POST", OLLAMA_URL, json=ollama_request(prompt, True)),
            stream=True,
        )
    except httpx.TimeoutException as exc:
        await client.aclose()
        return error_response(504, f"Ollama timed out: {exc!r}")
    except httpx.HTTPError as exc:
        await client.aclose()
        return error_response(503, f"Ollama unreachable at {OLLAMA_URL}: {exc!r}")

    if resp.status_code != 200:
        body = await resp.aread()
        await resp.aclose()
        await client.aclose()
        return error_response(resp.status_code, ollama_error_message(body))

    async def events():
        # Ollama streams newline-delimited JSON; the SDK (alt=sse) expects
        # server-sent events: one "data: <json>" line per chunk, blank line after.
        # The 200 is already sent here, so errors go out as a "data: {"error": ...}"
        # event, which the SDK raises as an APIError.
        try:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    yield f"data: {json.dumps(gemini_error(500, ollama_error_message(line)))}\n\n"
                    return
                finish = "STOP" if chunk.get("done") else None
                payload = gemini_response(chunk.get("response", ""), finish)
                yield f"data: {json.dumps(payload)}\n\n"
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps(gemini_error(503, f'Ollama stream failed: {exc!r}'))}\n\n"
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(events(), media_type="text/event-stream")
