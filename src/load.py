"""Phase 1: load and clean the five Groww pages. No chunking, embed, or Chroma."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config import INGEST_META_PATH, RAW_DIR, SOURCES, USER_AGENT

DROP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "footer",
        "header",
        "iframe",
        "form",
        "button",
    }
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        joined = " ".join(self._parts)
        return re.sub(r"\s+", " ", joined).strip()


def fetch_html(url: str, timeout: int = 30) -> tuple[int | None, str | None, str | None]:
    """Return (status, html, error)."""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or 200
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return status, raw.decode(charset, errors="replace"), None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body or None, f"HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        return None, None, f"URL error: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 — surface fetch failures in meta
        return None, None, str(exc)


def html_to_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser.text()


def trim_groww_chrome(text: str) -> str:
    """Keep scheme title + fact body; drop site nav and SEO footer."""
    title = text.split(" - NAV", 1)[0].strip()
    start = text.find("Min. for SIP")
    if start == -1:
        start = text.find("Expense ratio")
    body = text[start:] if start != -1 else text
    for marker in ("Home > Mutual Funds", "© 2016", "Vaishnavi Tech Park"):
        cut = body.find(marker)
        if cut != -1:
            body = body[:cut]
    combined = f"{title}. {body}".strip() if title and not body.startswith(title) else body
    return re.sub(r"\s+", " ", combined).strip()


def inspect_facts(text: str) -> dict[str, bool]:
    lower = text.lower()
    return {
        "expense_ratio": "expense ratio" in lower or "expense-ratio" in lower,
        "exit_load": "exit load" in lower,
        "sip": "sip" in lower or "systematic" in lower,
        "lock_in": "lock-in" in lower or "lock in" in lower or "lockin" in lower,
        "riskometer": (
            "riskometer" in lower
            or "risk-o-meter" in lower
            or "very high risk" in lower
        ),
        "benchmark": "benchmark" in lower,
        "statement": "statement" in lower and ("capital" in lower or "download" in lower),
    }


def read_raw_text(slug: str) -> str:
    """Return the saved clean text for a slug, or '' when it was never saved."""
    path = RAW_DIR / f"{slug}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_raw(slug: str, html: str | None, text: str, error: str | None) -> dict[str, str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    if html:
        html_path = RAW_DIR / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")
        paths["html"] = str(html_path.relative_to(RAW_DIR.parent.parent))
    txt_path = RAW_DIR / f"{slug}.txt"
    if error and not text:
        txt_path.write_text(f"[FETCH FAILED]\n{error}\n", encoding="utf-8")
    else:
        txt_path.write_text(text, encoding="utf-8")
    paths["txt"] = str(txt_path.relative_to(RAW_DIR.parent.parent))
    return paths


def load_all(refetch: bool = False) -> dict:
    """Fetch the five pages, or reuse data/raw/*.txt when they already exist.

    refetch=False keeps chunking deterministic against the Phase 1 snapshot.
    """
    meta_path = INGEST_META_PATH
    previous = {}
    if not refetch and meta_path.exists():
        try:
            previous = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    prev_pages = {p.get("slug"): p for p in previous.get("pages", [])}

    fetched_at = previous.get("fetched_at") or date.today().isoformat()
    fetched_at_utc = previous.get("fetched_at_utc") or datetime.now(timezone.utc).isoformat()
    pages: list[dict] = []

    for source in SOURCES:
        cached = prev_pages.get(source["slug"])
        cached_text = read_raw_text(source["slug"])
        if cached and cached_text and not refetch:
            pages.append({**cached, "fetch": "cached"})
            continue
        status, html, error = fetch_html(source["source_url"])
        text = trim_groww_chrome(html_to_text(html)) if html else ""
        paths = save_raw(source["slug"], html, text, error)
        facts = inspect_facts(text) if text else {k: False for k in inspect_facts("").keys()}
        pages.append(
            {
                "category": source["category"],
                "scheme_name": source["scheme_name"],
                "source_url": source["source_url"],
                "slug": source["slug"],
                "http_status": status,
                "error": error,
                "char_count": len(text),
                "facts_present": facts,
                "files": paths,
                "fetch": "http",
            }
        )

    meta = {
        "fetched_at": fetched_at,
        "fetched_at_utc": fetched_at_utc,
        "phase": 1,
        "chroma_written": False,
        "pages": pages,
    }
    INGEST_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    INGEST_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def print_summary(meta: dict) -> None:
    print(f"fetched_at: {meta['fetched_at']}")
    for page in meta["pages"]:
        facts = ", ".join(k for k, v in page["facts_present"].items() if v) or "(none detected)"
        err = f" error={page['error']}" if page["error"] else ""
        print(
            f"- {page['category']}: {page['char_count']} chars "
            f"status={page['http_status']}{err} facts=[{facts}]"
        )


if __name__ == "__main__":
    print_summary(load_all())
