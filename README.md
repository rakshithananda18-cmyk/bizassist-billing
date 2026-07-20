---
title: BizAssist
emoji: 💎
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# BizAssist — AI-Powered Business Intelligence & Billing Ecosystem

BizAssist is a high-performance, local-first business intelligence assistant and billing system designed for all scales of operations, including retail, distribution, wholesale, and service businesses. 

It integrates high-speed POS checkout billing, automated double-entry ledger postings with tamper-evident blockchain-style hash chains, multi-tenant supplier-buyer connection networks, offline-first data sync, and an AI-driven advisor that reasons over grounded local data.

---

## 📖 Key Documentation

*   **[docs/MASTER_PLAN.md](docs/MASTER_PLAN.md)** — The map: vision, settled decisions (D1–D10), build status, moats, risks. Start here.
*   **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — Technology architecture and stack decisions, layer by layer.
*   **[docs/SETUP_AND_DEPLOYMENT.md](docs/SETUP_AND_DEPLOYMENT.md)** — Developer environment setup, database options, and deployment (HF Spaces + Vercel).
*   **[docs/TESTING.md](docs/TESTING.md)** — Layered test strategy (pytest, Vitest, Playwright, RLS/testcontainers) and how to run it.
*   **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — User guide for the POS checkout, dashboard, uploads, and AI queries.
*   **[docs/STRATEGIC_REVIEW_JUL2026.md](docs/STRATEGIC_REVIEW_JUL2026.md)** — Current expert review: USPs, BizID moat, risks, P0–P2 recommendations, scorecard.
*   **[backend/FOUNDATION.md](backend/FOUNDATION.md)** — Backend conventions every feature inherits (tenancy, append-only money, command handlers).
*   `docs/plans/` — active feature plans (invoice templates, subscriptions, admin console, agentic blueprint, R5 sales decomposition…).
*   `docs/archive/` — superseded plans, reviews, audits, and benchmarks kept for history.

---

## 🚀 Core Features

### 1. High-Speed POS Counter & Pricing Model
*   **POS Interface**: Barcode-first scanning, multi-tab billing, keyboard-only checkout shortcuts, and payment method mapping (Cash, UPI, Card, Wallet).
*   **Pricing & Savings**: Implements "MRP-as-price + discount-as-savings" pricing. Calculated buyer discounts are locked relative to MRP, and price structures support client-scoped tiers (Wholesale, Distributor, Standard).

### 2. Posted Double-Entry Journal (Audit Trail)
*   **Automated Journaling**: Real-time posting of balanced `JournalEntry` and `JournalLine` records for checkouts, invoices, and payments.
*   **Tamper-Evident Hash Chain**: Links all journal entries sequentially using SHA-256 hashing. Includes a validation utility (`verify_chain`) to detect database tampering.

### 3. Multi-Tenant B2B Wholesaling
*   **BizID Connections**: Secure account bridging between suppliers and buyers via connection codes.
*   **Network Sharing**: Direct sharing of supplier catalogs with buyers, enabling seamless B2B purchase orders that map instantly to supplier sales orders under margin-protection rules.

### 4. Offline Sync & Row-Level Security (RLS)
*   **Offline-First**: Local SQLite client operations supporting delta syncing with the main database server using autoincrement ID cursor checks (`/sync/pull` and `/sync/push`).
*   **Tenant Isolation**: Hardened Row-Level Security (RLS) policies at the database level to ensure strict multi-merchant isolation.

### 5. Responsive UI & Accessibility
*   **Modern Layouts**: Fully responsive interface featuring collapsible sidebar navigation, horizontal sliding mobile tabs, responsive carts with horizontal scroll, and screen-reader accessibility (`aria-label`) tags.

### 6. Performance Guardrails
*   **Pagination limits**: Hard limit of 2,000 rows on Day Book, Sales Register, and Audit Journal list endpoints to prevent memory exhaustion.

---

## 🤖 AI Business Advisor & 4-Tier Routing Architecture

Every plain-language question or query goes through a cost-gated routing model that minimizes API costs and guarantees response speed:

