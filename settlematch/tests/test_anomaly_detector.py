import pytest
import pandas as pd
from settlematch.anomaly_detector import detect_anomalies


def test_detect_anomalies_empty_df():
    res = detect_anomalies(pd.DataFrame())
    assert res["total_anomalies"] == 0
    assert len(res["duplicate_utrs"]) == 0
    assert len(res["mdr_overcharges"]) == 0
    assert len(res["phantom_credits"]) == 0

    assert detect_anomalies(None)["total_anomalies"] == 0


def test_detect_duplicate_utrs():
    df = pd.DataFrame([
        {"settlement_id": "s1", "bank_utr": "UTR123", "decision": "AUTO_APPROVED", "reason": "ok"},
        {"settlement_id": "s2", "bank_utr": "utr123 ", "decision": "FUZZY_APPROVED", "reason": "ok"},
        {"settlement_id": "s3", "bank_utr": "UTR999", "decision": "AUTO_APPROVED", "reason": "ok"},
        {"settlement_id": "s4", "bank_utr": "402212345678", "decision": "AUTO_APPROVED", "reason": "ok"},
        {"settlement_id": "s5", "bank_utr": "402212345678", "decision": "AUTO_APPROVED", "reason": "ok"},
        {"settlement_id": "s6", "bank_utr": "1155.63", "decision": "AUTO_APPROVED", "reason": "ok"},
        {"settlement_id": "s7", "bank_utr": "1155.63", "decision": "AUTO_APPROVED", "reason": "ok"},
    ])
    res = detect_anomalies(df)
    utrs = [d["utr"] for d in res["duplicate_utrs"]]
    assert "UTR123" in utrs
    assert "402212345678" in utrs
    assert "1155.63" not in utrs  # Float amount filtered out


def test_detect_mdr_overcharges():
    df = pd.DataFrame([
        {"settlement_id": "s1", "reason": "MDR rate exceeds agreed contract tolerance"},
        {"settlement_id": "s2", "reason": "Excess fee deducted by gateway"},
        {"settlement_id": "s3", "reason": "Normal transaction"},
    ])
    res = detect_anomalies(df)
    assert len(res["mdr_overcharges"]) == 2
    ids = [m["settlement_id"] for m in res["mdr_overcharges"]]
    assert "s1" in ids
    assert "s2" in ids


def test_detect_phantom_credits():
    df = pd.DataFrame([
        {"settlement_id": "s1", "bank_utr": "UTR123", "decision": "MISSING_COUNTERPART", "reason": "Missing bank entry"},
    ])
    res = detect_anomalies(df)
    assert len(res["phantom_credits"]) == 1
    assert res["phantom_credits"][0]["settlement_id"] == "s1"

