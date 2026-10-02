# Implementation guide (phase-wise)

**For:** Cursor (or another coding agent) implementing the FAQ RAG chatbot  
**Follow:** `docs/architecture.md` (structure) and `docs/PRD.md` (behavior)  
**Corpus:** only the five Groww HDFC URLs in PRD §4.1

Use **one phase per Cursor chat (or per prompt)**. Do not skip ahead. Each phase ends with a checklist; start the next phase only when that checklist is green.

---

## How to use this file with Cursor

1. Open a new agent chat for the phase.
2. Paste the **Cursor prompt** at the bottom of that phase.
3. Attach or `@`-mention the files listed under **Read first**.
4. When the agent finishes, run the **Done when** checks yourself (or ask Cursor to verify).
5. Commit (if you use git) before starting the next phase.

**Global rules for every phase**

- Ingestion and query stay **separate**. Never call ingest on Streamlit/Gradio startup.
- Embedding model is always `sentence-transformers/all-MiniLM-L6-v2` (384-d) for **both** chunks and questions.
- Vector DB is **ChromaDB persisted to disk**.
- LLM is **Groq**; key only in `.env`.
- Do not add sources beyond the five Groww URLs.
- No PII storage. No return calculations. No investment advice in prompts or UI copy.

---

## Phase map

| Phase | RAG stage | Outcome |
|-------|-----------|---------|
| 0 | — | Repo skeleton, deps, gitignore, source list |
| 1 | Ingestion: Load | Raw text saved; pages inspected |
| 2 | Ingestion: Chunk | `docs/chunking.md` locked; `data/chunks.txt` |
| 3 | Ingestion: Embed + Store | Chroma on disk; ingest CLI |
| 4 | Retrieval + Groq | CLI/query path: answer + 1 citation |
| 5 | Guardrails | Advice / PII / returns / out-of-scope |
| 6 | Tiny UI | Welcome, examples, disclaimer, chat |
| 7 | Deliverables | README, sample Q&A, polish for demo |

---

## Phase 0 — Project skeleton

**Goal:** Empty runnable layout matching architecture §9. No scraping, no model download required to “finish” this phase (deps listed only).

### Read first

- `docs/architecture.md` §9, §10
- `docs/PRD.md` §4.1, §11

### Create

```
src/                 # empty modules ok: ingest.py, query.py, guardrails.py, embeddings.py, app.py as stubs or skip until later
data/sources.md      # five URLs
.env.example         # GROQ_API_KEY=
.gitignore           # .env, data/chroma/, data/raw/, __pycache__, .venv
requirements.txt
```

### Do

- Python 3.10+.
- `requirements.txt`: `sentence-transformers`, `chromadb`, `groq`, `python-dotenv`, `beautifulsoup4`, `requests` (or `httpx`), `streamlit` (prefer Streamlit for the tiny UI).
- `data/sources.md`: table of the five schemes + URLs from PRD.
- Shared config constants (paths, collection name `hdfc_mf_faq`, `TOP_K=4`, embed model name) in something like `src/config.py`.

### Do not

- Fetch pages yet.
- Put a real API key in git.

### Done when

- [ ] Layout matches architecture §9 (folders exist).
- [ ] `.gitignore` excludes `.env` and Chroma data.
- [ ] `data/sources.md` has exactly five Groww links.

### Cursor prompt (Phase 0)

```
Implement Phase 0 only from docs/implementation.md.

Read docs/architecture.md §9–10 and docs/PRD.md §4.1.

Create the repo skeleton: src/config.py, requirements.txt, .gitignore, .env.example, data/sources.md with the five Groww HDFC URLs from the PRD. Do not fetch pages, do not ingest, do not build the UI.

Stop when Phase 0 "Done when" is true.
```

---

## Phase 1 — Load and inspect (ingestion starts)

**Goal:** Fetch the five pages, save raw text, inspect structure so Phase 2 can lock chunking. **Do not chunk or embed yet.**

### Read first

- `docs/architecture.md` §4.1, §4.2, §4.6
- `docs/PRD.md` §4.1
- `data/sources.md`

### Create / implement

- `src/ingest.py` (load + clean only) **or** `src/load.py` imported by ingest later.
- `data/raw/` one `.txt` (or `.html` + `.txt`) per scheme.
- Short inspection notes in the chat **and** a stub `docs/chunking.md` titled “pending lock” listing what you observed (headings, tables, noise).

### Do

- HTTP GET the five URLs; extract visible text (BeautifulSoup); strip obvious nav/footer chrome.
- Normalize whitespace.
- Record `fetched_at` (ISO date) in `data/ingest_meta.json` (even if chroma is empty).
- Print or save: approximate character count per page, whether expense ratio / exit load / SIP appear, heading patterns.

