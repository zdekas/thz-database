# THz transmission database

Three layers, all started by one `docker compose`:

1. **Raw** – PostgreSQL schema `raw`: measurement metadata and the time-domain waveforms. Written only by the importer.
2. **Analysed** – schema `analysed`: complex transmission computed from raw. Can be rebuilt at any time.
3. **Website** – search, multi-select, graph viewer and text export, reading the analysed layer.

## Run

```bash
docker compose up -d --build
```

The site is at http://localhost:8050 (change with `WEB_PORT` in `.env`, see `.env.example`).

## Add data

Put one folder per measurement under `data/incoming/`, containing the waveform text files and a `metadata.yaml`.
`data/examples/` holds synthetic examples to copy a `metadata.yaml` from; they are not in the database (regenerate with `docker compose run --rm tools make-examples /data/examples`).

```bash
docker compose run --rm tools import /data/incoming
```

- Folders already in the database are skipped; add `--update` to replace them.
- New measurements are analysed right after import.
- Waveform files: two numeric columns (time, field), separated by tab, semicolon, spaces or comma; header lines are skipped; decimal commas are accepted. `time_unit`, `time_column`, `amplitude_column` can be set per waveform.
- Each measurement needs a `reference` and a `sample` waveform with label `main`. Further waveforms with other labels (e.g. `echo1`) are stored for later analysis of separately scanned echoes.

Other commands: `docker compose run --rm tools list`, `docker compose run --rm tools delete <slug>`.

## Add data through the website

Log in at http://localhost:8050/login (link "Log in" in the viewer), then use **Add record**:

- fill in the form, or load a `metadata.yaml` to pre-fill it;
- choose the waveform files – each one is parsed by the server and plotted next to the file, with the same reader the import uses;
- on save, the files and a generated `metadata.yaml` are stored in `data/uploads/<identifier>/`, imported and analysed. "Added by" is the logged-in account.

### Editing a record

Select exactly one record in the viewer and click **Edit record** (next to "+ Add record"). Metadata can be changed; waveforms can be re-labelled, replaced by a new file, removed or added. The identifier cannot be changed.

- Before every edit the complete previous state (metadata and waveform data) is stored in `raw.measurement_version`; version 1 is the original. Nothing is overwritten without a copy.
- The edit page shows a note "edited on … by …" and an edit history where each previous version can be compared with the current one. The public viewer does not show any of this.
- For records created on the website, the folder in `data/uploads/` is updated too: the old `metadata.yaml` is kept as `metadata.before-edit-N.yaml`, files are never removed.
- `tools import --update` does not overwrite a record that was edited on the website.

Accounts are created on the command line only (there is no public sign-up):

```bash
docker compose run --rm tools create-user someone@example.org --name "Full Name"
```

This prints a random password; running it again for an existing e-mail resets the password. The password can be changed on the Add record page. Also: `list-users`, `delete-user <email>`.

Before the site is public: serve it over HTTPS and set `COOKIE_SECURE=1` in `.env`.

## Lab (LabVIEW) files

A file is treated as a lab file when one of its first 20 lines starts with the columns `timeUTC (s)`, `delay (ps)`, `x (V)` (tab-separated). This works in the website and in `tools import`; column and unit options are ignored for such files.

- The scan is repeated several times; the **last block is the average** of the others and is what gets imported (`x (V)` against `delay (ps)`). If a file has no average block (single scan, aborted run), the complete scans are averaged here instead.
- Stored with the waveform (`raw.waveform.info`): the note lines above the header, start/end time and duration (timestamps are LabVIEW seconds since 1904-01-01 UTC), number of averaged scans, number of points, delay span and step, and KMM1/KMM2 = mean of the last two columns.
- Experiment parameters (laser, rep. rate, attenuation, THz source, pump power, focusing, THz detection, probe power) are stored in the record's `source`; "Other experiment details" is `description`.
- Waveform roles: `reference`, `sample`, `reference_echo`, `sample_echo`.
- Sample thickness is stored in nanometres (`thickness_nm`); substrate thickness stays in micrometres. Older `metadata.yaml` files with `thickness_um` are still read and converted.

## Waveform treatment

Each waveform in the Add/Edit record page has an **Edit waveform** button. The editor offers, in this order:

1. **Baseline subtraction** – subtracts the mean of the signal in a chosen range.
2. **Trimming** – keeps only the data between two delays.
3. **Apodization** – multiplies by the lab's window function (`apodize` in `backend/thz/treatment.py`), centred on the detected peak by default, spanning centre ± width (default 5 ps).

Values can be typed, set with sliders, or dragged in the plot. The plot shows the waveform before and after, the window, and both spectra.

Traceability: the stored waveform is never changed. The settings are saved per waveform in `raw.waveform.treatment`; the analysis applies them and records what it applied in `analysed.transmission.treatment`. Changing the settings of an existing record goes through the edit history like any other edit. Treated records are marked "treated" in the viewer list, and export headers state the treatment of each dataset. In a `metadata.yaml` the same settings can be given as `treatment:` under a waveform.

## Re-run the analysis

Edit `backend/thz/analysis.py`, bump `ANALYSIS_VERSION`, then:

```bash
docker compose run --rm tools analyse
```

Changes to the API or export code (`api.py`, `spectra.py`) need `docker compose restart web`.

This empties the analysed layer and recomputes it from raw. The version is stored with every result and printed in export headers.

Current analysis (v1.1.0): each waveform is first treated as configured (see above), then T = FFT(sample) / FFT(reference) with the exp(−iωt) convention, so a delayed pulse has arg(T) > 0. No zero padding. The phase is unwrapped and its 2π offset fixed by linear extrapolation to f = 0. The "reliable band" shown by default is the region around the reference spectral peak where its amplitude is above 2 % of the peak.

## Database users

Everything is in one database, but each job has its own user, so the raw layer is protected by Postgres itself:

| User | `raw` | `analysed` | Used by |
|---|---|---|---|
| `thz` (owner) | all | all | `init` service, `backup` |
| `thz_importer` | read + write | none | `tools import`, `tools delete` |
| `thz_analysis` | read-only | read + write | `tools analyse` |
| `thz_web` | read-only | read-only | public pages, `tools list` |
| `thz_auth` | none | none | accounts and sessions (schema `auth`) only |

The `init` service creates the users and grants on every `docker compose up` (passwords from `.env`). The public pages use only `thz_web`. The logged-in Add record area uses `thz_importer` and `thz_analysis`, so the `web` container holds those passwords too; the analysis still cannot write to `raw`.

## Backup

```bash
docker compose run --rm backup
```

writes `backups/thz_<date>_<time>.dump` (whole database). Restore into an empty database with:

```bash
docker compose exec -T db pg_restore -U thz -d thz --clean --if-exists < backups/<file>.dump
```

The live database is in the Docker volume `pgdata`, deliberately not in this (ownCloud-synced) folder.

## Export format

Tab-separated text, header lines start with `#` (readable by `np.loadtxt`). Columns `X1 Y1 X2 Y2 …` as shown, padded with `nan`; or a common `X` and `Y1 Y2 …` when interpolated (PCHIP, `nan` outside the data). The interpolation axis is a numpy expression in the unit of the selected x-axis.

## Layout

- `docker-compose.yml` – `db` (PostgreSQL), `init`, `web` (FastAPI + static frontend), and on demand `tools`, `backup`
- `backend/thz/schema.sql` – both schemas; `backend/thz/db.py` – users and grants
- `backend/thz/importer.py`, `analysis.py`, `spectra.py`, `api.py`, `cli.py`
- `backend/thz/static/` – the web page
