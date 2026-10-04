"""
SQLite database setup, schema, and one-time JSON migration.
"""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("DB_DIR", Path(__file__).parent)) / "tracker.db"
_PORTFOLIOS_JSON = Path(__file__).parent / "portfolios.json"
_WATCHLIST_JSON  = Path(__file__).parent / "watchlist.json"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                email         TEXT,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    NOT NULL DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS theses (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name       TEXT    NOT NULL,
                notes      TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL DEFAULT (date('now')),
                UNIQUE (user_id, name)
            );

            CREATE TABLE IF NOT EXISTS positions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis_id    INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                ticker       TEXT    NOT NULL,
                shares       REAL    NOT NULL,
                entry_price  REAL    NOT NULL,
                entry_date   TEXT    NOT NULL,
                notes        TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS closed_positions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis_id    INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                ticker       TEXT    NOT NULL,
                shares       REAL    NOT NULL,
                entry_price  REAL    NOT NULL,
                entry_date   TEXT    NOT NULL,
                exit_price   REAL    NOT NULL,
                exit_date    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS private_positions (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis_id                INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                company                  TEXT    NOT NULL,
                investment               REAL    NOT NULL,
                entry_valuation          REAL    NOT NULL,
                current_valuation        REAL    NOT NULL,
                entry_date               TEXT    NOT NULL,
                notes                    TEXT    NOT NULL DEFAULT '',
                expected_liquidity_date  TEXT,
                liquidity_event_type     TEXT    NOT NULL DEFAULT '',
                UNIQUE (thesis_id, company)
            );

            CREATE TABLE IF NOT EXISTS closed_private_positions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis_id           INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                company             TEXT    NOT NULL,
                investment          REAL    NOT NULL,
                entry_valuation     REAL    NOT NULL,
                exit_valuation      REAL    NOT NULL,
                entry_date          TEXT    NOT NULL,
                exit_date           TEXT    NOT NULL,
                notes               TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                ticker    TEXT    NOT NULL,
                added_at  TEXT    NOT NULL DEFAULT (date('now')),
                UNIQUE (user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS companies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL UNIQUE,
                ticker          TEXT,
                company_type    TEXT    NOT NULL DEFAULT 'public',
                description     TEXT    NOT NULL DEFAULT '',
                sector          TEXT    NOT NULL DEFAULT '',
                industry        TEXT    NOT NULL DEFAULT '',
                stage           TEXT    NOT NULL DEFAULT '',
                founded_year    INTEGER,
                headquarters    TEXT    NOT NULL DEFAULT '',
                website         TEXT    NOT NULL DEFAULT '',
                employee_count  TEXT    NOT NULL DEFAULT '',
                is_verified     INTEGER NOT NULL DEFAULT 0,
                verified_at     TEXT,
                verified_by     TEXT,
                created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                entity_type  TEXT    NOT NULL,
                entity_id    INTEGER NOT NULL,
                filename     TEXT    NOT NULL,
                mime_type    TEXT    NOT NULL DEFAULT 'application/octet-stream',
                size_bytes   INTEGER NOT NULL DEFAULT 0,
                data         BLOB    NOT NULL,
                uploaded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS dcf_models (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                private_position_id  INTEGER NOT NULL REFERENCES private_positions(id) ON DELETE CASCADE,
                label                TEXT    NOT NULL DEFAULT '',
                base_revenue         REAL    NOT NULL,
                revenue_growth       REAL    NOT NULL,
                fcf_margin           REAL    NOT NULL,
                discount_rate        REAL    NOT NULL,
                terminal_growth      REAL    NOT NULL,
                years                INTEGER NOT NULL,
                net_debt             REAL    NOT NULL DEFAULT 0,
                enterprise_value     REAL    NOT NULL,
                equity_value         REAL    NOT NULL,
                created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS startups (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name         TEXT    NOT NULL,
                source       TEXT    NOT NULL DEFAULT '',
                sector       TEXT    NOT NULL DEFAULT '',
                stage        TEXT    NOT NULL DEFAULT '',
                status       TEXT    NOT NULL DEFAULT 'Watching',
                website      TEXT    NOT NULL DEFAULT '',
                description  TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (user_id, name)
            );

            CREATE TABLE IF NOT EXISTS startup_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                startup_id  INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                body        TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS startup_contacts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                startup_id  INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                name        TEXT    NOT NULL,
                role        TEXT    NOT NULL DEFAULT '',
                email       TEXT    NOT NULL DEFAULT '',
                phone       TEXT    NOT NULL DEFAULT '',
                linkedin    TEXT    NOT NULL DEFAULT '',
                notes       TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)
    # Add columns introduced after initial schema — safe to run repeatedly
    with get_conn() as conn:
        for sql in [
            "ALTER TABLE private_positions ADD COLUMN expected_liquidity_date TEXT",
            "ALTER TABLE private_positions ADD COLUMN liquidity_event_type TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE positions ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists

    migrate_from_json()
    seed_companies()


_MAG7 = [
    {
        "name": "Apple Inc.", "ticker": "AAPL", "company_type": "public",
        "sector": "Technology", "industry": "Consumer Electronics",
        "founded_year": 1976, "headquarters": "Cupertino, CA",
        "website": "https://www.apple.com", "employee_count": "161,000+",
        "description": (
            "Designs, manufactures, and markets smartphones, personal computers, tablets, "
            "wearables, and accessories. Also sells software, services, and third-party digital "
            "content. Products include iPhone, Mac, iPad, Apple Watch, and Apple TV."
        ),
    },
    {
        "name": "Microsoft Corporation", "ticker": "MSFT", "company_type": "public",
        "sector": "Technology", "industry": "Software & Cloud",
        "founded_year": 1975, "headquarters": "Redmond, WA",
        "website": "https://www.microsoft.com", "employee_count": "228,000+",
        "description": (
            "Develops, licenses, and supports software, services, devices, and solutions. "
            "Segments include Productivity & Business Processes (Office, LinkedIn), Intelligent "
            "Cloud (Azure), and More Personal Computing (Windows, Xbox, Surface)."
        ),
    },
    {
        "name": "Alphabet Inc.", "ticker": "GOOGL", "company_type": "public",
        "sector": "Technology", "industry": "Internet Services & Infrastructure",
        "founded_year": 1998, "headquarters": "Mountain View, CA",
        "website": "https://abc.xyz", "employee_count": "181,000+",
        "description": (
            "Parent company of Google. Operates through Google Services (Search, YouTube, "
            "Maps, Gmail, Android, Chrome), Google Cloud, and Other Bets including Waymo "
            "(autonomous vehicles) and DeepMind (AI research)."
        ),
    },
    {
        "name": "Amazon.com Inc.", "ticker": "AMZN", "company_type": "public",
        "sector": "Consumer Discretionary", "industry": "E-Commerce & Cloud Computing",
        "founded_year": 1994, "headquarters": "Seattle, WA",
        "website": "https://www.amazon.com", "employee_count": "1,500,000+",
        "description": (
            "Operates through three segments: North America and International (online retail, "
            "Prime, Alexa devices) and Amazon Web Services (AWS), the leading cloud computing "
            "platform providing infrastructure, databases, analytics, and AI services."
        ),
    },
    {
        "name": "Meta Platforms Inc.", "ticker": "META", "company_type": "public",
        "sector": "Technology", "industry": "Social Media & Advertising",
        "founded_year": 2004, "headquarters": "Menlo Park, CA",
        "website": "https://www.meta.com", "employee_count": "67,000+",
        "description": (
            "Builds technology to connect people. Products include Facebook, Instagram, "
            "WhatsApp, and Messenger. Also developing augmented and virtual reality hardware "
            "and software through Reality Labs (Quest headsets, Ray-Ban Meta glasses)."
        ),
    },
    {
        "name": "NVIDIA Corporation", "ticker": "NVDA", "company_type": "public",
        "sector": "Technology", "industry": "Semiconductors & AI Infrastructure",
        "founded_year": 1993, "headquarters": "Santa Clara, CA",
        "website": "https://www.nvidia.com", "employee_count": "36,000+",
        "description": (
            "Designs graphics processing units (GPUs) and system-on-chip units. Segments "
            "include Graphics (GeForce, Quadro) and Compute & Networking (data center AI "
            "accelerators, CUDA platform, Mellanox networking). Dominant in AI training "
            "and inference infrastructure."
        ),
    },
    {
        "name": "Tesla Inc.", "ticker": "TSLA", "company_type": "public",
        "sector": "Consumer Discretionary", "industry": "Electric Vehicles & Energy",
        "founded_year": 2003, "headquarters": "Austin, TX",
        "website": "https://www.tesla.com", "employee_count": "125,000+",
        "description": (
            "Designs, develops, manufactures, and sells battery electric vehicles, solar "
            "energy generation systems, and energy storage products. Also develops full "
            "self-driving technology and operates the Supercharger network globally."
        ),
    },
]


def seed_companies() -> None:
    """Insert Mag 7 companies if not already present. Marks them as verified."""
    with get_conn() as conn:
        for c in _MAG7:
            existing = conn.execute(
                "SELECT id FROM companies WHERE name=?", (c["name"],)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO companies "
                    "(name, ticker, company_type, description, sector, industry, "
                    "founded_year, headquarters, website, employee_count, "
                    "is_verified, verified_at, verified_by) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,1,datetime('now'),'system')",
                    (c["name"], c["ticker"], c["company_type"], c["description"],
                     c["sector"], c["industry"], c["founded_year"],
                     c["headquarters"], c["website"], c["employee_count"]),
                )


def migrate_from_json() -> None:
    """One-shot migration from portfolios.json / watchlist.json. Safe to run multiple times."""
    if not _PORTFOLIOS_JSON.exists() and not _WATCHLIST_JSON.exists():
        return

    import bcrypt as _bcrypt

    with get_conn() as conn:
        # The imported data belongs to an 'admin' user. That user is only created
        # when MIGRATE_DEFAULT_PASSWORD is set: there is no built-in default password.
        default_password = os.getenv("MIGRATE_DEFAULT_PASSWORD")
        existing = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if existing:
            user_id = existing["id"]
        elif not default_password:
            print("[migrate] Skipping JSON import: set MIGRATE_DEFAULT_PASSWORD to create the 'admin' user that owns it.")
            return
        else:
            pw_hash = _bcrypt.hashpw(default_password[:72].encode(), _bcrypt.gensalt()).decode()
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES ('admin', ?)",
                (pw_hash,)
            )
            user_id = cur.lastrowid
            print("[migrate] Created user 'admin' with the password from MIGRATE_DEFAULT_PASSWORD.")

        if _PORTFOLIOS_JSON.exists():
            data = json.loads(_PORTFOLIOS_JSON.read_text())
            thesis_count = 0
            pos_count = 0

            for name, thesis in data.items():
                created = thesis.get("created", "")
                notes = thesis.get("notes", "")
                try:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO theses (user_id, name, notes, created_at) VALUES (?,?,?,?)",
                        (user_id, name, notes, created)
                    )
                    if cur.lastrowid:
                        thesis_id = cur.lastrowid
                    else:
                        thesis_id = conn.execute(
                            "SELECT id FROM theses WHERE user_id=? AND name=?", (user_id, name)
                        ).fetchone()["id"]
                    thesis_count += 1
                except Exception as e:
                    print(f"[migrate] Skipping thesis '{name}': {e}")
                    continue

                for pos in thesis.get("positions", []):
                    try:
                        conn.execute(
                            "INSERT INTO positions (thesis_id, ticker, shares, entry_price, entry_date) VALUES (?,?,?,?,?)",
                            (thesis_id, pos["ticker"], pos["shares"], pos["entry_price"], pos["entry_date"])
                        )
                        pos_count += 1
                    except Exception:
                        pass

                for pos in thesis.get("closed_positions", []):
                    try:
                        conn.execute(
                            "INSERT INTO closed_positions (thesis_id, ticker, shares, entry_price, entry_date, exit_price, exit_date) VALUES (?,?,?,?,?,?,?)",
                            (thesis_id, pos["ticker"], pos["shares"], pos["entry_price"],
                             pos["entry_date"], pos["exit_price"], pos["exit_date"])
                        )
                        pos_count += 1
                    except Exception:
                        pass

                for pos in thesis.get("private_positions", []):
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO private_positions "
                            "(thesis_id, company, investment, entry_valuation, current_valuation, entry_date, notes) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (thesis_id, pos["company"], pos["investment"], pos["entry_valuation"],
                             pos["current_valuation"], pos["entry_date"], pos.get("notes", ""))
                        )
                        pos_count += 1
                    except Exception:
                        pass

                for pos in thesis.get("closed_private_positions", []):
                    try:
                        conn.execute(
                            "INSERT INTO closed_private_positions "
                            "(thesis_id, company, investment, entry_valuation, exit_valuation, entry_date, exit_date, notes) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (thesis_id, pos["company"], pos["investment"], pos["entry_valuation"],
                             pos["exit_valuation"], pos["entry_date"], pos["exit_date"], pos.get("notes", ""))
                        )
                        pos_count += 1
                    except Exception:
                        pass

            print(f"[migrate] Imported {thesis_count} theses, {pos_count} positions for user 'admin'")

        if _WATCHLIST_JSON.exists():
            tickers = json.loads(_WATCHLIST_JSON.read_text())
            for ticker in tickers:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (user_id, ticker) VALUES (?,?)",
                        (user_id, ticker)
                    )
                except Exception:
                    pass
            print(f"[migrate] Imported {len(tickers)} watchlist tickers")
