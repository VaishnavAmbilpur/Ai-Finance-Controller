"""
Human-Cost Comparison Metric for SettleMatch.

Translates total records and execution runtime into estimated manual hours saved.
"""

def compute_time_saved(
    total_records: int,
    elapsed_seconds: float,
    manual_minutes_per_record: float = 3.0,
) -> dict:
    """
    Computes manual processing time vs automated pipeline execution time.

    Args:
        total_records: Number of total settlement records processed.
        elapsed_seconds: Total wall-clock execution time in seconds.
        manual_minutes_per_record: Stated baseline assumption for manual audit time per record.

    Returns:
        dict containing:
            - manual_hours: Estimated hours required for manual audit (float)
            - automated_seconds: Execution time in seconds (float)
            - hours_saved: Estimated net hours saved (float)
    """
    if total_records < 0 or elapsed_seconds < 0 or manual_minutes_per_record < 0:
        raise ValueError("Inputs to compute_time_saved cannot be negative.")

    manual_hours = round((total_records * manual_minutes_per_record) / 60.0, 2)
    automated_seconds = round(float(elapsed_seconds), 2)
    automated_hours = elapsed_seconds / 3600.0
    hours_saved = round(manual_hours - automated_hours, 2)

    return {
        "manual_hours": manual_hours,
        "automated_seconds": automated_seconds,
        "hours_saved": hours_saved,
    }
