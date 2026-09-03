# SettleMatch — Architecture & Design Decisions Log

This document records all key technical decisions, bug fixes, benchmark choices, and infrastructure configurations made during the development and optimization of **SettleMatch**.

---

## 1. Benchmark Dataset & Reproducibility (`seed=42`, `n=100`)

* **Decision:** Fixed default dataset generation parameter to **`n_records = 100`** with a deterministic seed **`seed = 42`** in [`settlematch/generator.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/generator.py) and [`generate_data.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/generate_data.py).
* **Rationale:**
  * `seed=42` guarantees exact PRNG reproducibility across automated tests, CI runs, and initial dashboard launches.
  * `n=100` provides a statistically meaningful sample size to exercise all 6 injected failure modes (50% clean, 10% lag, 10% UTR typo, 10% batch, 10% refund, 2% rounding, 8% missing).

---

## 2. Currency Standardization (INR / ₹)

* **Decision:** Converted all financial displays, cost calculations, deltas, and executive ROI metrics across [`dashboard.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/dashboard.py) and [`README.md`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/README.md) to **Indian Rupees (`₹`)**.
* **Rationale:**
  * SettleMatch operates in the context of Razorpay and Indian merchant banking (NEFT/IMPS/RTGS).
  * Operational cost calculations use **₹500 / hour** based on standard Indian Mid-Level Finance Analyst rates.
  * Statutory fee calculations incorporate **18.0% GST** on MDR under Indian CGST/SGST financial service regulations.

---

## 3. Exception Categorization Logic Fix

* **Decision:** Refactored UTR match fallback logic in [`settlematch/matcher.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/matcher.py) to calculate partial Levenshtein similarity scores (`fuzz.ratio`).
* **Rationale:**
  * Previously, missing bank records (`Decision.MISSING_COUNTERPART`) were hardcoded to `exception_category="UTR_MISMATCH"`, dumping all exceptions into a single bucket.
  * With the fix:
    * Bank candidates with partial UTR similarity (**70%–92%**) are categorized as **`UTR_MISMATCH`** (severe UTR typos).
    * Transactions missing bank statement entries entirely (similarity **< 70%**) are categorized as **`MISSING_COUNTERPART`**.
  * Results in a realistic 7-exception breakdown ($n=100, \text{seed}=42$): **6 `MISSING_COUNTERPART`** and **1 `LLM_ESCALATED`**.

---

## 4. Instant Streamlit Cloud Boot Strategy

* **Decision:** Tracked pre-computed canonical benchmark dataset (`data/audit_log.csv`, `settlement_report.csv`, `bank_statement.csv`, `merchant_ledger.csv`) in Git.
* **Rationale:**
  * Prevents cold-start delays and button-click requirements on Streamlit Community Cloud.
  * When a visitor visits [`https://ai-finance-controller.streamlit.app/`](https://ai-finance-controller.streamlit.app/), all executive KPIs, visual funnel stages, decision breakdown charts, and transaction inspector tables load **100% instantly**.

---

## 5. Deployment & Uptime Architecture (Streamlit Cloud + UptimeRobot)

* **Decision:** Deployed live application on Streamlit Community Cloud paired with a **5-minute ping interval** via UptimeRobot.
* **Rationale:**
  * Prevents Streamlit's 7-day deep sleep policy and 15-minute container pause.
  * Keeps the container warm, ensuring zero load latency for users while avoiding third-party CPU quota locks (e.g. Hugging Face Spaces limits).

---

## 6. Async Concurrency Optimization & Throughput Benchmarks

* **Decision:** Implemented `AsyncOpenAI` + `asyncio.gather` in [`settlematch/adjudicator.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/adjudicator.py) and [`main.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/main.py).
* **Rationale & Benchmark Measurements ($n=100$):**
  * **Sequential Blocking Pipeline (Day 1 baseline):** ~0.8 records/sec (1–5s blocking wait per LLM call).
  * **Live Network OpenRouter Pipeline:** **4.7 records/sec** (21.3s total wall-clock time over live HTTP API calls).
  * **Async Execution Engine Benchmark:** **34.7 records/sec** (2.88s total wall-clock time with non-blocking concurrent event loop processing).

---

## 7. Financial Fee Formulas & Verification Transparency

* **Decision:** Explicitly documented MDR fee ranges (1.5%–2.2%) and GST tax (18%) in [`README.md`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/README.md) and connected them to `AMOUNT_DELTA` tolerance and AI Adjudication.
* **Rationale:**
  * Explains how fee deductions and refunds are verified by the AI engine to convert raw amount variances into `LLM_MATCHED` decisions.

---

## 8. ERP Journal Voucher Exporter (`settlematch/erp_exporter.py`)

* **Decision:** Implemented [`settlematch/erp_exporter.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/erp_exporter.py) to export reconciled audit records directly as **Tally Prime XML** and **Zoho Books / SAP CSV** double-entry journal vouchers.
* **Rationale:**
  * Solves the post-reconciliation bottleneck for Indian merchants using Tally Prime or Zoho Books.
  * Exports proper double-entry vouchers: Debit Bank, Debit Razorpay MDR Fee, Debit GST Input Tax Credit (18%), and Credit Customer Sales Receivables.

---

## 9. Financial Anomaly & Risk Guard (`settlematch/anomaly_detector.py`)

* **Decision:** Created [`settlematch/anomaly_detector.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/anomaly_detector.py) to scan audit logs for macro financial risks.
* **Rationale:**
  * Detects duplicate UTR payouts across bank batches, MDR overcharges exceeding contract rates (>2.2%), and phantom bank credits missing ledger counterparts.
  * Surfaces high-priority warning banners directly in the Streamlit dashboard.

