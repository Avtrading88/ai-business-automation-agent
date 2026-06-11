from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def base_config(tmp_path: Path) -> dict:
    """Small safe test config using a temporary output folder."""
    return {
        "project": {"name": "Business Automation Agent Test", "version": "24.0.0"},
        "output": {
            "folder": str(tmp_path / "output"),
            "clean_file": "crm_ready_contacts.csv",
            "rejected_file": "rejected_rows.csv",
            "duplicates_file": "duplicates_removed.csv",
            "report_file": "report.txt",
        },
        "validation": {
            "required_columns": ["email"],
            "at_least_one_required_group": ["first_name", "last_name", "company"],
            "duplicate_key_columns": ["email"],
            "allowed_countries": ["germany", "usa", "united states", "bulgaria"],
        },
        "cleaning": {
            "lowercase_email": True,
            "normalize_phone": True,
            "title_case_names": True,
            "title_case_company": False,
        },
        "database": {"enabled": False},
        "file_versioning": {"enabled": False},
        "integrations": {
            "quickbooks": {"dry_run": True, "environment": "sandbox"},
            "hubspot": {"enabled": False, "dry_run": True},
        },
        "approval": {
            "role_based": {
                "enabled": True,
                "default_role": "reviewer",
            }
        },
    }
