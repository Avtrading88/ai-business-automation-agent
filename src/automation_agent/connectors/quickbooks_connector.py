from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import requests
from dotenv import load_dotenv

from automation_agent.core.audit_logger import AuditLogger


@dataclass
class QuickBooksExportResult:
    """Result returned after preparing QuickBooks-ready files and API plans."""

    success: bool
    customers_rows: int
    invoices_rows: int
    output_paths: dict[str, Path]
    messages: list[str]
    dry_run: bool = True
    api_plan: dict[str, Any] | None = None


@dataclass
class QuickBooksSyncResult:
    """Result returned after QuickBooks API planning or sync."""

    success: bool
    dry_run: bool
    attempted_customers: int
    attempted_invoices: int
    created_customers: int
    created_invoices: int
    output_paths: dict[str, Path]
    messages: list[str]
    errors: list[str]


class QuickBooksConnector:
    """
    QuickBooks connector for V18.

    Safe default behavior:
    - Creates reviewable CSV/Excel exports.
    - Creates API payload preview JSON files.
    - Builds a CustomerRef cache for invoice safety.
    - Generates a sandbox OAuth authorization URL.
    - Does not send real API calls while dry_run=true.

    New in V10:
    - Customer lookup by email/display name when API credentials are configured.
    - Persistent customer reference cache at data/output/quickbooks_customer_ref_cache.json.
    - Invoice payloads use cached CustomerRef IDs when available.
    - Real invoice sync is blocked unless every invoice has a resolved CustomerRef.
    """

    def __init__(self, config: dict | None = None) -> None:
        load_dotenv()
        self.config = config or {}
        integrations = self.config.get("integrations", {})
        self.quickbooks_config = integrations.get("quickbooks", {})
        self.dry_run = self.quickbooks_config.get("dry_run", True)
        self.mode = self.quickbooks_config.get("mode", "export_only")
        self.environment = self.quickbooks_config.get("environment", "sandbox")
        self.minor_version = self.quickbooks_config.get("minor_version", 75)
        self.enable_customer_lookup = self.quickbooks_config.get("enable_customer_lookup", True)
        self.allow_production_sync = self.quickbooks_config.get("allow_production_sync", False)
        self.default_item_ref_id = os.getenv(
            "QUICKBOOKS_DEFAULT_ITEM_ID", self.quickbooks_config.get("default_item_ref_id", "")
        )

        self.client_id = os.getenv("QUICKBOOKS_CLIENT_ID", "")
        self.client_secret = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "QUICKBOOKS_REDIRECT_URI",
            self.quickbooks_config.get("redirect_uri", "http://localhost:8501"),
        )
        self.access_token = os.getenv("QUICKBOOKS_ACCESS_TOKEN", "")
        self.refresh_token = os.getenv("QUICKBOOKS_REFRESH_TOKEN", "")
        self.realm_id = os.getenv("QUICKBOOKS_REALM_ID", "")
        self.audit = AuditLogger(self.output_folder)

    @property
    def base_api_url(self) -> str:
        if self.environment == "production":
            return "https://quickbooks.api.intuit.com"
        return "https://sandbox-quickbooks.api.intuit.com"

    @property
    def output_folder(self) -> Path:
        folder = Path(self.config.get("output", {}).get("folder", "data/output"))
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @property
    def cache_file(self) -> Path:
        return self.output_folder / self.quickbooks_config.get(
            "customer_ref_cache_file", "quickbooks_customer_ref_cache.json"
        )

    @property
    def unresolved_refs_file(self) -> Path:
        return self.output_folder / self.quickbooks_config.get(
            "unresolved_customer_refs_file", "quickbooks_unresolved_customer_refs.json"
        )

    @property
    def oauth_token_summary_file(self) -> Path:
        return self.output_folder / self.quickbooks_config.get(
            "oauth_token_summary_file", "quickbooks_oauth_token_summary.json"
        )

    @property
    def sync_result_file(self) -> Path:
        return self.output_folder / self.quickbooks_config.get(
            "sync_result_file", "quickbooks_api_sync_result.json"
        )

    @property
    def audit_csv_file(self) -> Path:
        return self.audit.csv_path

    @property
    def audit_jsonl_file(self) -> Path:
        return self.audit.jsonl_path

    def get_oauth_status(self) -> dict[str, Any]:
        """Return safe OAuth setup status without exposing full secrets."""
        return {
            "environment": self.environment,
            "redirect_uri": self.redirect_uri,
            "client_id_configured": bool(self.client_id),
            "client_secret_configured": bool(self.client_secret),
            "access_token_configured": bool(self.access_token),
            "refresh_token_configured": bool(self.refresh_token),
            "realm_id_configured": bool(self.realm_id),
            "client_id_preview": self._mask_secret(self.client_id),
            "realm_id_preview": self._mask_secret(self.realm_id, keep_start=4, keep_end=4),
            "authorization_url": self.get_authorization_url(),
        }

    def parse_oauth_redirect(self, redirect_value: str) -> dict[str, str]:
        """Parse either a full QuickBooks redirect URL or a plain authorization code."""
        value = (redirect_value or "").strip()
        if not value:
            return {
                "code": "",
                "realm_id": "",
                "state": "",
                "error": "No redirect URL or code was provided.",
            }

        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            query = parse_qs(parsed.query)
            return {
                "code": query.get("code", [""])[0],
                "realm_id": query.get("realmId", query.get("realm_id", [""]))[0],
                "state": query.get("state", [""])[0],
                "error": query.get("error", [""])[0],
            }

        return {"code": value, "realm_id": "", "state": "", "error": ""}

    def exchange_and_save_authorization_code(
        self,
        redirect_or_code: str,
        realm_id: str = "",
        env_file: str | Path = ".env",
    ) -> dict[str, Any]:
        """Exchange an authorization code and save returned tokens to .env safely."""
        parsed = self.parse_oauth_redirect(redirect_or_code)
        if parsed.get("error"):
            raise ValueError(f"QuickBooks OAuth returned an error: {parsed['error']}")
        authorization_code = parsed.get("code", "")
        final_realm_id = realm_id or parsed.get("realm_id", "")
        if not authorization_code:
            raise ValueError(
                "No authorization code found. Paste the full redirect URL or the code value."
            )

        tokens = self.exchange_authorization_code(authorization_code)
        self.save_oauth_values(tokens=tokens, realm_id=final_realm_id, env_file=env_file)
        return self._token_summary(tokens, final_realm_id)

    def refresh_and_save_access_token(self, env_file: str | Path = ".env") -> dict[str, Any]:
        """Refresh the access token and update .env with the new token values."""
        tokens = self.refresh_access_token()
        self.save_oauth_values(tokens=tokens, realm_id=self.realm_id, env_file=env_file)
        return self._token_summary(tokens, self.realm_id)

    def save_oauth_values(
        self,
        tokens: dict[str, Any] | None = None,
        realm_id: str = "",
        env_file: str | Path = ".env",
        client_id: str = "",
        client_secret: str = "",
        redirect_uri: str = "",
    ) -> dict[str, Any]:
        """Create/update local .env values. Does not print raw tokens."""
        tokens = tokens or {}
        updates: dict[str, str] = {}
        if client_id:
            updates["QUICKBOOKS_CLIENT_ID"] = client_id.strip()
        if client_secret:
            updates["QUICKBOOKS_CLIENT_SECRET"] = client_secret.strip()
        if redirect_uri:
            updates["QUICKBOOKS_REDIRECT_URI"] = redirect_uri.strip()
        if tokens.get("access_token"):
            updates["QUICKBOOKS_ACCESS_TOKEN"] = str(tokens["access_token"])
        if tokens.get("refresh_token"):
            updates["QUICKBOOKS_REFRESH_TOKEN"] = str(tokens["refresh_token"])
        if realm_id:
            updates["QUICKBOOKS_REALM_ID"] = str(realm_id).strip()

        if not updates:
            return {"saved": False, "message": "No OAuth values were provided."}

        self._update_env_file(Path(env_file), updates)

        # Keep process environment in sync for the current Streamlit session.
        for key, value in updates.items():
            os.environ[key] = value

        summary = {
            "saved": True,
            "env_file": str(env_file),
            "updated_keys": sorted(updates.keys()),
            "safe_preview": {key: self._mask_secret(value) for key, value in updates.items()},
        }
        self.oauth_token_summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    @staticmethod
    def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
        existing: dict[str, str] = {}
        order: list[str] = []
        if env_path.exists():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    order.append(raw_line)
                    continue
                key, value = raw_line.split("=", 1)
                existing[key.strip()] = value.strip()
                order.append(key.strip())

        existing.update(updates)
        ordered_keys = [item for item in order if item in existing]
        for key in updates:
            if key not in ordered_keys:
                ordered_keys.append(key)

        lines: list[str] = []
        seen: set[str] = set()
        for item in ordered_keys:
            if item in existing and item not in seen:
                lines.append(f"{item}={existing[item]}")
                seen.add(item)
            elif item not in existing:
                lines.append(item)
        env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    def _token_summary(self, tokens: dict[str, Any], realm_id: str = "") -> dict[str, Any]:
        summary = {
            "access_token_saved": bool(tokens.get("access_token")),
            "refresh_token_saved": bool(tokens.get("refresh_token")),
            "realm_id_saved": bool(realm_id),
            "expires_in": tokens.get("expires_in"),
            "x_refresh_token_expires_in": tokens.get("x_refresh_token_expires_in"),
            "token_type": tokens.get("token_type"),
        }
        self.oauth_token_summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    @staticmethod
    def _mask_secret(value: str, keep_start: int = 6, keep_end: int = 4) -> str:
        value = value or ""
        if not value:
            return ""
        if len(value) <= keep_start + keep_end:
            return "*" * len(value)
        return f"{value[:keep_start]}...{value[-keep_end:]}"

    def get_authorization_url(self, state: str = "business-automation-agent") -> str:
        """Build the Intuit OAuth authorization URL for the user to open manually."""
        params = {
            "client_id": self.client_id or "YOUR_QUICKBOOKS_CLIENT_ID",
            "response_type": "code",
            "scope": "com.intuit.quickbooks.accounting",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return "https://appcenter.intuit.com/connect/oauth2?" + urlencode(params)

    def exchange_authorization_code(self, authorization_code: str) -> dict[str, Any]:
        """Exchange an OAuth authorization code for tokens.

        This method is not called automatically by the app. Use it only after creating
        an Intuit Developer app and receiving a code from the redirect URL.
        """
        if not self.client_id or not self.client_secret:
            raise ValueError("Set QUICKBOOKS_CLIENT_ID and QUICKBOOKS_CLIENT_SECRET in .env first.")

        credentials = f"{self.client_id}:{self.client_secret}".encode()
        auth_header = base64.b64encode(credentials).decode("utf-8")
        response = requests.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            headers={
                "Authorization": f"Basic {auth_header}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def refresh_access_token(self) -> dict[str, Any]:
        """Refresh the QuickBooks OAuth access token using QUICKBOOKS_REFRESH_TOKEN."""
        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise ValueError(
                "Set QUICKBOOKS_CLIENT_ID, QUICKBOOKS_CLIENT_SECRET, and QUICKBOOKS_REFRESH_TOKEN in .env first."
            )

        credentials = f"{self.client_id}:{self.client_secret}".encode()
        auth_header = base64.b64encode(credentials).decode("utf-8")
        response = requests.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            headers={
                "Authorization": f"Basic {auth_header}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def prepare_exports(self, df: pd.DataFrame) -> QuickBooksExportResult:
        output_folder = self.output_folder

        customers_file = output_folder / self.quickbooks_config.get(
            "customers_file", "quickbooks_customers_ready.csv"
        )
        invoices_file = output_folder / self.quickbooks_config.get(
            "invoices_file", "quickbooks_invoices_ready.csv"
        )
        excel_file = output_folder / self.quickbooks_config.get(
            "excel_file", "quickbooks_ready_export.xlsx"
        )
        customer_payload_file = output_folder / self.quickbooks_config.get(
            "customer_payload_file", "quickbooks_customer_payload_preview.json"
        )
        invoice_payload_file = output_folder / self.quickbooks_config.get(
            "invoice_payload_file", "quickbooks_invoice_payload_preview.json"
        )
        api_plan_file = output_folder / self.quickbooks_config.get(
            "api_plan_file", "quickbooks_api_sync_plan.json"
        )

        customers_df = self.build_customers_export(df)
        invoices_df, invoice_messages = self.build_invoices_export(df)
        customer_ref_cache, lookup_messages = self.build_customer_ref_cache(customers_df)
        customer_payloads = self.build_customer_payloads(customers_df)
        invoice_payloads, unresolved_refs = self.build_invoice_payloads(
            invoices_df, customer_ref_cache
        )
        api_plan = self.build_api_sync_plan(
            customers_df,
            invoices_df,
            customer_payloads,
            invoice_payloads,
            customer_ref_cache,
            unresolved_refs,
        )

        customers_df.to_csv(customers_file, index=False)
        invoices_df.to_csv(invoices_file, index=False)

        with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
            customers_df.to_excel(writer, index=False, sheet_name="customers")
            invoices_df.to_excel(writer, index=False, sheet_name="invoices")

        customer_payload_file.write_text(json.dumps(customer_payloads, indent=2), encoding="utf-8")
        invoice_payload_file.write_text(json.dumps(invoice_payloads, indent=2), encoding="utf-8")
        self.cache_file.write_text(json.dumps(customer_ref_cache, indent=2), encoding="utf-8")
        self.unresolved_refs_file.write_text(
            json.dumps(unresolved_refs, indent=2), encoding="utf-8"
        )
        api_plan_file.write_text(json.dumps(api_plan, indent=2), encoding="utf-8")

        self.audit.log_many_planned(
            system="quickbooks", action="create_customer", payloads=customer_payloads
        )
        self.audit.log_many_planned(
            system="quickbooks",
            action="create_invoice",
            payloads=invoice_payloads,
            record_key_field="DocNumber",
        )
        if unresolved_refs:
            for unresolved in unresolved_refs:
                self.audit.log(
                    system="quickbooks",
                    action="create_invoice",
                    status="skipped",
                    record_key=str(unresolved.get("InvoiceNumber", "")),
                    message="Invoice skipped because CustomerRef is unresolved.",
                    error=json.dumps(unresolved, ensure_ascii=False),
                )

        messages = [
            "QuickBooks V24 created export files, API payload previews, CustomerRef cache, OAuth setup helpers, protected sync planning, and audit logs.",
            f"QuickBooks mode: {self.mode}",
            f"QuickBooks environment: {self.environment}",
            f"Dry-run mode: {self.dry_run}",
            f"Customer export created: {customers_file}",
            f"Invoice export created: {invoices_file}",
            f"Excel workbook created: {excel_file}",
            f"Customer payload preview created: {customer_payload_file}",
            f"Invoice payload preview created: {invoice_payload_file}",
            f"CustomerRef cache created: {self.cache_file}",
            f"Unresolved CustomerRefs report created: {self.unresolved_refs_file}",
            f"API sync plan created: {api_plan_file}",
        ]
        messages.extend(invoice_messages)
        messages.extend(lookup_messages)

        if self.dry_run or self.mode != "api_sync":
            messages.append("No real QuickBooks API calls were made.")

        return QuickBooksExportResult(
            success=True,
            customers_rows=len(customers_df),
            invoices_rows=len(invoices_df),
            output_paths={
                "quickbooks_customers": customers_file,
                "quickbooks_invoices": invoices_file,
                "quickbooks_excel": excel_file,
                "quickbooks_customer_payload_preview": customer_payload_file,
                "quickbooks_invoice_payload_preview": invoice_payload_file,
                "quickbooks_customer_ref_cache": self.cache_file,
                "quickbooks_unresolved_customer_refs": self.unresolved_refs_file,
                "quickbooks_api_sync_plan": api_plan_file,
                "automation_audit_log_csv": self.audit_csv_file,
                "automation_audit_log_jsonl": self.audit_jsonl_file,
            },
            messages=messages,
            dry_run=self.dry_run,
            api_plan=api_plan,
        )

    def build_customers_export(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create a QuickBooks-ready customer import shape."""
        output = pd.DataFrame()
        source = df.copy()

        first_name = self._get_series(source, "first_name")
        last_name = self._get_series(source, "last_name")
        company = self._get_series(source, "company")
        email = self._get_series(source, "email")
        phone = self._get_series(source, "phone")
        city = self._get_series(source, "city")
        country = self._get_series(source, "country")

        display_name = self._combine_display_name(first_name, last_name, company, email)

        output["DisplayName"] = display_name
        output["GivenName"] = first_name
        output["FamilyName"] = last_name
        output["CompanyName"] = company
        output["PrimaryEmailAddr"] = email
        output["PrimaryPhone"] = phone
        output["BillAddr_City"] = city
        output["BillAddr_Country"] = country
        output["SourceSystem"] = "business_automation_agent_v11"

        return output.drop_duplicates(subset=["PrimaryEmailAddr"], keep="first").reset_index(
            drop=True
        )

    def build_invoices_export(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        """Create a QuickBooks-ready invoice import shape when invoice fields exist."""
        messages: list[str] = []
        required_invoice_columns = self.quickbooks_config.get(
            "invoice_required_columns", ["invoice_number", "amount"]
        )

        missing_required = [col for col in required_invoice_columns if col not in df.columns]
        invoice_columns = [
            "InvoiceNumber",
            "CustomerEmail",
            "CustomerDisplayName",
            "InvoiceDate",
            "DueDate",
            "LineDescription",
            "Quantity",
            "UnitPrice",
            "Amount",
            "Currency",
            "Status",
        ]

        if missing_required:
            messages.append(
                "Invoice export is empty because these required invoice columns are missing: "
                + ", ".join(missing_required)
            )
            return pd.DataFrame(columns=invoice_columns), messages

        source = df.copy()
        output = pd.DataFrame()
        email = self._get_series(source, "email")
        first_name = self._get_series(source, "first_name")
        last_name = self._get_series(source, "last_name")
        company = self._get_series(source, "company")
        customer_name = self._combine_display_name(first_name, last_name, company, email)

        output["InvoiceNumber"] = self._get_series(source, "invoice_number")
        output["CustomerEmail"] = email
        output["CustomerDisplayName"] = customer_name
        output["InvoiceDate"] = self._get_series(source, "invoice_date")
        output["DueDate"] = self._get_series(source, "due_date")
        output["LineDescription"] = self._get_series(
            source, "description", default="Business service"
        )
        output["Quantity"] = pd.to_numeric(
            self._get_series(source, "quantity", default=1), errors="coerce"
        ).fillna(1)
        output["UnitPrice"] = pd.to_numeric(self._get_series(source, "unit_price"), errors="coerce")
        amount = pd.to_numeric(self._get_series(source, "amount"), errors="coerce")
        output["Amount"] = amount
        output["Currency"] = self._get_series(source, "currency", default="EUR")
        output["Status"] = "ready_for_review"

        output["UnitPrice"] = output["UnitPrice"].fillna(output["Amount"])
        output = output.dropna(subset=["InvoiceNumber", "CustomerEmail", "Amount"])
        output = output.drop_duplicates(subset=["InvoiceNumber"], keep="first").reset_index(
            drop=True
        )

        if output.empty:
            messages.append("Invoice columns were found, but no valid invoice rows were created.")
        else:
            messages.append(f"Invoice export contains {len(output)} ready-for-review invoice rows.")

        return output, messages

    def build_customer_ref_cache(
        self, customers_df: pd.DataFrame
    ) -> tuple[dict[str, Any], list[str]]:
        """Load saved CustomerRef values and optionally query QuickBooks for missing customers."""
        messages: list[str] = []
        cache = self._load_customer_ref_cache()
        lookup_allowed = bool(
            self.enable_customer_lookup
            and self.mode == "api_sync"
            and self.access_token
            and self.realm_id
        )

        if not lookup_allowed:
            messages.append(
                "Customer lookup skipped. Enable api_sync and configure QUICKBOOKS_ACCESS_TOKEN + QUICKBOOKS_REALM_ID to query QuickBooks."
            )
            return cache, messages

        checked = 0
        found = 0
        for _, row in customers_df.iterrows():
            email = self._clean_scalar(row.get("PrimaryEmailAddr")).lower()
            display_name = self._clean_scalar(row.get("DisplayName"))
            if not email and not display_name:
                continue

            cache_key = self._cache_key(email, display_name)
            if cache_key in cache and cache[cache_key].get("id"):
                continue

            checked += 1
            try:
                customer = self.lookup_customer(email=email, display_name=display_name)
                if customer:
                    cache[cache_key] = {
                        "id": self._clean_scalar(customer.get("Id")),
                        "display_name": self._clean_scalar(customer.get("DisplayName"))
                        or display_name,
                        "email": email,
                        "source": "quickbooks_lookup",
                    }
                    found += 1
            except Exception as error:
                cache[cache_key] = {
                    "id": "",
                    "display_name": display_name,
                    "email": email,
                    "source": "lookup_error",
                    "error": str(error),
                }

        messages.append(
            f"QuickBooks customer lookup checked {checked} customers and found {found} existing CustomerRef IDs."
        )
        return cache, messages

    def lookup_customer(self, email: str = "", display_name: str = "") -> dict[str, Any] | None:
        """Find one QuickBooks customer by email first, then display name."""
        if email:
            customer = self._query_one_customer(
                f"PrimaryEmailAddr = '{self._escape_query_value(email)}'"
            )
            if customer:
                return customer
        if display_name:
            customer = self._query_one_customer(
                f"DisplayName = '{self._escape_query_value(display_name)}'"
            )
            if customer:
                return customer
        return None

    def _query_one_customer(self, where_clause: str) -> dict[str, Any] | None:
        query = f"select * from Customer where {where_clause} maxresults 1"
        url = (
            f"{self.base_api_url}/v3/company/{self.realm_id}/query"
            f"?minorversion={self.minor_version}"
        )
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            params={"query": query},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        customers = data.get("QueryResponse", {}).get("Customer", [])
        return customers[0] if customers else None

    def build_customer_payloads(self, customers_df: pd.DataFrame) -> list[dict[str, Any]]:
        """Map export rows to QuickBooks Customer create payloads."""
        payloads: list[dict[str, Any]] = []
        for _, row in customers_df.iterrows():
            payload: dict[str, Any] = {
                "DisplayName": self._clean_scalar(row.get("DisplayName")),
            }
            if self._clean_scalar(row.get("GivenName")):
                payload["GivenName"] = self._clean_scalar(row.get("GivenName"))
            if self._clean_scalar(row.get("FamilyName")):
                payload["FamilyName"] = self._clean_scalar(row.get("FamilyName"))
            if self._clean_scalar(row.get("CompanyName")):
                payload["CompanyName"] = self._clean_scalar(row.get("CompanyName"))
            if self._clean_scalar(row.get("PrimaryEmailAddr")):
                payload["PrimaryEmailAddr"] = {
                    "Address": self._clean_scalar(row.get("PrimaryEmailAddr"))
                }
            if self._clean_scalar(row.get("PrimaryPhone")):
                payload["PrimaryPhone"] = {
                    "FreeFormNumber": self._clean_scalar(row.get("PrimaryPhone"))
                }
            if self._clean_scalar(row.get("BillAddr_City")) or self._clean_scalar(
                row.get("BillAddr_Country")
            ):
                payload["BillAddr"] = {
                    "City": self._clean_scalar(row.get("BillAddr_City")),
                    "Country": self._clean_scalar(row.get("BillAddr_Country")),
                }
            payloads.append(payload)
        return payloads

    def build_invoice_payloads(
        self,
        invoices_df: pd.DataFrame,
        customer_ref_cache: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Map export rows to QuickBooks Invoice payload previews using CustomerRef cache."""
        customer_ref_cache = customer_ref_cache or {}
        payloads: list[dict[str, Any]] = []
        unresolved_refs: list[dict[str, Any]] = []

        for _, row in invoices_df.iterrows():
            amount = float(row.get("Amount") or 0)
            quantity = float(row.get("Quantity") or 1)
            unit_price = float(row.get("UnitPrice") or amount)
            email = self._clean_scalar(row.get("CustomerEmail")).lower()
            display_name = self._clean_scalar(row.get("CustomerDisplayName"))
            cache_key = self._cache_key(email, display_name)
            cached_customer = customer_ref_cache.get(cache_key, {})
            customer_id = self._clean_scalar(cached_customer.get("id"))

            if not customer_id:
                unresolved_refs.append(
                    {
                        "invoice_number": self._clean_scalar(row.get("InvoiceNumber")),
                        "customer_email": email,
                        "customer_display_name": display_name,
                        "cache_key": cache_key,
                        "reason": "No QuickBooks CustomerRef ID found in cache.",
                    }
                )
                customer_id = "CUSTOMER_REF_LOOKUP_REQUIRED"

            payloads.append(
                {
                    "DocNumber": self._clean_scalar(row.get("InvoiceNumber")),
                    "TxnDate": self._clean_scalar(row.get("InvoiceDate")) or None,
                    "CustomerRef": {
                        "value": customer_id,
                        "name": cached_customer.get("display_name") or display_name,
                    },
                    "PrivateNote": f"Customer email: {email}",
                    "Line": [
                        {
                            "DetailType": "SalesItemLineDetail",
                            "Amount": amount,
                            "Description": self._clean_scalar(row.get("LineDescription")),
                            "SalesItemLineDetail": {
                                "Qty": quantity,
                                "UnitPrice": unit_price,
                                **(
                                    {"ItemRef": {"value": self.default_item_ref_id}}
                                    if self.default_item_ref_id
                                    else {}
                                ),
                            },
                        }
                    ],
                }
            )
        return payloads, unresolved_refs

    def build_api_sync_plan(
        self,
        customers_df: pd.DataFrame,
        invoices_df: pd.DataFrame,
        customer_payloads: list[dict[str, Any]],
        invoice_payloads: list[dict[str, Any]],
        customer_ref_cache: dict[str, Any] | None = None,
        unresolved_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        customer_ref_cache = customer_ref_cache or {}
        unresolved_refs = unresolved_refs or []
        has_credentials = bool(self.access_token and self.realm_id)
        ready_for_api_mode = bool(self.mode == "api_sync" and not self.dry_run and has_credentials)
        invoices_have_customer_refs = bool(invoice_payloads) and not unresolved_refs

        blocking_reasons: list[str] = []
        if self.mode != "api_sync":
            blocking_reasons.append("quickbooks.mode is not api_sync")
        if self.dry_run:
            blocking_reasons.append("quickbooks.dry_run is true")
        if self.environment != "sandbox" and not self.allow_production_sync:
            blocking_reasons.append(
                "Production sync is blocked unless quickbooks.allow_production_sync is true"
            )
        if not self.access_token:
            blocking_reasons.append("QUICKBOOKS_ACCESS_TOKEN is missing")
        if not self.realm_id:
            blocking_reasons.append("QUICKBOOKS_REALM_ID is missing")
        if invoice_payloads and not self.default_item_ref_id:
            blocking_reasons.append("QUICKBOOKS_DEFAULT_ITEM_ID is missing for invoice line items")
        if unresolved_refs:
            blocking_reasons.append(
                f"{len(unresolved_refs)} invoice customer reference(s) are unresolved"
            )

        return {
            "version": "11.0.0",
            "environment": self.environment,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "ready_for_customer_api_sync": ready_for_api_mode,
            "ready_for_invoice_api_sync": ready_for_api_mode and invoices_have_customer_refs,
            "blocking_reasons": blocking_reasons,
            "summary": {
                "customers_ready_for_review": len(customers_df),
                "invoices_ready_for_review": len(invoices_df),
                "customer_payloads_prepared": len(customer_payloads),
                "invoice_payloads_prepared": len(invoice_payloads),
                "customer_ref_cache_entries": len(customer_ref_cache),
                "resolved_invoice_customer_refs": max(
                    len(invoice_payloads) - len(unresolved_refs), 0
                ),
                "unresolved_invoice_customer_refs": len(unresolved_refs),
            },
            "oauth": {
                "authorization_url": self.get_authorization_url(),
                "redirect_uri": self.redirect_uri,
                "realm_id_configured": bool(self.realm_id),
                "access_token_configured": bool(self.access_token),
            },
            "customer_ref_cache_file": str(self.cache_file),
            "unresolved_customer_refs_file": str(self.unresolved_refs_file),
            "unresolved_customer_refs": unresolved_refs,
            "notes": [
                "Open the authorization_url only after creating an Intuit Developer sandbox app.",
                "Keep .env secrets private and never commit them to GitHub.",
                "V18 can run a protected sandbox sync: customers first, cache update second, invoices last.",
                "V18 writes an audit log for planned, skipped, created, and failed CRM/accounting actions.",
                "Real invoice sync should only be enabled when ready_for_invoice_api_sync is true and the output was reviewed.",
            ],
        }

    def sync_customers(self, df: pd.DataFrame) -> QuickBooksSyncResult:
        """Protected QuickBooks sandbox sync.

        The sequence is intentionally conservative:
        1. Recreate exports and payload previews.
        2. Create missing customers first.
        3. Save returned QuickBooks CustomerRef IDs into the local cache.
        4. Rebuild invoice payloads using the updated cache.
        5. Create invoices only when every invoice has a resolved CustomerRef.
        """
        export_result = self.prepare_exports(df)
        errors: list[str] = []
        messages = list(export_result.messages)
        created_customers = 0
        created_invoices = 0

        if self.dry_run or self.mode != "api_sync":
            messages.append(
                "QuickBooks sync finished in safe planning mode. No API records were created."
            )
            self.audit.log(
                system="quickbooks",
                action="protected_sync",
                status="skipped",
                message="Safe planning mode. No API records were created because dry_run is true or mode is not api_sync.",
            )
            sync_summary = self._write_sync_result(
                success=True,
                dry_run=self.dry_run,
                attempted_customers=export_result.customers_rows,
                attempted_invoices=export_result.invoices_rows,
                created_customers=0,
                created_invoices=0,
                messages=messages,
                errors=errors,
            )
            export_result.output_paths["quickbooks_api_sync_result"] = self.sync_result_file
            return QuickBooksSyncResult(
                success=True,
                dry_run=self.dry_run,
                attempted_customers=export_result.customers_rows,
                attempted_invoices=export_result.invoices_rows,
                created_customers=0,
                created_invoices=0,
                output_paths=export_result.output_paths,
                messages=messages + [f"Sync result saved: {sync_summary['file']}"],
                errors=errors,
            )

        if self.environment != "sandbox" and not self.allow_production_sync:
            errors.append(
                "Production sync is blocked. Use sandbox or set quickbooks.allow_production_sync=true intentionally."
            )

        if not self.access_token or not self.realm_id:
            errors.append("Missing QUICKBOOKS_ACCESS_TOKEN or QUICKBOOKS_REALM_ID.")

        if errors:
            for error in errors:
                self.audit.log(
                    system="quickbooks", action="protected_sync", status="failed", error=error
                )
            self._write_sync_result(
                success=False,
                dry_run=self.dry_run,
                attempted_customers=export_result.customers_rows,
                attempted_invoices=export_result.invoices_rows,
                created_customers=0,
                created_invoices=0,
                messages=messages,
                errors=errors,
            )
            export_result.output_paths["quickbooks_api_sync_result"] = self.sync_result_file
            return QuickBooksSyncResult(
                success=False,
                dry_run=self.dry_run,
                attempted_customers=export_result.customers_rows,
                attempted_invoices=export_result.invoices_rows,
                created_customers=0,
                created_invoices=0,
                output_paths=export_result.output_paths,
                messages=messages,
                errors=errors,
            )

        customer_payload_file = export_result.output_paths["quickbooks_customer_payload_preview"]
        customer_payloads = json.loads(customer_payload_file.read_text(encoding="utf-8"))

        cache = self._load_customer_ref_cache()
        messages.append("Starting protected QuickBooks sync: customers first, invoices second.")

        for payload in customer_payloads:
            display_name = self._clean_scalar(payload.get("DisplayName"))
            email = self._clean_scalar(
                payload.get("PrimaryEmailAddr", {}).get("Address", "")
            ).lower()
            cache_key = self._cache_key(email, display_name)

            if cache.get(cache_key, {}).get("id"):
                cached_id = self._clean_scalar(cache.get(cache_key, {}).get("id"))
                messages.append(f"Skipped existing cached customer: {display_name or email}")
                self.audit.log(
                    system="quickbooks",
                    action="create_customer",
                    status="skipped",
                    external_id=cached_id,
                    record_key=display_name or email,
                    message="Customer already exists in local CustomerRef cache.",
                    payload_preview=payload,
                )
                continue

            try:
                response = self._create_customer(payload)
                customer = response.get("Customer", {})
                customer_id = self._clean_scalar(customer.get("Id"))
                if customer_id:
                    cache[cache_key] = {
                        "id": customer_id,
                        "display_name": self._clean_scalar(customer.get("DisplayName"))
                        or display_name,
                        "email": email,
                        "source": "created_by_business_automation_agent_v11",
                    }
                    created_customers += 1
                    self.audit.log(
                        system="quickbooks",
                        action="create_customer",
                        status="created",
                        external_id=customer_id,
                        record_key=display_name or email,
                        message="QuickBooks customer created successfully.",
                        payload_preview=payload,
                    )
                    messages.append(
                        f"Created QuickBooks customer: {display_name or email} -> CustomerRef {customer_id}"
                    )
                else:
                    error_message = (
                        f"Customer {display_name or email} was created but no Id was returned."
                    )
                    self.audit.log(
                        system="quickbooks",
                        action="create_customer",
                        status="failed",
                        record_key=display_name or email,
                        error=error_message,
                        payload_preview=payload,
                    )
                    errors.append(error_message)
            except Exception as error:
                error_message = f"Customer {display_name or email} failed: {error}"
                self.audit.log(
                    system="quickbooks",
                    action="create_customer",
                    status="failed",
                    record_key=display_name or email,
                    error=str(error),
                    payload_preview=payload,
                )
                errors.append(error_message)

        self.cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")

        invoices_df = pd.read_csv(export_result.output_paths["quickbooks_invoices"])
        invoice_payloads, unresolved_refs = self.build_invoice_payloads(invoices_df, cache)
        export_result.output_paths["quickbooks_invoice_payload_preview"].write_text(
            json.dumps(invoice_payloads, indent=2), encoding="utf-8"
        )
        self.unresolved_refs_file.write_text(
            json.dumps(unresolved_refs, indent=2), encoding="utf-8"
        )

        api_plan = self.build_api_sync_plan(
            pd.read_csv(export_result.output_paths["quickbooks_customers"]),
            invoices_df,
            customer_payloads,
            invoice_payloads,
            cache,
            unresolved_refs,
        )
        export_result.output_paths["quickbooks_api_sync_plan"].write_text(
            json.dumps(api_plan, indent=2), encoding="utf-8"
        )

        if unresolved_refs:
            errors.append(
                "Invoice sync blocked because not every invoice has a resolved CustomerRef after customer creation."
            )
        elif invoice_payloads and not self.default_item_ref_id:
            errors.append("Invoice sync blocked because QUICKBOOKS_DEFAULT_ITEM_ID is missing.")
        else:
            for payload in invoice_payloads:
                try:
                    invoice_response = self._create_invoice(payload)
                    created_invoices += 1
                    invoice_id = (
                        self._clean_scalar(invoice_response.get("Invoice", {}).get("Id"))
                        if isinstance(invoice_response, dict)
                        else ""
                    )
                    self.audit.log(
                        system="quickbooks",
                        action="create_invoice",
                        status="created",
                        external_id=invoice_id,
                        record_key=str(payload.get("DocNumber", "")),
                        message="QuickBooks invoice created successfully.",
                        payload_preview=payload,
                    )
                    messages.append(f"Created QuickBooks invoice: {payload.get('DocNumber')}")
                except Exception as error:
                    self.audit.log(
                        system="quickbooks",
                        action="create_invoice",
                        status="failed",
                        record_key=str(payload.get("DocNumber", "")),
                        error=str(error),
                        payload_preview=payload,
                    )
                    errors.append(f"Invoice {payload.get('DocNumber')} failed: {error}")

        success = not errors
        messages.append(f"Created {created_customers} QuickBooks customers.")
        messages.append(f"Created {created_invoices} QuickBooks invoices.")
        self._write_sync_result(
            success=success,
            dry_run=self.dry_run,
            attempted_customers=export_result.customers_rows,
            attempted_invoices=export_result.invoices_rows,
            created_customers=created_customers,
            created_invoices=created_invoices,
            messages=messages,
            errors=errors,
        )
        export_result.output_paths["quickbooks_api_sync_result"] = self.sync_result_file
        return QuickBooksSyncResult(
            success=success,
            dry_run=self.dry_run,
            attempted_customers=export_result.customers_rows,
            attempted_invoices=export_result.invoices_rows,
            created_customers=created_customers,
            created_invoices=created_invoices,
            output_paths=export_result.output_paths,
            messages=messages,
            errors=errors,
        )

    def _write_sync_result(
        self,
        success: bool,
        dry_run: bool,
        attempted_customers: int,
        attempted_invoices: int,
        created_customers: int,
        created_invoices: int,
        messages: list[str],
        errors: list[str],
    ) -> dict[str, Any]:
        result = {
            "version": "11.0.0",
            "environment": self.environment,
            "mode": self.mode,
            "dry_run": dry_run,
            "success": success,
            "attempted_customers": attempted_customers,
            "attempted_invoices": attempted_invoices,
            "created_customers": created_customers,
            "created_invoices": created_invoices,
            "messages": messages,
            "errors": errors,
            "audit_log_csv": str(self.audit_csv_file),
            "audit_log_jsonl": str(self.audit_jsonl_file),
        }
        self.sync_result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return {"file": str(self.sync_result_file), "result": result}

    def _create_customer(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.base_api_url}/v3/company/{self.realm_id}/customer"
            f"?minorversion={self.minor_version}"
        )
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.base_api_url}/v3/company/{self.realm_id}/invoice"
            f"?minorversion={self.minor_version}"
        )
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _load_customer_ref_cache(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _get_series(df: pd.DataFrame, column: str, default: Any = "") -> pd.Series:
        if column in df.columns:
            return df[column].fillna("").astype(str).str.strip()
        return pd.Series([default] * len(df), index=df.index).astype(str)

    @staticmethod
    def _combine_display_name(
        first_name: pd.Series,
        last_name: pd.Series,
        company: pd.Series,
        email: pd.Series,
    ) -> pd.Series:
        person_name = (first_name + " " + last_name).str.strip()
        display_name = person_name.where(person_name != "", company)
        display_name = display_name.where(display_name != "", email)
        return display_name.fillna("").astype(str).str.strip()

    @staticmethod
    def _cache_key(email: str, display_name: str) -> str:
        email = (email or "").strip().lower()
        display_name = (display_name or "").strip().lower()
        return email or f"display_name:{display_name}"

    @staticmethod
    def _escape_query_value(value: str) -> str:
        return value.replace("'", "\\'")

    @staticmethod
    def _clean_scalar(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.lower() in {"nan", "none", "nat"}:
            return ""
        return text
