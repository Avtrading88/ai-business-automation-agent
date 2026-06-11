Write-Host "Formatting with Black..."
python -m black .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Auto-fixing with Ruff..."
python -m ruff check . --fix
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Formatting completed."
