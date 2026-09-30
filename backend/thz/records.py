"""Records created through the website.

The uploaded files and a generated metadata.yaml are stored as a normal
measurement folder under UPLOAD_DIR and then go through the same importer as
`thz import`, so the database can always be rebuilt from the files.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
import yaml

from . import analysis, db, importer
from . import treatment as treat

UPLOAD_DIR = Path("/data/uploads")
MAX_FILE_BYTES = 20 * 1024 * 1024
PREVIEW_POINTS = 20000


class RecordError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _safe(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "file"


def read_upload(upload):
    data = upload.file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise RecordError(f"{upload.filename}: file is larger than {MAX_FILE_BYTES // 2**20} MB")
    return data


def preview(data, name, **kw):
    try:
        t, e, info = importer.parse_waveform(data.decode(errors="replace"), name=name, **kw)
    except (importer.ImportError_, ValueError) as exc:
        raise RecordError(str(exc))
    return preview_arrays(t, e, info)


def preview_arrays(t, e, info):
    t, e = np.asarray(t, dtype=float), np.asarray(e, dtype=float)
    dt = float((t[-1] - t[0]) / (len(t) - 1))
    freq = np.fft.rfftfreq(len(e), dt)[1:]
    amp = np.abs(np.fft.rfft(e))[1:]
    step, fstep = (max(1, -(-len(a) // PREVIEW_POINTS)) for a in (t, freq))
    return {
        "n_points": len(t),
        "t_min": float(t[0]),
        "t_max": float(t[-1]),
        "dt": dt,
        "t": t[::step].tolist(),
        "e": e[::step].tolist(),
        "freq_thz": freq[::fstep].tolist(),
        "fft_abs": amp[::fstep].tolist(),
        "info": info,
    }


def parse_metadata(data):
    try:
        meta = yaml.safe_load(data.decode(errors="replace"))
    except yaml.YAMLError as exc:
        raise RecordError(f"not valid YAML: {exc}")
    if not isinstance(meta, dict):
        raise RecordError("the metadata file must contain key: value pairs")
    return meta


def create(meta, uploads, added_by):
    """meta: same structure as metadata.yaml; uploads[i] belongs to meta['waveforms'][i]."""
    if not isinstance(meta, dict) or not isinstance(meta.get("waveforms"), list):
        raise RecordError("metadata is incomplete")
    if len(meta["waveforms"]) != len(uploads):
        raise RecordError("every waveform needs a file")
    meta = {k: v for k, v in meta.items() if v not in (None, "", {}, [])}
    meta["added_by"] = added_by

    auto_slug = not meta.get("slug")
    slug = _safe(str(meta.get("slug") or f"{meta.get('experiment_date', '')}_{meta.get('sample_name', '')}"))[:120]
    with db.connect("web") as conn:
        taken = {r["slug"] for r in conn.execute("SELECT slug FROM raw.measurement").fetchall()}
    base, n = slug, 1
    while slug in taken or (UPLOAD_DIR / slug).exists():
        if not auto_slug:
            raise RecordError(f"a record with identifier '{slug}' already exists", status=409)
        n += 1
        slug = f"{base}_{n}"
    meta["slug"] = slug

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".incoming-", dir=UPLOAD_DIR))
    try:
        used = set()
        for k, (w, upload) in enumerate(zip(meta["waveforms"], uploads)):
            if not isinstance(w, dict):
                raise RecordError("metadata is incomplete")
            name = _safe(Path(upload.filename or "waveform.txt").name)
            if name in used or name == "metadata.yaml":
                name = f"{k + 1}_{name}"
            used.add(name)
            (tmp / name).write_bytes(read_upload(upload))
            w["file"] = name
            for key in ("upload", "id"):  # only meaningful to the edit request
                w.pop(key, None)
            if not w.get("treatment"):
                w.pop("treatment", None)
        (tmp / "metadata.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
        try:
            importer.load_folder(tmp)  # validate before anything is kept
        except (importer.ImportError_, ValueError) as exc:
            raise RecordError(str(exc))
        folder = UPLOAD_DIR / slug
        tmp.rename(folder)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    try:
        with db.connect("importer") as conn:
            mid, _ = importer.import_folder(conn, folder)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    with db.connect("analysis") as conn:
        analysis.analyse(conn, [mid])
    return {"id": mid, "slug": slug}


# ---------------------------------------------------------------- editing

def snapshot(conn, mid):
    """The complete current state of a record, as plain JSON-able data."""
    row = conn.execute("SELECT * FROM raw.measurement WHERE id = %s", [mid]).fetchone()
    if not row:
        raise RecordError("no such record", status=404)
    row.pop("search_text")
    waveforms = conn.execute(
        "SELECT id, role, label, source_file, info, treatment, time_ps, amplitude FROM raw.waveform"
        " WHERE measurement_id = %s ORDER BY id",
        [mid],
    ).fetchall()
    return json.loads(json.dumps({"measurement": row, "waveforms": waveforms}, default=str))


def _describe(w):
    out = {k: w[k] for k in ("role", "label", "source_file", "info")}
    out["treatment"] = w.get("treatment") or {}
    out["n_points"] = len(w["time_ps"])
    return out


def get(mid):
    """Current record for the edit form, with waveform previews and the edit history."""
    with db.connect("web") as conn:
        current = snapshot(conn, mid)
        history = conn.execute(
            "SELECT version, edited_at, edited_by FROM raw.measurement_version"
            " WHERE measurement_id = %s ORDER BY version",
            [mid],
        ).fetchall()
    current["waveforms"] = [
        {"id": w["id"], **_describe(w), "preview": preview_arrays(w["time_ps"], w["amplitude"], w["info"])}
        for w in current["waveforms"]
    ]
    current["history"] = history
    return current


def get_version(mid, version):
    with db.connect("web") as conn:
        row = conn.execute(
            "SELECT version, edited_at, edited_by, snapshot FROM raw.measurement_version"
            " WHERE measurement_id = %s AND version = %s",
            [mid, version],
        ).fetchone()
    if not row:
        raise RecordError("no such version", status=404)
    row["snapshot"]["waveforms"] = [_describe(w) for w in row["snapshot"]["waveforms"]]
    return row


def update(mid, meta, uploads, edited_by):
    """Replace a record, after storing its previous state in raw.measurement_version.

    meta['waveforms'] lists the waveforms the record should have afterwards:
    {'id': n} keeps stored data (role and label may change), {'upload': k}
    takes uploads[k]. Stored waveforms that are not listed are removed.
    """
    if not isinstance(meta, dict) or not isinstance(meta.get("waveforms"), list):
        raise RecordError("metadata is incomplete")
    meta = {k: v for k, v in meta.items() if v not in (None, "", {}, [])}

    with db.connect("importer") as conn:
        before = snapshot(conn, mid)
        slug = meta["slug"] = before["measurement"]["slug"]
        meta["added_by"] = before["measurement"]["added_by"]
        version = conn.execute(
            "SELECT coalesce(max(version), 0) + 1 AS v FROM raw.measurement_version WHERE measurement_id = %s", [mid]
        ).fetchone()["v"]
        stored = {w["id"]: w for w in before["waveforms"]}
        names = {w["source_file"] for w in before["waveforms"]}
        rows, new_files, entries = [], [], []
        try:
            m = importer.validate_metadata(meta)
            for w in meta.get("waveforms", []):
                role, label = importer.waveform_key(w)
                if w.get("upload") is not None:
                    if not isinstance(w["upload"], int) or not 0 <= w["upload"] < len(uploads):
                        raise RecordError("a waveform file is missing")
                    upload = uploads[w["upload"]]
                    name = _safe(Path(upload.filename or "waveform.txt").name)
                    if name in names or name.startswith("metadata."):
                        name = f"edit{version}_{name}"
                    names.add(name)
                    data = read_upload(upload)
                    options = importer.waveform_options(w)
                    t, e, info = importer.parse_waveform(data.decode(errors="replace"), name=name, **options)
                    rows.append({"role": role, "label": label, "time_ps": t.tolist(), "amplitude": e.tolist(),
                                 "source_file": name, "info": info,
                                 "treatment": importer.waveform_treatment(w, t, e, name)})
                    new_files.append((name, data))
                    entries.append({"role": role, "label": label, "file": name, **options})
                elif w.get("id") in stored:
                    old = stored[w["id"]]
                    rows.append({**old, "role": role, "label": label, "treatment": importer.waveform_treatment(
                        w, old["time_ps"], old["amplitude"], old["source_file"])})
                    entries.append({"role": role, "label": label, "file": old["source_file"]})
                else:
                    raise RecordError("a waveform has neither stored data nor a file")
                if rows[-1]["treatment"]:
                    entries[-1]["treatment"] = rows[-1]["treatment"]
            importer.check_waveform_set([(r["role"], r["label"]) for r in rows])
        except (importer.ImportError_, ValueError) as exc:
            raise RecordError(str(exc))

        for w in before["waveforms"]:
            w.pop("id")
        conn.execute(
            "INSERT INTO raw.measurement_version (measurement_id, version, edited_by, snapshot) VALUES (%s, %s, %s, %s)",
            [mid, version, edited_by, json.dumps(before)],
        )
        importer.update_measurement(conn, mid, m)
        conn.execute("DELETE FROM raw.waveform WHERE measurement_id = %s", [mid])
        importer.insert_waveforms(conn, mid, rows)

    with db.connect("analysis") as conn:
        analysis.analyse(conn, [mid])
    _update_folder(UPLOAD_DIR / slug, {**meta, "waveforms": entries}, new_files, version)
    return {"id": mid, "slug": slug, "version": version}


def _update_folder(folder, meta, new_files, version):
    """Keep the record's folder of original files in step with the database.

    Only records created on the website have one here. The previous
    metadata.yaml is kept next to the new one; files are never removed.
    """
    if not folder.is_dir():
        return
    current = folder / "metadata.yaml"
    try:
        options = {w.get("file"): w for w in yaml.safe_load(current.read_text()).get("waveforms", [])}
        for w in meta["waveforms"]:  # carry over how kept files are to be read
            for key in ("time_unit", "time_column", "amplitude_column"):
                if key not in w and key in options.get(w["file"], {}):
                    w[key] = options[w["file"]][key]
        current.rename(folder / f"metadata.before-edit-{version}.yaml")
        for name, data in new_files:
            (folder / name).write_bytes(data)
        current.write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
    except (OSError, yaml.YAMLError, AttributeError):
        pass  # the database is already updated and holds everything


# ---------------------------------------------------------------- waveform treatment editor

def _spectrum(t, e):
    freq = np.fft.rfftfreq(len(e), (t[-1] - t[0]) / (len(t) - 1))[1:]
    return {"freq_thz": freq.tolist(), "abs": np.abs(np.fft.rfft(e))[1:].tolist()}


def treat_preview(t, e, treatment):
    """Before/after data for the editor, computed by the same code the analysis uses."""
    t, e = np.asarray(t, dtype=float), np.asarray(e, dtype=float)
    if t.shape != e.shape or t.ndim != 1 or not treat.MIN_POINTS <= len(t) <= 10 * PREVIEW_POINTS:
        raise RecordError("bad waveform data")
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(e)) and np.all(np.diff(t) > 0)):
        raise RecordError("bad waveform data")
    try:
        treatment = treat.normalise(treatment)
        t_after, e_after = treat.apply(t, e, treatment)
    except ValueError as exc:
        raise RecordError(str(exc))
    window = None
    if "apodization" in treatment:
        a = treatment["apodization"]
        window = treat.apodize(t, a["width_ps"], a["centre_ps"]).tolist()
    return {
        "suggested": treat.suggest(t, e),
        "treatment": treatment,
        "t_after": t_after.tolist(),
        "e_after": e_after.tolist(),
        "window": window,
        "fft_before": _spectrum(t, e),
        "fft_after": _spectrum(t_after, e_after),
    }
