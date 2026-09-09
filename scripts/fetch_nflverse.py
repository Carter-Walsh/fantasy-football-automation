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


def fetch_ff_opportunity(season):
    """Precomputed Expected Fantasy Points (ffopportunity model) — lets us
    compute Fantasy Points Over Expectation (actual - expected) per player
    per week, the buy-low/sell-high signal. Separate dataset from
    load_player_stats(); same early-season caveat applies."""
    try:
        return nfl.load_ff_opportunity(seasons=[season], stat_type="weekly").to_pandas()
    except Exception as e:
        print(f"WARNING: ff_opportunity data unavailable for season {season} ({e}). "
              f"Continuing without Fantasy Points Over Expectation.")
        return pd.DataFrame()


def add_derived_columns(weekly):
    """Add simple derived metrics that aren't native nflverse columns but are
    trivial math on columns that already exist."""
    if weekly.empty:
        return weekly

    if "receiving_air_yards" in weekly.columns and "targets" in weekly.columns:
        weekly["adot"] = weekly.apply(
            lambda r: (r["receiving_air_yards"] / r["targets"])
            if r.get("targets") else None,
            axis=1,
        )

    if "carries" in weekly.columns and "targets" in weekly.columns:
        # Scott Barrett / PFF simple weighted opportunity (PPR weights).
        # Meaningful for RBs; harmless (just not very meaningful) for other positions.
        weekly["rb_weighted_opportunity"] = (
            weekly["carries"].fillna(0) * 0.58 + weekly["targets"].fillna(0) * 1.59
        )

    return weekly


def add_fantasy_points_over_expectation(weekly, ff_opp):
    """Join actual fantasy_points_ppr against ffopportunity's expected
    fantasy points, if we can find a matching expected-points column and a
    common join key. Fails gracefully (no FPOE column added) rather than
    guessing at an unconfirmed schema."""
    if weekly.empty or ff_opp.empty:
        return weekly

    join_keys = [k for k in ["player_id", "week"] if k in weekly.columns and k in ff_opp.columns]
    if len(join_keys) < 2:
        print("WARNING: couldn't find matching player_id/week columns between "
              "player_stats and ff_opportunity — skipping FPOE.")
        return weekly

    exp_cols = [
        c for c in ff_opp.columns
        if "fantasy_points" in c.lower() and ("exp" in c.lower())
    ]
    if not exp_cols:
        print("WARNING: no expected-fantasy-points column found in ff_opportunity "
              "data — skipping FPOE. (Schema may have changed upstream.)")
        return weekly

    exp_col = exp_cols[0]
    merged = weekly.merge(
        ff_opp[join_keys + [exp_col]],
        on=join_keys,
        how="left",
    )
    if "fantasy_points_ppr" in merged.columns:
        merged["fantasy_points_over_expectation"] = (
            merged["fantasy_points_ppr"] - merged[exp_col]
        )
    return merged


def build_points_allowed_by_position(weekly):
    """Aggregate, per defense faced, average PPR fantasy points allowed by
    position — a matchup-difficulty proxy. Not schedule-adjusted (that would
    require something like DVOA, which isn't freely available), so treat as
    a rough signal, not a precise one."""
    if weekly.empty or "opponent_team" not in weekly.columns:
        return {}

    result = {}
    group_cols = [c for c in ["opponent_team", "position"] if c in weekly.columns]
    if len(group_cols) < 2 or "fantasy_points_ppr" not in weekly.columns:
        return {}

    for (team, position), group in weekly.groupby(group_cols):
        result.setdefault(team, {})[position] = {
            "games": int(group["week"].nunique()) if "week" in group.columns else None,
            "avg_ppr_allowed": round(float(group["fantasy_points_ppr"].mean()), 2),
        }
    return result


def build_team_pass_rate(weekly):
    """Approximate team pass rate from box-score attempts/carries (not true
    play-calling rate, which needs play-by-play — this is a reasonable proxy
    from data we already have)."""
    if weekly.empty or "team" not in weekly.columns:
        return {}
    if "attempts" not in weekly.columns or "carries" not in weekly.columns:
        return {}

    result = {}
    for team, group in weekly.groupby("team"):
        pass_attempts = group["attempts"].sum()
        rush_attempts = group["carries"].sum()
        total = pass_attempts + rush_attempts
        result[team] = {
            "pass_attempts": int(pass_attempts),
            "rush_attempts": int(rush_attempts),
            "pass_rate": round(float(pass_attempts / total), 3) if total else None,
        }
    return result
    """Convert a DataFrame to JSON-safe records (NaN -> None)."""
    return json.loads(df.where(pd.notnull(df), None).to_json(orient="records"))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    season = current_season()

    crosswalk = fetch_id_crosswalk()
    weekly = fetch_weekly_stats(season)
    snaps = fetch_snap_counts(season)
    ff_opp = fetch_ff_opportunity(season)

    # Team-level context computed BEFORE derived per-player columns, since it
    # needs the raw box-score columns (attempts/carries/fantasy_points_ppr).
    points_allowed_by_position = build_points_allowed_by_position(weekly)
    team_pass_rate = build_team_pass_rate(weekly)

    weekly = add_derived_columns(weekly)
    weekly = add_fantasy_points_over_expectation(weekly, ff_opp)

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
        "points_allowed_by_position": points_allowed_by_position,
        "team_pass_rate": team_pass_rate,
    }

    out_path = os.path.join(OUTPUT_DIR, "nflverse.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
