# RULE-BASED MATCHER + FUZZY UTR MATCHING
# First pass at matching: fast, deterministic, zero API calls
# Resolves ~92% of records. Only ambiguous cases go to the LLM.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pandas as pd
from rapidfuzz import fuzz

# TOLERANCE THRESHOLDS — these determine what the rule engine accepts
AMOUNT_TOLERANCE = 1.00   # ₹1.00 — absorbs paise rounding drift between systems
DATE_TOLERANCE_DAYS = 2   # 2 days — absorbs Razorpay's T+1/T+2 settlement cycle
FUZZY_UTR_THRESHOLD = 93.0  # 93% similarity — catches 1-digit typos on 15-char UTRs


class Decision(str, Enum):
    """All possible outcomes for a single settlement record."""
    AUTO_APPROVED = "AUTO_APPROVED"           # exact match on all 4 checks
    FUZZY_APPROVED = "FUZZY_APPROVED"         # UTR fuzzy-matched, rest passed
    FUZZY_CANDIDATE = "FUZZY_CANDIDATE"       # UTR fuzzy-matched but amount/date off
    LLM_CANDIDATE = "LLM_CANDIDATE"           # candidates found but outside tolerance
    MISSING_COUNTERPART = "MISSING_COUNTERPART"  # no bank or ledger entry found
    BATCH_SPLIT_APPROVED = "BATCH_SPLIT_APPROVED"  # 1 bank credit = multiple settlements


@dataclass
class MatchResult:
    """Result of matching one settlement against bank + ledger."""
    decision: Decision
    method: str  # "rule" | "fuzzy" | "llm" | "batch" | "none"
    bank_utr: str | None = None
    ledger_order_id: str | None = None
    amount_delta: float | None = None
    date_delta_days: int | None = None
    reason: str = ""
    candidates: dict = field(default_factory=dict)
    exception_category: str | None = None  # carries original failure reason through LLM adjudication


def _parse_date(value) -> datetime:
    """Convert string or datetime to datetime object."""
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d")


def fuzzy_utr_match(settlement_utr: str, bank_utrs: list[str]) -> tuple[str | None, float]:
    """
    Find the closest UTR by Levenshtein similarity.
    Returns (best_match, score) or (None, 0.0) if no match above threshold.
    93% on a 15-char string = ~1 digit off = almost certainly a typo.
    """
    best_match, best_score = None, 0.0
    for bank_utr in bank_utrs:
        score = fuzz.ratio(settlement_utr, bank_utr)
        if score > best_score:
            best_score, best_match = score, bank_utr
    if best_score >= FUZZY_UTR_THRESHOLD:
        return best_match, best_score
    return None, 0.0


