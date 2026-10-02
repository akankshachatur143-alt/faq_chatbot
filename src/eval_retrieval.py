"""Phase 4 eval: how good is retrieval on its own, before any LLM is involved.

Runs the gold set below through src.query.retrieve() and reports:

    scheme_hit@k   the expected scheme (category) appears somewhere in the top-k
    section_hit@k  a chunk of the expected scheme *and* section is in the top-k
    fact_hit@k     the expected fact string is inside the top-k text (groundedness)
    top1_scheme    the very first hit is already the right scheme (citation quality)
    MRR            1 / rank of the first scheme+section match

The UNANSWERABLE set is scored separately: it exists to calibrate a similarity
floor for the "I don't have that in the listed sources." path. It does not
enter the gold metrics, because the app may still retrieve close-but-wrong
chunks for those questions - the point is to see how high they score.

No Groq call and no API key: this measures Stage B retrieval only.

CLI:
    py -3 -m src.eval_retrieval                    # report
    py -3 -m src.eval_retrieval --verbose          # also dump every ranking
    py -3 -m src.eval_retrieval --no-scheme-filter # A/B: ranking only, no metadata filter
    py -3 -m src.eval_retrieval --top-k 5
    py -3 -m src.eval_retrieval --fail-under 0.9   # exit 1 if section_hit@k drops below
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.chunking import (
    ABOUT_SECTION,
    EXIT_LOAD_SECTION,
    GLOSSARY_SECTION,
    HISTORY_SECTION,
    MANAGEMENT_SECTION,
    MINIMUM_INVESTMENTS_SECTION,
    SNAPSHOT_SECTION,
)
from src.config import TOP_K
from src.guardrails import check_question
from src.query import RetrievedChunk, retrieve


@dataclass
class GoldCase:
    """One question with the chunk metadata and the fact it must surface.

    category=None means the question names no scheme, so any scheme may match.
    """

    question: str
    category: Optional[str]
    section: str
    fact: str


@dataclass
class CaseResult:
    case: GoldCase
    chunks: List[RetrievedChunk]
    filtered_category: Optional[str] = None
    rank: int = 0
    scheme_hit: bool = False
    section_hit: bool = False
    fact_hit: bool = False
    top1_scheme: bool = False
    blocked: bool = False

    @property
    def top_score(self) -> float:
        return self.chunks[0].score if self.chunks else 0.0


# Facts are quoted from data/chunks.txt so a gold case breaks the moment ingest
# changes the numbers. Section names come from src.chunking, never from literals.
GOLD: List[GoldCase] = [
    # --- large cap -----------------------------------------------------------
    GoldCase("What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
             "large-cap", SNAPSHOT_SECTION, "Expense ratio 1.04%"),
    GoldCase("What is the AUM or fund size of HDFC Large Cap?",
             "large-cap", SNAPSHOT_SECTION, "39,933.36"),
    GoldCase("Minimum investment amount for HDFC Large Cap Direct Growth?",
             "large-cap", MINIMUM_INVESTMENTS_SECTION, "Min. for 1st investment ₹100"),
    GoldCase("What is the exit load of HDFC Large Cap Fund?",
             "large-cap", EXIT_LOAD_SECTION, "1% if redeemed within 1 year"),
    GoldCase("What is the exit load history of HDFC Large Cap Fund?",
             "large-cap", HISTORY_SECTION, "Exit load of 1% if redeemed within 18 months"),
    GoldCase("Who manages HDFC Large Cap Fund Direct Growth?",
             "large-cap", MANAGEMENT_SECTION, "Rahul Baijal"),
    GoldCase("What is the risk rating of HDFC Large Cap Fund Direct Growth?",
             "large-cap", ABOUT_SECTION, "rated Very High risk"),
    GoldCase("When was HDFC Large Cap Fund Direct Growth launched?",
             "large-cap", ABOUT_SECTION, "made available to investors on 10 Dec 1999"),
    GoldCase("What is the benchmark of HDFC Large Cap Fund?",
             "large-cap", ABOUT_SECTION, "NIFTY 100 Total Return Index"),
    # --- flexi cap / equity --------------------------------------------------
    GoldCase("What is the expense ratio of HDFC Equity Fund Direct Growth?",
             "flexi-cap", SNAPSHOT_SECTION, "Expense ratio 0.77%"),
    GoldCase("What is the fund size of HDFC Flexi Cap fund?",
             "flexi-cap", SNAPSHOT_SECTION, "1,13,606.46"),
    GoldCase("Minimum investment for HDFC Flexi Cap Direct Growth?",
             "flexi-cap", MINIMUM_INVESTMENTS_SECTION, "Min. for 2nd investment ₹100"),
    GoldCase("What is the exit load on HDFC Equity Fund?",
             "flexi-cap", EXIT_LOAD_SECTION, "1% if redeemed within 1 year"),
    GoldCase("Who is the fund manager of HDFC Equity Fund Direct Growth?",
             "flexi-cap", MANAGEMENT_SECTION, "Dhruv Muchhal"),
    GoldCase("What is the stamp duty on HDFC Equity Fund?",
             "flexi-cap", EXIT_LOAD_SECTION, "Stamp duty on investment: 0.005%"),
    GoldCase("What is the benchmark of HDFC Equity Fund?",
             "flexi-cap", ABOUT_SECTION, "NIFTY 500 Total Return Index"),
    # --- ELSS ----------------------------------------------------------------
    GoldCase("What is the expense ratio of HDFC ELSS Tax Saver Fund?",
             "elss", SNAPSHOT_SECTION, "Expense ratio 1.21%"),
    GoldCase("Minimum SIP for HDFC ELSS Tax Saver Fund?",
             "elss", MINIMUM_INVESTMENTS_SECTION, "Min. for SIP ₹500"),
    GoldCase("Is there an exit load on HDFC ELSS Tax Saver Fund?",
             "elss", EXIT_LOAD_SECTION, "Exit load Nil"),
    GoldCase("Who manages HDFC ELSS Tax Saver Fund Direct Plan Growth?",
             "elss", MANAGEMENT_SECTION, "Amar Kalkundrikar"),
    GoldCase("What is the lock-in period of HDFC ELSS Tax Saver Fund?",
             "elss", ABOUT_SECTION, "Minimum Lumpsum Investment is ₹500"),
    # --- small cap -----------------------------------------------------------
    GoldCase("What is the expense ratio of HDFC Small Cap Fund Direct Growth?",
             "small-cap", SNAPSHOT_SECTION, "Expense ratio 0.79%"),
    GoldCase("Exit load of HDFC Small Cap Fund?",
             "small-cap", EXIT_LOAD_SECTION, "1% if redeemed within 1 year"),
    GoldCase("What is the minimum lump sum for HDFC Small Cap Fund?",
             "small-cap", ABOUT_SECTION, "Minimum Lumpsum Investment is ₹100"),
    GoldCase("Who manages HDFC Small Cap Fund?",
             "small-cap", MANAGEMENT_SECTION, "Chirag Setalvad"),
    GoldCase("What is the benchmark of HDFC Small Cap Fund?",
             "small-cap", ABOUT_SECTION, "BSE 250 SmallCap Total Return Index"),
    GoldCase("What is the exit load history of HDFC Small Cap Fund?",
             "small-cap", HISTORY_SECTION, "Exit load of 1% if redeemed within 1 year"),
    # --- balanced advantage --------------------------------------------------
    GoldCase("What is the expense ratio of HDFC Balanced Advantage Fund?",
             "hybrid", SNAPSHOT_SECTION, "Expense ratio 0.78%"),
    GoldCase("Minimum SIP for HDFC Balanced Advantage Fund Direct Growth?",
             "hybrid", MINIMUM_INVESTMENTS_SECTION, "Min. for SIP ₹100"),
    GoldCase("What is the exit load of HDFC Balanced Advantage Fund?",
             "hybrid", EXIT_LOAD_SECTION, "in excess of 15% of the investment"),
    GoldCase("Who manages HDFC Balanced Advantage Fund?",
             "hybrid", MANAGEMENT_SECTION, "Anil Bamboli"),
    GoldCase("What is the risk category of HDFC Balanced Advantage Fund?",
             "hybrid", ABOUT_SECTION, "rated Very High risk"),
    GoldCase("What is the benchmark of HDFC Balanced Advantage Fund?",
             "hybrid", ABOUT_SECTION, "NIFTY 50 Hybrid Composite Debt 50:50 Index"),
    # --- no scheme named: any scheme may match -------------------------------
    GoldCase("What is an expense ratio?",
             None, GLOSSARY_SECTION, "total percentage of a company's fund assets"),
    GoldCase("What is stamp duty?",
             None, GLOSSARY_SECTION, "A form of tax payable for the purchase or sale"),
    GoldCase("What is exit load?",
             None, GLOSSARY_SECTION, "exiting a fund (fully or partially) before"),
    GoldCase("What is the minimum first-time investment for these direct growth plans?",
             None, MINIMUM_INVESTMENTS_SECTION, "Min. for 1st investment"),
    GoldCase("Who are the fund managers mentioned on these HDFC pages?",
             None, MANAGEMENT_SECTION, "Fund management:"),
]

# Questions the corpus cannot answer. They reach retrieval (guardrails do not
# block them) but must end in UNKNOWN_ANSWER, so their top score is the cost of
# a wrong similarity floor.
UNANSWERABLE: List[GoldCase] = [
    GoldCase("What is the expense ratio of HDFC Mid Cap Fund?",
             None, SNAPSHOT_SECTION, ""),
    GoldCase("Who is the CEO of HDFC Asset Management?",
             None, MANAGEMENT_SECTION, ""),
    GoldCase("What is the lock-in period of HDFC Large Cap Fund?",
             None, ABOUT_SECTION, ""),
    GoldCase("How many stocks does HDFC Small Cap Fund hold?",
             None, SNAPSHOT_SECTION, ""),
    GoldCase("What is the registered address of HDFC Mutual Fund?",
             None, ABOUT_SECTION, ""),
    GoldCase("What is the TER of HDFC Balanced Advantage Fund?",
             None, GLOSSARY_SECTION, ""),
    GoldCase("Who managed HDFC Small Cap Fund in 2010?",
             None, MANAGEMENT_SECTION, ""),
    GoldCase("Is there an exit load waiver on HDFC Large Cap Fund?",
             None, EXIT_LOAD_SECTION, ""),
]


def force_utf8_stdout() -> None:
    """Chunk text carries the rupee sign; the Windows default console cannot print it."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # already detached or not a TextIOWrapper
            pass


