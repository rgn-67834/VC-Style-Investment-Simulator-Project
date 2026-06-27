"""
Simulated portfolio tracker for testing investment theses.
Positions are stored in portfolios.json. yfinance provides current prices.

CLI usage:
  python portfolio.py new "AI Basket"
  python portfolio.py buy "AI Basket" NVDA 3 --price 800.00
  python portfolio.py buy "AI Basket" MSFT 8
  python portfolio.py close "AI Basket" NVDA --price 950.00
  python portfolio.py delete "AI Basket" NVDA

  # Private / startup positions
  python portfolio.py add-private "AI Basket" "Stripe" 10000 50000000000 --current-val 70000000000 --notes "7x rev"
  python portfolio.py update-private "AI Basket" "Stripe" 80000000000
  python portfolio.py close-private "AI Basket" "Stripe" 90000000000
  python portfolio.py delete-private "AI Basket" "Stripe"

  python portfolio.py list
  python portfolio.py data
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import yfinance as yf

PORTFOLIOS_FILE = Path(__file__).parent / "portfolios.json"

# ---------------------------------------------------------------------------
# Capital gains tax rates (US 2024, single filer — adjust as needed)
# Short-term = held < 365 days, taxed as ordinary income
# Long-term  = held >= 365 days
# ---------------------------------------------------------------------------
ST_TAX_RATE = 0.24   # 24% — common bracket for $100k–$200k income
LT_TAX_RATE = 0.15   # 15% — most common long-term rate


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> dict:
    if PORTFOLIOS_FILE.exists():
        return json.loads(PORTFOLIOS_FILE.read_text())
    return {}


def _save(data: dict) -> None:
    PORTFOLIOS_FILE.write_text(json.dumps(data, indent=2))


def _ensure_keys(thesis: dict) -> None:
    """Backfill keys added in later versions."""
    thesis.setdefault("closed_positions", [])
    thesis.setdefault("private_positions", [])
    thesis.setdefault("closed_private_positions", [])


# ---------------------------------------------------------------------------
# Thesis management
# ---------------------------------------------------------------------------

def new_thesis(name: str) -> None:
    data = _load()
    if name in data:
        print(f"Thesis '{name}' already exists.")
        return
    data[name] = {"created": date.today().isoformat(), "positions": [], "closed_positions": []}
    _save(data)
    print(f"Created thesis: '{name}'")


def list_theses() -> None:
    data = _load()
    if not data:
        print("No theses yet. Run: python portfolio.py new \"My Thesis\"")
        return
    for name, thesis in data.items():
        _ensure_keys(thesis)
        open_ct = len(thesis["positions"])
        closed_ct = len(thesis["closed_positions"])
        print(f"  {name}  ({open_ct} open, {closed_ct} closed, created {thesis['created']})")


def buy(thesis_name: str, ticker: str, shares: float, price: Optional[float] = None,
        entry_date: Optional[str] = None) -> None:
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found. Create it first.")

    ticker = ticker.upper()

    if price is None:
        price = float(yf.Ticker(ticker).fast_info.last_price or 0)
        if not price:
            raise ValueError(f"Could not fetch current price for {ticker}. Pass --price explicitly.")
        print(f"Using current price for {ticker}: ${price:,.2f}")

    if entry_date:
        try:
            date.fromisoformat(entry_date)
        except ValueError:
            raise ValueError(f"Invalid entry_date '{entry_date}'. Use YYYY-MM-DD format.")
    else:
        entry_date = date.today().isoformat()

    _ensure_keys(data[thesis_name])
    data[thesis_name]["positions"].append({
        "ticker": ticker,
        "shares": shares,
        "entry_price": price,
        "entry_date": entry_date,
    })
    _save(data)
    print(f"Added {shares} x {ticker} @ ${price:,.2f} = ${shares*price:,.2f}  →  '{thesis_name}' (entry {entry_date})")


def close_position(thesis_name: str, ticker: str, exit_price: Optional[float] = None) -> None:
    """Close a position: record exit price/date and move to closed_positions."""
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found.")

    ticker = ticker.upper()
    _ensure_keys(data[thesis_name])

    positions = data[thesis_name]["positions"]
    matches = [p for p in positions if p["ticker"] == ticker]
    if not matches:
        raise ValueError(f"{ticker} not found in open positions for '{thesis_name}'.")

    if exit_price is None:
        exit_price = float(yf.Ticker(ticker).fast_info.last_price or 0)
        if not exit_price:
            raise ValueError(f"Could not fetch current price for {ticker}. Pass --price explicitly.")
        print(f"Using current price for {ticker}: ${exit_price:,.2f}")

    for pos in matches:
        data[thesis_name]["closed_positions"].append({
            **pos,
            "exit_price": exit_price,
            "exit_date": date.today().isoformat(),
        })

    data[thesis_name]["positions"] = [p for p in positions if p["ticker"] != ticker]
    _save(data)

    pos = matches[0]
    gain = (exit_price - pos["entry_price"]) * pos["shares"]
    days = (date.today() - date.fromisoformat(pos["entry_date"])).days
    term = "long-term" if days >= 365 else "short-term"
    print(f"Closed {ticker}: gain ${gain:+,.2f}  ({days}d held, {term})")


def delete_position(thesis_name: str, ticker: str) -> None:
    """Hard-delete a position with no history saved."""
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found.")

    ticker = ticker.upper()
    before = len(data[thesis_name]["positions"])
    data[thesis_name]["positions"] = [p for p in data[thesis_name]["positions"] if p["ticker"] != ticker]
    if len(data[thesis_name]["positions"]) == before:
        raise ValueError(f"{ticker} not found in '{thesis_name}'.")
    _save(data)
    print(f"Deleted {ticker} from '{thesis_name}' (no history saved).")


# ---------------------------------------------------------------------------
# Private / startup positions
# ---------------------------------------------------------------------------

def add_private_position(
    thesis_name: str,
    company: str,
    investment: float,
    entry_valuation: float,
    current_valuation: Optional[float] = None,
    notes: str = "",
    entry_date: Optional[str] = None,
) -> None:
    """Add a simulated private investment based on DCF valuation."""
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found. Create it first.")
    _ensure_keys(data[thesis_name])

    # Prevent duplicate company names within the same thesis
    existing = [p["company"] for p in data[thesis_name]["private_positions"]]
    if company in existing:
        raise ValueError(f"'{company}' already exists in '{thesis_name}'. Use update-private to change the valuation.")

    if entry_date:
        try:
            date.fromisoformat(entry_date)
        except ValueError:
            raise ValueError(f"Invalid entry_date '{entry_date}'. Use YYYY-MM-DD format.")
    else:
        entry_date = date.today().isoformat()

    data[thesis_name]["private_positions"].append({
        "company": company,
        "investment": investment,
        "entry_valuation": entry_valuation,
        "current_valuation": current_valuation if current_valuation is not None else entry_valuation,
        "entry_date": entry_date,
        "notes": notes,
    })
    _save(data)

    ownership_pct = investment / entry_valuation * 100
    print(f"Added private: {company}  ${investment:,.0f} @ ${entry_valuation/1e9:.2f}B valuation  "
          f"({ownership_pct:.4f}% implied ownership)  →  '{thesis_name}'")


def update_private_valuation(thesis_name: str, company: str, new_valuation: float, notes: Optional[str] = None) -> None:
    """Update the current DCF valuation for a private position."""
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found.")
    _ensure_keys(data[thesis_name])

    matches = [p for p in data[thesis_name]["private_positions"] if p["company"] == company]
    if not matches:
        raise ValueError(f"'{company}' not found in private positions for '{thesis_name}'.")

    for pos in matches:
        old_val = pos["current_valuation"]
        pos["current_valuation"] = new_valuation
        if notes is not None:
            pos["notes"] = notes
        change = (new_valuation - old_val) / old_val * 100 if old_val else 0
        print(f"Updated {company}: ${old_val/1e9:.2f}B → ${new_valuation/1e9:.2f}B  ({change:+.1f}%)")

    _save(data)


def close_private_position(thesis_name: str, company: str, exit_valuation: float) -> None:
    """Record an exit for a private position (acquisition, IPO, write-down, etc.)."""
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found.")
    _ensure_keys(data[thesis_name])

    positions = data[thesis_name]["private_positions"]
    matches = [p for p in positions if p["company"] == company]
    if not matches:
        raise ValueError(f"'{company}' not found in private positions for '{thesis_name}'.")

    for pos in matches:
        data[thesis_name]["closed_private_positions"].append({
            **pos,
            "exit_valuation": exit_valuation,
            "exit_date": date.today().isoformat(),
        })

    data[thesis_name]["private_positions"] = [p for p in positions if p["company"] != company]
    _save(data)

    pos = matches[0]
    implied_exit = pos["investment"] / pos["entry_valuation"] * exit_valuation
    gain = implied_exit - pos["investment"]
    days = (date.today() - date.fromisoformat(pos["entry_date"])).days
    print(f"Closed {company}: gain ${gain:+,.0f}  (exit @ ${exit_valuation/1e9:.2f}B, {days}d held)")


def delete_private_position(thesis_name: str, company: str) -> None:
    """Hard-delete a private position with no history saved."""
    data = _load()
    if thesis_name not in data:
        raise ValueError(f"Thesis '{thesis_name}' not found.")
    _ensure_keys(data[thesis_name])

    before = len(data[thesis_name]["private_positions"])
    data[thesis_name]["private_positions"] = [
        p for p in data[thesis_name]["private_positions"] if p["company"] != company
    ]
    if len(data[thesis_name]["private_positions"]) == before:
        raise ValueError(f"'{company}' not found in '{thesis_name}'.")
    _save(data)
    print(f"Deleted '{company}' from '{thesis_name}' (no history saved).")


def _enrich_private(pos: dict) -> dict:
    """Compute return metrics for an open private position."""
    investment = pos["investment"]
    entry_val = pos["entry_valuation"]
    current_val = pos["current_valuation"]
    entry_date = pos["entry_date"]

    # Implied ownership is fixed at entry; current value scales with valuation
    implied_ownership = investment / entry_val if entry_val else 0
    current_value = implied_ownership * current_val
    gain = current_value - investment
    gain_pct = (gain / investment * 100) if investment else 0.0
    days = (date.today() - date.fromisoformat(entry_date)).days
    moic = current_value / investment if investment else 1.0  # multiple on invested capital

    return {
        **pos,
        "implied_ownership_pct": implied_ownership * 100,
        "current_value": current_value,
        "gain": gain,
        "gain_pct": gain_pct,
        "moic": moic,
        "days_held": days,
        **_cap_gains(gain, days),
    }


def _enrich_closed_private(pos: dict) -> dict:
    """Compute return metrics for a closed private position."""
    investment = pos["investment"]
    entry_val = pos["entry_valuation"]
    exit_val = pos["exit_valuation"]
    entry_date = pos["entry_date"]
    exit_date = pos["exit_date"]

    implied_ownership = investment / entry_val if entry_val else 0
    exit_value = implied_ownership * exit_val
    actual_gain = exit_value - investment
    actual_gain_pct = (actual_gain / investment * 100) if investment else 0.0
    moic = exit_value / investment if investment else 1.0
    days_held = (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days

    return {
        **pos,
        "implied_ownership_pct": implied_ownership * 100,
        "exit_value": exit_value,
        "actual_gain": actual_gain,
        "actual_gain_pct": actual_gain_pct,
        "moic": moic,
        "days_held": days_held,
        **_cap_gains(actual_gain, days_held),
    }


# ---------------------------------------------------------------------------
# Capital gains helpers
# ---------------------------------------------------------------------------

def _cap_gains(gross_gain: float, days_held: int) -> dict:
    """Return capital gains classification and after-tax figures."""
    is_lt = days_held >= 365
    rate = LT_TAX_RATE if is_lt else ST_TAX_RATE
    tax = max(0.0, gross_gain * rate)   # no tax benefit on losses (simplified)
    return {
        "term": "long-term" if is_lt else "short-term",
        "tax_rate": rate,
        "estimated_tax": tax,
        "net_gain": gross_gain - tax,
    }


# ---------------------------------------------------------------------------
# Return calculations
# ---------------------------------------------------------------------------

def _current_price(ticker: str) -> float:
    try:
        return float(yf.Ticker(ticker).fast_info.last_price or 0)
    except Exception:
        return 0.0


def get_all_thesis_data() -> list[dict]:
    data = _load()
    results = []

    for name, thesis in data.items():
        _ensure_keys(thesis)
        positions_out = []
        closed_out = []
        private_out = []
        closed_private_out = []
        total_cost = 0.0
        total_value = 0.0

        # Open public positions
        for pos in thesis["positions"]:
            ticker = pos["ticker"]
            shares = pos["shares"]
            entry = pos["entry_price"]
            entry_date = pos["entry_date"]

            current = _current_price(ticker)
            cost = shares * entry
            value = shares * current
            gain = value - cost
            gain_pct = (gain / cost * 100) if cost else 0.0
            days = (date.today() - date.fromisoformat(entry_date)).days

            total_cost += cost
            total_value += value

            positions_out.append({
                "ticker": ticker,
                "shares": shares,
                "entry_price": entry,
                "entry_date": entry_date,
                "current_price": current,
                "value": value,
                "gain": gain,
                "gain_pct": gain_pct,
                "days_held": days,
                **_cap_gains(gain, days),
            })

        # Closed public positions
        for pos in thesis["closed_positions"]:
            ticker = pos["ticker"]
            shares = pos["shares"]
            entry = pos["entry_price"]
            entry_date = pos["entry_date"]
            exit_price = pos["exit_price"]
            exit_date = pos["exit_date"]

            cost = shares * entry
            exit_value = shares * exit_price
            actual_gain = exit_value - cost
            actual_gain_pct = (actual_gain / cost * 100) if cost else 0.0
            days_held = (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days

            current = _current_price(ticker)
            held_value = shares * current
            held_gain = held_value - cost
            held_gain_pct = (held_gain / cost * 100) if cost else 0.0
            opportunity = held_gain - actual_gain

            closed_out.append({
                "ticker": ticker,
                "shares": shares,
                "entry_price": entry,
                "entry_date": entry_date,
                "exit_price": exit_price,
                "exit_date": exit_date,
                "days_held": days_held,
                "actual_gain": actual_gain,
                "actual_gain_pct": actual_gain_pct,
                "current_price": current,
                "held_gain": held_gain,
                "held_gain_pct": held_gain_pct,
                "opportunity": opportunity,
                **_cap_gains(actual_gain, days_held),
            })

        # Open private positions
        for pos in thesis["private_positions"]:
            enriched = _enrich_private(pos)
            total_cost  += enriched["investment"]
            total_value += enriched["current_value"]
            private_out.append(enriched)

        # Closed private positions
        for pos in thesis["closed_private_positions"]:
            closed_private_out.append(_enrich_closed_private(pos))

        total_gain = total_value - total_cost
        total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0.0

        results.append({
            "name": name,
            "created": thesis["created"],
            "total_cost": total_cost,
            "total_value": total_value,
            "total_gain": total_gain,
            "total_gain_pct": total_gain_pct,
            "positions": positions_out,
            "closed_positions": closed_out,
            "private_positions": private_out,
            "closed_private_positions": closed_private_out,
        })

    return results


def print_data() -> None:
    theses = get_all_thesis_data()
    if not theses:
        print("No theses found.")
        return

    for t in theses:
        s = "+" if t["total_gain"] >= 0 else ""
        print(f"\n{'='*80}")
        print(f"  {t['name']}  (since {t['created']})")
        print(f"  Cost: ${t['total_cost']:>12,.2f}   Value: ${t['total_value']:>12,.2f}   Return: {s}{t['total_gain_pct']:.2f}%")

        if t["positions"]:
            print(f"\n  PUBLIC — OPEN")
            print(f"  {'Ticker':<8} {'Shares':>8} {'Entry':>10} {'Current':>10} {'Gain':>12} {'Rtn%':>7} {'Term':<10} {'Net':>12}")
            print(f"  {'-'*80}")
            for p in t["positions"]:
                s2 = "+" if p["gain"] >= 0 else ""
                print(f"  {p['ticker']:<8} {p['shares']:>8.4f} ${p['entry_price']:>9,.2f} ${p['current_price']:>9,.2f} "
                      f"{s2}${abs(p['gain']):>10,.2f} {s2}{abs(p['gain_pct']):>5.2f}% {p['term']:<10} net ${p['net_gain']:>8,.2f}")

        if t["closed_positions"]:
            print(f"\n  PUBLIC — CLOSED")
            print(f"  {'Ticker':<8} {'Sold':>10} {'Actual Gain':>12} {'If Held':>12} {'Opportunity':>12} {'Term':<10}")
            print(f"  {'-'*70}")
            for p in t["closed_positions"]:
                s2 = "+" if p["actual_gain"] >= 0 else ""
                opp_s = "+" if p["opportunity"] >= 0 else ""
                print(f"  {p['ticker']:<8} {p['exit_date']:>10} {s2}${abs(p['actual_gain']):>10,.2f} "
                      f"${p['held_gain']:>10,.2f}   {opp_s}${abs(p['opportunity']):>9,.2f}  {p['term']:<10}")

        if t["private_positions"]:
            print(f"\n  PRIVATE — OPEN")
            print(f"  {'Company':<20} {'Invested':>12} {'Entry Val':>14} {'Curr Val':>14} {'MOIC':>6} {'Gain':>12} {'Term':<10}")
            print(f"  {'-'*90}")
            for p in t["private_positions"]:
                s2 = "+" if p["gain"] >= 0 else ""
                print(f"  {p['company']:<20} ${p['investment']:>10,.0f} "
                      f"${p['entry_valuation']/1e9:>12.2f}B ${p['current_valuation']/1e9:>12.2f}B "
                      f"{p['moic']:>5.2f}x {s2}${abs(p['gain']):>10,.0f} {p['term']:<10}")
                if p.get("notes"):
                    print(f"    Notes: {p['notes']}")

        if t["closed_private_positions"]:
            print(f"\n  PRIVATE — CLOSED (EXITED)")
            print(f"  {'Company':<20} {'Exited':>10} {'Invested':>12} {'Exit Val':>14} {'MOIC':>6} {'Gain':>12} {'Term':<10}")
            print(f"  {'-'*90}")
            for p in t["closed_private_positions"]:
                s2 = "+" if p["actual_gain"] >= 0 else ""
                print(f"  {p['company']:<20} {p['exit_date']:>10} ${p['investment']:>10,.0f} "
                      f"${p['exit_valuation']/1e9:>12.2f}B {p['moic']:>5.2f}x "
                      f"{s2}${abs(p['actual_gain']):>10,.0f} {p['term']:<10}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulated portfolio tracker")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List all theses")
    sub.add_parser("data", help="Show full return breakdown")

    p_new = sub.add_parser("new", help="Create a new thesis")
    p_new.add_argument("name")

    p_buy = sub.add_parser("buy", help="Add a position")
    p_buy.add_argument("thesis")
    p_buy.add_argument("ticker")
    p_buy.add_argument("shares", type=float)
    p_buy.add_argument("--price", type=float, default=None,
                       help="Entry price (defaults to today's market price)")
    p_buy.add_argument("--entry-date", type=str, default=None,
                       help="Backdated entry date YYYY-MM-DD (defaults to today)")

    p_close = sub.add_parser("close", help="Close a position (keeps history)")
    p_close.add_argument("thesis")
    p_close.add_argument("ticker")
    p_close.add_argument("--price", type=float, default=None,
                         help="Exit price (defaults to today's market price)")

    p_del = sub.add_parser("delete", help="Delete a public position with no history")
    p_del.add_argument("thesis")
    p_del.add_argument("ticker")

    p_ap = sub.add_parser("add-private", help="Add a private/startup position")
    p_ap.add_argument("thesis")
    p_ap.add_argument("company")
    p_ap.add_argument("investment", type=float, help="Dollar amount invested")
    p_ap.add_argument("entry_valuation", type=float, help="Company valuation at entry")
    p_ap.add_argument("--current-val", type=float, default=None, help="Current DCF valuation (defaults to entry)")
    p_ap.add_argument("--notes", type=str, default="", help="DCF assumptions or thesis notes")
    p_ap.add_argument("--entry-date", type=str, default=None,
                      help="Backdated entry date YYYY-MM-DD (defaults to today)")

    p_up = sub.add_parser("update-private", help="Update current valuation for a private position")
    p_up.add_argument("thesis")
    p_up.add_argument("company")
    p_up.add_argument("new_valuation", type=float)
    p_up.add_argument("--notes", type=str, default=None)

    p_cp = sub.add_parser("close-private", help="Record an exit for a private position")
    p_cp.add_argument("thesis")
    p_cp.add_argument("company")
    p_cp.add_argument("exit_valuation", type=float)

    p_dp = sub.add_parser("delete-private", help="Delete a private position with no history")
    p_dp.add_argument("thesis")
    p_dp.add_argument("company")

    args = parser.parse_args()

    try:
        if args.cmd == "new":
            new_thesis(args.name)
        elif args.cmd == "buy":
            buy(args.thesis, args.ticker, args.shares, args.price, args.entry_date)
        elif args.cmd == "close":
            close_position(args.thesis, args.ticker, args.price)
        elif args.cmd == "delete":
            delete_position(args.thesis, args.ticker)
        elif args.cmd == "add-private":
            add_private_position(args.thesis, args.company, args.investment,
                                 args.entry_valuation, args.current_val, args.notes, args.entry_date)
        elif args.cmd == "update-private":
            update_private_valuation(args.thesis, args.company, args.new_valuation, args.notes)
        elif args.cmd == "close-private":
            close_private_position(args.thesis, args.company, args.exit_valuation)
        elif args.cmd == "delete-private":
            delete_private_position(args.thesis, args.company)
        elif args.cmd == "list":
            list_theses()
        elif args.cmd == "data":
            print_data()
        else:
            parser.print_help()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