def match_settlement(
    settlement_row: dict | pd.Series,
    bank_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
) -> MatchResult:
    """
    Match ONE settlement record against bank statement + merchant ledger.

    Decision flow:
      1. Find exact UTR in bank? → check amount + date
      2. No exact UTR? → try fuzzy match (1 digit off)
      3. Find order_id in ledger?
      4. Amount within ₹1.00 AND date within 2 days?
      5. All pass → AUTO_APPROVED
      6. UTR fuzzy-matched → FUZZY_APPROVED or FUZZY_CANDIDATE
      7. Amount/date off → LLM_CANDIDATE (send to LLM)
      8. No candidates → MISSING_COUNTERPART
    """
    # Extract and normalize settlement fields
    settlement_utr = str(settlement_row["utr"]).strip().upper()
    settlement_order_id = str(settlement_row["order_id"]).strip()
    settlement_net = round(float(str(settlement_row["net_amount"])), 2)
    settlement_date = _parse_date(settlement_row["settlement_date"])

    # Edge case: empty bank or ledger = nothing to match against
    if bank_df.empty or ledger_df.empty:
        return MatchResult(
            decision=Decision.MISSING_COUNTERPART,
            method="none",
            reason="No bank or ledger candidates available for this settlement_id.",
            exception_category="MISSING_COUNTERPART",
        )

    # FIX #5 (matcher side): Only normalize if not already done by the caller.
    # main.py pre-computes utr_norm once for the whole run — avoid 65× redundant copies.
    # Tests that pass bare DataFrames still work because the column won't be present.
    if "utr_norm" not in bank_df.columns:
        bank_df = bank_df.copy()
        bank_df["utr_norm"] = bank_df["utr"].astype(str).str.strip().str.upper()

    # STEP 1: Try exact UTR match
    exact_bank_rows = bank_df[bank_df["utr_norm"] == settlement_utr]
    method = "rule"
    bank_row = None

    if not exact_bank_rows.empty:
        bank_row = exact_bank_rows.iloc[0]
    else:
        # STEP 2: No exact match — try fuzzy UTR matching
        match_utr, score = fuzzy_utr_match(settlement_utr, bank_df["utr_norm"].tolist())
        if match_utr is not None:
            bank_row = bank_df[bank_df["utr_norm"] == match_utr].iloc[0]
            method = "fuzzy"
        else:
            # No UTR match at all — nothing to compare
            return MatchResult(
                decision=Decision.MISSING_COUNTERPART,
                method="none",
                reason=f"No exact or fuzzy UTR match found for {settlement_utr}.",
                exception_category="UTR_MISMATCH",
            )

    # STEP 3: Find matching order_id in merchant ledger
    ledger_matches = ledger_df[ledger_df["order_id"].astype(str).str.strip() == settlement_order_id]
    if ledger_matches.empty:
        return MatchResult(
            decision=Decision.MISSING_COUNTERPART,
            method=method,
            bank_utr=bank_row["utr"],
            reason=f"No ledger entry found for order_id {settlement_order_id}.",
            exception_category="MISSING_COUNTERPART",
        )
    ledger_row = ledger_matches.iloc[0]

    # STEP 4: Calculate amount and date deltas
    bank_credit = round(float(bank_row["credit_amount"]), 2)
    amount_delta = round(abs(bank_credit - settlement_net), 2)

    bank_date = _parse_date(bank_row["value_date"])
    date_delta_days = abs((bank_date - settlement_date).days)

    # Store candidates for LLM adjudication if needed
    candidates = {
        "bank_row": bank_row.to_dict(),
        "ledger_row": ledger_row.to_dict(),
    }

    # STEP 5: Check if within tolerance
    within_amount_tolerance = amount_delta <= AMOUNT_TOLERANCE
    within_date_tolerance = date_delta_days <= DATE_TOLERANCE_DAYS

    if within_amount_tolerance and within_date_tolerance:
        # All checks passed — auto-approve
        decision = Decision.AUTO_APPROVED if method == "rule" else Decision.FUZZY_APPROVED
        return MatchResult(
            decision=decision,
            method=method,
            bank_utr=bank_row["utr"],
            ledger_order_id=settlement_order_id,
            amount_delta=amount_delta,
            date_delta_days=date_delta_days,
            reason="All checks passed within tolerance." if method == "rule"
                   else f"UTR fuzzy-matched at high similarity; amount/date within tolerance.",
            candidates=candidates,
        )

    # STEP 6: Outside tolerance — needs LLM adjudication
    # Classify the exception category BEFORE it gets overwritten by LLM
    if not within_amount_tolerance and not within_date_tolerance:
        exc_cat = "AMOUNT_DELTA"  # both off, prioritize amount
    elif not within_amount_tolerance:
        exc_cat = "AMOUNT_DELTA"
    else:
        exc_cat = "DATE_LAG"

    # FUZZY_CANDIDATE when fuzzy matched but amount/date off
    decision = Decision.LLM_CANDIDATE
    if method == "fuzzy":
        decision = Decision.FUZZY_CANDIDATE

    return MatchResult(
        decision=decision,
        method="rule" if method == "rule" else "fuzzy",
        bank_utr=bank_row["utr"],
        ledger_order_id=settlement_order_id,
        amount_delta=amount_delta,
        date_delta_days=date_delta_days,
        reason=(
            f"Amount delta ₹{amount_delta} "
            f"({'within' if within_amount_tolerance else 'OUTSIDE'} ₹{AMOUNT_TOLERANCE} tolerance), "
            f"date delta {date_delta_days}d "
            f"({'within' if within_date_tolerance else 'OUTSIDE'} {DATE_TOLERANCE_DAYS}d tolerance)."
        ),
        candidates=candidates,
        exception_category=exc_cat,
    )


