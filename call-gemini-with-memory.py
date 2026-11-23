"""Chat loop that keeps a short in-memory conversation history.

The last MAX_TURNS question/answer pairs are injected into DEFAULT_PROMPT as
"User:" / "Assistant:" lines, so the model can refer to earlier turns.
History lives only in this process and is lost on exit.
"""

import time
from collections import deque

from google import genai
from google.genai import errors
from google.genai.types import HttpOptions

MODEL = "gemini-2.5-flash"
MAX_TURNS = 5
EXIT_COMMANDS = {"exit", "quit"}

DEFAULT_PROMPT = """You are a helpful assistant. Use the conversation so far to answer the user's latest message.

Conversation so far:
{history}

User: {question}
Assistant:"""

# Each entry is one turn: (user question, assistant answer). Oldest turns drop off automatically.
session_history: deque[tuple[str, str]] = deque(maxlen=MAX_TURNS)


def format_history(history) -> str:
    if not history:
        return "(no earlier messages)"
    lines = []
    for question, answer in history:
        lines.append(f"User: {question}")
        lines.append(f"Assistant: {answer}")
    return "\n".join(lines)


def build_prompt(question: str, history) -> str:
    return DEFAULT_PROMPT.format(history=format_history(history), question=question)


def main() -> None:
    client = genai.Client(
        api_key="unused",
        http_options=HttpOptions(api_version="v1", base_url="http://localhost:4000"),
    )

    print(f"Chat with memory of the last {MAX_TURNS} turns. Type 'exit' or 'quit' to stop.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in EXIT_COMMANDS:
            break

        start_time = time.time()
        first_chunk_time = None
        parts: list[str] = []
        print("Assistant: ", end="", flush=True)
        try:
            for chunk in client.models.generate_content_stream(
                model=MODEL,
                contents=build_prompt(question, session_history),
            ):
                text = chunk.text or ""
                if not parts:
                    text = text.lstrip()  # drop leading whitespace before the first word
                if not text:
                    continue
                if first_chunk_time is None:
                    first_chunk_time = time.time() - start_time
                parts.append(text)
                print(text, end="", flush=True)
        except errors.APIError as exc:
            # Can fail before or partway through the reply; don't record failed turns.
            print(f"\nError {exc.code} {exc.status}: {exc.message}")
            continue
        except KeyboardInterrupt:
            # Ctrl+C stops the current reply and returns to the prompt; the partial reply is not recorded.
            print("\n[reply interrupted, not saved to history]")
            continue
        print()

        answer = "".join(parts).strip()
        session_history.append((question, answer))
        first = f"first token {first_chunk_time:.2f}s, " if first_chunk_time is not None else ""
        print(f"({first}total {time.time() - start_time:.2f}s, {len(session_history)}/{MAX_TURNS} turns in memory)")


if __name__ == "__main__":
    main()
