"""Import measurement folders (metadata.yaml + waveform files) into raw.*"""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import yaml

from . import treatment as treat

TIME_UNITS_PS = {"fs": 1e-3, "ps": 1.0, "ns": 1e3, "s": 1e12}
ROLES = ("reference", "sample", "reference_echo", "sample_echo")

# Files written by the lab's LabVIEW program are recognised by this column
# header within the first LAB_HEADER_LINES lines.
LAB_HEADER = ("timeUTC (s)", "delay (ps)", "x (V)")
LAB_HEADER_LINES = 20
LABVIEW_EPOCH = dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)
REQUIRED = ["sample_name", "experiment_date", "responsible_person", "added_by", "sample_type", "reference_type"]


class ImportError_(Exception):
    pass


def read_waveform(path, **kw):
    return parse_waveform(Path(path).read_text(errors="replace"), name=Path(path).name, **kw)


def _labview_time(seconds):
    try:
        stamp = LABVIEW_EPOCH + dt.timedelta(seconds=float(seconds))
    except OverflowError:
        return None
    return stamp.isoformat(timespec="seconds") if 1990 < stamp.year < 2100 else None


def parse_lab_file(lines, header, name):
    """LabVIEW lock-in scan: notes, the header line, then the scan repeated
    several times and (normally) their average as the last block.

    Columns: LabVIEW timestamp (s since 1904 UTC), delay (ps), x (V), y (V), ...,
    and the two Keithley multimeters in the last two columns. Returns the
    averaged x(delay) and what the file says about the measurement.
    """
    rows = []
    for line in lines[header + 1:]:
        try:
            rows.append([float(tok) for tok in line.split("\t") if tok.strip()])
        except ValueError:
            continue
    rows = [r for r in rows if rows and len(r) == len(rows[0])]
    if len(rows) < 8 or len(rows[0]) < 3:
        raise ImportError_(f"{name}: lab file has no usable data rows")
    data = np.array(rows)

    # a new scan starts where the delay jumps back
    step = np.diff(data[:, 1])
    direction = np.sign(step[0])
    starts = [0] + [i + 1 for i in np.flatnonzero(np.sign(step) == -direction)] + [len(data)]
    blocks = [data[a:b] for a, b in zip(starts, starts[1:])]
    first = blocks[0]
    complete = [b for b in blocks if len(b) == len(first) and np.allclose(b[:, 1], first[:, 1], atol=1e-6)]
    if len(first) < 8:
        raise ImportError_(f"{name}: scans have only {len(first)} points")

    average, scans, source = complete[-1], complete[:-1], "last block of the file"
    tolerance = 1e-6 * np.abs(data[:, 2]).max() + 1e-8
    has_average = (
        len(complete) >= 2
        and blocks[-1] is complete[-1]
        and np.allclose(average[:, 2], np.mean([s[:, 2] for s in scans], axis=0), rtol=0, atol=tolerance)
    )
    if not has_average:
        scans = complete
        average = np.mean(scans, axis=0)
        source = "single scan" if len(scans) == 1 else "computed here (file has no average block)"

    t, e = average[:, 1], average[:, 2]
    if direction < 0:
        t, e = t[::-1], e[::-1]
    stamps = np.concatenate([s[:, 0] for s in scans])
    info = {
        "format": "lab",
        "notes": [l.strip() for l in lines[:header] if l.strip()],
        "measured_start_utc": _labview_time(stamps.min()),
        "measured_end_utc": _labview_time(stamps.max()),
        "duration_s": round(float(stamps.max() - stamps.min()), 1),
        "n_averages": len(scans),
        "average_source": source,
        "n_points": len(t),
        "delay_span_ps": round(float(t[-1] - t[0]), 6),
        "step_ps": round(float((t[-1] - t[0]) / (len(t) - 1)), 6),
    }
    if data.shape[1] >= 6:
        info["kmm1_v"] = round(float(average[:, -2].mean()), 6)
        info["kmm2_v"] = round(float(average[:, -1].mean()), 6)
    return t, e, info


