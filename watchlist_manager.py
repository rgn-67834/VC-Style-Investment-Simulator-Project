"""
Manages the per-user watchlist — adding/removing tickers and fetching live market data.
"""

from typing import Optional

import yfinance as yf

from database import get_conn

CRITERIA = {
    "max_pe_ratio":       None,
    "min_dividend_yield": None,
    "near_52w_low_pct":   None,
    "min_day_drop_pct":   None,
}


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

        return {
            "ticker":         ticker,
            "name":           info.get("longName", ticker),
            "price":          price,
            "day_change_pct": day_change_pct,
            "pe_ratio":       info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
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


# ---------------------------------------------------------------------------
# Auto-add screening
# ---------------------------------------------------------------------------

def _matches_criteria(data: dict) -> tuple[bool, list[str]]:
    reasons = []

    pe     = data.get("pe_ratio")
    max_pe = CRITERIA["max_pe_ratio"]
    if max_pe is not None and pe is not None and pe <= max_pe:
        reasons.append(f"P/E {pe:.1f} <= {max_pe}")

    div     = data.get("dividend_yield")
    min_div = CRITERIA["min_dividend_yield"]
    if min_div is not None and div is not None and div >= min_div:
        reasons.append(f"Div yield {div*100:.2f}% >= {min_div*100:.2f}%")

    low_52  = data.get("low_52w")
    price   = data.get("price", 0)
    near_low = CRITERIA["near_52w_low_pct"]
    if near_low is not None and low_52 and low_52 > 0:
        pct_above_low = (price - low_52) / low_52
        if pct_above_low <= near_low:
            reasons.append(f"Price within {pct_above_low*100:.1f}% of 52W low")

    day_drop = CRITERIA["min_day_drop_pct"]
    day_chg  = data.get("day_change_pct", 0)
    if day_drop is not None and day_chg <= -abs(day_drop):
        reasons.append(f"Dropped {abs(day_chg):.2f}% today")

    return bool(reasons), reasons


def screen_and_add(user_id: int, candidates: list[str]) -> list[dict]:
    added = []
    for ticker in candidates:
        data = _fetch_ticker_data(ticker)
        if not data:
            continue
        matched, reasons = _matches_criteria(data)
        if matched:
            newly_added = add_to_watchlist(user_id, ticker)
            if newly_added:
                added.append({"ticker": ticker, "reasons": reasons, **data})
    return added
