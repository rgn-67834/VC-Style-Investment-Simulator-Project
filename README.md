# VC-Trading Simulator

A VC-style portfolio simulation tool. Track named investment theses, model public and private positions, and receive daily email newsletters summarizing thesis performance — without connecting to any brokerage.

Built with FastAPI + vanilla HTML/JS. Deployable to Railway in one click.

---

## What it does

- **Thesis portfolios** — group positions under named investment theses (e.g., "AI Infrastructure", "Energy Transition"). Each thesis tracks its own P&L independently.
- **Public positions** — add stocks by ticker; prices are fetched live from Yahoo Finance via yfinance. Record entry price at the time you "buy in" and track unrealized gains from there.
- **Private / startup positions** — add companies with an investment amount and entry valuation. Update the DCF valuation whenever you re-run your model. Implied ownership % is locked at entry and applied against the current valuation to compute current value, MOIC, and estimated gain.
- **Closed position history** — when you exit a position, it moves to a "Closed" section showing your actual gain alongside a live "if still held" comparison so you can see whether you sold at the right time.
- **Capital gains estimates** — positions held < 365 days are flagged ST (24%), ≥ 365 days LT (15%). After-tax gain is shown for both open and closed positions.
- **Watchlist** — track tickers you're screening but haven't invested in yet, with live price, day change %, P/E, dividend yield, and 52W range.
- **Daily email newsletter** — a formatted HTML email summarizing all thesis performance, top movers, and watchlist data.

---

## Setup

### 1. Install dependencies

```powershell
pip install -r requirements.txt
```

### 2. Configure email credentials

Copy `.env.example` to `.env` and fill in your values:

```
EMAIL_SENDER=you@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECIPIENT=you@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
```

> **Gmail App Password**: Go to myaccount.google.com → Security → 2-Step Verification → App passwords. Generate one for "Mail". This is not your regular Gmail password.

### 3. Run the web app

```powershell
uvicorn app:app --reload
```

Open `http://localhost:8000` in your browser.

---

## Using the app

### Theses

Create a thesis from the top bar ("+ New Thesis"). Each thesis card shows:
- Total deployed capital, current value, and overall return %
- Expandable detail panel with open and closed position tables

### Adding positions

Click **"+ Add Position"** on any thesis card. Toggle between **Public** and **Private**:

**Public** — enter a ticker symbol, share count, an optional entry price (defaults to the live market price), and an optional entry date to **backdate** a past investment (e.g. "what if I bought NVDA in 2022?"). Leave the date blank to default to today.

**Private** — enter the company name, your investment amount ($), the company's valuation at entry, and optionally a current valuation (can be updated later) and an **entry date** to backdate the investment. Notes field for your thesis or assumptions.

### Closing positions

**Public**: click **Close** on the position row. Optionally override the exit price (defaults to live market price). The position moves to the "Closed" section showing actual gain, estimated tax, and the current "if still held" value.

**Private**: click **Exit** to record an exit valuation (acquisition price, IPO, write-down, etc.). The position moves to "Exited Private Positions" with final MOIC and after-tax gain.

### Updating a private valuation

Click **✏** on any private position row to open the "Update DCF Valuation" modal. Enter your new company valuation and optional notes. The current value, gain, and MOIC update immediately.

### Watchlist

Use the Watchlist section at the bottom. Add tickers to monitor for potential entry. Live data includes price, day change %, P/E ratio, dividend yield, and 52W high/low.

Auto-add screening criteria can be configured in `watchlist_manager.py`:

```python
CRITERIA = {
    "max_pe_ratio": None,          # Add if P/E ≤ threshold
    "min_dividend_yield": None,    # Add if dividend yield ≥ threshold
    "near_52w_low_pct": None,      # Add if within X% of 52W low
    "min_day_drop_pct": None,      # Add if dropped > X% today
}
```

Run screening from the CLI:
```powershell
python watchlist_manager.py screen AAPL MSFT NVDA
```

### Refreshing prices

Click **↻ Refresh Prices** in the top bar to force a fresh yfinance fetch (bypasses the 5-minute cache).

---

## Daily email newsletter

Run manually:
```powershell
python main.py
```

Dry run (prints output, does not send):
```powershell
python main.py --dry-run
```

The newsletter includes per-thesis cards with position tables, total returns, and the watchlist.

---

## CLI (optional)

All data operations can also be done from the command line via `portfolio.py`:

```powershell
# Thesis management
python portfolio.py new "AI Infrastructure"
python portfolio.py list

# Public positions
python portfolio.py buy "AI Infrastructure" NVDA 10
python portfolio.py buy "AI Infrastructure" NVDA 10 --price 850.00
python portfolio.py buy "AI Infrastructure" NVDA 10 --price 140.00 --entry-date 2023-01-15
python portfolio.py close "AI Infrastructure" NVDA
python portfolio.py close "AI Infrastructure" NVDA --exit-price 950.00
python portfolio.py delete "AI Infrastructure" NVDA

# Private positions
python portfolio.py add-private "AI Infrastructure" "Anthropic" 25000 18000000000
python portfolio.py add-private "AI Infrastructure" "Anthropic" 25000 18000000000 --current-val 61500000000 --notes "Series E, 20x rev"
python portfolio.py add-private "AI Infrastructure" "Anthropic" 25000 18000000000 --entry-date 2021-04-01
python portfolio.py update-private "AI Infrastructure" "Anthropic" 75000000000
python portfolio.py close-private "AI Infrastructure" "Anthropic" 90000000000
python portfolio.py delete-private "AI Infrastructure" "Anthropic"

# Print full portfolio state
python portfolio.py data
```

---

## Capital gains rates

Configured at the top of `portfolio.py`:

```python
ST_TAX_RATE = 0.24   # short-term: held < 365 days
LT_TAX_RATE = 0.15   # long-term:  held ≥ 365 days
```

Change these to match your actual marginal rates.

---

## Deployment (Railway)

1. Push to a GitHub repo.
2. Create a new Railway project → "Deploy from GitHub repo".
3. Add environment variables from your `.env` in the Railway dashboard (Settings → Variables).
4. Railway auto-detects `Procfile` and starts the server.

The `Procfile` runs:
```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

Data (`portfolios.json`, `watchlist.json`) persists as long as the Railway volume is mounted. For production use, consider replacing the JSON files with a Postgres database.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI server — all REST endpoints |
| `portfolio.py` | Data layer — thesis CRUD, position math, cap gains |
| `watchlist_manager.py` | Watchlist CRUD + yfinance market data + auto-add screening |
| `email_sender.py` | HTML newsletter builder + SMTP sender |
| `main.py` | CLI entrypoint for sending the daily newsletter |
| `static/index.html` | Single-file SPA frontend |
| `portfolios.json` | Persisted thesis/position data |
| `watchlist.json` | Persisted watchlist tickers |
| `Procfile` | Railway/Heroku start command |
| `railway.json` | Railway deployment config |
| `.env` | Your credentials — never commit this |
| `.env.example` | Template for .env |
