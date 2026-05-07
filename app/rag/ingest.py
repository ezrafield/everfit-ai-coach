import hashlib
import re
from pathlib import Path
from typing import Iterable

import chromadb
import tiktoken
import typer
from loguru import logger
from openai import OpenAI
from rich.console import Console
from rich.table import Table
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.rag.schemas import DocumentChunk

app = typer.Typer(help="Ingest markdown fitness knowledge base into local Chroma.")
console = Console()


# -----------------------------
# Token helpers
# -----------------------------

def get_token_encoder(model_name: str):
    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model_name: str) -> int:
    encoder = get_token_encoder(model_name)
    return len(encoder.encode(text))


# -----------------------------
# Markdown loading / chunking
# -----------------------------

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def stable_chunk_id(
    source_path: str,
    section_title: str,
    chunk_index: int,
    text: str,
) -> str:
    raw = f"{source_path}|{section_title}|{chunk_index}|{text[:300]}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    stem = Path(source_path).stem
    return f"{stem}::{chunk_index:04d}::{digest}"


def split_markdown_by_headings(markdown_text: str) -> list[tuple[str, str]]:
    """
    Splits markdown by headings while preserving heading text inside each section.

    Returns:
        [(section_title, section_text), ...]
    """
    markdown_text = normalize_text(markdown_text)
    lines = markdown_text.split("\n")

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    sections: list[tuple[str, list[str]]] = []
    current_title = "Document"
    current_lines: list[str] = []

    for line in lines:
        match = heading_pattern.match(line)

        if match:
            if current_lines:
                sections.append((current_title, current_lines))

            current_title = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    cleaned_sections: list[tuple[str, str]] = []

    for title, section_lines in sections:
        section_text = normalize_text("\n".join(section_lines))
        if section_text:
            cleaned_sections.append((title, section_text))

    return cleaned_sections


def split_large_text_by_tokens(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    model_name: str,
) -> list[str]:
    encoder = get_token_encoder(model_name)
    tokens = encoder.encode(text)

    if len(tokens) <= max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = encoder.decode(chunk_tokens).strip()

        if chunk_text:
            chunks.append(chunk_text)

        if end >= len(tokens):
            break

        start = max(0, end - overlap_tokens)

    return chunks


def chunk_markdown_file(
    file_path: Path,
    kb_root: Path,
    max_tokens: int,
    overlap_tokens: int,
    model_name: str,
) -> list[DocumentChunk]:
    raw_text = file_path.read_text(encoding="utf-8")
    relative_path = str(file_path.relative_to(kb_root))
    doc_name = file_path.name

    sections = split_markdown_by_headings(raw_text)

    chunks: list[DocumentChunk] = []
    global_chunk_index = 0

    for section_title, section_text in sections:
        section_chunks = split_large_text_by_tokens(
            text=section_text,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            model_name=model_name,
        )

        for chunk_text in section_chunks:
            token_count = count_tokens(chunk_text, model_name)
            chunk_id = stable_chunk_id(
                source_path=relative_path,
                section_title=section_title,
                chunk_index=global_chunk_index,
                text=chunk_text,
            )

            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    text=chunk_text,
                    doc_name=doc_name,
                    source_path=relative_path,
                    section_title=section_title,
                    chunk_index=global_chunk_index,
                    token_count=token_count,
                )
            )

            global_chunk_index += 1

    return chunks


def load_and_chunk_kb(
    kb_dir: str,
    max_tokens: int,
    overlap_tokens: int,
    model_name: str,
) -> list[DocumentChunk]:
    kb_root = Path(kb_dir)

    if not kb_root.exists():
        raise FileNotFoundError(f"Knowledge base directory not found: {kb_root}")

    markdown_files = sorted(kb_root.rglob("*.md"))

    if not markdown_files:
        raise FileNotFoundError(f"No markdown files found in: {kb_root}")

    all_chunks: list[DocumentChunk] = []

    for file_path in markdown_files:
        file_chunks = chunk_markdown_file(
            file_path=file_path,
            kb_root=kb_root,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            model_name=model_name,
        )

        logger.info(f"Chunked {file_path.name}: {len(file_chunks)} chunks")
        all_chunks.extend(file_chunks)

    return all_chunks


# -----------------------------
# Embedding / Chroma
# -----------------------------

def batched(items: list, batch_size: int) -> Iterable[list]:
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
)
def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def get_or_create_chroma_collection(reset: bool):
    chroma_dir = Path(settings.CHROMA_DIR)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(chroma_dir))

    if reset:
        try:
            client.delete_collection(settings.CHROMA_COLLECTION_NAME)
            logger.info(f"Deleted existing collection: {settings.CHROMA_COLLECTION_NAME}")
        except Exception:
            logger.info("No existing collection found. Creating a new one.")

    collection = client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        metadata={
            "description": "Everfit fitness knowledge base",
            "embedding_model": settings.OPENAI_EMBEDDING_MODEL,
        },
    )

    return collection


def print_ingestion_summary(chunks: list[DocumentChunk]) -> None:
    by_doc: dict[str, int] = {}

    for chunk in chunks:
        by_doc[chunk.doc_name] = by_doc.get(chunk.doc_name, 0) + 1

    table = Table(title="RAG Ingestion Summary")
    table.add_column("Document", style="cyan")
    table.add_column("Chunks", justify="right")

    for doc_name, count in sorted(by_doc.items()):
        table.add_row(doc_name, str(count))

    console.print(table)
    console.print(f"[bold green]Total chunks:[/bold green] {len(chunks)}")


@app.command()
def main(
    kb_dir: str = typer.Option(
        settings.KB_DIR,
        "--kb-dir",
        help="Path to markdown knowledge base directory.",
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Delete existing Chroma collection before ingestion.",
    ),
):
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing. Please set it in .env.")

    logger.info(f"Loading markdown knowledge base from: {kb_dir}")
    logger.info(f"Embedding model: {settings.OPENAI_EMBEDDING_MODEL}")
    logger.info(f"Chroma directory: {settings.CHROMA_DIR}")

    chunks = load_and_chunk_kb(
        kb_dir=kb_dir,
        max_tokens=settings.RAG_CHUNK_MAX_TOKENS,
        overlap_tokens=settings.RAG_CHUNK_OVERLAP_TOKENS,
        model_name=settings.OPENAI_EMBEDDING_MODEL,
    )

    if not chunks:
        raise RuntimeError("No chunks generated from knowledge base.")

    print_ingestion_summary(chunks)

    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    collection = get_or_create_chroma_collection(reset=reset)

    total_inserted = 0

    for batch in batched(chunks, settings.EMBEDDING_BATCH_SIZE):
        texts = [chunk.text for chunk in batch]
        ids = [chunk.id for chunk in batch]

        metadatas = [
            {
                "doc_name": chunk.doc_name,
                "source_path": chunk.source_path,
                "section_title": chunk.section_title,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
            }
            for chunk in batch
        ]

        embeddings = embed_texts(openai_client, texts)

        collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        total_inserted += len(batch)
        logger.info(f"Inserted {total_inserted}/{len(chunks)} chunks")

    console.print(
        f"[bold green]Ingestion completed.[/bold green] "
        f"Collection='{settings.CHROMA_COLLECTION_NAME}', "
        f"PersistDir='{settings.CHROMA_DIR}', "
        f"TotalChunks={len(chunks)}"
    )


if __name__ == "__main__":
    app()