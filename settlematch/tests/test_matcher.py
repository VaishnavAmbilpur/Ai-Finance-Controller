"""
Unit tests for settlematch/matcher.py — Rule-based & Fuzzy Reconciliation Engine
"""

from datetime import datetime
import pandas as pd

from settlematch.matcher import (
    AMOUNT_TOLERANCE,
    DATE_TOLERANCE_DAYS,
    FUZZY_UTR_THRESHOLD,
    Decision,
    _parse_date,
    detect_batch_splits,
    fuzzy_utr_match,
    match_settlement,
)


# ---------------------------------------------------------------------------
# Test Fixtures & Factories
# ---------------------------------------------------------------------------

def make_settlement(**kwargs):
    base = {
        "settlement_id": "S001",
        "order_id": "order_abc123",
        "net_amount": 1155.63,
        "settlement_date": "2024-01-14",
        "utr": "HDFC0101240000001",
    }
    return {**base, **kwargs}


def make_bank(**kwargs):
    base = {
        "utr": "HDFC0101240000001",
        "credit_amount": 1155.63,
        "value_date": "2024-01-15",
    }
    return pd.DataFrame([{**base, **kwargs}])


def make_ledger(**kwargs):
    base = {"order_id": "order_abc123", "net_receivable": 1155.63}
    return pd.DataFrame([{**base, **kwargs}])


# ---------------------------------------------------------------------------
# Core Rule Engine Matching Tests
# ---------------------------------------------------------------------------

def test_clean_match():
    result = match_settlement(make_settlement(), make_bank(), make_ledger())
    assert result.decision == Decision.AUTO_APPROVED


def test_date_lag_within_tolerance():
    result = match_settlement(make_settlement(), make_bank(value_date="2024-01-16"), make_ledger())
    assert result.decision == Decision.AUTO_APPROVED


def test_date_lag_outside_tolerance():
    result = match_settlement(make_settlement(), make_bank(value_date="2024-01-20"), make_ledger())
    assert result.decision == Decision.LLM_CANDIDATE
    assert result.exception_category == "DATE_LAG"


def test_paise_rounding_within_tolerance():
    result = match_settlement(make_settlement(), make_bank(credit_amount=1155.20), make_ledger())
    assert result.decision == Decision.AUTO_APPROVED


def test_amount_outside_tolerance_goes_to_llm():
    result = match_settlement(make_settlement(), make_bank(credit_amount=1130.00), make_ledger())
    assert result.decision == Decision.LLM_CANDIDATE
    assert result.exception_category == "AMOUNT_DELTA"


def test_missing_bank_counterpart():
    result = match_settlement(make_settlement(), pd.DataFrame(), make_ledger())
    assert result.decision == Decision.MISSING_COUNTERPART


def test_missing_ledger_counterpart():
    result = match_settlement(make_settlement(), make_bank(), pd.DataFrame())
    assert result.decision == Decision.MISSING_COUNTERPART


def test_utr_case_insensitive_and_whitespace():
    result = match_settlement(
        make_settlement(utr="  hdfc0101240000001  "),
        make_bank(utr="HDFC0101240000001"),
        make_ledger(),
    )
    assert result.decision == Decision.AUTO_APPROVED


# ---------------------------------------------------------------------------
# Fuzzy UTR Matcher Tests
# ---------------------------------------------------------------------------

def test_fuzzy_utr_one_digit_off():
    result = match_settlement(
        make_settlement(utr="HDFC0101240000002"),
        make_bank(utr="HDFC0101240000001"),
        make_ledger(),
    )
    assert result.decision == Decision.FUZZY_APPROVED
    assert result.method == "fuzzy"


def test_fuzzy_utr_amount_outside_tolerance():
    result = match_settlement(
        make_settlement(utr="HDFC0101240000002", net_amount=1155.63),
        make_bank(utr="HDFC0101240000001", credit_amount=1100.00),
        make_ledger(),
    )
    assert result.decision == Decision.FUZZY_CANDIDATE


def test_fuzzy_utr_match_helper():
    match, score = fuzzy_utr_match("HDFC0101240000002", ["HDFC0101240000001"])
    assert match == "HDFC0101240000001"
    assert score >= FUZZY_UTR_THRESHOLD

    match_none, _ = fuzzy_utr_match("INVALID_UTR_123", ["HDFC0101240000001"])
    assert match_none is None


# ---------------------------------------------------------------------------
# Tolerance Boundaries & Edge Cases
# ---------------------------------------------------------------------------

def test_amount_tolerance_boundary():
    # Exactly ₹1.00 passes
    res1 = match_settlement(make_settlement(net_amount=100.00), make_bank(credit_amount=100.00 - AMOUNT_TOLERANCE), make_ledger())
    assert res1.decision == Decision.AUTO_APPROVED

    # ₹1.01 fails
    res2 = match_settlement(make_settlement(net_amount=100.00), make_bank(credit_amount=100.00 - (AMOUNT_TOLERANCE + 0.01)), make_ledger())
    assert res2.decision == Decision.LLM_CANDIDATE


def test_date_tolerance_boundary():
    # Exactly 2 days passes
    res1 = match_settlement(make_settlement(settlement_date="2024-01-10"), make_bank(value_date="2024-01-12"), make_ledger())
    assert res1.decision == Decision.AUTO_APPROVED

    # 3 days fails
    res2 = match_settlement(make_settlement(settlement_date="2024-01-10"), make_bank(value_date="2024-01-13"), make_ledger())
    assert res2.decision == Decision.LLM_CANDIDATE


def test_parse_date():
    dt = _parse_date("2024-01-15")
    assert dt == datetime(2024, 1, 15)
    assert _parse_date(dt) == dt


# ---------------------------------------------------------------------------
# Batch Split Detection Tests
# ---------------------------------------------------------------------------

def test_batch_split_detection():
    settlements = pd.DataFrame([
        {"settlement_id": "S001", "order_id": "order_a", "net_amount": 500.00,
         "settlement_date": "2024-01-14", "utr": "HDFC0101240000001"},
        {"settlement_id": "S002", "order_id": "order_b", "net_amount": 655.63,
         "settlement_date": "2024-01-14", "utr": "HDFC0101240000001"},
    ])
    bank = pd.DataFrame([
        {"utr": "HDFC0101240000001", "credit_amount": 1155.63, "value_date": "2024-01-15"},
    ])
    ledger = pd.DataFrame([
        {"order_id": "order_a", "net_receivable": 500.00},
        {"order_id": "order_b", "net_receivable": 655.63},
    ])

    batch_matches = detect_batch_splits(settlements, bank, ledger)
    assert len(batch_matches) == 2
    assert "S001" in batch_matches
    assert "S002" in batch_matches
    assert batch_matches["S001"].decision == Decision.BATCH_SPLIT_APPROVED


def test_batch_split_sum_mismatch():
    settlements = pd.DataFrame([
        {"settlement_id": "S001", "order_id": "order_a", "net_amount": 500.00,
         "settlement_date": "2024-01-14", "utr": "HDFC0101240000001"},
        {"settlement_id": "S002", "order_id": "order_b", "net_amount": 655.63,
         "settlement_date": "2024-01-14", "utr": "HDFC0101240000001"},
    ])
    bank = pd.DataFrame([
        {"utr": "HDFC0101240000001", "credit_amount": 900.00, "value_date": "2024-01-15"},
    ])
    ledger = pd.DataFrame([
        {"order_id": "order_a", "net_receivable": 500.00},
        {"order_id": "order_b", "net_receivable": 655.63},
    ])

    batch_matches = detect_batch_splits(settlements, bank, ledger)
    assert len(batch_matches) == 0
