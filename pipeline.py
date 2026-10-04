"""
Startup pipeline: companies a user is tracking before (or instead of) investing,
with a running log of notes and a list of contacts for each.
All functions take user_id first so data stays user-scoped.
"""

from typing import Optional

from database import get_conn

STATUSES = ["Watching", "Met", "In diligence", "Invested", "Passed"]

_STARTUP_FIELDS = ["name", "source", "sector", "stage", "status", "website", "description"]
_CONTACT_FIELDS = ["name", "role", "email", "phone", "linkedin", "notes"]


def _clean(fields: dict, allowed: list[str]) -> dict:
    return {k: (v or "").strip() for k, v in fields.items() if k in allowed}


def _check_startup(data: dict) -> None:
    if "name" in data and not data["name"]:
        raise ValueError("Startup name cannot be empty.")
    if data.get("status") and data["status"] not in STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(STATUSES)}.")


def _owned_startup(conn, user_id: int, startup_id: int):
    row = conn.execute(
        "SELECT * FROM startups WHERE id=? AND user_id=?", (startup_id, user_id)
    ).fetchone()
    if not row:
        raise ValueError("Startup not found.")
    return row


# ---------------------------------------------------------------------------
# Startups
# ---------------------------------------------------------------------------

def get_startups(user_id: int) -> list[dict]:
    with get_conn() as conn:
        startups = [dict(r) for r in conn.execute(
            "SELECT * FROM startups WHERE user_id=? ORDER BY updated_at DESC, id DESC", (user_id,)
        ).fetchall()]
        for s in startups:
            s["contacts"] = [dict(r) for r in conn.execute(
                "SELECT * FROM startup_contacts WHERE startup_id=? ORDER BY id", (s["id"],)
            ).fetchall()]
            s["notes"] = [dict(r) for r in conn.execute(
                "SELECT * FROM startup_notes WHERE startup_id=? ORDER BY created_at DESC, id DESC", (s["id"],)
            ).fetchall()]
    return startups


def add_startup(user_id: int, **fields) -> int:
    data = _clean(fields, _STARTUP_FIELDS)
    data.setdefault("name", "")
    if not data.get("status"):
        data["status"] = STATUSES[0]
    _check_startup(data)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                f"INSERT INTO startups (user_id, {', '.join(data)}) "
                f"VALUES (?, {', '.join('?' for _ in data)})",
                (user_id, *data.values())
            )
        except Exception:
            raise ValueError(f"'{data['name']}' is already in your pipeline.")
    return cur.lastrowid


def update_startup(user_id: int, startup_id: int, **fields) -> None:
    data = _clean(fields, _STARTUP_FIELDS)
    _check_startup(data)
    if not data:
        return
    with get_conn() as conn:
        _owned_startup(conn, user_id, startup_id)
        try:
            conn.execute(
                f"UPDATE startups SET {', '.join(f'{k}=?' for k in data)}, updated_at=datetime('now') "
                "WHERE id=?",
                (*data.values(), startup_id)
            )
        except Exception:
            raise ValueError(f"'{data.get('name')}' is already in your pipeline.")


def delete_startup(user_id: int, startup_id: int) -> None:
    with get_conn() as conn:
        _owned_startup(conn, user_id, startup_id)
        conn.execute("DELETE FROM startups WHERE id=?", (startup_id,))


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def add_note(user_id: int, startup_id: int, body: str) -> None:
    body = (body or "").strip()
    if not body:
        raise ValueError("Note cannot be empty.")
    with get_conn() as conn:
        _owned_startup(conn, user_id, startup_id)
        conn.execute("INSERT INTO startup_notes (startup_id, body) VALUES (?,?)", (startup_id, body))
        conn.execute("UPDATE startups SET updated_at=datetime('now') WHERE id=?", (startup_id,))


def delete_note(user_id: int, note_id: int) -> None:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM startup_notes WHERE id=? AND startup_id IN "
            "(SELECT id FROM startups WHERE user_id=?)",
            (note_id, user_id)
        )
    if cur.rowcount == 0:
        raise ValueError("Note not found.")


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def add_contact(user_id: int, startup_id: int, **fields) -> None:
    data = _clean(fields, _CONTACT_FIELDS)
    if not data.get("name"):
        raise ValueError("Contact name cannot be empty.")
    with get_conn() as conn:
        _owned_startup(conn, user_id, startup_id)
        conn.execute(
            f"INSERT INTO startup_contacts (startup_id, {', '.join(data)}) "
            f"VALUES (?, {', '.join('?' for _ in data)})",
            (startup_id, *data.values())
        )
        conn.execute("UPDATE startups SET updated_at=datetime('now') WHERE id=?", (startup_id,))


def delete_contact(user_id: int, contact_id: int) -> None:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM startup_contacts WHERE id=? AND startup_id IN "
            "(SELECT id FROM startups WHERE user_id=?)",
            (contact_id, user_id)
        )
    if cur.rowcount == 0:
        raise ValueError("Contact not found.")
