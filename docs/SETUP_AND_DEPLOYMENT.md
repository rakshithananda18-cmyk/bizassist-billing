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

---

# Ecosystem Deployment Guide — HF Spaces & Vercel

This guide outlines the steps to publish only the backend to Hugging Face Spaces and deploy the two frontend applications (`frontend-billing` and `frontend-ai`) to Vercel.

---

## 🏗️ Architecture Overview

```mermaid
graph TD
    Client1[POS Billing Frontend - Vercel] -->|API Requests| HF[FastAPI Backend - HF Spaces]
    Client2[AI Assistant Frontend - Vercel] -->|API Requests| HF
    HF --> DB[(Supabase Postgres or SQLite)]
```

> [!IMPORTANT]
> The backend acts as the central API. Both Vercel frontends communicate with it via the `VITE_API_URL` environment variable.

---

## 1. Backend: Deploy to Hugging Face Spaces (Docker SDK)

Hugging Face Spaces supports running custom Dockerfiles on a free tier (2vCPU, 16GB RAM). We have already configured a `Dockerfile` and `.dockerignore` inside the `backend/` folder.

### Step 1: Create a Space on Hugging Face
1. Log in to [Hugging Face](https://huggingface.co/).
2. Click **Spaces** > **Create new Space**.
3. Fill in your details:
   - **Space name**: e.g., `bizassist-backend`
   - **SDK**: Select **Docker** (under custom options, choose **Blank** template).
   - **Visibility**: Public or Private (Public is recommended for API access).

### Step 2: Initialize Git inside `backend/` and Push
Since you only want to publish the backend to HF, initialize Git directly inside the `backend` folder:

```bash
# Navigate to the backend directory
cd backend

# Initialize Git repository
git init

# Track all backend code files (the .gitignore ensures DB and secrets are ignored)
git add .

# Create the initial commit
git commit -m "Initial commit of BizAssist Backend"

# Add the Hugging Face Space remote
git remote add origin https://huggingface.co/spaces/YOUR_HF_USERNAME/YOUR_SPACE_NAME

# Force push to main (HF Spaces default branch is main)
git push -u origin main --force
```

### Step 3: Configure Environment Variables in HF Spaces
Go to your Space page, navigate to **Settings** > **Variables and secrets**, and add the required secrets:
* `GROQ_API_KEY`: Your Groq AI key.
* `SUPABASE_URL`: (If migrating database to Supabase Postgres).
* `SUPABASE_KEY`: (If using Supabase).
* `JWT_SECRET`: For auth token signing.

---

## 2. Frontends: Deploy to Vercel (Monorepo Setup)

You do **not** need to create separate repositories for the frontends. Vercel supports deploying subdirectories directly from a single monorepo.

### Option A: The Monorepo Approach (Recommended)
1. Push the entire workspace (containing both frontends and docs) to a single private GitHub repository.
2. In Vercel, import that repository **twice** (once for each frontend).

#### Project 1: POS Billing (`frontend-billing`)
1. In Vercel Dashboard, click **Add New** > **Project** and select your GitHub repository.
2. In the configuration:
   - **Framework Preset**: Select **Vite** or leave as **Other**.
   - **Root Directory**: Click Edit, select **`frontend-billing`**.
3. Under **Environment Variables**, add:
   - Key: `VITE_API_URL`
   - Value: `https://YOUR_HF_USERNAME-YOUR_SPACE_NAME.hf.space` (Your HF Space public API URL).
4. Click **Deploy**.

#### Project 2: AI Assistant (`frontend-ai`)
1. In Vercel Dashboard, click **Add New** > **Project** and import the same repository again.
2. In the configuration:
   - **Framework Preset**: Select **Vite** or leave as **Other**.
   - **Root Directory**: Click Edit, select **`frontend-ai`**.
3. Under **Environment Variables**, add:
   - Key: `VITE_API_URL`
   - Value: `https://YOUR_HF_USERNAME-YOUR_SPACE_NAME.hf.space`
4. Click **Deploy**.

---

### Option B: Separate Repositories
If you prefer completely separate repositories:
1. Initialize git inside `frontend-billing` and push to its own repository.
2. Initialize git inside `frontend-ai` and push to its own repository.
3. Import each project separately into Vercel (no root directory edits needed).
4. Configure `VITE_API_URL` in both Vercel dashboard projects.

---

## 3. Post-Deployment Verification

Once all three parts are deployed, verify connectivity:
1. Open the Vercel URL for `frontend-billing` in your browser.
2. Verify you can sign in/sign up (which will request auth from your HF Space backend).
3. Open `frontend-ai` and verify the AI Chat responds to commands.

---

## 4. Running Database Migrations on Production (Alembic)

Since the backend application does not automatically run Alembic migrations on startup, you must apply new migrations manually to the production database when you release schema changes.

### Step 1: Get the Production Database URL
Retrieve the connection string from your Supabase Dashboard or the Hugging Face Space secrets. The URL looks like:
`postgresql://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres`

Do not commit the real URL, paste it into docs, or keep it in the local repo.
For production, store it only in the Hugging Face Space secrets as
`DATABASE_URL`. Local development should keep using SQLite, for example:

```env
DATABASE_URL=sqlite:///./bizassist.db
```

### Step 2: Run the Migration command
Navigate to the `backend` directory, activate the Python virtual environment,
temporarily set the `DATABASE_URL` environment variable from your secrets
manager, and execute the upgrade command. Do this only for a deliberate
production migration session.

#### On Windows (PowerShell):
```powershell
# Navigate to backend
cd backend

# Set environment variable (temporary for this session)
$env:DATABASE_URL="<SUPABASE_DATABASE_URL_FROM_SECRET>"

# Execute migration to head
& ..\venv\Scripts\python -m alembic upgrade head
```

#### On Linux / macOS / Bash:
```bash
# Navigate to backend
cd backend

# Run migration
DATABASE_URL="<SUPABASE_DATABASE_URL_FROM_SECRET>" python -m alembic upgrade head
```

### Step 3: Rolling Back Migrations
If you need to undo a migration, use the `downgrade` command:

#### On Windows (PowerShell):
```powershell
& ..\venv\Scripts\python -m alembic downgrade -1
```

#### On Linux / macOS / Bash:
```bash
DATABASE_URL="<SUPABASE_DATABASE_URL_FROM_SECRET>" python -m alembic downgrade -1
```

### Step 4: Verification
To check if the migration was successfully applied, run a quick query to inspect rowsecurity (RLS) on your tables:
```python
from sqlalchemy import create_engine, text
engine = create_engine("DATABASE_URL_HERE")
with engine.connect() as conn:
    res = conn.execute(text("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public'")).fetchall()
    for row in res:
         print(row[0], "RLS Enabled:", row[1])
```

