# Walkthrough Steps

## Fast demo checklist

1. Open the Streamlit dashboard.
2. Log in as `admin / admin123`.
3. Go to **Data Processing**.
4. Upload `demo/data/demo_contacts_mixed_quality.csv`.
5. Click the processing button.
6. Show the metrics: original, clean, rejected, duplicates.
7. Open the **Report** tab.
8. Open the **Downloads** tab.
9. Open **QuickBooks API Plan** and explain dry-run safety.
10. Open **Audit Log** and **Approval History**.
11. Open **File Versions** to show rollback readiness.
12. Open **System Backups** to show portability.
13. Explain CI/CD and tests using `python -m pytest`.

## Suggested explanation

The strongest message is that this project combines practical business automation with responsible safety design. It avoids uncontrolled API updates by requiring review, approval, role permissions, audit logs, and dry-run planning before real CRM or accounting changes.
