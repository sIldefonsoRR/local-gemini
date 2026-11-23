FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi uvicorn httpx
COPY gemini-bridge.py /app/gemini-bridge.py
WORKDIR /app
CMD ["uvicorn", "gemini-bridge:app", "--host", "0.0.0.0", "--port", "4000"]
