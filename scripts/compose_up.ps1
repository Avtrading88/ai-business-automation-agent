if (!(Test-Path .env)) {
    Copy-Item .env.dev.example .env
    Write-Host "Created .env from .env.dev.example. Add secrets there if needed."
}

docker compose up --build
