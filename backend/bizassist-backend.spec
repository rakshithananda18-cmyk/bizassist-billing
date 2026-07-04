# -*- mode: python ; coding: utf-8 -*-
"""
bizassist-backend.spec — PyInstaller build for the FastAPI backend.

Run from backend/:   pyinstaller bizassist-backend.spec --noconfirm
Output:              dist/bizassist-backend/   (onedir — faster startup,
                     plays nicer with torch/chromadb than onefile)

⚠ Size note: sentence-transformers pulls torch (~240 MB). If installer size
matters, swap it for `fastembed` in requirements and drop the torch collects.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = [
    # uvicorn's dynamic imports
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # app modules imported via strings / lazily
    "app",
    "main_groq",
    "passlib.handlers.bcrypt",
    "apscheduler.triggers.interval",
    "apscheduler.triggers.cron",
]
hiddenimports += collect_submodules("routes")
hiddenimports += collect_submodules("services")
hiddenimports += collect_submodules("database")
hiddenimports += collect_submodules("core")

datas, binaries = [], []

# Packages that ship data files / native libs PyInstaller misses on its own.
for pkg in ("chromadb", "tiktoken_ext", "onnxruntime", "tokenizers", "transformers",
            "sentence_transformers", "langgraph", "langchain_core"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # optional pkg not installed — skip

# Alembic migrations so the frozen app can migrate the user's DB.
datas += [("alembic", "alembic"), ("alembic.ini", ".")]

# Business template configs (core/templates/configs/*.json). Without these the
# packaged app's /business/templates returns nothing and the signup "Business
# Category" dropdown is empty in the desktop app.
datas += [("core/templates/configs", "core/templates/configs")]

a = Analysis(
    ["server_entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "pytest", "testcontainers", "playwright",
        "tkinter", "matplotlib", "IPython", "jupyter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bizassist-backend",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # quiet — no console window on Windows
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="bizassist-backend",
)
