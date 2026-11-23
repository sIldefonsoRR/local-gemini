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
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=build_prompt(question, session_history),
            )
        except errors.APIError as exc:
            # Don't record failed turns in the history.
            print(f"Error {exc.code} {exc.status}: {exc.message}")
            continue

        answer = (response.text or "").strip()
        session_history.append((question, answer))
        print(f"Assistant: {answer}")
        print(f"({time.time() - start_time:.2f}s, {len(session_history)}/{MAX_TURNS} turns in memory)")


if __name__ == "__main__":
    main()
