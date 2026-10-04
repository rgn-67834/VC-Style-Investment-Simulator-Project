"""
FastAPI web server for the investment thesis tracker.
Run locally:  uvicorn app:app --reload
Railway:      auto-detected via Procfile
"""

import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from auth import create_access_token, get_current_user, hash_password, verify_password
from database import get_conn, init_db
from portfolio import (
    add_private_position, buy, close_position, close_private_position, compute_dcf,
    delete_dcf_model, delete_position, delete_private_position, delete_thesis,
    get_all_thesis_data, get_dcf_models, new_thesis, save_dcf_model,
    update_private_valuation, update_thesis_notes,
)
from examples import load_examples
from pipeline import (
    STATUSES, add_contact, add_note, add_startup, delete_contact, delete_note,
    delete_startup, get_startups, update_startup,
)
from watchlist_manager import add_to_watchlist, get_watchlist_data, remove_from_watchlist

app = FastAPI(title="Crossover")


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
    content = Path("static/index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})


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
    # A new account starts with example data so the app is not empty.
    # It must never block sign-up, so any failure is only logged.
    try:
        load_examples(user_id)
    except Exception as e:
        print(f"[examples] Could not load example data for user {user_id}: {e}")
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


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/change-password")
def api_change_password(body: ChangePasswordBody,
                        current_user: dict = Depends(get_current_user)):
    if len(body.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters.")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=?", (current_user["id"],)
        ).fetchone()
        if not verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(400, "Current password is incorrect.")
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(body.new_password), current_user["id"])
        )
    return {"ok": True}


@app.post("/api/examples")
def api_load_examples(current_user: dict = Depends(get_current_user)):
    """Add the example theses, watchlist and pipeline to an existing account."""
    added = load_examples(current_user["id"])
    _bust(current_user["id"])
    return added


@app.get("/api/auth/me")
def api_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "is_admin": bool(current_user.get("is_admin")),
    }


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
    notes: str = ""


@app.post("/api/theses/{thesis_name}/positions", status_code=201)
def api_add_position(thesis_name: str, body: NewPositionBody,
                     current_user: dict = Depends(get_current_user)):
    try:
        buy(current_user["id"], thesis_name, body.ticker, body.shares, body.price, body.entry_date, body.notes)
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
# DCF models
# ---------------------------------------------------------------------------

class DcfAssumptions(BaseModel):
    base_revenue: float
    revenue_growth: float
    fcf_margin: float
    discount_rate: float
    terminal_growth: float
    years: int
    net_debt: float = 0.0


class SaveDcfBody(DcfAssumptions):
    label: str = ""
    apply_valuation: bool = False


