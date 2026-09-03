import pytest
from settlematch.cost_comparison import compute_time_saved


def test_compute_time_saved_standard():
    # 100 records, 3 mins per record -> 300 mins -> 5.0 manual hours
    # 2.88 seconds elapsed -> 5.0 - (2.88 / 3600) ~ 5.0 hours saved
    res = compute_time_saved(total_records=100, elapsed_seconds=2.88, manual_minutes_per_record=3.0)
    assert res["manual_hours"] == 5.0
    assert res["automated_seconds"] == 2.88
    assert res["hours_saved"] == 5.0


def test_compute_time_saved_zero_records():
    res = compute_time_saved(total_records=0, elapsed_seconds=0.0)
    assert res["manual_hours"] == 0.0
    assert res["automated_seconds"] == 0.0
    assert res["hours_saved"] == 0.0


def test_compute_time_saved_custom_manual_rate():
    # 60 records, 5 mins per record -> 300 mins -> 5.0 manual hours
    # 180 seconds automated -> 0.05 hours -> 4.95 hours saved
    res = compute_time_saved(total_records=60, elapsed_seconds=180.0, manual_minutes_per_record=5.0)
    assert res["manual_hours"] == 5.0
    assert res["automated_seconds"] == 180.0
    assert res["hours_saved"] == 4.95


def test_compute_time_saved_negative_inputs_raise():
    with pytest.raises(ValueError):
        compute_time_saved(total_records=-10, elapsed_seconds=5.0)
