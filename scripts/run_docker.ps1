if (!(Test-Path .env)) {
    Copy-Item .env.dev.example .env
    Write-Host "Created .env from .env.dev.example. Add secrets there if needed."
}

docker run --rm `
    -p 8501:8501 `
    --env-file .env `
    -v ${PWD}/data:/app/data `
    -v ${PWD}/logs:/app/logs `
    -v ${PWD}/config.yaml:/app/config.yaml `
    business-automation-agent:v22
