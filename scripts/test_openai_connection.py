from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from labourcrew.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    print(f"Connecting with model: {settings.openai_chat_model}")
    response = client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": "Reply with exactly one word: pong"}],
        max_tokens=5,
    )

    print(f"Response: {response.choices[0].message.content.strip()}")
    print("OpenAI connection OK.")


if __name__ == "__main__":
    main()
