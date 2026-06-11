from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation_agent.core.database import DatabaseManager


@dataclass
class AuditEvent:
    """One reviewable automation action for CRM/accounting sync."""

    timestamp_utc: str
    system: str
    action: str
    status: str
    source_row: str = ""
    external_id: str = ""
    record_key: str = ""
    message: str = ""
    error: str = ""
    payload_preview: str = ""


class AuditLogger:
    """Writes audit events to CSV and JSONL so business actions are traceable."""

    FIELDNAMES = [
        "timestamp_utc",
        "system",
        "action",
        "status",
        "source_row",
        "external_id",
        "record_key",
        "message",
        "error",
        "payload_preview",
    ]

    def __init__(
        self,
        output_folder: str | Path = "data/output",
        csv_name: str = "automation_audit_log.csv",
        jsonl_name: str = "automation_audit_log.jsonl",
        db_path: str | Path | None = None,
    ) -> None:
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.output_folder / csv_name
        self.jsonl_path = self.output_folder / jsonl_name
        self.db = DatabaseManager(db_path or self.output_folder / "automation_agent.db")
        self._ensure_csv_header()

    def log(
        self,
        *,
        system: str,
        action: str,
        status: str,
        source_row: Any = "",
        external_id: str = "",
        record_key: str = "",
        message: str = "",
        error: str = "",
        payload_preview: Any = "",
    ) -> AuditEvent:
        event = AuditEvent(
            timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            system=system,
            action=action,
            status=status,
            source_row=str(source_row) if source_row is not None else "",
            external_id=external_id or "",
            record_key=record_key or "",
            message=message or "",
            error=error or "",
            payload_preview=self._serialize_payload(payload_preview),
        )
        self._append_csv(event)
        self._append_jsonl(event)
        self.db.insert_audit_event(asdict(event))
        return event

    def log_many_planned(
        self,
        *,
        system: str,
        action: str,
        payloads: list[dict[str, Any]],
        record_key_field: str = "",
    ) -> None:
        for index, payload in enumerate(payloads, start=1):
            record_key = ""
            if record_key_field:
                record_key = str(payload.get(record_key_field, ""))
            if not record_key:
                record_key = self._guess_record_key(payload)
            self.log(
                system=system,
                action=action,
                status="planned",
                source_row=index,
                record_key=record_key,
                message="Prepared for review. No API write has been performed yet.",
                payload_preview=payload,
            )

    def read_as_dataframe(self):
        import pandas as pd

        if not self.csv_path.exists():
            return pd.DataFrame(columns=self.FIELDNAMES)
        return pd.read_csv(self.csv_path)

    def _ensure_csv_header(self) -> None:
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            with self.csv_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.FIELDNAMES)
                writer.writeheader()

    def _append_csv(self, event: AuditEvent) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.FIELDNAMES)
            writer.writerow(asdict(event))

    def _append_jsonl(self, event: AuditEvent) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    @staticmethod
    def _serialize_payload(payload: Any) -> str:
        if payload in (None, ""):
            return ""
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)[:4000]
        except TypeError:
            return str(payload)[:4000]

    @staticmethod
    def _guess_record_key(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        properties = (
            payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        )
        primary_email = (
            payload.get("PrimaryEmailAddr")
            if isinstance(payload.get("PrimaryEmailAddr"), dict)
            else {}
        )
        email = properties.get("email") or primary_email.get("Address", "")
        return str(
            payload.get("DisplayName")
            or payload.get("DocNumber")
            or payload.get("id")
            or email
            or ""
        )
