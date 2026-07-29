---
title: BizAssist
emoji: 📊
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
app_port: 7860
---

<div align="center">

# BizAssist
### AI-Powered Business Intelligence, POS & Accounting Ecosystem

[![Version](https://img.shields.io/badge/version-1.2.2-blue.svg?style=for-the-badge)](https://github.com/rakshithananda18-cmyk/bizassist-billing)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg?style=for-the-badge)](#-running-tests)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-18.0-61DAFB.svg?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-UNLICENSED-red.svg?style=for-the-badge)](#)

*Offline-first POS, custom document labeling, double-entry ledgers with tamper-evident hash chains, multi-godown stock management, and a 4-tier cost-optimized AI advisor.*

---

[Quick Start](#-quick-start) â€¢ [Features](#-core-features) â€¢ [Architecture](#-architecture--ai-router) â€¢ [Testing](#-running-tests) â€¢ [Docs](#-key-documentation)

</div>

<br />

## ðŸŒŸ Overview

**BizAssist** is an enterprise-grade, offline-first business management platform designed for retail, wholesale, distribution, and service enterprises. It pairs a lightning-fast barcode POS counter with automated double-entry accounting, real-time stock intake, B2B supplier networking, and an LLM-driven business advisor.

---

## âš¡ Quick Start

### 1ï¸âƒ£ Install Dependencies
```bash
.\dependencies.bat
```

### 2ï¸âƒ£ Environment Setup
Copy the example environment file:
```bash
copy .env.example backend\.env
```
Ensure your `backend/.env` contains your key credentials:
```ini
GROQ_API_KEY=your_groq_api_key_here
JWT_SECRET=dev-test-secret-please-change-0123456789abcdef
DATABASE_URL=sqlite:///./bizassist.db
```

### 3ï¸âƒ£ Launch Development Environment
```bash
.\start_dev.bat
```
> **Services Started:**  
> ðŸ”¹ **Backend API:** `http://localhost:8001`  
> ðŸ”¹ **POS Billing App:** `http://localhost:5174`  
> ðŸ”¹ **AI Dashboard:** `http://localhost:5173`

---

## ✨ Core Features

| Feature Module | Description & Capabilities |
| :--- | :--- |
| 🛒 **POS Billing Counter** | Barcode-first scanning, multi-tab carts, keyboard shortcuts, split payments (Cash, UPI QR, Card, Credit). |
| 🛠️ **Master Self-Healing Engine** | 1-click **Auto-Repair Console** (`backend/services/self_healing.py`) for automated hash chain re-sealing, stock ledger alignment, sync outbox recovery, and staff session invalidation. |
| 🏷️ **Dynamic Labels (`useDocLabels`)** | Customize document names (*Sales Invoice*, *Credit Note*, *Debit Note*, *Voucher*). All UI & PDF headers update instantly. |
| 🔒 **Privacy & Security** | 1-click KPI blur mode for public counters, passcode lock, and immediate JWT session invalidation on staff role/password update (`token_version`). |
| 📜 **Audit Hash Chains** | Append-only double-entry ledger (`JournalEntry`) linked by SHA-256 cryptographic hash chains to detect database tampering. |
| 📦 **Stock Intake & Godowns** | Multi-item purchase intake grid with landed cost, batch expiry tracking, and multi-location warehouse transfers. |
| 🤝 **B2B Network & Price Tiers** | Connect buyers & suppliers via BizID codes; auto-apply *Wholesale*, *Distributor*, or *Standard* customer pricing tiers. |
| 🔄 **Dual Hosting & Solid Sync** | Seamless switching between offline local SQLite and cloud PostgreSQL with aggregate document sync, parent UID re-linking, and paginated outbox queues. |

---

## ðŸ¤– Architecture & AI Router

All user queries pass through a 4-tier cost-optimized intent router:

```mermaid
flowchart TD
    A[User Query] --> B{Intent Router}
    B -->|Greetings / Off-topic| C[Tier 1: Conversational - 0 Tokens]
    B -->|Exact Intent / SQL| D[Tier 2: Direct Intent - 0 Tokens]
    B -->|Cached Answers| E[Tier 3: Semantic Cache Hit - 0 Tokens]
    B -->|Simple Data Summaries| F[Tier 4a: AI_SIMPLE - Groq Llama 8B]
    B -->|Complex Analytics| G[Tier 4b: AI_COMPLEX - Groq Llama 70B Adaptive Loop]
```

---

## 🧪 Seeding & Benchmarks

Generate load testing datasets and run dual-mode latency benchmarks:

```bash
# Run enhanced dual-mode benchmarks (Local SQLite + Hybrid Sync)
cd backend
..\venv\Scripts\python benchmark_reports_enhanced.py
```

#### ⚡ Dual-Mode Latency & Throughput Benchmark Summary

| Hosting Mode | Benchmark Operation | Avg Latency | Min Latency |
| :--- | :--- | :--- | :--- |
| **Local (SQLite)** | SHA-256 Hash Chain Verification | `0.91 ms` | `0.52 ms` |
| **Local (SQLite)** | Stock Movement (1 Year, limit 2000) | `2.29 ms` | `1.99 ms` |
| **Local (SQLite)** | Day Book (Today, limit 200) | `3.03 ms` | `2.64 ms` |
| **Local (SQLite)** | Audit Journal (1 Year, limit 2000) | `3.69 ms` | `2.45 ms` |
| **Local (SQLite)** | Balance Sheet (Instant) | `9.92 ms` | `6.64 ms` |
| **Local (SQLite)** | P&L Report (1 Year Window) | `9.93 ms` | `8.38 ms` |
| **Local (SQLite)** | Trial Balance (Instant) | `12.21 ms` | `9.90 ms` |
| **Local (SQLite)** | Master Self-Healing Diagnostic Run | `15.41 ms` | `10.19 ms` |
| **Hybrid (Local+Cloud)** | Outbox Payload Serialization (Invoice) | `< 0.05 ms` | `< 0.05 ms` |
| **Hybrid (Local+Cloud)** | Parent UID FK Resolution Lookup | `< 0.05 ms` | `< 0.05 ms` |
| **Hybrid (Local+Cloud)** | Sync Outbox Queue Drain Batch (20 Items) | `0.45 ms` | `0.40 ms` |
| **Hybrid (Local+Cloud)** | Single-Pass O(N) Hash Re-Sealing | `2.01 ms` | `0.96 ms` |
| **Hybrid (Local+Cloud)** | Redundant Child Line-Item Heal Clearance | `5.54 ms` | `3.96 ms` |

---

## ðŸ§ª Running Tests

BizAssist includes a comprehensive dual test suite (970+ backend tests and 300+ frontend tests).

```bash
# Run both Backend & Frontend test suites in parallel
.\run_tests.bat fast

# Target specific test suites
.\run_tests.bat backend fast   # Pytest (backend)
.\run_tests.bat frontend       # Vitest (frontend)
```

---

## ðŸ“ Repository Structure

```text
bizassist-billing/
â”œâ”€â”€ backend/                  # FastAPI Python Service (API, Billing, Accounting, Sync, AI)
â”‚   â”œâ”€â”€ core/                 # Business logic, command handlers, and algorithms
â”‚   â”œâ”€â”€ database/             # SQLAlchemy schemas, models & migrations
â”‚   â”œâ”€â”€ routes/               # API endpoints
â”‚   â””â”€â”€ tests/                # 970+ Pytest unit & integration tests
â”œâ”€â”€ frontend-billing/         # Primary React POS & Billing Web App
â”‚   â”œâ”€â”€ src/components/       # POS, Invoice, Stock & Modal components
â”‚   â”œâ”€â”€ src/contexts/         # Auth, Confirm, & Theme providers
â”‚   â”œâ”€â”€ src/hooks/            # useDocLabels, useConfirm, usePageLifecycle...
â”‚   â””â”€â”€ src/__tests__/        # 300+ Vitest component & unit tests
â”œâ”€â”€ frontend-ai/              # AI Assistant & Analytics Dashboard
â”œâ”€â”€ desktop/                  # Electron desktop wrapper & build scripts
â”œâ”€â”€ docs/                     # Architecture, user guides & technical decision logs
â”œâ”€â”€ run_tests.bat             # Fast test runner script
â””â”€â”€ start_dev.bat             # Development server launcher
```

---

## ðŸ“– Key Documentation

| Document | Content Summary |
| :--- | :--- |
| ðŸ“Œ **[MASTER_PLAN.md](docs/MASTER_PLAN.md)** | Core vision, architectural decisions (D1â€“D10), roadmap. |
| ðŸ—ï¸ **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Layer-by-layer system architecture & data flows. |
| ðŸš€ **[SETUP_AND_DEPLOYMENT.md](docs/SETUP_AND_DEPLOYMENT.md)** | Local environment setup, Docker & cloud deployment guide. |
| ðŸ§ª **[TESTING.md](docs/TESTING.md)** | Testing strategy, RLS tenant isolation & benchmark instructions. |
| ðŸ“˜ **[USER_GUIDE.md](docs/USER_GUIDE.md)** | User manual for POS operations, custom labels, and AI queries. |
| ðŸ›ï¸ **[FOUNDATION.md](backend/FOUNDATION.md)** | Backend conventions, tenant isolation, and transaction safety. |

---

<div align="center">
  <sub>Built with â¤ï¸ for modern businesses â€¢ BizAssist Engine</sub>
</div>