def matches(case: GoldCase, chunk: RetrievedChunk) -> bool:
    if case.category and chunk.metadata.get("category") != case.category:
        return False
    return chunk.section == case.section


def run_case(
    case: GoldCase, top_k: int, use_scheme_filter: bool, verbose_categories: bool = False
) -> CaseResult:
    if check_question(case.question).blocked:
        return CaseResult(case=case, chunks=[], blocked=True)

    chunks = retrieve(case.question, top_k=top_k, use_scheme_filter=use_scheme_filter)
    result = CaseResult(case=case, chunks=chunks)
    result.scheme_hit = any(
        chunk.metadata.get("category") == case.category for chunk in chunks
    ) if case.category else bool(chunks)
    for rank, chunk in enumerate(chunks, start=1):
        if matches(case, chunk):
            result.rank = rank
            break
    result.section_hit = result.rank > 0
    context = "\n".join(chunk.text for chunk in chunks).lower()
    result.fact_hit = bool(case.fact) and case.fact.lower() in context
    result.top1_scheme = bool(chunks) and (
        not case.category or chunks[0].metadata.get("category") == case.category
    )
    return result


def _ratio(passed: int, total: int) -> float:
    return passed / total if total else 0.0


@dataclass
class Metrics:
    total: int = 0
    scheme_hit: int = 0
    section_hit: int = 0
    fact_hit: int = 0
    top1_scheme: int = 0
    reciprocal_rank: float = 0.0
    per_category: Dict[str, List[int]] = field(default_factory=dict)

    @property
    def mrr(self) -> float:
        return self.reciprocal_rank / self.total if self.total else 0.0

    def rows(self) -> List[str]:
        total = self.total or 1
        lines = [
            f"  questions            {self.total}",
            f"  scheme_hit@{TOP_K:<11} {_ratio(self.scheme_hit, total):.3f}"
            f"  ({self.scheme_hit}/{self.total})",
            f"  section_hit@{TOP_K:<10} {_ratio(self.section_hit, total):.3f}"
            f"  ({self.section_hit}/{self.total})",
            f"  fact_hit@{TOP_K:<12} {_ratio(self.fact_hit, total):.3f}"
            f"  ({self.fact_hit}/{self.total})",
            f"  top1_scheme          {_ratio(self.top1_scheme, total):.3f}"
            f"  ({self.top1_scheme}/{self.total})",
            f"  MRR                  {self.mrr:.3f}",
        ]
        return lines