@app.post("/api/dcf/preview")
def api_dcf_preview(body: DcfAssumptions, current_user: dict = Depends(get_current_user)):
    try:
        return compute_dcf(**body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/theses/{thesis_name}/private-positions/{company}/dcf")
def api_get_dcf(thesis_name: str, company: str,
                current_user: dict = Depends(get_current_user)):
    try:
        return get_dcf_models(current_user["id"], thesis_name, company)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/theses/{thesis_name}/private-positions/{company}/dcf", status_code=201)
def api_save_dcf(thesis_name: str, company: str, body: SaveDcfBody,
                 current_user: dict = Depends(get_current_user)):
    try:
        result = save_dcf_model(current_user["id"], thesis_name, company, **body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.apply_valuation:
        _bust(current_user["id"])
    return result


@app.delete("/api/dcf/{model_id}")
def api_delete_dcf(model_id: int, current_user: dict = Depends(get_current_user)):
    try:
        delete_dcf_model(current_user["id"], model_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
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


# ---------------------------------------------------------------------------
# Attachments  (entity_type: "position" | "private_position")
# ---------------------------------------------------------------------------

@app.post("/api/attachments", status_code=201)
async def upload_attachment(
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    data = await file.read()
    filename = file.filename or "attachment"
    mime = file.content_type or "application/octet-stream"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO attachments (user_id, entity_type, entity_id, filename, mime_type, size_bytes, data) "
            "VALUES (?,?,?,?,?,?,?)",
            (current_user["id"], entity_type, entity_id, filename, mime, len(data), data),
        )
    return {"ok": True}


@app.get("/api/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename, mime_type, data FROM attachments WHERE id=? AND user_id=?",
            (attachment_id, current_user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Attachment not found.")
    safe_name = row["filename"].replace('"', '_')
    return Response(
        content=bytes(row["data"]),
        media_type=row["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@app.get("/api/attachments/{entity_type}/{entity_id}")
def list_attachments(entity_type: str, entity_id: int,
                     current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, mime_type, size_bytes, uploaded_at FROM attachments "
            "WHERE user_id=? AND entity_type=? AND entity_id=? ORDER BY uploaded_at",
            (current_user["id"], entity_type, entity_id),
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM attachments WHERE id=? AND user_id=?",
            (attachment_id, current_user["id"]),
        )
    if cur.rowcount == 0:
        raise HTTPException(404, "Attachment not found.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Company profiles
# ---------------------------------------------------------------------------

class CompanyBody(BaseModel):
    name: str
    ticker: Optional[str] = None
    company_type: str = "public"
    description: str = ""
    sector: str = ""
    industry: str = ""
    stage: str = ""
    founded_year: Optional[int] = None
    headquarters: str = ""
    website: str = ""
    employee_count: str = ""


@app.get("/api/companies")
def api_list_companies(search: str = "",
                       current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        if search.strip():
            pat = f"%{search.strip()}%"
            rows = conn.execute(
                "SELECT * FROM companies WHERE name LIKE ? OR ticker LIKE ? OR sector LIKE ? "
                "ORDER BY is_verified DESC, name",
                (pat, pat, pat),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM companies ORDER BY is_verified DESC, name"
            ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/companies", status_code=201)
def api_create_company(body: CompanyBody,
                       current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO companies (name, ticker, company_type, description, sector, industry, "
                "stage, founded_year, headquarters, website, employee_count, created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.name.strip(),
                 body.ticker.strip().upper() if body.ticker else None,
                 body.company_type, body.description, body.sector, body.industry,
                 body.stage, body.founded_year, body.headquarters,
                 body.website, body.employee_count, current_user["id"]),
            )
        except Exception:
            raise HTTPException(400, f"A company named '{body.name.strip()}' already exists.")
    return {"ok": True, "id": cur.lastrowid}


@app.patch("/api/companies/{company_id}")
def api_update_company(company_id: int, body: CompanyBody,
                       current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Company not found.")
        if not current_user.get("is_admin") and row["created_by"] != current_user["id"]:
            raise HTTPException(403, "You can only edit companies you created.")
        conn.execute(
            "UPDATE companies SET name=?, ticker=?, company_type=?, description=?, sector=?, "
            "industry=?, stage=?, founded_year=?, headquarters=?, website=?, employee_count=?, "
            "updated_at=datetime('now') WHERE id=?",
            (body.name.strip(),
             body.ticker.strip().upper() if body.ticker else None,
             body.company_type, body.description, body.sector, body.industry,
             body.stage, body.founded_year, body.headquarters,
             body.website, body.employee_count, company_id),
        )
    return {"ok": True}


@app.post("/api/companies/{company_id}/verify")
def api_verify_company(company_id: int,
                       current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(403, "Only administrators can verify companies.")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE companies SET is_verified=1, verified_at=datetime('now'), verified_by=? WHERE id=?",
            (current_user["username"], company_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(404, "Company not found.")
    return {"ok": True}


@app.post("/api/companies/{company_id}/unverify")
def api_unverify_company(company_id: int,
                         current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(403, "Only administrators can modify verification.")
    with get_conn() as conn:
        conn.execute(
            "UPDATE companies SET is_verified=0, verified_at=NULL, verified_by=NULL WHERE id=?",
            (company_id,),
        )
    return {"ok": True}


@app.delete("/api/companies/{company_id}")
def api_delete_company(company_id: int,
                       current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Company not found.")
        if not current_user.get("is_admin") and row["created_by"] != current_user["id"]:
            raise HTTPException(403, "You can only delete companies you created.")
        conn.execute("DELETE FROM companies WHERE id=?", (company_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Startup pipeline
# ---------------------------------------------------------------------------

class StartupBody(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    sector: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None


class StartupNoteBody(BaseModel):
    body: str


class StartupContactBody(BaseModel):
    name: str
    role: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    notes: str = ""


@app.get("/api/startups")
def api_get_startups(current_user: dict = Depends(get_current_user)):
    return {"statuses": STATUSES, "startups": get_startups(current_user["id"])}


@app.post("/api/startups", status_code=201)
def api_add_startup(body: StartupBody, current_user: dict = Depends(get_current_user)):
    try:
        startup_id = add_startup(current_user["id"], **body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": startup_id}


@app.patch("/api/startups/{startup_id}")
def api_update_startup(startup_id: int, body: StartupBody,
                       current_user: dict = Depends(get_current_user)):
    try:
        update_startup(current_user["id"], startup_id, **body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/startups/{startup_id}")
def api_delete_startup(startup_id: int, current_user: dict = Depends(get_current_user)):
    try:
        delete_startup(current_user["id"], startup_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/startups/{startup_id}/notes", status_code=201)
def api_add_startup_note(startup_id: int, body: StartupNoteBody,
                         current_user: dict = Depends(get_current_user)):
    try:
        add_note(current_user["id"], startup_id, body.body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/startup-notes/{note_id}")
def api_delete_startup_note(note_id: int, current_user: dict = Depends(get_current_user)):
    try:
        delete_note(current_user["id"], note_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/startups/{startup_id}/contacts", status_code=201)
def api_add_startup_contact(startup_id: int, body: StartupContactBody,
                            current_user: dict = Depends(get_current_user)):
    try:
        add_contact(current_user["id"], startup_id, **body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/startup-contacts/{contact_id}")
def api_delete_startup_contact(contact_id: int, current_user: dict = Depends(get_current_user)):
    try:
        delete_contact(current_user["id"], contact_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}
