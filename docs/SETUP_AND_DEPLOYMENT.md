# Production deployment

The current production release uses Google Cloud Run for both APIs and
staterbill.com for Billing. Follow [the ordered migration runbook](runbooks/cloud-run-migration.md)
for the exact per-project Vercel variables, domain settings, Secret Manager
configuration, health checks, forwarder and rollback commands. Cloud Run sleeps
when idle by default; sign-in and idempotent requests tolerate cold starts.

# BizAssist - Setup Guide

Everything you need to get BizAssist running after cloning the repo, on any computer.

BizAssist has three parts:
- **Backend** - FastAPI (Python), runs on `http://localhost:8001`
- **AI Dashboard Frontend** - React + Vite, runs on `http://localhost:5173`
- **Billing Frontend** - React + Vite, runs on `http://localhost:5174`

---

## 1. Prerequisites

- **Python 3.10+** - https://python.org (tick "Add to PATH" during install)
- **Node.js 18+** - https://nodejs.org (for the React frontend)
- A **Groq API key** - https://console.groq.com (required for the AI)

---

## 2. First-time setup (any computer)

```powershell
# from the repo root
.\dependencies.bat
```
This creates the Python virtual environment (`venv`) and installs all backend
packages. It is safe to re-run any time - it reuses the existing venv and only
installs what's missing.

Frontend packages are installed automatically by `dependencies.bat`. If you ever need to manually update/install them, you can run:
```powershell
# Install AI Dashboard dependencies
cd frontend-ai
npm install
cd ..

# Install Billing Frontend dependencies
cd frontend-billing
npm install
cd ..
```

