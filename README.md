---
title: BizAssist
emoji: 💎
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# BizAssist — AI-Powered Business Intelligence, Billing & POS Ecosystem

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](#-running-tests)
[![License](https://img.shields.io/badge/license-UNLICENSED-blue)](#)
[![Version](https://img.shields.io/badge/version-1.2.2-blue)](#)

**BizAssist** is a modern, high-performance, offline-first business intelligence, POS, and accounting ecosystem built for retail, wholesale, distribution, and service operations. 

It combines high-speed POS checkout billing, dynamic custom document labeling, automated double-entry accounting with tamper-evident blockchain-style hash chains, multi-location stock & intake management, dual hosting modes (Local & Cloud Sync), and a cost-optimized AI business advisor grounded in local financial data.

---

## 📖 Table of Contents

- [Core Features & Functionality](#-core-features--functionality)
  - [1. POS Counter & Billing Engine](#1-pos-counter--billing-engine)
  - [2. Dynamic Settings & Custom Document Labels](#2-dynamic-settings--custom-document-labels)
  - [3. Financial Invariants & Double-Entry Ledger](#3-financial-invariants--double-entry-ledger)
  - [4. Stock, Intake & Inventory Control](#4-stock-intake--inventory-control)
  - [5. B2B Wholesaling & Customer Tiers](#5-b2b-wholesaling--customer-tiers)
  - [6. Custom Confirmation & Visual Diffing System](#6-custom-confirmation--visual-diffing-system)
  - [7. Dual Hosting Architecture & Sync](#7-dual-hosting-architecture--sync)
  - [8. AI Business Advisor & 4-Tier Intent Router](#8-ai-business-advisor--4-tier-intent-router)
- [🛠️ Technology Stack & Architecture](#-technology-stack--architecture)
- [⚡ Getting Started](#-getting-started)
- [📁 Project Structure](#-project-structure)
- [🧪 Seeding & Performance Benchmarks](#-seeding--performance-benchmarks)
- [📋 Running Tests](#-running-tests)
- [📖 Documentation Directory](#-documentation-directory)

---

## 🚀 Core Features & Functionality

### 1. POS Counter & Billing Engine
* **Barcode-First Checkout**: Rapid barcode scanning, multi-cart tab support, and pure keyboard shortcuts for high-volume sales counters.
* **Flexible Payment Methods**: Supports Cash, UPI (with QR code generation), Card, Net Banking, Wallet, and Credit/Split payments.
* **POS Column Customization**: Show or hide POS billing table columns dynamically (SKU, Unit, Discount %, Tax %, HSN/SAC, MRP, Batch, Serial/IMEI).
* **Multi-Tab Cart Persistence**: Auto-saves active sales tabs per cashier in local storage and safely clears them on bill completion or exit.
* **Auto-Discount & Round Off**: Master toggles for line-item/overall discounts (% or ₹ fixed) and total round-off (Nearest, Round Up, Round Down).

---

### 2. Dynamic Settings & Custom Document Labels
* **App-Wide Document Labeling (`useDocLabels`)**: Rename any business document type in **Settings → Custom Labels** (e.g. *Sales Invoice* ➔ *Tax Bill*, *Credit Note* ➔ *Return Slip*, *Payment Receipt* ➔ *Voucher*). All UI headings, button labels, lists, and PDF print headers update dynamically across the entire application.
* **Privacy Mode**: One-click toggle in Settings to blur financial KPI cards (Revenue, Gross Margin, Overdue) on the dashboard when operating counters in customer-facing environments.
* **Localisation & Precision**: Customizable date formats (`DD/MM/YYYY`, `MM/DD/YYYY`, `YYYY-MM-DD`) and separate decimal precision settings for Quantities (up to 3 decimals) and Amounts.
* **App Lock & Security**: Passcode PIN protection with configurable auto-lock inactivity timeouts.
* **Print & PDF Designer**: Custom theme color pickers, multiple invoice templates (*Classic*, *Modern*, *Thermal*), page sizes (A4, A5, 3-inch Thermal), and custom business logos/watermarks.

---

### 3. Financial Invariants & Double-Entry Ledger
* **Automated Journal Postings**: Every sales checkout, purchase, return, or payment automatically posts balanced `JournalEntry` and `JournalLine` records to the general ledger.
* **Tamper-Evident Hash Chain**: Sequentially links all journal entries using SHA-256 cryptographic hashes. Built-in verification (`verify_chain`) detects any database tampering or raw record manipulation.
* **Period Locking & Financial Controls**: Allows locking historical accounting periods to prevent retroactive modifications to closed books.
* **FIFO Payment Settlement & Advances**: Settle customer dues chronologically (oldest invoice first) with automatic banking of overpayments as advance credit balances.

---

### 4. Stock, Intake & Inventory Control
* **Stock Intake Sheet**: Grid-based batch purchase intake for multi-item inventory stock-in, with landed cost calculations, ROI/Margin forecasting, and batch expiry tracking.
* **Prevent Negative Stock**: Configurable negative stock policy that blocks sales when inventory levels would drop below zero.
* **Multi-Godown / Warehouse Transfers**: Manage stock movements across multiple physical godowns and warehouses with stock ledger audit entries.
* **Barcode & Label Management**: Generate, prefill, and print custom barcode labels for single or bulk items.
* **Bulk Add & Import**: Rapid bulk product creation and CSV data import with interactive column mapping.

---

### 5. B2B Wholesaling & Customer Tiers
* **BizID Connection Network**: Connect suppliers and buyers via unique connection codes (`BizID`) for direct inter-business trading.
* **Customer Price Tiers**: Automatic application of customer-specific price tiers (*Standard*, *Wholesale*, *Distributor*) during counter billing.
* **Network Catalog Sharing**: Share supplier product catalogs with connected buyers for automated purchase order mapping.

---

### 6. Custom Confirmation & Visual Diffing System
* **Context-Driven Dialogs (`useConfirm`)**: Replaces browser-default confirm dialogs with styled modal dialogs across all pages.
* **Field-Level Diffing (`diffFields`)**: Displays side-by-side "Before vs. After" field change summaries when editing existing customers, products, or transactions.
* **Unsaved Changes Protection**: Warns users before closing tabs or navigating away with unsaved bill items or form inputs.

---

### 7. Dual Hosting Architecture & Sync
* **Offline-First Local Operation**: Runs completely offline using local SQLite database storage.
* **Hybrid & Cloud Sync**: Seamlessly syncs local offline transactions to the cloud backend (`/sync/push` and `/sync/pull`) using delta cursor tracking and idempotent outbox queues.
* **Row-Level Security (RLS)**: Enforces multi-tenant isolation at the database level for cloud PostgreSQL deployments.

---

### 8. AI Business Advisor & 4-Tier Intent Router

Every plain-language question or query goes through a cost-optimized 4-tier routing architecture:

```
                  [User Natural Language Query]
                               │
                               ▼
                    ┌─────────────────────┐      0 tokens
                    │ CONVERSATIONAL TIER │ ──► Greetings, off-topic help
                    └─────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐      0 tokens (SQL intent)
                    │  DIRECT INTENT TIER │ ──► "who owes me?", "low stock products"
                    └─────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐      0 tokens
                    │   SEMANTIC CACHE    │ ──► Returns cached insights
                    └─────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐      Low cost (Groq Llama-3.1 8B)
                    │   AI_SIMPLE TIER    │ ──► Single-table summaries, simple filters
                    └─────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐      Adaptive Agent Loop (Groq 70B)
                    │   AI_COMPLEX TIER   │ ──► Multi-source financial reports & trend analysis
                    └─────────────────────┘
```

* **Durable Business Memories (`BusinessFact`)**: Background background processes distill long-term business patterns (e.g. top-moving products, payment behaviors) into durable memory records injected into AI prompt contexts.
* **Audited Action Execution**: The AI can propose actionable steps (e.g., `send_payment_reminders`). Proposed actions undergo a dry-run preview, require explicit user confirmation, and are logged in an immutable `ActionLog`.

---

## 🛠️ Technology Stack & Architecture

* **Frontend**: React 18, Vite, React Router v6, Vanilla CSS (Design system with dark mode, glassmorphism, micro-animations).
  * `frontend-billing/` — Main POS, Billing, Inventory, Accounting & Settings web app.
  * `frontend-ai/` — Conversational AI Advisor & Business Analytics dashboard.
* **Backend**: FastAPI (Python 3.12), SQLAlchemy ORM, Pydantic v2, SQLite / PostgreSQL.
* **Desktop App**: Electron wrapper (`desktop/`) with PyInstaller frozen Python backend for one-click desktop installation.
* **AI Engine**: Groq API (Llama-3.1 8B & Llama-3.3 70B) with local embeddings (`all-MiniLM-L6-v2`) for semantic intent routing.
* **Testing**: Pytest + pytest-xdist (Backend) and Vitest + Testing Library (Frontend).

---

## ⚡ Getting Started

### 1. Install Dependencies
Run the environment setup script to prepare the Python virtual environment and install Node packages for both frontend applications:
```bash
.\dependencies.bat
```

### 2. Configure Environment Variables
Copy `.env.example` to `backend/.env`:
```bash
copy .env.example backend\.env
```

Key environment parameters:

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Powers all AI LLM tiers + adaptive agent loop |
| `JWT_SECRET` | **Yes** | — | Signed JWT token secret key for user authentication |
| `DATABASE_URL` | No | `sqlite:///./bizassist.db` | Target database connection URI |
| `INTENT_ROUTER` | No | `shadow` | Intent router mode (`off` / `shadow` / `on`) |
| `AGENT_MODE` | No | `loop` | `loop` (adaptive tool calling) / `pipeline` |

### 3. Launch Development Servers
Start the backend API (port `8001`), AI Dashboard (port `5173`), and Billing POS App (port `5174`) concurrently:
```bash
.\start_dev.bat
```

---

## 📁 Project Structure

```
bizassist-billing/
├── backend/                  # FastAPI python backend
│   ├── core/                 # Core domains (api, billing, accounting, sync, ai)
│   ├── database/             # SQLAlchemy models & migrations
│   ├── routes/               # REST API route handlers
│   ├── services/             # Background workers & insights services
│   └── tests/                # 970+ Pytest unit & integration tests
├── frontend-billing/         # Primary React + Vite POS & Billing Web App
│   ├── src/
│   │   ├── components/       # POS, Invoice, Stock, Parties & Modal components
│   │   ├── contexts/         # Auth, Confirm, & Theme contexts
│   │   ├── hooks/            # useDocLabels, useConfirm, usePageLifecycle...
│   │   ├── pages/            # Dashboard, Sales, Stock, Money, Settings...
│   │   └── utils/            # invoiceMath, diffFields, logger...
│   └── src/__tests__/        # Vitest frontend unit & component tests
├── frontend-ai/              # React AI Chat & Business Advisor Dashboard
├── desktop/                  # Electron wrapper & PyInstaller packaging scripts
├── docs/                     # Comprehensive architecture, plans & user guides
├── run_tests.bat             # Test runner batch script
└── start_dev.bat             # Concurrent dev server starter
```

---

## 🧪 Seeding & Performance Benchmarks

BizAssist includes high-throughput load testing and database performance benchmark utilities.

### Seed 10,000 Invoices
Seed a high volume of transactions, inventory ledgers, and posted journal entries for stress testing:
```bash
cd backend
..\venv\Scripts\python seed_load_test.py --count 10000
```

### Run Latency Benchmarks
Measure query and serialization response times across reporting endpoints:
```bash
cd backend
..\venv\Scripts\python benchmark_reports.py
```

#### Verified Benchmark Latency Metrics (10k Invoices)
* **Day Book (1-Year Window)**: **~108 ms**
* **Audit Journal (1-Year Window)**: **~489 ms** (N+1 queries eliminated via `selectinload`)
* **Profit & Loss (1-Year Window)**: **~211 ms**
* **Balance Sheet / Trial Balance**: **~21 - 32 ms** (database-level aggregates)

---

## 📋 Running Tests

BizAssist features a comprehensive, dual-suite test architecture (970+ backend tests and 300+ frontend tests).

Run the full parallel test suite across all CPU cores:
```bash
# Run both backend and frontend test suites in parallel mode:
.\run_tests.bat fast

# Or run specific test suites:
.\run_tests.bat backend fast   # Backend Pytest only
.\run_tests.bat frontend       # Frontend Vitest only
```

---

## 📖 Documentation Directory

* **[docs/MASTER_PLAN.md](docs/MASTER_PLAN.md)** — Architectural decisions (D1–D10), roadmap & vision.
* **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — In-depth technology stack & database layer design.
* **[docs/SETUP_AND_DEPLOYMENT.md](docs/SETUP_AND_DEPLOYMENT.md)** — Deployment guides (Hugging Face Spaces, Docker, Vercel).
* **[docs/TESTING.md](docs/TESTING.md)** — Testing strategy, RLS validation & test execution patterns.
* **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — User guide for POS checkout, settings, stock intake & AI queries.
* **[backend/FOUNDATION.md](backend/FOUNDATION.md)** — Backend conventions, tenancy rules, and append-only ledgers.