def detect_batch_splits(
    settlement_df: pd.DataFrame,
    bank_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
) -> dict[str, MatchResult]:
    """
    Detect BATCH SPLITS: one bank UTR mapping to multiple settlements.
    Razorpay nets several settlements into a single NEFT credit.

    Example: settlements S001 (₹500) + S002 (₹655.63) = one bank credit of ₹1155.63

    How it works:
      1. Group all settlements by UTR
      2. If 2+ settlements share a UTR, sum their net_amounts
      3. Compare sum against the single bank credit
      4. If within tolerance → mark all as BATCH_SPLIT_APPROVED
    """
    if bank_df.empty or settlement_df.empty:
        return {}

    # Normalize UTRs for grouping
    bank_df = bank_df.copy()
    bank_df["utr_norm"] = bank_df["utr"].astype(str).str.strip().str.upper()

    settlement_df = settlement_df.copy()
    settlement_df["utr_norm"] = settlement_df["utr"].astype(str).str.strip().str.upper()

    # Build lookup maps: UTR → bank credit amount, UTR → bank value date
    bank_credit_map = bank_df.set_index("utr_norm")["credit_amount"].to_dict()
    bank_date_map = bank_df.set_index("utr_norm")["value_date"].to_dict()

    # Group settlements by UTR — groups with 2+ members are batch-split candidates
    utr_groups = settlement_df.groupby("utr_norm")

    batch_matches = {}

    for utr, group in utr_groups:
        # Need at least 2 settlements sharing one UTR to be a batch split
        if len(group) < 2:
            continue

        # This UTR must exist in the bank statement
        if utr not in bank_credit_map:
            continue

        # Sum all settlements' net amounts and compare to single bank credit
        bank_credit = round(float(bank_credit_map[utr]), 2)
        total_net = round(float(str(group["net_amount"].sum())), 2)
        delta = round(abs(bank_credit - total_net), 2)

        # Check if sum matches bank credit (tolerance scales with group size)
        if delta <= AMOUNT_TOLERANCE * len(group):
            # Check date is within tolerance
            bank_date = _parse_date(bank_date_map[utr])
            min_settlement_date = _parse_date(group["settlement_date"].min())
            date_delta_days = abs((bank_date - min_settlement_date).days)

            if date_delta_days <= DATE_TOLERANCE_DAYS:
                # FIX #6: Build a set of ledger order_ids ONCE — O(n) instead of O(n²).
                # Previously: full DataFrame scan inside a nested loop per member.
                # Now: O(1) set membership check per member.
                ledger_order_set = set(
                    ledger_df["order_id"].astype(str).str.strip()
                )
                ledger_orders = []
                for _, row in group.iterrows():
                    order_id = str(row["order_id"]).strip()
                    if order_id in ledger_order_set:
                        ledger_orders.append(order_id)

                # All settlements must have ledger entries
                if len(ledger_orders) == len(group):
                    # Mark every settlement in the batch as matched
                    for _, row in group.iterrows():
                        sid = str(row["settlement_id"])
                        batch_matches[sid] = MatchResult(
                            decision=Decision.BATCH_SPLIT_APPROVED,
                            method="batch",
                            bank_utr=bank_credit_map.get(utr, ""),
                            ledger_order_id=str(row["order_id"]),
                            amount_delta=round(delta / len(group), 2),
                            date_delta_days=date_delta_days,
                            reason=(
                                f"Batch split: {len(group)} settlements (total ₹{total_net}) "
                                f"match single bank credit ₹{bank_credit} (delta ₹{delta})."
                            ),
                            candidates={"bank_row": {"utr": utr, "credit_amount": bank_credit}},
                        )

    return batch_matches
