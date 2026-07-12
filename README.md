# GQ-Gap-tracker
  Question: Based on my Strava training data, am I on track to hit a Boston Qualifying time, and if so, by when?

## Key finding (from current data)

- **27 runs** synced from Strava (2024-09-02 → 2026-06-18), Women category.
- **No heart-rate data** on any activity; 2 implausible slow-pace outliers flagged and excluded from fitness modeling.
- Age **24** (18–34 Women): BQ standard **3:25:00**, safe target **3:19:00** (−6:00 buffer).
- Current Riegel-equivalent marathon fitness ≈ **6:43**. Recent trend is **flat** (~6 sec/week).
- **Verdict: not on track** for Boston 2027 at the current training volume/pattern, the gap requires ~5 min/week of improvement that the recent data does not support.

## Setup

```bash
cd bq-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Credentials live in `.env` (gitignored). Copy from `.env.example` if needed. Tokens refresh automatically via `src/strava_sync.py`.

## Sync Strava → local file

```bash
PYTHONPATH=. python -m src.strava_sync          # incremental
PYTHONPATH=. python -m src.strava_sync --full   # full re-pull
```

Notebook and tracker both read `data/activities_raw.json`.

## Analysis notebook

```bash
cd notebooks
jupyter notebook analysis.ipynb
```

## Live tracker

```bash
PYTHONPATH=. python tracker/app.py
# → http://127.0.0.1:5055
```

One page: fitness trend vs BQ/safe lines, verdict text, Sync button.

## Project layout

```
bq-tracker/
  data/                 # activities_raw.json, athlete.json
  src/
    load_data.py        # load + quality report
    pace_models.py      # Daniels VDOT + Riegel
    bq_standards.py     # BAA table, buffer, downhill penalties
    fitness_trend.py    # weekly fitness + projection
    diagnostics.py      # mileage / gaps / HR efficiency
    strava_sync.py      # incremental API sync
    analysis.py         # shared payload for notebook + tracker
    config.py           # age / race / buffer
  notebooks/analysis.ipynb
  tracker/app.py
```
