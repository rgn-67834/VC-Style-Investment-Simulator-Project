# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-user VC-style portfolio simulation tool. Users create named investment "theses" and track public stock positions (live-priced via yfinance) and private/startup positions (manually valued, with implied ownership locked at entry). FastAPI backend + SQLite, single-file vanilla JS/HTML frontend, deployed to Railway. No build step, no test suite, no frontend framework.

## Commands

```powershell
pip install -r requirements.txt          # install deps
uvicorn app:app --reload                  # run the web app locally (http://localhost:8000)
python main.py --dry-run --username X     # generate the email newsletter to preview.html without sending
python main.py --username X               # send the daily email newsletter for real
```

There is no test suite, linter, or build step configured in this repo.

## Architecture

**Backend layering** (strict): `app.py` (FastAPI routes, request/response only) → `portfolio.py` / `watchlist_manager.py` (business logic, all functions take `user_id` as the first arg) → `database.py` (`get_conn()` raw sqlite3 access). Routes never touch SQL directly except for simple lookups in `app.py` itself (auth, attachments, companies); thesis/position/watchlist logic always goes through the data-layer functions. Keep this separation when adding features.

- **`database.py`** — owns the schema (`init_db()`), one-time `ALTER TABLE` migrations (wrapped in try/except so they're safe to re-run), and `seed_companies()` (Mag 7 seed data). `DB_PATH` resolves from `DB_DIR` env var (set on Railway to a mounted volume) or falls back to the project directory — `tracker.db` must persist across deploys via that volume.
- **`portfolio.py`** — all thesis/position math. Every write function takes `user_id` first and resolves the thesis via `_get_thesis_id()` (raises `ValueError` if not found/owned — these become 400s in `app.py`). Private positions store `investment` + `entry_valuation`; current value is always *recomputed* as `(investment / entry_valuation) * current_valuation` (implied ownership locked at entry, not stored). DCF models (`compute_dcf`, `save_dcf_model`, `get_dcf_models`, `delete_dcf_model`) also live here: rates are stored as decimals, each row in `dcf_models` is an immutable dated snapshot tied to a private position (cascade-deleted with it), and the frontend never does DCF math itself — it calls `/api/dcf/preview`. `get_all_thesis_data()` is the single aggregator that enriches and returns the full nested structure (theses → open/closed public + private positions) consumed directly by the frontend.
- **`auth.py`** — JWT (`python-jose`), 7-day expiry, bcrypt password hashing (passwords truncated to 72 bytes before hashing — a hard bcrypt limit). `get_current_user` is the FastAPI dependency used on every protected route.
- **`app.py`** — per-user in-memory cache (`_cache` dict, 300s TTL) wraps `get_all_thesis_data`/`get_watchlist_data` to avoid refetching yfinance prices on every request; call `_bust(user_id)` after any write. **Route ordering matters**: more specific path templates must be declared before less specific ones with the same arity (e.g. `/api/attachments/{attachment_id}/download` must come before `/api/attachments/{entity_type}/{entity_id}`, or FastAPI matches the wrong route and 422s on type coercion).
- **`static/index.html`** — entire frontend in one file (HTML + CSS + vanilla JS, no build step, no framework). Auth token stored in `localStorage` as `tt_jwt`; `authFetch()` wraps `fetch` with the bearer header and throws on 401. `apiErrMsg()` normalizes FastAPI error shapes (string detail vs. Pydantic 422 array) for display. UI defaults to the Private/Startup position type first (VC-centric), not public stocks.
- **`email_sender.py`** — builds the newsletter HTML via plain `str.format()` templates (not Jinja, despite a similar pattern) and sends via SMTP. `main.py` is the CLI entrypoint for this — it is the *only* CLI in the project; `portfolio.py` and `watchlist_manager.py` are pure libraries with no `__main__`.

## Conventions to preserve

- Cap gains: short-term (<365 days held) = 24%, long-term (≥365 days) = 15%, configured as `ST_TAX_RATE`/`LT_TAX_RATE` constants at the top of `portfolio.py`.
- Write functions in `portfolio.py`/`watchlist_manager.py` raise `ValueError` with a user-facing message on bad input; `app.py` routes catch that specific exception and convert to `HTTPException(400, str(e))`. Don't introduce other exception types for expected validation failures.
- SQLite writes always go through `with get_conn() as conn:` (commits on successful exit, no manual `commit()` calls) — never reuse a connection across requests.
- New schema columns are added via the `ALTER TABLE ... ADD COLUMN` try/except block in `database.py:init_db()`, never by editing the original `CREATE TABLE` for already-shipped tables (so existing deployed SQLite files migrate safely on startup).
- File attachments are stored as BLOBs in the `attachments` table (not on disk), tied to `(entity_type, entity_id)` pairs — `entity_type` is `"position"` or `"private_position"`.
- Company profiles (`companies` table) are global, not per-user; `is_verified`/`verified_by` can only be set by users with `is_admin=1`.
