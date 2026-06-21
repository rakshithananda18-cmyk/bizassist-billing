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
| **Supabase (online)** | the Supabase connection string | none locally | Shared/online data; this is what Hugging Face uses. |
| **Local Postgres** | `postgresql://postgres:devpass@localhost:5432/bizassist` | install Postgres (section 4) | Only when you need to test Postgres behaviour locally. |

**Recommendation:** use **SQLite** for everyday local dev (no friction), and
**Supabase** for Hugging Face / production. Local Postgres is optional.

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

## 7. Deploying to Hugging Face

- HF builds the backend from `backend/Dockerfile`, which installs
  `backend/requirements_hf.txt` (separate from local `requirements.txt`).
- Set `DATABASE_URL` (the Supabase URL) and `GROQ_API_KEY` as **Space Secrets**,
  not in any committed file.
- HF storage is ephemeral, which is exactly why production uses Supabase.

---

## New-computer cheat sheet

```
git clone <repo>
cd bizassist
.\dependencies.bat
copy backend\.env.example backend\.env   # then add GROQ_API_KEY (+ DATABASE_URL if not SQLite)
.\start_dev.bat
```
With SQLite (the default), that's the whole process. Postgres only adds section 4.
