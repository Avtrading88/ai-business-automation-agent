# Demo Script — Business Automation Agent

Use this script for a 5–8 minute portfolio, interview, or client demo.

## 1. Opening pitch

> This project is a Python-based business automation agent. It helps companies clean customer/contact data, detect duplicates and missing fields, prepare CRM-ready exports, and create safe QuickBooks planning files before any real external sync happens.

## 2. Business problem

Many small teams manage customer, sales, and invoice information in spreadsheets. The problem is that these files often contain duplicated contacts, invalid emails, missing invoice fields, inconsistent column names, and risky manual copy-paste steps before sending data to CRM or accounting software.

## 3. Solution overview

This app provides a controlled workflow:

1. Upload CSV or Excel data.
2. Clean and validate records.
3. Split clean rows, rejected rows, and duplicates.
4. Generate CRM and QuickBooks-ready outputs.
5. Require human approval before external sync.
6. Store audit logs, approvals, roles, settings, backups, and file versions.

## 4. Live walkthrough

### Step A — Start the dashboard

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Log in as:

```text
username: admin
password: admin123
```

### Step B — Upload demo data

Go to **Data Processing** and upload:

```text
demo/data/demo_contacts_mixed_quality.csv
```

Explain that the file contains good rows, duplicates, missing email values, invalid emails, and incomplete invoice fields.

### Step C — Show validation results

Point out:

- Original rows
- CRM-ready rows
- Rejected rows
- Duplicates removed
- Report tab
- Download tab

### Step D — Show safety controls

Open these tabs:

- **Role Rules** — shows who can approve which actions.
- **Approval History** — shows who approved what.
- **Audit Log** — records planned, skipped, created, and failed actions.
- **QuickBooks OAuth Setup** — shows safe setup without exposing full tokens.
- **Settings Admin** — shows editable validation/CRM/QuickBooks rules.

### Step E — Show production readiness

Mention:

- Docker deployment files
- GitHub Actions CI/CD
- Pytest test suite
- Ruff/Black quality checks
- Public-release cleanup script
- Backup and rollback system

## 5. Closing summary

> This is not only a data-cleaning script. It is a structured business automation platform with safety controls, approvals, audit history, user roles, scheduled jobs, notifications, backups, tests, CI/CD, and deployment documentation.
