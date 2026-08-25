"""
Unit tests for settlematch/audit.py — AuditLogger
"""

import csv
import os

from settlematch.adjudicator import AdjudicationResult, DecisionType
from settlematch.audit import AuditLogger
from settlematch.matcher import Decision as MatcherDecision, MatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match_result(decision=MatcherDecision.AUTO_APPROVED, **kwargs) -> MatchResult:
    return MatchResult(
        decision=decision,
        method=str(kwargs.get("method", "rule")),
        bank_utr=kwargs.get("bank_utr", "HDFC010124000001"),
        ledger_order_id=kwargs.get("ledger_order_id", "order_abc123"),
        amount_delta=kwargs.get("amount_delta", 0.00),
        date_delta_days=kwargs.get("date_delta_days", 1),
        reason=str(kwargs.get("reason", "All checks passed within tolerance.")),
        candidates=kwargs.get("candidates", {}),
        exception_category=kwargs.get("exception_category", None),
    )


def _make_settlement_row(**kwargs):
    base = {"settlement_id": "setl_test001", "order_id": "order_abc123"}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Decision Mapping Tests
# ---------------------------------------------------------------------------

class TestMapDecision:
    def test_auto_approved_passthrough(self):
        logger = AuditLogger()
        assert logger._map_decision(MatcherDecision.AUTO_APPROVED) == "AUTO_APPROVED"

    def test_fuzzy_approved_passthrough(self):
        logger = AuditLogger()
        assert logger._map_decision(MatcherDecision.FUZZY_APPROVED) == "FUZZY_APPROVED"

    def test_missing_counterpart_passthrough(self):
        logger = AuditLogger()
        assert logger._map_decision(MatcherDecision.MISSING_COUNTERPART) == "MISSING_COUNTERPART"

    def test_batch_split_approved_passthrough(self):
        logger = AuditLogger()
        assert logger._map_decision(MatcherDecision.BATCH_SPLIT_APPROVED) == "BATCH_SPLIT_APPROVED"

    def test_adjudicator_match_maps_to_llm_matched(self):
        logger = AuditLogger()
        assert logger._map_decision(DecisionType.MATCH) == "LLM_MATCHED"

    def test_adjudicator_no_match_maps_to_llm_escalated(self):
        logger = AuditLogger()
        assert logger._map_decision(DecisionType.NO_MATCH) == "LLM_ESCALATED"

    def test_adjudicator_escalate_maps_to_llm_escalated(self):
        logger = AuditLogger()
        assert logger._map_decision(DecisionType.ESCALATE_TO_HUMAN) == "LLM_ESCALATED"

    def test_plain_string_decision_passthrough(self):
        logger = AuditLogger()
        assert logger._map_decision("AUTO_APPROVED") == "AUTO_APPROVED"

    def test_unknown_decision_returned_as_is(self):
        logger = AuditLogger()
        assert logger._map_decision("SOME_FUTURE_STATUS") == "SOME_FUTURE_STATUS"


# ---------------------------------------------------------------------------
# Safe Attribute Extraction Tests
# ---------------------------------------------------------------------------

class TestSafeAttr:
    def test_attr_present(self):
        result = _make_match_result(bank_utr="UTR123")
        assert AuditLogger._safe_attr(result, "bank_utr") == "UTR123"

    def test_attr_missing_returns_default(self):
        adj = AdjudicationResult(
            decision=DecisionType.MATCH,
            reason="Bank credit 1155.63 matches settlement net minus MDR and GST fees",
            confidence=0.9,
        )
        assert AuditLogger._safe_attr(adj, "bank_utr") == "—"

    def test_custom_default_returned(self):
        adj = AdjudicationResult(
            decision=DecisionType.MATCH,
            reason="Bank credit 1155.63 matches settlement net minus MDR and GST fees",
            confidence=0.9,
        )
        assert AuditLogger._safe_attr(adj, "bank_utr", default="N/A") == "N/A"

    def test_attr_is_none(self):
        result = _make_match_result(bank_utr=None)
        assert AuditLogger._safe_attr(result, "bank_utr") is None


# ---------------------------------------------------------------------------
# Logging Row Structure & CSV Output Tests
# ---------------------------------------------------------------------------

class TestLogAndSave:
    def test_log_auto_approved_row_keys(self):
        logger = AuditLogger()
        row = _make_settlement_row()
        result = _make_match_result()
        logger.log(row, result)
        assert len(logger.rows) == 1
        logged = logger.rows[0]
        expected_keys = {
            "timestamp", "settlement_id", "decision", "method",
            "bank_utr", "ledger_order", "amount_delta", "reason"
        }
        assert expected_keys == set(logged.keys())

    def test_log_amount_delta_formatted_with_rupee_symbol(self):
        logger = AuditLogger()
        logger.log(_make_settlement_row(), _make_match_result(amount_delta=0.75))
        assert logger.rows[0]["amount_delta"] == "₹0.75"

    def test_save_creates_csv_file(self, tmp_path):
        logger = AuditLogger()
        logger.log(_make_settlement_row(), _make_match_result())
        path = str(tmp_path / "test_audit.csv")
        logger.save(path)
        assert os.path.exists(path)

    def test_save_backs_up_existing_file(self, tmp_path):
        logger1 = AuditLogger()
        logger1.log(_make_settlement_row(settlement_id="setl_run1"), _make_match_result())
        path = str(tmp_path / "audit_log.csv")
        logger1.save(path)

        logger2 = AuditLogger()
        logger2.log(_make_settlement_row(settlement_id="setl_run2"), _make_match_result())
        logger2.save(path)

        csv_files = [f for f in os.listdir(tmp_path) if f.endswith(".csv")]
        assert len(csv_files) == 2
