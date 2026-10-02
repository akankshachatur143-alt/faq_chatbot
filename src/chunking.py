"""Phase 2: section-aware chunking of the saved Groww pages (no embed, no Chroma).

Strategy is locked in docs/chunking.md. In short: split on the repeated
fact-block markers Groww renders into fixed sections, drop the sections that
are noise for an FAQ (holdings, return calculator, peer comparison, AMC
contact details), then pack a section into <=CHUNK_MAX_CHARS pieces with
~CHUNK_OVERLAP_RATIO overlap on sentence boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional, Pattern, Sequence, Tuple, Union

from src.config import (
    CHUNK_MAX_CHARS,
    CHUNK_MIN_CHARS,
    CHUNK_OVERLAP_RATIO,
    CHUNKS_TXT_PATH,
    RAW_DIR,
    SOURCES,
)

Marker = Union[str, Pattern]

# Groww renders these markers in this order on every scheme page.
EXIT_LOAD_HISTORY_RE = re.compile(r"Exit Load \d{2} \w{3} \d{4}")
EXIT_LOAD_DETAIL_END_RE = re.compile(r"Check past data|Compare similar funds|Fund management")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u20b9\"'(])")
WHITESPACE_RE = re.compile(r"\s+")
MANAGER_ENTRY_RE = re.compile(
    r"[A-Z]{2} [A-Z][A-Za-z]+ [A-Z][A-Za-z]+ "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} - Present"
)
ALSO_MANAGES_RE = re.compile(r"\s*Also manages these schemes")
VIEW_DETAILS_RE = re.compile(r"\s*View details")
SENTENCE_ABBREVS = ("Mr.", "Mrs.", "Ms.", "Dr.")
SENTINEL = "\x00"
GLOSSARY_TERMS = ("Expense ratio", "Tax", "Exit load", "Stamp duty")

SNAPSHOT_SECTION = "Scheme snapshot"
MINIMUM_INVESTMENTS_SECTION = "Minimum investments"
GLOSSARY_SECTION = "Glossary: expense ratio, tax, exit load, stamp duty"
HISTORY_SECTION = "Exit load history by effective date"
EXIT_LOAD_SECTION = "Exit load, stamp duty and tax"
MANAGEMENT_SECTION = "Fund management"
ABOUT_SECTION = "About the scheme"


@dataclass
class SectionRule:
    """One span of page text, named after the Groww block it came from."""

    name: str
    keep: bool
    start_marker: Optional[Marker] = None
    end_marker: Optional[Marker] = None
    cleanup: Optional[str] = None


@dataclass
class SectionText:
    """Kept section content, ready to be packed into chunks."""

    name: str
    text: str


@dataclass
class Chunk:
    chunk_id: int
    scheme_name: str
    category: str
    source_url: str
    slug: str
    section: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_metadata(self) -> dict:
        return {
            "scheme_name": self.scheme_name,
            "category": self.category,
            "source_url": self.source_url,
            "slug": self.slug,
            "section": self.section,
        }


@dataclass
class SectionSpec:
    sections: List[SectionText] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)


def normalize(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def section_plan() -> List[SectionRule]:
    """Ordered spans of a Groww page, from the first marker to the last."""
    return [
        SectionRule(SNAPSHOT_SECTION, True, None, "Return calculator"),
        SectionRule("Return calculator", False, "Return calculator", "Holdings ("),
        SectionRule("Holdings", False, "Holdings (", "See All"),
        SectionRule(
            MINIMUM_INVESTMENTS_SECTION, True, "See All", "Understand terms"
        ),
        SectionRule("Returns glossary", False, "Understand terms", "Returns and rankings"),
        SectionRule("Returns and rankings", False, "Returns and rankings", "Understand terms"),
        SectionRule(
            GLOSSARY_SECTION,
            True,
            "Understand terms",
            EXIT_LOAD_HISTORY_RE,
            cleanup="glossary",
        ),
        SectionRule(HISTORY_SECTION, True, EXIT_LOAD_HISTORY_RE, EXIT_LOAD_SECTION),
        SectionRule(EXIT_LOAD_SECTION, True, EXIT_LOAD_SECTION, EXIT_LOAD_DETAIL_END_RE),
        SectionRule(MANAGEMENT_SECTION, True, MANAGEMENT_SECTION, "About HDFC", cleanup="managers"),
        SectionRule(ABOUT_SECTION, True, "About HDFC", "Scheme Information Document(SID)"),
        SectionRule("AMC contact details", False, "Scheme Information Document(SID)", None),
    ]


def _find(text: str, marker: Marker, start: int = 0) -> int:
    if isinstance(marker, str):
        idx = text.find(marker, start)
    else:
        match = marker.search(text, start)
        idx = match.start() if match else -1
    return idx


def _apply_cleanup(name: str, body: str, cleanup: Optional[str]) -> str:
    body = normalize(body)
    if name == MINIMUM_INVESTMENTS_SECTION:
        body = re.sub(r"^(?:(?:See All|Minimum investments)\s*)+", "", body)
    elif name == EXIT_LOAD_SECTION:
        body = re.sub(rf"^{re.escape(name)}\s*", "", body)
    elif name == ABOUT_SECTION:
        body = re.sub(r"^About\s+", "", body)
        body = re.sub(r"^(.+?) \1 is a ", r"\1 is a ", body)
    elif cleanup == "glossary":
        body = re.sub(r"^Understand terms\s*", "", body)
    return body


def _split_glossary(body: str) -> List[str]:
    """One unit per glossary term so a definition is never split from its term."""
    body = normalize(re.sub(r"^Understand terms\s*", "", body))
    if not body:
        return []
    positions = sorted(
        (idx, term) for term in GLOSSARY_TERMS if (idx := body.find(term)) != -1
    )
    units: List[str] = []
    for i, (idx, _) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        units.append(body[idx:end].strip())
    return [unit for unit in units if unit]


def _strip_scheme_lists(body: str) -> str:
    """Delete each 'Also manages these schemes ...' block up to the next manager entry."""
    entries = [m.start() for m in MANAGER_ENTRY_RE.finditer(body)]
    pieces: List[str] = []
    cursor = 0
    for match in ALSO_MANAGES_RE.finditer(body):
        if match.start() < cursor:
            continue
        end = next((start for start in entries if start >= match.end()), len(body))
        pieces.append(body[cursor : match.start()])
        cursor = end
    pieces.append(body[cursor:])
    return normalize("".join(pieces))


def _split_managers(body: str) -> List[str]:
    """One unit per fund manager, so the name never separates from its tenure/bio."""
    body = _strip_scheme_lists(body)
    body = re.sub(r"^Fund management\s*", "", body)
    starts = [m.start() for m in MANAGER_ENTRY_RE.finditer(body)]
    if not starts:
        return [body] if body else []
    units: List[str] = []
    lead = body[: starts[0]].strip()
    if lead:
        units.append(lead)
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        unit = normalize(VIEW_DETAILS_RE.sub("", body[start:end]))
        if unit:
            units.append(unit)
    return units


def split_sections(text: str) -> SectionSpec:
    """Map the flat page text onto named Groww sections."""
    if not normalize(text):
        return SectionSpec()
    if "Return calculator" not in text and "About HDFC" not in text:
        return SectionSpec(
            sections=window_fallback(text), dropped=["Unstructured page -> character windows"]
        )
    spec = SectionSpec()
    cursor = 0
    for section in section_plan():
        start = cursor if section.start_marker is None else _find(text, section.start_marker, cursor)
        if start == -1 or start < cursor:
            continue
        if section.end_marker is None:
            end = len(text)
        else:
            end = _find(text, section.end_marker, start + 1)
            if end == -1:
                end = len(text)
        body = _apply_cleanup(section.name, text[start:end], section.cleanup)
        if section.keep and body:
            sub_units: List[str] = [body]
            if section.cleanup == "glossary":
                sub_units = _split_glossary(body)
            elif section.cleanup == "managers":
                sub_units = _split_managers(body)
            for unit in sub_units:
                spec.sections.append(SectionText(section.name, unit))
        else:
            spec.dropped.append(section.name)
        cursor = max(end, start + 1)
    if cursor < len(text):
        spec.dropped.append("Trailing text")
    return spec


def window_fallback(
    text: str, max_chars: int = CHUNK_MAX_CHARS, overlap_ratio: float = CHUNK_OVERLAP_RATIO
) -> List[SectionText]:
    """Architecture fallback (~400-600 chars, 10-15% overlap) for an unstructured dump."""
    text = normalize(text)
    if not text:
        return []
    step = max(1, int(max_chars * (1 - overlap_ratio)))
    windows: List[SectionText] = []
    for start in range(0, len(text), step):
        piece = text[start : start + max_chars]
        if piece:
            windows.append(SectionText("Page text (character window)", piece))
    return windows


def _sentence_units(text: str) -> List[str]:
    protected = text
    for abbr in SENTENCE_ABBREVS:
        protected = protected.replace(abbr, abbr[:-1] + SENTINEL)
    units = [normalize(part.replace(SENTINEL, ".")) for part in SENTENCE_SPLIT_RE.split(protected)]
    return [unit for unit in units if unit]


def _pack_units(units: Sequence[str], max_chars: int, overlap_chars: int) -> List[str]:
    """Greedily pack units; start a new chunk at a unit boundary, carry ~overlap."""
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for unit in units:
        unit_len = len(unit) + (1 if current else 0)
        if current and current_len + unit_len > max_chars:
            chunks.append(" ".join(current))
            carry: List[str] = []
            carry_len = 0
            for prev in reversed(current):
                prev_len = len(prev) + (1 if carry else 0)
                if carry_len + prev_len > overlap_chars:
                    break
                carry.insert(0, prev)
                carry_len += prev_len
            current = carry
            current_len = carry_len
            unit_len = len(unit) + (1 if current else 0)
        current.append(unit)
        current_len += unit_len
    if current:
        chunks.append(" ".join(current))
    return chunks


def _merge_short_tail(chunks: List[str], min_chars: int, max_chars: int) -> List[str]:
    merged: List[str] = []
    for chunk in chunks:
        if merged and len(chunk) < min_chars and len(merged[-1]) + 1 + len(chunk) <= max_chars:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
    return merged


def pack_section(body: str, max_chars: int, min_chars: int, overlap_ratio: float) -> List[str]:
    units = _sentence_units(body)
    if not units:
        return []
    packed = _pack_units(units, max_chars, int(max_chars * overlap_ratio))
    return _merge_short_tail(packed, min_chars, max_chars)


def build_chunk_text(scheme_name: str, category: str, section: str, body: str) -> str:
    return normalize(f"{scheme_name} ({category}). {section}: {body}")


def chunk_page(
    text: str, source: dict, chunk_id_start: int = 0
) -> Tuple[List[Chunk], SectionSpec]:
    spec = split_sections(text)
    chunks: List[Chunk] = []
    next_id = chunk_id_start
    for section in spec.sections:
        for body in pack_section(
            section.text, CHUNK_MAX_CHARS, CHUNK_MIN_CHARS, CHUNK_OVERLAP_RATIO
        ):
            chunks.append(
                Chunk(
                    chunk_id=next_id,
                    scheme_name=source["scheme_name"],
                    category=source["category"],
                    source_url=source["source_url"],
                    slug=source["slug"],
                    section=section.name,
                    text=build_chunk_text(
                        source["scheme_name"], source["category"], section.name, body
                    ),
                )
            )
            next_id += 1
    return chunks, spec


def read_raw_text(slug: str) -> str:
    path = RAW_DIR / f"{slug}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def chunk_corpus(sources: Optional[Iterable[dict]] = None) -> Tuple[List[Chunk], List[dict]]:
    sources = list(sources if sources is not None else SOURCES)
    chunks: List[Chunk] = []
    pages: List[dict] = []
    for source in sources:
        text = read_raw_text(source["slug"])
        page_chunks, spec = chunk_page(text, source, len(chunks))
        chunks.extend(page_chunks)
        pages.append(
            {
                "scheme_name": source["scheme_name"],
                "category": source["category"],
                "source_url": source["source_url"],
                "slug": source["slug"],
                "raw_chars": len(text),
                "chunk_count": len(page_chunks),
                "sections_kept": sorted({c.section for c in page_chunks}),
                "sections_dropped": spec.dropped,
            }
        )
    return chunks, pages


def format_chunks_txt(chunks: Sequence[Chunk], fetched_at: str) -> str:
    total_chars = sum(c.char_count for c in chunks)
    lines = [
        "# HDFC Mutual Fund FAQ chunks (Groww corpus, Phase 2)",
        f"# fetched_at: {fetched_at}",
        f"# chunker: section-aware, max {CHUNK_MAX_CHARS} chars, "
        f"{int(CHUNK_OVERLAP_RATIO * 100)}% overlap - see docs/chunking.md",
        f"# chunks: {len(chunks)} | total_chars: {total_chars}",
        "# fields: source_url / scheme_name / category are chunk metadata; text is embedded as-is.",
        "",
    ]
    for chunk in chunks:
        lines.extend(
            [
                f"--- chunk_id: {chunk.chunk_id} ---",
                f"scheme: {chunk.scheme_name}",
                f"category: {chunk.category}",
                f"source_url: {chunk.source_url}",
                f"section: {chunk.section}",
                f"chars: {chunk.char_count}",
                "",
                chunk.text,
                "",
            ]
        )
    return "\n".join(lines)


def write_chunks_txt(chunks: Sequence[Chunk], fetched_at: str = "") -> str:
    CHUNKS_TXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = fetched_at or date.today().isoformat()
    CHUNKS_TXT_PATH.write_text(format_chunks_txt(chunks, stamp), encoding="utf-8")
    return str(CHUNKS_TXT_PATH)


def summarize(chunks: Sequence[Chunk], pages: Sequence[dict]) -> None:
    print(f"chunks: {len(chunks)} | chars: {sum(c.char_count for c in chunks)}")
    for page in pages:
        print(
            f"- {page['category']}: {page['raw_chars']} raw chars -> "
            f"{page['chunk_count']} chunks | kept={page['sections_kept']}"
        )
    lengths = [c.char_count for c in chunks]
    if lengths:
        print(
            f"chunk size min/avg/max: {min(lengths)}/"
            f"{sum(lengths) // len(lengths)}/{max(lengths)}"
        )