$ErrorActionPreference = "Stop"
Write-Host "Preparing project for public GitHub release..."
python .\scripts\prepare_public_release.py
Write-Host ""
Write-Host "Now run: git status"
Write-Host "Review the commit list carefully before pushing."
