"""Stage B (Phase 4): question -> guardrails -> MiniLM embed -> top-k from ChromaDB -> Groq.

Read-only on the vector store: this module never ingests and never writes to
data/chroma/, so restarting the app (or this CLI) never re-embeds the corpus.
Run `python -m src.ingest` once first.

Blocked intents (Phase 5, src/guardrails.py) are answered from the guardrail
refusal before any embedding or retrieval happens (architecture section 7).

Answer contract (architecture section 5.2, PRD FR-4/FR-5/FR-6/FR-8):
    text          <= 3 sentences, grounded in the retrieved chunks
    citation_url  exactly one source_url, picked in Python from the best chunk
    last_updated  ingest date from data/ingest_meta.json
    chunk_ids     retrieved chunk ids, for debug/inspection

CLI:
    py -3 -m src.query "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
    py -3 -m src.query "..." --debug      # also print the retrieved chunks
    py -3 -m src.query                     # interactive loop

Retrieval quality is measured separately and offline: py -3 -m src.eval_retrieval.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv

from src.config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    ENV_PATH,
    GROQ_MODEL,
    INGEST_HINT,
    INGEST_META_PATH,
    LAST_UPDATED_PREFIX,
    MAX_ANSWER_SENTENCES,
    ROOT,
    TOP_K,
    UNKNOWN_ANSWER,
)
from src.embeddings import embed_texts
from src.guardrails import SCHEME_ALIASES, check_question

GROQ_TEMPERATURE = 0.0
GROQ_MAX_TOKENS = 400

SYSTEM_PROMPT = (
    "You are a facts-only FAQ assistant for five HDFC Mutual Fund Direct-Growth "
    "scheme pages from Groww. You answer strictly from the retrieved context "
    "below, which is the only source you have.\n"
    "Rules:\n"
    "1. Use only facts present in the context. Never invent, estimate, round or "
    "infer numbers (expense ratio, exit load, minimum investment, tenure, dates).\n"
    "2. If the context does not contain the answer, say that the listed sources "
    f"do not contain it. Say exactly: \"{UNKNOWN_ANSWER}\" and add nothing else.\n"
    "3. Answer in at most 3 sentences of plain prose. No bullet lists, no markdown, "
    "no headings, no URLs.\n"
    "4. No investment advice: never say whether to buy, sell, hold or choose a "
    "scheme, never compare schemes by quality, never promise or compare returns.\n"
    "5. Name the scheme the fact belongs to when the context makes it clear."
)

BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*+\u2022]|\d+[.)]|#{1,6}|>)\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\u20b9\"'(])")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


class QueryError(RuntimeError):
    """Any failure the UI should show as a friendly message."""


class MissingAPIKey(QueryError):
    """GROQ_API_KEY is not set in the environment or .env."""


class VectorStoreNotReady(QueryError):
    """data/chroma/ has no collection; ingest has not been run."""


class GenerationError(QueryError):
    """Groq could not produce an answer."""


@dataclass
class RetrievedChunk:
    """One hit from ChromaDB, ordered by distance (closest first)."""

    chunk_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    distance: float = 1.0

    @property
    def score(self) -> float:
        """Cosine similarity (collection is hnsw:space=cosine, so distance = 1 - score)."""
        return 1.0 - self.distance

    @property
    def source_url(self) -> str:
        return str(self.metadata.get("source_url", ""))

    @property
    def scheme_name(self) -> str:
        return str(self.metadata.get("scheme_name", ""))

    @property
    def section(self) -> str:
        return str(self.metadata.get("section", ""))


def load_env() -> None:
    """Load .env (GROQ_API_KEY only); the real key never lives in git."""
    load_dotenv(ENV_PATH, override=False)


def api_key() -> str:
    load_env()
    return (os.getenv("GROQ_API_KEY") or "").strip()


def groq_model() -> str:
    load_env()
    return (os.getenv("GROQ_MODEL") or GROQ_MODEL).strip() or GROQ_MODEL


@lru_cache(maxsize=1)
def get_groq_client() -> Any:
    key = api_key()
    if not key:
        raise MissingAPIKey(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your "
            "Groq API key, then try again."
        )
    from groq import Groq

    return Groq(api_key=key)


@lru_cache(maxsize=1)
def get_collection() -> Any:
    """Open the persisted collection for reading; never called at import time."""
    import chromadb
    from chromadb.config import Settings

    if not CHROMA_DIR.exists():
        raise VectorStoreNotReady(INGEST_HINT)
    try:
        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
        )
        collection = client.get_collection(
            name=COLLECTION_NAME, embedding_function=None
        )
    except Exception as exc:  # missing directory, missing collection, bad path
        raise VectorStoreNotReady(f"{INGEST_HINT} ({exc})") from exc
    if collection.count() == 0:
        raise VectorStoreNotReady(INGEST_HINT)
    return collection


def last_updated() -> str:
    """Ingest date for the `Last updated from sources:` line, or 'unknown'."""
    try:
        meta = json.loads(INGEST_META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    for key in ("fetched_at", "embedded_at", "chunked_at"):
        value = meta.get(key)
        if value:
            return str(value)[:10]
    return "unknown"


def scheme_category(question: str) -> Optional[str]:
    """Corpus category named by the question, when it names exactly one scheme.

    Reuses the guardrail alias table, so "HDFC Equity Fund" and "flexi cap" both
    route to flexi-cap. A question naming two or more schemes gets no category,
    because narrowing to either one would silently drop the other from the context.
    """
    lowered = (question or "").lower()
    hits = {
        category
        for category, aliases in SCHEME_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    }
    if len(hits) == 1:
        return hits.pop()
    return None


def retrieve(
    question: str,
    top_k: int = TOP_K,
    category: Optional[str] = None,
    use_scheme_filter: bool = True,
) -> List[RetrievedChunk]:
    """Embed the question with the same MiniLM model and take the top-k chunks.

    Every chunk text starts with its scheme name, so pure cosine ranking lets a
    neighbouring scheme's chunk outrank the one actually asked about: "exit load
    of HDFC Small Cap" put the Large Cap chunk first. When the question names
    exactly one corpus scheme, the retrieval is narrowed to that scheme's chunks
    with a metadata filter, which is what makes the citation (FR-6) trustworthy.

    category= pins the scheme explicitly; use_scheme_filter=False disables the
    narrowing (used by src/eval_retrieval.py to A/B the two modes).
    """
    question = (question or "").strip()
    if not question:
        return []
    collection = get_collection()
    vector = embed_texts([question])[0]
    if category is None and use_scheme_filter:
        category = scheme_category(question)
    query_args: Dict[str, Any] = {}
    if category:
        query_args["where"] = {"category": category}
    result = collection.query(
        query_embeddings=[vector],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
        **query_args,
    )

    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or []
    chunks: List[RetrievedChunk] = []
    for i, chunk_id in enumerate(ids):
        chunks.append(
            RetrievedChunk(
                chunk_id=str(chunk_id),
                text=documents[i] if i < len(documents) else "",
                metadata=dict(metadatas[i]) if i < len(metadatas) else {},
                distance=float(distances[i]) if i < len(distances) else 1.0,
            )
        )
    return chunks


def build_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Numbered chunk blocks: text + metadata, the only context the model sees."""
    blocks: List[str] = []
    for i, chunk in enumerate(chunks, start=1):
        blocks.append(
            f"[{i}] scheme: {chunk.scheme_name or 'unknown'}\n"
            f"category: {chunk.metadata.get('category', 'unknown')}\n"
            f"section: {chunk.section or 'unknown'}\n"
            f"source_url: {chunk.source_url}\n"
            f"text: {chunk.text}"
        )
    return "\n\n".join(blocks)


