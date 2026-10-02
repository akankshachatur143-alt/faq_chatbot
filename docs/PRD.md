# Product Requirements Document (PRD)

**Product:** HDFC Mutual Fund FAQ RAG Chatbot  
**Type:** Class demo / working prototype  
**Status:** Draft for implementation  
**Source brief:** `docs/problemstatement.txt`

---

## 1. Summary

Build a small, facts-only FAQ assistant for **five HDFC Mutual Fund Direct–Growth schemes**. Users ask operational questions (expense ratio, exit load, min SIP, ELSS lock-in, riskometer, benchmark, statement download). The assistant answers **only from retrieved source pages**, shows **one citation URL** per answer, and **never gives investment advice**.

The product is a **RAG chatbot**: ingestion (load → chunk → embed → store) is separate from query (embed question → retrieve → LLM → answer). This split is required so the class demo can walk through each RAG stage.

---

## 2. Goals and non-goals

### Goals

- Answer factual scheme questions from the scoped corpus only.
- Cite **exactly one** source link on every answer.
- Refuse buy/sell, portfolio, and “which fund is better” questions politely.
- Demonstrate a complete RAG pipeline on a tiny UI suitable for a ≤3-minute demo.
- Meet assignment deliverables (prototype, source list, README, sample Q&A, disclaimer).

### Non-goals

- Personalized advice, KYC, login, or account-linked data.
- Computing or comparing returns, rankings, or “best fund” lists.
- Multi-AMC coverage, live market quotes, or agentic tool use beyond RAG retrieve + generate.
- Production-grade crawlers, auth, analytics, or multi-user persistence.

---

## 3. Users

| User | Need |
|------|------|
| Retail investor (demo persona) | Fast facts while comparing HDFC schemes. |
| Support / content teammate (demo persona) | Repeatable answers with a source URL. |
| Instructor / classmates | See RAG stages, citations, and safety refusals. |

---

## 4. Scope

### 4.1 AMC and schemes

**AMC:** HDFC Mutual Fund  
**Plan type:** Direct – Growth (as listed on Groww)

| Category | Scheme (as named on source page) | Source URL |
|----------|----------------------------------|------------|
| Large Cap | HDFC Large Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| Flexi Cap | HDFC Equity Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| ELSS | HDFC ELSS Tax Saver Fund – Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| Small Cap | HDFC Small Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| Hybrid | HDFC Balanced Advantage Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

These five Groww URLs from `docs/problemstatement.txt` are the **entire retrieval corpus**. Do not add other pages.

### 4.2 In-scope question types

- Expense ratio  
- Exit load  
- Minimum SIP / minimum investment  
- ELSS lock-in  
- Riskometer  
- Benchmark  
- How to download statements / capital-gains statement

### 4.3 Out of scope

- “Should I buy/sell?”  
- Portfolio construction, asset allocation, tax optimization as advice  
- Return calculation, CAGR comparison, “which is better?”  
- Any PII (PAN, Aadhaar, account numbers, OTP, email, phone)  
- Screenshots or backend-only data as sources  

---

## 5. User experience

### 5.1 Tiny UI (must-have)

- Welcome line (one sentence: what the bot is).  
- Three example questions (clickable or copy-paste).  
- Persistent note: **“Facts-only. No investment advice.”**  
- Chat: user message + assistant reply.  
- Every successful answer shows:
  - ≤3 sentences of facts  
  - One citation link  
  - `Last updated from sources: <date>` (date of last ingestion / source fetch)  
- Refusal copy for advice questions (polite, facts-only, plus one educational/source link from the corpus or a generic “we don’t give advice” line with a relevant scheme page).

### 5.2 Example questions (UI)

1. What is the expense ratio of HDFC Large Cap Fund Direct Growth?  
2. What is the lock-in for HDFC ELSS Tax Saver?  
3. What is the exit load of HDFC Small Cap Fund Direct Growth?

### 5.3 Disclaimer snippet (UI + README)

> This assistant answers **facts only** from listed public pages. It is **not** investment advice, a recommendation to buy or sell, or a substitute for the scheme information document / key information memorandum. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully.

---

## 6. Functional requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Ingest the five source URLs into a persisted vector store (run once, not on every app start). | P0 |
| FR-2 | Persist inspectable chunks to a readable `.txt` file. | P0 |
| FR-3 | Embed chunks and queries with the same local embedding model. | P0 |
| FR-4 | On query: retrieve top-k chunks, generate answer **only** from those chunks. | P0 |
| FR-5 | If the corpus has no supporting fact, say so; do not invent numbers. | P0 |
| FR-6 | Attach **one** citation URL (best matching retrieved chunk’s source). | P0 |
| FR-7 | Detect advice / comparison / performance-compute intent and refuse. | P0 |
| FR-8 | Cap answers at **3 sentences** (citation and last-updated line may sit outside the 3 sentences). | P0 |
| FR-9 | Do not accept or store PII; if the user pastes PII, refuse and ask them to rephrase without identifiers. | P0 |
| FR-10 | If asked for returns / performance, do not compute or compare; link to the source page used for that scheme. | P0 |
| FR-11 | Groq API key loaded from `.env` only; never commit `.env`. | P0 |
| FR-12 | Sample Q&A file (5–10 queries) with answers + links for submission. | P1 |

