# GitHub Upload Checklist

Use this checklist before pushing the project to a public GitHub repository.

## 1. Keep secrets private

Do **not** commit these files:

```text
.env
.env.dev
.env.prod
.streamlit/secrets.toml
*.pem
*.key
```

Only commit example templates such as:

```text
.env.example
.env.dev.example
.env.prod.example
```

## 2. Keep customer/accounting data private

Do **not** commit generated files from:

```text
data/output/
data/scheduled_input/
data/scheduled_archive/
data/scheduled_errors/
```

The repository should include only sample/demo files in `data/input/`.

## 3. Run tests and quality checks

```powershell
python -m pytest
.\scriptsun_quality_checks.ps1
```

## 4. Run the public-release cleanup script

```powershell
.\scripts\prepare_public_release.ps1
```

This removes generated output files and checks for common secret files.

## 5. Review files before commit

```powershell
git status
```

Make sure no private data, database files, token files, or real customer spreadsheets appear in the commit list.

## 6. Commit and push

```powershell
git add .
git commit -m "Prepare business automation agent for public GitHub release"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```
