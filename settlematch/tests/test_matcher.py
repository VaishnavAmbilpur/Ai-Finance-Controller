import pytest
import pandas as pd
from settlematch.matcher import match_settlement, Decision


def make_settlement(**kwargs):
    base = {
        'settlement_id': 'S001', 'order_id': 'order_abc123',
        'net_amount': 1155.63, 'settlement_date': '2024-01-14', 'utr': 'HDFC0101240000001'
    }
    return {**base, **kwargs}


def make_bank(**kwargs):
    base = {
        'utr': 'HDFC0101240000001', 'credit_amount': 1155.63, 'value_date': '2024-01-15'
    }
    return pd.DataFrame([{**base, **kwargs}])


def make_ledger(**kwargs):
    base = {'order_id': 'order_abc123', 'net_receivable': 1155.63}
    return pd.DataFrame([{**base, **kwargs}])


def test_clean_match():
    result = match_settlement(make_settlement(), make_bank(), make_ledger())
    assert result.decision == Decision.AUTO_APPROVED


def test_date_lag_within_tolerance():
    result = match_settlement(make_settlement(), make_bank(value_date='2024-01-16'), make_ledger())
    assert result.decision == Decision.AUTO_APPROVED   # T+2 is within tolerance


def test_date_lag_outside_tolerance():
    result = match_settlement(make_settlement(), make_bank(value_date='2024-01-20'), make_ledger())
    assert result.decision == Decision.LLM_CANDIDATE


def test_paise_rounding_within_tolerance():
    result = match_settlement(make_settlement(), make_bank(credit_amount=1155.20), make_ledger())
    assert result.decision == Decision.AUTO_APPROVED   # ₹0.43 delta — within ₹1.00


def test_amount_outside_tolerance_goes_to_llm():
    result = match_settlement(make_settlement(), make_bank(credit_amount=1130.00), make_ledger())
    assert result.decision == Decision.LLM_CANDIDATE


def test_missing_bank_counterpart():
    result = match_settlement(make_settlement(), pd.DataFrame(), make_ledger())
    assert result.decision == Decision.MISSING_COUNTERPART