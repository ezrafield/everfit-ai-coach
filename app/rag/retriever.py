from typing import Any

import chromadb
from loguru import logger

from app.core.config import settings
from app.core.guardrails import check_rag_guardrails
from app.core.llm import embed_query, generate_text
from app.rag.schemas import RagAskResponse, RetrievedChunk, SourceReference


RAG_SYSTEM_PROMPT = """
You are an AI Workout Coach assistant for a fitness coaching platform.

Your job:
- Answer only using the provided retrieved knowledge base context.
- Be practical, concise, and coach-friendly.
- Cite source references naturally by mentioning document names or section titles when helpful.
- Do not invent facts that are not supported by the retrieved context.
- If the context is insufficient, say what is missing and give a limited answer.
- Do not provide medical diagnosis, injury treatment, or unsafe nutrition advice.
""".strip()


def get_chroma_collection():
    client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
    return client.get_collection(settings.CHROMA_COLLECTION_NAME)


def distance_to_relevance_score(distance: float | None) -> float | None:
    """
    Chroma distances are lower when more similar.
    Convert distance into a simple 0..1-ish relevance score for display/filtering.

    This is not a mathematically perfect similarity score, but it is useful
    as a stable practical threshold for the take-home assignment.
    """
    if distance is None:
        return None

    return 1.0 / (1.0 + max(distance, 0.0))


def retrieve_chunks(question: str, top_k: int | None = None) -> list[RetrievedChunk]:
    collection = get_chroma_collection()
    query_embedding = embed_query(question)

    n_results = top_k or settings.RAG_TOP_K

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    chunks: list[RetrievedChunk] = []

    for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
        score = distance_to_relevance_score(distance)

        chunks.append(
            RetrievedChunk(
                id=chunk_id,
                text=text,
                score=score,
                metadata=metadata or {},
            )
        )

    return chunks


def filter_relevant_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    filtered: list[RetrievedChunk] = []

    for chunk in chunks:
        if chunk.score is None:
            filtered.append(chunk)
            continue

        if chunk.score >= settings.RAG_MIN_RELEVANCE_SCORE:
            filtered.append(chunk)

    return filtered


def build_context(chunks: list[RetrievedChunk]) -> str:
    context_blocks: list[str] = []

    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata

        doc_name = metadata.get("doc_name", "unknown_document")
        section_title = metadata.get("section_title", "unknown_section")
        chunk_index = metadata.get("chunk_index", "unknown_chunk")

        context_blocks.append(
            "\n".join(
                [
                    f"[Source {index}]",
                    f"Document: {doc_name}",
                    f"Section: {section_title}",
                    f"Chunk Index: {chunk_index}",
                    f"Chunk ID: {chunk.id}",
                    "Content:",
                    chunk.text,
                ]
            )
        )

    return "\n\n---\n\n".join(context_blocks)


def build_rag_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context = build_context(chunks)

    return f"""
Question:
{question}

Retrieved knowledge base context:
{context}

Instructions:
- Answer the question using only the retrieved context.
- If the retrieved context is weak or incomplete, say so clearly.
- Include concrete training guidance only when supported by the context.
- Keep the answer useful for a fitness coach or client.
""".strip()


def chunks_to_source_references(chunks: list[RetrievedChunk]) -> list[SourceReference]:
    sources: list[SourceReference] = []

    for chunk in chunks:
        metadata: dict[str, Any] = chunk.metadata

        sources.append(
            SourceReference(
                chunk_id=chunk.id,
                doc_name=str(metadata.get("doc_name", "")),
                source_path=str(metadata.get("source_path", "")),
                section_title=str(metadata.get("section_title", "")),
                chunk_index=int(metadata.get("chunk_index", 0)),
                score=chunk.score,
            )
        )

    return sources


def ask_rag(question: str, top_k: int | None = None) -> RagAskResponse:
    guardrail_result = check_rag_guardrails(question)

    if not guardrail_result.allowed:
        return RagAskResponse(
            answer=guardrail_result.message or "I can’t answer that request.",
            sources=[],
            refusal=True,
            refusal_reason=guardrail_result.reason,
        )

    try:
        retrieved_chunks = retrieve_chunks(question=question, top_k=top_k)
    except Exception as exc:
        logger.exception("RAG retrieval failed")

        return RagAskResponse(
            answer=(
                "I could not search the fitness knowledge base right now. "
                "Please make sure the RAG ingestion has been run and the Chroma collection exists."
            ),
            sources=[],
            refusal=True,
            refusal_reason="retrieval_error",
        )

    relevant_chunks = filter_relevant_chunks(retrieved_chunks)

    if not relevant_chunks:
        return RagAskResponse(
            answer=(
                "I could not find enough relevant information in the fitness knowledge base to answer this. "
                "Please ask a question about exercise technique, training principles, workout programming, "
                "recovery, or nutrition basics."
            ),
            sources=[],
            refusal=True,
            refusal_reason="insufficient_retrieval",
        )

    user_prompt = build_rag_user_prompt(question=question, chunks=relevant_chunks)
    answer = generate_text(
        system_prompt=RAG_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    return RagAskResponse(
        answer=answer,
        sources=chunks_to_source_references(relevant_chunks),
        refusal=False,
        refusal_reason=None,
    )