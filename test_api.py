import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from openai import (
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APIStatusError,
)


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH, override=True)


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required env variable: {name}")
    return value


def test_chat(client: OpenAI, model: str) -> None:
    response = client.responses.create(
        model=model,
        input="Reply with exactly: API_OK",
        max_output_tokens=30,
    )

    print("✅ GPT API works")
    print("Chat model:", model)
    print("Response:", response.output_text.strip())


def test_embedding(client: OpenAI, model: str) -> None:
    response = client.embeddings.create(
        model=model,
        input="This is a test embedding input.",
    )

    embedding = response.data[0].embedding

    print("\n✅ Embedding API works")
    print("Embedding model:", model)
    print("Embedding dimension:", len(embedding))
    print("First 5 values:", embedding[:5])


def main():
    try:
        api_key = required_env("OPENAI_API_KEY")
        chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.4-mini")
        embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

        if api_key.startswith("sk-proj-your"):
            raise ValueError("OPENAI_API_KEY is still a placeholder. Replace it with your real OpenAI API key.")

        client = OpenAI(api_key=api_key)

        test_chat(client, chat_model)
        test_embedding(client, embedding_model)

        print("\n✅ All OpenAI API tests passed")

    except AuthenticationError as e:
        print("❌ Authentication failed")
        print("Check your OPENAI_API_KEY.")
        print(e)

    except RateLimitError as e:
        print("❌ Rate limit or billing/quota issue")
        print("Check your OpenAI billing and usage limits.")
        print(e)

    except APIConnectionError as e:
        print("❌ Network connection issue")
        print(e)

    except APIStatusError as e:
        print(f"❌ OpenAI API returned status: {e.status_code}")
        print(e.response)

    except Exception as e:
        print("❌ Error")
        print(type(e).__name__, e)


if __name__ == "__main__":
    main()