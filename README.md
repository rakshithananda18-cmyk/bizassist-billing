# BizAssist

## Documentation

- **[SETUP.md](SETUP.md)** - clone-to-run setup for any computer (dependencies, `.env`, database options, local Postgres, running, tests, deploy).
- **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** - end-user guide to using the app (AI Assistant, data pages, uploads, alerts, actions).


BizAssist is a business-intelligence assistant for Indian distributors and small businesses. Owners upload their invoices, inventory and payments (CSV/XLSX/PDF) and then ask plain-language questions — "who owes me the most?", "what's expiring this month?", "why is my collection rate low?" — and get grounded, data-backed answers, advice, and one-tap actions (payment reminders, escalations, reorder drafts). An isolated Admin workspace monitors usage, rate limits, and per-merchant data.

Answers are **grounded**: the models reason only over real numbers pulled from the database, never fabricated.

## Tech Stack

- **Frontend:** React + Vite (`frontend-ai/` for the AI Dashboard, and `frontend-billing/` for the Billing Frontend).
- **Backend:** FastAPI, SQLAlchemy, SQLite (Alembic migrations), Groq API for the LLM tiers, and a local MiniLM embedding model (no API cost) for semantic routing and chat memory.
- **Testing:** Pytest (backend) + Vitest (frontend).

## Architecture (short version)

Every question flows through a cost-tiered router:

`CONVERSATIONAL → DIRECT (DB only, 0 tokens) → CACHE → AI_SIMPLE (8B) → AI_COMPLEX (adaptive 70B agent loop)`

plus `AI_ADVISE` (data + grounded advice) and gated `ACTION` previews. A newer one-shot **LLM router** can steer this (see `LLM_ROUTER` below); the legacy regex+embedding router is the always-on fallback. Design details live in [`docs/`](docs/).

---

## Getting Started (Windows)

### 1. Backend dependencies
Run `dependencies.bat` — creates the `venv`, upgrades pip, installs `requirements.txt`.

### 2. Environment variables
Copy `.env.example` to `backend/.env` and fill it in (see the table below). At minimum set `GROQ_API_KEY` and `JWT_SECRET`.

### 3. Run the backend
Run `start.bat` (or `start_dev.bat`) — starts FastAPI on `http://localhost:8001`.

### 4. Run the frontends
Frontend packages are installed automatically by `dependencies.bat`. To start them manually:
```bash
# AI Dashboard (default: port 5173)
cd frontend-ai
npm run dev

# Billing Frontend (default: port 5174)
cd frontend-billing
npm run dev
```

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | **yes** | — | LLM calls (8B/70B tiers + LLM router) |
| `JWT_SECRET` | **yes** | — | Auth token signing |
| `DATABASE_URL` | no | local SQLite | DB connection string |
| `LLM_ROUTER` | no | `off` | Router mode at startup: `off` (legacy) / `shadow` / `on` (new). Can be flipped live in Admin, but that override is in-memory and resets to this value on restart. |
| `LLM_ROUTER_CONF_FLOOR` | no | `0.6` | Below this confidence the LLM router defers to legacy |
| `AGENT_MODE` | no | `pipeline` | `loop` = adaptive tool-calling agent for AI_COMPLEX; `pipeline` = fixed fan-out |
| `INTENT_ROUTER` | no | `off` | Embedding shadow router: `off` / `shadow` / `on` |
| `EMAIL_USER`, `EMAIL_PASS` | no | — | SMTP for sending real payment reminders; without them reminders are drafted + logged only |
| `LOG_LEVEL` | no | `INFO` | Logging verbosity |

> **Deploying to Hugging Face Spaces:** set the above as Space *secrets/variables*. The Admin router-mode switch is per-process and non-persistent, so set `LLM_ROUTER` to your desired default. The 70B (AI_COMPLEX) tier is subject to Groq's daily token cap — upgrade the Groq tier for heavy use.

---

## Tests

```bash
run_tests.bat          # backend (pytest) + frontend (vitest)
```
Or directly: `venv\Scripts\activate && python -m pytest`.

## Sample data

`generate_sample_data.py` writes compatible CSVs into `sample_data/` (invoices, inventory with cost/selling prices, payments). Upload them through the app to try every feature. `MANUAL_TEST_QUERIES.md` (in `docs/`) lists test queries with expected results.

## Load Testing & Performance Benchmarks

To ensure the billing reports, ledgers, and registers scale to tens of thousands of transactions, the application includes a performance load-testing suite under `backend/`:

1. **Seed Load Test Data**:
   ```bash
   # From the backend directory, seed 10,000 invoices + stock ledgers + journals
   ..\venv\Scripts\python seed_load_test.py --count 10000
   ```
   Uses SQLite connection-speed optimizations (`PRAGMA synchronous = OFF`) to insert data at ~73 invoices/second.

2. **Benchmark Reporting Latency**:
   ```bash
   # Measure exact DB query and serialization latency across reports
   ..\venv\Scripts\python benchmark_reports.py
   ```

### Scalability Milestones (10k Invoices Load)
- **N+1 Query Elimination**: Pre-fetches journal lines in a single query using SQLAlchemy `selectinload` for the Audit Journal and Hash Chain verification.
- **ORM Overhead Bypass (12x Day Book Speedup)**: Bypasses SQLAlchemy tracking in `report_day_book` by selecting specific scalar columns, dropping latencies from **1.32s** to **108ms**.
- **Pagination & DB-level Aggregates**: Added limits/offsets to all journal tables and shifted totals calculations to database-level aggregate functions (`func.sum`).

