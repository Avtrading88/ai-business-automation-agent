# Contributing

Thanks for improving this project.

## Development setup

```powershell
python -m venv .venv
.venv\Scriptsctivate
pip install -r requirements.txt
```

## Before opening a pull request

```powershell
python -m pytest
.\scriptsun_quality_checks.ps1
```

## Code style

The project uses Black for formatting and Ruff for linting.

```powershell
.\scriptsormat_code.ps1
```

## Data safety

Do not add real customer data, accounting files, tokens, `.env` files, or generated database/output files to commits.
