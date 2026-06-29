"""
Simulated portfolio tracker. Backed by SQLite via database.py.
All write operations require a user_id so data stays user-scoped.
"""

from datetime import date
from typing import Optional

import yfinance as yf

from database import get_conn

ST_TAX_RATE = 0.24   # 24% short-term (< 365 days)
LT_TAX_RATE = 0.15   # 15% long-term  (>= 365 days)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_thesis_id(conn, user_id: int, thesis_name: str) -> int:
    row = conn.execute(
        "SELECT id FROM theses WHERE user_id=? AND name=?", (user_id, thesis_name)
    ).fetchone()
    if not row:
        raise ValueError(f"Thesis '{thesis_name}' not found.")
    return row["id"]


def _cap_gains(gross_gain: float, days_held: int) -> dict:
    is_lt = days_held >= 365
    rate = LT_TAX_RATE if is_lt else ST_TAX_RATE
    tax = max(0.0, gross_gain * rate)
    return {
        "term": "long-term" if is_lt else "short-term",
        "tax_rate": rate,
        "estimated_tax": tax,
        "net_gain": gross_gain - tax,
    }


def _current_price(ticker: str) -> float:
    try:
        return float(yf.Ticker(ticker).fast_info.last_price or 0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Thesis management
# ---------------------------------------------------------------------------

def new_thesis(user_id: int, name: str, notes: str = "") -> None:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO theses (user_id, name, notes, created_at) VALUES (?,?,?,?)",
                (user_id, name, notes, date.today().isoformat())
            )
        except Exception:
            raise ValueError(f"Thesis '{name}' already exists.")


def delete_thesis(user_id: int, thesis_name: str) -> None:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM theses WHERE user_id=? AND name=?", (user_id, thesis_name)
        )
    if cur.rowcount == 0:
        raise ValueError(f"Thesis '{thesis_name}' not found.")


def update_thesis_notes(user_id: int, thesis_name: str, notes: str) -> None:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE theses SET notes=? WHERE user_id=? AND name=?",
            (notes, user_id, thesis_name)
        )
    if cur.rowcount == 0:
        raise ValueError(f"Thesis '{thesis_name}' not found.")


def list_theses(user_id: int) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, created_at FROM theses WHERE user_id=? ORDER BY created_at",
            (user_id,)
        ).fetchall()
    if not rows:
        print("No theses yet.")
        return
    for r in rows:
        print(f"  {r['name']}  (created {r['created_at']})")


# ---------------------------------------------------------------------------
# Public positions
# ---------------------------------------------------------------------------

def buy(user_id: int, thesis_name: str, ticker: str, shares: float,
        price: Optional[float] = None, entry_date: Optional[str] = None,
        notes: str = "") -> None:
    ticker = ticker.upper()

    if price is None:
        price = _current_price(ticker)
        if not price:
            raise ValueError(f"Could not fetch price for {ticker}. Try again or enter a price manually.")
        print(f"Using current price for {ticker}: ${price:,.2f}")

    if entry_date:
        try:
            date.fromisoformat(entry_date)
        except ValueError:
            raise ValueError(f"Invalid entry_date '{entry_date}'. Use YYYY-MM-DD.")
    else:
        entry_date = date.today().isoformat()

    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        conn.execute(
            "INSERT INTO positions (thesis_id, ticker, shares, entry_price, entry_date, notes) VALUES (?,?,?,?,?,?)",
            (thesis_id, ticker, shares, price, entry_date, notes)
        )
    print(f"Added {shares} x {ticker} @ ${price:,.2f} → '{thesis_name}'")


