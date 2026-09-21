# Post-Event Report

A simple form for tech leads to fill out at the warehouse when returning from an
event, plus a weekly rollup report of misplaced/missing/broken items for the
Monday reset.

## How it works

- **`/`** — the tech-facing form. Pick your event, enter your name, list any
  misplaced/missing/broken items, add notes. No login required.
- **`/admin`** — PIN-protected. Add/close/delete events, and view the report.
- **`/admin/report`** — a live view of all submissions in a chosen window
  (7/14/30/90 days).
- **`/report/email?token=...`** — a token-protected, email-formatted version of
  the report, meant to be fetched by an automated weekly job (see below).

## Local setup

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit the PIN/tokens
./venv/bin/python app.py
```

Visit http://127.0.0.1:5050. The default admin PIN is whatever you set as
`ADMIN_PIN` in `.env` (starts as `1234` — change it before real use).

## Environment variables

| Variable        | Purpose                                                        |
|-----------------|------------------------------------------------------------------|
| `SECRET_KEY`    | Flask session signing key — any random string                   |
| `ADMIN_PIN`     | PIN required to reach `/admin`                                   |
| `REPORT_TOKEN`  | Secret required to fetch `/api/report` or `/report/email`        |
| `DATABASE_URL`  | SQLAlchemy DB URL. Defaults to a local SQLite file for dev.       |

## Deploying so tech leads can use it from their phones

This needs to run somewhere public (not just on one laptop). Two easy, free/cheap
options that don't need Node or Docker knowledge:

**Render.com** (recommended — simplest):
1. Push this folder to a GitHub repo (see below).
2. On Render, "New Web Service" → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add the environment variables above under "Environment".
6. For real persistence across deploys, add a Render Postgres database (free
   tier) and set `DATABASE_URL` to its connection string — change
   `models.py`'s usage stays the same, SQLAlchemy handles both.

**Fly.io** works similarly with a `fly launch` + a small `Dockerfile` if you'd
rather containerize it.

### Getting this onto GitHub

```bash
# create an empty repo at github.com/new first, then:
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

## Weekly email report

Rather than build email-sending into the app, the plan is to have a scheduled
Claude task fetch `/report/email?token=...` once deployed, and send it via your
connected Outlook account to lucas@siagel.com every Monday morning. See Claude's
scheduled task for this project.
