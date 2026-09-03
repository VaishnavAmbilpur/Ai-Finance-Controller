import pytest
import pandas as pd
from settlematch.anomaly_detector import detect_anomalies


def test_detect_anomalies_empty_df():
    res = detect_anomalies(pd.DataFrame())
    assert res["total_anomalies"] == 0
    assert len(res["duplicate_utrs"]) == 0


def test_detect_duplicate_utrs():
    df = pd.DataFrame([
        {"settlement_id": "s1", "bank_utr": "UTR123", "decision": "AUTO_APPROVED", "reason": "ok"},
        {"settlement_id": "s2", "bank_utr": "UTR123", "decision": "FUZZY_APPROVED", "reason": "ok"},
        {"settlement_id": "s3", "bank_utr": "UTR999", "decision": "AUTO_APPROVED", "reason": "ok"},
    ])
    res = detect_anomalies(df)
    assert len(res["duplicate_utrs"]) == 1
    assert res["duplicate_utrs"][0]["utr"] == "UTR123"
    assert res["duplicate_utrs"][0]["occurrences"] == 2


def test_detect_phantom_credits():
    df = pd.DataFrame([
        {"settlement_id": "s1", "bank_utr": "UTR123", "decision": "MISSING_COUNTERPART", "reason": "Missing bank entry"},
    ])
    res = detect_anomalies(df)
    assert len(res["phantom_credits"]) == 1
    assert res["phantom_credits"][0]["settlement_id"] == "s1"
