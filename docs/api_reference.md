# Internal API Reference

This is a practical reference for the main Python modules in the project. The project currently exposes an internal Python API rather than a public web REST API.

## `automation_agent.core.data_reader`

### `read_input_file(file_path)`

Reads a CSV or Excel file into a pandas DataFrame.

Typical use:

```python
from automation_agent.core.data_reader import read_input_file

df = read_input_file("data/input/sample_contacts.csv")
```

Expected behavior:

- Supports `.csv`, `.xlsx`, and `.xls`.
- Raises an error for unsupported file formats.
- Keeps raw data unchanged before cleaning.

## `automation_agent.core.cleaner`

### `clean_dataframe(df, config=None)`

Normalizes business data so downstream validation and exports are more reliable.

Typical transformations:

- `E-mail`, `Email Address`, `email address` → `email`
- trims whitespace
- lowercases emails
- normalizes empty values
- cleans basic text fields

```python
from automation_agent.core.cleaner import clean_dataframe

clean_df = clean_dataframe(df, config)
```

## `automation_agent.core.validator`

### `validate_dataframe(df, config)`

Splits data into accepted and rejected rows based on configured rules.

Returns conceptually:

- valid rows
- rejected rows
- validation issue summary

Common rules:

- required columns
- missing required values
- valid email format
- at least one identity field such as first name, last name, or company

## `automation_agent.core.duplicate_detector`

### `remove_duplicates(df, duplicate_columns)`

Removes duplicate records using configured identity columns, usually email.

```python
from automation_agent.core.duplicate_detector import remove_duplicates

unique_df, duplicates_df = remove_duplicates(df, ["email"])
```

## `automation_agent.core.pipeline`

### `process_file(input_path, config_path="config.yaml", output_dir="data/output")`

Runs the main file-processing workflow.

Responsibilities:

1. read file
2. clean data
3. validate data
4. remove duplicates
5. create output files
6. generate report
7. prepare HubSpot and QuickBooks plans
8. save audit/version metadata

This is the best function to reuse if you later add a REST API, background worker, or another UI.

## `automation_agent.connectors.hubspot_connector`

HubSpot connector responsibilities:

- build contact payloads
- create dry-run payload previews
- plan create/update actions
- avoid duplicate creation by checking existing contacts where configured

Important safety behavior:

- real sync should stay disabled unless `enabled=true`, `dry_run=false`, and approval checks pass.

## `automation_agent.connectors.quickbooks_connector`

QuickBooks connector responsibilities:

- export customer/invoice files
- generate OAuth authorization URLs
- exchange/refresh tokens
- prepare Customer and Invoice API payloads
- maintain CustomerRef cache
- block invoice sync when CustomerRef or ItemRef is missing

Important safety behavior:

- production sync is blocked by default.
- sandbox sync still requires valid OAuth, approval, role permission, and `dry_run=false`.

## `automation_agent.core.role_based_approval`

### Role model

| Role | Main permission |
|---|---|
| viewer | view outputs only |
| reviewer | approve export-only flows |
| approver | approve CRM sync and QuickBooks sandbox sync |
| admin | approve sandbox and production sync, manage users/settings |

## `automation_agent.core.file_versioning`

Creates versioned folders for processed outputs.

Each run has:

- unique run ID
- manifest file
- output hashes
- source file metadata
- rollback support

## CLI reference

### Process a file

```powershell
python main.py --input data/input/sample_contacts.csv --skip-approval
```

### Process QuickBooks sample file

```powershell
python main.py --input data/input/sample_quickbooks_contacts_invoices.csv --skip-approval
```

### Run protected QuickBooks sandbox sync

```powershell
python main.py --input data/input/sample_quickbooks_contacts_invoices.csv --quickbooks-sync --approved-by "Vladimir Trifonov"
```

### Run scheduled jobs

```powershell
python main.py --run-scheduled-jobs
```

### Create system backup

```powershell
python main.py --create-system-backup --approved-by "Vladimir Trifonov"
```

### List file versions

```powershell
python main.py --list-runs
```

### Run tests

```powershell
python -m pytest
```

### Run quality checks

```powershell
.\scripts\run_quality_checks.ps1
```
