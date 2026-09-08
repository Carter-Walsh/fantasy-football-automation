"""
Pulls advanced usage metrics (snap %, target share, air yards, etc.) from
nflverse via `nflreadpy` (the actively maintained Python successor to the
now-archived `nfl_data_py`), plus the DynastyProcess/ffverse ID crosswalk
needed to bridge Sleeper's numeric player IDs to nflverse's gsis_id.

Single flat script, mirrors fetch_sleeper.py in style.

Writes: output/nflverse.json
"""

import json
import os
from datetime import datetime

import nflreadpy as nfl
import pandas as pd

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def current_season():
    now = datetime.utcnow()
    # NFL season year rolls over in Feb; before that, "this season" is last year's.
    return now.year if now.month >= 3 else now.year - 1


def fetch_id_crosswalk():
    """Returns a DataFrame with columns including sleeper_id and gsis_id,
    used to bridge Sleeper rosters to nflverse stats. Sourced from
    DynastyProcess/ffverse via nflreadpy's load_ff_playerids()."""
    try:
        ids = nfl.load_ff_playerids().to_pandas()
    except Exception as e:
        print(f"WARNING: id crosswalk fetch failed ({e}). Continuing with an "
              f"empty crosswalk — merge.py will just have no gsis_id matches.")
        return pd.DataFrame(columns=["sleeper_id", "gsis_id", "name", "position", "team"])
    keep_cols = [c for c in ["sleeper_id", "gsis_id", "name", "position", "team"] if c in ids.columns]
    return ids[keep_cols]


def fetch_weekly_stats(season):
    """Per-player, per-week box score stats for the season so far.

    Early in a season (or before Week 1 has been played), nflverse may not
    have published data for `season` yet. Treat that as "no data yet" rather
    than a fatal error — the pipeline should still run and produce
    rosters/crosswalk even without advanced stats until games start.
    """
    try:
        return nfl.load_player_stats(seasons=[season]).to_pandas()
    except Exception as e:
        print(f"WARNING: weekly data unavailable for season {season} ({e}). "
              f"Continuing with empty weekly stats — likely means the season "
              f"hasn't started yet.")
        return pd.DataFrame()


def fetch_snap_counts(season):
    """Per-player, per-week snap share (Pro Football Reference via nflverse).
    Same early-season caveat as above."""
    try:
        return nfl.load_snap_counts(seasons=[season]).to_pandas()
    except Exception as e:
        print(f"WARNING: snap count data unavailable for season {season} ({e}). "
              f"Continuing with empty snap counts.")
        return pd.DataFrame()


def safe_records(df):
    """Convert a DataFrame to JSON-safe records (NaN -> None)."""
    return json.loads(df.where(pd.notnull(df), None).to_json(orient="records"))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    season = current_season()

    crosswalk = fetch_id_crosswalk()
    weekly = fetch_weekly_stats(season)
    snaps = fetch_snap_counts(season)

    # Index weekly stats and snaps by gsis_id (player_id in nflverse weekly data)
    # so the merge step can do a single dict lookup per player instead of a
    # full table scan.
    weekly_by_player = {}
    if "player_id" in weekly.columns:
        for pid, group in weekly.groupby("player_id"):
            weekly_by_player[pid] = safe_records(group.sort_values("week"))

    snaps_by_player = {}
    if "pfr_player_id" in snaps.columns:
        key_col = "pfr_player_id"
    elif "player" in snaps.columns:
        key_col = "player"
    else:
        key_col = None

    if key_col:
        for key, group in snaps.groupby(key_col):
            snaps_by_player[key] = safe_records(group.sort_values("week"))

    output = {
        "season": season,
        "id_crosswalk": safe_records(crosswalk),
        "weekly_stats_by_gsis_id": weekly_by_player,
        "snap_counts": snaps_by_player,
        "snap_counts_key": key_col,
    }

    out_path = os.path.join(OUTPUT_DIR, "nflverse.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
