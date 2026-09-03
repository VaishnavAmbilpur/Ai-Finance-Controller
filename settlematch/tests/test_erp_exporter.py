import pytest
import pandas as pd
from settlematch.erp_exporter import generate_tally_xml, generate_zoho_csv


@pytest.fixture
def sample_approved_df():
    return pd.DataFrame([
        {
            "settlement_id": "setl_101",
            "decision": "AUTO_APPROVED",
            "bank_utr": "HDFC00012345",
            "ledger_order": "order_9901",
            "amount_delta": "₹0.00",
            "reason": "Perfect match"
        },
        {
            "settlement_id": "setl_102",
            "decision": "LLM_MATCHED",
            "bank_utr": "ICIC00054321",
            "ledger_order": "order_9902",
            "amount_delta": "₹472.00",
            "reason": "AI Adjudicator: Verified MDR fee deduction"
        }
    ])


def test_generate_tally_xml(sample_approved_df):
    xml_str = generate_tally_xml(sample_approved_df)
    assert "<ENVELOPE>" in xml_str
    assert "HDFC Bank Account" in xml_str
    assert "Razorpay MDR Charges" in xml_str
    assert "GST Input Tax Credit (18%)" in xml_str
    assert "setl_101" in xml_str


def test_generate_zoho_csv(sample_approved_df):
    csv_str = generate_zoho_csv(sample_approved_df)
    assert "Journal Date" in csv_str
    assert "HDFC Bank Settlement Account" in csv_str
    assert "Razorpay MDR Expense Account" in csv_str
    assert "setl_101" in csv_str
    assert "setl_102" in csv_str


def test_generate_erp_empty_df():
    empty_df = pd.DataFrame()
    xml_str = generate_tally_xml(empty_df)
    assert "<ENVELOPE>" in xml_str
    csv_str = generate_zoho_csv(empty_df)
    assert "Journal Date" in csv_str
