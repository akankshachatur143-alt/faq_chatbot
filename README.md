# HDFC Mutual Fund FAQ RAG Chatbot

A small **facts-only** FAQ assistant for five HDFC Mutual Fund Direct–Growth
scheme pages on Groww. It answers strictly from retrieved source text, shows
**one citation URL** per answer, and **never gives investment advice**.

Built as a RAG demo: the ingestion stage and the query stage are deliberately
separate so each can be walked through live.

---

## Disclaimer

> This assistant answers **facts only** from listed public pages. It is **not**
> investment advice, a recommendation to buy or sell, or a substitute for the
> scheme information document / key information memorandum. Mutual fund
> investments are subject to market risks. Read all scheme-related documents
> carefully.

---

## Scope

**AMC:** HDFC Mutual Fund · **Plan type:** Direct – Growth

These five Groww pages are the **entire** retrieval corpus (full list with
metadata in `data/sources.md`):

| Category | Scheme | Source |
|----------|--------|--------|
| Large Cap | HDFC Large Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| Flexi Cap | HDFC Equity Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| ELSS | HDFC ELSS Tax Saver Fund – Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| Small Cap | HDFC Small Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| Hybrid | HDFC Balanced Advantage Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

**In scope:** expense ratio, exit load, minimum SIP / minimum investment, ELSS
lock-in, riskometer, benchmark, statement download.

**Out of scope:** should-I-buy/sell, portfolio advice, return or CAGR
calculation and comparison, any non-HDFC scheme, and all PII.

---

## Setup

