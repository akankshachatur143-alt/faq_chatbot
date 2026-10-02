# Chunking strategy (locked)

**Status:** Phase 2 — locked after inspecting `data/raw/*.txt` (Phase 1 observations are summarised in §1 below).  
**Code:** `src/chunking.py` (used by `python -m src.ingest`)  
**Output:** `data/chunks.txt` — 64 chunks, 20,171 chars, from 73,644 raw chars (5 pages).  
**Corpus:** the five Groww URLs in `data/sources.md`. Nothing else.

---

## 1. What the inspection showed (Phase 1)

Groww scheme pages are server-rendered HTML that collapses to **one long text line** per scheme. There is
no real heading tree in the extracted text, but the blocks appear in a **fixed order** and are separated by
stable label strings, which behave like headings:

```
HDFC <Scheme> … Min. for SIP … Fund size (AUM) … Expense ratio … Rating      <- fact strip
Return calculator … Historic returns Returns 1 year … 5 years … 10 years   <- performance
Holdings ( 50 ) Name Sector Instruments Assets … See All
Minimum investments Min. for 1st investment …
Understand terms (returns glossary)
Returns and rankings … Rank ( Equity ELSS ) …
Understand terms Expense ratio … Tax … Exit load … Stamp duty              <- glossary
Exit Load <date> <rule> <date> <rule> …                                    <- exit-load history
Exit load, stamp duty and tax Exit load … Stamp duty … Tax implication …
Fund management <XX> <Name> <Mon YYYY - Present> … Also manages these schemes …
About HDFC <Scheme> … rated Very High risk … Minimum SIP … Investment Objective
Fund benchmark … Scheme Information Document(SID) Fund house … Phone … Address …
Compare similar funds Name 1Y 3Y Fund Size(Cr) …                          <- peer comparison
```

Raw sizes: 8.7k / 10.6k / 8.9k / 10.9k / 34.5k chars. The Balanced Advantage page is 4x the others
purely because of ~326 holdings rows.

**Conclusion:** the pages *are* structured — the architecture's character-window default
(400–600 chars, 10–15% overlap) is **not** the primary splitter. It is kept only as a fallback
(§6). Windowing the raw dump would have produced holdings noise, peer-fund comparisons of other
AMCs, and performance figures the product must never use.

---

## 2. Locked strategy — section-aware (fact-block) split

Every page is mapped onto the ordered Groww sections above, then each kept section is packed into
chunks. Implementation: `section_plan()` in `src/chunking.py`.

