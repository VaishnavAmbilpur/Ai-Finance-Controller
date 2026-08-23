import csv
from datetime import datetime


class AuditLogger:
    def __init__(self):
        self.rows = []

    def _map_decision(self, decision) -> str:
        if hasattr(decision, "value"):
            d = decision.value
        else:
            d = str(decision)

        if d in {"AUTO_APPROVED", "FUZZY_APPROVED", "MISSING_COUNTERPART"}:
            return d

        if d == "MATCH":
            return "LLM_MATCHED"
        if d in {"NO_MATCH", "ESCALATE_TO_HUMAN"}:
            return "LLM_ESCALATED"

        return d

    @staticmethod
    def _safe_attr(result, attr, default="—"):
        if hasattr(result, attr):
            return getattr(result, attr, default)
        return default

    def log(self, settlement_row, result) -> None:
        decision = self._map_decision(result.decision)

        if hasattr(result, "method"):
            method = result.method
        elif decision.startswith("LLM"):
            method = "llm"
        else:
            method = "rule"

        amount_delta = self._safe_attr(result, "amount_delta")
        if amount_delta is not None and isinstance(amount_delta, (int, float)):
            amount_str = f"₹{amount_delta:.2f}"
        else:
            amount_str = "—"

        bank_utr = self._safe_attr(result, "bank_utr")
        ledger_order = self._safe_attr(result, "ledger_order_id")

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
