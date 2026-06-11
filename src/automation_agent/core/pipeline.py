from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from automation_agent.core.cleaner import DataCleaner
from automation_agent.core.data_reader import DataReader
from automation_agent.core.database import DatabaseManager
from automation_agent.core.duplicate_detector import DuplicateDetector
from automation_agent.core.file_versioning import FileVersionManager, VersionedRun
from automation_agent.core.reporter import ReportGenerator
from automation_agent.core.validator import DataValidator


@dataclass
class ProcessingResult:
    """Container for all files and data created by the automation pipeline."""

    original_rows: int
    cleaned_rows: pd.DataFrame
    crm_ready_rows: pd.DataFrame
    rejected_rows: pd.DataFrame
    duplicate_rows: pd.DataFrame
    validation_summary: dict[str, Any]
    duplicate_summary: dict[str, Any]
    report_text: str
    output_paths: dict[str, Path]
    versioned_run: VersionedRun | None = None


def process_dataframe(
    df: pd.DataFrame,
    config: dict,
    source_name: str = "uploaded_file",
    save_outputs: bool = True,
) -> ProcessingResult:
    """Clean, validate, deduplicate, report, and optionally save output files."""

    original_rows = len(df)

    cleaner = DataCleaner(config.get("cleaning", {}))
    cleaned_df = cleaner.clean(df)

    validator = DataValidator(config)
    valid_rows, rejected_rows, validation_summary = validator.validate(cleaned_df)

    duplicate_detector = DuplicateDetector(config)
    crm_ready_rows, duplicate_rows, duplicate_summary = duplicate_detector.remove_duplicates(
        valid_rows
    )

    output_config = config.get("output", {})
    output_folder = Path(output_config.get("folder", "data/output"))
    output_folder.mkdir(parents=True, exist_ok=True)

    output_paths = {
        "clean": output_folder / output_config.get("clean_file", "crm_ready_contacts.csv"),
        "rejected": output_folder / output_config.get("rejected_file", "rejected_rows.csv"),
        "duplicates": output_folder
        / output_config.get("duplicates_file", "duplicates_removed.csv"),
        "report": output_folder / output_config.get("report_file", "report.txt"),
    }

    reporter = ReportGenerator()
    report_text = reporter.generate_text(
        source_file=source_name,
        original_rows=original_rows,
        clean_rows=crm_ready_rows,
        rejected_rows=rejected_rows,
        duplicate_rows=duplicate_rows,
        validation_summary=validation_summary,
        duplicate_summary=duplicate_summary,
        project_name=config.get("project", {}).get("name", "Business Automation Agent"),
    )

    if save_outputs:
        crm_ready_rows.to_csv(output_paths["clean"], index=False)
        rejected_rows.to_csv(output_paths["rejected"], index=False)
        duplicate_rows.to_csv(output_paths["duplicates"], index=False)
        output_paths["report"].write_text(report_text, encoding="utf-8")

        db_cfg = config.get("database", {})
        if db_cfg.get("enabled", True):
            DatabaseManager(
                db_cfg.get("path") or output_folder / "automation_agent.db"
            ).insert_processed_file(
                source_name=source_name,
                original_rows=original_rows,
                crm_ready_rows=len(crm_ready_rows),
                rejected_rows=len(rejected_rows),
                duplicate_rows=len(duplicate_rows),
                output_folder=str(output_folder),
                report_text=report_text,
            )

        versioned_run = FileVersionManager(config).create_versioned_run(
            source_name=source_name,
            source_file=source_name if Path(str(source_name)).exists() else None,
            output_paths=output_paths,
            dataframes={
                "cleaned_rows": cleaned_df,
                "crm_ready_rows": crm_ready_rows,
                "rejected_rows": rejected_rows,
                "duplicate_rows": duplicate_rows,
            },
            report_text=report_text,
            metadata={
                "project_name": config.get("project", {}).get("name", "Business Automation Agent"),
                "project_version": config.get("project", {}).get("version", ""),
                "validation_summary": validation_summary,
                "duplicate_summary": duplicate_summary,
            },
        )
    else:
        versioned_run = None

    return ProcessingResult(
        original_rows=original_rows,
        cleaned_rows=cleaned_df,
        crm_ready_rows=crm_ready_rows,
        rejected_rows=rejected_rows,
        duplicate_rows=duplicate_rows,
        validation_summary=validation_summary,
        duplicate_summary=duplicate_summary,
        report_text=report_text,
        output_paths=output_paths,
        versioned_run=versioned_run,
    )


def process_file(
    input_file: str | Path, config: dict, save_outputs: bool = True
) -> ProcessingResult:
    """Read a CSV/Excel file and run the processing pipeline."""

    reader = DataReader()
    df = reader.read(input_file)
    return process_dataframe(df, config, source_name=str(input_file), save_outputs=save_outputs)
