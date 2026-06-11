from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# Allow running Streamlit without installing the package locally.
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

from automation_agent.connectors.hubspot_connector import HubSpotConnector
from automation_agent.connectors.quickbooks_connector import QuickBooksConnector
from automation_agent.core.approval_history import ApprovalHistory
from automation_agent.core.audit_logger import AuditLogger
from automation_agent.core.auth_manager import AuthManager
from automation_agent.core.config_manager import ConfigManager
from automation_agent.core.database import DatabaseManager
from automation_agent.core.email_notifier import EmailNotifier
from automation_agent.core.file_versioning import FileVersionManager
from automation_agent.core.pipeline import process_dataframe
from automation_agent.core.role_based_approval import RoleBasedApproval
from automation_agent.core.scheduler import ScheduledJobManager
from automation_agent.core.system_backup import SystemBackupManager

st.set_page_config(
    page_title="Business Automation Agent V24",
    page_icon="🤖",
    layout="wide",
)


@st.cache_data
def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as file:
        return yaml.safe_load(file)


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    file_name = uploaded_file.name.lower()
    if file_name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if file_name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    raise ValueError("Unsupported file type. Please upload CSV, XLSX, or XLS.")


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "data") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def dataframe_pair_to_excel_bytes(customers_df: pd.DataFrame, invoices_df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        customers_df.to_excel(writer, index=False, sheet_name="customers")
        invoices_df.to_excel(writer, index=False, sheet_name="invoices")
    return output.getvalue()


def show_dataframe_section(title: str, df: pd.DataFrame, help_text: str) -> None:
    st.subheader(title)
    st.caption(help_text)
    if df.empty:
        st.info("No rows in this section.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def show_quickbooks_oauth_setup(config: dict) -> None:
    """Streamlit setup helper for QuickBooks OAuth without exposing tokens."""
    st.subheader("🔐 QuickBooks OAuth Setup")
    st.caption(
        "Use this page to generate the sandbox authorization URL, paste the redirect URL/code, "
        "and save QuickBooks tokens locally in your .env file. Tokens are never shown in full."
    )

    qb_connector = QuickBooksConnector(config)
    status = qb_connector.get_oauth_status()

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Client ID", "Ready" if status["client_id_configured"] else "Missing")
    s2.metric("Client Secret", "Ready" if status["client_secret_configured"] else "Missing")
    s3.metric("Access Token", "Ready" if status["access_token_configured"] else "Missing")
    s4.metric("Refresh Token", "Ready" if status["refresh_token_configured"] else "Missing")
    s5.metric("Realm ID", "Ready" if status["realm_id_configured"] else "Missing")

    st.write("**Current setup preview:**")
    st.json(
        {
            "environment": status["environment"],
            "redirect_uri": status["redirect_uri"],
            "client_id_preview": status["client_id_preview"],
            "realm_id_preview": status["realm_id_preview"],
        }
    )

    with st.expander(
        "1. Save QuickBooks app credentials to .env", expanded=not status["client_id_configured"]
    ):
        st.caption(
            "Create a QuickBooks/Intuit sandbox app first, then paste your Client ID and Client Secret here. "
            "The values are saved only to your local .env file."
        )
        client_id = st.text_input(
            "QuickBooks Client ID", value="", placeholder="Paste sandbox client ID"
        )
        client_secret = st.text_input(
            "QuickBooks Client Secret",
            value="",
            placeholder="Paste sandbox client secret",
            type="password",
        )
        redirect_uri = st.text_input(
            "Redirect URI",
            value=status["redirect_uri"] or "http://localhost:8501",
            help="This must match the Redirect URI configured in your Intuit Developer app.",
        )
        if st.button("Save QuickBooks credentials to .env"):
            try:
                save_result = qb_connector.save_oauth_values(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                    env_file=PROJECT_ROOT / ".env",
                )
                st.success(
                    "QuickBooks credentials saved to .env. Restart Streamlit if the authorization URL does not update immediately."
                )
                st.json(save_result)
            except Exception as error:
                st.error(f"Could not save credentials: {error}")

    with st.expander("2. Open authorization URL", expanded=True):
        st.caption(
            "Open this URL, connect your sandbox company, then copy the full redirect URL from your browser."
        )
        st.code(status.get("authorization_url", ""), language="text")
        st.info(
            "After approval, QuickBooks redirects back with code=... and realmId=.... Copy that full URL."
        )

    with st.expander("3. Exchange authorization code and save tokens", expanded=False):
        redirect_or_code = st.text_area(
            "Paste full redirect URL or only the code value",
            placeholder="http://localhost:8501/?code=...&state=...&realmId=...",
            height=100,
        )
        manual_realm_id = st.text_input(
            "Realm ID / Company ID optional",
            value="",
            help="Only needed if you pasted only the code and not the full redirect URL.",
        )
        parsed_preview = (
            qb_connector.parse_oauth_redirect(redirect_or_code) if redirect_or_code else {}
        )
        if parsed_preview:
            st.write("**Parsed preview:**")
            st.json(
                {
                    "code_found": bool(parsed_preview.get("code")),
                    "realm_id_found": bool(parsed_preview.get("realm_id")),
                    "state": parsed_preview.get("state", ""),
                    "error": parsed_preview.get("error", ""),
                }
            )
        if st.button("Exchange code and save QuickBooks tokens"):
            try:
                token_summary = qb_connector.exchange_and_save_authorization_code(
                    redirect_or_code=redirect_or_code,
                    realm_id=manual_realm_id,
                    env_file=PROJECT_ROOT / ".env",
                )
                st.success("QuickBooks tokens saved to .env successfully.")
                st.json(token_summary)
            except Exception as error:
                st.error(f"Token exchange failed: {error}")

    with st.expander("4. Refresh access token", expanded=False):
        st.caption(
            "Use this when you already have QUICKBOOKS_REFRESH_TOKEN in .env and need a new access token."
        )
        if st.button("Refresh and save QuickBooks access token"):
            try:
                refresh_summary = qb_connector.refresh_and_save_access_token(
                    env_file=PROJECT_ROOT / ".env"
                )
                st.success("QuickBooks access token refreshed and saved.")
                st.json(refresh_summary)
            except Exception as error:
                st.error(f"Token refresh failed: {error}")

    st.warning(
        "Keep your .env file private. Do not upload it to GitHub or share it in screenshots."
    )


def show_role_rules(config: dict) -> None:
    st.subheader("👥 Role-Based Approval Rules")
    st.caption(
        "V20 uses login authentication, dashboard user management, settings admin, and file versioning, so the user role is selected automatically from the signed-in account."
    )
    role_guard = RoleBasedApproval(config, config.get("output", {}).get("folder", "data/output"))
    matrix_df = role_guard.read_permission_matrix()
    st.dataframe(matrix_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download permission matrix CSV",
        data=matrix_df.to_csv(index=False).encode("utf-8"),
        file_name="role_permission_matrix.csv",
        mime="text/csv",
    )
    st.info(
        "Typical setup: viewer can only view outputs, reviewer can approve exports, "
        "approver can approve CRM and QuickBooks sandbox sync, and admin can approve production sync."
    )


def render_auth_gate(config: dict):
    """Render login/logout controls and return the signed-in user dictionary."""
    output_folder = config.get("output", {}).get("folder", "data/output")
    auth_manager = AuthManager(config, output_folder)

    if not auth_manager.enabled or not config.get("auth", {}).get("login_required", True):
        return {
            "username": "local_user",
            "display_name": "Local User",
            "email": "",
            "role": config.get("approval", {})
            .get("role_based", {})
            .get("default_role", "reviewer"),
            "active": True,
        }

    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None

    current_user = auth_manager.from_session_dict(st.session_state.auth_user)

    with st.sidebar:
        st.header("User Login")
        if current_user:
            st.success(f"Signed in as {current_user.display_name}")
            st.write(f"**Role:** `{current_user.role}`")
            st.write(f"**Username:** `{current_user.username}`")
            if st.button("Logout"):
                st.session_state.auth_user = None
                st.rerun()
        else:
            st.caption(
                "Demo accounts: viewer/viewer123, reviewer/reviewer123, approver/approver123, admin/admin123"
            )
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.button("Login", type="primary"):
                user = auth_manager.authenticate(username, password)
                if user:
                    st.session_state.auth_user = auth_manager.to_session_dict(user)
                    st.success("Login successful.")
                    st.rerun()
                else:
                    st.error("Login failed. Check username, password, or active status.")

    current_user = auth_manager.from_session_dict(st.session_state.auth_user)
    if not current_user:
        st.title("🤖 Business Automation Agent V24")
        st.info("Please sign in from the sidebar to use the automation dashboard.")
        st.warning(
            "For production, replace this local demo login with SSO/OAuth such as Google Workspace, Azure AD, Auth0, or another identity provider."
        )
        st.stop()

    return auth_manager.to_session_dict(current_user)


def show_auth_admin(config: dict, current_user: dict) -> None:
    st.subheader("🔐 Authentication")
    st.caption(
        "V20 includes dashboard user management, settings admin, file versioning, and rollback. Admins can add users, change roles, deactivate/reactivate users, and reset passwords without editing config.yaml."
    )
    output_folder = config.get("output", {}).get("folder", "data/output")
    auth_manager = AuthManager(config, output_folder)

    c1, c2, c3 = st.columns(3)
    c1.metric("Signed-in user", current_user.get("display_name", ""))
    c2.metric("Role", current_user.get("role", ""))
    c3.metric("Auth enabled", "Yes" if auth_manager.enabled else "No")

    st.write("**Configured users**")
    users_df = auth_manager.users_dataframe()
    st.dataframe(users_df, use_container_width=True, hide_index=True)

    st.write("**Login events**")
    events_df = auth_manager.read_login_events()
    if events_df.empty:
        st.info("No login events recorded yet.")
    else:
        st.dataframe(events_df.tail(100), use_container_width=True, hide_index=True)
        st.download_button(
            "Download login events JSONL",
            data=auth_manager.login_events_file.read_bytes(),
            file_name="auth_login_events.jsonl",
            mime="application/jsonl",
        )

    if current_user.get("role") != "admin":
        st.info(
            "Only admins can manage users. Open the User Management tab with an admin account to make changes."
        )
    else:
        st.success(
            "Admin role detected. Open the User Management tab to add, deactivate, update roles, or reset passwords."
        )


def show_user_management(config: dict, current_user: dict) -> None:
    st.subheader("👤 User Management")
    st.caption(
        "V20 lets admins manage local MVP users from the dashboard instead of editing config.yaml manually."
    )

    output_folder = config.get("output", {}).get("folder", "data/output")
    auth_manager = AuthManager(config, output_folder)
    roles = auth_manager.allowed_roles()

    if current_user.get("role") != "admin":
        st.info(
            "Only admin users can add, deactivate, reactivate, update roles, or reset passwords."
        )
        st.dataframe(auth_manager.users_dataframe(), use_container_width=True, hide_index=True)
        return

    initialized = auth_manager.initialize_user_store_if_missing(
        actor=current_user.get("username", "admin")
    )
    if initialized:
        st.success("Initialized auth_users.json from config.yaml. Future changes are stored there.")

    st.write("**Current managed users**")
    users_df = auth_manager.users_dataframe()
    st.dataframe(users_df, use_container_width=True, hide_index=True)

    with st.expander("Add new user", expanded=False):
        with st.form("add_user_form"):
            c1, c2 = st.columns(2)
            username = c1.text_input("Username", placeholder="new.user")
            display_name = c2.text_input("Display name", placeholder="New User")
            email = c1.text_input("Email", placeholder="new.user@example.com")
            role = c2.selectbox(
                "Role", roles, index=roles.index("viewer") if "viewer" in roles else 0
            )
            password = st.text_input(
                "Temporary password", type="password", help="Minimum 8 characters."
            )
            active = st.checkbox("Active", value=True)
            submitted = st.form_submit_button("Create user")
        if submitted:
            try:
                auth_manager.create_user(
                    username=username,
                    display_name=display_name,
                    email=email,
                    role=role,
                    password=password,
                    active=active,
                    actor=current_user.get("username", "admin"),
                )
                st.success(f"User '{username}' created.")
                st.rerun()
            except Exception as error:
                st.error(f"Could not create user: {error}")

    if not users_df.empty:
        with st.expander("Update existing user", expanded=False):
            selected_username = st.selectbox("Select user", users_df["username"].tolist())
            selected = auth_manager.get_user(selected_username) or {}
            with st.form("update_user_form"):
                c1, c2 = st.columns(2)
                new_display_name = c1.text_input(
                    "Display name", value=str(selected.get("display_name", ""))
                )
                new_email = c2.text_input("Email", value=str(selected.get("email", "")))
                current_role = str(selected.get("role", "viewer"))
                role_index = roles.index(current_role) if current_role in roles else 0
                new_role = c1.selectbox("Role", roles, index=role_index)
                new_active = c2.checkbox("Active", value=bool(selected.get("active", True)))
                new_password = st.text_input(
                    "New password optional",
                    type="password",
                    help="Leave empty to keep the current password.",
                )
                update_submitted = st.form_submit_button("Save changes")
            if update_submitted:
                try:
                    auth_manager.update_user(
                        username=selected_username,
                        display_name=new_display_name,
                        email=new_email,
                        role=new_role,
                        active=new_active,
                        new_password=new_password or None,
                        actor=current_user.get("username", "admin"),
                    )
                    st.success(f"User '{selected_username}' updated.")
                    if selected_username == current_user.get("username") and not new_active:
                        st.session_state.auth_user = None
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not update user: {error}")

    st.write("**User management events**")
    events_df = auth_manager.read_user_management_events()
    if events_df.empty:
        st.info("No user-management events recorded yet.")
    else:
        st.dataframe(events_df.tail(200), use_container_width=True, hide_index=True)
        st.download_button(
            "Download user management events JSONL",
            data=auth_manager.user_management_events_file.read_bytes(),
            file_name="auth_user_management_events.jsonl",
            mime="application/jsonl",
        )

    if auth_manager.user_store_file.exists():
        st.download_button(
            "Download managed users JSON",
            data=auth_manager.user_store_file.read_bytes(),
            file_name="auth_users.json",
            mime="application/json",
        )
        st.warning("Do not commit auth_users.json to GitHub because it contains password hashes.")


def show_database_admin(config: dict, current_user: dict) -> None:
    st.subheader("🗄️ SQLite Database")
    st.caption(
        "V20 stores users, approvals, audit events, role decisions, login events, and processing runs in one local SQLite database while keeping CSV/JSON downloads for convenience."
    )

    output_folder = Path(config.get("output", {}).get("folder", "data/output"))
    db_cfg = config.get("database", {})
    db_path = Path(db_cfg.get("path") or output_folder / "automation_agent.db")
    db = DatabaseManager(db_path)

    st.write(f"**Database file:** `{db.db_path}`")
    counts = db.table_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Users", counts.get("users", 0))
    c2.metric("Audit events", counts.get("audit_events", 0))
    c3.metric("Approvals", counts.get("approval_records", 0))
    c4.metric("Processing runs", counts.get("processed_files", 0))

    table = st.selectbox(
        "Choose database table",
        [
            "processed_files",
            "audit_events",
            "approval_records",
            "role_permission_decisions",
            "users",
            "auth_login_events",
            "auth_user_management_events",
        ],
    )
    limit = st.slider("Rows to show", min_value=50, max_value=1000, value=200, step=50)
    try:
        table_df = db.read_table(table, limit=limit)
        if table_df.empty:
            st.info("No records in this table yet.")
        else:
            st.dataframe(table_df, use_container_width=True, hide_index=True)
            st.download_button(
                f"Download {table} CSV",
                data=table_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{table}.csv",
                mime="text/csv",
            )
    except Exception as error:
        st.error(f"Could not read database table: {error}")

    with st.expander("Import existing JSONL logs into SQLite", expanded=False):
        st.caption(
            "Use this once if you already created JSONL logs before opening V20. New events are written to SQLite automatically."
        )
        if current_user.get("role") != "admin":
            st.info("Only admins can import log files into the database.")
        else:
            if st.button("Import existing JSONL logs"):
                imports = {}
                imports["audit_events"] = db.import_jsonl(
                    output_folder / "automation_audit_log.jsonl", "audit"
                )
                imports["approval_records"] = db.import_jsonl(
                    output_folder / "approval_history.jsonl", "approval"
                )
                imports["role_permission_decisions"] = db.import_jsonl(
                    output_folder / "role_permission_decisions.jsonl", "role_decision"
                )
                imports["auth_login_events"] = db.import_jsonl(
                    output_folder / "auth_login_events.jsonl", "login"
                )
                imports["auth_user_management_events"] = db.import_jsonl(
                    output_folder / "auth_user_management_events.jsonl", "user_management"
                )
                st.success("Import finished.")
                st.json(imports)

    st.warning(
        "Keep automation_agent.db private. It may contain customer data, approval records, and local user metadata."
    )


def show_settings_admin(config: dict, current_user: dict) -> None:
    """Admin settings panel for validation, integration, and safety settings."""
    st.subheader("⚙️ Settings / Admin Panel")
    st.caption(
        "V20 lets admins edit validation rules, CRM settings, QuickBooks settings, and safety settings from the dashboard instead of editing config.yaml manually."
    )

    output_folder = config.get("output", {}).get("folder", "data/output")
    manager = ConfigManager(PROJECT_ROOT / "config.yaml", output_folder)

    role = current_user.get("role", "viewer")
    permissions = (
        config.get("approval", {})
        .get("role_based", {})
        .get("roles", {})
        .get(role, {})
        .get("permissions", {})
    )
    can_manage_settings = bool(permissions.get("manage_settings")) or role == "admin"

    if not can_manage_settings:
        st.info(
            "Only users with the admin/manage_settings permission can change settings. You can still view the current configuration below."
        )
        st.json(config)
        return

    st.success(
        f"Admin settings access granted for **{current_user.get('display_name', current_user.get('username', 'admin'))}**."
    )
    editable_config = manager.load()

    with st.form("settings_admin_form"):
        st.write("### Validation rules")
        validation = editable_config.setdefault("validation", {})
        required_columns = st.text_input(
            "Required columns comma-separated",
            value=", ".join(validation.get("required_columns", [])),
            help="Rows missing these columns/values will be rejected. Example: email",
        )
        identity_group = st.text_input(
            "At least one identity field comma-separated",
            value=", ".join(validation.get("at_least_one_required_group", [])),
            help="At least one of these fields must exist. Example: first_name, last_name, company",
        )
        duplicate_keys = st.text_input(
            "Duplicate key columns comma-separated",
            value=", ".join(validation.get("duplicate_key_columns", [])),
            help="Usually email for contacts.",
        )
        allowed_countries = st.text_area(
            "Allowed countries one per line optional",
            value="\n".join(validation.get("allowed_countries", [])),
            height=120,
        )
        max_missing = st.slider(
            "Missing percentage warning threshold",
            min_value=0,
            max_value=100,
            value=int(validation.get("max_missing_percentage_warning", 20)),
            step=5,
        )

        st.write("### Cleaning rules")
        cleaning = editable_config.setdefault("cleaning", {})
        c1, c2, c3 = st.columns(3)
        lowercase_email = c1.checkbox(
            "Lowercase emails", value=bool(cleaning.get("lowercase_email", True))
        )
        normalize_phone = c2.checkbox(
            "Normalize phone numbers", value=bool(cleaning.get("normalize_phone", True))
        )
        title_case_names = c3.checkbox(
            "Title-case names", value=bool(cleaning.get("title_case_names", True))
        )
        title_case_company = st.checkbox(
            "Title-case company names", value=bool(cleaning.get("title_case_company", False))
        )

        st.write("### HubSpot settings")
        integrations = editable_config.setdefault("integrations", {})
        hubspot = integrations.setdefault("hubspot", {})
        h1, h2, h3 = st.columns(3)
        hubspot_enabled = h1.checkbox("HubSpot enabled", value=bool(hubspot.get("enabled", False)))
        hubspot_dry_run = h2.checkbox("HubSpot dry-run", value=bool(hubspot.get("dry_run", True)))
        check_existing = h3.checkbox(
            "Check existing contacts before sync",
            value=bool(hubspot.get("check_existing_before_sync", True)),
        )
        hubspot_operation = st.selectbox(
            "HubSpot operation",
            ["plan", "upsert", "create"],
            index=(
                ["plan", "upsert", "create"].index(str(hubspot.get("operation", "plan")))
                if str(hubspot.get("operation", "plan")) in ["plan", "upsert", "create"]
                else 0
            ),
        )
        hubspot_batch_size = st.number_input(
            "HubSpot batch size",
            min_value=1,
            max_value=500,
            value=int(hubspot.get("batch_size", 100)),
            step=10,
        )

        st.write("### QuickBooks settings")
        quickbooks = integrations.setdefault("quickbooks", {})
        q1, q2, q3 = st.columns(3)
        quickbooks_enabled = q1.checkbox(
            "QuickBooks enabled", value=bool(quickbooks.get("enabled", True))
        )
        quickbooks_dry_run = q2.checkbox(
            "QuickBooks dry-run", value=bool(quickbooks.get("dry_run", True))
        )
        qb_environment = q3.selectbox(
            "QuickBooks environment",
            ["sandbox", "production"],
            index=0 if str(quickbooks.get("environment", "sandbox")) != "production" else 1,
        )
        qb_mode = st.selectbox(
            "QuickBooks mode",
            ["export_only", "api_sync"],
            index=0 if str(quickbooks.get("mode", "export_only")) != "api_sync" else 1,
        )
        allow_production_sync = st.checkbox(
            "Allow production sync",
            value=bool(quickbooks.get("allow_production_sync", False)),
            help="Keep this off unless you are intentionally ready for production accounting changes.",
        )
        default_item_ref_id = st.text_input(
            "Default QuickBooks ItemRef ID for invoices",
            value=str(quickbooks.get("default_item_ref_id", "")),
            help="Required before invoice API sync can create invoices.",
        )
        enable_customer_lookup = st.checkbox(
            "Enable QuickBooks customer lookup/cache",
            value=bool(quickbooks.get("enable_customer_lookup", True)),
        )

        st.write("### Approval and auth safety")
        approval = editable_config.setdefault("approval", {})
        require_human_approval = st.checkbox(
            "Require human approval", value=bool(approval.get("require_human_approval", True))
        )
        auth = editable_config.setdefault("auth", {})
        login_required = st.checkbox("Require login", value=bool(auth.get("login_required", True)))
        session_timeout = st.number_input(
            "Session timeout minutes",
            min_value=15,
            max_value=1440,
            value=int(auth.get("session_timeout_minutes", 120)),
            step=15,
        )

        reason = st.text_input(
            "Change reason", value="Updated settings from V20 dashboard admin panel"
        )
        submitted = st.form_submit_button("Save settings to config.yaml", type="primary")

    if submitted:

        def split_csv(value: str) -> list[str]:
            return [item.strip() for item in value.split(",") if item.strip()]

        validation["required_columns"] = split_csv(required_columns)
        validation["at_least_one_required_group"] = split_csv(identity_group)
        validation["duplicate_key_columns"] = split_csv(duplicate_keys)
        validation["allowed_countries"] = [
            line.strip().lower() for line in allowed_countries.splitlines() if line.strip()
        ]
        validation["max_missing_percentage_warning"] = int(max_missing)

        cleaning["lowercase_email"] = bool(lowercase_email)
        cleaning["normalize_phone"] = bool(normalize_phone)
        cleaning["title_case_names"] = bool(title_case_names)
        cleaning["title_case_company"] = bool(title_case_company)

        hubspot["enabled"] = bool(hubspot_enabled)
        hubspot["dry_run"] = bool(hubspot_dry_run)
        hubspot["check_existing_before_sync"] = bool(check_existing)
        hubspot["operation"] = hubspot_operation
        hubspot["batch_size"] = int(hubspot_batch_size)
        integrations["crm_enabled"] = bool(hubspot_enabled)

        quickbooks["enabled"] = bool(quickbooks_enabled)
        quickbooks["dry_run"] = bool(quickbooks_dry_run)
        quickbooks["environment"] = qb_environment
        quickbooks["mode"] = qb_mode
        quickbooks["allow_production_sync"] = bool(allow_production_sync)
        quickbooks["default_item_ref_id"] = default_item_ref_id.strip()
        quickbooks["enable_customer_lookup"] = bool(enable_customer_lookup)
        integrations["quickbooks_enabled"] = bool(quickbooks_enabled)

        approval["require_human_approval"] = bool(require_human_approval)
        auth["login_required"] = bool(login_required)
        auth["session_timeout_minutes"] = int(session_timeout)

        actor = current_user.get("username") or current_user.get("display_name") or "admin"
        result = manager.save(editable_config, actor=actor, reason=reason)
        if result.success:
            st.success(result.message)
            st.info(f"Backup created: {result.backup_path}")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(result.message)

    st.write("### Settings change history")
    events = manager.read_events()
    if events:
        events_df = pd.DataFrame(events)
        st.dataframe(events_df.tail(100), use_container_width=True, hide_index=True)
        st.download_button(
            "Download settings change events JSONL",
            data=manager.event_file.read_bytes(),
            file_name="settings_change_events.jsonl",
            mime="application/jsonl",
        )
    else:
        st.info("No settings changes recorded yet.")

    st.write("### Config backups")
    backups = manager.available_backups()
    if backups:
        backup_df = pd.DataFrame([{"backup_file": b.name, "path": str(b)} for b in backups])
        st.dataframe(backup_df, use_container_width=True, hide_index=True)
    else:
        st.info("No config backups yet. A backup is created automatically before every save.")

    with st.expander("View current config.yaml", expanded=False):
        st.code((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"), language="yaml")


def show_scheduled_jobs(config: dict, current_user: dict) -> None:
    st.subheader("⏰ Scheduled Automation Jobs")
    st.caption(
        "Create safe folder-based automation jobs, process new CSV/Excel files, archive successful files, "
        "and keep failed files in an error folder. For real scheduling, call the CLI from Windows Task Scheduler or cron."
    )

    scheduler = ScheduledJobManager(config)
    role = current_user.get("role", "viewer") if current_user else "viewer"
    is_admin = role == "admin"

    s1, s2, s3, s4 = st.columns(4)
    jobs = scheduler.load_jobs()
    due = scheduler.due_jobs()
    s1.metric("Scheduler enabled", "Yes" if scheduler.enabled else "No")
    s2.metric("Jobs", len(jobs))
    s3.metric("Enabled jobs", sum(1 for job in jobs if job.enabled))
    s4.metric("Due now", len(due))

    st.write("### Job list")
    jobs_df = pd.DataFrame([job.__dict__ for job in jobs]) if jobs else pd.DataFrame()
    if jobs_df.empty:
        st.info("No scheduled jobs yet.")
    else:
        st.dataframe(jobs_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download scheduled_jobs.json",
            data=scheduler.jobs_file.read_bytes(),
            file_name="scheduled_jobs.json",
            mime="application/json",
        )

    st.write("### Create or update job")
    if not is_admin:
        st.info("Only admins can create, update, delete, or run scheduled jobs from the dashboard.")
    with st.form("scheduled_job_form"):
        existing_ids = [job.job_id for job in jobs]
        selected_existing = st.selectbox(
            "Load existing job optional", [""] + existing_ids, disabled=not is_admin
        )
        existing = next((job for job in jobs if job.job_id == selected_existing), None)
        job_id = st.text_input(
            "Job ID",
            value=existing.job_id if existing else "daily_file_cleaning",
            disabled=not is_admin,
        )
        name = st.text_input(
            "Job name",
            value=existing.name if existing else "Daily folder cleaning job",
            disabled=not is_admin,
        )
        enabled = st.checkbox(
            "Enabled", value=existing.enabled if existing else False, disabled=not is_admin
        )
        c1, c2, c3 = st.columns(3)
        cadence = c1.selectbox(
            "Cadence",
            ["manual", "hourly", "daily"],
            index=(
                ["manual", "hourly", "daily"].index(existing.cadence)
                if existing and existing.cadence in ["manual", "hourly", "daily"]
                else 2
            ),
            disabled=not is_admin,
        )
        run_time = c2.text_input(
            "Run time HH:MM for daily",
            value=existing.run_time if existing else "09:00",
            disabled=not is_admin,
        )
        max_files = c3.number_input(
            "Max files this run",
            min_value=1,
            max_value=500,
            value=int(config.get("scheduler", {}).get("max_files_per_run", 25)),
            disabled=not is_admin,
        )
        input_folder = st.text_input(
            "Input folder",
            value=existing.input_folder if existing else str(scheduler.default_input_folder),
            disabled=not is_admin,
        )
        archive_folder = st.text_input(
            "Archive folder",
            value=existing.archive_folder if existing else str(scheduler.default_archive_folder),
            disabled=not is_admin,
        )
        error_folder = st.text_input(
            "Error folder",
            value=existing.error_folder if existing else str(scheduler.default_error_folder),
            disabled=not is_admin,
        )
        notes = st.text_area(
            "Notes", value=existing.notes if existing else "", disabled=not is_admin, height=80
        )
        save_job = st.form_submit_button(
            "Save scheduled job", disabled=not is_admin, type="primary"
        )

    if save_job and is_admin:
        try:
            saved = scheduler.upsert_job(
                job_id=job_id.strip(),
                name=name.strip(),
                enabled=enabled,
                input_folder=input_folder.strip(),
                archive_folder=archive_folder.strip(),
                error_folder=error_folder.strip(),
                cadence=cadence,
                run_time=run_time.strip(),
                notes=notes.strip(),
            )
            st.success(f"Saved job: {saved.job_id}")
            st.rerun()
        except Exception as error:
            st.error(f"Could not save scheduled job: {error}")

    st.write("### Run jobs")
    run_col1, run_col2, run_col3 = st.columns(3)
    run_job_id = run_col1.selectbox(
        "Job to run now", existing_ids or [""], disabled=not is_admin or not existing_ids
    )
    if run_col2.button("Run selected job now", disabled=not is_admin or not run_job_id):
        try:
            summary = scheduler.run_job_now(run_job_id, max_files=int(max_files))
            st.success("Scheduled job finished.")
            st.json(summary)
        except Exception as error:
            st.error(f"Scheduled job failed: {error}")
    if run_col3.button("Run all due jobs", disabled=not is_admin):
        try:
            summaries = scheduler.run_due_jobs(max_files_per_job=int(max_files))
            st.success(f"Executed {len(summaries)} due job(s).")
            st.json(summaries)
        except Exception as error:
            st.error(f"Could not run due jobs: {error}")

    if is_admin and existing_ids:
        with st.expander("Danger zone: delete a scheduled job", expanded=False):
            delete_id = st.selectbox("Delete job", existing_ids, key="delete_scheduled_job")
            confirm_delete = st.checkbox(
                "I understand this deletes only the job definition, not processed output files."
            )
            if st.button("Delete scheduled job", disabled=not confirm_delete):
                if scheduler.delete_job(delete_id):
                    st.success(f"Deleted job: {delete_id}")
                    st.rerun()
                else:
                    st.warning("Job was not found.")

    st.write("### Scheduled job events")
    events = scheduler.read_events(limit=300)
    if events:
        events_df = pd.DataFrame(events)
        st.dataframe(events_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download scheduled job events JSONL",
            data=scheduler.events_file.read_bytes(),
            file_name="scheduled_job_events.jsonl",
            mime="application/jsonl",
        )
    else:
        st.info("No scheduled job events yet.")

    st.write("### CLI commands")
    st.code("python main.py --run-scheduled-jobs", language="powershell")
    st.code("python main.py --run-job-now daily_file_cleaning", language="powershell")


def show_email_notifications(config: dict, current_user: dict) -> None:
    st.subheader("📧 Email Notifications")
    st.caption(
        "Send summary emails when scheduled jobs finish, fail, or create rejected rows. "
        "Dry-run mode writes a local preview without sending real email."
    )
    notifier = EmailNotifier(config)
    role = current_user.get("role", "viewer") if current_user else "viewer"
    is_admin = role == "admin"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Enabled", "Yes" if notifier.enabled else "No")
    c2.metric("Dry-run", "Yes" if notifier.dry_run else "No")
    c3.metric("Recipients", len(notifier.recipients))
    c4.metric("SMTP host", notifier.smtp_host or "Not set")

    st.write("### Current notification settings")
    settings = config.get("notifications", {}).get("email", {})
    safe_settings = dict(settings)
    safe_settings["password"] = "Stored only in .env as SMTP_PASSWORD"
    st.json(safe_settings)

    st.write("### Test notification")
    if not is_admin:
        st.info("Only admins can send test notifications from the dashboard.")
    if st.button("Create/send test notification", disabled=not is_admin, type="primary"):
        result = notifier.send_test_email()
        if result.success:
            st.success(result.message)
        else:
            st.error(f"{result.message} {result.error}")
        st.write(f"Preview file: `{result.preview_file}`")
        st.write(f"Events file: `{result.event_file}`")

    st.write("### Latest email preview")
    if notifier.preview_file.exists():
        st.text_area(
            "Preview content", notifier.preview_file.read_text(encoding="utf-8"), height=260
        )
        st.download_button(
            "Download latest email preview",
            data=notifier.preview_file.read_bytes(),
            file_name="latest_email_notification_preview.txt",
            mime="text/plain",
        )
    else:
        st.info("No email preview created yet.")

    st.write("### Notification events")
    events = notifier.read_events(limit=300)
    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
        st.download_button(
            "Download email notification events JSONL",
            data=notifier.event_file.read_bytes(),
            file_name="email_notification_events.jsonl",
            mime="application/jsonl",
        )
    else:
        st.info("No notification events yet.")

    st.write("### CLI test command")
    st.code("python main.py --send-test-notification", language="powershell")


def show_file_versions(config: dict, current_user: dict) -> None:
    st.subheader("📦 File Versions & Rollback")
    st.caption(
        "Every saved processing run is copied into an immutable run folder with a manifest, hashes, row counts, and rollback support."
    )
    manager = FileVersionManager(config)

    c1, c2, c3 = st.columns(3)
    c1.metric("Versioning", "Enabled" if manager.enabled else "Disabled")
    c2.metric("Runs folder", str(manager.runs_folder))
    c3.metric("Index exists", "Yes" if manager.manifest_index_file.exists() else "No")

    runs_df = manager.list_runs(limit=200)
    if runs_df.empty:
        st.info("No versioned runs yet. Process a file first to create a run ID and manifest.")
    else:
        st.write("### Recent runs")
        st.dataframe(runs_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download file version index CSV",
            data=runs_df.to_csv(index=False).encode("utf-8"),
            file_name="file_version_index.csv",
            mime="text/csv",
        )

        run_ids = runs_df["run_id"].dropna().astype(str).tolist()
        selected_run = st.selectbox("Select a run to inspect or restore", run_ids)
        if selected_run:
            try:
                manifest = manager.get_manifest(selected_run)
                st.write("### Selected run manifest")
                st.json(manifest)
                st.download_button(
                    "Download selected manifest JSON",
                    data=json.dumps(manifest, indent=2).encode("utf-8"),
                    file_name=f"{selected_run}_manifest.json",
                    mime="application/json",
                )
            except Exception as error:
                st.error(f"Could not read manifest: {error}")

        if len(run_ids) >= 2:
            st.write("### Compare two runs")
            a = st.selectbox("Run A", run_ids, key="compare_run_a")
            b = st.selectbox("Run B", run_ids, index=1, key="compare_run_b")
            if a and b and a != b:
                try:
                    compare_df = manager.compare_runs(a, b)
                    st.dataframe(compare_df, use_container_width=True, hide_index=True)
                except Exception as error:
                    st.error(f"Could not compare runs: {error}")

        st.write("### Rollback")
        if current_user.get("role") != "admin":
            st.info("Only admin users can restore old output files from a previous run.")
        else:
            st.warning(
                "Rollback copies the selected run's output files back into data/output. It does not delete the run history."
            )
            reason = st.text_input(
                "Rollback reason", value="Restoring reviewed previous output version"
            )
            confirm = st.checkbox(
                "I understand this will overwrite the active output files with the selected run outputs."
            )
            if st.button("Restore selected run", type="primary", disabled=not confirm):
                try:
                    event = manager.rollback_run(
                        selected_run,
                        actor=current_user.get("email") or current_user.get("username", "admin"),
                        reason=reason,
                    )
                    st.success(
                        "Rollback finished. Active output files were restored from the selected run."
                    )
                    st.json(event)
                except Exception as error:
                    st.error(f"Rollback failed: {error}")

    st.write("### Rollback events")
    rollback_df = manager.read_rollback_events(limit=200)
    if rollback_df.empty:
        st.info("No rollback events recorded yet.")
    else:
        st.dataframe(rollback_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download rollback events CSV",
            data=rollback_df.to_csv(index=False).encode("utf-8"),
            file_name="rollback_events.csv",
            mime="text/csv",
        )

    st.write("### CLI commands")
    st.code("python main.py --list-runs", language="powershell")
    st.code(
        'python main.py --rollback-run run_YYYYMMDD_HHMMSS_abc12345 --approved-by "Vladimir Trifonov" --rollback-reason "Restore previous clean output"',
        language="powershell",
    )


def show_system_backups(config: dict, current_user: dict) -> None:
    st.subheader("🧳 System Backup / Export / Import")
    st.caption(
        "Create a portable ZIP backup of local system state: settings, users, SQLite database, approvals, audit logs, scheduled jobs, version history, and generated state files. Secrets in .env are excluded by default."
    )
    manager = SystemBackupManager(config, PROJECT_ROOT)
    backup_cfg = config.get("system_backup", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Backup", "Enabled" if backup_cfg.get("enabled", True) else "Disabled")
    c2.metric("Database", "Included" if backup_cfg.get("include_database", True) else "Excluded")
    c3.metric(
        "Versioned runs",
        "Included" if backup_cfg.get("include_versioned_runs", True) else "Excluded",
    )
    c4.metric(".env secrets", "Included" if backup_cfg.get("include_env", False) else "Excluded")

    st.write("### Create backup")
    if current_user.get("role") != "admin":
        st.info("Only admin users can create or restore full system-state backups.")
    else:
        note = st.text_input("Backup note", value="Manual dashboard backup")
        if st.button("Create system backup", type="primary"):
            try:
                result = manager.create_backup(
                    created_by=current_user.get("email") or current_user.get("username", "admin"),
                    note=note,
                )
                st.success(f"System backup created: {result.backup_id}")
                st.json(result.__dict__)
                with open(result.backup_file, "rb") as file:
                    st.download_button(
                        "Download backup ZIP",
                        data=file.read(),
                        file_name=Path(result.backup_file).name,
                        mime="application/zip",
                    )
            except Exception as error:
                st.error(f"Backup failed: {error}")

    st.write("### Available backups")
    backups = manager.list_backups()
    if not backups:
        st.info("No backups found yet.")
    else:
        backup_rows = [
            {
                "backup_id": b.get("backup_id"),
                "created_at_utc": b.get("created_at_utc"),
                "created_by": b.get("created_by"),
                "files": b.get("included_file_count"),
                "size_bytes": b.get("backup_size_bytes"),
                "note": b.get("note", ""),
            }
            for b in backups
        ]
        backups_df = pd.DataFrame(backup_rows)
        st.dataframe(backups_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download backup index CSV",
            data=backups_df.to_csv(index=False).encode("utf-8"),
            file_name="system_backup_index.csv",
            mime="text/csv",
        )

        selected_backup = st.selectbox(
            "Select a backup", backups_df["backup_id"].astype(str).tolist()
        )
        selected_record = next((b for b in backups if b.get("backup_id") == selected_backup), None)
        if selected_record:
            st.write("### Backup manifest")
            st.json(selected_record)
            backup_file = manager.backups_folder / f"{selected_backup}.zip"
            if backup_file.exists():
                with backup_file.open("rb") as file:
                    st.download_button(
                        "Download selected backup ZIP",
                        data=file.read(),
                        file_name=backup_file.name,
                        mime="application/zip",
                    )

        st.write("### Restore / import selected backup")
        st.warning(
            "Restore can overwrite config, database, users, outputs, and state files. Use preview first. Keep .env/API secrets backed up separately."
        )
        restore_reason = st.text_input(
            "Restore reason", value="Restore system state from selected backup"
        )
        if st.button("Preview restore selected backup"):
            try:
                event = manager.restore_backup(
                    selected_backup,
                    restored_by=current_user.get("email") or current_user.get("username", "admin"),
                    reason=restore_reason,
                    dry_run=True,
                )
                st.info("Restore preview created. No files were overwritten.")
                st.json(event)
            except Exception as error:
                st.error(f"Restore preview failed: {error}")

        apply_confirm = st.checkbox("I understand this restore can overwrite local state files.")
        if st.button(
            "Apply restore selected backup",
            type="primary",
            disabled=(current_user.get("role") != "admin" or not apply_confirm),
        ):
            try:
                event = manager.restore_backup(
                    selected_backup,
                    restored_by=current_user.get("email") or current_user.get("username", "admin"),
                    reason=restore_reason,
                    dry_run=False,
                )
                st.success(
                    "System restore applied. Restart Streamlit to reload restored settings/users."
                )
                st.json(event)
            except Exception as error:
                st.error(f"Restore failed: {error}")

    st.write("### Restore events")
    if manager.restore_events_file.exists():
        rows = []
        for line in manager.restore_events_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    rows.append(
                        {
                            k: rec.get(k)
                            for k in [
                                "restore_id",
                                "backup_file",
                                "restored_at_utc",
                                "restored_by",
                                "dry_run",
                                "file_count",
                                "reason",
                            ]
                        }
                    )
                except json.JSONDecodeError:
                    pass
        if rows:
            restore_df = pd.DataFrame(rows)
            st.dataframe(restore_df, use_container_width=True, hide_index=True)
        else:
            st.info("No restore events yet.")
    else:
        st.info("No restore events yet.")

    st.write("### CLI commands")
    st.code(
        'python main.py --create-system-backup --approved-by "Vladimir Trifonov" --backup-note "Before moving laptop"',
        language="powershell",
    )
    st.code("python main.py --list-system-backups", language="powershell")
    st.code(
        'python main.py --restore-system-backup backup_YYYYMMDD_HHMMSS --approved-by "Vladimir Trifonov" --backup-note "Preview restore"',
        language="powershell",
    )
    st.code(
        'python main.py --restore-system-backup backup_YYYYMMDD_HHMMSS --restore-apply --approved-by "Vladimir Trifonov" --backup-note "Apply restore"',
        language="powershell",
    )


def main() -> None:
    config = load_config()
    current_user = render_auth_gate(config)

    st.title("🤖 Business Automation Agent V24")
    st.write(
        "Upload a CSV or Excel file, clean and validate customer/contact data, "
        "review CRM-ready rows, prepare HubSpot and QuickBooks plans, and manage login users/roles from the dashboard."
    )

    with st.sidebar:
        st.header("Validation Settings")
        validation = config.get("validation", {})
        st.write("**Required columns:**")
        st.code(", ".join(validation.get("required_columns", [])) or "None")
        st.write("**Duplicate check columns:**")
        st.code(", ".join(validation.get("duplicate_key_columns", [])) or "None")
        st.write("**Identity rule:**")
        st.code("At least one of: " + ", ".join(validation.get("at_least_one_required_group", [])))
        st.divider()
        st.warning(
            "HubSpot and QuickBooks are safe by default. V24 adds GitHub Actions CI/CD, automated tests, security checks, Docker build checks, and local CI scripts."
        )

    (
        auth_tab,
        users_tab,
        settings_tab,
        db_tab,
        versions_tab,
        backup_tab,
        scheduler_tab,
        notifications_tab,
        oauth_tab,
        roles_tab,
        processing_tab,
    ) = st.tabs(
        [
            "Authentication",
            "User Management",
            "Settings Admin",
            "Database",
            "File Versions",
            "System Backups",
            "Scheduled Jobs",
            "Email Notifications",
            "QuickBooks OAuth Setup",
            "Role Rules",
            "Data Processing",
        ]
    )

    with auth_tab:
        show_auth_admin(config, current_user)

    with users_tab:
        show_user_management(config, current_user)

    with settings_tab:
        show_settings_admin(config, current_user)

    with db_tab:
        show_database_admin(config, current_user)

    with versions_tab:
        show_file_versions(config, current_user)

    with backup_tab:
        show_system_backups(config, current_user)

    with scheduler_tab:
        show_scheduled_jobs(config, current_user)

    with notifications_tab:
        show_email_notifications(config, current_user)

    with oauth_tab:
        show_quickbooks_oauth_setup(config)

    with roles_tab:
        show_role_rules(config)

    with processing_tab:
        st.subheader("Data processing")

        uploaded_file = st.file_uploader(
            "Upload your contact/customer file",
            type=["csv", "xlsx", "xls"],
            help="Use fields like first_name, last_name, email, phone, company, city, country. For invoices add invoice_number and amount.",
        )

    if uploaded_file is None:
        st.info(
            "Upload a file to start. You can test with data/input/sample_contacts.csv or "
            "data/input/sample_quickbooks_contacts_invoices.csv from the project folder."
        )
        return

    try:
        raw_df = read_uploaded_file(uploaded_file)
    except Exception as error:
        st.error(f"Could not read file: {error}")
        return

    st.subheader("Raw uploaded data preview")
    st.dataframe(raw_df.head(20), use_container_width=True, hide_index=True)

    if st.button("Clean, Validate, and Prepare Exports", type="primary"):
        try:
            result = process_dataframe(
                raw_df,
                config=config,
                source_name=uploaded_file.name,
                save_outputs=True,
            )
        except Exception as error:
            st.error(f"Processing failed: {error}")
            return

        st.success("Processing finished successfully.")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Original rows", result.original_rows)
        col2.metric("CRM-ready rows", len(result.crm_ready_rows))
        col3.metric("Rejected rows", len(result.rejected_rows))
        col4.metric("Duplicates removed", len(result.duplicate_rows))

        if result.versioned_run:
            st.info(f"Versioned run created: `{result.versioned_run.run_id}`")

        (
            tab_clean,
            tab_rejected,
            tab_duplicates,
            tab_report,
            tab_hubspot,
            tab_quickbooks,
            tab_audit,
            tab_approval_history,
            tab_role_decisions,
            tab_download,
        ) = st.tabs(
            [
                "CRM-ready",
                "Rejected rows",
                "Duplicates",
                "Report",
                "HubSpot Sync Plan",
                "QuickBooks API Plan",
                "Audit Log",
                "Approval History",
                "Role Decisions",
                "Downloads",
            ]
        )

        with tab_clean:
            show_dataframe_section(
                "CRM-ready contacts",
                result.crm_ready_rows,
                "These rows passed validation and duplicate checks.",
            )

        with tab_rejected:
            show_dataframe_section(
                "Rejected rows",
                result.rejected_rows,
                "These rows need manual fixing before CRM or accounting upload.",
            )

        with tab_duplicates:
            show_dataframe_section(
                "Duplicates removed",
                result.duplicate_rows,
                "These rows were detected as duplicates based on configured key columns.",
            )

        with tab_report:
            st.subheader("Processing report")
            st.text(result.report_text)

        with tab_hubspot:
            st.subheader("HubSpot sync plan")
            st.caption(
                "This prepares contacts to create, update, or review. By default, it does not send data."
            )
            try:
                hubspot_connector = HubSpotConnector(config)
                hubspot_payload = hubspot_connector.build_payload(
                    result.crm_ready_rows, operation="upsert"
                )
                hubspot_plan = hubspot_connector.build_sync_plan(result.crm_ready_rows)
                hubspot_connector.save_payload_preview(hubspot_payload)
                hubspot_connector.save_sync_plan(hubspot_plan)

                summary = hubspot_plan.get("summary", {})
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Existing found", summary.get("existing_contacts_found", 0))
                c2.metric("To create", summary.get("contacts_to_create", 0))
                c3.metric("To update", summary.get("contacts_to_update", 0))
                c4.metric("Unknown / upsert", summary.get("contacts_with_unknown_status", 0))

                st.info(summary.get("lookup_message", "Sync plan created."))
                st.json(hubspot_plan)
                st.download_button(
                    "Download HubSpot sync plan JSON",
                    data=json.dumps(hubspot_plan, indent=2).encode("utf-8"),
                    file_name="hubspot_sync_plan.json",
                    mime="application/json",
                )
                st.download_button(
                    "Download HubSpot upsert payload JSON",
                    data=json.dumps(hubspot_payload, indent=2).encode("utf-8"),
                    file_name="hubspot_payload_preview.json",
                    mime="application/json",
                )
            except Exception as error:
                st.error(f"Could not create HubSpot sync plan: {error}")

        with tab_quickbooks:
            st.subheader("QuickBooks-ready export")
            st.caption(
                "V20 creates reviewable customer/invoice files, CustomerRef cache, QuickBooks API payload previews, and a protected sandbox sync flow. Approval role comes from the signed-in user."
            )
            try:
                qb_connector = QuickBooksConnector(config)
                customers_df = qb_connector.build_customers_export(result.crm_ready_rows)
                invoices_df, invoice_messages = qb_connector.build_invoices_export(
                    result.crm_ready_rows
                )
                customer_ref_cache, lookup_messages = qb_connector.build_customer_ref_cache(
                    customers_df
                )
                customer_payloads = qb_connector.build_customer_payloads(customers_df)
                invoice_payloads, unresolved_refs = qb_connector.build_invoice_payloads(
                    invoices_df, customer_ref_cache
                )
                api_plan = qb_connector.build_api_sync_plan(
                    customers_df,
                    invoices_df,
                    customer_payloads,
                    invoice_payloads,
                    customer_ref_cache,
                    unresolved_refs,
                )

                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Customer rows", len(customers_df))
                q2.metric("Invoice rows", len(invoices_df))
                q3.metric("CustomerRef cache", len(customer_ref_cache))
                q4.metric("Unresolved refs", len(unresolved_refs))

                st.write("**OAuth authorization URL for sandbox setup:**")
                st.code(api_plan.get("oauth", {}).get("authorization_url", ""))
                if api_plan.get("blocking_reasons"):
                    st.warning("Real sync is blocked until these items are fixed:")
                    for reason in api_plan.get("blocking_reasons", []):
                        st.write(f"- {reason}")

                for message in invoice_messages + lookup_messages:
                    st.info(message)

                if unresolved_refs:
                    st.warning(
                        "Some invoices do not have a resolved QuickBooks CustomerRef yet. Create or look up the customers first, then rerun the plan."
                    )
                    st.json(unresolved_refs)

                show_dataframe_section(
                    "QuickBooks customers",
                    customers_df,
                    "Customer export fields mapped toward QuickBooks customer data.",
                )
                show_dataframe_section(
                    "QuickBooks invoices",
                    invoices_df,
                    "Invoice export fields. This table is empty when invoice_number or amount is missing.",
                )

                st.subheader("QuickBooks API sync plan")
                st.json(api_plan)
                st.subheader("Protected QuickBooks sandbox sync")
                st.caption(
                    "This button calls the protected sync flow only after you review the data. "
                    "The connector creates customers first, updates the CustomerRef cache, then creates invoices only when every invoice has a CustomerRef."
                )
                ready_customers = api_plan.get("ready_for_customer_api_sync", False)
                ready_invoices = api_plan.get("ready_for_invoice_api_sync", False)
                if not ready_customers:
                    st.warning(
                        "Customer API sync is not ready yet. Check the blocking reasons above."
                    )
                elif invoices_df.empty:
                    st.info(
                        "Customer sync is ready. No invoice rows were found, so only customers would be created."
                    )
                elif not ready_invoices:
                    st.warning(
                        "Invoice sync is not ready yet. Customers can be created first, but invoices stay blocked until CustomerRefs and item settings are resolved."
                    )

                st.subheader("Approval before sync")
                role_guard = RoleBasedApproval(
                    config, config.get("output", {}).get("folder", "data/output")
                )
                approver_name = (
                    current_user.get("display_name")
                    or current_user.get("username")
                    or "Streamlit user"
                )
                approver_role = current_user.get("role", "viewer")
                st.info(
                    f"Approval identity is taken from login: **{approver_name}** with role **{approver_role}**."
                )
                approval_note = st.text_area(
                    "Approval note optional",
                    placeholder="Example: Reviewed customer/invoice rows and approved sandbox sync.",
                    height=80,
                )
                decision = role_guard.evaluate(
                    approved_by=approver_name,
                    role=approver_role,
                    scope="quickbooks_sandbox_sync",
                    system="quickbooks",
                    environment=qb_connector.environment,
                    dry_run=qb_connector.dry_run,
                )
                if decision.allowed:
                    st.success(decision.message)
                else:
                    st.error(decision.message)
                confirm_review = st.checkbox(
                    "I reviewed the CRM-ready rows, QuickBooks payloads, and sync plan."
                )
                confirm_sandbox = st.checkbox(
                    "I understand this can create records in my QuickBooks sandbox company if config is api_sync and dry_run is false."
                )
                sync_disabled = not (
                    confirm_review
                    and confirm_sandbox
                    and str(approver_name).strip()
                    and decision.allowed
                )
                if st.button(
                    "Run protected QuickBooks sandbox sync", type="primary", disabled=sync_disabled
                ):
                    try:
                        approval_history = ApprovalHistory(
                            config.get("output", {}).get("folder", "data/output")
                        )
                        approval_record = approval_history.record(
                            approved_by=approver_name,
                            approver_role=decision.role,
                            permission_result="allowed_by_role",
                            approval_status="approved",
                            approval_scope="quickbooks_sandbox_sync",
                            source_name=uploaded_file.name,
                            output_file=result.output_paths.get("clean", ""),
                            output_dataframe=result.crm_ready_rows,
                            original_rows=result.original_rows,
                            crm_ready_rows=len(result.crm_ready_rows),
                            rejected_rows=len(result.rejected_rows),
                            duplicate_rows=len(result.duplicate_rows),
                            project_name=config.get("project", {}).get(
                                "name", "Business Automation Agent"
                            ),
                            project_version=str(config.get("project", {}).get("version", "")),
                            note=approval_note,
                        )
                        st.success(f"Approval recorded: {approval_record.approval_id}")
                        sync_result = qb_connector.sync_customers(result.crm_ready_rows)
                        if sync_result.success:
                            st.success("Protected QuickBooks sync flow finished.")
                        else:
                            st.error("Protected QuickBooks sync flow finished with errors.")
                        st.write("**Sync result summary:**")
                        st.json(
                            {
                                "success": sync_result.success,
                                "dry_run": sync_result.dry_run,
                                "attempted_customers": sync_result.attempted_customers,
                                "attempted_invoices": sync_result.attempted_invoices,
                                "created_customers": sync_result.created_customers,
                                "created_invoices": sync_result.created_invoices,
                                "messages": sync_result.messages,
                                "errors": sync_result.errors,
                            }
                        )
                        if "quickbooks_api_sync_result" in sync_result.output_paths:
                            st.info(
                                f"Sync result saved: {sync_result.output_paths['quickbooks_api_sync_result']}"
                            )
                    except Exception as error:
                        st.error(f"Protected QuickBooks sync failed: {error}")

                st.subheader("Payload previews")
                with st.expander("Customer payload preview"):
                    st.json(customer_payloads)
                with st.expander("Invoice payload preview"):
                    st.json(invoice_payloads)
                with st.expander("CustomerRef cache"):
                    st.json(customer_ref_cache)
                with st.expander("Unresolved CustomerRefs"):
                    st.json(unresolved_refs)

                st.download_button(
                    "Download QuickBooks customers CSV",
                    data=dataframe_to_csv_bytes(customers_df),
                    file_name="quickbooks_customers_ready.csv",
                    mime="text/csv",
                )
                st.download_button(
                    "Download QuickBooks invoices CSV",
                    data=dataframe_to_csv_bytes(invoices_df),
                    file_name="quickbooks_invoices_ready.csv",
                    mime="text/csv",
                )
                st.download_button(
                    "Download QuickBooks Excel workbook",
                    data=dataframe_pair_to_excel_bytes(customers_df, invoices_df),
                    file_name="quickbooks_ready_export.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                st.download_button(
                    "Download QuickBooks API sync plan JSON",
                    data=json.dumps(api_plan, indent=2).encode("utf-8"),
                    file_name="quickbooks_api_sync_plan.json",
                    mime="application/json",
                )
                st.download_button(
                    "Download QuickBooks customer payload JSON",
                    data=json.dumps(customer_payloads, indent=2).encode("utf-8"),
                    file_name="quickbooks_customer_payload_preview.json",
                    mime="application/json",
                )
                st.download_button(
                    "Download QuickBooks invoice payload JSON",
                    data=json.dumps(invoice_payloads, indent=2).encode("utf-8"),
                    file_name="quickbooks_invoice_payload_preview.json",
                    mime="application/json",
                )
                st.download_button(
                    "Download QuickBooks CustomerRef cache JSON",
                    data=json.dumps(customer_ref_cache, indent=2).encode("utf-8"),
                    file_name="quickbooks_customer_ref_cache.json",
                    mime="application/json",
                )
                st.download_button(
                    "Download unresolved CustomerRefs JSON",
                    data=json.dumps(unresolved_refs, indent=2).encode("utf-8"),
                    file_name="quickbooks_unresolved_customer_refs.json",
                    mime="application/json",
                )
            except Exception as error:
                st.error(f"Could not prepare QuickBooks exports: {error}")

        with tab_audit:
            st.subheader("Automation audit log")
            st.caption(
                "Every planned, skipped, created, updated/upserted, or failed CRM/QuickBooks action is stored here for review."
            )
            try:
                audit_logger = AuditLogger(config.get("output", {}).get("folder", "data/output"))
                audit_df = audit_logger.read_as_dataframe()
                if audit_df.empty:
                    st.info(
                        "No audit events yet. Run the HubSpot or QuickBooks planning/sync flow first."
                    )
                else:
                    st.dataframe(audit_df.tail(200), use_container_width=True, hide_index=True)
                    a1, a2, a3 = st.columns(3)
                    a1.metric("Audit events", len(audit_df))
                    a2.metric(
                        "Systems", audit_df["system"].nunique() if "system" in audit_df else 0
                    )
                    a3.metric(
                        "Failures",
                        int((audit_df["status"] == "failed").sum()) if "status" in audit_df else 0,
                    )
                    st.download_button(
                        "Download audit log CSV",
                        data=audit_df.to_csv(index=False).encode("utf-8"),
                        file_name="automation_audit_log.csv",
                        mime="text/csv",
                    )
                    if audit_logger.jsonl_path.exists():
                        st.download_button(
                            "Download audit log JSONL",
                            data=audit_logger.jsonl_path.read_bytes(),
                            file_name="automation_audit_log.jsonl",
                            mime="application/jsonl",
                        )
            except Exception as error:
                st.error(f"Could not load audit log: {error}")

        with tab_approval_history:
            st.subheader("Approval history")
            st.caption(
                "Records who approved a sync, when it was approved, and exactly which processed file/version was approved."
            )
            try:
                approval_history = ApprovalHistory(
                    config.get("output", {}).get("folder", "data/output")
                )
                approval_df = approval_history.read_as_dataframe()
                if approval_df.empty:
                    st.info(
                        "No approvals recorded yet. Use the approval fields in the QuickBooks sync section or run the CLI approval flow."
                    )
                else:
                    st.dataframe(approval_df.tail(200), use_container_width=True, hide_index=True)
                    h1, h2, h3 = st.columns(3)
                    h1.metric("Approval records", len(approval_df))
                    h2.metric(
                        "Approved",
                        (
                            int(
                                (
                                    approval_df["approval_status"]
                                    .astype(str)
                                    .str.contains("approved")
                                ).sum()
                            )
                            if "approval_status" in approval_df
                            else 0
                        ),
                    )
                    h3.metric(
                        "Rejected",
                        (
                            int((approval_df["approval_status"] == "rejected").sum())
                            if "approval_status" in approval_df
                            else 0
                        ),
                    )
                    st.download_button(
                        "Download approval history CSV",
                        data=approval_df.to_csv(index=False).encode("utf-8"),
                        file_name="approval_history.csv",
                        mime="text/csv",
                    )
                    if approval_history.jsonl_path.exists():
                        st.download_button(
                            "Download approval history JSONL",
                            data=approval_history.jsonl_path.read_bytes(),
                            file_name="approval_history.jsonl",
                            mime="application/jsonl",
                        )
                    latest_manifest = (
                        approval_history.output_folder / "latest_approval_manifest.json"
                    )
                    if latest_manifest.exists():
                        st.download_button(
                            "Download latest approval manifest JSON",
                            data=latest_manifest.read_bytes(),
                            file_name="latest_approval_manifest.json",
                            mime="application/json",
                        )
            except Exception as error:
                st.error(f"Could not load approval history: {error}")

        with tab_role_decisions:
            st.subheader("Role permission decisions")
            st.caption("Every role permission check is written to role_permission_decisions.jsonl.")
            decision_path = Path(
                config.get("output", {}).get("folder", "data/output")
            ) / config.get("approval", {}).get("role_based", {}).get(
                "permission_decision_file", "role_permission_decisions.jsonl"
            )
            if decision_path.exists():
                rows = [
                    json.loads(line)
                    for line in decision_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                decisions_df = pd.DataFrame(rows)
                st.dataframe(decisions_df.tail(200), use_container_width=True, hide_index=True)
                st.download_button(
                    "Download role decisions JSONL",
                    data=decision_path.read_bytes(),
                    file_name="role_permission_decisions.jsonl",
                    mime="application/jsonl",
                )
            else:
                st.info("No role permission decisions recorded yet.")

        with tab_download:
            st.subheader("Download output files")
            st.download_button(
                "Download CRM-ready CSV",
                data=dataframe_to_csv_bytes(result.crm_ready_rows),
                file_name="crm_ready_contacts.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download rejected rows CSV",
                data=dataframe_to_csv_bytes(result.rejected_rows),
                file_name="rejected_rows.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download duplicates CSV",
                data=dataframe_to_csv_bytes(result.duplicate_rows),
                file_name="duplicates_removed.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download report TXT",
                data=result.report_text.encode("utf-8"),
                file_name="report.txt",
                mime="text/plain",
            )
            st.download_button(
                "Download CRM-ready Excel",
                data=dataframe_to_excel_bytes(result.crm_ready_rows, sheet_name="crm_ready"),
                file_name="crm_ready_contacts.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.info(
            "Human approval step: review CRM-ready data, HubSpot plan, and QuickBooks exports before enabling any real sync."
        )


if __name__ == "__main__":
    main()
