# Portfolio Guide: Business Automation Agent

## Project title

**Business Automation Agent — Spreadsheet-to-CRM/QuickBooks Automation Platform**

## One-line summary

A Python and Streamlit automation platform that cleans spreadsheet data, validates customer/contact records, prepares CRM and QuickBooks-ready outputs, and adds approval, audit, scheduling, backup, testing, and deployment workflows.

## Problem

Many small and medium-sized businesses still rely on spreadsheets for customer, sales, and invoice data. Before this data can be uploaded to CRM or accounting tools, it needs to be cleaned, validated, deduplicated, reviewed, and approved. Manual data entry causes errors, duplicate CRM records, missing invoice details, and weak audit trails.

## Solution

This project automates the preparation process while keeping human approval and traceability in place. It reads CSV/Excel files, cleans and validates records, separates rejected rows, detects duplicates, prepares CRM and QuickBooks-ready exports, and records audit and approval history before any external sync.

## Main features to highlight in a portfolio

| Category | Highlights |
|---|---|
| Python engineering | Modular backend pipeline, CLI support, reusable service modules |
| Data processing | Cleaning, validation, duplicate detection, CRM-ready exports |
| Business automation | HubSpot planning, QuickBooks planning, scheduled jobs, email notifications |
| Governance | Human approvals, role-based permissions, audit logs, SQLite database |
| Reliability | File versioning, rollback, backups, restore preview, error folders |
| DevOps | Docker, docker-compose, GitHub Actions CI/CD, security checks |
| Code quality | pytest, Ruff, Black, pyproject.toml, quality scripts |
| Documentation | Architecture diagrams, API reference, data-flow guide, polished README |

## Suggested GitHub repository description

```text
Python + Streamlit business automation agent for spreadsheet cleaning, CRM/QuickBooks-ready exports, approvals, audit logs, scheduled jobs, backups, Docker deployment, and CI/CD.
```

## Suggested LinkedIn post

```text
I built a Business Automation Agent in Python and Streamlit.

The project focuses on a common business problem: teams often manage customer, contact, and invoice data in spreadsheets, but this data needs cleaning, validation, duplicate detection, and approval before it is uploaded into CRM or accounting systems.

The app can:
- Read CSV/Excel files
- Clean and validate customer/contact data
- Detect duplicates and rejected rows
- Prepare CRM-ready and QuickBooks-ready outputs
- Generate audit logs and approval history
- Support role-based approval rules
- Run scheduled jobs and email notification previews
- Store records in SQLite
- Support file versioning, rollback, and system backups
- Run with Docker and GitHub Actions CI/CD

This project helped me practice practical automation engineering, data processing, Streamlit dashboards, API integration planning, testing, and deployment workflows.
```

## Suggested resume bullet points

- Built a Python and Streamlit business automation agent for cleaning, validating, and preparing spreadsheet data for CRM and accounting workflows.
- Implemented duplicate detection, rejected-row handling, CRM-ready exports, QuickBooks-ready customer/invoice exports, approval history, and audit logging.
- Added role-based permissions, Streamlit authentication, SQLite persistence, scheduled jobs, file versioning, rollback, system backups, and email notification previews.
- Containerized the application with Docker and added GitHub Actions CI/CD, pytest tests, Ruff linting, and Black formatting checks.

## Screenshots to add

Place screenshots in `docs/screenshots/` and reference them from the README if desired.

Recommended screenshots:

1. Dashboard upload and data processing
2. CRM-ready output preview
3. Rejected rows and duplicate rows
4. QuickBooks OAuth setup
5. QuickBooks API plan
6. Audit log
7. Approval history
8. User management
9. Settings admin
10. File versions and rollback
11. System backups
12. GitHub Actions passing tests

## Demo script for interviews

1. Start the app with `streamlit run app.py`.
2. Log in as admin.
3. Upload the sample QuickBooks/contact file.
4. Show raw rows, cleaned rows, rejected rows, duplicates, and report.
5. Show HubSpot sync plan and QuickBooks export/plan.
6. Open approval history and audit log.
7. Show user roles and permission rules.
8. Show scheduled jobs and email notification dry-run.
9. Show file versioning and rollback.
10. Explain Docker, tests, CI/CD, and security checks.

## Why this project is valuable

This project is more than a basic Streamlit dashboard. It shows an end-to-end business automation workflow with safety controls. It demonstrates practical skills in data engineering, automation, Python architecture, API integration planning, security-aware development, testing, documentation, and deployment.


## GitHub presentation

- See `docs/github_landing_page.md` for repository title, description, topics, screenshot order and portfolio messaging.
- See `docs/screenshots/README.md` for screenshot placeholder and replacement instructions.
