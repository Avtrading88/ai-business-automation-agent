# CI/CD Setup with GitHub Actions

Version 24 adds GitHub Actions so the project can be tested automatically whenever you push code to GitHub or open a pull request.

## Included workflows

```text
.github/workflows/ci.yml
.github/workflows/security-checks.yml
```

## What the CI workflow does

The main CI workflow:

1. Checks out the repository.
2. Installs Python 3.11 and 3.12.
3. Installs dependencies from `requirements.txt`.
4. Runs the full `pytest` test suite.
5. Runs a command-line smoke test with the sample QuickBooks file.
6. Checks that important output files were created.
7. Builds the Docker image to confirm the deployment container still works.

## What the security workflow does

The security workflow blocks common mistakes:

1. `.env` accidentally committed.
2. Local SQLite database accidentally committed.
3. QuickBooks access or refresh tokens accidentally committed.

## How to use it

Push the project to GitHub:

```powershell
git init
git add .
git commit -m "Add business automation agent with CI"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

After pushing, open the repository on GitHub and go to:

```text
Actions
```

You should see the workflows running automatically.

## Run the same checks locally

```powershell
.\scripts\run_ci_checks.ps1
```

Or manually:

```powershell
python -m pytest
python main.py --input data/input/sample_quickbooks_contacts_invoices.csv --skip-approval --approved-by "Local CI" --approver-role reviewer
```

## Important files that should not be committed

Keep these private/local:

```text
.env
data/output/automation_agent.db
data/output/auth_users.json
data/output/system_backups/
data/output/config_backups/
logs/*.log
```

The `.gitignore` file is configured to protect these files.
