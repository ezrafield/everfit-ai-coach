from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4.1"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OPENAI_TEMPERATURE: float = 0.0
    OPENAI_MAX_TOKENS: int = 1000

    # Local RAG
    CHROMA_DIR: str = "./data/chroma"
    KB_DIR: str = "./data/kb"
    CHROMA_COLLECTION_NAME: str = "everfit_fitness_kb"

    # Chunking
    RAG_CHUNK_MAX_TOKENS: int = 700
    RAG_CHUNK_OVERLAP_TOKENS: int = 100
    EMBEDDING_BATCH_SIZE: int = 32

    # Retrieval
    RAG_TOP_K: int = 5
    RAG_MIN_RELEVANCE_SCORE: float = 0.25

    # Workout history
    WORKOUT_HISTORY_PATH: str = "./data/workout-history.json"

    # App
    APP_ENV: str = "local"
    DEBUG_MODE: bool = True
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()