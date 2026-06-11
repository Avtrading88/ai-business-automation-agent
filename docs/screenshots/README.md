# Screenshots and GitHub visuals

This folder contains GitHub-ready SVG placeholder screenshots for the Business Automation Agent.

These files are useful before you have final real screenshots. After running the app locally, you can replace them with actual screenshots using the same names.

## Included placeholders

| File | Purpose |
|---|---|
| `dashboard_data_processing.svg` | Main upload, cleaning, validation and download workflow |
| `quickbooks_oauth_setup.svg` | QuickBooks OAuth setup and token status page |
| `audit_log.svg` | Audit log table and traceability view |
| `settings_admin.svg` | Admin settings panel |
| `file_versions.svg` | Versioned runs and rollback page |
| `system_backups.svg` | Backup/export/import page |

## How to replace with real screenshots

1. Run the app with `streamlit run app.py`.
2. Log in as `admin / admin123`.
3. Open each important tab.
4. Take a screenshot.
5. Save the screenshot in this folder.
6. Update the README image path if you use `.png` instead of `.svg`.

For GitHub, screenshots normally work best with relative Markdown paths like:

```markdown
![Dashboard](docs/screenshots/dashboard_data_processing.svg)
```
