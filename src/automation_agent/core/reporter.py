from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


class ReportGenerator:
    """Generate a clear business report for human review."""

    def generate_text(
        self,
        source_file: str,
        original_rows: int,
        clean_rows: pd.DataFrame,
        rejected_rows: pd.DataFrame,
        duplicate_rows: pd.DataFrame,
        validation_summary: dict,
        duplicate_summary: dict,
        project_name: str = "Business Automation Agent",
    ) -> str:
        lines = [
            f"{project_name} Report",
            "=" * 42,
            f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Source file: {source_file}",
            "",
            "Processing Summary",
            "-" * 20,
            f"Original rows: {original_rows}",
            f"Clean CRM-ready rows: {len(clean_rows)}",
            f"Rejected rows: {len(rejected_rows)}",
            f"Duplicate rows removed: {len(duplicate_rows)}",
            "",
            "Validation Issues",
            "-" * 20,
        ]

        error_counts = validation_summary.get("error_counts", {})
        if error_counts:
            for error, count in sorted(error_counts.items()):
                lines.append(f"- {error}: {count}")
        else:
            lines.append("No validation issues found.")

        lines.extend(
            [
                "",
                "Missing Value Percentages",
                "-" * 26,
            ]
        )

        for column, percentage in validation_summary.get("missing_percentages", {}).items():
            lines.append(f"- {column}: {percentage}%")

        lines.extend(
            [
                "",
                "Duplicate Detection",
                "-" * 20,
                f"Duplicate key columns: {duplicate_summary.get('duplicate_key_columns', [])}",
                f"Duplicates removed: {duplicate_summary.get('duplicates_removed', 0)}",
                "",
                "Human Approval Status",
                "-" * 22,
                "External sync is NOT automatic in this version.",
                "Review the CRM-ready output before uploading or syncing.",
            ]
        )

        return "\n".join(lines)

    def generate(
        self,
        output_path: str | Path,
        source_file: str,
        original_rows: int,
        clean_rows: pd.DataFrame,
        rejected_rows: pd.DataFrame,
        duplicate_rows: pd.DataFrame,
        validation_summary: dict,
        duplicate_summary: dict,
    ) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_text = self.generate_text(
            source_file=source_file,
            original_rows=original_rows,
            clean_rows=clean_rows,
            rejected_rows=rejected_rows,
            duplicate_rows=duplicate_rows,
            validation_summary=validation_summary,
            duplicate_summary=duplicate_summary,
        )
        output_path.write_text(report_text, encoding="utf-8")
