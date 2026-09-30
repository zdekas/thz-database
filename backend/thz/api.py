import datetime as dt
import json
import os
from pathlib import Path

import numpy as np
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, records, spectra

STATIC = Path(__file__).with_name("static")
MAX_SELECTED = 50
COOKIE = "thz_session"

app = FastAPI(title="THz transmission database", docs_url="/api/docs", openapi_url="/api/openapi.json")


# ---------------------------------------------------------------- public, read-only

def _ids(text):
    try:
        ids = [int(p) for p in text.split(",") if p.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    if not ids or len(ids) > MAX_SELECTED:
        raise HTTPException(400, f"select between 1 and {MAX_SELECTED} datasets")
    return ids


@app.get("/api/measurements")
def measurements(q: str = "", ids: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    """Every word of the query must occur somewhere in the metadata."""
    words = q.split()[:10]
    where = ["m.search_text ILIKE %s"] * len(words)
    args = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]
    if ids:
        where.append("m.id = ANY(%s)")
        args.append(_ids(ids))
    with db.connect("web") as conn:
        rows = conn.execute(
            f"""
            SELECT m.id, m.slug, m.sample_name, m.experiment_date, m.responsible_person, m.added_by,
                   m.description, m.sample_type, m.reference_type, m.material, m.substrate,
                   m.thickness_nm, m.substrate_thickness_um, m.treatment, m.temperature_k, m.source, m.extra,
                   a.treatment <> '{{}}'::jsonb AS treated
            FROM raw.measurement m JOIN analysed.transmission a ON a.measurement_id = m.id
            WHERE {" AND ".join(where) or "TRUE"}
            ORDER BY m.experiment_date DESC, m.sample_name, m.temperature_k
            LIMIT %s
            """,
            args + [limit],
        ).fetchall()
    return rows


def _clean(arr):
    return [None if not np.isfinite(v) else float(v) for v in arr]


@app.get("/api/spectra")
def spectra_json(ids: str, x: str = "thz", y: str = "abs", full: bool = False):
    try:
        with db.connect("web") as conn:
            series = spectra.build_series(conn, _ids(ids), x, y, full)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "x_label": spectra.X_AXES[x][0],
        "y_label": spectra.Y_AXES[y],
        "series": [
            {"id": row["id"], "slug": row["slug"], "label": spectra.label(row), "x": _clean(xs), "y": _clean(ys)}
            for row, xs, ys in series
        ],
    }


@app.get("/api/export", response_class=PlainTextResponse)
def export(ids: str, x: str = "thz", y: str = "abs", full: bool = False, interp: str | None = None):
    try:
        with db.connect("web") as conn:
            series = spectra.build_series(conn, _ids(ids), x, y, full)
        text = spectra.export_text(series, x, y, full, interp or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    name = f"thz_{y}_vs_{x}_{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}.txt"
    return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- accounts

class Login(BaseModel):
    email: str
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


def current_account(thz_session: str | None = Cookie(None)):
    with db.connect("auth") as conn:
        account = auth.account_for(conn, thz_session)
    if not account:
        raise HTTPException(401, "not logged in")
    return account


def _set_cookie(response, token):
    response.set_cookie(
        COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="strict",
        secure=os.environ.get("COOKIE_SECURE") == "1",
    )


@app.post("/api/auth/login")
def login(body: Login, response: Response):
    if auth.blocked(auth.normalise_email(body.email)):
        raise HTTPException(429, "too many failed attempts, try again in 15 minutes")
    with db.connect("auth") as conn:
        token = auth.login(conn, body.email, body.password)
    if not token:
        raise HTTPException(401, "wrong e-mail or password")
    _set_cookie(response, token)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response, thz_session: str | None = Cookie(None)):
    with db.connect("auth") as conn:
        auth.logout(conn, thz_session)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(account=Depends(current_account)):
    return {"email": account["email"], "name": account["name"]}


@app.post("/api/auth/password")
def change_password(body: PasswordChange, response: Response, account=Depends(current_account)):
    if not auth.verify_password(body.current, account["password_hash"]):
        raise HTTPException(400, "current password is wrong")
    if len(body.new) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"new password must have at least {auth.MIN_PASSWORD_LENGTH} characters")
    with db.connect("auth") as conn:
        auth.set_password(conn, account["email"], body.new)  # ends every session
        token = auth.login(conn, account["email"], body.new)
    _set_cookie(response, token)
    return {"ok": True}


# ---------------------------------------------------------------- adding records (login required)

def _record_error(exc):
    return HTTPException(exc.status, str(exc))


@app.post("/api/admin/preview-waveform")
def preview_waveform(
    file: UploadFile = File(...),
    time_unit: str = Form("ps"),
    time_column: int = Form(0, ge=0, le=50),
    amplitude_column: int = Form(1, ge=0, le=50),
    account=Depends(current_account),
):
    try:
        return records.preview(
            records.read_upload(file), file.filename or "file",
            time_unit=time_unit, time_column=time_column, amplitude_column=amplitude_column,
        )
    except records.RecordError as exc:
        raise _record_error(exc)


@app.post("/api/admin/parse-metadata")
def parse_metadata(file: UploadFile = File(...), account=Depends(current_account)):
    try:
        meta = records.parse_metadata(records.read_upload(file))
    except records.RecordError as exc:
        raise _record_error(exc)
    return json.loads(json.dumps(meta, default=str))


@app.post("/api/admin/records")
def create_record(
    metadata: str = Form(...),
    files: list[UploadFile] = File(...),
    account=Depends(current_account),
):
    try:
        meta = json.loads(metadata)
    except ValueError:
        raise HTTPException(400, "metadata is not valid JSON")
    try:
        return records.create(meta, files, added_by=account["name"] or account["email"])
    except records.RecordError as exc:
        raise _record_error(exc)


class TreatPreview(BaseModel):
    t: list[float]
    e: list[float]
    treatment: dict | None = None


@app.post("/api/admin/treat-preview")
def treat_preview(body: TreatPreview, account=Depends(current_account)):
    try:
        return records.treat_preview(body.t, body.e, body.treatment)
    except records.RecordError as exc:
        raise _record_error(exc)


def _metadata(text):
    try:
        return json.loads(text)
    except ValueError:
        raise HTTPException(400, "metadata is not valid JSON")


@app.get("/api/admin/records/{mid}")
def get_record(mid: int, account=Depends(current_account)):
    try:
        return records.get(mid)
    except records.RecordError as exc:
        raise _record_error(exc)


@app.get("/api/admin/records/{mid}/versions/{version}")
def get_record_version(mid: int, version: int, account=Depends(current_account)):
    try:
        return records.get_version(mid, version)
    except records.RecordError as exc:
        raise _record_error(exc)


@app.put("/api/admin/records/{mid}")
def update_record(
    mid: int,
    metadata: str = Form(...),
    files: list[UploadFile] = File([]),
    account=Depends(current_account),
):
    try:
        return records.update(mid, _metadata(metadata), files, edited_by=account["name"] or account["email"])
    except records.RecordError as exc:
        raise _record_error(exc)


# ---------------------------------------------------------------- pages

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.get("/new")
@app.get("/edit")
def record_page():
    return FileResponse(STATIC / "new.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
