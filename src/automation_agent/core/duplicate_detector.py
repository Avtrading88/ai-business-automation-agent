import pandas as pd


class DuplicateDetector:
    """Detect and remove duplicate CRM records using configured key columns."""

    def __init__(self, config: dict):
        self.config = config or {}

    def remove_duplicates(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        key_columns = self.config.get("validation", {}).get("duplicate_key_columns", ["email"])
        existing_key_columns = [column for column in key_columns if column in df.columns]

        if not existing_key_columns:
            return (
                df.copy(),
                pd.DataFrame(),
                {
                    "duplicate_key_columns": [],
                    "duplicates_removed": 0,
                    "message": "No duplicate key columns found.",
                },
            )

        duplicate_mask = df.duplicated(subset=existing_key_columns, keep="first")
        duplicates = df[duplicate_mask].copy()
        unique_rows = df[~duplicate_mask].copy()

        return (
            unique_rows,
            duplicates,
            {
                "duplicate_key_columns": existing_key_columns,
                "duplicates_removed": int(len(duplicates)),
            },
        )
