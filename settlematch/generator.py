# DATA GENERATOR
# Creates realistic payment records across 3 sources (settlement, bank, ledger)
# Injects 6 real-world Razorpay failure modes to make data realistic for reconciliation
# Supports dynamic entropy / seed control for high randomness on every run.

from datetime import datetime, timedelta
import random
import string

from faker import Faker
import numpy as np
import pandas as pd

fake = Faker("en_IN")

BANKS = [
    "HDFC", "ICIC", "SBIN", "AXIS", "KKBK",
    "YESB", "UTIB", "IDFB", "PUNB", "BARB",
]

FAILURE_MODES = ["clean", "lag", "utr_typo", "batch", "refund", "rounding", "missing"]
FAILURE_WEIGHTS = [50, 10, 10, 10, 10, 2, 8]  # percentages


def set_seed(seed: int | None = None) -> None:
    """Set random seed for reproducibility if seed is provided, else use dynamic entropy."""
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
    else:
        # Resets to system entropy for true randomness
        random.seed()
        np.random.seed()


def generate_utr(settlement_date: datetime | None = None) -> str:
    """Generate a realistic NEFT UTR number: bank code + date + 9-digit sequence"""
    bank = random.choice(BANKS)
    date_part = (settlement_date or datetime.now()).strftime("%d%m%y")
    seq = "".join([str(random.randint(0, 9)) for _ in range(9)])
    return f"{bank}{date_part}{seq}"


def generate_order_id() -> str:
    """Generate a Razorpay-style order ID: order_ + 14 random chars"""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
    return f"order_{suffix}"


def generate_payment_id() -> str:
    """Generate a Razorpay payment ID: pay_ + 14 random chars"""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
    return f"pay_{suffix}"


def generate_settlement_id() -> str:
    """Generate a Razorpay settlement ID: setl_ + 14 random chars"""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
    return f"setl_{suffix}"


def calculate_net_amount(gross: float, mdr_rate: float | None = None) -> dict:
    """
    Calculate what Razorpay pays out after deductions:
    - MDR (Merchant Discount Rate): random between 1.5% and 2.2% if not specified
    - GST on MDR: 18% of MDR amount
    - Net = Gross - MDR - GST
    """
    if mdr_rate is None:
        mdr_rate = random.choice([0.015, 0.0175, 0.02, 0.022])

    mdr = round(gross * mdr_rate, 2)
    gst_on_mdr = round(mdr * 0.18, 2)
    net = round(gross - mdr - gst_on_mdr, 2)
    return {"gross": gross, "mdr": mdr, "gst_on_mdr": gst_on_mdr, "net": net}


