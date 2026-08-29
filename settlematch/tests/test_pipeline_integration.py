"""
Integration tests for main.py — run_pipeline()
"""

from unittest.mock import AsyncMock, patch

from settlematch.adjudicator import AdjudicationResult, DecisionType
from settlematch.generator import generate_dataset


def _escalate_mock():
    return AsyncMock(return_value=AdjudicationResult(
        decision=DecisionType.ESCALATE_TO_HUMAN,
        reason="Mocked: API error during adjudication after retry — cannot determine match",
        confidence=0.0,
    ))


def _setup_csvs(tmp_path, n_records):
    settlements, bank, ledger = generate_dataset(n_records)
    s_path = str(tmp_path / "settlement_report.csv")
    b_path = str(tmp_path / "bank_statement.csv")
    l_path = str(tmp_path / "merchant_ledger.csv")
    settlements.to_csv(s_path, index=False)
    bank.to_csv(b_path, index=False)
    ledger.to_csv(l_path, index=False)
    return s_path, b_path, l_path


class TestRunPipelineMetrics:
    def test_returns_dict_with_required_keys(self, tmp_path):
        from main import run_pipeline
        s_path, b_path, l_path = _setup_csvs(tmp_path, 10)

        with patch("main.adjudicate_async", _escalate_mock()):
            metrics = run_pipeline(s_path, b_path, l_path)

        for key in ("total_records", "matched", "match_rate_pct", "throughput_rec_per_sec",
                    "llm_call_rate_pct", "elapsed_seconds", "exception_count", "exception_breakdown"):
            assert key in metrics, f"Missing key: {key}"

    def test_match_rate_in_valid_range(self, tmp_path):
        from main import run_pipeline
        s_path, b_path, l_path = _setup_csvs(tmp_path, 20)
        with patch("main.adjudicate_async", _escalate_mock()):
            metrics = run_pipeline(s_path, b_path, l_path)
        assert 0.0 <= metrics["match_rate_pct"] <= 100.0

    def test_total_records_matches_input(self, tmp_path):
        from main import run_pipeline
        N = 15
        s_path, b_path, l_path = _setup_csvs(tmp_path, N)
        with patch("main.adjudicate_async", _escalate_mock()):
            metrics = run_pipeline(s_path, b_path, l_path)
        assert metrics["total_records"] == N

    def test_llm_calls_counted_for_candidates(self, tmp_path):
        from main import run_pipeline
        N = 30
        s_path, b_path, l_path = _setup_csvs(tmp_path, N)
        mock_adj = _escalate_mock()
        with patch("main.adjudicate_async", mock_adj):
            metrics = run_pipeline(s_path, b_path, l_path)
        expected_rate = round(mock_adj.call_count / N * 100, 1)
        assert metrics["llm_call_rate_pct"] == expected_rate

    def test_matched_plus_exceptions_equals_total(self, tmp_path):
        from main import run_pipeline
        s_path, b_path, l_path = _setup_csvs(tmp_path, 20)
        with patch("main.adjudicate_async", _escalate_mock()):
            metrics = run_pipeline(s_path, b_path, l_path)
        assert metrics["matched"] + metrics["exception_count"] == metrics["total_records"]

    def test_pipeline_100_records_reproducible(self, tmp_path):
        from main import run_pipeline
        settlements, bank, ledger = generate_dataset(n_records=100, seed=42)
        s_path = str(tmp_path / "settlement_report.csv")
        b_path = str(tmp_path / "bank_statement.csv")
        l_path = str(tmp_path / "merchant_ledger.csv")
        settlements.to_csv(s_path, index=False)
        bank.to_csv(b_path, index=False)
        ledger.to_csv(l_path, index=False)

        with patch("main.adjudicate_async", _escalate_mock()):
            metrics = run_pipeline(s_path, b_path, l_path)

        assert metrics["total_records"] == 100
        assert metrics["exception_count"] > 0
        assert "MISSING_COUNTERPART" in metrics["exception_breakdown"]

