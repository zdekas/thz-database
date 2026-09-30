"""Axis conversions, series for the viewer, and text export."""
import datetime as dt

import numpy as np
from scipy.interpolate import PchipInterpolator

from .importer import format_thickness
from .treatment import describe
from .xexpr import parse_x, strip_assignment

C_UM_THZ = 299.792458        # c in um * THz
H_MEV_PER_THZ = 4.135667696  # h in meV / THz

X_AXES = {
    "thz": ("Frequency (THz)", lambda f: f),
    "cm-1": ("Wavenumber (cm^-1)", lambda f: f * 1e4 / C_UM_THZ),
    "um": ("Wavelength (um)", lambda f: C_UM_THZ / f),
    "mev": ("Energy (meV)", lambda f: f * H_MEV_PER_THZ),
}
Y_AXES = {
    "abs": "|T|",
    "delay": "Delay arg(T)/omega (ps)",
    "phase": "Phase arg(T) (rad)",
}


def _y(kind, f, row):
    if kind == "abs":
        return np.hypot(np.asarray(row["t_real"], dtype=float), np.asarray(row["t_imag"], dtype=float))
    phase = np.asarray(row["phase_rad"], dtype=float)
    return phase if kind == "phase" else phase / (2 * np.pi * f)


def label(row):
    text = row["sample_name"]
    if row["temperature_k"] is not None:
        text += f", {row['temperature_k']:g} K"
    return text


def build_series(conn, ids, x_axis, y_axis, full):
    """One (metadata row, x, y) per id, in the order asked, x ascending."""
    if x_axis not in X_AXES or y_axis not in Y_AXES:
        raise ValueError("unknown axis")
    rows = conn.execute(
        """
        SELECT m.id, m.slug, m.sample_name, m.experiment_date, m.thickness_nm, m.temperature_k,
               a.analysis_version, a.treatment, a.freq_thz, a.t_real, a.t_imag, a.phase_rad, a.band_min_thz, a.band_max_thz
        FROM analysed.transmission a JOIN raw.measurement m ON m.id = a.measurement_id
        WHERE m.id = ANY(%s)
        """,
        [ids],
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    out = []
    for i in ids:
        row = by_id.get(i)
        if row is None:
            continue
        f = np.asarray(row["freq_thz"], dtype=float)
        x, y = X_AXES[x_axis][1](f), _y(y_axis, f, row)
        if not full:
            keep = (f >= row["band_min_thz"]) & (f <= row["band_max_thz"])
            x, y = x[keep], y[keep]
        order = np.argsort(x)
        out.append((row, x[order], y[order]))
    return out


def export_text(series, x_axis, y_axis, full, interp_expr=None):
    lines = [
        "THz transmission database export",
        f"Downloaded: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"x-axis: {X_AXES[x_axis][0]}",
        f"y-axis: {Y_AXES[y_axis]}",
        "Range: " + ("full spectrum up to the Nyquist frequency" if full else "reliable band of each reference spectrum"),
    ]
    if interp_expr is None:
        lines.append("Interpolated: no (points as analysed)")
        n = max((len(x) for _, x, _ in series), default=0)
        cols, names = [], []
        for k, (_, x, y) in enumerate(series, 1):
            for arr, name in ((x, f"X{k}"), (y, f"Y{k}")):
                cols.append(np.concatenate([arr, np.full(n - len(arr), np.nan)]))
                names.append(name)
        col_note = "Columns X{k}, Y{k}:"
    else:
        xi = parse_x(interp_expr)
        expr = strip_assignment(interp_expr)
        lines.append(f"Interpolated: YES - PCHIP interpolation onto x = {expr}")
        lines.append("              NaN where x is outside the exported range of a dataset (no extrapolation)")
        cols, names = [xi], ["X"]
        for k, (_, x, y) in enumerate(series, 1):
            ok = np.isfinite(x) & np.isfinite(y)
            if ok.sum() >= 2:
                cols.append(PchipInterpolator(x[ok], y[ok], extrapolate=False)(xi))
            else:
                cols.append(np.full(xi.shape, np.nan))
            names.append(f"Y{k}")
        if len(cols) > 1 and not np.any(np.isfinite(np.column_stack(cols[1:]))):
            raise ValueError(
                f"none of the requested x values lie inside the data; x is interpreted in the "
                f"selected axis unit: {X_AXES[x_axis][0]}"
            )
        col_note = "Column X is common, columns Y{k}:"
    lines.append(col_note)
    for k, (row, _, _) in enumerate(series, 1):
        bits = [row["slug"], label(row), f"measured {row['experiment_date']}"]
        if row["thickness_nm"] is not None:
            bits.append(f"thickness {format_thickness(row['thickness_nm'])}")
        bits.append(f"analysis v{row['analysis_version']}")
        lines.append(f"  {k}: " + " | ".join(bits))
        for role, applied in row["treatment"].items():
            lines.append(f"     {role} waveform treated before FFT: {describe(applied)}")
    lines.append("Sign convention: exp(-i omega t); a delayed pulse has arg(T) > 0")
    lines.append("\t".join(names))

    body = []
    for vals in zip(*cols):
        body.append("\t".join("nan" if not np.isfinite(v) else f"{v:.8g}" for v in vals))
    return "\n".join("# " + l for l in lines) + "\n" + "\n".join(body) + "\n"
