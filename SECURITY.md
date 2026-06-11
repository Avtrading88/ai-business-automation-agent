# Security Policy

This project handles spreadsheet, CRM, and accounting-style data. Treat all real business data as sensitive.

## Do not commit secrets

Never commit `.env`, OAuth tokens, SMTP passwords, QuickBooks credentials, HubSpot tokens, SQLite database files, generated exports, or real customer spreadsheets.

## Safe configuration

The project is designed to run in dry-run/export-only mode by default. Real CRM or QuickBooks sync should only be enabled after review, approval, and environment setup.

## Reporting security issues

For a portfolio/demo repository, open a private issue or contact the repository owner directly instead of posting secrets or vulnerabilities in a public issue.
