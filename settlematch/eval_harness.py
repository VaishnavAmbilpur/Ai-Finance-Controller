EXCEPTION_CATEGORIES = [
    "UTR_MISMATCH",
    "AMOUNT_DELTA",
    "DATE_LAG",
    "BATCH_SPLIT",
    "LLM_ESCALATED",
    "MISSING_COUNTERPART",
]

MATCHED_DECISIONS = {"AUTO_APPROVED", "FUZZY_APPROVED", "LLM_MATCHED"}
LLM_DECISIONS = {"LLM_MATCHED", "LLM_ESCALATED"}


def categorize_exceptions(results) -> dict[str, list]:
    buckets = {cat: [] for cat in EXCEPTION_CATEGORIES}

    for r in results:
        d = r.decision if hasattr(r, "decision") else str(r.decision)

        if hasattr(d, "value"):
            d = d.value

        if d in MATCHED_DECISIONS:
            continue

        if d == "MISSING_COUNTERPART":
            buckets["MISSING_COUNTERPART"].append(r)
        elif d == "LLM_ESCALATED":
            buckets["LLM_ESCALATED"].append(r)
        elif d == "LLM_CANDIDATE":
            buckets["AMOUNT_DELTA"].append(r)
        elif d == "FUZZY_CANDIDATE":
            buckets["UTR_MISMATCH"].append(r)
        elif hasattr(r, "amount_delta") and r.amount_delta is not None and r.amount_delta > 1.0:
            buckets["AMOUNT_DELTA"].append(r)
        elif hasattr(r, "date_delta_days") and r.date_delta_days is not None and r.date_delta_days > 2:
            buckets["DATE_LAG"].append(r)
        else:
            buckets["LLM_ESCALATED"].append(r)

    return buckets


def compute_metrics(results, elapsed: float, llm_calls: int, total: int) -> dict:
    matched = sum(
        1 for r in results
        if (r.decision if hasattr(r, "decision") else str(r.decision)) in MATCHED_DECISIONS
        or (hasattr(r.decision, "value") and r.decision.value in MATCHED_DECISIONS)
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
    print(f"\n{'='*50}")
    print(f"  SettleMatch — Evaluation Results")
    print(f"{'='*50}")
    print(f"  Match rate:          {metrics['match_rate_pct']}%  ({metrics['matched']}/{metrics['total_records']})")
    print(f"  Throughput:          {metrics['throughput_rec_per_sec']} records/sec")
    print(f"  LLM call rate:       {metrics['llm_call_rate_pct']}%")
    print(f"  Wall-clock time:     {metrics['elapsed_seconds']}s")
    print(f"  Exceptions:          {metrics['exception_count']}")
    print(f"{'='*50}")

    if any(v > 0 for v in metrics["exception_breakdown"].values()):
        print(f"\n  Exception Breakdown:")
        for cat, count in metrics["exception_breakdown"].items():
            if count > 0:
                print(f"    {cat}: {count}")
        print()
