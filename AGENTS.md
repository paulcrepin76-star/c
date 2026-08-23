# AGENTS.md

## Cursor Cloud specific instructions

### What this repo is
A self-hosted restaurant back-office stack ("resto"). The two custom apps live under `apps/`:
- `apps/resto-core` — the primary product: a FastAPI + Jinja2 web app (wine cellar, inventory, costing, purchasing, invoices, `/connect` OAuth flows). Entry point `app.main:app`.
- `apps/price-collector` — optional Playwright/Chromium supplier price scraper. Entry point `app.main:app`.

Everything else in `compose.yml` (postgres, paperless-ngx, mealie, n8n, metabase, redis, tika, gotenberg, home-assistant, frigate) is an off-the-shelf image. See `README.md` and `docs/ARCHITECTURE.md` for the big picture.

### Python environment
A single virtualenv at `/workspace/.venv` serves both apps (the update script creates/refreshes it). Both apps use `pip` + per-app `requirements.txt` (no lockfile). `apps/resto-core` uses `>=` ranges; `apps/price-collector` pins exact versions of the overlapping packages, so install resto-core first, then price-collector (the update script already does this).

### Tests (no services required)
- resto-core: `cd apps/resto-core && /workspace/.venv/bin/python -m pytest -q` (69 tests). Runs against SQLite in-process; `tests/conftest.py` forces `DATABASE_URL=sqlite://` and disables the network integrations.
- price-collector: `cd apps/price-collector && /workspace/.venv/bin/python -m pytest -q` (7 tests). Its unit tests do NOT need a Playwright browser.
- `make test` also works but only covers resto-core and re-runs a `pip install`.

### Running resto-core in dev (uvicorn)
Docker is NOT installed in this environment, so the `docker compose` / `make up` path (the intended production deployment) does not run here. For a dev loop, run the app directly:

```
cd apps/resto-core
DATABASE_URL="sqlite:////workspace/appdata/resto-core/dev.db" \
SECRET_KEY=dev-secret RESTO_API_KEY=dev-api-key \
CATALOG_SCAN_ENABLED=false OPEN_PRICES_ENABLED=false BLS_ENABLED=false \
/workspace/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
```

Then open `http://localhost:8088` (dashboard), `/wines` (cellar), `/health`. The app auto-creates its schema and seeds demo data on startup (`lifespan` in `app/main.py`).

Non-obvious gotchas:
- Config is loaded via `pydantic-settings` from a `.env` file in the app's working directory plus environment variables. There is no committed `.env` for resto-core; without overrides `DATABASE_URL` defaults to `postgresql://resto:resto@localhost:5432/resto` (no local Postgres here), so set `DATABASE_URL` to a SQLite path for local dev. SQLite is fully supported (the whole test suite, including page rendering, runs on it).
- Set `CATALOG_SCAN_ENABLED=false`, `OPEN_PRICES_ENABLED=false`, `BLS_ENABLED=false` for local dev to avoid outbound network calls tied to those integrations. All external integrations (Square/Mealie/Paperless/USDA/Ollama) are credential-gated and default to disabled/empty.
- `uvicorn --reload` is not enabled by default; add `--reload` if you want hot reload while editing.

### price-collector full run (optional)
Running the actual scraper needs Playwright browsers (`playwright install chromium`) plus the Xvfb/noVNC stack from `apps/price-collector/entrypoint.sh` (only present in its Docker image). Not needed for its unit tests. It is described as a "last resort" and core costing works without it.
