import pandas as pd

from automation_agent.core.duplicate_detector import DuplicateDetector


def test_duplicate_detector_removes_duplicate_email(base_config):
    df = pd.DataFrame(
        [
            {"email": "a@example.com", "first_name": "A"},
            {"email": "b@example.com", "first_name": "B"},
            {"email": "a@example.com", "first_name": "A Duplicate"},
        ]
    )

    unique_rows, duplicates, summary = DuplicateDetector(base_config).remove_duplicates(df)

    assert len(unique_rows) == 2
    assert len(duplicates) == 1
    assert duplicates.iloc[0]["first_name"] == "A Duplicate"
    assert summary["duplicates_removed"] == 1
    assert summary["duplicate_key_columns"] == ["email"]
