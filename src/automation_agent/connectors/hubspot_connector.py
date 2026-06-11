from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from dotenv import load_dotenv

from automation_agent.core.audit_logger import AuditLogger


@dataclass
class HubSpotSyncResult:
    """Result object returned by the HubSpot connector."""

    attempted_rows: int
    operation: str
    dry_run: bool
    batches: int
    success: bool
    messages: list[str] = field(default_factory=list)
    payload_preview: dict[str, Any] | None = None
    sync_plan: dict[str, Any] | None = None
    response_data: list[dict[str, Any]] = field(default_factory=list)


class HubSpotConnector:
    """
    Safe HubSpot CRM contacts connector.

    Version 5 adds a safer planning layer:
    - optionally checks HubSpot for existing contacts by email
    - separates rows into create, update, and unknown/upsert groups
    - saves a human-readable sync plan before any real API call

    Real API writes are still disabled unless enabled=True and dry_run=False.
    """

    BASE_URL = "https://api.hubapi.com"

    DEFAULT_PROPERTY_MAPPING = {
        "email": "email",
        "first_name": "firstname",
        "last_name": "lastname",
        "phone": "phone",
        "company": "company",
        "city": "city",
        "country": "country",
    }

    def __init__(self, config: dict | None = None) -> None:
        load_dotenv()
        self.config = config or {}
        hubspot_config = self.config.get("integrations", {}).get("hubspot", {})
        self.enabled = bool(hubspot_config.get("enabled", False))
        self.dry_run = bool(hubspot_config.get("dry_run", True))
        self.operation = hubspot_config.get("operation", "plan").lower().strip()
        self.batch_size = int(hubspot_config.get("batch_size", 100))
        self.id_property = hubspot_config.get("id_property", "email")
        self.check_existing_before_sync = bool(
            hubspot_config.get("check_existing_before_sync", True)
        )
        self.payload_preview_file = Path(
            hubspot_config.get("payload_preview_file", "data/output/hubspot_payload_preview.json")
        )
        self.sync_plan_file = Path(
            hubspot_config.get("sync_plan_file", "data/output/hubspot_sync_plan.json")
        )
        self.property_mapping = (
            hubspot_config.get("property_mapping") or self.DEFAULT_PROPERTY_MAPPING
        )
        self.token = os.getenv("HUBSPOT_PRIVATE_APP_TOKEN", "").strip()
        self.audit = AuditLogger(self.config.get("output", {}).get("folder", "data/output"))

        if self.operation not in {"plan", "create", "update", "upsert"}:
            raise ValueError(
                "HubSpot operation must be one of: 'plan', 'create', 'update', 'upsert'."
            )

        if self.batch_size <= 0:
            raise ValueError("HubSpot batch_size must be greater than 0.")

    def build_properties(self, row: pd.Series, columns: list[str]) -> dict[str, Any]:
        """Map internal CRM-ready columns to HubSpot contact properties."""
        properties: dict[str, Any] = {}
        for source_column, hubspot_property in self.property_mapping.items():
            if source_column not in columns:
                continue
            value = row.get(source_column)
            if pd.isna(value) or str(value).strip() == "":
                continue
            properties[hubspot_property] = str(value).strip()
        return properties

    def build_payload(
        self, df: pd.DataFrame, operation: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Convert CRM-ready rows into a HubSpot batch API payload."""
        selected_operation = (operation or self.operation).lower().strip()
        inputs: list[dict[str, Any]] = []
        columns = list(df.columns)

        for _, row in df.iterrows():
            properties = self.build_properties(row, columns)
            email = properties.get("email")
            if not email:
                continue

            if selected_operation == "upsert":
                inputs.append(
                    {
                        "idProperty": self.id_property,
                        "id": email,
                        "properties": properties,
                    }
                )
            elif selected_operation == "create":
                inputs.append({"properties": properties})
            elif selected_operation == "update":
                # For direct update, HubSpot normally needs the record ID.
                # build_sync_plan() creates update payloads with the discovered HubSpot ID.
                hubspot_id = row.get("hubspot_id")
                if pd.isna(hubspot_id) or str(hubspot_id).strip() == "":
                    continue
                inputs.append({"id": str(hubspot_id).strip(), "properties": properties})
            else:
                inputs.append({"properties": properties})

        return {"inputs": inputs}

    def build_sync_plan(self, df: pd.DataFrame) -> dict[str, Any]:
        """
        Build a safe plan that separates contacts into create/update/upsert groups.

        When the HubSpot token is missing or the connector is disabled/dry-run, the
        plan still works locally but cannot know which contacts already exist.
        """
        payload_upsert = self.build_payload(df, operation="upsert")
        emails = [item["id"] for item in payload_upsert["inputs"] if item.get("id")]

        existing_by_email: dict[str, dict[str, Any]] = {}
        lookup_performed = False
        lookup_message = (
            "Lookup not performed because HubSpot is disabled, dry-run is on, or token is missing."
        )

        if self.check_existing_before_sync and self.enabled and self.token:
            existing_by_email = self.fetch_existing_contacts_by_email(emails)
            lookup_performed = True
            lookup_message = (
                f"Checked HubSpot and found {len(existing_by_email)} existing contacts."
            )

        create_inputs: list[dict[str, Any]] = []
        update_inputs: list[dict[str, Any]] = []
        unknown_upsert_inputs: list[dict[str, Any]] = []

        for item in payload_upsert["inputs"]:
            email = item.get("id")
            properties = item.get("properties", {})
            existing = existing_by_email.get(str(email).lower()) if lookup_performed else None

            if lookup_performed:
                if existing:
                    update_inputs.append({"id": existing["id"], "properties": properties})
                else:
                    create_inputs.append({"properties": properties})
            else:
                unknown_upsert_inputs.append(item)

        plan = {
            "summary": {
                "total_crm_ready_rows": int(len(df)),
                "valid_hubspot_inputs": len(payload_upsert["inputs"]),
                "lookup_performed": lookup_performed,
                "lookup_message": lookup_message,
                "existing_contacts_found": len(existing_by_email),
                "contacts_to_create": len(create_inputs),
                "contacts_to_update": len(update_inputs),
                "contacts_with_unknown_status": len(unknown_upsert_inputs),
                "dry_run": self.dry_run,
                "enabled": self.enabled,
            },
            "create_payload": {"inputs": create_inputs},
            "update_payload": {"inputs": update_inputs},
            "upsert_payload_for_unknown_status": {"inputs": unknown_upsert_inputs},
        }
        return plan

    def fetch_existing_contacts_by_email(self, emails: list[str]) -> dict[str, dict[str, Any]]:
        """Read existing HubSpot contacts by email using the batch read endpoint."""
        if not emails:
            return {}
        if not self.token:
            raise RuntimeError("Missing HUBSPOT_PRIVATE_APP_TOKEN for HubSpot lookup.")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        properties = sorted(set(self.property_mapping.values()))
        endpoint = f"{self.BASE_URL}/crm/v3/objects/contacts/batch/read"
        existing: dict[str, dict[str, Any]] = {}

        unique_emails = sorted({email.lower().strip() for email in emails if email})
        for batch in self._chunk([{"id": email} for email in unique_emails], self.batch_size):
            body = {
                "idProperty": "email",
                "properties": properties,
                "inputs": batch,
            }
            response = requests.post(endpoint, headers=headers, json=body, timeout=30)
            if response.status_code >= 400:
                # Some portals may return multi-status details for partial misses; keep error readable.
                raise RuntimeError(
                    f"HubSpot lookup failed with status {response.status_code}: {response.text[:500]}"
                )
            data = response.json()
            for contact in data.get("results", []):
                email = contact.get("properties", {}).get("email")
                if email:
                    existing[email.lower().strip()] = contact
        return existing

    def save_payload_preview(self, payload: dict[str, Any]) -> Path:
        """Save the HubSpot payload preview for human review."""
        self.payload_preview_file.parent.mkdir(parents=True, exist_ok=True)
        self.payload_preview_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self.payload_preview_file

    def save_sync_plan(self, plan: dict[str, Any]) -> Path:
        """Save the HubSpot sync plan for human review."""
        self.sync_plan_file.parent.mkdir(parents=True, exist_ok=True)
        self.sync_plan_file.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self.sync_plan_file

    def sync_contacts(self, df: pd.DataFrame) -> HubSpotSyncResult:
        """Prepare or send contacts to HubSpot."""
        sync_plan = self.build_sync_plan(df)
        plan_path = self.save_sync_plan(sync_plan)

        # Keep the old preview file too, because it is useful for human review and dashboard download.
        payload = self.build_payload(df, operation="upsert")
        payload_path = self.save_payload_preview(payload)

        total_inputs = len(payload["inputs"])
        batches = list(self._chunk(payload["inputs"], self.batch_size))

        self.audit.log_many_planned(
            system="hubspot",
            action="upsert_contact",
            payloads=payload.get("inputs", []),
            record_key_field="id",
        )

        result = HubSpotSyncResult(
            attempted_rows=total_inputs,
            operation=self.operation,
            dry_run=self.dry_run,
            batches=len(batches),
            success=True,
            payload_preview=payload,
            sync_plan=sync_plan,
        )

        if not self.enabled:
            self.audit.log(
                system="hubspot",
                action="sync_contacts",
                status="skipped",
                message="HubSpot integration is disabled.",
            )
            result.messages.append(
                f"HubSpot integration is disabled. Sync plan saved to {plan_path}. Payload preview saved to {payload_path}."
            )
            return result

        if self.dry_run:
            self.audit.log(
                system="hubspot",
                action="sync_contacts",
                status="skipped",
                message="HubSpot dry-run mode is enabled. No records were sent.",
            )
            result.messages.append(
                f"HubSpot dry-run mode is enabled. Sync plan saved to {plan_path}. Payload preview saved to {payload_path}."
            )
            return result

        if not self.token:
            result.success = False
            self.audit.log(
                system="hubspot",
                action="sync_contacts",
                status="failed",
                error="Missing HUBSPOT_PRIVATE_APP_TOKEN.",
            )
            result.messages.append(
                "Missing HUBSPOT_PRIVATE_APP_TOKEN. Add it to your .env file before real sync."
            )
            return result

        if self.operation == "plan":
            self.audit.log(
                system="hubspot",
                action="sync_contacts",
                status="skipped",
                message="Plan-only mode. No records were sent.",
            )
            result.messages.append(
                f"Plan-only mode. Sync plan saved to {plan_path}; no records were sent."
            )
            return result

        if self.operation == "create":
            operations = [("create", sync_plan["create_payload"])]
        elif self.operation == "update":
            operations = [("update", sync_plan["update_payload"])]
        else:
            # Upsert is the safest first real-write mode for contacts because it avoids duplicates by email.
            operations = [("upsert", payload)]

        for operation_name, operation_payload in operations:
            endpoint = self._endpoint(operation_name)
            operation_batches = list(self._chunk(operation_payload["inputs"], self.batch_size))
            for batch_number, batch in enumerate(operation_batches, start=1):
                batch_payload = {"inputs": batch}
                response = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json=batch_payload,
                    timeout=30,
                )
                try:
                    response_json = response.json()
                except ValueError:
                    response_json = {"text": response.text}

                result.response_data.append(
                    {
                        "operation": operation_name,
                        "batch": batch_number,
                        "status_code": response.status_code,
                        "response": response_json,
                    }
                )

                if response.status_code >= 400:
                    result.success = False
                    self.audit.log(
                        system="hubspot",
                        action=f"{operation_name}_contact_batch",
                        status="failed",
                        source_row=f"batch {batch_number}",
                        message=f"HubSpot batch failed with status {response.status_code}.",
                        error=json.dumps(response_json, ensure_ascii=False, default=str),
                        payload_preview=batch_payload,
                    )
                    result.messages.append(
                        f"HubSpot {operation_name} batch {batch_number} failed with status {response.status_code}."
                    )
                    return result

                self.audit.log(
                    system="hubspot",
                    action=f"{operation_name}_contact_batch",
                    status=(
                        "created"
                        if operation_name == "create"
                        else "updated" if operation_name == "update" else "upserted"
                    ),
                    source_row=f"batch {batch_number}",
                    message=f"HubSpot {operation_name} batch synced successfully.",
                    payload_preview=batch_payload,
                )
                result.messages.append(
                    f"HubSpot {operation_name} batch {batch_number} synced successfully."
                )

        return result

    def _endpoint(self, operation: str) -> str:
        if operation == "create":
            return f"{self.BASE_URL}/crm/v3/objects/contacts/batch/create"
        if operation == "update":
            return f"{self.BASE_URL}/crm/v3/objects/contacts/batch/update"
        return f"{self.BASE_URL}/crm/v3/objects/contacts/batch/upsert"

    @staticmethod
    def _chunk(items: list[Any], batch_size: int) -> Iterable[list[Any]]:
        for index in range(0, len(items), batch_size):
            yield items[index : index + batch_size]
