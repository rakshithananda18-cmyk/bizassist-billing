# BizAssist

BizAssist is a simple, modern enterprise business intelligence portal. It helps businesses track invoices, manage client billing histories, look at sales telemetry, and ask questions about their business data using an interactive, context-aware AI assistant. It also features an isolated Admin Workspace for administrators to monitor sandbox databases and aggregate metrics across all active accounts.

## Tech Stack

- **Frontend:** Vanilla HTML5, CSS3 (glassmorphic layout with full dark/light theme switching), and clean asynchronous JavaScript.
- **Backend:** FastAPI, SQLite database, SQLAlchemy ORM, and Groq API for the AI assistant chatbot.
- **Testing:** Pytest.

---

## Getting Started

Follow these steps to set up and run the application locally on Windows:

### 1. Set Up the Environment
Double-click or run `dependencies.bat` in your terminal. This will automatically:
- Create a Python virtual environment (`venv`).
- Upgrade `pip`.
- Install all backend dependencies listed in `requirements.txt`.

### 2. Configure Environment Variables
1. Copy `backend/.env.example` and rename it to `backend/.env`.
2. Open `backend/.env` and add your Groq API key:
   ```env
   GROQ_API_KEY=your-actual-api-key-here
   ```

### 3. Run the Backend Server
Run `start.bat` in the root directory. This activates the virtual environment and starts the FastAPI server on `http://localhost:8001` with auto-reload enabled.

### 4. Run the Frontend
Open VS Code, right-click on `frontend/index.html`, and select **Open with Live Server** (or serve the `frontend` folder using any simple HTTP server of your choice on port `5500`).

---

## Running Backend Tests

To run the unit tests, activate the virtual environment and run `pytest`:

```bash
venv\Scripts\activate
python -m pytest
```

---

## Notable Features

- **Context-Aware AI Chatbot:** Talk directly to the Groq-powered AI to ask questions about Stock levels, client debts, overdue invoices, and top customers.
- **Translucent UI Locker:** When logged out, the dashboard is visible in the background but matte-blurred and locked. Signing in fades out the locker and fades in the dashboard.
- **Inline Password Security:** Includes an inline, vector SVG password visibility toggle and dynamic validation rules (Length, Capital, Lowercase, Number, Special) that pop up only after typing pauses for 1 second.
- **Pagination & Grid Safety:** Large listings (Invoices, Payments, Clients) are cleanly paginated. Responsive column tracks prevent wide tables from breaking the layout.
- **Admin Workspace:** Access the admin portal at `/frontend/admin.html` to view register entries, combined total revenues, and sandbox directory logs.