def build_user_message(question: str, chunks: Sequence[RetrievedChunk]) -> str:
    return (
        "Context (retrieved chunks, closest first):\n\n"
        f"{build_context(chunks)}\n\n"
        f"Question: {question}\n\n"
        "Answer in at most 3 sentences using only the context above."
    )


def _numbers(text: str) -> set:
    found = set()
    for token in NUMBER_RE.findall(text or ""):
        try:
            found.add(round(float(token.replace(",", "")), 6))
        except ValueError:
            continue
    return found


def unsupported_numbers(answer: str, context: str) -> List[str]:
    """Numbers the model produced that are not in the retrieved text (FR-5)."""
    return sorted(token for token in _numbers(answer) - _numbers(context))


def _clean_answer(text: str) -> str:
    lines = [BULLET_PREFIX_RE.sub("", line) for line in (text or "").splitlines()]
    flattened = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return flattened


def cap_sentences(text: str, max_sentences: int = MAX_ANSWER_SENTENCES) -> str:
    """Keep the first `max_sentences` sentences (FR-8)."""
    sentences = [part for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    return " ".join(sentences[:max_sentences]).strip()


def enforce_answer_contract(text: str, context: str) -> str:
    """Clean, cap at 3 sentences, and drop answers with numbers not in the chunks."""
    cleaned = cap_sentences(_clean_answer(text))
    if not cleaned:
        return UNKNOWN_ANSWER
    if unsupported_numbers(cleaned, context):
        return UNKNOWN_ANSWER
    return cleaned


def generate_answer(question: str, chunks: Sequence[RetrievedChunk]) -> str:
    """Call Groq with the grounded prompt; returns text already inside the contract."""
    if not chunks:
        return UNKNOWN_ANSWER
    context = build_context(chunks)
    client = get_groq_client()
    try:
        completion = client.chat.completions.create(
            model=groq_model(),
            temperature=GROQ_TEMPERATURE,
            max_tokens=GROQ_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(question, chunks)},
            ],
        )
    except Exception as exc:
        raise GenerationError(f"Groq request failed: {exc}") from exc
    choices = getattr(completion, "choices", None) or []
    if not choices:
        raise GenerationError("Groq returned no answer.")
    message = getattr(choices[0], "message", None)
    return enforce_answer_contract(getattr(message, "content", "") or "", context)


