# Sample Q&A

Real output from the shipped query path (`src/query.py`), captured on
**2026-10-02** (the ingest date, so every answer shows the same
`Last updated from sources: 2026-10-02` line).

Reproduce any row with:

```
py -3 -m src.query "<question>"
```

`Groq model: openai/gpt-oss-120b` · `top_k = 4` · embedding model
`sentence-transformers/all-MiniLM-L6-v2` (384-d)

---

## 1. Expense ratio — in scope, answered with a citation

**Q:** What is the expense ratio of HDFC Large Cap Fund Direct Growth?

> The expense ratio of HDFC Large Cap Fund – Direct Growth is 1.04%.

Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
Last updated from sources: 2026-10-02

---

## 2. ELSS lock-in — honest miss

**Q:** What is the lock-in period for HDFC ELSS Tax Saver Fund Direct Plan Growth?

> I don't have that in the listed sources.

Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
Last updated from sources: 2026-10-02

The Groww ELSS page as fetched does not state a lock-in period in the kept
sections, so the assistant says so instead of supplying the well-known 3 years.
`data/ingest_meta.json` records `lock_in: false` for this page.

---

## 3. Minimum SIP — in scope, answered with a citation

**Q:** What is the minimum SIP amount for HDFC Equity Fund Direct Growth?

> The minimum SIP amount for HDFC Equity Fund – Direct Growth is ₹100.

Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth
Last updated from sources: 2026-10-02

---

## 4. Exit load — in scope, answered with a citation

**Q:** What is the exit load of HDFC Small Cap Fund Direct Growth?

> The HDFC Small Cap Fund – Direct Growth charges an exit load of 1% if redeemed within one year.

Source: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
Last updated from sources: 2026-10-02

---

## 5. Benchmark + riskometer in one question — honest miss

**Q:** What is the benchmark and riskometer level of HDFC Balanced Advantage Fund Direct Growth?

> I don't have that in the listed sources.

Source: https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth
Last updated from sources: 2026-10-02

Asking for two facts at once diluted the top-4 retrieval. Asking for one at a
time returns an answer — this is the known "MiniLM + small k" limit from the
PRD, and it is the intended honest failure rather than a guess.

---

## 6. Statement download — honest miss

**Q:** How do I download my capital-gains statement?

> I don't have that in the listed sources.

Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
Last updated from sources: 2026-10-02

This is in the PRD's in-scope question types but is **not** present on the five
scheme pages (`statement: false` in `data/ingest_meta.json`). Correct refusal.

---

## 7. Advice request — guardrail refusal (no retrieval)

**Q:** Should I buy HDFC Small Cap Fund Direct Growth?

> I don't give investment advice, so I can't say whether you should buy, sell or hold a scheme. I can share published facts such as expense ratio, exit load, minimum investment, benchmark and riskometer for the listed HDFC pages, so please read those on the scheme page linked below.

Source: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
Last updated from sources: 2026-10-02

Blocked by `src/guardrails.py` **before** embedding or retrieval — zero chunks
retrieved, and no Groq call was made.

---

## 8. Returns comparison — guardrail refusal, no math

**Q:** Which of these five funds has better 5-year returns?

> I don't calculate or compare returns, so I won't produce a number for that. The published figures are on the scheme's own Groww page, so please open the linked page and read the returns section there.

Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
Last updated from sources: 2026-10-02

Also blocked pre-retrieval. Note the "Return calculator", "Returns and
rankings" and "Holdings" sections were dropped at ingest, so there is no
performance data in the vector store at all.

---

## 9. Out-of-scope scheme — lists the five

**Q:** What is the expense ratio of SBI Bluechip Fund Direct Growth?

> That scheme is outside this assistant's scope, which covers only five HDFC Mutual Fund Direct-Growth pages: HDFC Large Cap Fund Direct Growth (large-cap); HDFC Equity Fund Direct Growth (flexi-cap); HDFC ELSS Tax Saver Fund Direct Plan Growth (elss); HDFC Small Cap Fund Direct Growth (small-cap); HDFC Balanced Advantage Fund Direct Growth (hybrid). Ask me a factual question about one of these five and I will answer from those pages.

Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
Last updated from sources: 2026-10-02

Blocked pre-retrieval; the refusal names all five corpus schemes.

---

## PII behaviour

A message containing an identifier (PAN, Aadhaar, account number, OTP, email or
phone) is refused and **not** kept in the transcript — the UI substitutes
`_(withheld: this message contained personal identifiers)_` and the raw string
is never stored or logged.

---

## Disclaimer

> This assistant answers **facts only** from listed public pages. It is **not** investment advice, a recommendation to buy or sell, or a substitute for the scheme information document / key information memorandum. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully.
