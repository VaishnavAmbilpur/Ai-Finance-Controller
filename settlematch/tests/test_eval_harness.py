"""
Unit tests for settlematch/eval_harness.py
"""

from settlematch.eval_harness import (
    EXCEPTION_CATEGORIES,
    categorize_exceptions,
    compute_metrics,
    print_metrics,
)
from settlematch.matcher import Decision as MatcherDecision, MatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matched_result(decision=MatcherDecision.AUTO_APPROVED):
    return MatchResult(decision=decision, method="rule", reason="ok")


def _unmatched_result(decision=MatcherDecision.MISSING_COUNTERPART, exc_cat="MISSING_COUNTERPART"):
    return MatchResult(
        decision=decision,
        method="none",
        reason="missing",
        exception_category=exc_cat,
    )


def _llm_candidate_result(amount_delta=None, date_delta_days=None, exc_cat=None):
    return MatchResult(
        decision=MatcherDecision.LLM_CANDIDATE,
        method="rule",
        reason="outside tolerance",
        amount_delta=amount_delta,
        date_delta_days=date_delta_days,
        exception_category=exc_cat,
    )


# ---------------------------------------------------------------------------
# Metric Calculation Tests
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_all_matched_100_percent(self):
        results = [_matched_result() for _ in range(10)]
        m = compute_metrics(results, elapsed=1.0, llm_calls=0, total=10)
        assert m["match_rate_pct"] == 100.0
        assert m["matched"] == 10
        assert m["exception_count"] == 0

    def test_none_matched_0_percent(self):
        results = [_unmatched_result() for _ in range(5)]
        m = compute_metrics(results, elapsed=1.0, llm_calls=0, total=5)
        assert m["match_rate_pct"] == 0.0
        assert m["matched"] == 0
        assert m["exception_count"] == 5

    def test_mixed_match_rate(self):
        results = [_matched_result()] * 7 + [_unmatched_result()] * 3
        m = compute_metrics(results, elapsed=1.0, llm_calls=0, total=10)
        assert m["match_rate_pct"] == 70.0

    def test_throughput_calculation(self):
        results = [_matched_result() for _ in range(10)]
        m = compute_metrics(results, elapsed=2.0, llm_calls=0, total=10)
        assert m["throughput_rec_per_sec"] == 5.0

    def test_llm_call_rate(self):
        results = [_matched_result() for _ in range(10)]
        m = compute_metrics(results, elapsed=1.0, llm_calls=3, total=10)
        assert m["llm_call_rate_pct"] == 30.0

    def test_zero_total_no_division_by_zero(self):
        m = compute_metrics([], elapsed=1.0, llm_calls=0, total=0)
        assert m["match_rate_pct"] == 0.0
        assert m["llm_call_rate_pct"] == 0.0
        assert m["throughput_rec_per_sec"] == 0.0

    def test_zero_elapsed_no_division_by_zero(self):
        results = [_matched_result()]
        m = compute_metrics(results, elapsed=0.0, llm_calls=0, total=1)
        assert m["throughput_rec_per_sec"] == 0.0


# ---------------------------------------------------------------------------
# Exception Categorization Tests
# ---------------------------------------------------------------------------

class TestCategorizeExceptions:
    def test_matched_records_not_in_exceptions(self):
        results = [_matched_result(MatcherDecision.AUTO_APPROVED)]
        buckets = categorize_exceptions(results)
        assert all(len(v) == 0 for v in buckets.values())

    def test_missing_counterpart_bucket(self):
        results = [_unmatched_result(
            decision=MatcherDecision.MISSING_COUNTERPART,
            exc_cat="MISSING_COUNTERPART"
        )]
        buckets = categorize_exceptions(results)
        assert len(buckets["MISSING_COUNTERPART"]) == 1

    def test_amount_delta_bucket_via_exception_category(self):
        results = [_llm_candidate_result(amount_delta=5.0, exc_cat="AMOUNT_DELTA")]
        buckets = categorize_exceptions(results)
        assert len(buckets["AMOUNT_DELTA"]) == 1

    def test_date_lag_bucket_via_exception_category(self):
        results = [_llm_candidate_result(date_delta_days=5, exc_cat="DATE_LAG")]
        buckets = categorize_exceptions(results)
        assert len(buckets["DATE_LAG"]) == 1

    def test_all_6_exception_categories_present(self):
        results = [_unmatched_result()]
        buckets = categorize_exceptions(results)
        assert set(buckets.keys()) == set(EXCEPTION_CATEGORIES)


# ---------------------------------------------------------------------------
# Print Metrics Output Tests
# ---------------------------------------------------------------------------

def test_print_metrics_output(capsys):
    results = [_matched_result()] * 8 + [_unmatched_result()] * 2
    m = compute_metrics(results, elapsed=0.5, llm_calls=1, total=10)
    print_metrics(m)
    captured = capsys.readouterr()
    assert "Match rate" in captured.out
    assert "Throughput" in captured.out
