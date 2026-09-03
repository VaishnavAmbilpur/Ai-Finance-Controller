"""
Settlement Q&A Agent for SettleMatch.

Natural-language query layer over the SettleMatch audit log using pandas pre-filtering
and OpenRouter LLM answer generation.
"""

from __future__ import annotations

import os
import re
import pandas as pd
from settlematch.adjudicator import get_async_client, get_model, _get_api_key

SYSTEM_PROMPT = """You are a financial reconciliation Q&A assistant for SettleMatch.
You answer user questions about a payment settlement audit log.

The audit log schema contains these columns:
- timestamp: Execution timestamp
- settlement_id: Unique Razorpay settlement identifier
- decision: Reconciliation outcome (AUTO_APPROVED, FUZZY_APPROVED, BATCH_SPLIT_APPROVED, LLM_MATCHED, LLM_ESCALATED, MISSING_COUNTERPART)
- method: Engine used (rule or llm)
- bank_utr: Bank statement Unique Transaction Reference
- ledger_order: Merchant ERP order ID
- amount_delta: Discrepancy amount in INR (₹)
- reason: Audit trail explanation

Rules for answering:
1. Ground your answer strictly in the provided audit log records or summary metrics below.
2. Be concise, direct, and clear.
3. Reference specific settlement_id, UTR, order_id, or decision counts whenever applicable.
4. If no matching records exist in the audit log, state that clearly."""


def filter_audit_dataframe(question: str, df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """
    Filter/aggregate audit DataFrame based on user query string.

    Returns:
        tuple of (matched_rows DataFrame, context_summary_string for LLM)
    """
    if df.empty:
        return df, "Audit log is empty."

    q_lower = question.lower()
    matched_mask = pd.Series(False, index=df.index)

    # 1. Check for specific settlement IDs, UTRs, or Order IDs mentioned in question
    words = re.findall(r"[A-Za-z0-9_\-]+", question)
    id_mask = pd.Series(False, index=df.index)
    for word in words:
        if len(word) >= 5:
            w_lower = word.lower()
            mask = (
                df["settlement_id"].astype(str).str.lower().str.contains(w_lower)
                | df["bank_utr"].astype(str).str.lower().str.contains(w_lower)
                | df["ledger_order"].astype(str).str.lower().str.contains(w_lower)
            )
            if mask.any():
                id_mask = id_mask | mask

    if id_mask.any():
        matched_df = df[id_mask]
        records_count = len(matched_df)
        summary_lines = [
            f"Total Records in Audit Log: {len(df)}",
            f"Filtered Records Matching Query: {records_count}",
            "\nMatching Audit Log Records:",
        ]
        cols_to_show = [c for c in ["settlement_id", "decision", "bank_utr", "ledger_order", "amount_delta", "reason"] if c in matched_df.columns]
        for r in matched_df[cols_to_show].to_dict(orient="records"):
            summary_lines.append(str(r))
        return matched_df, "\n".join(summary_lines)

    # 2. Check for decision keywords or exception reasons in question
    decision_keywords = [
        "AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED",
        "LLM_MATCHED", "LLM_ESCALATED", "MISSING_COUNTERPART",
        "AMOUNT_DELTA", "DATE_LAG", "UTR_MISMATCH", "BATCH_SPLIT"
    ]
    for kw in decision_keywords:
        if kw.lower() in q_lower:
            mask = (
                df["decision"].astype(str).str.lower().str.contains(kw.lower())
                | df["reason"].astype(str).str.lower().str.contains(kw.lower())
            )
            matched_mask = matched_mask | mask

    # 3. Check for general exception queries
    if "exception" in q_lower or "flagged" in q_lower or "unmatched" in q_lower or "escalat" in q_lower:
        mask = df["decision"].isin(["LLM_ESCALATED", "MISSING_COUNTERPART"]) | (df["method"] == "llm")
        matched_mask = matched_mask | mask

    matched_df = df[matched_mask]

    # If no specific filter matched, default to entire DataFrame
    if matched_df.empty:
        matched_df = df

    # Prepare context summary for LLM
    records_count = len(matched_df)

    # Summary statistics
    decision_counts = df["decision"].value_counts().to_dict()
    reason_counts = df["reason"].value_counts().head(5).to_dict()

    summary_lines = [
        f"Total Records in Audit Log: {len(df)}",
        f"Filtered Records Matching Query: {records_count}",
        f"Decision Distribution across full log: {decision_counts}",
        f"Top Reasons in full log: {reason_counts}",
        "\nMatching Audit Log Records (up to 30 shown):",
    ]

    cols_to_show = [c for c in ["settlement_id", "decision", "bank_utr", "ledger_order", "amount_delta", "reason"] if c in matched_df.columns]
    records_sample = matched_df[cols_to_show].head(30).to_dict(orient="records")
    for r in records_sample:
        summary_lines.append(str(r))

    context_str = "\n".join(summary_lines)
    return matched_df, context_str


async def answer_question(question: str, audit_log_path: str = "data/audit_log.csv") -> dict:
    """
    Answers a natural language question about the audit log.

    Args:
        question: User query string.
        audit_log_path: Path to audit_log.csv file.

    Returns:
        dict: {"answer": str, "records_used": int, "matched_rows": pd.DataFrame}
    """
    if not os.path.exists(audit_log_path):
        return {
            "answer": f"Audit log file not found at '{audit_log_path}'. Please run the pipeline first.",
            "records_used": 0,
            "matched_rows": pd.DataFrame(),
        }

    try:
        df = pd.read_csv(audit_log_path)
    except Exception as e:
        return {
            "answer": f"Error reading audit log file: {e}",
            "records_used": 0,
            "matched_rows": pd.DataFrame(),
        }

    if df.empty:
        return {
            "answer": "Audit log is empty.",
            "records_used": 0,
            "matched_rows": pd.DataFrame(),
        }

    matched_rows, context_str = filter_audit_dataframe(question, df)
    records_used = len(matched_rows)

    prompt = f"User Question: {question}\n\nAudit Context Data:\n{context_str}"

    # Try LLM answer generation with fallback if API fails
    try:
        # Check API key before calling
        _get_api_key()
        client = get_async_client()
        response = await client.chat.completions.create(
            model=get_model(),
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        answer = response.choices[0].message.content or "No response received from LLM."
    except Exception as e:
        # Fallback response grounded in pandas pre-filtering
        q_lower = question.lower()
        if "how many" in q_lower or "count" in q_lower:
            answer = f"Based on audit log analysis, there are {records_used} matching record(s) for your query."
        elif "list" in q_lower or "show" in q_lower:
            ids = matched_rows["settlement_id"].tolist()[:5] if "settlement_id" in matched_rows.columns else []
            answer = f"Found {records_used} matching record(s). Sample Settlement IDs: {', '.join(ids)}"
        else:
            answer = f"Analysis of {records_used} matching audit record(s): " + (
                matched_rows["reason"].iloc[0] if not matched_rows.empty and "reason" in matched_rows.columns else "Query processed successfully."
            )

    return {
        "answer": answer.strip(),
        "records_used": records_used,
        "matched_rows": matched_rows,
    }
