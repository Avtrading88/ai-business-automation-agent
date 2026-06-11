from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from automation_agent.core.database import DatabaseManager


@dataclass
class AuthUser:
    username: str
    display_name: str
    email: str
    role: str
    active: bool = True


class AuthManager:
    """Small local authentication + user-management manager for the Streamlit MVP.

    V18 keeps users in a local JSON store so an admin can add, deactivate,
    reactivate, and update users from the dashboard without editing config.yaml.
    For production, replace this with SSO/OAuth such as Google Workspace, Azure AD,
    Auth0, Okta, or another identity provider.
    """

    def __init__(self, config: dict[str, Any], output_folder: str | Path = "data/output") -> None:
        self.config = config
        self.auth_config = config.get("auth", {})
        self.enabled = bool(self.auth_config.get("enabled", True))
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.login_events_file = self.output_folder / self.auth_config.get(
            "login_events_file", "auth_login_events.jsonl"
        )
        self.user_store_file = self.output_folder / self.auth_config.get(
            "user_store_file", "auth_users.json"
        )
        self.user_management_events_file = self.output_folder / self.auth_config.get(
            "user_management_events_file", "auth_user_management_events.jsonl"
        )
        self.config_users = self.auth_config.get("users", [])
        self.db = DatabaseManager(self.output_folder / "automation_agent.db")
        self.users = self.load_users()
        self._sync_users_to_db()

    @staticmethod
    def hash_password(password: str, *, iterations: int = 260_000) -> str:
        if not password:
            raise ValueError("Password cannot be empty.")
        salt = os.urandom(16).hex()
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
        ).hex()
        return f"pbkdf2_sha256${iterations}${salt}${digest}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        try:
            algorithm, iterations_text, salt_hex, expected_digest = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(iterations_text)
            actual_digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
            ).hex()
            return hmac.compare_digest(actual_digest, expected_digest)
        except Exception:
            return False

    def load_users(self) -> list[dict[str, Any]]:
        """Load managed users from disk, falling back to demo users from config.yaml."""
        if self.user_store_file.exists():
            try:
                data = json.loads(self.user_store_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        return [dict(user) for user in self.config_users]

    def save_users(self) -> None:
        self.user_store_file.write_text(
            json.dumps(self.users, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._sync_users_to_db()

    def _sync_users_to_db(self) -> None:
        try:
            self.db.replace_users(self.users)
        except Exception:
            # The JSON user store remains the source of truth if SQLite is temporarily unavailable.
            pass

    def initialize_user_store_if_missing(self, *, actor: str = "system") -> bool:
        if self.user_store_file.exists():
            return False
        self.save_users()
        self.record_user_management_event(
            actor=actor,
            action="initialize_user_store",
            username="*",
            success=True,
            message="Initialized auth_users.json from config.yaml users.",
        )
        return True

    def allowed_roles(self) -> list[str]:
        roles = self.config.get("approval", {}).get("role_based", {}).get("roles", {})
        return list(roles.keys()) or ["viewer", "reviewer", "approver", "admin"]

    def get_user(self, username: str) -> dict[str, Any] | None:
        username_normalized = (username or "").strip().lower()
        for user in self.users:
            if str(user.get("username", "")).strip().lower() == username_normalized:
                return user
        return None

    def authenticate(self, username: str, password: str) -> AuthUser | None:
        # Reload from disk each login attempt so user changes take effect immediately.
        self.users = self.load_users()
        user = self.get_user(username)
        if not user:
            self.record_login_event(
                username=username, success=False, role="", message="Unknown username"
            )
            return None
        if not user.get("active", True):
            self.record_login_event(
                username=username, success=False, role=user.get("role", ""), message="Inactive user"
            )
            return None
        if not self.verify_password(password, user.get("password_hash", "")):
            self.record_login_event(
                username=username,
                success=False,
                role=user.get("role", ""),
                message="Invalid password",
            )
            return None

        auth_user = AuthUser(
            username=str(user.get("username", "")),
            display_name=str(user.get("display_name", user.get("username", ""))),
            email=str(user.get("email", "")),
            role=str(user.get("role", "viewer")),
            active=bool(user.get("active", True)),
        )
        self.record_login_event(
            username=auth_user.username,
            success=True,
            role=auth_user.role,
            message="Login successful",
        )
        return auth_user

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        email: str,
        role: str,
        password: str,
        active: bool = True,
        actor: str = "unknown",
    ) -> dict[str, Any]:
        username = (username or "").strip().lower()
        role = (role or "viewer").strip().lower()
        if not username:
            raise ValueError("Username is required.")
        if self.get_user(username):
            raise ValueError(f"User '{username}' already exists.")
        if role not in self.allowed_roles():
            raise ValueError(f"Role '{role}' is not allowed.")
        if not password or len(password) < 8:
            raise ValueError("Password must contain at least 8 characters.")

        user = {
            "username": username,
            "display_name": display_name.strip() or username,
            "email": email.strip(),
            "role": role,
            "active": bool(active),
            "password_hash": self.hash_password(password),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "created_by": actor,
            "updated_by": actor,
        }
        self.users.append(user)
        self.save_users()
        self.record_user_management_event(
            actor=actor,
            action="create_user",
            username=username,
            success=True,
            message=f"Created user with role '{role}'.",
        )
        return user

    def update_user(
        self,
        *,
        username: str,
        display_name: str | None = None,
        email: str | None = None,
        role: str | None = None,
        active: bool | None = None,
        new_password: str | None = None,
        actor: str = "unknown",
    ) -> dict[str, Any]:
        user = self.get_user(username)
        if not user:
            raise ValueError(f"User '{username}' was not found.")

        old_role = user.get("role", "viewer")
        old_active = bool(user.get("active", True))

        if display_name is not None:
            user["display_name"] = display_name.strip() or user.get("username", "")
        if email is not None:
            user["email"] = email.strip()
        if role is not None:
            role = role.strip().lower()
            if role not in self.allowed_roles():
                raise ValueError(f"Role '{role}' is not allowed.")
            user["role"] = role
        if active is not None:
            if (
                old_active
                and active is False
                and old_role == "admin"
                and self.count_active_admins() <= 1
            ):
                raise ValueError("Cannot deactivate the last active admin user.")
            user["active"] = bool(active)
        if new_password:
            if len(new_password) < 8:
                raise ValueError("New password must contain at least 8 characters.")
            user["password_hash"] = self.hash_password(new_password)
            user["password_updated_at_utc"] = datetime.now(timezone.utc).isoformat()

        user["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        user["updated_by"] = actor
        self.save_users()
        self.record_user_management_event(
            actor=actor,
            action="update_user",
            username=username,
            success=True,
            message="Updated user profile, role, active status, or password.",
        )
        return user

    def count_active_admins(self) -> int:
        return sum(
            1
            for user in self.users
            if bool(user.get("active", True)) and str(user.get("role", "")).lower() == "admin"
        )

    def record_login_event(self, *, username: str, success: bool, role: str, message: str) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "username": username,
            "role": role,
            "success": success,
            "message": message,
        }
        with self.login_events_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.db.insert_login_event(event)

    def record_user_management_event(
        self, *, actor: str, action: str, username: str, success: bool, message: str
    ) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "target_username": username,
            "success": success,
            "message": message,
        }
        with self.user_management_events_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.db.insert_user_management_event(event)

    def read_jsonl_events(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return pd.DataFrame(rows)

    def read_login_events(self) -> pd.DataFrame:
        return self.read_jsonl_events(self.login_events_file)

    def read_user_management_events(self) -> pd.DataFrame:
        return self.read_jsonl_events(self.user_management_events_file)

    def users_dataframe(self) -> pd.DataFrame:
        public_rows = []
        for user in self.users:
            public_rows.append(
                {
                    "username": user.get("username", ""),
                    "display_name": user.get("display_name", ""),
                    "email": user.get("email", ""),
                    "role": user.get("role", "viewer"),
                    "active": user.get("active", True),
                    "created_at_utc": user.get("created_at_utc", "config_user"),
                    "updated_at_utc": user.get("updated_at_utc", ""),
                    "password_hash": "configured" if user.get("password_hash") else "missing",
                }
            )
        return pd.DataFrame(public_rows)

    @staticmethod
    def to_session_dict(user: AuthUser) -> dict[str, Any]:
        return asdict(user)

    @staticmethod
    def from_session_dict(data: dict[str, Any] | None) -> AuthUser | None:
        if not data:
            return None
        return AuthUser(**data)
