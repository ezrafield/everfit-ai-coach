from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    text: str
    doc_name: str
    source_path: str
    section_title: str
    chunk_index: int
    token_count: int


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    text: str
    score: float | None
    metadata: dict[str, Any]


class RagAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=10)


class SourceReference(BaseModel):
    chunk_id: str
    doc_name: str
    source_path: str
    section_title: str
    chunk_index: int
    score: float | None = None


class RagAskResponse(BaseModel):
    answer: str
    sources: list[SourceReference] = []
    refusal: bool = False
    refusal_reason: str | None = None