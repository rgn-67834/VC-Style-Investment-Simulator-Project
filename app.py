"""
FastAPI web server for the investment thesis tracker.
Run locally:  uvicorn app:app --reload
Railway:      auto-detected via Procfile
"""

import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from portfolio import (
    get_all_thesis_data, new_thesis, buy, close_position, delete_position,
    add_private_position, update_private_valuation, close_private_position, delete_private_position,
    _load,
)
from watchlist_manager import get_watchlist_data, add_to_watchlist, remove_from_watchlist

app = FastAPI(title="Thesis Tracker")

# ---------------------------------------------------------------------------
# Simple in-memory cache so yfinance isn't hit on every request
# ---------------------------------------------------------------------------

_cache: dict = {"theses": None, "watchlist": None, "ts": 0}
CACHE_TTL = 300  # seconds


def _cached_theses(force: bool = False) -> list:
    now = time.time()
    if force or _cache["theses"] is None or (now - _cache["ts"]) > CACHE_TTL:
        _cache["theses"] = get_all_thesis_data()
        _cache["watchlist"] = get_watchlist_data()
        _cache["ts"] = now
    return _cache["theses"]


def _cached_watchlist() -> list:
    _cached_theses()  # ensures both are populated
    return _cache["watchlist"] or []


def _bust() -> None:
    _cache["theses"] = None
    _cache["watchlist"] = None


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    return Path("static/index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# API — theses
# ---------------------------------------------------------------------------

@app.get("/api/theses")
def api_get_theses(refresh: bool = False):
    return _cached_theses(force=refresh)


class NewThesisBody(BaseModel):
    name: str


@app.post("/api/theses", status_code=201)
def api_new_thesis(body: NewThesisBody):
    data = _load()
    if body.name in data:
        raise HTTPException(400, f"Thesis '{body.name}' already exists.")
    new_thesis(body.name)
    _bust()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — positions
# ---------------------------------------------------------------------------

class NewPositionBody(BaseModel):
    ticker: str
    shares: float
    price: Optional[float] = None
    entry_date: Optional[str] = None


@app.post("/api/theses/{thesis_name}/positions", status_code=201)
def api_add_position(thesis_name: str, body: NewPositionBody):
    try:
        buy(thesis_name, body.ticker, body.shares, body.price, body.entry_date)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


class ClosePositionBody(BaseModel):
    exit_price: Optional[float] = None


@app.post("/api/theses/{thesis_name}/positions/{ticker}/close")
def api_close_position(thesis_name: str, ticker: str, body: ClosePositionBody):
    try:
        close_position(thesis_name, ticker, body.exit_price)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


@app.delete("/api/theses/{thesis_name}/positions/{ticker}")
def api_delete_position(thesis_name: str, ticker: str):
    try:
        delete_position(thesis_name, ticker)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — private positions
# ---------------------------------------------------------------------------

class NewPrivateBody(BaseModel):
    company: str
    investment: float
    entry_valuation: float
    current_valuation: Optional[float] = None
    notes: str = ""
    entry_date: Optional[str] = None


@app.post("/api/theses/{thesis_name}/private-positions", status_code=201)
def api_add_private(thesis_name: str, body: NewPrivateBody):
    try:
        add_private_position(thesis_name, body.company, body.investment,
                             body.entry_valuation, body.current_valuation, body.notes, body.entry_date)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


class UpdateValuationBody(BaseModel):
    current_valuation: float
    notes: Optional[str] = None


@app.patch("/api/theses/{thesis_name}/private-positions/{company}")
def api_update_private(thesis_name: str, company: str, body: UpdateValuationBody):
    try:
        update_private_valuation(thesis_name, company, body.current_valuation, body.notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


class ClosePrivateBody(BaseModel):
    exit_valuation: float


@app.post("/api/theses/{thesis_name}/private-positions/{company}/close")
def api_close_private(thesis_name: str, company: str, body: ClosePrivateBody):
    try:
        close_private_position(thesis_name, company, body.exit_valuation)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


@app.delete("/api/theses/{thesis_name}/private-positions/{company}")
def api_delete_private(thesis_name: str, company: str):
    try:
        delete_private_position(thesis_name, company)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bust()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — watchlist
# ---------------------------------------------------------------------------

@app.get("/api/watchlist")
def api_get_watchlist():
    return _cached_watchlist()


class WatchlistBody(BaseModel):
    ticker: str


@app.post("/api/watchlist", status_code=201)
def api_add_watchlist(body: WatchlistBody):
    add_to_watchlist(body.ticker)
    _bust()
    return {"ok": True}


@app.delete("/api/watchlist/{ticker}")
def api_remove_watchlist(ticker: str):
    remove_from_watchlist(ticker)
    _bust()
    return {"ok": True}