| # | Section (chunk `section` value) | Page marker | Kept? | Why |
|---|----------------------------------|-------------|-------|-----|
| 1 | `Scheme snapshot` | start → `Return calculator` | **keep** | Scheme name + min SIP + AUM + **expense ratio** + Groww rating. Answers the most common question. |
| 2 | `Return calculator` | `Return calculator` → `Holdings (` | drop | Returns the product must not quote or compute (PRD FR-10). |
| 3 | `Holdings` | `Holdings (` → `See All` | drop | Company lists are noise for an FAQ and dominate the page. |
| 4 | `Minimum investments` | `See All` → `Understand terms` | **keep** | 1st / 2nd investment / SIP minimums. |
| 5 | `Returns glossary` | `Understand terms` → `Returns and rankings` | drop | Defines annualised vs absolute returns — only relevant to performance answers. |
| 6 | `Returns and rankings` | `Returns and rankings` → `Understand terms` | drop | Category rank table = performance comparison. |
| 7 | `Glossary: expense ratio, tax, exit load, stamp duty` | `Understand terms` → `Exit Load <date>` | **keep**, one chunk per term | Lets "what is an expense ratio / exit load" be answered from the page's own wording. |
| 8 | `Exit load history by effective date` | `Exit Load <date>` → `Exit load, stamp duty and tax` | **keep** | Dated load changes. |
| 9 | `Exit load, stamp duty and tax` | `Exit load, stamp duty and tax` → `Check past data` / `Compare similar funds` / `Fund management` | **keep** | Current exit load, stamp duty, tax implication — the authoritative exit-load answer. |
| 10 | `Fund management` | `Fund management` → `About HDFC` | **keep**, one chunk per manager | Name + tenure + education + experience. |
| 11 | `About the scheme` | `About HDFC` → `Scheme Information Document(SID)` | **keep** | Launch date, manager, AUM/NAV, **risk rating**, min SIP/lumpsum, exit load, objective, **benchmark**. |
| 12 | `AMC contact details` | `Scheme Information Document(SID)` → end | drop | Phone, e-mail, postal address, custodian and RTA blocks: chrome, and contact data we do not need to answer FAQs. |
| — | `Compare similar funds` (inside #9) | cut at the marker | drop | Peer funds from other AMCs + 1Y/3Y returns. Out of corpus (PRD §4.1) and performance data. |

Extra cleanups applied to kept sections:

- `See All`, `View details`, duplicated `About HDFC <title>` / `<title> is a …` headings, and the
  repeated `Minimum investments` / `Exit load, stamp duty and tax` labels are removed so the section
  title is not repeated twice in one chunk.
- Each `Also manages these schemes HDFC … HDFC …` list (up to ~20 out-of-corpus scheme names) is cut
  at the next fund-manager entry (`MANAGER_ENTRY_RE`: `XX First Last Mon YYYY - Present`). This keeps
  the corpus clean for the Phase 5 out-of-scope guardrail.

## 3. Chunk size, overlap, packing

| Parameter | Locked value | Where |
|-----------|--------------|-------|
| Max chunk | **600 characters** of section body | `config.CHUNK_MAX_CHARS` |
| Min chunk | **250 characters**, merged into the previous chunk of the *same section* if it fits | `config.CHUNK_MIN_CHARS` |
| Overlap | **15% (~90 characters)**, carried at **sentence boundaries** from the previous chunk | `config.CHUNK_OVERLAP_RATIO` |
| Split unit | Sentence (`(?<=[.!?])\s+(?=[A-Z₹"'('])`, `Mr./Mrs./Ms./Dr.` protected), or a whole glossary term / manager entry when the section is sub-divided | `pack_section`, `_pack_units` |
| Corpus total | **64 chunks**, min 115 / avg 315 / max 595 chars | `data/chunks.txt` |

Why 600 / 15%: MiniLM truncates at ~256 word-pieces; a 600-character chunk stays far inside that, so
no fact is silently cut by the encoder. 15% overlap guarantees a number that lands on a boundary
(`Minimum SIP Investment is set to ₹500.`) still appears complete in at least one neighbouring chunk.
Pieces shorter than 250 chars are merged rather than emitted as fragments, **except** where a section
*is* a single atomic fact (expense ratio strip, exit-load history, a one-line glossary term) — those
stay short on purpose so the vector stays focused.

Chunk text always carries the scheme name and category, so no chunk can be quoted without knowing
which scheme it is about:

```
<scheme name> (<category>). <section>: <body>
```

## 4. Metadata per chunk

| Field | Value | Used by |
|-------|-------|---------|
| `chunk_id` | 0…63, stable across re-runs in corpus order | Chroma id (Phase 3), `chunks.txt` header, debug in `query.py` |
| `source_url` | The page the chunk came from | FR-6 single citation (Phase 4 picks the best chunk's URL) |
| `scheme_name` | PRD §4.1 name, e.g. `HDFC Large Cap Fund – Direct Growth` | Answer phrasing, scheme filter |
| `category` | `large-cap` \| `flexi-cap` \| `elss` \| `small-cap` \| `hybrid` | Filtering / demo |
| `section` | The Groww block (see table in §2) | Demo storytelling, retrieval debugging |
| `slug` | Raw file name stem | Traceability to `data/raw/` |

## 5. Example chunks (verbatim from `data/chunks.txt`)

Expense ratio + min SIP + scheme name (chunk 0):

```
--- chunk_id: 0 ---
scheme: HDFC Large Cap Fund – Direct Growth
category: large-cap
source_url: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
section: Scheme snapshot
chars: 177

HDFC Large Cap Fund – Direct Growth (large-cap). Scheme snapshot: HDFC Large Cap Fund Direct
Growth. Min. for SIP ₹100 Fund size (AUM) ₹39,933.36 Cr Expense ratio 1.04% Rating 4
```

Exit load + benchmark with 15% overlap on the sentence boundary (chunks 10–11):

```
... About the scheme: ... The HDFC Large Cap Fund Direct Growth is rated Very High risk.
Minimum SIP Investment is set to ₹100. Minimum Lumpsum Investment is ₹100.

... About the scheme: Minimum SIP Investment is set to ₹100. Minimum Lumpsum Investment is ₹100.
Exit load of 1% if redeemed within 1 year ; Investment Objective The scheme seeks to provide
long-term capital appreciation/income by investing predominantly in Large-Cap companies.
Fund benchmark NIFTY 100 Total Return Index
```

## 6. Fallback

`window_fallback()` implements the architecture's starting proposal (~600-char windows, 15%
overlap) and is used **only** when a page contains neither `Return calculator` nor `About HDFC`,
i.e. Groww changed the page and no section marker can be trusted. It logs
`Unstructured page -> character windows` in `data/ingest_meta.json` → `sections_dropped`.

## 7. Known trade-offs and gaps

- **Exit-load history (§2 row 8) is kept on purpose**, but it contains superseded tiers (e.g. Small Cap
  "2% within 12 months" from 2014). It is labelled `Exit load history by effective date` so the current
  figure lives in its own clearly-named chunk (`Exit load, stamp duty and tax`). Phase 4's grounded
  prompt must prefer the current-load chunk.
- **ELSS 3-year lock-in is not in the corpus.** No section of the Groww ELSS page states it; "3 years"
  only appears in the dropped return calculator. Phase 4/5 must answer "not in the listed sources".
- **Capital-gains statement download is not in the corpus** either (Phase 1 confirmed). Same handling.
- Holdings, peer comparison, and performance tables are intentionally absent; if a future question
  needs them, the fix is a scoped re-ingest, not a bigger `TOP_K`.
- A manager entry longer than 600 chars would be split across two chunks with the name only in the
  first; the scheme prefix still identifies it. Not observed in this corpus (max entry ≈ 560 chars).

## 8. How to re-run

From repo root:

```
py -3 -m src.ingest              # reuse data/raw, re-chunk, rewrite data/chunks.txt
py -3 -m src.ingest --refetch    # re-fetch the five URLs first, then chunk
```

`py -3 -m src.ingest` is the **only** place chunking runs. Nothing embeds yet: `data/chroma/` is not
created and no model is downloaded (Phase 3 adds MiniLM + ChromaDB).