### Create your .env
The `.env` file holds secrets and is **never committed** (it's gitignored), so
you must create it on each computer:
```powershell
copy .env.example backend\.env
```
Open `backend\.env` and fill in at minimum:
- `GROQ_API_KEY` - required for the AI to work
- `DATABASE_URL` - see the next section (the choice of database)

---

## 3. Choose your database

The app and Alembic both read **one variable: `DATABASE_URL`**. You don't change
any code - you just set this variable differently per environment.

| Flow | `DATABASE_URL` value | Extra steps | Use it when |
|------|----------------------|-------------|-------------|
| **SQLite (default, zero setup)** | `sqlite:///./bizassist.db` (or leave unset) | none | Quick local dev. This is the simplest. |
| **Supabase (online)** | the Supabase connection string | none locally | Shared/online data; this is what Cloud Run uses. |
| **Local Postgres** | `postgresql://postgres:devpass@localhost:5432/bizassist` | install Postgres (section 4) | Only when you need to test Postgres behaviour locally. |

**Recommendation:** use **SQLite** for everyday local dev (no friction), and
**Supabase** for Cloud Run / production. Local Postgres is optional.

---

## 4. (Optional) Local Postgres setup

Only needed if you chose the "Local Postgres" flow above. These steps use
PowerShell (not the interactive "SQL Shell"), which is more reliable - the SQL
Shell's connection prompts (Server / Database / Port / Username) are easy to
confuse with where you type SQL.

### 4.1 Install PostgreSQL 16
```powershell
winget install -e --id PostgreSQL.PostgreSQL.16
```
(or download the installer from https://www.postgresql.org/download/windows/)

The installer **requires** a password for the `postgres` superuser and keeps
port **5432**. A winget install commonly leaves the password as **`postgres`** -
remember whatever it ends up being; you'll need it once below.

### 4.2 Find your password + create the database
All commands go through `psql.exe` with `-c` so there are no interactive prompts.
`$env:PGPASSWORD` tells psql the password for that one command.

```powershell
# 1) confirm the password (try "postgres" first)
$env:PGPASSWORD="postgres"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -d postgres -c "SELECT 1;"
```
- Prints a table with `1`  -> password is correct, continue.
- "password authentication failed" -> set `$env:PGPASSWORD="<your password>"` and retry.
- "path does not exist" -> your version/location differs; find psql with:
  `Get-ChildItem "C:\Program Files\PostgreSQL" -Recurse -Filter psql.exe | Select FullName`

```powershell
# 2) create the database
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -d postgres -c "CREATE DATABASE bizassist;"

# 3) standardize the password to devpass (so it matches DATABASE_URL in .env)
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -d postgres -c "ALTER USER postgres PASSWORD 'devpass';"
```
> If you'd rather keep your own password, skip step 3 and instead set it in
> `backend\.env` (URL-encode special chars: `@`->`%40`, `#`->`%23`, `:`->`%3A`,
> `/`->`%2F`, `%`->`%25`).

### 4.3 Create the tables
```powershell
cd backend
..\venv\Scripts\activate
alembic upgrade head
```

### 4.4 (Optional) Copy existing SQLite data into Postgres
```powershell
python migrate_sqlite_to_postgres.py
```
Run from the `backend\` folder. It prints `OK <table>: N rows`, then
`SEQ <table>` (sequence reset), then `Done!`.

> If the output shows `SKIP feedback (not in Postgres)` or
> `SKIP query_override (...)`, those tables are created by the app at first boot,
> not by Alembic. To copy their data too: run the app once (section 5) so the
> tables get created, then re-run `python migrate_sqlite_to_postgres.py` (it's
> idempotent - safe to run again).

> Note: `psycopg2-binary` (the Postgres driver) is already in `requirements.txt`,
> so `dependencies.bat` installs it automatically - no manual step.

---

## 5. Run the app

**Easiest - both servers at once:**
```powershell
.\start_dev.bat
```
(For verbose backend logs: `.\start_dev.bat debug`)

**Or run them separately:**
```powershell
# backend
cd backend
..\venv\Scripts\activate
uvicorn main_groq:app --reload --port 8001

# AI dashboard (in another terminal)
cd frontend-ai
npm run dev -- --port 5173

# Billing App (in another terminal)
cd frontend-billing
npm run dev -- --port 5174
```

Open **http://localhost:5173** (AI Dashboard) and **http://localhost:5174** (Billing app) in your browser.

---

## 6. Run the tests
```powershell
.\run_tests.bat
```
Tests run on SQLite and should all pass.

---

## 7. Production deployment: Cloud Run and Vercel

Deploy the Field Team API first, Billing second, the Hugging Face compatibility
forwarder third, then all four frontends and a new desktop installer. Follow
[the release runbook](runbooks/cloud-run-migration.md) for exact commands,
Secret Manager checks and rollback. Existing installations continue using the
legacy Space through `ops/hf-forwarder/` until they upgrade.

Billing deploy commands, from the repository root:

```powershell
.\backend\deploy_cloudrun.ps1 -Project staterbill -Setup
# Later deploys omit -Setup.
```

```bash
bash backend/deploy_cloudrun.sh --setup staterbill
```

The deploy scripts keep unmanaged environment variables and secret mounts,
use one worker and one instance, keep `--min-instances 0`, set
`SUBSCRIPTION_ENFORCED=0`, and rotate SSE connections before Cloud Run's 120s
request limit. They probe the tagged revision's `/health` before moving traffic.
Cloud Scheduler invokes eight secret-authenticated jobs; durable leases and
business cursors resume incomplete runs. Pause those jobs before rolling back
to a revision that still schedules in-process jobs.

Before deploying, back up PostgreSQL and run Billing's `python -m alembic
upgrade head` with schema-owner credentials from Secret Manager. Current head:
`h4_auth_admin_runtime_state`. Field Team has its own `ft_*` migration chain.
Constrained runtime credentials never perform DDL. Mount `ADMIN_SERVICE_URL`
when the runtime role cannot perform privileged admin operations.

Both APIs must use the same JWT_SECRET and database. The runbook explains how
to compare SHA-256 digests without printing a secret. The optional authenticated
release check verifies a 90-second `field_team` handoff; AI dashboard handoffs
are 60 seconds. Field Team and AI still enforce Pro on their own endpoints.
Free Billing web accounts keep the five-minute preview once plan status is known.

### Vercel production projects

Use the corresponding frontend directory as each project's root and `npm run
build` as the build command, with output `dist`. Set the following public
build variables in Production, then redeploy each project. An unset variable
uses its production default; the build records configured URLs in
`/build-info.json` for release verification.

| Project | Variable | Value |
|---|---|---|
| frontend-billing | VITE_API_URL | https://staterbill-api-1076771386585.asia-south1.run.app |
| frontend-billing | VITE_FIELD_TEAM_URL | https://task.staterbill.com |
| frontend-billing | VITE_AI_DASHBOARD_URL | https://bizassist-dev-workspace-ai.vercel.app |
| frontend-billing | VITE_PUBLIC_WEB_URL | https://staterbill.com |
| frontend-task | VITE_API_URL | https://bizassist-task-qyfsbxu27a-el.a.run.app |
| frontend-task | VITE_BILLING_URL | https://staterbill.com,https://www.staterbill.com |
| frontend-ai | VITE_API_URL | https://staterbill-api-1076771386585.asia-south1.run.app |
| frontend-ai | VITE_BILLING_URL | https://staterbill.com,https://www.staterbill.com |
| frontend-admin | VITE_API_URL | https://staterbill-api-1076771386585.asia-south1.run.app |
| frontend-admin | VITE_BILLING_URL | https://staterbill.com,https://www.staterbill.com |

Billing uses `staterbill.com`, `www.staterbill.com` redirects to it with a valid
certificate, and Admin uses `admin.staterbill.com`. Add `task.staterbill.com`
to the same Vercel project whose Root Directory is `frontend-task`, with the
DNS record Vercel provides and a valid production certificate. Field Team uses
that custom domain; `bizassist-task.vercel.app` remains accepted during the
transition. AI keeps its Vercel address above. Disable Vercel Authentication on AI's production
deployment so owners can reach Dashboard BIZASSIST. The owner has reported
these console changes completed; verify them against the deployed builds.

### Release verification

```powershell
python dev/check_cloud_release.py --report scratch/cloud-release-check.json
```

The check tolerates API cold starts and checks readiness, CORS, frontend build
URLs, the www redirect, certificates and accidental Vercel sign-in redirects.
Use its digest options and optional owner token only from a private operator
shell; reports contain no tokens or digests. Public checks alone cannot prove
the authenticated business workflows or physical printing: complete the
runbook's end-to-end checks before declaring a production release.

### Local development on a new computer

```powershell
git clone <repo>
cd bizassist
.\dependencies.bat
Copy-Item .env.example backend\.env
.\start_dev.bat
```

Local SQLite needs no cloud credentials. Desktop installers must ship without
an .env file; the bundled backend receives the same Cloud Run URL as the shell.
