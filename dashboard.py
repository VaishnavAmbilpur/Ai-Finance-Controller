# STREAMLIT DASHBOARD
# Non-technical, executive-ready interface for 3-way payment reconciliation.
# Completely emoji-free layout focusing on business clarity and AI impact.

import os
import pandas as pd
import streamlit as st

from main import run_pipeline
from settlematch.generator import generate_dataset

# Page configuration - wide layout for business metrics
st.set_page_config(page_title="SettleMatch - Payment Reconciliation Controller", layout="wide")

AUDIT_PATH = "data/audit_log.csv"


def _generate_and_run(seed=None):
    os.makedirs("data", exist_ok=True)
    settlements, bank, ledger = generate_dataset(n_records=65, seed=seed)
    settlements.to_csv("data/settlement_report.csv", index=False)
    bank.to_csv("data/bank_statement.csv", index=False)
    ledger.to_csv("data/merchant_ledger.csv", index=False)
    run_pipeline("data/settlement_report.csv", "data/bank_statement.csv", "data/merchant_ledger.csv")


# HEADER: Title + Control Button
header_col, btn_col = st.columns([3, 1], vertical_alignment="center")
with header_col:
    st.title("SettleMatch - Payment Reconciliation Controller")
    st.caption("Automated 3-Way Reconciliation between Settlement Reports, Bank Statements, and Merchant Ledgers")
with btn_col:
    if st.button("Generate New Data & Run Pipeline", type="primary", use_container_width=True):
        with st.spinner("Processing reconciliation pipeline..."):
            _generate_and_run(seed=None)
            st.rerun()

st.divider()

# Auto-initialize dataset on first launch
if not os.path.exists(AUDIT_PATH):
    with st.spinner("Initializing sample dataset and executing reconciliation pipeline..."):
        _generate_and_run(seed=42)

# Load audit log data
df = pd.read_csv(AUDIT_PATH)
total_records = len(df)

# Traditional Rule Engine Matches (Auto, Fuzzy, Batch)
rule_matches = len(df[df["decision"].isin(["AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED"])])
rule_accuracy = round(rule_matches / total_records * 100, 1) if total_records > 0 else 0.0

# Discrepancies sent to AI
ai_discrepancies = len(df[df["method"] == "llm"])

# Resolved by AI
ai_resolved = len(df[df["decision"] == "LLM_MATCHED"])

# Final Total Matched after AI
final_matched = rule_matches + ai_resolved
final_accuracy = round(final_matched / total_records * 100, 1) if total_records > 0 else 0.0

# Final Unresolved Exceptions
final_exceptions = len(df[df["decision"].isin(["LLM_ESCALATED", "MISSING_COUNTERPART"])])

# Net AI Automation Improvement
automation_diff = round(final_accuracy - rule_accuracy, 1)

# SECTION 1: EXECUTIVE METRIC OVERVIEW
st.subheader("Executive Performance Summary")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Records Processed", total_records)
c2.metric("Rule Engine Accuracy (Without AI)", f"{rule_accuracy}%")
c3.metric("AI Controller Accuracy (With AI)", f"{final_accuracy}%", delta=f"+{automation_diff}%")
c4.metric("Final Manual Exceptions Remaining", final_exceptions, delta=f"-{ai_resolved} resolved", delta_color="inverse")

st.divider()

# SECTION 2: BEFORE VS AFTER AI AUTOMATION COMPARISON
st.subheader("Automation Difference: Traditional Rules vs AI Finance Controller")

col_before, col_after = st.columns(2)

with col_before:
    st.markdown("### Traditional Rule-Based Engine")
    st.write("Strict hard-coded rules for exact UTR, exact amount, and standard date matching.")
    st.metric("Successful Matches", f"{rule_matches} / {total_records}")
    st.metric("Discrepancies Flagged for Review", ai_discrepancies + final_exceptions)
    st.info("Traditional systems flag all fee variances, MDR deductions, and refund timing lags as manual exceptions.")

with col_after:
    st.markdown("### SettleMatch AI Finance Controller")
    st.write("Intelligent AI engine that evaluates merchant fee deductions, MDR taxes, and refund timing.")
    st.metric("Automatically Resolved by AI", f"{ai_resolved} / {ai_discrepancies}")
    st.metric("Net Automation Boost", f"+{automation_diff}% improvement")
    st.success(f"AI automatically resolved {ai_resolved} complex fee & refund discrepancies without human intervention.")

st.divider()

# SECTION 3: DECISION BREAKDOWN & AI RESOLUTION DETAILS
st.subheader("Reconciliation Outcome Breakdown")

chart_col, details_col = st.columns([1, 1])

with chart_col:
    st.markdown("**Distribution of Processing Decisions**")
    decision_counts = df["decision"].value_counts()
    st.bar_chart(decision_counts)

with details_col:
    st.markdown("**Summary of System Actions**")
    st.write(f"- Auto Approved (Exact Match): {len(df[df['decision']=='AUTO_APPROVED'])}")
    st.write(f"- Fuzzy Approved (Minor UTR Typo): {len(df[df['decision']=='FUZZY_APPROVED'])}")
    st.write(f"- Batch Split Approved (Multi-Order Deposit): {len(df[df['decision']=='BATCH_SPLIT_APPROVED'])}")
    st.write(f"- AI Resolved (Fee/MDR Deduction Verified): {ai_resolved}")
    st.write(f"- Missing Counterpart (Manual Audit Required): {len(df[df['decision']=='MISSING_COUNTERPART'])}")

st.divider()

# SECTION 4: AI RESOLUTION DEEP-DIVE TABLE
st.subheader("AI Adjudication Deep-Dive - Verified Discrepancy Log")
with st.expander("View detailed records resolved by AI", expanded=True):
    available_cols = [
        c for c in ["settlement_id", "decision", "bank_utr", "ledger_order", "amount_delta", "reason"]
        if c in df.columns
    ]
    llm_df = df[df["method"] == "llm"][available_cols]
    if not llm_df.empty:
        st.write("The table below lists the exact transactions flagged by rules and automatically resolved by AI:")
        st.dataframe(llm_df, use_container_width=True, height=300)
    else:
        st.info("No records required AI resolution in this processing run.")

st.divider()

# SECTION 5: AUDIT TRAIL & LOG EXPORT
st.subheader("Audit Trail & Log Export")
with st.expander("Filter and Download Audit Log"):
    filter_options = df["decision"].unique().tolist()
    selected_decisions = st.multiselect("Filter audit log by decision:", options=filter_options, default=filter_options)
    filtered_df = df[df["decision"].isin(selected_decisions)]
    st.dataframe(filtered_df, use_container_width=True, height=350)

    st.download_button(
        label="Download Audit Log (CSV)",
        data=df.to_csv(index=False),
        file_name="audit_log.csv",
        mime="text/csv",
    )
