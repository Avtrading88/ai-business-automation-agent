from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class VersionedRun:
    run_id: str
    created_at: str
    source_name: str
    source_file: str
    run_folder: Path
    manifest_path: Path
    output_paths: dict[str, str]
    source_file_hash: str
    status: str = "created"


class FileVersionManager:
    """Create immutable run folders for every processed file and restore old outputs."""

    def __init__(self, config_or_output_folder: dict | str | Path):
        if isinstance(config_or_output_folder, dict):
            config = config_or_output_folder
            output_folder = Path(config.get("output", {}).get("folder", "data/output"))
            versioning_cfg = config.get("file_versioning", {})
        else:
            output_folder = Path(config_or_output_folder)
            versioning_cfg = {}

        self.output_folder = output_folder
        self.enabled = bool(versioning_cfg.get("enabled", True))
        self.runs_folder = Path(versioning_cfg.get("runs_folder", output_folder / "versioned_runs"))
        self.manifest_index_file = Path(
            versioning_cfg.get("manifest_index_file", output_folder / "file_version_index.jsonl")
        )
        self.latest_manifest_file = Path(
            versioning_cfg.get(
                "latest_run_manifest_file", output_folder / "latest_run_manifest.json"
            )
        )
        self.restore_log_file = Path(
            versioning_cfg.get("restore_log_file", output_folder / "rollback_events.jsonl")
        )

        if not self.runs_folder.is_absolute():
            self.runs_folder = Path(self.runs_folder)
        if not self.manifest_index_file.is_absolute():
            self.manifest_index_file = Path(self.manifest_index_file)
        if not self.latest_manifest_file.is_absolute():
            self.latest_manifest_file = Path(self.latest_manifest_file)
        if not self.restore_log_file.is_absolute():
            self.restore_log_file = Path(self.restore_log_file)

        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.runs_folder.mkdir(parents=True, exist_ok=True)
        self.manifest_index_file.parent.mkdir(parents=True, exist_ok=True)
        self.latest_manifest_file.parent.mkdir(parents=True, exist_ok=True)
        self.restore_log_file.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def make_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"run_{stamp}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def file_sha256(path: str | Path) -> str:
        path = Path(path)
        if not path.exists() or not path.is_file():
            return ""
        hasher = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def dataframe_hash(df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return hashlib.sha256(b"").hexdigest()
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        return hashlib.sha256(csv_bytes).hexdigest()

    def create_versioned_run(
        self,
        *,
        source_name: str,
        source_file: str | Path | None,
        output_paths: dict[str, Path],
        dataframes: dict[str, pd.DataFrame] | None = None,
        report_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> VersionedRun:
        """Copy current output files into an immutable run folder and write a manifest."""
        if not self.enabled:
            run_id = "versioning_disabled"
            return VersionedRun(
                run_id=run_id,
                created_at=self.now_iso(),
                source_name=source_name,
                source_file=str(source_file or ""),
                run_folder=self.runs_folder / run_id,
                manifest_path=self.latest_manifest_file,
                output_paths={k: str(v) for k, v in output_paths.items()},
                source_file_hash="",
                status="disabled",
            )

        run_id = self.make_run_id()
        run_folder = self.runs_folder / run_id
        files_folder = run_folder / "outputs"
        files_folder.mkdir(parents=True, exist_ok=True)

        copied_outputs: dict[str, str] = {}
        output_hashes: dict[str, str] = {}
        for key, path in output_paths.items():
            path = Path(path)
            if path.exists() and path.is_file():
                destination = files_folder / path.name
                shutil.copy2(path, destination)
                copied_outputs[key] = str(destination)
                output_hashes[key] = self.file_sha256(destination)
            else:
                copied_outputs[key] = ""
                output_hashes[key] = ""

        dataframe_hashes = {
            name: self.dataframe_hash(df) for name, df in (dataframes or {}).items()
        }
        row_counts = {name: int(len(df)) for name, df in (dataframes or {}).items()}

        source_file_hash = self.file_sha256(source_file) if source_file else ""
        manifest = {
            "run_id": run_id,
            "created_at": self.now_iso(),
            "status": "created",
            "source_name": source_name,
            "source_file": str(source_file or ""),
            "source_file_hash": source_file_hash,
            "run_folder": str(run_folder),
            "copied_outputs": copied_outputs,
            "output_hashes": output_hashes,
            "dataframe_hashes": dataframe_hashes,
            "row_counts": row_counts,
            "report_preview": report_text[:2000],
            "metadata": metadata or {},
        }

        manifest_path = run_folder / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.latest_manifest_file.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        with self.manifest_index_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(manifest, ensure_ascii=False) + "\n")

        return VersionedRun(
            run_id=run_id,
            created_at=manifest["created_at"],
            source_name=source_name,
            source_file=str(source_file or ""),
            run_folder=run_folder,
            manifest_path=manifest_path,
            output_paths=copied_outputs,
            source_file_hash=source_file_hash,
            status="created",
        )

    def list_runs(self, limit: int = 100) -> pd.DataFrame:
        rows = []
        if self.manifest_index_file.exists():
            for line in self.manifest_index_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    manifest = json.loads(line)
                    rows.append(
                        {
                            "run_id": manifest.get("run_id", ""),
                            "created_at": manifest.get("created_at", ""),
                            "source_name": manifest.get("source_name", ""),
                            "source_file": manifest.get("source_file", ""),
                            "crm_ready_rows": manifest.get("row_counts", {}).get(
                                "crm_ready_rows", 0
                            ),
                            "rejected_rows": manifest.get("row_counts", {}).get("rejected_rows", 0),
                            "duplicate_rows": manifest.get("row_counts", {}).get(
                                "duplicate_rows", 0
                            ),
                            "run_folder": manifest.get("run_folder", ""),
                        }
                    )
                except json.JSONDecodeError:
                    continue
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("created_at", ascending=False).head(limit)
        return df

    def get_manifest(self, run_id: str) -> dict[str, Any]:
        manifest_path = self.runs_folder / run_id / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No manifest found for run_id: {run_id}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def compare_runs(self, run_id_a: str, run_id_b: str) -> pd.DataFrame:
        a = self.get_manifest(run_id_a)
        b = self.get_manifest(run_id_b)
        rows = []
        for metric in ["crm_ready_rows", "rejected_rows", "duplicate_rows", "cleaned_rows"]:
            value_a = int(a.get("row_counts", {}).get(metric, 0) or 0)
            value_b = int(b.get("row_counts", {}).get(metric, 0) or 0)
            rows.append(
                {
                    "metric": metric,
                    "run_a": value_a,
                    "run_b": value_b,
                    "difference_b_minus_a": value_b - value_a,
                }
            )
        for output_key in sorted(set(a.get("output_hashes", {})) | set(b.get("output_hashes", {}))):
            hash_a = a.get("output_hashes", {}).get(output_key, "")
            hash_b = b.get("output_hashes", {}).get(output_key, "")
            rows.append(
                {
                    "metric": f"hash_changed:{output_key}",
                    "run_a": hash_a[:12],
                    "run_b": hash_b[:12],
                    "difference_b_minus_a": str(hash_a != hash_b),
                }
            )
        return pd.DataFrame(rows)

    def rollback_run(
        self, run_id: str, *, actor: str = "unknown", reason: str = ""
    ) -> dict[str, Any]:
        """Restore output files from a previous versioned run into the active output folder."""
        manifest = self.get_manifest(run_id)
        restored: dict[str, str] = {}
        for key, versioned_path in manifest.get("copied_outputs", {}).items():
            if not versioned_path:
                continue
            source = Path(versioned_path)
            if source.exists() and source.is_file():
                destination = self.output_folder / source.name
                shutil.copy2(source, destination)
                restored[key] = str(destination)

        event = {
            "event_id": uuid.uuid4().hex,
            "event_type": "rollback",
            "timestamp": self.now_iso(),
            "run_id": run_id,
            "actor": actor,
            "reason": reason,
            "restored_files": restored,
        }
        with self.restore_log_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read_rollback_events(self, limit: int = 200) -> pd.DataFrame:
        rows = []
        if self.restore_log_file.exists():
            for line in self.restore_log_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("timestamp", ascending=False).head(limit)
        return df