```
[User Query]
     │
     ▼
┌──────────────┐      0 tokens
│ CONVERSATIONAL│ ──► Quick greetings, off-topic help
└──────────────┘
     │
     ▼
┌──────────────┐      0 tokens (SQL intent)
│ DIRECT/INTENT│ ──► "who owes me?", "low stock products", "total sales"
└──────────────┘
     │
     ▼
┌──────────────┐      0 tokens
│  CACHE HIT   │ ──► Returns matching cached queries
└──────────────┘
     │
     ▼
┌──────────────┐      Low cost (Groq Llama-3.1 8B)
│  AI_SIMPLE   │ ──► Single-table summaries, simple filters
└──────────────┘
     │
     ▼
┌──────────────┐      Adaptive Agent Loop (Groq Llama-3.3 70B)
│  AI_COMPLEX  │ ──► Multi-source analysis, business health reports
└──────────────┘
```

*   **Durable Memories (`BusinessFact`)**: A weekly background job distills long-term business patterns (e.g. late-paying customers, high-moving products) into durable fact records, injecting them into prompt context so the AI advisor remains contextualized without scanning full history.
*   **Gated Actions**: The AI can propose actionable steps (e.g., `send_payment_reminders`). Actions undergo a dry-run **preview**, require explicit user **confirmation**, and are fully audited in the `ActionLog`.

---

## 🛠️ Technology Stack

*   **Frontend**: React + Vite (two independent apps: `frontend-billing/` for POS, and `frontend-ai/` for the advisor/dashboard).
*   **Backend**: FastAPI (Python), SQLAlchemy ORM, SQLite/PostgreSQL (configured via `DATABASE_URL` in `.env`).
*   **AI Engine**: Groq API (Llama-3.1 8B/70B) and local MiniLM embeddings (`all-MiniLM-L6-v2`) for semantic routing.
*   **Testing**: Pytest (backend) + Vitest (frontend).

---

## ⚡ Getting Started (Windows)

### 1. Install Backend & Frontend Dependencies
Run the root setup utility to prepare the virtual environment, install all python packages, and install dependencies for both React frontend directories:
```bash
.\dependencies.bat
```

### 2. Configure Environment Variables
Copy `.env.example` to `backend/.env` and update it:
```bash
copy .env.example backend\.env
```
Fill in the configuration parameters:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Powers all LLM tiers + adaptive agent loop |
| `JWT_SECRET` | **Yes** | — | Signed JWT token secret key for user authentication |
| `DATABASE_URL` | No | `sqlite:///./bizassist.db` | Target database connection URI |
| `INTENT_ROUTER` | No | `shadow` | Embedding shadow router: `off` / `shadow` / `on` |
| `AGENT_MODE` | No | `loop` | AI_COMPLEX mode: `loop` (adaptive tool-calling) / `pipeline` |
| `EMAIL_USER` / `EMAIL_PASS` | No | — | SMTP credentials to send real payment reminders |

### 3. Launch Development Servers
Start the backend API (port `8001`), the AI Dashboard (port `5173`), and the POS Billing App (port `5174`) concurrently:
```bash
.\start_dev.bat
```

---

## 🧪 Seeding & Report Performance Benchmarks

BizAssist comes equipped with a high-throughput load testing and benchmarking suite.

### 1. Seed 10,000 Invoices
Seed a high volume of transactions, stock ledgers, and posted journal entries for performance checks:
```bash
cd backend
..\venv\Scripts\python seed_load_test.py --count 10000
```
*(Uses SQLite PRAGMA speeds to complete 10k database commits in under 2 minutes)*

### 2. Run Latency Benchmarks
Run tests measuring database query and serialization response times across reporting paths:
```bash
cd backend
..\venv\Scripts\python benchmark_reports.py
```

### High-Scale Performance Latency Metrics (10k Invoices)
*   **Day Book (1 Year Window)**: **~108 ms** (SQLAlchemy tracking bypassed using specific scalar selects).
*   **Audit Journal (1 Year Window)**: **~489 ms** (N+1 queries eliminated via `selectinload` prefetching).
*   **Profit & Loss (1 Year Window)**: **~211 ms** (optimized SQL date windowing joins).
*   **Balance Sheet / Trial Balance**: **~21 - 32 ms** (computed using database-level aggregates).

---

## 📋 Running Tests

To run the complete test suite (containing over 600 backend test cases):
```bash
.\run_tests.bat
```
*(Or run directly inside the `backend/` directory: `..\venv\Scripts\pytest`)*
