from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ConfigChangeResult:
    success: bool
    message: str
    backup_path: str = ""


class ConfigManager:
    """Small safe helper for editing config.yaml from the Streamlit admin panel."""

    def __init__(
        self, config_path: str | Path = "config.yaml", output_folder: str | Path = "data/output"
    ) -> None:
        self.config_path = Path(config_path)
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.backup_folder = self.output_folder / "config_backups"
        self.backup_folder.mkdir(parents=True, exist_ok=True)
        self.event_file = self.output_folder / "settings_change_events.jsonl"

    def load(self) -> dict[str, Any]:
        with self.config_path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def save(
        self, config: dict[str, Any], actor: str = "unknown", reason: str = "dashboard update"
    ) -> ConfigChangeResult:
        try:
            backup_path = self.backup(actor=actor)
            with self.config_path.open("w", encoding="utf-8") as file:
                yaml.safe_dump(config, file, sort_keys=False, allow_unicode=True)
            self.log_event(
                actor=actor,
                action="save_config",
                status="success",
                message=reason,
                backup_path=backup_path,
            )
            return ConfigChangeResult(
                True,
                "Config saved successfully. Restart or rerun Streamlit if some settings do not refresh immediately.",
                backup_path,
            )
        except Exception as error:
            self.log_event(actor=actor, action="save_config", status="failed", message=str(error))
            return ConfigChangeResult(False, f"Could not save config: {error}")

    def backup(self, actor: str = "unknown") -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_actor = "".join(ch for ch in actor if ch.isalnum() or ch in ("-", "_")) or "unknown"
        backup_path = self.backup_folder / f"config_{timestamp}_{safe_actor}.yaml"
        if self.config_path.exists():
            shutil.copy2(self.config_path, backup_path)
        return str(backup_path)

    def log_event(
        self, actor: str, action: str, status: str, message: str = "", backup_path: str = ""
    ) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "status": status,
            "message": message,
            "backup_path": backup_path,
        }
        with self.event_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        if not self.event_file.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.event_file.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events

    def available_backups(self) -> list[Path]:
        return sorted(self.backup_folder.glob("config_*.yaml"), reverse=True)
