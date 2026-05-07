from functools import lru_cache

from openai import OpenAI

from app.core.config import settings


@lru_cache
def get_openai_client() -> OpenAI:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing. Please set it in .env.")

    return OpenAI(api_key=settings.OPENAI_API_KEY)


def embed_query(text: str) -> list[float]:
    client = get_openai_client()

    response = client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding


def generate_text(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    client = get_openai_client()

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=settings.OPENAI_TEMPERATURE if temperature is None else temperature,
        max_tokens=settings.OPENAI_MAX_TOKENS if max_tokens is None else max_tokens,
    )

    return response.choices[0].message.content or ""