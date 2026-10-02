"""Shared MiniLM embedder: one model per process, used by ingest and by query.

Model is always src.config.EMBEDDING_MODEL (384-d) for both chunks and questions,
so ingest (Stage A) and query (Stage B) must call this module and nothing else.

Also owns the data/embeddings.txt dump, so the vectors handed to ChromaDB can be
inspected in an editor next to data/chunks.txt (FR-2).
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from math import sqrt
from typing import TYPE_CHECKING, Any, List, Sequence

from src.config import EMBEDDING_DIM, EMBEDDING_MODEL, EMBEDDINGS_TXT_PATH

if TYPE_CHECKING:
    from src.chunking import Chunk

VALUE_PRECISION = 6
VALUES_PER_LINE = 8
PREVIEW_DIMS = 8


@lru_cache(maxsize=1)
def get_model() -> Any:
    """Load MiniLM once per process (slow: ~90 MB model download on first run)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """Embed chunks or a question; returns one L2-normalized 384-d vector per text."""
    texts = [str(text) for text in texts]
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=32,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    if int(vectors.shape[1]) != EMBEDDING_DIM:
        raise ValueError(
            f"{EMBEDDING_MODEL} returned {vectors.shape[1]}-d vectors, expected {EMBEDDING_DIM}"
        )
    return [[float(value) for value in row] for row in vectors]


def _format_value(value: float) -> str:
    return f"{value:.{VALUE_PRECISION}f}"


def _vector_lines(vector: Sequence[float]) -> List[str]:
    return [
        f"dim {start:>3}-{start + len(group) - 1:>3}: "
        + " ".join(_format_value(value) for value in group)
        for start, group in (
            (i, vector[i : i + VALUES_PER_LINE])
            for i in range(0, len(vector), VALUES_PER_LINE)
        )
    ]


def format_embeddings_txt(
    chunks: Sequence["Chunk"], vectors: Sequence[Sequence[float]], embedded_at: str
) -> str:
    """Render chunk text + its exact stored vector, mirroring chunks.txt layout."""
    if len(chunks) != len(vectors):
        raise ValueError(f"got {len(chunks)} chunks but {len(vectors)} vectors")
    norms = [sqrt(sum(value * value for value in vector)) for vector in vectors]
    dims = "/".join(str(dim) for dim in sorted({len(vector) for vector in vectors}))
    norm_summary = (
        f"min/avg/max: {min(norms):.{VALUE_PRECISION}f}/"
        f"{sum(norms) / len(norms):.{VALUE_PRECISION}f}/"
        f"{max(norms):.{VALUE_PRECISION}f}"
        if norms
        else "n/a (no vectors)"
    )
    lines = [
        "# HDFC Mutual Fund FAQ embeddings (Groww corpus, Phase 3)",
        f"# embedded_at: {embedded_at}",
        f"# model: {EMBEDDING_MODEL} | dim: {dims} | normalized: L2 | chroma space: cosine",
        f"# vectors: {len(vectors)} | l2_norm {norm_summary}",
        f"# values rounded to {VALUE_PRECISION} decimals; chunk ids match "
        "data/chunks.txt and the ChromaDB ids.",
        "# fields: metadata + text are copied from the chunk; vector is stored as shown.",
        "",
    ]
    for chunk, vector, norm in zip(chunks, vectors, norms):
        preview = vector[:PREVIEW_DIMS]
        lines.extend(
            [
                f"--- chunk_id: {chunk.chunk_id} ---",
                f"scheme: {chunk.scheme_name}",
                f"category: {chunk.category}",
                f"source_url: {chunk.source_url}",
                f"section: {chunk.section}",
                f"chars: {chunk.char_count}",
                f"dim: {len(vector)}",
                f"l2_norm: {_format_value(norm)}",
                f"first_{PREVIEW_DIMS}: " + " ".join(_format_value(v) for v in preview),
                "",
                "vector:",
            ]
        )
        lines.extend(f"  {line}" for line in _vector_lines(vector))
        lines.extend(["", f"text: {chunk.text}", ""])
    return "\n".join(lines)


def write_embeddings_txt(
    chunks: Sequence["Chunk"],
    vectors: Sequence[Sequence[float]],
    embedded_at: str = "",
) -> str:
    EMBEDDINGS_TXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = embedded_at or date.today().isoformat()
    EMBEDDINGS_TXT_PATH.write_text(
        format_embeddings_txt(chunks, vectors, stamp), encoding="utf-8"
    )
    return str(EMBEDDINGS_TXT_PATH)