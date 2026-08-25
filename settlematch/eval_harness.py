# EVALUATION HARNESS
# Computes the 4 metrics the track brief requires:
#   1. Match rate % — how many records matched
#   2. Throughput — records per second (wall-clock timed)
#   3. LLM call rate % — % needing AI help (lower = better rule engine)
#   4. Exception breakdown — WHY records failed (6 named categories)

# The 6 exception categories from 03-flow.md Step 6
EXCEPTION_CATEGORIES = [
    "UTR_MISMATCH",         # UTR fuzzy-matched but still ambiguous
    "AMOUNT_DELTA",         # Amount beyond tolerance, LLM couldn't explain
    "DATE_LAG",             # Date outside T+2 window
    "BATCH_SPLIT",          # One bank UTR maps to multiple settlements
    "LLM_ESCALATED",        # LLM failed or couldn't decide
    "MISSING_COUNTERPART",  # No bank or ledger entry found at all
]

# Decisions that count as "matched"
MATCHED_DECISIONS = {"AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED", "LLM_MATCHED"}
LLM_DECISIONS = {"LLM_MATCHED", "LLM_ESCALATED"}


def categorize_exceptions(results) -> dict[str, list]:
    """
    Sort unmatched records into 6 named buckets.
    Uses exception_category field from MatchResult if available,
    otherwise falls back to decision-based classification.
    """
    buckets = {cat: [] for cat in EXCEPTION_CATEGORIES}

    for r in results:
        d_val = getattr(r, "decision", r)
        d = str(getattr(d_val, "value", d_val))

        # Skip matched records — they're not exceptions
        if d in MATCHED_DECISIONS:
            continue

        # Use exception_category field if available (carried through LLM adjudication)
        exc_cat = getattr(r, "exception_category", None)

        if exc_cat and exc_cat in buckets:
            buckets[exc_cat].append(r)
        elif d == "MISSING_COUNTERPART":
            buckets["MISSING_COUNTERPART"].append(r)
        elif d == "LLM_ESCALATED":
            buckets["LLM_ESCALATED"].append(r)
        elif d in {"LLM_CANDIDATE", "FUZZY_CANDIDATE"}:
            # Fallback: classify based on amount/date deltas
            if hasattr(r, "amount_delta") and r.amount_delta is not None and r.amount_delta > 1.0:
                buckets["AMOUNT_DELTA"].append(r)
            elif hasattr(r, "date_delta_days") and r.date_delta_days is not None and r.date_delta_days > 2:
                buckets["DATE_LAG"].append(r)
            else:
                buckets["LLM_ESCALATED"].append(r)
        else:
            buckets["LLM_ESCALATED"].append(r)

    return buckets


def compute_metrics(results, elapsed: float, llm_calls: int, total: int) -> dict:
    """
    Compute all 4 required metrics from the results list.
    Returns a dict with match rate, throughput, LLM call rate, exception breakdown.
    """
    matched = sum(
        1 for r in results
        if str(getattr(r.decision if hasattr(r, "decision") else r, "value", getattr(r, "decision", r))) in MATCHED_DECISIONS
    )

    exceptions = categorize_exceptions(results)
    exception_summary = {cat: len(records) for cat, records in exceptions.items()}

    return {
        "total_records": total,
        "matched": matched,
        "match_rate_pct": round(matched / total * 100, 1) if total > 0 else 0.0,
        "throughput_rec_per_sec": round(total / elapsed, 1) if elapsed > 0 else 0.0,
        "llm_call_rate_pct": round(llm_calls / total * 100, 1) if total > 0 else 0.0,
        "elapsed_seconds": round(elapsed, 2),
        "exception_count": total - matched,
        "exception_breakdown": exception_summary,
        "exceptions": exceptions,
    }


def print_metrics(metrics: dict) -> None:
    """Print results in a clean, human-readable format."""
    print(f"\n{'='*50}")
    print(f"  SettleMatch — Evaluation Results")
    print(f"{'='*50}")
    print(f"  Match rate:          {metrics['match_rate_pct']}%  ({metrics['matched']}/{metrics['total_records']})")
    print(f"  Throughput:          {metrics['throughput_rec_per_sec']} records/sec")
    print(f"  LLM call rate:       {metrics['llm_call_rate_pct']}%")
    print(f"  Wall-clock time:     {metrics['elapsed_seconds']}s")
    print(f"  Exceptions:          {metrics['exception_count']}")
    print(f"{'='*50}")

    # Show exception breakdown only if there are exceptions
    if any(v > 0 for v in metrics["exception_breakdown"].values()):
        print(f"\n  Exception Breakdown:")
        for cat, count in metrics["exception_breakdown"].items():
            if count > 0:
                print(f"    {cat}: {count}")
        print()