def close_position(user_id: int, thesis_name: str, ticker: str,
                   exit_price: Optional[float] = None) -> None:
    ticker = ticker.upper()

    if exit_price is None:
        exit_price = float(yf.Ticker(ticker).fast_info.last_price or 0)
        if not exit_price:
            raise ValueError(f"Could not fetch price for {ticker}. Pass --price explicitly.")
        print(f"Using current price for {ticker}: ${exit_price:,.2f}")

    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        matches = conn.execute(
            "SELECT * FROM positions WHERE thesis_id=? AND ticker=?", (thesis_id, ticker)
        ).fetchall()
        if not matches:
            raise ValueError(f"{ticker} not found in open positions for '{thesis_name}'.")

        exit_date = date.today().isoformat()
        for pos in matches:
            conn.execute(
                "INSERT INTO closed_positions "
                "(thesis_id, ticker, shares, entry_price, entry_date, exit_price, exit_date) "
                "VALUES (?,?,?,?,?,?,?)",
                (thesis_id, pos["ticker"], pos["shares"], pos["entry_price"],
                 pos["entry_date"], exit_price, exit_date)
            )
        conn.execute(
            "DELETE FROM positions WHERE thesis_id=? AND ticker=?", (thesis_id, ticker)
        )

    pos = matches[0]
    gain = (exit_price - pos["entry_price"]) * pos["shares"]
    days = (date.today() - date.fromisoformat(pos["entry_date"])).days
    term = "long-term" if days >= 365 else "short-term"
    print(f"Closed {ticker}: gain ${gain:+,.2f} ({days}d held, {term})")


def delete_position(user_id: int, thesis_name: str, ticker: str) -> None:
    ticker = ticker.upper()
    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        cur = conn.execute(
            "DELETE FROM positions WHERE thesis_id=? AND ticker=?", (thesis_id, ticker)
        )
    if cur.rowcount == 0:
        raise ValueError(f"{ticker} not found in '{thesis_name}'.")
    print(f"Deleted {ticker} from '{thesis_name}' (no history saved).")


# ---------------------------------------------------------------------------
# Private positions
# ---------------------------------------------------------------------------

def add_private_position(
    user_id: int,
    thesis_name: str,
    company: str,
    investment: float,
    entry_valuation: float,
    current_valuation: Optional[float] = None,
    notes: str = "",
    entry_date: Optional[str] = None,
    expected_liquidity_date: Optional[str] = None,
    liquidity_event_type: str = "",
) -> None:
    if entry_date:
        try:
            date.fromisoformat(entry_date)
        except ValueError:
            raise ValueError(f"Invalid entry_date '{entry_date}'. Use YYYY-MM-DD.")
    else:
        entry_date = date.today().isoformat()

    if current_valuation is None:
        current_valuation = entry_valuation

    if expected_liquidity_date:
        try:
            date.fromisoformat(expected_liquidity_date)
        except ValueError:
            raise ValueError(f"Invalid expected_liquidity_date '{expected_liquidity_date}'. Use YYYY-MM-DD.")

    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        try:
            conn.execute(
                "INSERT INTO private_positions "
                "(thesis_id, company, investment, entry_valuation, current_valuation, entry_date, notes, "
                "expected_liquidity_date, liquidity_event_type) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (thesis_id, company, investment, entry_valuation, current_valuation, entry_date, notes,
                 expected_liquidity_date, liquidity_event_type)
            )
        except Exception:
            raise ValueError(f"'{company}' already exists in '{thesis_name}'.")

    ownership_pct = investment / entry_valuation * 100
    print(f"Added private: {company} ${investment:,.0f} @ ${entry_valuation/1e9:.2f}B "
          f"({ownership_pct:.4f}% implied ownership) → '{thesis_name}'")


def update_private_valuation(user_id: int, thesis_name: str, company: str,
                              new_valuation: float, notes: Optional[str] = None) -> None:
    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        row = conn.execute(
            "SELECT * FROM private_positions WHERE thesis_id=? AND company=?", (thesis_id, company)
        ).fetchone()
        if not row:
            raise ValueError(f"'{company}' not found in private positions for '{thesis_name}'.")

        if notes is not None:
            conn.execute(
                "UPDATE private_positions SET current_valuation=?, notes=? WHERE thesis_id=? AND company=?",
                (new_valuation, notes, thesis_id, company)
            )
        else:
            conn.execute(
                "UPDATE private_positions SET current_valuation=? WHERE thesis_id=? AND company=?",
                (new_valuation, thesis_id, company)
            )

    old_val = row["current_valuation"]
    change = (new_valuation - old_val) / old_val * 100 if old_val else 0
    print(f"Updated {company}: ${old_val/1e9:.2f}B → ${new_valuation/1e9:.2f}B ({change:+.1f}%)")


