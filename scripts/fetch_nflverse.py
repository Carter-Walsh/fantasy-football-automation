"""
Pulls advanced usage metrics (snap %, target share, air yards, etc.) from
nflverse via the nfl_data_py package, plus the ID crosswalk needed to bridge
Sleeper's numeric player IDs to nflverse's gsis_id.

Single flat script, mirrors fetch_sleeper.py in style.

Writes: output/nflverse.json
"""

import json
import os
from datetime import datetime

import nfl_data_py as nfl
import pandas as pd

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def current_season():
    now = datetime.utcnow()
    # NFL season year rolls over in Feb; before that, "this season" is last year's.
    return now.year if now.month >= 3 else now.year - 1


def fetch_id_crosswalk():
    """Returns a DataFrame with columns including sleeper_id and gsis_id,
    used to bridge Sleeper rosters to nflverse stats."""
    ids = nfl.import_ids()
    keep_cols = [c for c in ["sleeper_id", "gsis_id", "name", "position", "team"] if c in ids.columns]
    return ids[keep_cols]


def fetch_weekly_stats(season):
    """Per-player, per-week box score stats for the season so far."""
    return nfl.import_weekly_data([season])


def fetch_snap_counts(season):
    """Per-player, per-week snap share."""
    return nfl.import_snap_counts([season])


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
        # snap counts key off pfr_player_id in some nflverse releases; fall back
        # to player if that column doesn't exist.
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
