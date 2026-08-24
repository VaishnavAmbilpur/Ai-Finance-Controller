from settlematch.generator import generate_dataset

if __name__ == "__main__":
    # Generates a dynamic random dataset across settlement, bank, and ledger sources
    settlements, bank, ledger = generate_dataset(n_records=65)

    settlements.to_csv("data/settlement_report.csv", index=False)
    bank.to_csv("data/bank_statement.csv", index=False)
    ledger.to_csv("data/merchant_ledger.csv", index=False)

    print(f"Generated dynamic dataset: {len(settlements)} settlements, {len(bank)} bank entries, {len(ledger)} ledger entries")
    print("Saved to data/")
