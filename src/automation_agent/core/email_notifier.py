from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


@dataclass
class NotificationResult:
    enabled: bool
    dry_run: bool
    success: bool
    subject: str
    recipients: list[str]
    preview_file: str
    event_file: str
    message: str
    error: str = ""


class EmailNotifier:
    """SMTP email notifier for job summaries and failures.

    Safe by default:
    - disabled unless notifications.email.enabled=true
    - dry-run unless notifications.email.dry_run=false
    - stores every notification attempt as JSONL
    - writes the latest email body to a local preview file
    """

    def __init__(self, config: dict[str, Any]):
        if load_dotenv:
            load_dotenv()
        self.config = config
        output_folder = Path(config.get("output", {}).get("folder", "data/output"))
        email_config = config.get("notifications", {}).get("email", {})
        self.enabled = bool(email_config.get("enabled", False))
        self.dry_run = bool(email_config.get("dry_run", True))
        self.notify_on_success = bool(email_config.get("notify_on_success", True))
        self.notify_on_failure = bool(email_config.get("notify_on_failure", True))
        self.notify_on_rejected_rows = bool(email_config.get("notify_on_rejected_rows", True))
        self.smtp_host = str(email_config.get("smtp_host", os.getenv("SMTP_HOST", ""))).strip()
        self.smtp_port = int(email_config.get("smtp_port", os.getenv("SMTP_PORT", "587") or 587))
        self.use_tls = bool(email_config.get("use_tls", True))
        self.from_email = str(
            email_config.get("from_email", os.getenv("SMTP_FROM_EMAIL", ""))
        ).strip()
        self.username = str(email_config.get("username", os.getenv("SMTP_USERNAME", ""))).strip()
        self.password = str(os.getenv("SMTP_PASSWORD", "")).strip()
        self.recipients = self._normalize_recipients(email_config.get("recipients", []))
        self.subject_prefix = str(
            email_config.get("subject_prefix", "[Business Automation Agent]")
        ).strip()
        self.preview_file = Path(
            email_config.get(
                "preview_file", output_folder / "latest_email_notification_preview.txt"
            )
        )
        self.event_file = Path(
            email_config.get("event_file", output_folder / "email_notification_events.jsonl")
        )
        self.preview_file.parent.mkdir(parents=True, exist_ok=True)
        self.event_file.parent.mkdir(parents=True, exist_ok=True)

    def _normalize_recipients(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            return [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    def should_notify_for_job_summary(self, summary: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        failed_count = int(summary.get("failed_count", 0) or 0)
        processed_count = int(summary.get("processed_count", 0) or 0)
        rejected_rows = self._count_rejected_rows(summary)
        if failed_count > 0 and self.notify_on_failure:
            return True
        if rejected_rows > 0 and self.notify_on_rejected_rows:
            return True
        if processed_count > 0 and self.notify_on_success:
            return True
        return False

    def _count_rejected_rows(self, summary: dict[str, Any]) -> int:
        total = 0
        for item in summary.get("processed", []) or []:
            try:
                total += int(item.get("rejected_rows", 0) or 0)
            except Exception:
                continue
        return total

    def build_job_summary_email(self, summary: dict[str, Any]) -> tuple[str, str]:
        failed_count = int(summary.get("failed_count", 0) or 0)
        rejected_rows = self._count_rejected_rows(summary)
        status = "FAILED" if failed_count else "COMPLETED"
        if rejected_rows and not failed_count:
            status = "COMPLETED WITH REJECTED ROWS"
        subject = (
            f"{self.subject_prefix} Scheduled job {status}: {summary.get('job_id', 'unknown')}"
        )

        lines = [
            "Business Automation Agent scheduled job summary",
            "",
            f"Job ID: {summary.get('job_id', '')}",
            f"Job name: {summary.get('job_name', '')}",
            f"Started at: {summary.get('started_at', '')}",
            f"Finished at: {summary.get('finished_at', '')}",
            f"Files found: {summary.get('files_found', 0)}",
            f"Processed files: {summary.get('processed_count', 0)}",
            f"Failed files: {summary.get('failed_count', 0)}",
            f"Rejected rows found: {rejected_rows}",
            f"Next run at: {summary.get('next_run_at', '')}",
            "",
            "Processed files:",
        ]
        processed = summary.get("processed", []) or []
        if processed:
            for item in processed:
                lines.append(
                    "- {file} | clean={clean_rows} rejected={rejected_rows} duplicates={duplicate_rows} | archived={archived_to}".format(
                        file=item.get("file", ""),
                        clean_rows=item.get("clean_rows", item.get("crm_ready_rows", "")),
                        rejected_rows=item.get("rejected_rows", ""),
                        duplicate_rows=item.get("duplicate_rows", ""),
                        archived_to=item.get("archived_to", item.get("archive_path", "")),
                    )
                )
        else:
            lines.append("- None")

        lines.extend(["", "Failed files:"])
        failed = summary.get("failed", []) or []
        if failed:
            for item in failed:
                lines.append(
                    "- {file} | error={error} | moved_to={moved_to}".format(
                        file=item.get("file", ""),
                        error=item.get("error", ""),
                        moved_to=item.get("moved_to", ""),
                    )
                )
        else:
            lines.append("- None")

        lines.extend(
            [
                "",
                "This notification was generated automatically by the local automation agent.",
                "Review the output files before any CRM or QuickBooks sync.",
            ]
        )
        return subject, "\n".join(lines)

    def send_job_summary(self, summary: dict[str, Any]) -> NotificationResult:
        subject, body = self.build_job_summary_email(summary)
        if not self.should_notify_for_job_summary(summary):
            result = NotificationResult(
                enabled=self.enabled,
                dry_run=self.dry_run,
                success=True,
                subject=subject,
                recipients=self.recipients,
                preview_file=str(self.preview_file),
                event_file=str(self.event_file),
                message="Notification skipped by notification rules.",
            )
            self._write_event(result, {"summary": summary})
            return result
        return self.send_email(
            subject, body, metadata={"summary": summary, "type": "scheduled_job_summary"}
        )

    def send_test_email(self) -> NotificationResult:
        subject = f"{self.subject_prefix} Test notification"
        body = (
            "This is a test notification from Business Automation Agent.\n\n"
            f"Created at: {datetime.now().replace(microsecond=0).isoformat()}\n"
            "If dry-run mode is enabled, this email was saved as a preview only."
        )
        return self.send_email(subject, body, metadata={"type": "test_notification"})

    def send_email(
        self, subject: str, body: str, metadata: dict[str, Any] | None = None
    ) -> NotificationResult:
        self.preview_file.write_text(
            f"Subject: {subject}\nTo: {', '.join(self.recipients)}\n\n{body}\n", encoding="utf-8"
        )

        if not self.enabled:
            result = NotificationResult(
                False,
                self.dry_run,
                True,
                subject,
                self.recipients,
                str(self.preview_file),
                str(self.event_file),
                "Email notifications are disabled.",
            )
            self._write_event(result, metadata or {})
            return result
        if not self.recipients:
            result = NotificationResult(
                True,
                self.dry_run,
                False,
                subject,
                self.recipients,
                str(self.preview_file),
                str(self.event_file),
                "No email recipients configured.",
                "Missing recipients",
            )
            self._write_event(result, metadata or {})
            return result
        if self.dry_run:
            result = NotificationResult(
                True,
                True,
                True,
                subject,
                self.recipients,
                str(self.preview_file),
                str(self.event_file),
                "Dry-run mode: email preview saved, no email sent.",
            )
            self._write_event(result, metadata or {})
            return result

        missing = []
        if not self.smtp_host:
            missing.append("SMTP_HOST / smtp_host")
        if not self.from_email:
            missing.append("SMTP_FROM_EMAIL / from_email")
        if not self.username:
            missing.append("SMTP_USERNAME / username")
        if not self.password:
            missing.append("SMTP_PASSWORD")
        if missing:
            result = NotificationResult(
                True,
                False,
                False,
                subject,
                self.recipients,
                str(self.preview_file),
                str(self.event_file),
                "SMTP settings are incomplete.",
                ", ".join(missing),
            )
            self._write_event(result, metadata or {})
            return result

        try:
            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = self.from_email
            message["To"] = ", ".join(self.recipients)
            message.set_content(body)

            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                    server.starttls(context=context)
                    server.login(self.username, self.password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                    server.login(self.username, self.password)
                    server.send_message(message)

            result = NotificationResult(
                True,
                False,
                True,
                subject,
                self.recipients,
                str(self.preview_file),
                str(self.event_file),
                "Email sent successfully.",
            )
        except Exception as error:
            result = NotificationResult(
                True,
                False,
                False,
                subject,
                self.recipients,
                str(self.preview_file),
                str(self.event_file),
                "Email send failed.",
                str(error),
            )
        self._write_event(result, metadata or {})
        return result

    def _write_event(self, result: NotificationResult, metadata: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now().replace(microsecond=0).isoformat(),
            "enabled": result.enabled,
            "dry_run": result.dry_run,
            "success": result.success,
            "subject": result.subject,
            "recipients": result.recipients,
            "message": result.message,
            "error": result.error,
            "preview_file": result.preview_file,
            "metadata": metadata,
        }
        with self.event_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_events(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.event_file.exists():
            return []
        lines = self.event_file.read_text(encoding="utf-8").splitlines()[-limit:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events
