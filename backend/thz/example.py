"""Synthetic example measurements: templates for metadata.yaml and test data.

These are simulated, not measured.
"""
from pathlib import Path

import numpy as np

C = 299.792458  # um / ps
T = np.arange(0, 60, 0.05)  # ps


def _pulse(rng):
    x = (T - 5.0) / 0.25
    return -x * np.exp(-x**2 / 2) + 2e-4 * rng.standard_normal(T.size)


def _apply(e, H):
    """H(f) in the exp(-i omega t) convention, f in THz."""
    f = np.fft.rfftfreq(T.size, T[1] - T[0])
    return np.fft.irfft(np.fft.rfft(e) * np.conj(H(f)), T.size)


def _slab(n, d_um, echoes=True):
    def H(f):
        phi = 2 * np.pi * f * d_um / C
        r2 = ((n - 1) / (n + 1)) ** 2
        fp = 1 / (1 - r2 * np.exp(2j * n * phi)) if echoes else 1
        return 4 * n / (n + 1) ** 2 * np.exp(1j * (n - 1) * phi) * fp
    return H


def _save(path, t, e):
    np.savetxt(path, np.column_stack([t, e]), fmt="%.4f\t%.6e", header="time (ps)\tE field (a.u.)")


def write_examples(root):
    root = Path(root)
    rng = np.random.default_rng(1)
    written = []

    # bulk sample against air, echoes inside one long scan
    folder = root / "2026-09-01_example_bulk_Si"
    folder.mkdir(parents=True, exist_ok=True)
    ref = _pulse(rng)
    _save(folder / "reference.txt", T, ref)
    _save(folder / "sample.txt", T, _apply(ref, _slab(3.42 + 0.002j, 500)) + 2e-4 * rng.standard_normal(T.size))
    (folder / "metadata.yaml").write_text("""\
# slug: unique identifier; defaults to the folder name
sample_name: SYNTHETIC example - bulk Si wafer
experiment_date: 2026-09-01
responsible_person: Example Person
added_by: Example Person
description: >
  Simulated data. Bulk high-resistivity silicon, reference is an air scan.
  One long scan that contains the internal echoes.
sample_type: bulk            # bulk | thin_film
reference_type: air          # air | substrate
material: Si
thickness_nm: 500000          # sample thickness in nm
treatment: none
temperature_K: 300
source:                      # experiment parameters, all optional, free text
  laser: Pharos Standard
  rep_rate: 10kHz
  attenuation: 100%
  thz_source: 2mm GaP
  pump_power: 500mW
  focusing: Collimated
  thz_detection: 2mm GaP
  probe_power: 700uW
waveforms:
  - {role: reference, file: reference.txt}
  - {role: sample, file: sample.txt}
# role: reference | sample | reference_echo | sample_echo
# optional per waveform: label (default main), time_unit (fs|ps|ns|s),
# time_column (default 0), amplitude_column (default 1)
# files from the lab LabVIEW program are recognised automatically
""")
    written.append(folder)

    # thin film on a substrate at three temperatures, echoes scanned separately
    sub = _slab(3.07, 500)
    main, echo = T < 14, (T >= 14) & (T < 26)
    for temp, sigma_d in ((10, 0.030), (100, 0.015), (300, 0.006)):
        folder = root / f"2026-09-12_example_film_{temp}K"
        folder.mkdir(parents=True, exist_ok=True)
        ref = _apply(_pulse(rng), sub)
        # Tinkham formula with a Drude sheet conductance sigma_d (in S), tau = 0.1 ps
        film = lambda f: (1 + 3.07) / (1 + 3.07 + 376.73 * sigma_d / (1 - 2j * np.pi * f * 0.1))
        sam = _apply(ref, film) + 2e-4 * rng.standard_normal(T.size)
        _save(folder / "substrate.txt", T[main], ref[main])
        _save(folder / "film.txt", T[main], sam[main])
        _save(folder / "substrate_echo.txt", T[echo], ref[echo])
        _save(folder / "film_echo.txt", T[echo], sam[echo])
        (folder / "metadata.yaml").write_text(f"""\
sample_name: SYNTHETIC example - conducting film on sapphire
experiment_date: 2026-09-12
responsible_person: Example Person
added_by: Example Person
description: Simulated data. Drude-like thin film, reference is the bare substrate. Echoes scanned separately.
sample_type: thin_film
reference_type: substrate
material: metal film
substrate: sapphire
thickness_nm: 50
substrate_thickness_um: 500
treatment: annealed 400 C
temperature_K: {temp}
source:
  thz_source: photoconductive antenna
waveforms:
  - {{role: reference, file: substrate.txt}}
  - {{role: sample, file: film.txt}}
  - {{role: reference_echo, file: substrate_echo.txt}}
  - {{role: sample_echo, file: film_echo.txt}}
""")
        written.append(folder)
    return written
