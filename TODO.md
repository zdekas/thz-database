# TODO

Status on 2026-10-01. The site runs locally at http://localhost:8050 with one real record (`2026-06-29_Si_wafer`).

## Before the site is reachable from outside

- [x] **Real passwords.** `.env` with new passwords for all five database users is in use (2026-09-30); old defaults are rejected.
- [ ] **HTTPS.** Put a reverse proxy with a certificate in front (e.g. Caddy), and stop publishing port 8050 to the outside. Needs: which server, which domain name. Note: `COOKIE_SECURE=1` is already set in `.env`, so until HTTPS exists, login over plain http fails in Safari (set it to 0 meanwhile).
- [ ] **Initial password file.** Change the password of `zdenek.kaspar@matfyz.cuni.cz` on the site, then delete `initial-password-zdenek.txt`.
- [ ] **Decide what is public.** Every record and all its metadata (responsible person, "added by", experiment details) is visible to anyone. If data should be loaded before it is published, add a per-record "published" switch.
- [ ] **Production mode for the web container.** Build the code into the image instead of mounting `backend/thz`, and switch off the API page at `/api/docs`.

## Should do

- [ ] **Scheduled backups.** Run `docker compose run --rm backup` nightly, include `data/uploads/`, and do one restore test (restore has never been tested).
- [ ] **Serve Plotly locally.** The graph library currently loads from `cdn.plot.ly`.
- [x] **Version control.** The project is a git repository (initial commit 2026-09-30), on GitHub at `zdekas/thz-database`.
- [ ] **Server copy outside ownCloud.** On the deployment machine the project must not live in a synced folder.
- [ ] **Public-facing text.** Institute name, contact, and a note on how to cite or reuse the data.

## Scientific checks

- [ ] **Delay direction.** The analysis assumes a larger delay value means later time. Check with a real reference/sample pair that a sample which slows the pulse gives a positive delay; otherwise the sign of arg(T) and the delay is wrong.
- [ ] **Exact handling of shifted delay axes.** When reference and sample grids are offset by a fraction of a step, the current linear interpolation damps high frequencies (up to about 5 % at 2 THz for a 0.05 ps step). Replace with the phase-factor method when both scans have the same step.
- [ ] **Apodization width.** In the lab's `apodize` function the window spans centre ± width, so the default 5 ps covers 10 ps in total. Confirm this is what is wanted.
- [ ] **Apodization floor.** Outside the window the function returns 0.0023, not 0. Confirm this is intended.
- [ ] **Zero padding** as an optional treatment step.

## Next analysis (needs measured data first)

Discussed 2026-10-01. Before building, decide: which substrates besides silicon; whether echoes are in the same scan as the main pulse or scanned separately; whether separate echo scans share the same delay-stage zero.

- [ ] **Bulk: refractive index n(ω) and κ(ω).** From the main pulse alone, `δn = (n − 1)·δd/d`, so n is only as good as the thickness (500 µm Si: ±5 µm → δn ≈ 0.024). With the first echo, thickness and index follow from the two delays: `Δt₁ = (n − 1)d/c` (main pulse vs air), `Δt₂ = 2nd/c` (echo after main) → `d = c(Δt₂/2 − Δt₁)`, `n = Δt₂/(Δt₂ − 2Δt₁)`. Needs delays from a phase fit (1 µm ≈ 3 fs). Refinement for dispersive samples: choose d that minimises the Fabry-Perot ripple in n(ω).
- [ ] **Thin film: complex conductivity (Tinkham), bare-substrate reference.** `σ = (1 + n_s)/(Z₀·d_film) · (1/T − 1)` with `T = E_film+substrate / E_substrate`. Needs n_s and film thickness; no echo required.
- [ ] **Thin film: substrate thickness mismatch correction.** Reference and sample substrates differ in thickness; Δd adds a phase `(n_s − 1)ωΔd/c` (≈ 0.05 rad per µm of Si at 1 THz), mainly corrupting Im σ. The echo of each piece gives its optical thickness, so the mismatch can be removed. The bare substrate with its echo also gives n_s.
- [ ] **Thin film with only an air scan (experimental).** With `y = Z₀·σ·d_film`: main pulse vs air `T₀ = [2/(1 + n_s + y)]·[2n_s/(n_s + 1)]·exp(i(n_s − 1)ωd/c)`; first echo vs main pulse `R₁ = [(n_s − 1)/(n_s + 1)]·[(n_s − 1 − y)/(n_s + 1 + y)]·exp(2in_sωd/c)`. With n_s known and a low-loss substrate, |T₀| and |R₁| give Re y and Im y per frequency without any phase, so substrate thickness drops out; phases over-determine and allow fitting d. Caveats: does not cancel substrate absorption or focus shift (collimated beam helps); laser drift between air and sample scans enters |T₀| (R₁ is immune). Validate against the substrate-reference method on a sample measured both ways.

## Data

- [ ] **Store individual scans.** Only the averaged block of a lab file is in the database. Agreed plan: a table with `x (V)` and `y (V)` of every scan plus each scan's start time and mean KMM1/KMM2, and the checksum and size of the original file. Enables error bars, drift checks and re-averaging.
- [ ] **Raise the upload limit** from 20 MB to 100 MB per file (large measurements are 10–20 MB).
- [ ] **Laser value of `2026-06-29_Si_wafer`.** Stored as "Pharos"; becomes "Pharos Standard" the next time the record is saved from the edit page.

## Interface

- [ ] **Delete a record** from the website (now only `docker compose run --rm tools delete <identifier>`, plus removing its folder in `data/uploads/`).
- [ ] **Copy treatment settings** from one waveform to another (e.g. reference to sample, with the window following each peak).
- [ ] **Restore a previous version** from the edit history (versions can be viewed and compared, not restored).
- [ ] **Show previous versions' waveforms as plots** in the comparison (now file names and point counts only).
- [ ] **Per-waveform file info in the viewer** (notes, number of averages, KMM1/KMM2 are shown only on the add/edit page).
- [ ] **Fill experiment fields from the file's note lines** (now stored and displayed, but typed in by hand).
- [ ] **Guard against double submission** (saving the same new record twice creates a second one with `_2`).

## Later

- [ ] Further analysis types beyond those listed under "Next analysis".
- [ ] Accounts: creating users from the website instead of the command line, if more people will add data.
