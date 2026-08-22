from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pandas as pd
from rapidfuzz import fuzz

AMOUNT_TOLERANCE = 1.00   # rupees — absorbs paise rounding drift
DATE_TOLERANCE_DAYS = 2   # absorbs Razorpay's standard T+1/T+2 cycle
FUZZY_UTR_THRESHOLD = 93.0  # ~1 character off on a 15-digit string


class Decision(str, Enum):
    AUTO_APPROVED = "AUTO_APPROVED"
    FUZZY_APPROVED = "FUZZY_APPROVED"
    FUZZY_CANDIDATE = "FUZZY_CANDIDATE"
    LLM_CANDIDATE = "LLM_CANDIDATE"
    MISSING_COUNTERPART = "MISSING_COUNTERPART"


@dataclass
class MatchResult:
    decision: Decision
    method: str  # "rule" | "fuzzy" | "llm" | "none"
    bank_utr: str | None = None
    ledger_order_id: str | None = None
    amount_delta: float | None = None
    date_delta_days: int | None = None
    reason: str = ""
    candidates: dict = field(default_factory=dict)


def _parse_date(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d")


def fuzzy_utr_match(settlement_utr: str, bank_utrs: list[str]) -> tuple[str | None, float]:
    """Find the closest UTR by Levenshtein similarity. Returns (match, score)."""
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
    Rule-based first pass for one settlement record against the bank
    statement and merchant ledger. Order of checks:
      1. Exact UTR match in bank_df
      2. If no exact UTR, try fuzzy UTR match
      3. Exact order_id match in ledger_df
      4. Amount delta within tolerance
      5. Date delta within tolerance
    All four core checks must pass for AUTO_APPROVED.
    """
    settlement_utr = str(settlement_row["utr"]).strip().upper()
    settlement_order_id = str(settlement_row["order_id"]).strip()
    settlement_net = round(float(settlement_row["net_amount"]), 2)
    settlement_date = _parse_date(settlement_row["settlement_date"])

    if bank_df.empty or ledger_df.empty:
        return MatchResult(
            decision=Decision.MISSING_COUNTERPART,
            method="none",
            reason="No bank or ledger candidates available for this settlement_id.",
        )

    # Normalize bank UTRs once
    bank_df = bank_df.copy()
    bank_df["utr_norm"] = bank_df["utr"].astype(str).str.strip().str.upper()

    exact_bank_rows = bank_df[bank_df["utr_norm"] == settlement_utr]
    method = "rule"
    bank_row = None

    if not exact_bank_rows.empty:
        bank_row = exact_bank_rows.iloc[0]
    else:
        # Step 3: try fuzzy match before giving up
        match_utr, score = fuzzy_utr_match(settlement_utr, bank_df["utr_norm"].tolist())
        if match_utr is not None:
            bank_row = bank_df[bank_df["utr_norm"] == match_utr].iloc[0]
            method = "fuzzy"
        else:
            return MatchResult(
                decision=Decision.MISSING_COUNTERPART,
                method="none",
                reason=f"No exact or fuzzy UTR match found for {settlement_utr}.",
            )

    # Ledger lookup by order_id
    ledger_matches = ledger_df[ledger_df["order_id"].astype(str).str.strip() == settlement_order_id]
    if ledger_matches.empty:
        return MatchResult(
            decision=Decision.MISSING_COUNTERPART,
            method=method,
            bank_utr=bank_row["utr"],
            reason=f"No ledger entry found for order_id {settlement_order_id}.",
        )
    ledger_row = ledger_matches.iloc[0]

    # Amount + date deltas
    bank_credit = round(float(bank_row["credit_amount"]), 2)
    amount_delta = round(abs(bank_credit - settlement_net), 2)

    bank_date = _parse_date(bank_row["value_date"])
    date_delta_days = abs((bank_date - settlement_date).days)

    candidates = {
        "bank_row": bank_row.to_dict(),
        "ledger_row": ledger_row.to_dict(),
    }

    within_amount_tolerance = amount_delta <= AMOUNT_TOLERANCE
    within_date_tolerance = date_delta_days <= DATE_TOLERANCE_DAYS

    if within_amount_tolerance and within_date_tolerance:
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

    # Outside tolerance but candidates exist — send to LLM adjudication
    return MatchResult(
        decision=Decision.LLM_CANDIDATE,
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
    )