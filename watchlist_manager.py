"""
Manages the watchlist — adding/removing tickers and fetching live market data.
Criteria for auto-adding tickers will be configured here.
"""

import json
import os
from pathlib import Path
from typing import Optional
import yfinance as yf

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"


# ---------------------------------------------------------------------------
# Criteria config — edit these thresholds to control auto-add behavior
# ---------------------------------------------------------------------------

CRITERIA = {
    # Add ticker if P/E ratio is at or below this value (None = disabled)
    "max_pe_ratio": None,

    # Add ticker if dividend yield is at or above this value, e.g. 0.03 = 3% (None = disabled)
    "min_dividend_yield": None,

    # Add ticker if price is within this % of its 52-week low, e.g. 0.05 = within 5% (None = disabled)
    "near_52w_low_pct": None,

    # Add ticker if it dropped more than this % today, e.g. 0.03 = dropped >3% (None = disabled)
    "min_day_drop_pct": None,
}


# ---------------------------------------------------------------------------
# Watchlist I/O
# ---------------------------------------------------------------------------

def load_watchlist() -> list[str]:
    if WATCHLIST_FILE.exists():
        return json.loads(WATCHLIST_FILE.read_text())
    return []


def save_watchlist(tickers: list[str]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(sorted(set(tickers)), indent=2))


def add_to_watchlist(ticker: str) -> bool:
    """Add a ticker. Returns True if it was newly added."""
    ticker = ticker.upper().strip()
    current = load_watchlist()
    if ticker in current:
        return False
    current.append(ticker)
    save_watchlist(current)
    print(f"[watchlist] Added {ticker}")
    return True


def remove_from_watchlist(ticker: str) -> bool:
    """Remove a ticker. Returns True if it existed."""
    ticker = ticker.upper().strip()
    current = load_watchlist()
    if ticker not in current:
        return False
    current.remove(ticker)
    save_watchlist(current)
    print(f"[watchlist] Removed {ticker}")
    return True


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def _fetch_ticker_data(ticker: str) -> Optional[dict]:
    """Fetch current market data for a single ticker via yfinance."""
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        info = t.info

        price = float(fi.last_price or 0)
        prev_close = float(fi.previous_close or price)
        day_change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "price": price,
            "day_change_pct": day_change_pct,
            "pe_ratio": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "low_52w": float(fi.year_low) if fi.year_low else None,
            "high_52w": float(fi.year_high) if fi.year_high else None,
            "market_cap": info.get("marketCap"),
        }
    except Exception as e:
        print(f"[watchlist] Error fetching {ticker}: {e}")
        return None


def get_watchlist_data() -> list[dict]:
    """Return enriched market data for all tickers in the watchlist."""
    tickers = load_watchlist()
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
    """Check if a ticker meets any enabled auto-add criteria. Returns (match, reasons)."""
    reasons = []

    pe = data.get("pe_ratio")
    max_pe = CRITERIA["max_pe_ratio"]
    if max_pe is not None and pe is not None and pe <= max_pe:
        reasons.append(f"P/E {pe:.1f} ≤ {max_pe}")

    div = data.get("dividend_yield")
    min_div = CRITERIA["min_dividend_yield"]
    if min_div is not None and div is not None and div >= min_div:
        reasons.append(f"Div yield {div*100:.2f}% ≥ {min_div*100:.2f}%")

    low_52 = data.get("low_52w")
    price = data.get("price", 0)
    near_low = CRITERIA["near_52w_low_pct"]
    if near_low is not None and low_52 and low_52 > 0:
        pct_above_low = (price - low_52) / low_52
        if pct_above_low <= near_low:
            reasons.append(f"Price within {pct_above_low*100:.1f}% of 52W low")

    day_drop = CRITERIA["min_day_drop_pct"]
    day_chg = data.get("day_change_pct", 0)
    if day_drop is not None and day_chg <= -abs(day_drop):
        reasons.append(f"Dropped {abs(day_chg):.2f}% today")

    return bool(reasons), reasons


def screen_and_add(candidates: list[str]) -> list[dict]:
    """
    Given a list of candidate tickers, fetch their data, apply CRITERIA,
    and auto-add any that match. Returns a list of added items with reasons.
    """
    added = []
    for ticker in candidates:
        data = _fetch_ticker_data(ticker)
        if not data:
            continue
        matched, reasons = _matches_criteria(data)
        if matched:
            newly_added = add_to_watchlist(ticker)
            if newly_added:
                added.append({"ticker": ticker, "reasons": reasons, **data})
                print(f"[watchlist] Auto-added {ticker}: {', '.join(reasons)}")
    return added


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "add" and len(sys.argv) > 2:
        add_to_watchlist(sys.argv[2])
    elif cmd == "remove" and len(sys.argv) > 2:
        remove_from_watchlist(sys.argv[2])
    elif cmd == "list":
        tickers = load_watchlist()
        print("Watchlist:", tickers if tickers else "(empty)")
    elif cmd == "data":
        for item in get_watchlist_data():
            print(f"{item['ticker']:6s}  ${item['price']:>10,.2f}  {item['day_change_pct']:+.2f}%")
    elif cmd == "screen":
        # Example: python watchlist_manager.py screen AAPL MSFT NVDA
        candidates = sys.argv[2:]
        if not candidates:
            print("Usage: python watchlist_manager.py screen TICKER1 TICKER2 ...")
        else:
            result = screen_and_add(candidates)
            print(f"Auto-added {len(result)} ticker(s).")