def close_private_position(user_id: int, thesis_name: str, company: str,
                            exit_valuation: float) -> None:
    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        pos = conn.execute(
            "SELECT * FROM private_positions WHERE thesis_id=? AND company=?", (thesis_id, company)
        ).fetchone()
        if not pos:
            raise ValueError(f"'{company}' not found in private positions for '{thesis_name}'.")

        exit_date = date.today().isoformat()
        conn.execute(
            "INSERT INTO closed_private_positions "
            "(thesis_id, company, investment, entry_valuation, exit_valuation, entry_date, exit_date, notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (thesis_id, pos["company"], pos["investment"], pos["entry_valuation"],
             exit_valuation, pos["entry_date"], exit_date, pos["notes"])
        )
        conn.execute(
            "DELETE FROM private_positions WHERE thesis_id=? AND company=?", (thesis_id, company)
        )

    implied_exit = pos["investment"] / pos["entry_valuation"] * exit_valuation
    gain = implied_exit - pos["investment"]
    days = (date.today() - date.fromisoformat(pos["entry_date"])).days
    print(f"Closed {company}: gain ${gain:+,.0f} (exit @ ${exit_valuation/1e9:.2f}B, {days}d held)")


def delete_private_position(user_id: int, thesis_name: str, company: str) -> None:
    with get_conn() as conn:
        thesis_id = _get_thesis_id(conn, user_id, thesis_name)
        cur = conn.execute(
            "DELETE FROM private_positions WHERE thesis_id=? AND company=?", (thesis_id, company)
        )
    if cur.rowcount == 0:
        raise ValueError(f"'{company}' not found in '{thesis_name}'.")
    print(f"Deleted '{company}' from '{thesis_name}' (no history saved).")


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

def _time_to_liquidity(liquidity_date_str: Optional[str]) -> dict:
    """Compute time-to-liquidity metrics from an expected liquidity date."""
    if not liquidity_date_str:
        return {"years_to_liquidity": None, "time_to_liquidity": None, "pct_hold_elapsed": None}

    today = date.today()
    liq   = date.fromisoformat(liquidity_date_str)
    days_remaining = (liq - today).days
    years_remaining = days_remaining / 365.25

    if days_remaining < 0:
        time_str = "Past due"
    else:
        y = int(years_remaining)
        m = int((years_remaining - y) * 12)
        parts = []
        if y: parts.append(f"{y}y")
        if m: parts.append(f"{m}m")
        time_str = " ".join(parts) if parts else "< 1m"

    return {
        "years_to_liquidity": years_remaining,
        "time_to_liquidity":  time_str,
    }


def _projected_irr(current_value: float, investment: float,
                   years_to_liquidity: Optional[float]) -> Optional[float]:
    """CAGR from today to expected liquidity at current implied value."""
    if years_to_liquidity is None or years_to_liquidity <= 0 or investment <= 0:
        return None
    try:
        return (current_value / investment) ** (1 / years_to_liquidity) - 1
    except Exception:
        return None


def _enrich_private(pos) -> dict:
    pos = dict(pos)
    investment  = pos["investment"]
    entry_val   = pos["entry_valuation"]
    current_val = pos["current_valuation"]
    entry_date  = pos["entry_date"]
    liq_date    = pos.get("expected_liquidity_date")

    implied_ownership = investment / entry_val if entry_val else 0
    current_value = implied_ownership * current_val
    gain     = current_value - investment
    gain_pct = (gain / investment * 100) if investment else 0.0
    days     = (date.today() - date.fromisoformat(entry_date)).days
    moic     = current_value / investment if investment else 1.0

    liq_metrics  = _time_to_liquidity(liq_date)
    proj_irr     = _projected_irr(current_value, investment, liq_metrics["years_to_liquidity"])

    return {
        **pos,
        "implied_ownership_pct": implied_ownership * 100,
        "current_value":   current_value,
        "gain":            gain,
        "gain_pct":        gain_pct,
        "moic":            moic,
        "days_held":       days,
        "projected_irr":   proj_irr,
        **liq_metrics,
        **_cap_gains(gain, days),
    }


