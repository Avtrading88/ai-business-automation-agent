# Interview Answer

## Question: Tell me about one of your recent projects.

I built an AI Business Automation Agent to solve a common business problem: many companies manage customer, invoice, or CRM data in spreadsheets, and manual data entry often causes duplicates, missing fields, invalid emails, and inconsistent records.

My solution is a Python-based automation agent that reads CSV and Excel files, cleans and validates the data, detects duplicates, creates clean output files, and generates reports. I also added a Streamlit dashboard, audit logs, approval workflows, role-based permissions, file versioning, backups, scheduled jobs, Docker support, automated tests, and CI/CD with GitHub Actions.

I focused heavily on safety. The app uses dry-run mode and human approval before sending data to external systems like HubSpot or QuickBooks. This makes it not only a technical project, but also a realistic business workflow automation tool.

Technologies used: Python, Pandas, Streamlit, SQLite, Pytest, Ruff, Black, Docker, GitHub Actions, YAML configuration, and API integration planning.
