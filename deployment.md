# Deployment Guide — Business Automation Agent V24

This project can run locally with Python or inside Docker. Docker is recommended when you want the same environment on another computer or server.

## 1. Local development

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open Streamlit at:

```text
http://localhost:8501
```

## 2. Prepare environment file

Copy the development template:

```powershell
copy .env.dev.example .env
```

For production/server usage, copy:

```powershell
copy .env.prod.example .env
```

Then fill in only the secrets you actually use. Keep `.env` private.

## 3. Build and run with Docker

```powershell
docker build -t business-automation-agent:v22 .
docker run --rm -p 8501:8501 --env-file .env -v ${PWD}/data:/app/data -v ${PWD}/logs:/app/logs business-automation-agent:v22
```

## 4. Run with Docker Compose

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8501
```

Stop it with:

```powershell
docker compose down
```

## 5. Persistent data

The Compose file mounts these folders from your computer into the container:

```text
data/input/
data/output/
data/scheduled_input/
data/scheduled_archive/
data/scheduled_errors/
logs/
config.yaml
```

That means the database, reports, backups, audit logs, and versioned files remain available after the container stops.

## 6. Production safety checklist

Before using real CRM or accounting data:

- Change demo admin password.
- Keep `.env` private.
- Keep `data/output/automation_agent.db` private.
- Keep `data/output/system_backups/` private.
- Leave CRM/QuickBooks dry-run enabled until you test with sandbox data.
- Use QuickBooks sandbox before production.
- Create a system backup before changing settings or syncing data.

## 7. Scheduled jobs with Docker

Scheduled jobs can still be triggered by your host system:

```powershell
docker compose run --rm business-automation-agent python main.py --run-scheduled-jobs
```

On Windows, this command can be placed inside Windows Task Scheduler.
