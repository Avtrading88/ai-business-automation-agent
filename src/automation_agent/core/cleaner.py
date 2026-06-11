import re

import pandas as pd


class DataCleaner:
    """Clean contact/customer data before validation and CRM export."""

    COLUMN_ALIASES = {
        "firstname": "first_name",
        "first name": "first_name",
        "first_name": "first_name",
        "lastname": "last_name",
        "last name": "last_name",
        "last_name": "last_name",
        "e-mail": "email",
        "e_mail": "email",
        "email address": "email",
        "email_address": "email",
        "mail": "email",
        "telephone": "phone",
        "mobile": "phone",
        "phone number": "phone",
        "phone_number": "phone",
        "company name": "company",
        "company_name": "company",
        "organisation": "company",
        "organization": "company",
    }

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        cleaned = df.copy()
        cleaned = self._clean_column_names(cleaned)
        cleaned = self._strip_text_values(cleaned)
        cleaned = self._normalize_empty_values(cleaned)
        cleaned = self._normalize_email(cleaned)
        cleaned = self._normalize_phone(cleaned)
        cleaned = self._format_names(cleaned)
        cleaned = self._format_company(cleaned)
        return cleaned

    def _clean_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        def normalize_column(column: str) -> str:
            column = str(column).strip().lower()
            column = re.sub(r"[^a-z0-9]+", "_", column)
            column = column.strip("_")
            readable = column.replace("_", " ")
            return self.COLUMN_ALIASES.get(column, self.COLUMN_ALIASES.get(readable, column))

        df.columns = [normalize_column(col) for col in df.columns]
        return df

    def _strip_text_values(self, df: pd.DataFrame) -> pd.DataFrame:
        for column in df.select_dtypes(include=["object", "string"]).columns:
            df[column] = df[column].astype("string").str.strip()
        return df

    def _normalize_empty_values(self, df: pd.DataFrame) -> pd.DataFrame:
        empty_values = ["", "nan", "none", "null", "n/a", "na", "-"]
        return df.replace(empty_values, pd.NA)

    def _normalize_email(self, df: pd.DataFrame) -> pd.DataFrame:
        if "email" in df.columns and self.config.get("lowercase_email", True):
            df["email"] = df["email"].astype("string").str.lower().str.strip()
        return df

    def _normalize_phone(self, df: pd.DataFrame) -> pd.DataFrame:
        if "phone" not in df.columns or not self.config.get("normalize_phone", True):
            return df

        def clean_phone(value):
            if pd.isna(value):
                return pd.NA
            value = str(value).strip()
            value = re.sub(r"[^0-9+]", "", value)
            return value if value else pd.NA

        df["phone"] = df["phone"].apply(clean_phone)
        return df

    def _format_names(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.config.get("title_case_names", True):
            return df
        for column in ["first_name", "last_name", "city", "country"]:
            if column in df.columns:
                df[column] = df[column].astype("string").str.title()
        return df

    def _format_company(self, df: pd.DataFrame) -> pd.DataFrame:
        if "company" in df.columns and self.config.get("title_case_company", False):
            df["company"] = df["company"].astype("string").str.title()
        return df
