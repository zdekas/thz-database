-- Layer 1: raw data. Written only by the importer, never by the analysis.
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.measurement (
    id                      serial PRIMARY KEY,
    slug                    text NOT NULL UNIQUE,
    sample_name             text NOT NULL,
    experiment_date         date NOT NULL,
    responsible_person      text NOT NULL,
    added_by                text NOT NULL,
    added_at                timestamptz NOT NULL DEFAULT now(),
    description             text NOT NULL DEFAULT '',
    sample_type             text NOT NULL CHECK (sample_type IN ('thin_film', 'bulk')),
    reference_type          text NOT NULL CHECK (reference_type IN ('substrate', 'air')),
    material                text,
    substrate               text,
    thickness_nm            double precision,
    substrate_thickness_um  double precision,
    treatment               text,
    temperature_k           double precision,
    source                  jsonb NOT NULL DEFAULT '{}',
    extra                   jsonb NOT NULL DEFAULT '{}',
    search_text             text NOT NULL DEFAULT ''
);

-- The sample thickness used to be stored in micrometres.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'raw' AND table_name = 'measurement' AND column_name = 'thickness_um') THEN
        ALTER TABLE raw.measurement RENAME COLUMN thickness_um TO thickness_nm;
        UPDATE raw.measurement SET thickness_nm = thickness_nm * 1000;
    END IF;
END $$;

-- Any number of waveforms per measurement, each with its own time axis. The
-- pair (reference, sample) with label 'main' is the transmission measurement;
-- the echo roles hold separately scanned echoes. `info` keeps what the file
-- itself told us (header notes, timestamps, number of averages, ...).
CREATE TABLE IF NOT EXISTS raw.waveform (
    id              serial PRIMARY KEY,
    measurement_id  integer NOT NULL REFERENCES raw.measurement(id) ON DELETE CASCADE,
    role            text NOT NULL,
    label           text NOT NULL DEFAULT 'main',
    time_ps         double precision[] NOT NULL,
    amplitude       double precision[] NOT NULL,
    source_file     text,
    UNIQUE (measurement_id, role, label)
);
ALTER TABLE raw.waveform ADD COLUMN IF NOT EXISTS info jsonb NOT NULL DEFAULT '{}';
-- Treatment parameters chosen by the user (baseline, trimming, apodization);
-- applied by the analysis, the stored waveform itself stays as measured.
ALTER TABLE raw.waveform ADD COLUMN IF NOT EXISTS treatment jsonb NOT NULL DEFAULT '{}';
ALTER TABLE raw.waveform DROP CONSTRAINT IF EXISTS waveform_role_check;
ALTER TABLE raw.waveform ADD CONSTRAINT waveform_role_check
    CHECK (role IN ('reference', 'sample', 'reference_echo', 'sample_echo'));

-- Layer 2: analysed data. Can be dropped and rebuilt from raw at any time
-- with `thz analyse`.
CREATE SCHEMA IF NOT EXISTS analysed;

CREATE TABLE IF NOT EXISTS analysed.transmission (
    measurement_id    integer PRIMARY KEY REFERENCES raw.measurement(id) ON DELETE CASCADE,
    analysis_version  text NOT NULL,
    analysed_at       timestamptz NOT NULL DEFAULT now(),
    freq_thz          double precision[] NOT NULL,
    t_real            double precision[] NOT NULL,
    t_imag            double precision[] NOT NULL,
    phase_rad         double precision[] NOT NULL,
    band_min_thz      double precision NOT NULL,
    band_max_thz      double precision NOT NULL
);

-- Accounts for the "add record" area. Created with `thz create-user`.
-- What was applied to the waveforms before the FFT: {"reference": {...}, "sample": {...}}
ALTER TABLE analysed.transmission ADD COLUMN IF NOT EXISTS treatment jsonb NOT NULL DEFAULT '{}';

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.account (
    id             serial PRIMARY KEY,
    email          text NOT NULL UNIQUE,
    name           text NOT NULL DEFAULT '',
    password_hash  text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth.session (
    token_hash  text PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES auth.account(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);

-- Every edit made through the website first stores the complete previous
-- state of the record here (metadata and waveforms), so nothing is lost.
-- Version n is the record as it was before its n-th edit; version 1 is the
-- original.
CREATE TABLE IF NOT EXISTS raw.measurement_version (
    id              serial PRIMARY KEY,
    measurement_id  integer NOT NULL REFERENCES raw.measurement(id) ON DELETE CASCADE,
    version         integer NOT NULL,
    edited_at       timestamptz NOT NULL DEFAULT now(),
    edited_by       text NOT NULL,
    snapshot        jsonb NOT NULL,
    UNIQUE (measurement_id, version)
);