def parse_waveform(text, name="file", time_column=0, amplitude_column=1, time_unit="ps"):
    """Returns (time in ps, amplitude, info).

    Lab files (see LAB_HEADER) are read specifically and the column options
    are ignored. Anything else is read as text with a time and an amplitude
    column: tab / semicolon / whitespace / comma separated, decimal commas
    accepted, lines that do not parse as numbers (headers, comments) skipped.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines[:LAB_HEADER_LINES]):
        if tuple(tok.strip() for tok in line.split("\t")[:3]) == LAB_HEADER:
            return parse_lab_file(lines, i, name)
    if time_unit not in TIME_UNITS_PS:
        raise ImportError_(f"unknown time_unit '{time_unit}' (use one of {', '.join(TIME_UNITS_PS)})")
    t, e = [], []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if ";" in line or "\t" in line:
            tokens = line.replace(";", "\t").replace(",", ".").split("\t")
        elif len(line.split()) > 1:
            tokens = line.replace(",", ".").split()
        else:
            tokens = line.split(",")
        try:
            a, b = float(tokens[time_column]), float(tokens[amplitude_column])
        except (ValueError, IndexError):
            continue
        t.append(a)
        e.append(b)
    if len(t) < 8:
        raise ImportError_(f"{name}: found only {len(t)} numeric rows")
    t = np.array(t) * TIME_UNITS_PS[time_unit]
    e = np.array(e)
    if t[0] > t[-1]:
        t, e = t[::-1], e[::-1]
    if np.any(np.diff(t) <= 0):
        raise ImportError_(f"{name}: time axis is not monotonic")
    return t, e, {}


def _num(meta, key):
    v = meta.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ImportError_(f"{key} must be a number, got {v!r}")


def format_thickness(nm):
    return f"{nm:g} nm" if nm < 1000 else f"{nm / 1000:g} um"


def _search_text(m):
    parts = [
        m["slug"], m["sample_name"], str(m["experiment_date"]), m["responsible_person"], m["added_by"],
        m["description"], m["sample_type"].replace("_", " "), m["reference_type"],
        m["material"], m["substrate"], m["treatment"],
    ]
    if m["thickness_nm"] is not None:
        parts.append(format_thickness(m["thickness_nm"]))
    if m["temperature_k"] is not None:
        parts.append(f"{m['temperature_k']:g} K")
    parts += [f"{k} {v}" for k, v in {**m["source"], **m["extra"]}.items()]
    return " ".join(str(p) for p in parts if p)


def validate_metadata(meta, default_slug=None):
    """Metadata in the metadata.yaml structure -> column values of raw.measurement."""
    missing = [k for k in REQUIRED if meta.get(k) in (None, "")]
    if missing:
        raise ImportError_(f"metadata is missing: {', '.join(missing)}")

    date = meta["experiment_date"]
    if not isinstance(date, dt.date):
        try:
            date = dt.date.fromisoformat(str(date))
        except ValueError:
            raise ImportError_(f"experiment_date must be YYYY-MM-DD, got {date!r}")
    if meta["sample_type"] not in ("thin_film", "bulk"):
        raise ImportError_("sample_type must be 'thin_film' or 'bulk'")
    if meta["reference_type"] not in ("substrate", "air"):
        raise ImportError_("reference_type must be 'substrate' or 'air'")

    thickness = _num(meta, "thickness_nm")
    if thickness is None and _num(meta, "thickness_um") is not None:  # older metadata files
        thickness = _num(meta, "thickness_um") * 1000

    m = {
        "slug": str(meta.get("slug") or default_slug),
        "sample_name": str(meta["sample_name"]),
        "experiment_date": date,
        "responsible_person": str(meta["responsible_person"]),
        "added_by": str(meta["added_by"]),
        "description": str(meta.get("description") or "").strip(),
        "sample_type": meta["sample_type"],
        "reference_type": meta["reference_type"],
        "material": meta.get("material"),
        "substrate": meta.get("substrate"),
        "thickness_nm": thickness,
        "substrate_thickness_um": _num(meta, "substrate_thickness_um"),
        "treatment": meta.get("treatment"),
        "temperature_k": _num(meta, "temperature_K"),
        "source": meta.get("source") or {},
        "extra": meta.get("extra") or {},
    }
    if not isinstance(m["source"], dict) or not isinstance(m["extra"], dict):
        raise ImportError_("source and extra must be key: value pairs")
    m["search_text"] = _search_text(m)
    return m


def waveform_key(w):
    if not isinstance(w, dict):
        raise ImportError_("each waveform must have role and file")
    role, label = w.get("role"), str(w.get("label") or "main")
    if role not in ROLES:
        raise ImportError_(f"waveform role must be one of {', '.join(ROLES)}; got {role!r}")
    return role, label


def waveform_treatment(w, t, e, name):
    """Validated treatment of a waveform entry; also checks it can be applied."""
    try:
        treatment = treat.normalise(w.get("treatment"))
        treat.apply(t, e, treatment)
    except ValueError as exc:
        raise ImportError_(f"{name}: treatment: {exc}")
    return treatment


def check_waveform_set(keys):
    for key in keys:
        if keys.count(key) > 1:
            raise ImportError_(f"duplicate waveform {key[0]}/{key[1]}")
    for needed in (("reference", "main"), ("sample", "main")):
        if needed not in keys:
            raise ImportError_(f"waveforms must contain a '{needed[0]}' with label 'main'")


def waveform_options(w):
    return {
        "time_column": int(w.get("time_column") or 0),
        "amplitude_column": int(w.get("amplitude_column") if w.get("amplitude_column") is not None else 1),
        "time_unit": str(w.get("time_unit") or "ps"),
    }


def load_folder(folder):
    folder = Path(folder)
    try:
        meta = yaml.safe_load((folder / "metadata.yaml").read_text())
    except yaml.YAMLError as exc:
        raise ImportError_(f"metadata.yaml is not valid YAML: {exc}")
    if not isinstance(meta, dict):
        raise ImportError_("metadata.yaml must contain key: value pairs")
    m = validate_metadata(meta, folder.name)

    waveforms = []
    for w in meta.get("waveforms") or []:
        role, label = waveform_key(w)
        if not w.get("file"):
            raise ImportError_(f"waveform {role}/{label} has no file")
        path = folder / w["file"]
        if not path.is_file():
            raise ImportError_(f"waveform file not found: {w['file']}")
        t, e, info = read_waveform(path, **waveform_options(w))
        waveforms.append(
            {"role": role, "label": label, "time_ps": t, "amplitude": e, "source_file": w["file"], "info": info,
             "treatment": waveform_treatment(w, t, e, w["file"])}
        )
    check_waveform_set([(w["role"], w["label"]) for w in waveforms])
    return m, waveforms


def insert_waveforms(conn, mid, waveforms):
    for w in waveforms:
        conn.execute(
            "INSERT INTO raw.waveform (measurement_id, role, label, time_ps, amplitude, source_file, info, treatment)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [mid, w["role"], w["label"], list(w["time_ps"]), list(w["amplitude"]), w["source_file"],
             json.dumps(w["info"]), json.dumps(w.get("treatment") or {})],
        )


def update_measurement(conn, mid, m):
    m = {**m, "source": json.dumps(m["source"], default=str), "extra": json.dumps(m["extra"], default=str)}
    conn.execute(
        f"UPDATE raw.measurement SET {', '.join(f'{c} = %s' for c in m)} WHERE id = %s",
        list(m.values()) + [mid],
    )


def import_folder(conn, folder, update=False):
    """Returns (measurement id, 'added' | 'updated' | 'skipped' | 'edited').

    'edited': the record was changed on the website, so the folder no longer
    describes it and is not allowed to overwrite it.
    """
    m, waveforms = load_folder(folder)
    existing = conn.execute("SELECT id FROM raw.measurement WHERE slug = %s", [m["slug"]]).fetchone()
    if existing and not update:
        return existing["id"], "skipped"
    if existing and conn.execute(
        "SELECT 1 FROM raw.measurement_version WHERE measurement_id = %s LIMIT 1", [existing["id"]]
    ).fetchone():
        return existing["id"], "edited"

    if existing:
        mid = existing["id"]
        update_measurement(conn, mid, m)
        conn.execute("DELETE FROM raw.waveform WHERE measurement_id = %s", [mid])
    else:
        m["source"], m["extra"] = json.dumps(m["source"], default=str), json.dumps(m["extra"], default=str)
        cols = list(m)
        mid = conn.execute(
            f"INSERT INTO raw.measurement ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
            [m[c] for c in cols],
        ).fetchone()["id"]
    insert_waveforms(conn, mid, waveforms)
    conn.commit()
    return mid, "updated" if existing else "added"


def find_folders(path):
    path = Path(path)
    if (path / "metadata.yaml").is_file():
        return [path]
    return sorted(p.parent for p in path.rglob("metadata.yaml"))
