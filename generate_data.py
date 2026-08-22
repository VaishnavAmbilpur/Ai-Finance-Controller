from settlematch.generator import generate_dataset

if __name__ == "__main__":
    settlements, bank, ledger = generate_dataset(n_records=65)

    settlements_clean = settlements.drop(columns=["_failure_mode"])
    settlements_clean.to_csv("data/settlement_report.csv", index=False)
    bank.to_csv("data/bank_statement.csv", index=False)
    ledger.to_csv("data/merchant_ledger.csv", index=False)

    print(f"Generated: {len(settlements)} settlements, {len(bank)} bank entries, {len(ledger)} ledger entries")
    print("Saved to data/")