### Do not

- Embed, write Chroma, or call Groq.
- Add extra URLs if a fetch fails — retry/fix headers (User-Agent) instead. If Groww blocks, save what you can and document the block in `docs/chunking.md`; still do not invent a sixth source.

### Done when

- [ ] Five raw text files exist under `data/raw/`.
- [ ] You can open them and see scheme facts (or a documented fetch failure).
- [ ] `ingest_meta.json` has a fetch date.
- [ ] No Chroma collection created yet.

### Cursor prompt (Phase 1)

```
Implement Phase 1 only from docs/implementation.md.

Read docs/architecture.md §4.1–4.2 and §4.6, docs/PRD.md §4.1, and data/sources.md.

Fetch only those five Groww URLs, extract visible text, save under data/raw/, write data/ingest_meta.json with fetched_at. Inspect the text and draft observations in docs/chunking.md (do not lock chunk size yet). Do not embed, do not write Chroma, do not call Groq.

Stop when Phase 1 "Done when" is true. Summarize page structure for Phase 2.
```

---

## Phase 2 — Chunking (lock strategy, write chunks.txt)

**Goal:** Decide chunk size, overlap, metadata from **inspected** pages. Persist every chunk to `data/chunks.txt`. Still **no** embeddings/Chroma.

### Read first

- `docs/architecture.md` §4.3
- `docs/PRD.md` §8
- `docs/chunking.md` (Phase 1 notes)
- Sample files in `data/raw/`

### Create / implement

- Finalize `docs/chunking.md`: why this strategy, size, overlap, metadata, examples of 1–2 chunks.
- Chunker used by ingest (e.g. `src/chunking.py`).
- `data/chunks.txt` human-readable dump.

### Do

- Prefer heading / fact-block splits so expense ratio, exit load, and SIP stay with the scheme name.
- Fallback: ~400–600 characters, 10–15% overlap (architecture starting proposal) **only if** inspection shows unstructured dumps.
- Metadata per chunk: `source_url`, `scheme_name`, `category` (`large-cap` | `flexi-cap` | `elss` | `small-cap` | `hybrid`), optional `section`.
- `chunks.txt` format example:

```
--- chunk_id: 0 ---
scheme: ...
category: ...
source_url: https://groww.in/...
section: ...

<text>
```

### Do not

- Change the five URLs.
- Embed or upsert to Chroma yet.

### Done when

- [ ] `docs/chunking.md` states size, overlap, metadata, and rationale.
- [ ] `data/chunks.txt` contains all chunks and is readable in an editor.
- [ ] Each chunk has `source_url` + `scheme_name` + `category`.

### Cursor prompt (Phase 2)

```
Implement Phase 2 only from docs/implementation.md.

Read docs/architecture.md §4.3, docs/PRD.md §8, docs/chunking.md, and data/raw/.

Inspect the saved pages first. Then lock a chunking strategy in docs/chunking.md (why it fits this data, chunk size, overlap, metadata). Implement the chunker and write every chunk to data/chunks.txt with source_url, scheme_name, and category.

Do not embed. Do not write Chroma. Do not call Groq.

Stop when Phase 2 "Done when" is true.
```

---

## Phase 3 — Embed and store (finish Stage A)

**Goal:** Embed chunks with MiniLM, persist ChromaDB on disk. Ingest is a **CLI** you run once.

### Read first

- `docs/architecture.md` §4.4, §4.5, §9
- `docs/chunking.md`
- `src/config.py`

### Create / implement

- `src/embeddings.py` — load MiniLM once; `embed_texts(list[str]) -> vectors`.
- `src/ingest.py` — load raw or reuse chunks → embed → upsert Chroma persist dir `data/chroma/`, collection `hdfc_mf_faq`.
- Re-write `data/chunks.txt` if ingest is the single source of truth.
- Refresh `data/ingest_meta.json` (`fetched_at` / `embedded_at`).

### Do

- Same model name string as config; 384 dimensions.
- Persist to disk; running ingest twice should replace/rebuild the collection cleanly (delete+recreate is OK for this demo).
- CLI: `python -m src.ingest` (or `python src/ingest.py`) from repo root.
- Confirm ingest is **not** imported as a side effect by a future UI.

### Do not

- Call Groq.
- Download a different embedding model.

### Done when

- [ ] `data/chroma/` exists after one ingest run.
- [ ] Collection count equals number of chunks in `chunks.txt`.
- [ ] Restarting Python and opening Chroma in a one-liner still finds the collection (persist works).
- [ ] App/UI still does not exist or does not ingest on import.

### Cursor prompt (Phase 3)

