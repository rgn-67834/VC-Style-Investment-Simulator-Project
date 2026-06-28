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
                entry_date   TEXT    NOT NULL
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
        """)
    # Add columns introduced after initial schema — safe to run repeatedly
    with get_conn() as conn:
        for sql in [
            "ALTER TABLE private_positions ADD COLUMN expected_liquidity_date TEXT",
            "ALTER TABLE private_positions ADD COLUMN liquidity_event_type TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists

    migrate_from_json()


def migrate_from_json() -> None:
    """One-shot migration from portfolios.json / watchlist.json. Safe to run multiple times."""
    if not _PORTFOLIOS_JSON.exists() and not _WATCHLIST_JSON.exists():
        return

    import bcrypt as _bcrypt

    with get_conn() as conn:
        default_password = os.getenv("MIGRATE_DEFAULT_PASSWORD", "changeme")
        existing = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if existing:
            user_id = existing["id"]
        else:
            pw_hash = _bcrypt.hashpw(default_password[:72].encode(), _bcrypt.gensalt()).decode()
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES ('admin', ?)",
                (pw_hash,)
            )
            user_id = cur.lastrowid
            print(f"[migrate] Created default user 'admin' (password: {default_password})")
            print("[migrate] IMPORTANT: Change this password after first login.")

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
