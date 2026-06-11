import pandas as pd

from automation_agent.connectors.quickbooks_connector import QuickBooksConnector


def test_quickbooks_invoice_payload_uses_customer_ref_cache(base_config):
    base_config["integrations"]["quickbooks"].update(
        {
            "default_item_ref_id": "1",
            "invoice_required_columns": ["invoice_number", "amount"],
        }
    )
    connector = QuickBooksConnector(base_config)
    invoices_df = pd.DataFrame(
        [
            {
                "InvoiceNumber": "INV-001",
                "CustomerEmail": "anna@example.com",
                "CustomerDisplayName": "Anna Example",
                "InvoiceDate": "2026-01-01",
                "LineDescription": "Automation service",
                "Quantity": 1,
                "UnitPrice": 200,
                "Amount": 200,
            }
        ]
    )
    cache = {
        "anna@example.com": {
            "id": "123",
            "display_name": "Anna Example",
            "email": "anna@example.com",
        }
    }

    payloads, unresolved = connector.build_invoice_payloads(invoices_df, cache)

    assert unresolved == []
    assert payloads[0]["CustomerRef"]["value"] == "123"
    assert payloads[0]["Line"][0]["SalesItemLineDetail"]["ItemRef"]["value"] == "1"


def test_quickbooks_invoice_payload_marks_missing_customer_ref(base_config):
    connector = QuickBooksConnector(base_config)
    invoices_df = pd.DataFrame(
        [
            {
                "InvoiceNumber": "INV-002",
                "CustomerEmail": "missing@example.com",
                "CustomerDisplayName": "Missing Customer",
                "Amount": 100,
            }
        ]
    )

    payloads, unresolved = connector.build_invoice_payloads(invoices_df, {})

    assert len(unresolved) == 1
    assert unresolved[0]["invoice_number"] == "INV-002"
    assert payloads[0]["CustomerRef"]["value"] == "CUSTOMER_REF_LOOKUP_REQUIRED"
