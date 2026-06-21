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
