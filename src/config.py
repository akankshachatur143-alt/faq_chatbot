"""Shared paths and the five Groww corpus URLs (PRD §4.1)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INGEST_META_PATH = DATA_DIR / "ingest_meta.json"
SOURCES_MD_PATH = DATA_DIR / "sources.md"
CHUNKS_TXT_PATH = DATA_DIR / "chunks.txt"
EMBEDDINGS_TXT_PATH = DATA_DIR / "embeddings.txt"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION_NAME = "hdfc_mf_faq"
TOP_K = 4

# Stage B generation (Phase 4). GROQ_API_KEY lives in .env only; the model name
# may be overridden with GROQ_MODEL in .env. Architecture section 10.
# llama-3.3-70b-versatile was retired by Groq (404 model_not_found); this is the
# largest general chat model the account is served today.
GROQ_MODEL = "openai/gpt-oss-120b"
MAX_ANSWER_SENTENCES = 3
LAST_UPDATED_PREFIX = "Last updated from sources: "
UNKNOWN_ANSWER = "I don't have that in the listed sources."
ENV_PATH = ROOT / ".env"
INGEST_HINT = "No vector store yet: run `python -m src.ingest` once before querying."

# Phase 1 loads the raw pages; Phase 2 chunks them (see docs/chunking.md).
# Phase 3 embeds the chunks with EMBEDDING_MODEL and persists them in CHROMA_DIR.
# Nothing imports this module's paths at UI start-up; ingest runs from the CLI only.

CHUNK_MAX_CHARS = 600
CHUNK_MIN_CHARS = 250
CHUNK_OVERLAP_RATIO = 0.15

SOURCES = [
    {
        "category": "large-cap",
        "scheme_name": "HDFC Large Cap Fund – Direct Growth",
        "slug": "hdfc-large-cap-fund-direct-growth",
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    },
    {
        "category": "flexi-cap",
        "scheme_name": "HDFC Equity Fund – Direct Growth",
        "slug": "hdfc-equity-fund-direct-growth",
        "source_url": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    },
    {
        "category": "elss",
        "scheme_name": "HDFC ELSS Tax Saver Fund – Direct Plan Growth",
        "slug": "hdfc-elss-tax-saver-fund-direct-plan-growth",
        "source_url": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    },
    {
        "category": "small-cap",
        "scheme_name": "HDFC Small Cap Fund – Direct Growth",
        "slug": "hdfc-small-cap-fund-direct-growth",
        "source_url": "https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth",
    },
    {
        "category": "hybrid",
        "scheme_name": "HDFC Balanced Advantage Fund – Direct Growth",
        "slug": "hdfc-balanced-advantage-fund-direct-growth",
        "source_url": "https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth",
    },
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
