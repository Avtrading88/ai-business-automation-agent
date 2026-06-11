# Architecture Diagrams

These diagrams use Mermaid syntax, which renders automatically in GitHub Markdown.

## System context

```mermaid
flowchart TB
    User[Business User / Admin] --> UI[Streamlit Dashboard]
    User --> CLI[Command Line]
    UI --> Agent[Python Automation Agent]
    CLI --> Agent
    Agent --> Files[CSV / Excel / Google Sheets later]
    Agent --> DB[(SQLite Database)]
    Agent --> Logs[Logs + Audit Files]
    Agent --> HubSpot[HubSpot API]
    Agent --> QB[QuickBooks API]
    Agent --> Email[SMTP Email Notifications]
```

## Component diagram

```mermaid
flowchart LR
    subgraph Interface
        A[app.py]
        B[main.py]
    end

    subgraph Core
        C[Data Reader]
        D[Cleaner]
        E[Validator]
        F[Duplicate Detector]
        G[Pipeline]
        H[Reporter]
    end

    subgraph Safety
        I[Role Approval]
        J[Approval History]
        K[Audit Logger]
        L[File Versioning]
        M[System Backup]
    end

    subgraph Integrations
        N[HubSpot Connector]
        O[QuickBooks Connector]
        P[Email Notifier]
    end

    A --> G
    B --> G
    G --> C --> D --> E --> F --> H
    G --> I
    I --> J
    G --> K
    G --> L
    G --> N
    G --> O
    G --> P
    A --> M
```

## QuickBooks protected sync

```mermaid
sequenceDiagram
    participant Admin
    participant App
    participant Approval
    participant QB as QuickBooks Connector
    participant Cache as CustomerRef Cache
    participant API as QuickBooks Sandbox API
    participant Audit

    Admin->>App: Click protected sandbox sync
    App->>Approval: Check logged-in role and approval
    Approval-->>App: Allowed or blocked
    App->>QB: Build customer payloads
    QB->>API: Create or update customers
    API-->>QB: Customer IDs
    QB->>Cache: Save CustomerRef IDs
    QB->>QB: Rebuild invoice payloads
    QB->>QB: Verify CustomerRef + ItemRef
    QB->>API: Create invoices if safe
    API-->>QB: Invoice IDs
    QB->>Audit: Record created/failed/skipped actions
```

## HubSpot sync plan

```mermaid
flowchart TD
    A[CRM-ready contacts] --> B[Search HubSpot by email]
    B --> C{Contact exists?}
    C -->|Yes| D[Plan update]
    C -->|No| E[Plan create]
    C -->|Lookup unavailable| F[Unknown status]
    D --> G[hubspot_sync_plan.json]
    E --> G
    F --> G
    G --> H[Human review]
```

## Scheduled jobs

```mermaid
flowchart TD
    A[data/scheduled_input] --> B[Scheduled job runner]
    B --> C{CSV or Excel files found?}
    C -->|No| D[No-op event]
    C -->|Yes| E[Run pipeline]
    E --> F{Success?}
    F -->|Yes| G[Move file to archive]
    F -->|No| H[Move file to errors]
    G --> I[Email notification preview/send]
    H --> I
```

## Backup and restore

```mermaid
flowchart LR
    A[Current system state] --> B[Create backup ZIP]
    B --> C[Backup manifest]
    C --> D[System Backups tab]
    D --> E[Preview restore]
    E --> F{Admin applies restore?}
    F -->|No| G[No changes]
    F -->|Yes| H[Restore selected files]
```
