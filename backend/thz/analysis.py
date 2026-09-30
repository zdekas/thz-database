"""Raw waveforms -> analysed quantities.

Bump ANALYSIS_VERSION whenever the numbers produced here change, then run
`thz analyse` to rebuild the analysed layer.
"""
import json

import numpy as np

from . import treatment as treat

ANALYSIS_VERSION = "1.1.0"

# The reliable band is the contiguous region around the spectral peak of the
# reference where its amplitude stays above this fraction of the peak.
BAND_THRESHOLD = 0.02
# Part of the band used to fix the 2*pi ambiguity of the unwrapped phase.
PHASE_FIT_THRESHOLD = 0.2


def _uniform(t):
    d = np.diff(t)
    return len(t) > 2 and np.allclose(d, d[0], rtol=1e-3, atol=0)


def common_grid(t_ref, e_ref, t_sam, e_sam):
    """Put both waveforms on one uniform time axis (zero outside their scan)."""
    if len(t_ref) == len(t_sam) and _uniform(t_ref) and np.allclose(t_ref, t_sam, rtol=0, atol=1e-6):
        return t_ref[1] - t_ref[0], e_ref, e_sam
    dt = min(np.median(np.diff(t_ref)), np.median(np.diff(t_sam)))
    t0 = min(t_ref[0], t_sam[0])
    t1 = max(t_ref[-1], t_sam[-1])
    t = t0 + dt * np.arange(int(round((t1 - t0) / dt)) + 1)
    return (
        dt,
        np.interp(t, t_ref, e_ref, left=0.0, right=0.0),
        np.interp(t, t_sam, e_sam, left=0.0, right=0.0),
    )


def reliable_band(amp):
    peak = int(np.argmax(amp))
    ok = amp > BAND_THRESHOLD * amp[peak]
    lo = hi = peak
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    while hi < len(amp) - 1 and ok[hi + 1]:
        hi += 1
    return lo, hi


def transmission(t_ref, e_ref, t_sam, e_sam):
    """Complex transmission T = E_sample(f) / E_reference(f).

    Convention: E(f) = integral E(t) exp(+i 2 pi f t) dt, i.e. exp(-i omega t)
    time dependence, so a sample that delays the pulse has arg(T) > 0 and
    arg(T)/omega is that delay. (This is the complex conjugate of numpy's FFT.)
    Time in ps, frequency in THz. The f = 0 point is dropped.
    """
    t_ref, e_ref, t_sam, e_sam = (np.asarray(a, dtype=float) for a in (t_ref, e_ref, t_sam, e_sam))
    dt, e_ref, e_sam = common_grid(t_ref, e_ref, t_sam, e_sam)

    freq = np.fft.rfftfreq(len(e_ref), dt)[1:]
    s_ref = np.conj(np.fft.rfft(e_ref))[1:]
    s_sam = np.conj(np.fft.rfft(e_sam))[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        T = s_sam / s_ref
    T[~np.isfinite(T)] = np.nan

    amp_ref = np.abs(s_ref)
    lo, hi = reliable_band(amp_ref)

    phase = np.unwrap(np.nan_to_num(np.angle(T)))
    # Unwrapping starts in the noisy low-frequency region, which leaves an
    # arbitrary multiple of 2*pi. Remove it by requiring the linear
    # extrapolation of the phase from the strong part of the spectrum to pass
    # near zero at f = 0.
    fit = np.zeros(len(freq), dtype=bool)
    fit[lo : hi + 1] = amp_ref[lo : hi + 1] > PHASE_FIT_THRESHOLD * amp_ref.max()
    if fit.sum() >= 2:
        intercept = np.polyfit(freq[fit], phase[fit], 1)[1]
        phase -= 2 * np.pi * np.round(intercept / (2 * np.pi))
    phase[np.isnan(T)] = np.nan

    return {
        "freq_thz": freq,
        "t_real": T.real,
        "t_imag": T.imag,
        "phase_rad": phase,
        "band_min_thz": float(freq[lo]),
        "band_max_thz": float(freq[hi]),
    }


def analyse(conn, measurement_ids=None):
    """(Re)build analysed.transmission from raw. None = everything."""
    where, args = "", []
    if measurement_ids is not None:
        where, args = "WHERE m.id = ANY(%s)", [list(measurement_ids)]
    rows = conn.execute(
        f"""
        SELECT m.id, m.slug,
               r.time_ps AS t_ref, r.amplitude AS e_ref, r.treatment AS treat_ref,
               s.time_ps AS t_sam, s.amplitude AS e_sam, s.treatment AS treat_sam
        FROM raw.measurement m
        JOIN raw.waveform r ON r.measurement_id = m.id AND r.role = 'reference' AND r.label = 'main'
        JOIN raw.waveform s ON s.measurement_id = m.id AND s.role = 'sample' AND s.label = 'main'
        {where}
        ORDER BY m.id
        """,
        args,
    ).fetchall()

    if measurement_ids is None:
        conn.execute("TRUNCATE analysed.transmission")
    else:
        conn.execute("DELETE FROM analysed.transmission WHERE measurement_id = ANY(%s)", [list(measurement_ids)])

    for row in rows:
        t_ref, e_ref = treat.apply(row["t_ref"], row["e_ref"], row["treat_ref"])
        t_sam, e_sam = treat.apply(row["t_sam"], row["e_sam"], row["treat_sam"])
        res = transmission(t_ref, e_ref, t_sam, e_sam)
        applied = {k: v for k, v in (("reference", row["treat_ref"]), ("sample", row["treat_sam"])) if v}
        conn.execute(
            """
            INSERT INTO analysed.transmission
                (measurement_id, analysis_version, freq_thz, t_real, t_imag, phase_rad, band_min_thz, band_max_thz,
                 treatment)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                row["id"],
                ANALYSIS_VERSION,
                res["freq_thz"].tolist(),
                res["t_real"].tolist(),
                res["t_imag"].tolist(),
                res["phase_rad"].tolist(),
                res["band_min_thz"],
                res["band_max_thz"],
                json.dumps(applied),
            ],
        )
    conn.commit()
    return [row["slug"] for row in rows]
