from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass
class BackupResult:
    backup_id: str
    backup_file: str
    manifest_file: str
    included_files: int
    total_size_bytes: int


class SystemBackupManager:
    """Create, list, export, and restore full local system-state backups.

    Backups are ZIP files containing selected state files such as config.yaml,
    SQLite DB, user store, approvals, audit logs, settings history, scheduled jobs,
    version history, and optional output artifacts. Runtime secrets like .env are
    deliberately excluded by default.
    """

    DEFAULT_EXCLUDES = {
        ".venv",
        "__pycache__",
        ".git",
        ".env",
        "logs",
    }

    def __init__(self, config: dict, project_root: str | Path | None = None):
        self.config = config
        self.project_root = Path(project_root or Path.cwd()).resolve()
        backup_cfg = config.get("system_backup", {})
        self.backups_folder = self._resolve(
            backup_cfg.get("backups_folder", "data/output/system_backups")
        )
        self.restore_folder = self._resolve(
            backup_cfg.get("restore_folder", "data/output/system_restore_staging")
        )
        self.index_file = self._resolve(
            backup_cfg.get("index_file", "data/output/system_backup_index.jsonl")
        )
        self.restore_events_file = self._resolve(
            backup_cfg.get("restore_events_file", "data/output/system_restore_events.jsonl")
        )
        self.include_outputs = bool(backup_cfg.get("include_output_files", True))
        self.include_versioned_runs = bool(backup_cfg.get("include_versioned_runs", True))
        self.include_database = bool(backup_cfg.get("include_database", True))
        self.include_env = bool(backup_cfg.get("include_env", False))
        self.backups_folder.mkdir(parents=True, exist_ok=True)
        self.index_file.parent.mkdir(parents=True, exist_ok=True)

    def _resolve(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    def _now(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.project_root).as_posix()

    def _append_jsonl(self, path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _safe_copy_sqlite(self, source_db: Path, dest_db: Path) -> bool:
        if not source_db.exists():
            return False
        dest_db.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(source_db))
            backup_conn = sqlite3.connect(str(dest_db))
            with backup_conn:
                conn.backup(backup_conn)
            backup_conn.close()
            conn.close()
        except Exception:
            shutil.copy2(source_db, dest_db)
        return True

    def _configured_state_files(self) -> list[Path]:
        output_folder = self._resolve(self.config.get("output", {}).get("folder", "data/output"))
        paths: list[Path] = [
            self.project_root / "config.yaml",
            self.project_root / ".gitignore",
            self.project_root / "README.md",
        ]

        # Configured individual files.
        for section, keys in {
            "auth": ["user_store_file", "login_events_file", "user_management_events_file"],
            "approval": ["history_csv_file", "history_jsonl_file", "latest_manifest_file"],
            "scheduler": ["jobs_file", "events_file"],
            "file_versioning": [
                "manifest_index_file",
                "latest_run_manifest_file",
                "restore_log_file",
            ],
        }.items():
            cfg = self.config.get(section, {})
            for key in keys:
                value = cfg.get(key)
                if not value:
                    continue
                p = Path(value)
                paths.append(
                    self._resolve(p) if (p.is_absolute() or len(p.parts) > 1) else output_folder / p
                )

        # Integration and notification outputs that matter for state review.
        for value in self.config.get("integrations", {}).get("quickbooks", {}).values():
            if isinstance(value, str) and value.endswith(
                (".json", ".csv", ".xlsx", ".jsonl", ".txt")
            ):
                p = Path(value)
                paths.append(self._resolve(p) if len(p.parts) > 1 else output_folder / p)
        hubspot = self.config.get("integrations", {}).get("hubspot", {})
        for key in ["payload_preview_file", "sync_plan_file"]:
            if hubspot.get(key):
                paths.append(self._resolve(hubspot[key]))

        email = self.config.get("notifications", {}).get("email", {})
        for key in ["preview_file", "event_file"]:
            if email.get(key):
                paths.append(self._resolve(email[key]))

        database_path = self.config.get("database", {}).get("path")
        if self.include_database and database_path:
            paths.append(self._resolve(database_path))

        if self.include_env:
            paths.append(self.project_root / ".env")

        # Common generated files.
        if output_folder.exists():
            for pattern in ["*.csv", "*.json", "*.jsonl", "*.txt", "*.xlsx"]:
                paths.extend(output_folder.glob(pattern))

        return sorted({p.resolve() for p in paths if p.exists() and p.is_file()})

    def _configured_state_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if self.include_versioned_runs:
            runs_folder = self.config.get("file_versioning", {}).get("runs_folder")
            if runs_folder:
                dirs.append(self._resolve(runs_folder))
        if self.include_outputs:
            for rel in ["data/scheduled_input", "data/scheduled_archive", "data/scheduled_errors"]:
                p = self.project_root / rel
                if p.exists():
                    dirs.append(p)
        config_backups = self.project_root / "data/output/config_backups"
        if config_backups.exists():
            dirs.append(config_backups)
        return sorted({d.resolve() for d in dirs if d.exists() and d.is_dir()})

    def _iter_backup_files(self) -> Iterable[Path]:
        for path in self._configured_state_files():
            yield path
        for folder in self._configured_state_dirs():
            for path in folder.rglob("*"):
                if path.is_file():
                    yield path

    def _is_allowed(self, path: Path) -> bool:
        rel_parts = set(self._rel(path).split("/"))
        if not self.include_env and path.name == ".env":
            return False
        return not bool(rel_parts & self.DEFAULT_EXCLUDES)

    def create_backup(self, *, created_by: str = "system", note: str = "") -> BackupResult:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"backup_{timestamp}"
        backup_file = self.backups_folder / f"{backup_id}.zip"
        manifest_file = self.backups_folder / f"{backup_id}_manifest.json"

        files = []
        for file_path in sorted({p.resolve() for p in self._iter_backup_files()}):
            if file_path.exists() and file_path.is_file() and self._is_allowed(file_path):
                try:
                    rel = self._rel(file_path)
                except ValueError:
                    continue
                files.append((file_path, rel))

        manifest = {
            "backup_id": backup_id,
            "created_at_utc": self._now(),
            "created_by": created_by,
            "note": note,
            "project_name": self.config.get("project", {}).get("name", "Business Automation Agent"),
            "project_version": self.config.get("project", {}).get("version", ""),
            "include_env": self.include_env,
            "included_files": [],
        }

        staging_dir = self.backups_folder / f".{backup_id}_staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            staged_files = []
            for source, rel in files:
                dest = staging_dir / rel
                if source.suffix == ".db" and self.include_database:
                    copied = self._safe_copy_sqlite(source, dest)
                    if not copied:
                        continue
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
                size = dest.stat().st_size
                staged_files.append((dest, rel, size))
                manifest["included_files"].append({"path": rel, "size_bytes": size})

            manifest_path_in_zip = staging_dir / "backup_manifest.json"
            manifest_path_in_zip.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            staged_files.append(
                (manifest_path_in_zip, "backup_manifest.json", manifest_path_in_zip.stat().st_size)
            )

            with zipfile.ZipFile(backup_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for staged, rel, _size in staged_files:
                    zf.write(staged, rel)

            total_size = backup_file.stat().st_size
            manifest["backup_file"] = self._rel(backup_file)
            manifest["manifest_file"] = self._rel(manifest_file)
            manifest["backup_size_bytes"] = total_size
            manifest["included_file_count"] = len(manifest["included_files"])
            manifest_file.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._append_jsonl(self.index_file, manifest)
            return BackupResult(
                backup_id,
                str(backup_file),
                str(manifest_file),
                len(manifest["included_files"]),
                total_size,
            )
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

    def list_backups(self) -> list[dict]:
        backups: dict[str, dict] = {}
        if self.index_file.exists():
            for line in self.index_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    backups[record.get("backup_id", "")] = record
                except json.JSONDecodeError:
                    continue
        for manifest in self.backups_folder.glob("backup_*_manifest.json"):
            try:
                record = json.loads(manifest.read_text(encoding="utf-8"))
                backups[record.get("backup_id", manifest.stem)] = record
            except Exception:
                continue
        return sorted(backups.values(), key=lambda r: r.get("created_at_utc", ""), reverse=True)

    def restore_backup(
        self,
        backup_id_or_file: str,
        *,
        restored_by: str = "system",
        reason: str = "",
        dry_run: bool = True,
    ) -> dict:
        candidate = Path(backup_id_or_file)
        if candidate.exists():
            backup_file = candidate.resolve()
        else:
            backup_file = self.backups_folder / f"{backup_id_or_file}.zip"
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup not found: {backup_id_or_file}")

        restore_id = f"restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        staging = self.restore_folder / restore_id
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        restored_files = []
        try:
            with zipfile.ZipFile(backup_file, "r") as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                zf.extractall(staging)

            for name in names:
                if name == "backup_manifest.json":
                    continue
                source = staging / name
                destination = self.project_root / name
                if dry_run:
                    action = "would_restore"
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    action = "restored"
                restored_files.append(
                    {"path": name, "action": action, "size_bytes": source.stat().st_size}
                )

            event = {
                "restore_id": restore_id,
                "backup_file": str(backup_file),
                "restored_at_utc": self._now(),
                "restored_by": restored_by,
                "reason": reason,
                "dry_run": dry_run,
                "file_count": len(restored_files),
                "files": restored_files,
            }
            self._append_jsonl(self.restore_events_file, event)
            return event
        finally:
            if staging.exists() and not dry_run:
                shutil.rmtree(staging)
