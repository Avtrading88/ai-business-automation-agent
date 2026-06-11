from __future__ import annotations

import pandas as pd

from automation_agent.connectors.hubspot_connector import HubSpotConnector, HubSpotSyncResult


class CRMConnector:
    """CRM connector router. Currently supports HubSpot contacts."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    def sync_contacts(self, df: pd.DataFrame) -> HubSpotSyncResult:
        connector_name = (
            self.config.get("integrations", {}).get("crm_provider", "hubspot").lower().strip()
        )

        if connector_name != "hubspot":
            raise ValueError(
                f"Unsupported CRM provider: {connector_name}. Currently supported: hubspot"
            )

        return HubSpotConnector(self.config).sync_contacts(df)
