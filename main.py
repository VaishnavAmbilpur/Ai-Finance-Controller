import asyncio
import os
import time
from dataclasses import replace

import pandas as pd
from dotenv import load_dotenv

from settlematch.adjudicator import adjudicate_async, DecisionType, AdjudicationResult
from settlematch.audit import AuditLogger
from settlematch.eval_harness import compute_metrics, print_metrics
from settlematch.matcher import match_settlement, detect_batch_splits, Decision as MatcherDecision

load_dotenv()


def _apply_llm_result(rule_result, llm_result: AdjudicationResult):
    """
    Merge an LLM adjudication result back onto a rule-engine MatchResult.
    Extracted into a helper so the async pipeline loop stays readable.
    """
    if llm_result.decision == DecisionType.MATCH:
        return replace(
            rule_result,
            decision="LLM_MATCHED",
            reason=llm_result.reason,
            method="llm",
            exception_category=None,
        )
    elif llm_result.decision == DecisionType.ESCALATE_TO_HUMAN:
        return replace(
            rule_result,
            decision=MatcherDecision.LLM_CANDIDATE,
            reason=f"[ESCALATE_TO_HUMAN] {llm_result.reason}",
            method="llm",
        )
    else:  # NO_MATCH
        return replace(
            rule_result,
            decision=MatcherDecision.MISSING_COUNTERPART,
            reason=f"[NO_MATCH] {llm_result.reason}",
            method="llm",
            exception_category="LLM_ESCALATED",
        )


async def run_pipeline_async(settlement_path: str, bank_path: str, ledger_path: str) -> dict:
    """
    Async pipeline — runs all LLM calls concurrently via asyncio.gather.

    FIX #4 (async): LLM calls are now awaited concurrently, not sequentially.
    FIX #5 (normalization): bank_df["utr_norm"] computed ONCE before the loop,
    not inside match_settlement() on every single row.

    Flow:
      PASS 1 — Rule engine (fast, synchronous, no I/O):
                Process all settlements → separate into:
                  a) Already resolved (batch/rule/fuzzy)
                  b) LLM candidates (need AI adjudication)

      PASS 2 — Concurrent LLM calls (asyncio.gather):
                All LLM candidates sent simultaneously — no sequential waiting.

      PASS 3 — Merge:
                Apply LLM results back, log everything, compute metrics.
    """
    settlements = pd.read_csv(settlement_path)
    bank = pd.read_csv(bank_path)
    ledger = pd.read_csv(ledger_path)
    logger = AuditLogger()

    start = time.perf_counter()

    # FIX #5: Pre-normalize bank UTRs ONCE before any matching starts.
    # Previously, match_settlement() did bank_df.copy() + normalization on EVERY call.
    # At 65 records that's 65 wasted copies. At 10k records it's significant overhead.
    bank = bank.copy()
    bank["utr_norm"] = bank["utr"].astype(str).str.strip().str.upper()

    batch_matches = detect_batch_splits(settlements, bank, ledger)

    # PASS 1: Rule-based matching — pure CPU, no I/O
    # Results are stored as (row, final_result | None) where None = needs LLM
    pre_results: list[tuple] = []   # (row, result_or_none)
    pending_llm: list[tuple] = []   # (row, rule_result) for LLM candidates

    for _, row in settlements.iterrows():
        sid = str(row["settlement_id"])

        if sid in batch_matches:
            pre_results.append((row, batch_matches[sid]))
        else:
            rule_result = match_settlement(row, bank, ledger)

            if rule_result.decision in {MatcherDecision.LLM_CANDIDATE, MatcherDecision.FUZZY_CANDIDATE}:
                pending_llm.append((row, rule_result))
                pre_results.append((row, None))  # placeholder — filled in PASS 3
            else:
                pre_results.append((row, rule_result))

    # PASS 2: FIX #4 — fire all LLM calls concurrently, await all together
    # Before: each LLM call blocked for 1-5s → 5 calls = 5-25s of sequential waiting
    # After:  all calls run in parallel → wall-clock time ≈ slowest single call
    llm_results: list[AdjudicationResult] = []
    if pending_llm:
        llm_results = list(await asyncio.gather(*[
            adjudicate_async(row, rule_result.candidates)
            for row, rule_result in pending_llm
        ]))

    # PASS 3: Merge LLM results back and build final result list
    llm_iter = iter(zip(pending_llm, llm_results))
    results = []

    for row, pre_result in pre_results:
        if pre_result is None:
            # This slot was a LLM candidate — pick up the next LLM result in order
            (_, rule_result), llm_result = next(llm_iter)
            final = _apply_llm_result(rule_result, llm_result)
        else:
            final = pre_result

        logger.log(row, final)
        results.append(final)

    elapsed = time.perf_counter() - start
    llm_calls = len(pending_llm)
    metrics = compute_metrics(results, elapsed, llm_calls, len(results))

    os.makedirs("data", exist_ok=True)
    logger.save("data/audit_log.csv")

    print_metrics(metrics)
    return metrics


def run_pipeline(settlement_path: str, bank_path: str, ledger_path: str) -> dict:
    """
    Synchronous entry point — wraps the async pipeline with asyncio.run().
    External callers (CLI, tests, Streamlit) use this exactly as before.
    """
    return asyncio.run(run_pipeline_async(settlement_path, bank_path, ledger_path))


if __name__ == "__main__":
    run_pipeline(
        "data/settlement_report.csv",
        "data/bank_statement.csv",
        "data/merchant_ledger.csv",
    )
