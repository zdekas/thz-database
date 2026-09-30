# TODO

Status on 2026-09-30. The site runs locally at http://localhost:8050 with one real record (`2026-06-29_Si_wafer`).

## Before the site is reachable from outside

- [ ] **Real passwords.** Create `.env` from `.env.example` with strong values for all five database users. The owner (`thz`) password is only set when the database is first created, so it also needs a one-off `ALTER ROLE thz PASSWORD ...` inside the running database.
- [ ] **HTTPS.** Put a reverse proxy with a certificate in front (e.g. Caddy), set `COOKIE_SECURE=1`, and stop publishing port 8050 to the outside. Needs: which server, which domain name.
- [ ] **Initial password file.** Change the password of `zdenek.kaspar@matfyz.cuni.cz` on the site, then delete `initial-password-zdenek.txt`.
- [ ] **Decide what is public.** Every record and all its metadata (responsible person, "added by", experiment details) is visible to anyone. If data should be loaded before it is published, add a per-record "published" switch.
- [ ] **Production mode for the web container.** Build the code into the image instead of mounting `backend/thz`, and switch off the API page at `/api/docs`.

## Should do

- [ ] **Scheduled backups.** Run `docker compose run --rm backup` nightly, include `data/uploads/`, and do one restore test (restore has never been tested).
- [ ] **Serve Plotly locally.** The graph library currently loads from `cdn.plot.ly`.
- [x] **Version control.** The project is a git repository (initial commit 2026-09-30). No remote yet.
- [ ] **Server copy outside ownCloud.** On the deployment machine the project must not live in a synced folder.
- [ ] **Public-facing text.** Institute name, contact, and a note on how to cite or reuse the data.

## Scientific checks

- [ ] **Delay direction.** The analysis assumes a larger delay value means later time. Check with a real reference/sample pair that a sample which slows the pulse gives a positive delay; otherwise the sign of arg(T) and the delay is wrong.
- [ ] **Exact handling of shifted delay axes.** When reference and sample grids are offset by a fraction of a step, the current linear interpolation damps high frequencies (up to about 5 % at 2 THz for a 0.05 ps step). Replace with the phase-factor method when both scans have the same step.
- [ ] **Apodization width.** In the lab's `apodize` function the window spans centre ± width, so the default 5 ps covers 10 ps in total. Confirm this is what is wanted.
- [ ] **Apodization floor.** Outside the window the function returns 0.0023, not 0. Confirm this is intended.
- [ ] **Zero padding** as an optional treatment step.
- [ ] **Echo analysis.** Echo waveforms are stored (`reference_echo`, `sample_echo`) but not analysed yet: thickness and refractive index from echoes.

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

- [ ] More analysis beyond complex transmission (refractive index, conductivity, ...).
- [ ] Accounts: creating users from the website instead of the command line, if more people will add data.
