# VC-Trading Simulator

A VC-style portfolio simulation tool with multi-user accounts. Track named investment theses, model public and private positions, attach files and notes, maintain verified company profiles, and receive daily email newsletters summarizing performance — without connecting to any brokerage.

Built with FastAPI + SQLite + vanilla HTML/JS. Deployable to Railway in one click.

**Live demo:** <https://vc-simulator.up.railway.app> — sign up with any username to try it.

Built with [Claude Code](https://claude.com/claude-code).

---

## What it does

- **Accounts** — sign up / log in (JWT auth, bcrypt-hashed passwords). Each user's theses, positions, watchlist, and attachments are fully isolated.
- **Thesis portfolios** — group positions under named investment theses (e.g., "AI Infrastructure", "Energy Transition"). Each thesis tracks its own P&L independently and supports freeform notes.
- **Public positions** — add stocks by ticker; prices are fetched live from Yahoo Finance via yfinance. Record entry price at the time you "buy in" and track unrealized gains from there.
- **Private / startup positions** — add companies with an investment amount and entry valuation, expected liquidity date, and liquidity event type (IPO, acquisition, secondary, etc.). Update the valuation whenever you re-run your model. Implied ownership % is locked at entry and applied against the current valuation to compute current value, MOIC, projected IRR, and estimated gain. Shown as expandable cards in the UI.
- **Closed position history** — when you exit a position, it moves to a "Closed" section showing your actual gain alongside a live "if still held" comparison so you can see whether you sold at the right time.
- **Capital gains estimates** — positions held < 365 days are flagged ST (24%), ≥ 365 days LT (15%). After-tax gain is shown for both open and closed positions.
- **Notes & file attachments** — every position can carry freeform notes and uploaded files (decks, memos, cap tables). Files can be previewed in-browser (images, PDFs, text) or downloaded.
- **Company profiles** — a searchable directory of companies (public and private/startup), pre-seeded with the Mag 7. Admin users can verify profiles with a badge; any user can add new companies.
- **Watchlist** — track tickers you're screening but haven't invested in yet, with live price, day change %, P/E, dividend yield, and 52W range.
- **Daily email newsletter** — a formatted HTML email summarizing all thesis performance and watchlist data.

---

## Setup

### 1. Install dependencies

```powershell
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```
JWT_SECRET_KEY=replace_with_a_long_random_secret

EMAIL_SENDER=you@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECIPIENT=you@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

Generate a JWT secret with:
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

> **Gmail App Password** (only needed for the email newsletter): Go to myaccount.google.com → Security → 2-Step Verification → App passwords. Generate one for "Mail". This is not your regular Gmail password.

### 3. Run the web app

```powershell
uvicorn app:app --reload
```

Open `http://localhost:8000` in your browser and sign up for an account.

---

## Using the app

### Theses

Create a thesis from the top bar ("+ New Thesis"). Each thesis card shows:
- Total deployed capital, current value, and overall return %
- Expandable detail panel with open and closed position tables/cards
- Editable notes

### Adding positions

Click **"+ Add Position"** on any thesis card. Toggle between **Private / Startup** (default) and **Public**:

**Private** — enter the company name, your investment amount ($), the company's valuation at entry, and optionally a current valuation (can be updated later), an entry date to backdate the investment, expected liquidity date, and liquidity event type. Notes field for your thesis or assumptions. Files can be attached after the position is created.

**Public** — enter a ticker symbol, share count, an optional entry price (defaults to the live market price), and an optional entry date to backdate a past investment (e.g. "what if I bought NVDA in 2022?"). Leave the date blank to default to today.

### Closing positions

**Private**: click **Exit** on a position card to record an exit valuation (acquisition price, IPO, write-down, etc.). The position moves to "Exited Private Positions" with final MOIC and after-tax gain.

**Public**: click **Close** on the position row. Optionally override the exit price (defaults to live market price). The position moves to the "Closed" section showing actual gain, estimated tax, and the current "if still held" value.

### Updating a private valuation

Click **Edit** on any private position card to open the valuation update modal. Enter your new company valuation and optional notes. The current value, gain, MOIC, and projected IRR update immediately.

### Files

Click **Files** on any position to attach supporting documents (decks, memos, cap tables) or preview/download existing ones. Images, PDFs, and text files can be previewed in-browser.

### Company profiles

Browse or search the Company Profiles section. Add a new company with **"+ Company"**. Admin accounts can verify a company (adds a checkmark badge) or unverify it. Non-admins can edit/delete companies they created.

### Watchlist

Use the Watchlist section at the bottom. Add tickers to monitor for potential entry. Live data includes price, day change %, P/E ratio, dividend yield, and 52W high/low.

### Refreshing prices

Click **↻ Refresh Prices** in the top bar to force a fresh yfinance fetch (bypasses the 5-minute server-side cache).

---

## Daily email newsletter

Run manually, for a given username (defaults to `admin`):
```powershell
python main.py --username yourname
```

Dry run (saves HTML to `preview.html`, does not send):
```powershell
python main.py --dry-run --username yourname
```

The newsletter includes per-thesis cards with position tables, total returns, and the watchlist.

---

## Capital gains rates

Configured at the top of `portfolio.py`:

```python
ST_TAX_RATE = 0.24   # short-term: held < 365 days
LT_TAX_RATE = 0.15   # long-term:  held >= 365 days
```

Change these to match your actual marginal rates.

---

## Deployment (Railway)

1. Push to a GitHub repo.
2. Create a new Railway project → "Deploy from GitHub repo".
3. Add environment variables from your `.env` in the Railway dashboard (Settings → Variables), including `JWT_SECRET_KEY`.
4. Attach a Railway volume mounted at `/app/data` (or set `DB_DIR` to wherever it's mounted) so `tracker.db` persists across deploys.
5. Railway auto-detects `Procfile` and starts the server.

The `Procfile` runs:
```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

---

## Future agents

See [AGENTS_ROADMAP.md](AGENTS_ROADMAP.md) for planned AI agents (patent intelligence, valuation modeling, VC scorecards, summaries, orchestration) and the infrastructure changes needed to support them.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI server — all REST endpoints, auth, attachments, company profiles |
| `auth.py` | JWT token creation/validation, password hashing |
| `database.py` | SQLite schema, migrations, Mag 7 company seed data |
| `portfolio.py` | Thesis/position CRUD, valuation math, cap gains |
| `watchlist_manager.py` | Watchlist CRUD + yfinance market data |
| `email_sender.py` | HTML newsletter builder + SMTP sender |
| `main.py` | CLI entrypoint for sending the daily newsletter |
| `static/index.html` | Single-file SPA frontend |
| `tracker.db` | SQLite database (created on first run) |
| `AGENTS_ROADMAP.md` | Planning doc for future AI agent features |
| `Procfile` | Railway/Heroku start command |
| `railway.json` | Railway deployment config |
| `.env` | Your credentials — never commit this |
| `.env.example` | Template for `.env` |