def generate_dataset(
    n_records: int = 65, seed: int | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Main generator: creates n_records across 3 data sources with high randomness.

    Args:
        n_records: Number of settlement records to generate (default: 65)
        seed: Optional integer seed for reproducibility. If None, uses dynamic entropy.

    Returns:
        (settlements_df, bank_df, ledger_df)
    """
    set_seed(seed)

    settlements, bank_entries, ledger_entries = [], [], []

    # Dynamic base date within the last 90 days
    days_ago = random.randint(10, 60)
    base_date = datetime.now() - timedelta(days=days_ago)

    # Assign randomized failure modes weighted by failure distribution
    failure_weights = [
        random.choices(FAILURE_MODES, weights=FAILURE_WEIGHTS)[0]
        for _ in range(n_records)
    ]

    # Pre-plan batch groups for batch failure mode
    batch_indices = [i for i, f in enumerate(failure_weights) if f == "batch"]
    batch_groups = {}
    group_id = 0
    idx = 0
    while idx < len(batch_indices):
        group_size = random.choice([2, 3]) if idx + 1 < len(batch_indices) else 1
        members = batch_indices[idx : idx + group_size]
        if len(members) >= 2:
            for m in members:
                batch_groups[m] = group_id
            group_id += 1
        idx += group_size

    # Shared UTRs for batch groups
    shared_utrs = {}
    for gid in sorted(set(batch_groups.values())):
        bank_code = random.choice(BANKS)
        date_str = base_date.strftime("%d%m%y")
        rand_seq = "".join(random.choices(string.ascii_uppercase + string.digits, k=9))
        shared_utrs[gid] = f"NEFT{bank_code}{date_str}{rand_seq}"

    for i in range(n_records):
        order_id = generate_order_id()
        payment_id = generate_payment_id()
        settlement_id = generate_settlement_id()

        # High amount variance: ₹150 to ₹45,000 with realistic paise
        gross = round(random.uniform(150.0, 45000.0), 2)
        amounts = calculate_net_amount(gross)

        # Random date spread over a 30-day window
        settlement_date = base_date + timedelta(days=random.randint(0, 30))
        utr = generate_utr(settlement_date)

        failure = failure_weights[i]

        bank_utr = utr
        bank_credit = amounts["net"]
        bank_date = settlement_date + timedelta(days=1)  # default T+1
        refund = 0.0

        if failure == "lag":
            # Simulate T+2 or T+3 credit cycle
            bank_date = settlement_date + timedelta(days=random.choice([1, 2, 3]))

        elif failure == "utr_typo":
            # Flip 1 digit in UTR
            utr_list = list(utr)
            idx_flip = random.randint(4, len(utr_list) - 1)
            if utr_list[idx_flip].isdigit():
                utr_list[idx_flip] = str((int(utr_list[idx_flip]) + 1) % 10)
            else:
                utr_list[idx_flip] = random.choice(string.ascii_uppercase)
            bank_utr = "".join(utr_list)

        elif failure == "batch":
            gid = batch_groups.get(i)
            if gid is not None:
                utr = shared_utrs[gid]
                bank_utr = shared_utrs[gid]
                members = [m for m, g in batch_groups.items() if g == gid]
                group_base = base_date + timedelta(days=random.randint(0, 25))
                settlement_date = group_base + timedelta(days=members.index(i))
                bank_date = settlement_date + timedelta(days=1)
            else:
                failure = "clean"

        elif failure == "refund":
            # Refund between ₹25 and 30% of gross
            refund = round(random.uniform(25.0, min(500.0, gross * 0.3)), 2)
            bank_credit = round(amounts["net"] - refund, 2)

        elif failure == "rounding":
            # Paise rounding drift up to ₹0.99
            drift = round(random.uniform(0.01, 0.99), 2) * random.choice([-1, 1])
            bank_credit = round(amounts["net"] + drift, 2)

        # SOURCE 1: Settlement Report
        settlements.append({
            "settlement_id": settlement_id,
            "order_id": order_id,
            "payment_id": payment_id,
            "gross_amount": amounts["gross"],
            "mdr_amount": amounts["mdr"],
            "gst_on_mdr": amounts["gst_on_mdr"],
            "net_amount": amounts["net"],
            "settlement_date": settlement_date.strftime("%Y-%m-%d"),
            "utr": utr,
            "_failure_mode": failure,
            "_batch_group": batch_groups.get(i),
        })

        # SOURCE 2: Bank Statement (non-batch and non-missing only)
        if failure not in {"batch", "missing"}:
            bank_entries.append({
                "value_date": bank_date.strftime("%Y-%m-%d"),
                "utr": bank_utr,
                "credit_amount": bank_credit,
                "narration": f"NEFT CR-RAZORPAY SETTLEMENTS {bank_utr}",
            })

        # SOURCE 3: Merchant Ledger
        ledger_entries.append({
            "order_id": order_id,
            "invoice_amount": gross,
            "payment_received_date": settlement_date.strftime("%Y-%m-%d"),
            "refund_amount": refund,
            "net_receivable": round(amounts["net"] - refund, 2),
        })

        # Shuffle bank entries order for realism (bank deposits don't arrive in order)
        random.shuffle(bank_entries)

    # BATCH POST-PROCESSING
    for gid in sorted(set(batch_groups.values())):
        members = [s for s in settlements if s.get("_batch_group") == gid]
        if len(members) < 2:
            continue
        shared_utr = shared_utrs[gid]
        total_credit = round(sum(m["net_amount"] for m in members), 2)
        earliest = min(m["settlement_date"] for m in members)
        bank_date = (datetime.strptime(earliest, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        bank_entries.append({
            "value_date": bank_date,
            "utr": shared_utr,
            "credit_amount": total_credit,
            "narration": f"NEFT CR-RAZORPAY SETTLEMENTS {shared_utr}",
        })

    # Clean up internal metadata
    for s in settlements:
        s.pop("_batch_group", None)
        s.pop("_failure_mode", None)

    return (
        pd.DataFrame(settlements),
        pd.DataFrame(bank_entries),
        pd.DataFrame(ledger_entries),
    )
