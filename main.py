import os
import time

import pandas as pd
from dotenv import load_dotenv

from settlematch.adjudicator import adjudicate, AdjudicationResult, DecisionType
from settlematch.audit import AuditLogger
from settlematch.eval_harness import compute_metrics, print_metrics
from settlematch.matcher import match_settlement, Decision as MatcherDecision

load_dotenv()

ADJUDICATED_DECISIONS = {DecisionType.MATCH, DecisionType.NO_MATCH, DecisionType.ESCALATE_TO_HUMAN}


def _to_llm_decision(result):
    """Map AdjudicationResult to a normalized decision string for metrics."""
    if result.decision == DecisionType.MATCH:
        return "LLM_MATCHED"
    return "LLM_ESCALATED"


def run_pipeline(settlement_path: str, bank_path: str, ledger_path: str) -> dict:
    settlements = pd.read_csv(settlement_path)
    bank = pd.read_csv(bank_path)
    ledger = pd.read_csv(ledger_path)
    logger = AuditLogger()

    start = time.perf_counter()
    results = []
    llm_calls = 0

    for _, row in settlements.iterrows():
        rule_result = match_settlement(row, bank, ledger)

        if rule_result.decision in {MatcherDecision.LLM_CANDIDATE, MatcherDecision.FUZZY_CANDIDATE}:
            llm_result = adjudicate(row, rule_result.candidates)
            llm_calls += 1

            if llm_result.decision == DecisionType.MATCH:
                from dataclasses import replace
                final = replace(
                    rule_result,
                    decision=MatcherDecision.AUTO_APPROVED,
                    reason=llm_result.reason,
                    method="llm",
                )
            else:
                from dataclasses import replace
                final = replace(
                    rule_result,
                    decision=MatcherDecision.MISSING_COUNTERPART,
                    reason=f"[{llm_result.decision.value}] {llm_result.reason}",
                    method="llm",
                )
        else:
            final = rule_result

        logger.log(row, final)
        results.append(final)

    elapsed = time.perf_counter() - start
    total = len(results)

    matched = sum(
        1 for r in results
        if r.decision in {MatcherDecision.AUTO_APPROVED, MatcherDecision.FUZZY_APPROVED}
    )

    metrics = {
        "total_records": total,
        "matched": matched,
        "match_rate_pct": round(matched / total * 100, 1) if total > 0 else 0.0,
        "throughput_rec_per_sec": round(total / elapsed, 1) if elapsed > 0 else 0.0,
        "llm_call_rate_pct": round(llm_calls / total * 100, 1) if total > 0 else 0.0,
        "elapsed_seconds": round(elapsed, 2),
        "exception_count": total - matched,
    }

    exception_buckets = {cat: [] for cat in [
        "UTR_MISMATCH", "AMOUNT_DELTA", "DATE_LAG",
        "BATCH_SPLIT", "LLM_ESCALATED", "MISSING_COUNTERPART",
    ]}
    for r in results:
        d = r.decision
        if hasattr(d, "value"):
            d = d.value
        if d in {"AUTO_APPROVED", "FUZZY_APPROVED"}:
            continue
        elif d == "MISSING_COUNTERPART":
            exception_buckets["MISSING_COUNTERPART"].append(r)
        elif d == "LLM_CANDIDATE":
            exception_buckets["AMOUNT_DELTA"].append(r)
        elif d == "FUZZY_CANDIDATE":
            exception_buckets["UTR_MISMATCH"].append(r)
        else:
            exception_buckets["LLM_ESCALATED"].append(r)

    metrics["exception_breakdown"] = {cat: len(recs) for cat, recs in exception_buckets.items()}
    metrics["exceptions"] = exception_buckets

    os.makedirs("data", exist_ok=True)
    logger.save("data/audit_log.csv")

    print_metrics(metrics)
    return metrics


if __name__ == "__main__":
    run_pipeline(
        "data/settlement_report.csv",
        "data/bank_statement.csv",
        "data/merchant_ledger.csv",
    )
