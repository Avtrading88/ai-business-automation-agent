import re

import pandas as pd


class DataValidator:
    """Validate contact/customer data and separate clean rows from rejected rows."""

    EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

    def __init__(self, config: dict):
        self.config = config or {}
        self.validation_config = self.config.get("validation", {})

    def validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        validated = df.copy()
        validated["validation_errors"] = ""

        self._validate_required_columns_exist(validated)
        self._validate_required_values(validated)
        self._validate_identity_group(validated)
        self._validate_email_format(validated)
        self._validate_country(validated)

        rejected_mask = validated["validation_errors"].str.len() > 0
        rejected_rows = validated[rejected_mask].copy()
        clean_rows = validated[~rejected_mask].copy()

        clean_rows = clean_rows.drop(columns=["validation_errors"], errors="ignore")

        validation_summary = self._build_validation_summary(validated, rejected_rows)
        return clean_rows, rejected_rows, validation_summary

    def _validate_required_columns_exist(self, df: pd.DataFrame) -> None:
        required_columns = self.validation_config.get("required_columns", [])
        missing_columns = [column for column in required_columns if column not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")

    def _add_error(self, df: pd.DataFrame, mask: pd.Series, error_message: str) -> None:
        df.loc[mask, "validation_errors"] = df.loc[mask, "validation_errors"].apply(
            lambda current: f"{current}; {error_message}" if current else error_message
        )

    def _validate_required_values(self, df: pd.DataFrame) -> None:
        required_columns = self.validation_config.get("required_columns", [])
        for column in required_columns:
            if column in df.columns:
                mask = df[column].isna()
                self._add_error(df, mask, f"missing required value: {column}")

    def _validate_identity_group(self, df: pd.DataFrame) -> None:
        group = self.validation_config.get("at_least_one_required_group", [])
        existing_columns = [column for column in group if column in df.columns]
        if not existing_columns:
            return
        mask = df[existing_columns].isna().all(axis=1)
        self._add_error(
            df,
            mask,
            f"at least one identity field required: {', '.join(existing_columns)}",
        )

    def _validate_email_format(self, df: pd.DataFrame) -> None:
        if "email" not in df.columns:
            return

        def is_invalid_email(value) -> bool:
            if pd.isna(value):
                return False
            return not bool(self.EMAIL_PATTERN.match(str(value).strip()))

        mask = df["email"].apply(is_invalid_email)
        self._add_error(df, mask, "invalid email format")

    def _validate_country(self, df: pd.DataFrame) -> None:
        if "country" not in df.columns:
            return

        allowed = self.validation_config.get("allowed_countries", [])
        if not allowed:
            return

        allowed_normalized = {str(country).strip().lower() for country in allowed}
        mask = df["country"].notna() & ~df["country"].astype("string").str.lower().isin(
            allowed_normalized
        )
        self._add_error(df, mask, "country is not in allowed list")

    def _build_validation_summary(self, df: pd.DataFrame, rejected_rows: pd.DataFrame) -> dict:
        error_counts: dict[str, int] = {}
        if not rejected_rows.empty:
            for errors in rejected_rows["validation_errors"].dropna():
                for error in str(errors).split("; "):
                    error_counts[error] = error_counts.get(error, 0) + 1

        missing_percentages = {
            column: round(float(df[column].isna().mean() * 100), 2)
            for column in df.columns
            if column != "validation_errors"
        }

        return {
            "total_rows_after_cleaning": int(len(df)),
            "valid_rows": int(len(df) - len(rejected_rows)),
            "rejected_rows": int(len(rejected_rows)),
            "error_counts": error_counts,
            "missing_percentages": missing_percentages,
        }