def _enrich_closed_private(pos) -> dict:
    pos = dict(pos)
    investment  = pos["investment"]
    entry_val   = pos["entry_valuation"]
    exit_val    = pos["exit_valuation"]
    entry_date  = pos["entry_date"]
    exit_date   = pos["exit_date"]

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
# Data retrieval
# ---------------------------------------------------------------------------

def get_all_thesis_data(user_id: int) -> list[dict]:
    with get_conn() as conn:
        theses = conn.execute(
            "SELECT id, name, notes, created_at FROM theses WHERE user_id=? ORDER BY created_at",
            (user_id,)
        ).fetchall()

        results = []
        for thesis in theses:
            thesis_id   = thesis["id"]
            total_cost  = 0.0
            total_value = 0.0

            # Open public positions
            positions_out = []
            for pos in conn.execute(
                "SELECT * FROM positions WHERE thesis_id=?", (thesis_id,)
            ).fetchall():
                ticker     = pos["ticker"]
                shares     = pos["shares"]
                entry      = pos["entry_price"]
                entry_date = pos["entry_date"]

                current  = _current_price(ticker)
                cost     = shares * entry
                value    = shares * current
                gain     = value - cost
                gain_pct = (gain / cost * 100) if cost else 0.0
                days     = (date.today() - date.fromisoformat(entry_date)).days

                total_cost  += cost
                total_value += value

                positions_out.append({
                    "id": pos["id"],
                    "ticker": ticker,
                    "shares": shares,
                    "entry_price": entry,
                    "entry_date": entry_date,
                    "notes": pos["notes"] if "notes" in pos.keys() else "",
                    "current_price": current,
                    "value": value,
                    "gain": gain,
                    "gain_pct": gain_pct,
                    "days_held": days,
                    **_cap_gains(gain, days),
                })

            # Closed public positions
            closed_out = []
            for pos in conn.execute(
                "SELECT * FROM closed_positions WHERE thesis_id=?", (thesis_id,)
            ).fetchall():
                ticker      = pos["ticker"]
                shares      = pos["shares"]
                entry       = pos["entry_price"]
                entry_date  = pos["entry_date"]
                exit_price  = pos["exit_price"]
                exit_date   = pos["exit_date"]

                cost            = shares * entry
                exit_value      = shares * exit_price
                actual_gain     = exit_value - cost
                actual_gain_pct = (actual_gain / cost * 100) if cost else 0.0
                days_held       = (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days

                current      = _current_price(ticker)
                held_value   = shares * current
                held_gain    = held_value - cost
                held_gain_pct = (held_gain / cost * 100) if cost else 0.0
                opportunity  = held_gain - actual_gain

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
            private_out = []
            for pos in conn.execute(
                "SELECT * FROM private_positions WHERE thesis_id=?", (thesis_id,)
            ).fetchall():
                enriched = _enrich_private(pos)
                total_cost  += enriched["investment"]
                total_value += enriched["current_value"]
                private_out.append(enriched)

            # Closed private positions
            closed_private_out = []
            for pos in conn.execute(
                "SELECT * FROM closed_private_positions WHERE thesis_id=?", (thesis_id,)
            ).fetchall():
                closed_private_out.append(_enrich_closed_private(pos))

            total_gain     = total_value - total_cost
            total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0.0

            results.append({
                "name":                    thesis["name"],
                "notes":                   thesis["notes"],
                "created":                 thesis["created_at"],
                "total_cost":              total_cost,
                "total_value":             total_value,
                "total_gain":              total_gain,
                "total_gain_pct":          total_gain_pct,
                "positions":               positions_out,
                "closed_positions":        closed_out,
                "private_positions":       private_out,
                "closed_private_positions": closed_private_out,
            })

    return results
