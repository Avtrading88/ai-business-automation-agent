from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from automation_agent.core.database import DatabaseManager


@dataclass
class PermissionDecision:
    approved_by: str
    role: str
    scope: str
    system: str
    environment: str
    dry_run: bool
    allowed: bool
    required_permission: str
    message: str
    timestamp_utc: str


class RoleBasedApproval:
    """Small role/permission layer for approval and sync safety.

    This is intentionally config-driven and simple. It is not a full identity provider;
    it is a project-level guardrail before API sync actions are allowed.
    """

    DEFAULT_ROLES: dict[str, dict[str, Any]] = {
        "viewer": {
            "description": "Can view reports and output files only.",
            "permissions": {
                "view_outputs": True,
                "approve_exports": False,
                "approve_crm_sync": False,
                "approve_quickbooks_sandbox_sync": False,
                "approve_quickbooks_production_sync": False,
                "manage_settings": False,
            },
        },
        "reviewer": {
            "description": "Can review data and approve export-only flows.",
            "permissions": {
                "view_outputs": True,
                "approve_exports": True,
                "approve_crm_sync": False,
                "approve_quickbooks_sandbox_sync": False,
                "approve_quickbooks_production_sync": False,
                "manage_settings": False,
            },
        },
        "approver": {
            "description": "Can approve CRM sync and QuickBooks sandbox sync.",
            "permissions": {
                "view_outputs": True,
                "approve_exports": True,
                "approve_crm_sync": True,
                "approve_quickbooks_sandbox_sync": True,
                "approve_quickbooks_production_sync": False,
                "manage_settings": False,
            },
        },
        "admin": {
            "description": "Can approve sandbox and production flows and manage settings.",
            "permissions": {
                "view_outputs": True,
                "approve_exports": True,
                "approve_crm_sync": True,
                "approve_quickbooks_sandbox_sync": True,
                "approve_quickbooks_production_sync": True,
                "manage_settings": True,
            },
        },
    }

    def __init__(self, config: dict, output_folder: str | Path = "data/output") -> None:
        self.config = config or {}
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        approval_cfg = self.config.get("approval", {})
        role_cfg = approval_cfg.get("role_based", {})
        self.enabled = bool(role_cfg.get("enabled", True))
        self.default_role = str(role_cfg.get("default_role", "reviewer")).lower().strip()
        self.roles = role_cfg.get("roles") or self.DEFAULT_ROLES
        self.decision_file = self.output_folder / role_cfg.get(
            "permission_decision_file", "role_permission_decisions.jsonl"
        )
        self.matrix_file = self.output_folder / role_cfg.get(
            "permission_matrix_file", "role_permission_matrix.csv"
        )
        self.db = DatabaseManager(self.output_folder / "automation_agent.db")
        self.export_permission_matrix()

    def available_roles(self) -> list[str]:
        return list(self.roles.keys())

    def permissions_for_role(self, role: str) -> dict[str, Any]:
        normalized = self.normalize_role(role)
        return self.roles.get(normalized, {}).get("permissions", {})

    def normalize_role(self, role: str | None) -> str:
        normalized = (role or self.default_role or "reviewer").strip().lower()
        if normalized not in self.roles:
            return self.default_role if self.default_role in self.roles else "viewer"
        return normalized

    def required_permission_for_scope(
        self, scope: str, system: str = "", environment: str = ""
    ) -> str:
        scope_text = (scope or "").lower()
        system_text = (system or "").lower()
        env_text = (environment or "").lower()

        if "production" in scope_text or env_text == "production":
            if "quickbooks" in scope_text or system_text == "quickbooks":
                return "approve_quickbooks_production_sync"
        if "quickbooks" in scope_text or system_text == "quickbooks":
            if "sync" in scope_text:
                return "approve_quickbooks_sandbox_sync"
            return "approve_exports"
        if "hubspot" in scope_text or "crm" in scope_text or system_text in {"crm", "hubspot"}:
            if "sync" in scope_text:
                return "approve_crm_sync"
            return "approve_exports"
        if "export" in scope_text or "placeholder" in scope_text:
            return "approve_exports"
        return "view_outputs"

    def evaluate(
        self,
        *,
        approved_by: str,
        role: str | None,
        scope: str,
        system: str = "",
        environment: str = "",
        dry_run: bool = True,
    ) -> PermissionDecision:
        normalized_role = self.normalize_role(role)
        required_permission = self.required_permission_for_scope(
            scope, system=system, environment=environment
        )
        permissions = self.permissions_for_role(normalized_role)
        allowed = True if not self.enabled else bool(permissions.get(required_permission, False))

        if allowed:
            message = f"Role '{normalized_role}' is allowed for scope '{scope}' using permission '{required_permission}'."
        else:
            message = f"Role '{normalized_role}' is NOT allowed for scope '{scope}'. Required permission: '{required_permission}'."

        decision = PermissionDecision(
            approved_by=(approved_by or "unknown").strip(),
            role=normalized_role,
            scope=scope,
            system=system or "general",
            environment=environment or "not_set",
            dry_run=bool(dry_run),
            allowed=allowed,
            required_permission=required_permission,
            message=message,
            timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._append_decision(decision)
        return decision

    def export_permission_matrix(self) -> Path:
        rows: list[dict[str, Any]] = []
        permission_names = sorted(
            {
                permission
                for role_data in self.roles.values()
                for permission in role_data.get("permissions", {}).keys()
            }
        )
        for role_name, role_data in self.roles.items():
            row = {
                "role": role_name,
                "description": role_data.get("description", ""),
            }
            permissions = role_data.get("permissions", {})
            for permission in permission_names:
                row[permission] = bool(permissions.get(permission, False))
            rows.append(row)
        pd.DataFrame(rows).to_csv(self.matrix_file, index=False)
        return self.matrix_file

    def read_permission_matrix(self) -> pd.DataFrame:
        if not self.matrix_file.exists():
            self.export_permission_matrix()
        return pd.read_csv(self.matrix_file)

    def _append_decision(self, decision: PermissionDecision) -> None:
        decision_dict = asdict(decision)
        with self.decision_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(decision_dict, ensure_ascii=False) + "\n")
        self.db.insert_role_decision(decision_dict)