Requires **64-bit Python 3.9–3.12** (PyTorch and ChromaDB publish no 32-bit
Windows wheels).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 1. API key

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
```

Then add your Groq key to `.env`:

```
GROQ_API_KEY=gsk_...
```

`.env` is gitignored and is never committed (FR-11). Optionally set
`GROQ_MODEL` to override the default.

### 2. Ingest once

```bash
python -m src.ingest
```

This is the **only** step that fetches pages, embeds, and writes the vector
store. It is a CLI you run by hand — the app never re-ingests on startup.

Produces:

| Artifact | What it is |
|----------|-----------|
| `data/raw/*.html`, `*.txt` | The five fetched pages, saved for inspection |
| `data/chunks.txt` | All 64 chunks, human-readable, with metadata |
| `data/chroma/` | Persisted ChromaDB collection `hdfc_mf_faq` |
| `data/ingest_meta.json` | Fetch/chunk/embed timestamps and per-page fact flags |

### 3. Run the UI

```bash
streamlit run src/app.py
```

You can also query from the terminal without the UI:

```bash
py -3 -m src.query "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
py -3 -m src.query "..." --debug     # also prints the retrieved chunks
```

Or measure retrieval quality offline:

```bash
py -3 -m src.eval_retrieval
```

---

## How it works

```
INGESTION (offline, run once via `python -m src.ingest`)
  Load pages -> Clean text -> Chunk -> Embed (MiniLM) -> Store ChromaDB on disk
  Also writes data/chunks.txt for inspection

QUERY (runtime, via src/query.py and the Streamlit UI)
  Question -> Guardrails (advice / PII / out-of-scope / returns)
            -> Embed question (same MiniLM)
            -> Retrieve top-4 chunks from ChromaDB
            -> Groq LLM (grounded prompt, temperature 0)
            -> Answer + 1 citation + last-updated
```

### Configuration

| Setting | Value | Where |
|---------|-------|-------|
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (384-d) | `src/config.py` |
| Vector DB | ChromaDB, persisted to `data/chroma/` | `src/config.py` |
| Collection name | `hdfc_mf_faq` | `src/config.py` |
| `TOP_K` | 4 | `src/config.py` |
| Groq model | `openai/gpt-oss-120b` (override with `GROQ_MODEL`) | `src/config.py` |
| Max answer length | 3 sentences | `src/config.py` |
| Chunk size | ~600 chars max, 250 min, 15% overlap | `src/config.py` |
| Temperature | 0.0 | `src/query.py` |

### Answer contract

Every answer returns `text` (≤3 sentences), `citation_url` (exactly one,
chosen in Python from the best-matching chunk's metadata — never from model
text), `last_updated` (ingest date), and `chunk_ids` for debugging.

### Hallucination control

Three layers:

1. **Grounded prompt** — use only the retrieved context; say the exact unknown
   string if the fact is absent.
2. **Scheme filter** — when a question names exactly one corpus scheme,
   retrieval is narrowed to that scheme's `category`, because neighbouring
   schemes' chunks otherwise outrank the one asked about.
3. **Post-check** — any number in the answer that does not appear in the
   retrieved text is discarded and replaced with the unknown answer.

### Guardrails

`src/guardrails.py` runs **before** embedding or retrieval, so blocked
intents cost no Groq call:

| Intent | Behaviour |
|--------|-----------|
| PII (PAN, Aadhaar, account no., OTP, email, phone) | Refuse, ask to rephrase, do not log or store the identifier |
| Advice / buy-sell / "best fund" | Refuse + one scheme link |
| Returns or performance comparison | No math; point to the published figures on the page |
| Scheme outside the five | Out of scope + list all five schemes |

### Repo layout

```
src/config.py         paths, collection name, top-k, model names, five URLs
src/load.py           stdlib page fetch + visible-text extraction
src/chunking.py       heading-aware chunking with metadata
src/embeddings.py     MiniLM wrapper (loaded once, cached)
src/ingest.py         Stage A CLI: load -> chunk -> embed -> store
src/query.py          Stage B: guardrails -> retrieve -> Groq -> answer (+ CLI)
src/guardrails.py     pre-RAG intent rules
src/eval_retrieval.py offline retrieval scoring with/without scheme filter
src/app.py            Phase 6 Streamlit UI (query path only)
docs/                 PRD, architecture, chunking decision, implementation guide
data/sources.md       the five source URLs
samples/qa.md         9 real questions with real answers
```

---

## Demo walkthrough (~3 minutes)

1. Show `data/chunks.txt` and `data/chroma/` — ingestion already happened once.
2. Ask an in-scope fact: *"What is the exit load of HDFC Small Cap Fund Direct Growth?"*
3. Point out the citation URL matches a corpus page and the last-updated date.
4. Ask *"Should I buy HDFC Small Cap Fund Direct Growth?"* — refusal on camera.
5. Ask a returns comparison, or an honest miss such as *"How do I download my
   capital-gains statement?"* — no computation / no invented number.

Full script: `docs/architecture.md` §12. Sample outputs: `samples/qa.md`.

---

## Known limits

- The corpus is only the five Groww pages listed above; nothing else is
  retrievable.
- Page HTML changes. The last-updated date is the ingest date, not live Groww
  data, so re-run `python -m src.ingest` to refresh.
- MiniLM with `k=4` can miss a fact, especially when a question asks for two
  things at once (see `samples/qa.md` §5). Chunking and `k` are the levers.
- Groq may still paraphrase. The guarantee is "no invented numbers", enforced
  by the post-check, not "no paraphrasing".
- ELSS lock-in and statement download are PRD in-scope topics that are simply
  absent from the fetched pages, so the assistant honestly says it does not
  have them.
- Ingest drops the "Return calculator", "Returns and rankings", "Holdings" and
  AMC contact sections, so there is deliberately **no** performance data in
  the vector store.
- Not a licensed advisor. The disclaimer above stays in the UI.
- Single-user local demo: no login, no analytics, no multi-user persistence.

---

## Docs

| File | Contents |
|------|----------|
| `docs/PRD.md` | Product requirements, scope, functional requirements |
| `docs/architecture.md` | RAG design, answer contract, guardrail placement |
| `docs/chunking.md` | Why this chunking strategy, size, overlap, metadata |
| `docs/implementation.md` | Phase-by-phase build guide (Phases 0–7) |
| `docs/problemstatement.txt` | Original assignment brief |
