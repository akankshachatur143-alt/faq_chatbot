"""Ingest CLI (Stage A): load pages -> chunk -> embed (MiniLM) -> persist to ChromaDB.

Run once from the repo root:

    py -3 -m src.ingest               # reuse data/raw, chunk, embed, persist to data/chroma/
    py -3 -m src.ingest --refetch     # re-fetch the five URLs first
    py -3 -m src.ingest --skip-embed  # load + chunk only (no model download)

Importing this module has no side effects: nothing here runs on `import`.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from typing import Any, List, Sequence

from src.chunking import Chunk, chunk_corpus, summarize, write_chunks_txt
from src.config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    EMBEDDINGS_TXT_PATH,
    INGEST_META_PATH,
)
from src.embeddings import embed_texts, write_embeddings_txt
from src.load import load_all, print_summary

COLLECTION_METADATA = {
    "hnsw:space": "cosine",
    "embedding_model": EMBEDDING_MODEL,
    "embedding_dim": EMBEDDING_DIM,
    "source": "groww.in",
}


def chunk_stage(refetch: bool = False) -> tuple:
    meta = load_all(refetch=refetch)
    chunks, pages = chunk_corpus()
    write_chunks_txt(chunks, meta["fetched_at"])

    meta["phase"] = 2
    meta["chunked_at"] = date.today().isoformat()
    meta["chunked_at_utc"] = datetime.now(timezone.utc).isoformat()
    meta["chunk_count"] = len(chunks)
    meta["total_chunk_chars"] = sum(c.char_count for c in chunks)
    for page, chunked in zip(meta["pages"], pages):
        page["chunk_count"] = chunked["chunk_count"]
        page["sections_kept"] = chunked["sections_kept"]
        page["sections_dropped"] = chunked["sections_dropped"]
    INGEST_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta, chunks, pages


def open_client() -> Any:
    """Persistent Chroma client on disk; shared path with the query app (Phase 4)."""
    import chromadb
    from chromadb.config import Settings

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
    )


def embed_store_stage(chunks: Sequence[Chunk], embedded_at: str = "") -> int:
    """Embed chunks with MiniLM, upsert them, and dump the vectors; returns the stored count."""
    if not chunks:
        raise SystemExit("no chunks to embed: run without --skip-embed after loading data/raw")

    stamp = embedded_at or date.today().isoformat()
    embeddings: List[List[float]] = embed_texts([chunk.text for chunk in chunks])

    client = open_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except ValueError:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,
        metadata=dict(COLLECTION_METADATA),
    )
    collection.upsert(
        ids=[str(chunk.chunk_id) for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=[chunk.to_metadata() for chunk in chunks],
        embeddings=embeddings,
    )
    write_embeddings_txt(chunks, embeddings, stamp)
    return int(collection.count())


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest the five Groww pages: chunk, embed, persist to ChromaDB."
    )
    parser.add_argument(
        "--refetch", action="store_true", help="re-fetch the URLs instead of using data/raw"
    )
    parser.add_argument(
        "--skip-embed", action="store_true", help="only load and chunk (no model download)"
    )
    args = parser.parse_args(argv)

    meta, chunks, pages = chunk_stage(refetch=args.refetch)
    print_summary(meta)
    print("--- chunk stage ---")
    summarize(chunks, pages)

    if args.skip_embed:
        meta["phase"] = 2
        meta["chroma_written"] = False
        INGEST_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print("--- embed stage skipped (--skip-embed) ---")
        return

    print(f"--- embed stage: {EMBEDDING_MODEL} ({EMBEDDING_DIM}-d) ---")
    embedded_at = date.today().isoformat()
    count = embed_store_stage(chunks, embedded_at)

    meta["phase"] = 3
    meta["chroma_written"] = True
    meta["chroma_dir"] = str(CHROMA_DIR.relative_to(CHROMA_DIR.parent.parent))
    meta["collection_name"] = COLLECTION_NAME
    meta["collection_count"] = count
    meta["embedding_model"] = EMBEDDING_MODEL
    meta["embedding_dim"] = EMBEDDING_DIM
    meta["embeddings_txt"] = str(EMBEDDINGS_TXT_PATH.relative_to(EMBEDDINGS_TXT_PATH.parent.parent))
    meta["embedded_at"] = embedded_at
    meta["embedded_at_utc"] = datetime.now(timezone.utc).isoformat()
    INGEST_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"stored {count} chunks in {CHROMA_DIR} (collection '{COLLECTION_NAME}')")
    print(f"wrote {EMBEDDINGS_TXT_PATH}")


if __name__ == "__main__":
    main()