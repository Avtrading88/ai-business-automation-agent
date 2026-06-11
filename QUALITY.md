# Code Quality Guide

V26 includes Ruff and Black for professional code quality.

## Run all quality checks

```powershell
.\scripts\run_quality_checks.ps1
```

## Auto-format code

```powershell
.\scripts\format_code.ps1
```

## Manual commands

```powershell
python -m ruff check .
python -m black --check .
python -m pytest
```
