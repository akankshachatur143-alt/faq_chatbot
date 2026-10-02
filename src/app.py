"""Phase 6 (tiny UI): Streamlit front end for the Stage B query path.

Run from the repo root:

    streamlit run src/app.py

This module only reads. It calls src.query.answer_question() and never
ingests, never embeds the corpus, and never opens a write path to
data/chroma/ (architecture sections 8 and 9), so restarting the app cannot
re-embed anything. The vector store must already exist from
`python -m src.ingest`; when it does not, the page says so instead of
guessing.

UI surface (PRD section 5.1): welcome line, persistent facts-only note, three
clickable example questions, chat transcript where every assistant turn shows
the body plus one citation link and the last-updated date, and the section 5.3
disclaimer in the sidebar.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import INGEST_HINT, LAST_UPDATED_PREFIX, SOURCES
from src.guardrails import check_question
from src.query import (
    QueryError,
    VectorStoreNotReady,
    answer_question,
    get_collection,
    last_updated,
)

WELCOME = (
    "Ask factual questions about five HDFC Mutual Fund Direct-Growth scheme "
    "pages from Groww. Answers come only from those pages."
)

FACTS_ONLY_NOTE = "Facts-only. No investment advice."

DISCLAIMER = (
    "This assistant answers **facts only** from listed public pages. It is "
    "**not** investment advice, a recommendation to buy or sell, or a "
    "substitute for the scheme information document / key information "
    "memorandum. Mutual fund investments are subject to market risks. Read all "
    "scheme-related documents carefully."
)

EXAMPLE_QUESTIONS = (
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the lock-in for HDFC ELSS Tax Saver?",
    "What is the exit load of HDFC Small Cap Fund Direct Growth?",
)

# FR-9: a message holding identifiers is refused and never kept in the
# transcript, so the session does not become a PII store.
PII_WITHHELD = "_(withheld: this message contained personal identifiers)_"


def render_assistant_turn(message: Dict[str, Any]) -> None:
    """One assistant turn: body, at most one citation link, last-updated line."""
    with st.chat_message("assistant"):
        st.markdown(message["text"])
        if message.get("citation_url"):
            url = message["citation_url"]
            st.markdown(f"Source: [{url}]({url})")
        if message.get("last_updated"):
            st.caption(f"{LAST_UPDATED_PREFIX}{message['last_updated']}")


def render_sidebar() -> None:
    st.sidebar.markdown(f"**{FACTS_ONLY_NOTE}**")
    st.sidebar.divider()
    st.sidebar.markdown("**Sources**")
    for source in SOURCES:
        st.sidebar.markdown(
            f"[{str(source['scheme_name']).replace(' – ', ' ')}]"
            f"({source['source_url']})"
        )
    st.sidebar.divider()
    st.sidebar.caption(f"{LAST_UPDATED_PREFIX}{last_updated()}")
    st.sidebar.caption(DISCLAIMER)
    if st.sidebar.button("Clear chat", width="stretch"):
        st.session_state["messages"] = []
        st.rerun()


def store_is_ready() -> bool:
    """Read-only probe: is there a persisted collection to query?"""
    try:
        return get_collection() is not None
    except VectorStoreNotReady:
        return False


def ask(question: str) -> Optional[Dict[str, Any]]:
    """Run one question through the query path and append the turn to the chat.

    Returns the answer dict, or None when the path failed (the error has
    already been shown, and no half-turn is stored).
    """
    withheld = check_question(question).reason == "pii"
    shown = PII_WITHHELD if withheld else question

    try:
        with st.spinner("Looking this up in the five Groww pages..."):
            result = answer_question(question)
    except QueryError as exc:
        st.error(str(exc))
        if isinstance(exc, VectorStoreNotReady):
            st.code("python -m src.ingest", language="bash")
        return None

    with st.chat_message("user"):
        st.markdown(shown)
    render_assistant_turn(result)

    st.session_state["messages"].extend(
        [
            {"role": "user", "text": shown},
            {
                "role": "assistant",
                "text": result["text"],
                "citation_url": result.get("citation_url"),
                "last_updated": result.get("last_updated"),
            },
        ]
    )
    return result


def main() -> None:
    st.set_page_config(page_title="HDFC Mutual Fund FAQ assistant")
    st.session_state.setdefault("messages", [])

    render_sidebar()
    st.markdown(f"### {WELCOME}")
    st.info(FACTS_ONLY_NOTE)

    if not store_is_ready():
        st.error(f"Vector store is not ready. {INGEST_HINT}")
        st.code("python -m src.ingest", language="bash")
        return

    typed = st.chat_input("Ask a factual question about one of the five HDFC schemes")
    for index, example in enumerate(EXAMPLE_QUESTIONS):
        if st.button(example, key=f"example-{index}", width="stretch"):
            st.session_state["pending_question"] = example

    for message in st.session_state["messages"]:
        if message["role"] == "user":
            with st.chat_message("user"):
                st.markdown(message["text"])
        else:
            render_assistant_turn(message)

    question = typed or st.session_state.pop("pending_question", None)
    if question:
        ask(question)


if __name__ == "__main__":
    main()