def collect(results: Sequence[CaseResult]) -> Metrics:
    metrics = Metrics()
    for result in results:
        if result.blocked:
            continue
        metrics.total += 1
        metrics.scheme_hit += int(result.scheme_hit)
        metrics.section_hit += int(result.section_hit)
        metrics.fact_hit += int(result.fact_hit)
        metrics.top1_scheme += int(result.top1_scheme)
        if result.rank:
            metrics.reciprocal_rank += 1.0 / result.rank
        label = result.case.category or "any"
        bucket = metrics.per_category.setdefault(label, [0, 0, 0])
        bucket[0] += 1
        bucket[1] += int(result.section_hit)
        bucket[2] += int(result.top1_scheme)
    return metrics


def format_ranking(chunks: Sequence[RetrievedChunk]) -> List[str]:
    if not chunks:
        return ["    (no chunks retrieved)"]
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(
            f"    [{i}] id={chunk.chunk_id:<3} score={chunk.score:.4f} "
            f"category={chunk.metadata.get('category', '?'):<10} "
            f"section={chunk.section}"
        )
    return lines


def report(
    results: Sequence[CaseResult],
    top_k: int,
    verbose: bool,
    use_scheme_filter: bool,
    failures_only: bool = False,
) -> None:
    metrics = collect(results)
    for result in results:
        if result.blocked:
            print(f"BLOCKED (guardrail, no retrieval): {result.case.question}")
            print(f"    -> {check_question(result.case.question).reason}")
    print("--- gold set ---")
    for line in metrics.rows():
        print(line)
    if metrics.per_category:
        print("  by scheme          section_hit@k / top1_scheme")
        for label in sorted(metrics.per_category):
            total, section, top1 = metrics.per_category[label]
            print(f"    {label:<12} {section}/{total}  {top1}/{total}")

    print("--- failures ---")
    shown = 0
    for result in results:
        if result.blocked:
            continue
        failed = not (result.section_hit and result.fact_hit and result.top1_scheme)
        if not failed:
            continue
        shown += 1
        case = result.case
        missing = [
            name
            for name, ok in (
                ("scheme_hit", result.scheme_hit),
                ("section_hit", result.section_hit),
                ("fact_hit", result.fact_hit),
                ("top1_scheme", result.top1_scheme),
            )
            if not ok
        ]
        print(f"  FAIL[{','.join(missing)}] {case.question}")
        print(f"    want category={case.category or 'any'} section={case.section}")
        print(f"    want fact: {case.fact}")
        for line in format_ranking(result.chunks):
            print(line)
    if not shown:
        print("  none")

    if verbose:
        print("--- every ranking ---")
        for result in results:
            if result.blocked:
                continue
            print(f"  {result.case.question}")
            for line in format_ranking(result.chunks):
                print(line)


