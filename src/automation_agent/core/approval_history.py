from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from automation_agent.core.database import DatabaseManager


@dataclass
class ApprovalRecord:
    """One approval decision for a specific processed file/version."""

    approval_id: str
    timestamp_utc: str
    approved_by: str
    approval_status: str
    approval_scope: str
    approver_role: str
    permission_result: str
    source_name: str
    source_hash: str
    output_file: str
    output_hash: str
    original_rows: int
    crm_ready_rows: int
    rejected_rows: int
    duplicate_rows: int
    project_name: str
    project_version: str
    note: str = ""


class ApprovalHistory:
    """Stores approval history in CSV and JSONL for compliance-style review."""

    FIELDNAMES = [
        "approval_id",
        "timestamp_utc",
        "approved_by",
        "approval_status",
        "approval_scope",
        "approver_role",
        "permission_result",
        "source_name",
        "source_hash",
        "output_file",
        "output_hash",
        "original_rows",
        "crm_ready_rows",
        "rejected_rows",
        "duplicate_rows",
        "project_name",
        "project_version",
        "note",
    ]

    def __init__(
        self,
        output_folder: str | Path = "data/output",
        csv_name: str = "approval_history.csv",
        jsonl_name: str = "approval_history.jsonl",
    ) -> None:
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.output_folder / csv_name
        self.jsonl_path = self.output_folder / jsonl_name
        self.db = DatabaseManager(self.output_folder / "automation_agent.db")
        self._ensure_csv_header()

    def record(
        self,
        *,
        approved_by: str,
        approval_status: str,
        approval_scope: str,
        source_name: str,
        project_name: str,
        project_version: str,
        approver_role: str = "",
        permission_result: str = "",
        original_rows: int,
        crm_ready_rows: int,
        rejected_rows: int,
        duplicate_rows: int,
        output_file: str | Path = "",
        source_file: str | Path = "",
        output_dataframe: pd.DataFrame | None = None,
        note: str = "",
    ) -> ApprovalRecord:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        output_file_path = Path(output_file) if output_file else Path("")
        source_file_path = Path(source_file) if source_file else Path("")
        source_hash = (
            self._hash_file(source_file_path)
            if source_file_path and source_file_path.exists()
            else self._hash_text(source_name)
        )
        output_hash = ""
        if output_file_path and output_file_path.exists():
            output_hash = self._hash_file(output_file_path)
        elif output_dataframe is not None:
            output_hash = self._hash_dataframe(output_dataframe)

        approval_id = self._make_approval_id(
            timestamp=timestamp,
            approved_by=approved_by,
            source_hash=source_hash,
            output_hash=output_hash,
            approval_scope=approval_scope,
        )

        record = ApprovalRecord(
            approval_id=approval_id,
            timestamp_utc=timestamp,
            approved_by=(approved_by or "unknown").strip(),
            approval_status=approval_status,
            approval_scope=approval_scope,
            approver_role=approver_role or "",
            permission_result=permission_result or "",
            source_name=source_name,
            source_hash=source_hash,
            output_file=str(output_file) if output_file else "",
            output_hash=output_hash,
            original_rows=int(original_rows),
            crm_ready_rows=int(crm_ready_rows),
            rejected_rows=int(rejected_rows),
            duplicate_rows=int(duplicate_rows),
            project_name=project_name,
            project_version=project_version,
            note=note or "",
        )
        self._append_csv(record)
        self._append_jsonl(record)
        self.db.insert_approval_record(asdict(record))
        self._write_latest_manifest(record)
        return record

    def read_as_dataframe(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame(columns=self.FIELDNAMES)
        return pd.read_csv(self.csv_path)

    def _ensure_csv_header(self) -> None:
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            with self.csv_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.FIELDNAMES)
                writer.writeheader()
            return

        # If the project version added new approval columns, keep the old rows and add the new headers safely.
        existing_df = pd.read_csv(self.csv_path)
        if list(existing_df.columns) != self.FIELDNAMES:
            for field in self.FIELDNAMES:
                if field not in existing_df.columns:
                    existing_df[field] = ""
            existing_df = existing_df[self.FIELDNAMES]
            existing_df.to_csv(self.csv_path, index=False)

    def _append_csv(self, record: ApprovalRecord) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.FIELDNAMES)
            writer.writerow(asdict(record))

    def _append_jsonl(self, record: ApprovalRecord) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _write_latest_manifest(self, record: ApprovalRecord) -> None:
        latest_path = self.output_folder / "latest_approval_manifest.json"
        latest_path.write_text(
            json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_dataframe(df: pd.DataFrame) -> str:
        csv_text = df.to_csv(index=False)
        return hashlib.sha256(csv_text.encode("utf-8")).hexdigest()

    @staticmethod
    def _make_approval_id(
        *, timestamp: str, approved_by: str, source_hash: str, output_hash: str, approval_scope: str
    ) -> str:
        raw = "|".join(
            [
                timestamp,
                approved_by or "",
                source_hash or "",
                output_hash or "",
                approval_scope or "",
            ]
        )
        return "appr_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
