"""
Manages the per-user watchlist — adding/removing tickers and fetching live market data.
"""

from typing import Optional

import yfinance as yf

from database import get_conn


# ---------------------------------------------------------------------------
# Watchlist I/O
# ---------------------------------------------------------------------------

def load_watchlist(user_id: int) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id=? ORDER BY added_at", (user_id,)
        ).fetchall()
    return [r["ticker"] for r in rows]


def add_to_watchlist(user_id: int, ticker: str) -> bool:
    """Add a ticker. Returns True if newly added."""
    ticker = ticker.upper().strip()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO watchlist (user_id, ticker) VALUES (?,?)", (user_id, ticker)
            )
            return True
        except Exception:
            return False


def remove_from_watchlist(user_id: int, ticker: str) -> bool:
    """Remove a ticker. Returns True if it existed."""
    ticker = ticker.upper().strip()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE user_id=? AND ticker=?", (user_id, ticker)
        )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def _fetch_ticker_data(ticker: str) -> Optional[dict]:
    try:
        t  = yf.Ticker(ticker)
        fi = t.fast_info
        info = t.info

        price     = float(fi.last_price or 0)
        prev_close = float(fi.previous_close or price)
        day_change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

        # Stored as a fraction (0.008 = 0.8%). Yahoo's own dividendYield field
        # changed units between library versions, so derive it from the
        # annual dividend and the price instead.
        rate = info.get("dividendRate")
        dividend_yield = (float(rate) / price) if rate and price else (0.0 if rate == 0 else None)

        return {
            "ticker":         ticker,
            "name":           info.get("longName", ticker),
            "price":          price,
            "day_change_pct": day_change_pct,
            "pe_ratio":       info.get("trailingPE"),
            "dividend_yield": dividend_yield,
            "low_52w":        float(fi.year_low)  if fi.year_low  else None,
            "high_52w":       float(fi.year_high) if fi.year_high else None,
            "market_cap":     info.get("marketCap"),
        }
    except Exception as e:
        print(f"[watchlist] Error fetching {ticker}: {e}")
        return None


def get_watchlist_data(user_id: int) -> list[dict]:
    """Return enriched market data for all tickers in the user's watchlist."""
    tickers = load_watchlist(user_id)
    results = []
    for ticker in tickers:
        data = _fetch_ticker_data(ticker)
        if data:
            results.append(data)
    return results
