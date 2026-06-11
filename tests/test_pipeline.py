from pathlib import Path

import pandas as pd

from automation_agent.core.pipeline import process_dataframe


def test_process_dataframe_creates_outputs_and_report(base_config, tmp_path: Path):
    df = pd.DataFrame(
        [
            {"First Name": " Anna ", "Email": "ANNA@example.com", "Country": "Germany"},
            {"First Name": "Duplicate", "Email": "anna@example.com", "Country": "Germany"},
            {"First Name": "Bad", "Email": "bad-email", "Country": "Germany"},
        ]
    )

    result = process_dataframe(df, base_config, source_name="unit_test.csv", save_outputs=True)

    assert result.original_rows == 3
    assert len(result.crm_ready_rows) == 1
    assert len(result.duplicate_rows) == 1
    assert len(result.rejected_rows) == 1
    assert result.output_paths["clean"].exists()
    assert result.output_paths["rejected"].exists()
    assert result.output_paths["duplicates"].exists()
    assert result.output_paths["report"].exists()
    assert "unit_test.csv" in result.report_text
    assert "Duplicate rows removed" in result.report_text