```
Implement Phase 3 only from docs/implementation.md.

Read docs/architecture.md §4.4–4.5 and §9, docs/chunking.md, and src/config.py.

Add src/embeddings.py using sentence-transformers/all-MiniLM-L6-v2 (384-d). Finish src/ingest.py: chunk (from Phase 2) → embed → persist ChromaDB at data/chroma/ collection hdfc_mf_faq. Write data/chunks.txt and update data/ingest_meta.json. Ingest must be a CLI run once, not on UI start.

Do not implement query, Groq, guardrails, or UI.

After coding, run ingest once. Stop when Phase 3 "Done when" is true and report chunk count.
```

---

## Phase 4 — Retrieve + generate (Stage B core)

**Goal:** Question → embed → top-k → Groq → answer + **one citation** + last-updated. No UI yet; a function + optional CLI is enough.

### Read first

- `docs/architecture.md` §5, §6, §10
- `docs/PRD.md` §6 (FR-4, FR-5, FR-6, FR-8, FR-11)

### Create / implement

- `src/query.py` — `answer_question(question: str) -> dict` with `text`, `citation_url`, `last_updated`, `chunk_ids` (debug).
- Groq client from `GROQ_API_KEY`; model name in config / env.
- Grounded system prompt: facts only, ≤3 sentences, no inventing numbers, unknown if not in chunks, no advice.
- Citation chosen **in Python** from the top retrieved chunk’s `source_url` (highest similarity), not from free-form model text.
- Last-updated from `ingest_meta.json`.
- `.env` local only; document key in `.env.example`.

### Do

- `TOP_K = 4`.
- Reuse `src/embeddings.py` for the question.
- Open Chroma in **read** mode from `data/chroma/`.
- If chunks do not contain the fact, the model (and/or a post-check) must say sources do not contain it — no fabricated ratios.

### Do not

- Guardrails module yet (optional light handling is OK; full rules are Phase 5).
- Streamlit UI.
- Re-run ingest inside `answer_question`.

### Done when

- [ ] With `.env` set, a CLI or Python snippet answers: “What is the expense ratio of HDFC Large Cap Fund Direct Growth?”
- [ ] Response has ≤3 sentences, one Groww URL from the corpus, and `Last updated from sources:`.
- [ ] Asking something absent yields an explicit unknown, not a made-up number.

### Cursor prompt (Phase 4)

```
Implement Phase 4 only from docs/implementation.md.

Read docs/architecture.md §5–6 and §10, and docs/PRD.md FR-4, FR-5, FR-6, FR-8, FR-11.

Implement src/query.py: embed the question with the same MiniLM model, retrieve top-k=4 from persisted Chroma, call Groq with a grounded prompt (facts only, ≤3 sentences, no invented numbers). The app selects exactly one citation URL from chunk metadata (best match). Append last-updated from ingest_meta.json. Load GROQ_API_KEY from .env.

Do not add Streamlit. Do not add the full guardrails module yet. Do not ingest on query.

Add a small CLI to test one question. Stop when Phase 4 "Done when" is true.
```

---

## Phase 5 — Guardrails

**Goal:** Product logic **before** RAG for blocked intents (architecture §7). Not a second agent.

### Read first

- `docs/architecture.md` §7, §5.1 step 2
- `docs/PRD.md` §10, FR-7, FR-9, FR-10

### Create / implement

- `src/guardrails.py` — classify/handle:
  1. PII (PAN, Aadhaar, account numbers, OTP, email, phone) → refuse; do not log identifiers; ask to rephrase.
  2. Advice / buy-sell / best fund / portfolio → refuse + one corpus URL.
  3. Compute/compare returns → no math; cite the relevant scheme URL if detectable, else any one corpus URL + instruction to read the page.
  4. Scheme clearly not in the five → out of scope; list the five schemes.
- Wire into `answer_question` **before** embed/retrieve for (1)(2)(3)(4). In-scope factual questions still go to RAG.

### Do

- Keep refusals short and polite; still facts-only tone.
- Use keyword / regex / simple rules (allowed). An extra Groq classifier is **out of scope** unless rules fail badly.

### Do not

- Store user messages that contain PII.
- Soften advice into “this fund looks good.”

### Done when

- [ ] “Should I buy HDFC Small Cap?” → refusal + one link, no RAG numbers presented as a recommendation.
- [ ] Message containing a fake PAN/email → refuse, nothing written to a log file with that value.
- [ ] “Which of these has better 5-year returns?” → no computation.
- [ ] “Expense ratio of SBI Bluechip?” → out of scope + list of five HDFC schemes.
- [ ] A normal expense-ratio question still hits Groq/RAG.

### Cursor prompt (Phase 5)

