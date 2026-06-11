import pandas as pd
import pytest

from automation_agent.core.validator import DataValidator


def test_validator_rejects_missing_required_invalid_email_and_country(base_config):
    df = pd.DataFrame(
        [
            {"first_name": "Anna", "email": "anna@example.com", "country": "Germany"},
            {"first_name": "Bob", "email": "bad-email", "country": "Germany"},
            {"first_name": "Carla", "email": None, "country": "Germany"},
            {"first_name": "Dan", "email": "dan@example.com", "country": "Unknownland"},
            {
                "first_name": None,
                "last_name": None,
                "company": None,
                "email": "noidentity@example.com",
                "country": "USA",
            },
        ]
    )

    clean_rows, rejected_rows, summary = DataValidator(base_config).validate(df)

    assert len(clean_rows) == 1
    assert len(rejected_rows) == 4
    assert summary["valid_rows"] == 1
    assert summary["rejected_rows"] == 4
    errors = " | ".join(rejected_rows["validation_errors"].astype(str).tolist())
    assert "invalid email format" in errors
    assert "missing required value: email" in errors
    assert "country is not in allowed list" in errors
    assert "at least one identity field required" in errors


def test_validator_raises_when_required_column_is_missing(base_config):
    df = pd.DataFrame({"first_name": ["Anna"]})

    with pytest.raises(ValueError, match="Missing required columns"):
        DataValidator(base_config).validate(df)
