"""
Financial Anomaly & Risk Detector for SettleMatch.
Scans reconciliation audit logs to flag macro financial risks:
1. Duplicate UTR payouts across bank batches.
2. MDR Fee Overcharges exceeding merchant contract rates (>2.2%).
3. Phantom Bank Credits missing merchant ledger counterparts.
"""

import pandas as pd


def detect_anomalies(df: pd.DataFrame) -> dict:
    """
    Scans audit log DataFrame for macro financial anomalies.

    Returns:
        dict containing:
        - "total_anomalies": int count of flagged anomaly items
        - "duplicate_utrs": list of duplicate UTR risk dicts
        - "mdr_overcharges": list of MDR overcharge risk dicts
        - "phantom_credits": list of phantom bank credit risk dicts
    """
    if df.empty:
        return {
            "total_anomalies": 0,
            "duplicate_utrs": [],
            "mdr_overcharges": [],
            "phantom_credits": [],
        }

    duplicate_utrs = []
    if "bank_utr" in df.columns:
        def is_valid_utr_code(utr_val):
            s = str(utr_val).strip().upper()
            if not s or s in ["N/A", "NAN", "NONE", "—", "-"]:
                return False
            try:
                float(s)
                return False  # Skip numerical batch sums
            except ValueError:
                pass
            return len(s) >= 6

        utr_series = df["bank_utr"].apply(lambda x: str(x).strip() if is_valid_utr_code(x) else None).dropna()
        dup_counts = utr_series.value_counts()
        dups = dup_counts[dup_counts > 1]
        for utr_val, cnt in dups.items():
            duplicate_utrs.append({
                "type": "DUPLICATE_UTR_PAYOUT",
                "utr": utr_val,
                "occurrences": int(cnt),
                "severity": "HIGH",
                "message": f"Bank UTR `{utr_val}` appears {cnt} times across settlement batches (potential double-payout)."
            })

    mdr_overcharges = []
    if "reason" in df.columns:
        for idx, row in df.iterrows():
            reason_str = str(row.get("reason", "")).lower()
            if "overcharge" in reason_str or "exceeds" in reason_str or "unauthorized fee" in reason_str:
                mdr_overcharges.append({
                    "type": "MDR_FEE_OVERCHARGE",
                    "settlement_id": str(row.get("settlement_id", f"SETL_{idx}")),
                    "severity": "MEDIUM",
                    "message": f"Settlement `{row.get('settlement_id')}` flagged for MDR fee overcharge rate."
                })

    phantom_credits = []
    if "decision" in df.columns:
        phantom_rows = df[df["decision"] == "MISSING_COUNTERPART"]
        for idx, row in phantom_rows.iterrows():
            phantom_credits.append({
                "type": "PHANTOM_BANK_CREDIT",
                "settlement_id": str(row.get("settlement_id", f"SETL_{idx}")),
                "severity": "HIGH",
                "message": f"Settlement `{row.get('settlement_id')}` missing ledger order reference."
            })

    total_count = len(duplicate_utrs) + len(mdr_overcharges) + len(phantom_credits)
    return {
        "total_anomalies": total_count,
        "duplicate_utrs": duplicate_utrs,
        "mdr_overcharges": mdr_overcharges,
        "phantom_credits": phantom_credits,
    }
