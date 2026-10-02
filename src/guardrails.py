"""Phase 5: guardrails as product logic, applied *before* embed/retrieve.

Architecture section 7 order:

    PII -> advice / buy-sell / best fund -> returns compute or compare -> scheme
    not in the five -> RAG (embed -> retrieve -> Groq)

These are regex/keyword rules only, never a second LLM call. A blocked decision
already carries the refusal text plus the single citation URL the answer
contract allows, so src/query.py returns the same dict shape for a refusal as
for a grounded answer. Identifiers found in a message are never echoed back or
written anywhere (FR-9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern

from src.config import SOURCES

CORPUS_URLS = [str(source["source_url"]) for source in SOURCES]
DEFAULT_URL = CORPUS_URLS[0]

# Words that may sit between a foreign name and its category ("Mirae Large Cap")
# without making the scheme foreign.
GENERIC_WORDS = {
    "a", "an", "any", "and", "about", "balance", "best", "better", "can", "compare",
    "comparison", "cost", "detail", "details", "direct", "expense", "exit", "fee",
    "for", "fund", "growth", "growth?", "give", "growth", "i", "in", "info", "is",
    "it", "load", "lock", "lock-in", "management", "minimum", "mutual", "my", "of",
    "on", "or", "please", "ratio", "returns", "risk", "riskometer", "savings", "sip",
    "should", "state", "tax", "tell", "the", "this", "to", "what", "when", "which",
    "who", "why", "with", "year", "years",
}


@dataclass
class Decision:
    """Result of the pre-retrieval checks."""

    blocked: bool
    reason: str = ""
    text: str = ""
    citation_url: Optional[str] = None


# --------------------------------------------------------------------------
# 1. PII - refuse, never echo the identifiers, never log them (FR-9)
# --------------------------------------------------------------------------

PAN_RE: Pattern = re.compile(r"\b[A-Z]{5}\s?\d{4}\s?[A-Z]\b")
AADHAAR_RE: Pattern = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
ACCOUNT_RE: Pattern = re.compile(r"\b\d{9,18}\b")
PHONE_RE: Pattern = re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b")
EMAIL_RE: Pattern = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
OTP_WORD_RE: Pattern = re.compile(
    r"\b(?:otp|one[\s-]?time\s+(?:password|passcode|pin|code))\b", re.IGNORECASE
)
SHORT_NUMBER_RE: Pattern = re.compile(r"\b\d{4,8}\b")
OTP_REQUEST_RE: Pattern = re.compile(
    r"\b(?:share|send|give|tell|provide|read|confirm|what\s+is|my)\b"
)
IDENTIFIER_WORD_RE: Pattern = re.compile(
    r"\b(?:pan|aadhaar|aadhar|account\s+(?:number|no\.?)|folio\s+(?:number|no\.?)"
    r"|debit\s+card|credit\s+card|cvv|demat|upi\s+id|bank\s+account)\b"
)

PII_REFUSAL = (
    "I can't work with a message that contains personal identifiers such as a "
    "PAN, Aadhaar number, account number, OTP, email address or phone number. "
    "Please rephrase your question without any personal details."
)


def pii_kind(question: str) -> Optional[str]:
    """Name the identifier *kind* only - never the value itself."""
    if EMAIL_RE.search(question):
        return "email"
    if PAN_RE.search(question):
        return "PAN"
    if AADHAAR_RE.search(question):
        return "Aadhaar"
    if ACCOUNT_RE.search(question):
        return "account number"
    if PHONE_RE.search(question):
        return "phone number"
    if OTP_WORD_RE.search(question) and (
        SHORT_NUMBER_RE.search(question) or OTP_REQUEST_RE.search(question.lower())
    ):
        return "OTP"
    if IDENTIFIER_WORD_RE.search(question.lower()):
        return "account identifier"
    return None


# --------------------------------------------------------------------------
# 2. Advice / buy-sell / best fund / portfolio - refuse + one corpus link (FR-7)
# --------------------------------------------------------------------------

ADVICE_RES: tuple = (
    re.compile(r"\bshould\s+(?:i|we|one|anyone)\b"),
    re.compile(r"\bshould\s+(?:i|we)\s+(?:buy|sell|redeem|invest|start|switch)\b"),
    re.compile(r"\b(?:can|may)\s+(?:i|we)\s+(?:buy|sell|redeem|invest|purchase|switch)\b"),
    re.compile(r"\b(?:buy|sell|redeem|purchase|switch)\s+(?:it|this|that|these|any|hdfc)\b"),
    re.compile(r"\b(?:buy|sell|invest|purchase)\s+(?:hdfc|sbi|icici|kotak|axis|mirae|parag|nippen|nippon)\b"),
    re.compile(r"\binvest\s+in\b"),
    re.compile(r"\bworth\s+(?:buying|investing|it|this)\b"),
    re.compile(r"\b(?:is|are)\s+(?:it|this|that)\s+(?:safe|good|risky|better|worth)\b"),
    re.compile(r"\bgood\s+(?:fund|scheme|choice|option|investment|buy|time|place)\b"),
    re.compile(r"\bbest\s+(?:fund|scheme|option|choice|one|mutual|equity|sip)\b"),
    re.compile(r"\b(?:recommend|recommendation|advise|advice|suggest|suggestion)\w*\b"),
    re.compile(r"\bportfolio\b"),
    re.compile(r"\basset\s+allocation\b"),
    re.compile(r"\ballocat(?:e|ion)\w*\b"),
    re.compile(r"\bwhich\s+(?:fund|scheme|one)\s+(?:should|do|is)\b"),
    re.compile(r"\bany\s+(?:advice|tips?|opinion|suggestions?)\b"),
    re.compile(r"\bopini(?:on|nated)\b"),
    re.compile(r"\b(?:horizon|goal)\s+planning\b"),
    re.compile(r"\bsuitable\s+for\s+(?:me|my)\b"),
)

ADVICE_REFUSAL = (
    "I don't give investment advice, so I can't say whether you should buy, "
    "sell or hold a scheme. I can share published facts such as expense ratio, "
    "exit load, minimum investment, benchmark and riskometer for the listed HDFC "
    "pages, so please read those on the scheme page linked below."
)

# --------------------------------------------------------------------------
# 3. Returns compute/compare - no math, point at the scheme page (FR-10)
# --------------------------------------------------------------------------

CAPITAL_GAINS_RE: Pattern = re.compile(r"capital[\s-]?gains?")

RETURNS_RES: tuple = (
    re.compile(r"\bcagr\b"),
    re.compile(r"\breturns?\b"),
    re.compile(r"\bperformance\b"),
    re.compile(r"\bprofits?\b"),
    re.compile(r"\byields?\b"),
    re.compile(r"\bmoney\s+multiplier\b"),
    re.compile(r"\bcalculat(?:e|or|ion)|calculator\b"),
    re.compile(r"\bcompar(?:e|es|ed|ing|ison)\b"),
    re.compile(r"\bversus\b"),
    re.compile(r"\bvs\.?\b"),
    re.compile(r"\bbetter\b"),
    re.compile(r"\bworst\b"),
    re.compile(r"\brank(?:ing|ings|s|ed)?\b"),
    re.compile(r"\btop\s+performing\b"),
    re.compile(r"\bhow\s+(?:much|well|did)\b"),
    re.compile(r"\bwill\s+(?:i|it|this|hdfc|the\s+fund)\b"),
    re.compile(r"\bproject(?:ed|ion|ions)?\b"),
    re.compile(r"\bforecast\b"),
    re.compile(r"\bworth\s+in\s+\d"),
    re.compile(r"\bgains?\b"),
    re.compile(r"\bearnings?\b"),
    re.compile(r"\b\d+\s*(?:year|yr|month)\s+returns?\b"),
)

RETURNS_REFUSAL = (
    "I don't calculate or compare returns, so I won't produce a number for that. "
    "The published figures for this scheme are on its Groww page, which is linked "
    "below - please read the performance figures there."
)

RETURNS_REFUSAL_NO_SCHEME = (
    "I don't calculate or compare returns, so I won't produce a number for that. "
    "The published figures are on the scheme's own Groww page, so please open the "
    "linked page and read the returns section there."
)


# --------------------------------------------------------------------------
# 4. Scope - only the five HDFC Direct-Growth pages (PRD section 10)
# --------------------------------------------------------------------------

SCHEME_ALIASES = {
    "large-cap": ("large cap",),
    "flexi-cap": ("flexi cap", "equity fund", "hdfc equity"),
    "elss": ("elss", "tax saver", "80c"),
    "small-cap": ("small cap",),
    "hybrid": ("balanced advantage",),
}

OTHER_AMC_RE: Pattern = re.compile(
    r"\b(?:sbi|icici|axis|kotak|mahindra|nippon|mirae|canara|uti|lic|motilal|ppfas"
    r"|quant|bandhan|invesco|idbi|tata|bajaj|aditya|sundaram|hsbc|franklin|edelweiss"
    r"|dsp|parag|paragparikh|bluechip)\b"
)

FUND_CATEGORY_RE: Pattern = re.compile(
    r"bluechip|large[\s-]?cap|flexi[\s-]?cap|small[\s-]?cap|mid[\s-]?cap|elss"
    r"|tax\s+saver|balanced\s+advantage|index\s+fund|dividend\s+yield|liquid"
    r"|overnight|value\s+fund|contra\s+fund|arbitrage\s+fund|global\s+fund"
    r"|gold\s+fund|credit\s+fund|corporate\s+bond|banking\s+and\s+psu"
)

WORD_RE: Pattern = re.compile(r"[A-Za-z&.']+")


def detect_category(lowered: str) -> Optional[str]:
    """Category of a corpus scheme named in the question, if any."""
    for category, aliases in SCHEME_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return category
    return None


def mentions_foreign_scheme(lowered: str) -> bool:
    """A fund-style name that is not one of the five, e.g. 'Mirae Large Cap'."""
    for match in FUND_CATEGORY_RE.finditer(lowered):
        prefix = [word.lower() for word in WORD_RE.findall(lowered[: match.start()])]
        for word in reversed(prefix[-3:]):
            if word in GENERIC_WORDS or word == "hdfc":
                continue
            return True
    return False


def url_for(lowered: str) -> str:
    """Best single corpus URL for a refusal: the named scheme, else the first page."""
    category = detect_category(lowered)
    for source in SOURCES:
        if source["category"] == category:
            return str(source["source_url"])
    return DEFAULT_URL


def corpus_list() -> str:
    return "; ".join(
        f"{source['scheme_name'].replace(' – ', ' ')} ({source['category']})"
        for source in SOURCES
    )


OUT_OF_SCOPE_REFUSAL = (
    "That scheme is outside this assistant's scope, which covers only five HDFC "
    f"Mutual Fund Direct-Growth pages: {corpus_list()}. Ask me a factual question "
    "about one of these five and I will answer from those pages."
)


def scope_check(lowered: str) -> Decision:
    """Only the five schemes (or a generic fact) may reach retrieval.

    A foreign AMC wins over a matching alias: "SBI Large Cap" is not in scope
    even though "large cap" is one of our category names.
    """
    foreign = OTHER_AMC_RE.search(lowered) is not None or mentions_foreign_scheme(lowered)
    if "hdfc" in lowered:
        return Decision(blocked=False)
    if foreign:
        return Decision(
            blocked=True,
            reason="out_of_scope",
            text=OUT_OF_SCOPE_REFUSAL,
            citation_url=DEFAULT_URL,
        )
    return Decision(blocked=False)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def check_question(question: str) -> Decision:
    """Run the blocked-intent checks in architecture section 7 order."""
    text = (question or "").strip()
    lowered = text.lower()
    if not lowered:
        return Decision(blocked=False)

    if pii_kind(text):
        return Decision(blocked=True, reason="pii", text=PII_REFUSAL)

    if any(pattern.search(lowered) for pattern in ADVICE_RES):
        return Decision(
            blocked=True,
            reason="advice",
            text=ADVICE_REFUSAL,
            citation_url=url_for(lowered),
        )

    # "capital-gains statement" is an in-scope operational question, not a
    # returns computation, so blank it out before the returns patterns run.
    without_capital_gains = CAPITAL_GAINS_RE.sub(" ", lowered)
    if any(pattern.search(without_capital_gains) for pattern in RETURNS_RES):
        named = detect_category(without_capital_gains) or "hdfc" in without_capital_gains
        return Decision(
            blocked=True,
            reason="returns",
            text=RETURNS_REFUSAL if named else RETURNS_REFUSAL_NO_SCHEME,
            citation_url=url_for(without_capital_gains),
        )

    return scope_check(lowered)