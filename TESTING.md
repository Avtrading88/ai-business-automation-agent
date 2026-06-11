# Testing Guide

This project uses `pytest` for automated tests.

## Install dependencies

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run all tests

```powershell
python -m pytest
```

## Run one test file

```powershell
python -m pytest tests/test_validator.py
```

## Current test areas

- Data cleaning
- Required field validation
- Email validation
- Country validation
- Duplicate detection
- End-to-end dataframe processing
- Role-based approval decisions
- QuickBooks CustomerRef invoice payload safety

## Why this matters

Before connecting real CRM or accounting APIs, the project should prove that the cleaning, validation, approval, and export logic works reliably. These tests make it safer to change the code later without breaking existing behavior.

---

## CI/CD testing

Version 24 includes GitHub Actions. The same checks can be run locally:

```powershell
.\scripts\run_ci_checks.ps1
```

GitHub runs the workflow automatically on push and pull request:

```text
.github/workflows/ci.yml
.github/workflows/security-checks.yml
```