```
Implement Phase 5 only from docs/implementation.md.

Read docs/architecture.md §7 and §5.1, and docs/PRD.md §10.

Add src/guardrails.py as product logic (not a second LLM). Before retrieve/generate, handle: PII refuse (do not log identifiers); advice/buy-sell/best-fund refuse + one corpus link; returns compute/compare refuse (cite scheme page, no math); unknown AMC/scheme out of scope listing the five HDFC schemes.

Wire this into src/query.py. In-scope factual questions still use RAG from Phase 4.

Stop when Phase 5 "Done when" is true. Show example outputs for each blocked path.
```

---

## Phase 6 — Tiny UI

**Goal:** Class-demo UI from architecture §8 and PRD §5. Query path only; **no ingest on startup**.

### Read first

- `docs/architecture.md` §8, §12
- `docs/PRD.md` §5

### Create / implement

- `src/app.py` (Streamlit preferred).
- Always visible: welcome line, note **“Facts-only. No investment advice.”**, disclaimer from PRD §5.3.
- Three clickable example questions (PRD §5.2).
- Chat: user + assistant; each assistant turn shows body, citation link, last-updated.
- `if __name__` / `streamlit run src/app.py` documented.

### Do

- Call `answer_question` only.
- If Chroma is missing, show a clear error: run ingest first (`python -m src.ingest`).

### Do not

- Login, PII inputs, extra pages, analytics.
- Trigger ingest in `app.py`.

### Done when

- [ ] UI matches the tiny-UI list in the PRD.
- [ ] Example question click fills/sends a factual query.
- [ ] Advice question in the chat shows refusal.
- [ ] Restarting Streamlit does **not** re-download/re-embed the corpus.

### Cursor prompt (Phase 6)

```
Implement Phase 6 only from docs/implementation.md.

Read docs/architecture.md §8 and §12, and docs/PRD.md §5.

Build a tiny Streamlit UI in src/app.py: welcome line, three example questions from the PRD, persistent "Facts-only. No investment advice.", chat, disclaimer snippet from PRD §5.3. Each answer shows ≤3-sentence body, one citation URL, and last-updated. Call src/query.py only. Do not run ingest on startup. If Chroma is missing, tell the user to run ingest.

Stop when Phase 6 "Done when" is true.
```

---

## Phase 7 — Deliverables and demo polish

**Goal:** Assignment extras: README, sample Q&A, source list already done, known limits.

### Read first

- `docs/PRD.md` §11, §12, §13
- `docs/architecture.md` §12

### Create / update

- `README.md`: setup (venv, `pip install`, `.env`, **run ingest once**, `streamlit run`), scope (AMC + five schemes), known limits from PRD §13.
- `samples/qa.md`: 5–10 queries with the assistant’s actual answers + links (run the app or `query.py` and paste).
- Confirm `data/sources.md` is the source-list deliverable.
- Disclaimer in UI matches README.

### Suggested sample questions (mix)

1. Expense ratio — HDFC Large Cap Direct Growth  
2. ELSS lock-in  
3. Minimum SIP — one scheme  
4. Exit load — Small Cap  
5. Riskometer or benchmark  
6. How to download capital-gains statement (honest miss OK if not in pages)  
7. Should I buy? (refusal)  
8. Compare 5y returns (no compute)  
9. A non-HDFC / sixth scheme (out of scope)  

### Done when

- [ ] README lets a classmate reproduce without tribal knowledge.
- [ ] `samples/qa.md` has 5–10 real answers + URLs.
- [ ] Demo path in architecture §12 works without code changes.

### Cursor prompt (Phase 7)

```
Implement Phase 7 only from docs/implementation.md.

Read docs/PRD.md §11–13 and docs/architecture.md §12.

Write README.md (setup, ingest once then UI, AMC + five schemes, known limits). Create samples/qa.md with 5–10 real questions run through the existing query path, including one advice refusal and one unknown or returns refusal. Do not add new sources or change the RAG architecture.

Stop when Phase 7 "Done when" is true.
```

---

## After all phases — smoke test

Run in order:

```text
python -m src.ingest
streamlit run src/app.py
```

Then architecture §12:

1. Open `data/chunks.txt` and `data/chroma/`.
2. Ask an in-scope fact → citation is one of the five URLs.
3. Ask “Should I buy this fund?” → refusal.
4. Ask a returns comparison → no compute.

If any step fails, re-open Cursor on **that phase only** (3 = ingest, 4 = RAG, 5 = guardrails, 6 = UI).

---

## Out of scope for all phases

- Extra AMCs or extra URLs  
- Login, KYC, PAN capture  
- Return/CAGR calculators  
- Re-ingest on every app start  
- A different embedding model or hosted vector DB  
- Multi-agent orchestration
