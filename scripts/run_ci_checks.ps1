Write-Host "Running local CI checks..." -ForegroundColor Cyan

python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host "Running pytest..." -ForegroundColor Cyan
python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Running CLI smoke test..." -ForegroundColor Cyan
python main.py --input data/input/sample_quickbooks_contacts_invoices.csv --skip-approval --approved-by "Local CI" --approver-role reviewer
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Local CI checks passed." -ForegroundColor Green
