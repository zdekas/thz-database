"""Waveform treatment applied before the FFT: baseline subtraction, trimming
and apodization, in this order.

The raw waveform in the database is never changed. Only the parameters are
stored (raw.waveform.treatment); the analysis applies them and records what
it applied (analysed.transmission.treatment).

Stored form, every step optional:
    {"baseline":    {"from_ps": a, "to_ps": b},
     "trim":        {"from_ps": a, "to_ps": b},
     "apodization": {"centre_ps": c, "width_ps": w}}
"""
import numpy as np

STEPS = {
    "baseline": ("from_ps", "to_ps"),
    "trim": ("from_ps", "to_ps"),
    "apodization": ("centre_ps", "width_ps"),
}
DEFAULT_APODIZATION_WIDTH_PS = 5.0
MIN_POINTS = 8


def apodize(t, width=0, tmax=None):
    """
    Apodization window function for FFT (the lab's function, unchanged in behaviour).

    Parameters
    ----------
    t : array_like
        Time array on which the apodization window is to be evaluated.
    width : float, optional
        Width of the apodization window in units of the time array. Default is 0, which
        means no apodization is performed. The window spans tmax - width .. tmax + width.
    tmax : float, optional
        Time at which the apodization window should be centred. Should be specified if width > 0.

    Returns
    -------
    f : array_like
        The apodization window evaluated at the points in `t`.
    """
    C = np.array([[ 0.701551 ,-0.639244  ,0.937693  ,0.       ,0.        ,0.      ],
                [ 0.39643   ,-0.150902  ,0.754472  ,0.       ,0.        ,0.      ],
                [ 0.237413  ,-0.065285  ,0.827872  ,0.       ,0.        ,0.      ],
                [ 0.153945  ,-0.141765  ,0.98782   ,0.       ,0.        ,0.      ],
                [ 0.077112  ,0.         ,0.703371  ,0.219517 ,0.        ,0.      ],
                [ 0.039234  ,0.         ,0.630268  ,0.234934 ,0.095563  ,0.      ],
                [ 0.020078  ,0.         ,0.480667  ,0.386409 ,0.112845  ,0.      ],
                [ 0.010172  ,0.         ,0.344429  ,0.451817 ,0.19358   ,0.      ],
                [ 0.004773  ,0.         ,0.232473  ,0.464562 ,0.298191  ,0.      ],
                [ 0.002267  ,0.         ,0.140412  ,0.487172 ,0.2562    ,0.113948]])
    # FWHM = 2
    # C = C[np.floor((FWHM-1)*10),:]
    C = C[9,:]

    t = np.asarray(t, dtype=float)
    L = t[-1]-t[0]
    u = 2 * (t-t[0]) / ( L) - 1
    if tmax is not None:
        u0 = 2 * (tmax-t[0]) / ( L) - 1
        u = u - u0
    if width > 0:
        u = u / width/2*L
        u[np.abs(u) > 1] = 1
    x = 1-u**2
    f = 0*x
    for j in range(6):
        f = f + C[j] * x**(j)
    return f


def normalise(treatment):
    """Validate user input; returns the stored form ({} = untreated)."""
    if not treatment:
        return {}
    if not isinstance(treatment, dict) or set(treatment) - set(STEPS):
        raise ValueError(f"treatment may only contain: {', '.join(STEPS)}")
    out = {}
    for step, keys in STEPS.items():
        if not treatment.get(step):
            continue
        try:
            values = {k: float(treatment[step][k]) for k in keys}
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{step} needs numbers for {' and '.join(keys)}")
        if not all(np.isfinite(v) for v in values.values()):
            raise ValueError(f"{step} values must be finite")
        if "from_ps" in values and not values["from_ps"] < values["to_ps"]:
            raise ValueError(f"{step}: 'from' must be smaller than 'to'")
        if step == "apodization" and not values["width_ps"] > 0:
            raise ValueError("apodization width must be positive")
        out[step] = values
    return out


def apply(t, e, treatment):
    """Returns the treated (t, e). `treatment` must be in the stored form."""
    t, e = np.asarray(t, dtype=float), np.asarray(e, dtype=float)
    if "baseline" in treatment:
        b = treatment["baseline"]
        inside = (t >= b["from_ps"]) & (t <= b["to_ps"])
        if not inside.any():
            raise ValueError("baseline range contains no data points")
        e = e - e[inside].mean()
    if "trim" in treatment:
        b = treatment["trim"]
        keep = (t >= b["from_ps"]) & (t <= b["to_ps"])
        if keep.sum() < MIN_POINTS:
            raise ValueError(f"trimming leaves fewer than {MIN_POINTS} points")
        t, e = t[keep], e[keep]
    if "apodization" in treatment:
        a = treatment["apodization"]
        e = e * apodize(t, a["width_ps"], a["centre_ps"])
    return t, e


def find_peak(t, e):
    """Delay of the largest excursion from the median level."""
    e = np.asarray(e, dtype=float)
    return float(np.asarray(t)[np.argmax(np.abs(e - np.median(e)))])


def suggest(t, e):
    """Starting values for the editor: baseline before the pulse, no trimming,
    apodization centred on the detected peak."""
    t = np.asarray(t, dtype=float)
    peak = find_peak(t, e)
    before = peak - 2.0 if peak - 2.0 > t[min(4, len(t) - 1)] else t[min(4, len(t) - 1)]
    return {
        "baseline": {"from_ps": float(t[0]), "to_ps": float(before)},
        "trim": {"from_ps": float(t[0]), "to_ps": float(t[-1])},
        "apodization": {"centre_ps": peak, "width_ps": DEFAULT_APODIZATION_WIDTH_PS},
    }


def describe(treatment):
    """One line for export headers and lists."""
    parts = []
    if "baseline" in treatment:
        parts.append("baseline = mean of {from_ps:g} to {to_ps:g} ps subtracted".format(**treatment["baseline"]))
    if "trim" in treatment:
        parts.append("trimmed to {from_ps:g} to {to_ps:g} ps".format(**treatment["trim"]))
    if "apodization" in treatment:
        parts.append("apodized, centre {centre_ps:g} ps, width +-{width_ps:g} ps".format(**treatment["apodization"]))
    return "; ".join(parts) or "none"
