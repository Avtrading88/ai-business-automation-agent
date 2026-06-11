# Public Release Guide

Version 29 prepares the project for a clean public GitHub upload.

## What should be public

Safe to commit:

- Source code in `src/`
- Streamlit app code
- Tests in `tests/`
- Documentation in `docs/`
- Docker and CI/CD files
- Example environment templates
- Demo/sample input files
- Placeholder screenshots

## What should stay private

Never commit:

- `.env` with API keys or tokens
- QuickBooks OAuth tokens
- HubSpot private app tokens
- SMTP passwords
- SQLite database files
- Generated audit logs
- Generated approval records
- Real customer files
- Real invoice/accounting exports

## Recommended repository description

```text
Python + Streamlit business automation agent for cleaning spreadsheet data, validating CRM/customer records, preparing HubSpot and QuickBooks sync plans, and enforcing approval, audit, testing, and deployment workflows.
```

## Suggested GitHub topics

```text
python streamlit automation data-cleaning crm quickbooks hubspot pandas sqlite docker pytest github-actions business-automation
```

## Suggested repository name

```text
business-automation-agent
```
