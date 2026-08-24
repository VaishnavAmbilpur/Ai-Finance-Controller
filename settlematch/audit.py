# AUDIT LOG WRITER
# Records every single decision to audit_log.csv with timestamp + reason.
# This is the "honest exception list" the track brief requires.
# Judges download this CSV to verify your claims.
#
# Day 2 fix: save() now backs up any existing audit log before overwriting.
# For a financial reconciliation tool, silently replacing audit history is
# an integrity concern — every run's results are now preserved.

import csv
import os
from datetime import datetime


class AuditLogger:
    """Accumulates decisions in memory, writes CSV on save()."""

    def __init__(self):
        self.rows = []

    def _map_decision(self, decision) -> str:
        """
        Normalize decision types from matcher AND adjudicator into one format.
        Matcher uses: AUTO_APPROVED, FUZZY_APPROVED, MISSING_COUNTERPART, BATCH_SPLIT_APPROVED
        Adjudicator uses: MATCH, NO_MATCH, ESCALATE_TO_HUMAN
        Audit log uses: AUTO_APPROVED, FUZZY_APPROVED, LLM_MATCHED, LLM_ESCALATED, etc.
        """
        if hasattr(decision, "value"):
            d = decision.value
        else:
            d = str(decision)

        # Matcher decisions — pass through as-is
        if d in {"AUTO_APPROVED", "FUZZY_APPROVED", "MISSING_COUNTERPART", "BATCH_SPLIT_APPROVED"}:
            return d

        # Adjudicator decisions — map to audit-friendly names
        if d == "MATCH":
            return "LLM_MATCHED"
        if d in {"NO_MATCH", "ESCALATE_TO_HUMAN"}:
            return "LLM_ESCALATED"

        return d

    @staticmethod
    def _safe_attr(result, attr, default="—"):
        """
        Safely extract an attribute from result.
        MatchResult has bank_utr, ledger_order_id, amount_delta.
        AdjudicationResult doesn't — it only has decision, reason, confidence.
        """
        if hasattr(result, attr):
            return getattr(result, attr, default)
        return default

    def log(self, settlement_row, result) -> None:
        """Record one decision for one settlement row."""
        decision = self._map_decision(result.decision)

        # Determine method: rule, fuzzy, llm, batch, or none
        if hasattr(result, "method"):
            method = result.method
        elif decision.startswith("LLM"):
            method = "llm"
        else:
            method = "rule"

        # Format amount delta with ₹ symbol
        amount_delta = self._safe_attr(result, "amount_delta")
        if amount_delta is not None and isinstance(amount_delta, (int, float)):
            amount_str = f"₹{amount_delta:.2f}"
        else:
            amount_str = "—"

        bank_utr = self._safe_attr(result, "bank_utr")
        ledger_order = self._safe_attr(result, "ledger_order_id")

        # Build the audit row — human-readable without a data dictionary
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "settlement_id": str(settlement_row.get("settlement_id", "")),
            "decision": decision,
            "method": method,
            "bank_utr": str(bank_utr) if bank_utr is not None else "—",
            "ledger_order": str(ledger_order) if ledger_order is not None else "—",
            "amount_delta": str(amount_str),
            "reason": str(result.reason),
        }
        self.rows.append(row)

    def save(self, path="data/audit_log.csv") -> None:
        """
        Write all logged rows to CSV — downloadable from the dashboard.

        FIX #7: If an audit log already exists, rename it with a timestamp suffix
        before writing the new one. This preserves the full audit trail across runs
        rather than silently destroying previous reconciliation results.
        """
        # Back up existing audit log before overwriting
        if os.path.exists(path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = path.replace(".csv", f"_{ts}.csv")
            counter = 1
            while os.path.exists(backup_path):
                backup_path = path.replace(".csv", f"_{ts}_{counter}.csv")
                counter += 1
            os.rename(path, backup_path)

        fieldnames = [
            "timestamp",
            "settlement_id",
            "decision",
            "method",
            "bank_utr",
            "ledger_order",
            "amount_delta",
            "reason",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.rows)
