from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


class DatabaseManager:
    """Small SQLite database layer for the local automation MVP.

    V18 keeps the existing CSV/JSON files for easy downloads, but every new
    audit, approval, role decision, login, and user-management event can also be
    stored in one local SQLite database.
    """

    def __init__(self, db_path: str | Path = "data/output/automation_agent.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @classmethod
    def from_config(
        cls, config: dict[str, Any] | None = None, output_folder: str | Path = "data/output"
    ) -> "DatabaseManager":
        config = config or {}
        db_cfg = config.get("database", {}) if isinstance(config, dict) else {}
        output_folder = Path(output_folder)
        db_path = db_cfg.get("path") or output_folder / "automation_agent.db"
        return cls(db_path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    email TEXT,
                    role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    password_hash TEXT,
                    created_at_utc TEXT,
                    updated_at_utc TEXT,
                    created_by TEXT,
                    updated_by TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_login_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    username TEXT,
                    role TEXT,
                    success INTEGER NOT NULL,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_user_management_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    actor TEXT,
                    action TEXT,
                    target_username TEXT,
                    success INTEGER NOT NULL,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    system TEXT,
                    action TEXT,
                    status TEXT,
                    source_row TEXT,
                    external_id TEXT,
                    record_key TEXT,
                    message TEXT,
                    error TEXT,
                    payload_preview TEXT
                );

                CREATE TABLE IF NOT EXISTS approval_records (
                    approval_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    approved_by TEXT,
                    approval_status TEXT,
                    approval_scope TEXT,
                    approver_role TEXT,
                    permission_result TEXT,
                    source_name TEXT,
                    source_hash TEXT,
                    output_file TEXT,
                    output_hash TEXT,
                    original_rows INTEGER,
                    crm_ready_rows INTEGER,
                    rejected_rows INTEGER,
                    duplicate_rows INTEGER,
                    project_name TEXT,
                    project_version TEXT,
                    note TEXT
                );

                CREATE TABLE IF NOT EXISTS role_permission_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    approved_by TEXT,
                    role TEXT,
                    scope TEXT,
                    system TEXT,
                    environment TEXT,
                    dry_run INTEGER NOT NULL,
                    allowed INTEGER NOT NULL,
                    required_permission TEXT,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS processed_files (
                    run_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    source_name TEXT,
                    original_rows INTEGER,
                    crm_ready_rows INTEGER,
                    rejected_rows INTEGER,
                    duplicate_rows INTEGER,
                    output_folder TEXT,
                    report_text TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit_events(timestamp_utc);
                CREATE INDEX IF NOT EXISTS idx_audit_events_system_status ON audit_events(system, status);
                CREATE INDEX IF NOT EXISTS idx_approvals_timestamp ON approval_records(timestamp_utc);
                CREATE INDEX IF NOT EXISTS idx_role_decisions_timestamp ON role_permission_decisions(timestamp_utc);
                CREATE INDEX IF NOT EXISTS idx_login_events_timestamp ON auth_login_events(timestamp_utc);
                """)

    def upsert_user(self, user: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    username, display_name, email, role, active, password_hash,
                    created_at_utc, updated_at_utc, created_by, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    display_name=excluded.display_name,
                    email=excluded.email,
                    role=excluded.role,
                    active=excluded.active,
                    password_hash=excluded.password_hash,
                    updated_at_utc=excluded.updated_at_utc,
                    updated_by=excluded.updated_by
                """,
                (
                    str(user.get("username", "")),
                    str(user.get("display_name", user.get("username", ""))),
                    str(user.get("email", "")),
                    str(user.get("role", "viewer")),
                    1 if user.get("active", True) else 0,
                    str(user.get("password_hash", "")),
                    str(user.get("created_at_utc", "")),
                    str(user.get("updated_at_utc", "")),
                    str(user.get("created_by", "")),
                    str(user.get("updated_by", "")),
                ),
            )

    def replace_users(self, users: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM users")
        for user in users:
            self.upsert_user(user)

    def insert_login_event(self, event: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_login_events(timestamp_utc, username, role, success, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.get("timestamp_utc") or self.now(),
                    event.get("username", ""),
                    event.get("role", ""),
                    1 if event.get("success") else 0,
                    event.get("message", ""),
                ),
            )

    def insert_user_management_event(self, event: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_user_management_events(timestamp_utc, actor, action, target_username, success, message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("timestamp_utc") or self.now(),
                    event.get("actor", ""),
                    event.get("action", ""),
                    event.get("target_username", ""),
                    1 if event.get("success") else 0,
                    event.get("message", ""),
                ),
            )

    def insert_audit_event(self, event: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events(
                    timestamp_utc, system, action, status, source_row, external_id,
                    record_key, message, error, payload_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(
                    event.get(field, "")
                    for field in [
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
                ),
            )

    def insert_approval_record(self, record: dict[str, Any]) -> None:
        fields = [
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
        with self.connect() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO approval_records({', '.join(fields)})
                VALUES ({', '.join(['?'] * len(fields))})
                """,
                tuple(record.get(field, "") for field in fields),
            )

    def insert_role_decision(self, decision: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO role_permission_decisions(
                    timestamp_utc, approved_by, role, scope, system, environment,
                    dry_run, allowed, required_permission, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.get("timestamp_utc") or self.now(),
                    decision.get("approved_by", ""),
                    decision.get("role", ""),
                    decision.get("scope", ""),
                    decision.get("system", ""),
                    decision.get("environment", ""),
                    1 if decision.get("dry_run") else 0,
                    1 if decision.get("allowed") else 0,
                    decision.get("required_permission", ""),
                    decision.get("message", ""),
                ),
            )

    def insert_processed_file(
        self,
        *,
        source_name: str,
        original_rows: int,
        crm_ready_rows: int,
        rejected_rows: int,
        duplicate_rows: int,
        output_folder: str,
        report_text: str,
    ) -> str:
        run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_files(run_id, timestamp_utc, source_name, original_rows, crm_ready_rows, rejected_rows, duplicate_rows, output_folder, report_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    self.now(),
                    source_name,
                    int(original_rows),
                    int(crm_ready_rows),
                    int(rejected_rows),
                    int(duplicate_rows),
                    output_folder,
                    report_text,
                ),
            )
        return run_id

    def table_counts(self) -> dict[str, int]:
        tables = [
            "users",
            "auth_login_events",
            "auth_user_management_events",
            "audit_events",
            "approval_records",
            "role_permission_decisions",
            "processed_files",
        ]
        with self.connect() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }

    def read_table(self, table_name: str, limit: int = 500) -> pd.DataFrame:
        allowed = {
            "users",
            "auth_login_events",
            "auth_user_management_events",
            "audit_events",
            "approval_records",
            "role_permission_decisions",
            "processed_files",
        }
        if table_name not in allowed:
            raise ValueError(f"Unsupported table: {table_name}")
        order = "timestamp_utc" if table_name != "users" else "username"
        direction = "DESC" if table_name != "users" else "ASC"
        with self.connect() as conn:
            return pd.read_sql_query(
                f"SELECT * FROM {table_name} ORDER BY {order} {direction} LIMIT ?",
                conn,
                params=(int(limit),),
            )

    def export_table_to_csv(self, table_name: str, output_path: str | Path) -> Path:
        df = self.read_table(table_name, limit=100000)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        return output_path

    def import_jsonl(self, path: str | Path, table_kind: str) -> int:
        path = Path(path)
        if not path.exists():
            return 0
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if table_kind == "login":
                self.insert_login_event(row)
            elif table_kind == "user_management":
                self.insert_user_management_event(row)
            elif table_kind == "role_decision":
                self.insert_role_decision(row)
            elif table_kind == "audit":
                self.insert_audit_event(row)
            elif table_kind == "approval":
                self.insert_approval_record(row)
            else:
                raise ValueError(f"Unsupported import type: {table_kind}")
            count += 1
        return count

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
