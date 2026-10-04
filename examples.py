"""
Example data for a new account: two theses with public and private positions,
DCF snapshots, a watchlist and a small startup pipeline, so the app is not
empty on first sign-in.

The private companies, startups and people here are invented. Public tickers
are real, but their entry prices are illustrative, not historical quotes.
Everything can be edited or removed like any other entry.
"""

from datetime import date, timedelta

from database import get_conn
from pipeline import add_contact, add_note, add_startup
from portfolio import add_private_position, buy, new_thesis, save_dcf_model
from watchlist_manager import add_to_watchlist


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _days_ahead(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


EXAMPLE_NOTE = "Example position. The entry price is illustrative, not a real quote."

THESES = [
    {
        "name": "AI Infrastructure (example)",
        "notes": "Example thesis. The compute, networking and tooling layer captures value before applications do. "
                 "Public positions are the picks-and-shovels names; the private position is an early bet on physical automation.",
        "public": [
            # ticker, shares, entry price, days since entry
            ("NVDA", 150, 95.00, 480),
            ("MSFT", 40, 410.00, 300),
        ],
        "private": [
            {
                "company": "Northwind Robotics",
                "investment": 250_000, "entry_valuation": 40_000_000, "current_valuation": 65_000_000,
                "days_ago": 420, "liquidity_in_days": 365 * 4, "liquidity_event_type": "Acquisition",
                "notes": "Example company (invented). Warehouse picking arms sold as a monthly subscription. "
                         "Valuation marked up after a Series A extension.",
                "dcf": [
                    # label, base revenue, growth, FCF margin, discount, terminal growth, years, net debt, days ago
                    ("Entry case", 4_000_000, 0.60, 0.10, 0.25, 0.03, 7, 0, 420),
                    ("After Series A extension", 6_500_000, 0.70, 0.12, 0.22, 0.03, 7, -3_000_000, 90),
                ],
            },
        ],
    },
    {
        "name": "Energy Transition (example)",
        "notes": "Example thesis. Grid storage and electrification grow faster than generation. "
                 "Long holding periods, so the private position is modeled to an IPO.",
        "public": [
            ("NEE", 200, 68.00, 200),
        ],
        "private": [
            {
                "company": "Helio Grid Storage",
                "investment": 100_000, "entry_valuation": 18_000_000, "current_valuation": 18_000_000,
                "days_ago": 150, "liquidity_in_days": 365 * 6, "liquidity_event_type": "IPO",
                "notes": "Example company (invented). Iron-air batteries for multi-day grid storage. Pre-revenue; held at entry valuation.",
                "dcf": [],
            },
        ],
    },
]

WATCHLIST = ["AMD", "TSM", "ENPH"]

STARTUPS = [
    {
        "name": "Tidewater Sensors (example)", "source": "MIT delta v", "sector": "Climate", "stage": "Pre-seed", "status": "Met",
        "website": "", "description": "Example entry (invented). Low-cost salinity sensors that let coastal farms time irrigation.",
        "contacts": [{"name": "Jordan Avery", "role": "Co-founder, CEO", "email": "jordan@example.com",
                      "notes": "Met at demo day. Wants intros to agricultural co-ops."}],
        "notes": ["Pilot with two farms planned for spring. Follow up after their first data comes back.",
                  "Team of three, two from the same lab. Hardware cost per unit is the open question."],
    },
    {
        "name": "Ledgerline Health (example)", "source": "MIT Sloan class", "sector": "Healthcare", "stage": "Seed", "status": "In diligence",
        "website": "", "description": "Example entry (invented). Automates prior-authorization paperwork for small clinics.",
        "contacts": [{"name": "Priya Nair", "role": "Co-founder, COO", "email": "priya@example.com",
                      "notes": "Classmate. Shared their pipeline numbers."},
                     {"name": "Sam Okoro", "role": "Co-founder, CTO", "email": "sam@example.com", "notes": ""}],
        "notes": ["Twelve paying clinics. Asked for churn by cohort before the next conversation."],
    },
    {
        "name": "Quarry AI (example)", "source": "MIT $100K", "sector": "AI", "stage": "Idea", "status": "Watching",
        "website": "", "description": "Example entry (invented). Agents that draft permitting documents for construction projects.",
        "contacts": [],
        "notes": [],
    },
]


def load_examples(user_id: int) -> dict:
    """Add the example data to an account. Anything that already exists under
    the same name is left alone, so this is safe to call more than once."""
    added = {"theses": 0, "positions": 0, "startups": 0}

    for t in THESES:
        try:
            new_thesis(user_id, t["name"], t["notes"])
            added["theses"] += 1
        except ValueError:
            continue  # already there: don't add positions to a thesis the user may have changed

        for ticker, shares, price, days in t["public"]:
            try:
                buy(user_id, t["name"], ticker, shares, price, _days_ago(days), EXAMPLE_NOTE)
                added["positions"] += 1
            except ValueError:
                pass

        for p in t["private"]:
            try:
                add_private_position(
                    user_id, t["name"], p["company"], p["investment"], p["entry_valuation"],
                    p["current_valuation"], p["notes"], _days_ago(p["days_ago"]),
                    _days_ahead(p["liquidity_in_days"]), p["liquidity_event_type"],
                )
                added["positions"] += 1
            except ValueError:
                continue
            for label, revenue, growth, margin, discount, terminal, years, net_debt, days in p["dcf"]:
                save_dcf_model(user_id, t["name"], p["company"], revenue, growth, margin, discount,
                               terminal, years, net_debt, label)
                # Snapshots are stamped with the save time; back-date the examples
                # so the history reads as assumptions changing over time.
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE dcf_models SET created_at=? WHERE id=(SELECT MAX(id) FROM dcf_models)",
                        (_days_ago(days) + " 12:00:00",)
                    )

    for ticker in WATCHLIST:
        add_to_watchlist(user_id, ticker)

    for s in STARTUPS:
        fields = {k: s[k] for k in ("name", "source", "sector", "stage", "status", "website", "description")}
        try:
            startup_id = add_startup(user_id, **fields)
        except ValueError:
            continue
        added["startups"] += 1
        for c in s["contacts"]:
            add_contact(user_id, startup_id, **c)
        for note in s["notes"]:
            add_note(user_id, startup_id, note)

    return added
