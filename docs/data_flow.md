# Data Flow Guide

This document explains how a file moves through the Business Automation Agent.

## Processing flow

```mermaid
sequenceDiagram
    participant User
    participant Dashboard as Streamlit / CLI
    participant Pipeline
    participant Cleaner
    participant Validator
    participant Duplicates
    participant Outputs
    participant Audit
    participant DB as SQLite

    User->>Dashboard: Upload CSV / Excel or provide path
    Dashboard->>Pipeline: process_file(input_path, config)
    Pipeline->>Cleaner: clean_dataframe(df)
    Cleaner-->>Pipeline: cleaned dataframe
    Pipeline->>Validator: validate_dataframe(cleaned_df)
    Validator-->>Pipeline: valid rows + rejected rows
    Pipeline->>Duplicates: remove_duplicates(valid_rows)
    Duplicates-->>Pipeline: CRM-ready rows + duplicate rows
    Pipeline->>Outputs: write CSV / Excel / JSON / report
    Pipeline->>Audit: record planned/skipped actions
    Pipeline->>DB: store run metadata
    Outputs-->>Dashboard: Downloadable files
```

## Output categories

| Output | Purpose |
|---|---|
| `crm_ready_contacts.csv` | Clean contacts that can be imported or synced to CRM |
| `rejected_rows.csv` | Rows blocked by validation rules |
| `duplicates_removed.csv` | Rows removed as duplicates |
| `report.txt` | Human-readable summary of changes |
| `hubspot_sync_plan.json` | Create/update/unknown plan for HubSpot |
| `quickbooks_ready_export.xlsx` | Reviewable QuickBooks customer/invoice workbook |
| `quickbooks_customer_ref_cache.json` | Cached QuickBooks CustomerRef IDs |
| `automation_audit_log.csv` | Governance log of planned/skipped/created/failed actions |
| `latest_run_manifest.json` | Hashes, row counts, file version, and run metadata |

## Validation flow

```mermaid
flowchart TD
    A[Cleaned row] --> B{Required email exists?}
    B -->|No| R[Rejected row]
    B -->|Yes| C{Email format valid?}
    C -->|No| R
    C -->|Yes| D{Identity rule satisfied?}
    D -->|No| R
    D -->|Yes| E{Duplicate?}
    E -->|Yes| X[Duplicate removed]
    E -->|No| G[CRM-ready row]
```

## Approval flow

```mermaid
flowchart TD
    A[Processed output] --> B[User reviews report and rows]
    B --> C{Approval submitted?}
    C -->|No| D[External sync blocked]
    C -->|Yes| E[Record approval history]
    E --> F{Role has permission?}
    F -->|No| G[Block + audit decision]
    F -->|Yes| H{dry_run false and integration enabled?}
    H -->|No| I[Create plan/preview only]
    H -->|Yes| J[Protected sync flow]
```