---

## 7. RAG architecture (demo must show both stages)

Ingestion and retrieval are **separate stages**. Architecture diagrams and the README should name them explicitly.

```
INGESTION (offline / once)
  Load pages → Clean text → Chunk → Embed (MiniLM) → Store ChromaDB (disk)
  Also write chunks.txt for inspection

QUERY (runtime)
  User question → Guardrails (advice / PII / out of scope)
               → Embed question (same MiniLM)
               → Retrieve top-k chunks from ChromaDB
               → Groq LLM (grounded prompt)
               → Answer + 1 citation + last-updated
```

### 7.1 Ingestion

1. **Load:** Fetch and extract visible text from the five URLs.  
2. **Chunk:** Strategy is decided **after inspecting the page text** (see §8).  
3. **Embed:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim).  
4. **Store:** ChromaDB on disk so restart does not re-ingest.

### 7.2 Retrieval and generation

1. Embed the question with the same model.  
2. Retrieve top-k chunks (k documented in README; start with k=3–5).  
3. Prompt the LLM: use only retrieved text; quote facts; if missing, say unknown.  
4. Return answer + single source URL from chunk metadata.

---

## 8. Chunking strategy (required before coding)

The implementing agent must inspect a sample of the loaded pages first, then lock:

- **Why** this strategy fits Groww scheme pages (typically: scheme name, category, ratios, loads, SIP, risk, benchmark in a compact fact-block).  
- **Chunk size** and **overlap**.  
- **Metadata per chunk:** at least `source_url`, `scheme_name`, `category` (large-cap / flexi-cap / ELSS / small-cap / hybrid), and optional `section` if headings exist.

**Starting proposal (to confirm after inspection):**

- Prefer **semantic / heading-aware** splits so expense ratio, exit load, and SIP stay in the same chunk when they sit in one fact table.  
- If pages are short unstructured dumps: **~400–600 characters, 10–15% overlap**, so a fact is not split from its scheme name.  
- Persist **all** chunks to `data/chunks.txt` (or similar) for demo inspection.

Do not implement ingestion until this proposal is written down (README or `docs/chunking.md`).

---

## 9. Technical constraints

| Layer | Choice | Notes |
|-------|--------|--------|
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | Local, no API key, 384 dimensions; same model for docs and queries. |
| Vector DB | ChromaDB | Persist to disk. |
| LLM | Groq | Key in `.env` only. |
| Sources | Public HTTP pages listed in §4.1 | No private backends. |

Suggested (not mandated by the brief) stack for a class demo: Python, a small Streamlit or Gradio UI, one ingest script + one app/query path.

---

## 10. Guardrails (product behavior)

| Signal | Behavior |
|--------|----------|
| Advice / buy-sell / “best fund” | Refuse. Short facts-only message + one relevant educational/scheme link. |
| Returns / performance compare | Do not calculate. Cite source page; user can read published figures there. |
| Question about a scheme not in the five | Say out of scope; list the five schemes. |
| PII in the prompt | Refuse to process; do not log the identifiers. |
| Empty retrieval / low confidence | “I don’t have that in the listed sources.” + citation of closest scheme page if useful. |

---

## 11. Deliverables (assignment)

1. Working prototype (local app) or ≤3-minute demo video if hosting is not possible.  
2. Source list (CSV or MD) of the five URLs.  
3. README: setup, AMC + schemes, known limits.  
4. Sample Q&A file: 5–10 queries with assistant answers and links.  
5. Disclaimer snippet used in the UI.  
6. Inspectable chunks file from ingestion.

---

## 12. Success criteria (class demo)

- Live question → grounded answer in a few seconds with a clickable citation.  
- One advice question is refused on camera.  
- One “unknown / not in sources” (or returns) question shows honest limitation.  
- Instructor can open `chunks.txt` and Chroma persist folder and see ingestion happened once.  
- Answers stay ≤3 sentences and show last-updated date.

---

## 13. Known limits (document in README)

- Corpus is only the five Groww scheme pages listed in the problem statement.  
- Page HTML can change; last-updated reflects last ingest.  
- MiniLM + small k can miss a fact if chunking splits tables poorly.  
- Groq may paraphrase; product requirement is still “no invented numbers.”  
- Not a licensed advisor; SEBI-style disclaimer remains in the UI.

---

## 14. Open decisions

| Topic | Default for demo | Change only if needed |
|-------|------------------|------------------------|
| UI framework | Streamlit or Gradio | Keep tiny. |
| Groq model name | Pick a current Groq chat model in README | Must work with `.env` key. |
| top-k | 4 | Tune after first retrieval tests. |
| Ingest refresh | Manual re-run of ingest script | No auto-crawl in demo. |

---

## 15. Implementation order (suggested)

1. Fetch and save raw text of the five pages; inspect structure.  
2. Write chunking decision + `chunks.txt`.  
3. Embed + persist ChromaDB.  
4. Query path + Groq grounded prompt + citation.  
5. Guardrails + tiny UI + disclaimer.  
6. Sample Q&A + README + source list.
