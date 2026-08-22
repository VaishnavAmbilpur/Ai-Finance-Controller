import pandas as pd
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
import random
import string

fake = Faker('en_IN')
random.seed(42)
np.random.seed(42)


def generate_utr() -> str:
    """Realistic NEFT UTR: bank code + date + sequence"""
    banks = ['HDFC', 'ICIC', 'SBIN', 'AXIS', 'KKBK']
    bank = random.choice(banks)
    date_part = datetime.now().strftime('%d%m%y')
    seq = ''.join([str(random.randint(0, 9)) for _ in range(9)])
    return f"{bank}{date_part}{seq}"


def generate_order_id() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=14))
    return f"order_{suffix}"


def calculate_net_amount(gross: float, mdr_rate: float = 0.0175) -> dict:
    """Razorpay deducts MDR + 18% GST on MDR before settling"""
    mdr = round(gross * mdr_rate, 2)
    gst_on_mdr = round(mdr * 0.18, 2)
    net = round(gross - mdr - gst_on_mdr, 2)
    return {"gross": gross, "mdr": mdr, "gst_on_mdr": gst_on_mdr, "net": net}


def generate_dataset(n_records: int = 65) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    settlements, bank_entries, ledger_entries = [], [], []
    base_date = datetime(2024, 1, 10)

    for i in range(n_records):
        order_id = generate_order_id()
        payment_id = f"pay_{''.join(random.choices(string.ascii_lowercase + string.digits, k=14))}"
        settlement_id = f"setl_{''.join(random.choices(string.ascii_lowercase + string.digits, k=14))}"
        utr = generate_utr()
        gross = round(random.uniform(500, 25000), 2)
        amounts = calculate_net_amount(gross)
        settlement_date = base_date + timedelta(days=random.randint(0, 20))

        # --- Inject failure modes ---
        failure = random.choices(
            ['clean', 'lag', 'utr_typo', 'batch', 'refund', 'rounding'],
            weights=[62, 10, 5, 6, 8, 9]
        )[0]

        bank_utr = utr
        bank_credit = amounts['net']
        bank_date = settlement_date + timedelta(days=1)   # T+1 default
        refund = 0.0

        if failure == 'lag':
            bank_date = settlement_date + timedelta(days=random.choice([1, 2]))

        elif failure == 'utr_typo':
            utr_list = list(utr)
            idx = random.randint(4, len(utr_list) - 1)
            utr_list[idx] = str((int(utr_list[idx]) + 1) % 10)
            bank_utr = ''.join(utr_list)   # one digit flipped

        elif failure == 'batch':
            # This record shares a bank entry with the previous — handled in post-processing
            pass

        elif failure == 'refund':
            refund = round(random.uniform(50, 500), 2)
            bank_credit = round(amounts['net'] - refund, 2)

        elif failure == 'rounding':
            drift = round(random.uniform(0.01, 0.99), 2) * random.choice([-1, 1])
            bank_credit = round(amounts['net'] + drift, 2)

        # Settlement report row
        settlements.append({
            'settlement_id': settlement_id,
            'order_id': order_id,
            'payment_id': payment_id,
            'gross_amount': amounts['gross'],
            'mdr_amount': amounts['mdr'],
            'gst_on_mdr': amounts['gst_on_mdr'],
            'net_amount': amounts['net'],
            'settlement_date': settlement_date.strftime('%Y-%m-%d'),
            'utr': utr,
            '_failure_mode': failure   # for testing only — remove from final output
        })

        # Bank statement row
        bank_entries.append({
            'value_date': bank_date.strftime('%Y-%m-%d'),
            'utr': bank_utr,
            'credit_amount': bank_credit,
            'narration': f"NEFT CR-RAZORPAY SETTLEMENTS {bank_utr}",
        })

        # Merchant ledger row
        ledger_entries.append({
            'order_id': order_id,
            'invoice_amount': gross,
            'payment_received_date': settlement_date.strftime('%Y-%m-%d'),
            'refund_amount': refund,
            'net_receivable': round(amounts['net'] - refund, 2),
        })

    # CRITICAL: Return all 3 DataFrames as a tuple
    return (
        pd.DataFrame(settlements),
        pd.DataFrame(bank_entries),
        pd.DataFrame(ledger_entries)
    )