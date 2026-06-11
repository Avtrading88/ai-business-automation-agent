from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from automation_agent.core.email_notifier import EmailNotifier
from automation_agent.core.pipeline import process_file

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


@dataclass
class ScheduledJob:
    job_id: str
    name: str
    enabled: bool
    input_folder: str
    archive_folder: str
    error_folder: str
    cadence: str = "manual"  # manual, hourly, daily
    run_time: str = "09:00"
    last_run_at: str = ""
    next_run_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""


class ScheduledJobManager:
    """Small local scheduler manager for file-processing automation jobs.

    This is intentionally simple and safe: it does not run a background process by itself.
    The dashboard or CLI calls run_due_jobs() or run_job_now() explicitly.
    For real production scheduling, call the CLI command from Windows Task Scheduler,
    cron, GitHub Actions self-hosted runner, or a server process.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        output_folder = Path(config.get("output", {}).get("folder", "data/output"))
        scheduler_config = config.get("scheduler", {})
        self.enabled = bool(scheduler_config.get("enabled", True))
        self.jobs_file = Path(
            scheduler_config.get("jobs_file", output_folder / "scheduled_jobs.json")
        )
        self.events_file = Path(
            scheduler_config.get("events_file", output_folder / "scheduled_job_events.jsonl")
        )
        self.default_input_folder = Path(
            scheduler_config.get("default_input_folder", "data/scheduled_input")
        )
        self.default_archive_folder = Path(
            scheduler_config.get("default_archive_folder", "data/scheduled_archive")
        )
        self.default_error_folder = Path(
            scheduler_config.get("default_error_folder", "data/scheduled_errors")
        )
        self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        self.default_input_folder.mkdir(parents=True, exist_ok=True)
        self.default_archive_folder.mkdir(parents=True, exist_ok=True)
        self.default_error_folder.mkdir(parents=True, exist_ok=True)
        self._ensure_jobs_file()

    def _now(self) -> datetime:
        return datetime.now().replace(microsecond=0)

    def _ensure_jobs_file(self) -> None:
        if self.jobs_file.exists():
            return
        now = self._now().isoformat()
        default_job = ScheduledJob(
            job_id="daily_file_cleaning",
            name="Daily folder cleaning job",
            enabled=False,
            input_folder=str(self.default_input_folder),
            archive_folder=str(self.default_archive_folder),
            error_folder=str(self.default_error_folder),
            cadence="daily",
            run_time="09:00",
            next_run_at="",
            created_at=now,
            updated_at=now,
            notes="Disabled by default. Enable it from the dashboard when ready.",
        )
        self.save_jobs([default_job])

    def load_jobs(self) -> list[ScheduledJob]:
        if not self.jobs_file.exists():
            self._ensure_jobs_file()
        raw = json.loads(self.jobs_file.read_text(encoding="utf-8"))
        return [ScheduledJob(**item) for item in raw]

    def save_jobs(self, jobs: list[ScheduledJob]) -> None:
        self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(job) for job in jobs]
        self.jobs_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def upsert_job(
        self,
        *,
        job_id: str,
        name: str,
        enabled: bool,
        input_folder: str,
        archive_folder: str,
        error_folder: str,
        cadence: str,
        run_time: str,
        notes: str = "",
    ) -> ScheduledJob:
        jobs = self.load_jobs()
        now = self._now().isoformat()
        existing = next((job for job in jobs if job.job_id == job_id), None)
        if existing:
            existing.name = name
            existing.enabled = enabled
            existing.input_folder = input_folder
            existing.archive_folder = archive_folder
            existing.error_folder = error_folder
            existing.cadence = cadence
            existing.run_time = run_time
            existing.notes = notes
            existing.updated_at = now
            job = existing
        else:
            job = ScheduledJob(
                job_id=job_id,
                name=name,
                enabled=enabled,
                input_folder=input_folder,
                archive_folder=archive_folder,
                error_folder=error_folder,
                cadence=cadence,
                run_time=run_time,
                created_at=now,
                updated_at=now,
                notes=notes,
            )
            jobs.append(job)
        job.next_run_at = (
            self.calculate_next_run(job).isoformat()
            if job.enabled and job.cadence != "manual"
            else ""
        )
        self.save_jobs(jobs)
        self.log_event(
            job.job_id, "job_saved", "success", f"Saved job {job.name}", {"job": asdict(job)}
        )
        return job

    def delete_job(self, job_id: str) -> bool:
        jobs = self.load_jobs()
        remaining = [job for job in jobs if job.job_id != job_id]
        changed = len(remaining) != len(jobs)
        if changed:
            self.save_jobs(remaining)
            self.log_event(job_id, "job_deleted", "success", "Deleted scheduled job", {})
        return changed

    def calculate_next_run(self, job: ScheduledJob, from_time: datetime | None = None) -> datetime:
        base = from_time or self._now()
        if job.cadence == "hourly":
            return base + timedelta(hours=1)
        if job.cadence == "daily":
            hour, minute = self._parse_run_time(job.run_time)
            candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= base:
                candidate += timedelta(days=1)
            return candidate
        return base

    def _parse_run_time(self, value: str) -> tuple[int, int]:
        try:
            hour, minute = str(value).split(":")[:2]
            return max(0, min(23, int(hour))), max(0, min(59, int(minute)))
        except Exception:
            return 9, 0

    def due_jobs(self) -> list[ScheduledJob]:
        if not self.enabled:
            return []
        now = self._now()
        due = []
        for job in self.load_jobs():
            if not job.enabled or job.cadence == "manual":
                continue
            if not job.next_run_at:
                due.append(job)
                continue
            try:
                next_run = datetime.fromisoformat(job.next_run_at)
                if next_run <= now:
                    due.append(job)
            except ValueError:
                due.append(job)
        return due

    def discover_files(self, job: ScheduledJob) -> list[Path]:
        input_folder = Path(job.input_folder)
        input_folder.mkdir(parents=True, exist_ok=True)
        return sorted(
            path
            for path in input_folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    def run_due_jobs(self, *, max_files_per_job: int | None = None) -> list[dict[str, Any]]:
        results = []
        for job in self.due_jobs():
            results.append(self.run_job_now(job.job_id, max_files=max_files_per_job))
        return results

    def run_job_now(self, job_id: str, *, max_files: int | None = None) -> dict[str, Any]:
        jobs = self.load_jobs()
        job = next((item for item in jobs if item.job_id == job_id), None)
        if job is None:
            raise ValueError(f"Scheduled job not found: {job_id}")

        started_at = self._now()
        files = self.discover_files(job)
        if max_files is not None:
            files = files[:max_files]

        processed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for file_path in files:
            try:
                result = process_file(file_path, self.config, save_outputs=True)
                archive_path = self._move_file(file_path, Path(job.archive_folder))
                item = {
                    "file": str(file_path),
                    "archive_path": str(archive_path),
                    "original_rows": result.original_rows,
                    "crm_ready_rows": len(result.crm_ready_rows),
                    "rejected_rows": len(result.rejected_rows),
                    "duplicate_rows": len(result.duplicate_rows),
                }
                processed.append(item)
                self.log_event(
                    job.job_id, "file_processed", "success", f"Processed {file_path.name}", item
                )
            except Exception as error:
                error_path = self._move_file(file_path, Path(job.error_folder))
                item = {"file": str(file_path), "error_path": str(error_path), "error": str(error)}
                failed.append(item)
                self.log_event(
                    job.job_id, "file_failed", "failed", f"Failed {file_path.name}: {error}", item
                )

        finished_at = self._now()
        job.last_run_at = finished_at.isoformat()
        job.updated_at = finished_at.isoformat()
        if job.enabled and job.cadence != "manual":
            job.next_run_at = self.calculate_next_run(job, finished_at).isoformat()
        self.save_jobs(jobs)

        summary = {
            "job_id": job.job_id,
            "job_name": job.name,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "files_found": len(files),
            "processed_count": len(processed),
            "failed_count": len(failed),
            "processed": processed,
            "failed": failed,
            "next_run_at": job.next_run_at,
        }
        self.log_event(
            job.job_id,
            "job_run_finished",
            "success" if not failed else "partial_failure",
            "Scheduled job finished",
            summary,
        )

        notification = EmailNotifier(self.config).send_job_summary(summary)
        summary["notification"] = {
            "enabled": notification.enabled,
            "dry_run": notification.dry_run,
            "success": notification.success,
            "message": notification.message,
            "error": notification.error,
            "preview_file": notification.preview_file,
            "event_file": notification.event_file,
        }
        self.log_event(
            job.job_id,
            "notification",
            "success" if notification.success else "failed",
            notification.message,
            summary["notification"],
        )
        return summary

    def _move_file(self, file_path: Path, destination_folder: Path) -> Path:
        destination_folder.mkdir(parents=True, exist_ok=True)
        destination = destination_folder / file_path.name
        if destination.exists():
            timestamp = self._now().strftime("%Y%m%d_%H%M%S")
            destination = destination_folder / f"{file_path.stem}_{timestamp}{file_path.suffix}"
        shutil.move(str(file_path), str(destination))
        return destination

    def log_event(
        self, job_id: str, event_type: str, status: str, message: str, details: dict[str, Any]
    ) -> None:
        event = {
            "timestamp": self._now().isoformat(),
            "job_id": job_id,
            "event_type": event_type,
            "status": status,
            "message": message,
            "details": details,
        }
        with self.events_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, default=str) + "\n")

    def read_events(self, limit: int = 500) -> list[dict[str, Any]]:
        if not self.events_file.exists():
            return []
        rows = [
            json.loads(line)
            for line in self.events_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return rows[-limit:]