def pick_citation(chunks: Sequence[RetrievedChunk]) -> Optional[str]:
    """One citation URL, from the highest-similarity chunk (FR-6, app-owned)."""
    for chunk in chunks:
        if chunk.source_url:
            return chunk.source_url
    return None


def answer_question(question: str, top_k: int = TOP_K) -> Dict[str, Any]:
    """Question -> answer dict. The single entry point for CLI and (Phase 6) UI."""
    question = (question or "").strip()
    stamp = last_updated()
    if not question:
        return {
            "text": "Please ask a factual question about one of the five HDFC schemes.",
            "citation_url": None,
            "last_updated": stamp,
            "chunk_ids": [],
        }

    # Phase 5: blocked intents stop here, before embed/retrieve (architecture section 7).
    decision = check_question(question)
    if decision.blocked:
        return {
            "text": decision.text,
            "citation_url": decision.citation_url,
            "last_updated": stamp,
            "chunk_ids": [],
        }

    chunks = retrieve(question, top_k=top_k)
    if not chunks:
        return {
            "text": UNKNOWN_ANSWER,
            "citation_url": None,
            "last_updated": stamp,
            "chunk_ids": [],
        }

    return {
        "text": generate_answer(question, chunks),
        "citation_url": pick_citation(chunks),
        "last_updated": stamp,
        "chunk_ids": [chunk.chunk_id for chunk in chunks],
    }


def format_result(result: Dict[str, Any]) -> str:
    lines = [result["text"]]
    if result.get("citation_url"):
        lines.append(f"Source: {result['citation_url']}")
    lines.append(f"{LAST_UPDATED_PREFIX}{result['last_updated']}")
    return "\n".join(lines)


def force_utf8_stdout() -> None:
    """Chunk text carries the rupee sign, which the Windows console codec cannot print."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # already detached, or not a TextIOWrapper
            pass


def _print_debug(question: str, top_k: int) -> None:
    decision = check_question(question)
    if decision.blocked:
        print(f"--- blocked by guardrail: {decision.reason} (no retrieval) ---")
        return
    category = scheme_category(question)
    chunks = retrieve(question, top_k=top_k, category=category)
    print(
        f"--- retrieval: {len(chunks)} chunks (top_k={top_k}, "
        f"scheme filter: {category or 'none'}) ---"
    )
    for i, chunk in enumerate(chunks, start=1):
        print(
            f"[{i}] id={chunk.chunk_id} score={chunk.score:.4f} "
            f"scheme={chunk.scheme_name} section={chunk.section}"
        )
        print(f"    {chunk.text[:160]}...")
    print(f"citation_url -> {pick_citation(chunks)}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ask one question against the persisted ChromaDB (Stage B)."
    )
    parser.add_argument("question", nargs="*", help="question to ask; omit for a prompt loop")
    parser.add_argument("--top-k", type=int, default=TOP_K, help=f"chunks to retrieve (default {TOP_K})")
    parser.add_argument("--debug", action="store_true", help="print retrieved chunks first")
    args = parser.parse_args(argv)

    force_utf8_stdout()

    question = " ".join(args.question).strip()
    if question:
        if args.debug:
            _print_debug(question, args.top_k)
        try:
            print(format_result(answer_question(question, top_k=args.top_k)))
        except QueryError as exc:
            print(f"error: {exc}")
        return

    print("HDFC Mutual Fund FAQ assistant (facts only). Type 'quit' to exit.")
    while True:
        try:
            typed = input("question> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if typed.lower() in {"quit", "exit", "q"}:
            return
        if not typed:
            continue
        try:
            print(format_result(answer_question(typed, top_k=args.top_k)))
        except QueryError as exc:
            print(f"error: {exc}")
        print()


if __name__ == "__main__":
    main()