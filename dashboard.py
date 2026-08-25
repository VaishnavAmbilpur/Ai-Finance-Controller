# STREAMLIT DASHBOARD
# Presentation layer — shows metrics, AI Impact (Before vs After), decision charts, audit log.
# Run: python -m streamlit run dashboard.py

import os
import pandas as pd
import streamlit as st

from main import run_pipeline
from settlematch.generator import generate_dataset

# Page config — wide layout for metric cards
st.set_page_config(page_title="SettleMatch — AI Finance Controller", layout="wide")

AUDIT_PATH = "data/audit_log.csv"


def _generate_and_run(seed=None):
    os.makedirs("data", exist_ok=True)
    settlements, bank, ledger = generate_dataset(n_records=65, seed=seed)
    settlements.to_csv("data/settlement_report.csv", index=False)
    bank.to_csv("data/bank_statement.csv", index=False)
    ledger.to_csv("data/merchant_ledger.csv", index=False)
    run_pipeline("data/settlement_report.csv", "data/bank_statement.csv", "data/merchant_ledger.csv")


# HEADER: Title + inline control button
col_header, col_btn = st.columns([3, 1], vertical_alignment="center")
with col_header:
    st.title("SettleMatch — Reconciliation Results")
    st.caption("⚡ Automated 3-way reconciliation (Razorpay Settlement vs Bank Statement vs Merchant Ledger)")
with col_btn:
    if st.button("🎲 Generate New Data & Run", type="primary", use_container_width=True):
        with st.spinner("Running AI pipeline..."):
            _generate_and_run(seed=None)
            st.rerun()

st.divider()

# Check if audit log exists — auto-generate dataset on first launch if missing
if not os.path.exists(AUDIT_PATH):
    with st.spinner("Initializing dataset and running SettleMatch pipeline for first launch..."):
        _generate_and_run(seed=42)

# Load audit log and compute metrics
df = pd.read_csv(AUDIT_PATH)
total = len(df)
matched = len(df[df["decision"].isin(["AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED", "LLM_MATCHED"])])
exceptions = total - matched
match_rate = round(matched / total * 100, 1) if total > 0 else 0.0
llm_calls = len(df[df["method"] == "llm"])
llm_rate = round(llm_calls / total * 100, 1) if total > 0 else 0.0

# ROW 1: 4 primary metric cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Overall Match Rate", f"{match_rate}%")
c2.metric("Total Records Processed", total)
c3.metric("LLM Escalation Rate", f"{llm_rate}%")
c4.metric("Unresolved Exceptions", exceptions)

st.divider()

# ROW 2: AI Impact Comparison (Before vs After AI Adjudication)
st.subheader("🤖 AI Adjudicator Impact — Before vs After AI")

pre_ai_exceptions = len(df[df["method"] == "llm"])
ai_resolved = len(df[df["decision"] == "LLM_MATCHED"])
post_ai_unresolved = len(df[df["decision"].isin(["LLM_ESCALATED", "MISSING_COUNTERPART"])])
resolution_pct = round(ai_resolved / pre_ai_exceptions * 100, 1) if pre_ai_exceptions > 0 else 100.0

m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric(
    "Pre-AI Rule Discrepancies",
    pre_ai_exceptions,
    help="Flagged by strict rule engine (MDR fee variances, date lags)",
)
m_col2.metric("AI Adjudicated & Resolved", ai_resolved, delta=f"+{ai_resolved} matched")
m_col3.metric("AI Resolution Efficiency", f"{resolution_pct}%")
m_col4.metric(
    "Post-AI Final Exceptions",
    post_ai_unresolved,
    delta=f"-{ai_resolved} resolved",
    delta_color="inverse",
)

with st.expander("🔍 AI Adjudication Deep-Dive — How AI Resolved Discrepancies"):
    available_cols = [
        c for c in ["settlement_id", "decision", "bank_utr", "ledger_order", "amount_delta", "reason"]
        if c in df.columns
    ]
    llm_df = df[df["method"] == "llm"][available_cols]
    if not llm_df.empty:
        st.write(
            "Below are the exact ambiguous records that strict rule engine could not match, and how AI adjudicated them:"
        )
        st.dataframe(llm_df, use_container_width=True)
    else:
        st.info("No records required AI adjudication in this run.")

st.divider()

# ROW 3: Decision distribution bar chart
st.subheader("Decision Breakdown")
col_chart, col_exc = st.columns(2)

with col_chart:
    st.markdown("**All Decision Outcomes**")
    decision_counts = df["decision"].value_counts()
    st.bar_chart(decision_counts)

with col_exc:
    st.markdown("**Unresolved Exception Breakdown**")
    exc_df = df[
        ~df["decision"].isin(["AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED", "LLM_MATCHED"])
    ]
    if not exc_df.empty:
        exc_counts = pd.Series(exc_df["decision"]).value_counts()
        st.bar_chart(exc_counts)
    else:
        st.success("🎉 All exceptions successfully resolved by AI!")

st.divider()

# ROW 4: Filterable audit log table with download button
st.subheader("Audit Log & Export")
with st.expander("Filter & search audit log", expanded=True):
    filter_decision = st.multiselect(
        "Filter by decision",
        options=df["decision"].unique(),
        default=df["decision"].unique(),
    )
    filtered = df[df["decision"].isin(filter_decision)]
    st.dataframe(filtered, use_container_width=True, height=350)

    # Download button
    st.download_button(
        label="📥 Download Complete Audit Log (CSV)",
        data=df.to_csv(index=False),
        file_name="audit_log.csv",
        mime="text/csv",
    )
