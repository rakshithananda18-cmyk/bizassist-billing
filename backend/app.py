"""
app.py — the canonical entry point alias.
=========================================
Historically the FastAPI app was defined in `main_groq.py` (Groq was the first
LLM provider). The app has since grown well past that — it's now the BizAssist
billing ecosystem (`core/`) with AI as one add-on — so the old name is
misleading.

Rather than rename `main_groq.py` (14 files, start.bat, Dockerfile reference it),
this module just re-exports the app under a neutral name. Both work:

    uvicorn app:app          # preferred, going forward
    uvicorn main_groq:app    # still works (legacy)

When everything has migrated to `app:app`, `main_groq.py` can be slimmed to a
one-line shim too.
"""
from main_groq import app  # noqa: F401
