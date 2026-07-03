# BizAssist Desktop

Electron shell that packages the FastAPI backend (PyInstaller) + both React frontends into one installable, auto-updating desktop app.

## Architecture

```
BizAssist.exe (Electron)
 ├─ spawns  resources/backend/bizassist-backend.exe   → http://127.0.0.1:8001  (FastAPI, hidden)
 ├─ serves  resources/renderer/billing/               → http://127.0.0.1:8450  (main window)
 ├─ serves  resources/renderer/ai/                    → http://127.0.0.1:8451  ("Dashboard BIZASSIST" window)
 └─ tray icon · single-instance · close-to-tray · electron-updater (GitHub Releases)
```

- Frontends are served over `127.0.0.1` (not `file://`) so `frontend-billing/src/config.js` detects "local app" and routes API calls to the local backend — exactly like the web dev setup.
- SQLite DB lives in `%APPDATA%/BizAssist/data/bizassist.db` (`BIZASSIST_DATA_DIR`) → survives updates/uninstalls.
- Backend process tree is force-killed on quit (`taskkill /T /F` on Windows).

| File | Purpose |
|---|---|
| `src/main.js` | boot, windows, tray, shutdown |
| `src/backend.js` | spawn/health-check/kill the PyInstaller backend |
| `src/static-server.js` | zero-dep static server w/ SPA fallback |
| `src/updater.js` | silent download → "Restart now / Later" prompt |
| `../backend/server_entry.py` + `bizassist-backend.spec` | PyInstaller entry & build spec |
| `scripts/build-backend.bat/.sh` | compile backend → `resources/backend` |
| `scripts/prepare-renderer.js` | copy frontend dists → `resources/renderer` |
| `scripts/build-all.bat` | full local Windows installer build |

## Local build (Windows)

```bat
cd desktop
scripts\build-all.bat      :: frontends → backend (PyInstaller) → NSIS installer
:: → desktop\release\BizAssist-Setup-<version>.exe
```

Dev shell (uses Vite dev servers on 5174/5173 + your dev backend):

```bat
cd desktop && npm install && set BIZASSIST_DEV=1 && npx electron .
```

## Releasing an update (CI)

```bash
git tag v1.0.1 && git push origin v1.0.1
```

`.github/workflows/release.yml` then builds Windows + macOS installers and publishes them (plus `latest.yml` update manifests) to GitHub Releases. Installed apps detect the new version within ~4 h (or on relaunch), download silently, and prompt to restart. **The tag must be `v` + the semver you want shipped** — CI syncs `package.json` to the tag automatically.

## Gotchas

- **Repo going private later:** electron-updater + the landing page both read the *public* Releases API. When you flip the repo private, publish releases to a separate public repo (change `build.publish` here and `GITHUB_OWNER/REPO` in `bizassist-landing/src/useLatestRelease.js`) or move to S3/R2 (`provider: generic`).
- **API keys:** the packaged backend reads env vars at runtime; `.env` isn't bundled. Groq/Anthropic AI features need keys present (ship a settings UI or a `.env` in `BIZASSIST_DATA_DIR` — `python-dotenv` loads from CWD, which is the data dir).
- **Installer size:** `sentence-transformers` pulls torch (~240 MB). Swap to `fastembed` in `requirements.txt` to cut the installer dramatically (spec already collects optional pkgs defensively).
- **Code signing:** builds are unsigned by default. Windows SmartScreen / macOS Gatekeeper will warn users; add `CSC_LINK`/`CSC_KEY_PASSWORD` secrets in the workflow when you buy certs.
- **First smoke test:** `scripts/build-backend.bat` health-checks the compiled exe on :8009 before staging.
