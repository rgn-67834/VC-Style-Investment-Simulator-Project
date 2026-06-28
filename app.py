"""
FastAPI web server for the investment thesis tracker.
Run locally:  uvicorn app:app --reload
Railway:      auto-detected via Procfile
"""

import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from auth import create_access_token, get_current_user, hash_password, verify_password
from database import get_conn, init_db
from portfolio import (
    add_private_position, buy, close_position, close_private_position,
    delete_position, delete_private_position, delete_thesis, get_all_thesis_data,
    new_thesis, update_private_valuation, update_thesis_notes,
)
from watchlist_manager import add_to_watchlist, get_watchlist_data, remove_from_watchlist

app = FastAPI(title="Thesis Tracker")


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------------------
# Per-user in-memory cache
# ---------------------------------------------------------------------------

_cache: dict[int, dict] = {}
CACHE_TTL = 300  # seconds


def _cached_theses(user_id: int, force: bool = False) -> list:
    now   = time.time()
    entry = _cache.get(user_id, {})
    if force or not entry or (now - entry.get("ts", 0)) > CACHE_TTL:
        entry = {
            "theses":    get_all_thesis_data(user_id),
            "watchlist": get_watchlist_data(user_id),
            "ts":        now,
        }
        _cache[user_id] = entry
    return entry["theses"]


def _cached_watchlist(user_id: int) -> list:
    _cached_theses(user_id)
    return _cache.get(user_id, {}).get("watchlist", [])


def _bust(user_id: int) -> None:
    _cache.pop(user_id, None)


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    return Path("static/index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

class SignupBody(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/signup", status_code=201)
def api_signup(body: SignupBody):
    if not body.username.strip():
        raise HTTPException(400, "Username cannot be empty.")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username=?", (body.username.strip(),)
        ).fetchone()
        if existing:
            raise HTTPException(400, "Username already taken.")
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?,?,?)",
            (body.username.strip(), body.email, hash_password(body.password))
        )
        user_id = cur.lastrowid
    token = create_access_token(user_id, body.username.strip())
    return {"token": token, "username": body.username.strip()}


@app.post("/api/auth/login")
def api_login(body: LoginBody):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username=?",
            (body.username.strip(),)
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid username or password.")
    token = create_access_token(row["id"], row["username"])
    return {"token": token, "username": row["username"]}


@app.get("/api/auth/me")
def api_me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "username": current_user["username"]}


# ---------------------------------------------------------------------------
# Theses
# ---------------------------------------------------------------------------

@app.get("/api/theses")
def api_get_theses(refresh: bool = False, current_user: dict = Depends(get_current_user)):
    return _cached_theses(current_user["id"], force=refresh)


class NewThesisBody(BaseModel):
    name: str
    notes: str = ""


@app.post("/api/theses", status_code=201)
def api_new_thesis(body: NewThesisBody, current_user: dict = Depends(get_current_user)):
    try:
        new_thesis(current_user["id"], body.name, body.notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


class UpdateThesisBody(BaseModel):
    notes: str


@app.patch("/api/theses/{thesis_name}")
def api_update_thesis(thesis_name: str, body: UpdateThesisBody,
                      current_user: dict = Depends(get_current_user)):
    try:
        update_thesis_notes(current_user["id"], thesis_name, body.notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


@app.delete("/api/theses/{thesis_name}")
def api_delete_thesis(thesis_name: str, current_user: dict = Depends(get_current_user)):
    try:
        delete_thesis(current_user["id"], thesis_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Public positions
# ---------------------------------------------------------------------------

class NewPositionBody(BaseModel):
    ticker: str
    shares: float
    price: Optional[float] = None
    entry_date: Optional[str] = None


@app.post("/api/theses/{thesis_name}/positions", status_code=201)
def api_add_position(thesis_name: str, body: NewPositionBody,
                     current_user: dict = Depends(get_current_user)):
    try:
        buy(current_user["id"], thesis_name, body.ticker, body.shares, body.price, body.entry_date)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


class ClosePositionBody(BaseModel):
    exit_price: Optional[float] = None


@app.post("/api/theses/{thesis_name}/positions/{ticker}/close")
def api_close_position(thesis_name: str, ticker: str, body: ClosePositionBody,
                       current_user: dict = Depends(get_current_user)):
    try:
        close_position(current_user["id"], thesis_name, ticker, body.exit_price)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


@app.delete("/api/theses/{thesis_name}/positions/{ticker}")
def api_delete_position(thesis_name: str, ticker: str,
                        current_user: dict = Depends(get_current_user)):
    try:
        delete_position(current_user["id"], thesis_name, ticker)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Private positions
# ---------------------------------------------------------------------------

class NewPrivateBody(BaseModel):
    company: str
    investment: float
    entry_valuation: float
    current_valuation: Optional[float] = None
    notes: str = ""
    entry_date: Optional[str] = None
    expected_liquidity_date: Optional[str] = None
    liquidity_event_type: str = ""


@app.post("/api/theses/{thesis_name}/private-positions", status_code=201)
def api_add_private(thesis_name: str, body: NewPrivateBody,
                    current_user: dict = Depends(get_current_user)):
    try:
        add_private_position(
            current_user["id"], thesis_name, body.company, body.investment,
            body.entry_valuation, body.current_valuation, body.notes, body.entry_date,
            body.expected_liquidity_date, body.liquidity_event_type,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


class UpdateValuationBody(BaseModel):
    current_valuation: float
    notes: Optional[str] = None


@app.patch("/api/theses/{thesis_name}/private-positions/{company}")
def api_update_private(thesis_name: str, company: str, body: UpdateValuationBody,
                       current_user: dict = Depends(get_current_user)):
    try:
        update_private_valuation(
            current_user["id"], thesis_name, company, body.current_valuation, body.notes
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


class ClosePrivateBody(BaseModel):
    exit_valuation: float


@app.post("/api/theses/{thesis_name}/private-positions/{company}/close")
def api_close_private(thesis_name: str, company: str, body: ClosePrivateBody,
                      current_user: dict = Depends(get_current_user)):
    try:
        close_private_position(current_user["id"], thesis_name, company, body.exit_valuation)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


@app.delete("/api/theses/{thesis_name}/private-positions/{company}")
def api_delete_private(thesis_name: str, company: str,
                       current_user: dict = Depends(get_current_user)):
    try:
        delete_private_position(current_user["id"], thesis_name, company)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust(current_user["id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@app.get("/api/watchlist")
def api_get_watchlist(current_user: dict = Depends(get_current_user)):
    return _cached_watchlist(current_user["id"])


class WatchlistBody(BaseModel):
    ticker: str


@app.post("/api/watchlist", status_code=201)
def api_add_watchlist(body: WatchlistBody, current_user: dict = Depends(get_current_user)):
    add_to_watchlist(current_user["id"], body.ticker)
    _bust(current_user["id"])
    return {"ok": True}


@app.delete("/api/watchlist/{ticker}")
def api_remove_watchlist(ticker: str, current_user: dict = Depends(get_current_user)):
    remove_from_watchlist(current_user["id"], ticker)
    _bust(current_user["id"])
    return {"ok": True}