def report_unanswerable(results: Sequence[CaseResult]) -> None:
    print("--- unanswerable (similarity floor calibration) ---")
    scored = sorted(
        (r for r in results if r.chunks), key=lambda r: r.top_score, reverse=True
    )
    for result in scored:
        print(
            f"  top1={result.top_score:.4f} category="
            f"{result.chunks[0].metadata.get('category', '?')} | {result.case.question}"
        )
    print(f"  questions scored   {len(scored)}/{len(results)}")
    print(f"  max top1 score     {scored[0].top_score:.4f}" if scored else "  no scores")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline retrieval eval on the gold set (no Groq, no API key)."
    )
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--verbose", action="store_true", help="dump every ranking")
    parser.add_argument(
        "--no-scheme-filter",
        action="store_true",
        help="A/B the metadata filter off: pure embedding ranking",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="exit 1 when section_hit@k falls below this ratio",
    )
    args = parser.parse_args(argv)

    force_utf8_stdout()
    use_filter = not args.no_scheme_filter
    print(
        f"retrieval eval | top_k={args.top_k} | "
        f"scheme_filter={'on' if use_filter else 'off'}"
    )

    gold_results = [run_case(case, args.top_k, use_filter) for case in GOLD]
    report(gold_results, args.top_k, args.verbose, use_filter)

    unknown_results = [run_case(case, args.top_k, use_filter) for case in UNANSWERABLE]
    report_unanswerable(unknown_results)

    metrics = collect(gold_results)
    ratio = _ratio(metrics.section_hit, metrics.total)
    if args.fail_under is not None and ratio < args.fail_under:
        print(f"FAIL: section_hit@{args.top_k} {ratio:.3f} < {args.fail_under:.3f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())