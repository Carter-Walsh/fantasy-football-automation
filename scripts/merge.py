"""
Merges a Sleeper output file (from fetch_sleeper.py) and the shared
nflverse.json (from fetch_nflverse.py) into a single file keyed by Sleeper
player ID, using the nflverse id crosswalk (sleeper_id <-> gsis_id) so a
Sleeper roster player_id can be looked up straight through to their nflverse
weekly stats and snap counts.

nflverse.json is league-agnostic (same NFL players regardless of league), so
one nflverse.json can be merged against multiple leagues' Sleeper files in
the same pipeline run without re-fetching it.

Usage:
    python merge.py --sleeper output/sleeper_redraft.json --output output/latest_redraft.json
"""

import argparse
import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def load(path):
    with open(path) as f:
        return json.load(f)


def build_sleeper_to_gsis_map(crosswalk):
    mapping = {}
    for row in crosswalk:
        sleeper_id = row.get("sleeper_id")
        gsis_id = row.get("gsis_id")
        if sleeper_id and gsis_id:
            # sleeper_id in the crosswalk may be a float-like string; normalize.
            mapping[str(int(float(sleeper_id)))] = gsis_id
    return mapping


def main():
    parser = argparse.ArgumentParser(description="Merge one league's Sleeper data with shared nflverse data.")
    parser.add_argument("--sleeper", required=True, help="Path to this league's sleeper_*.json")
    parser.add_argument(
        "--nflverse",
        default=os.path.join(OUTPUT_DIR, "nflverse.json"),
        help="Path to the shared nflverse.json (same for all leagues)",
    )
    parser.add_argument("--output", required=True, help="Path to write the merged latest_*.json")
    args = parser.parse_args()

    sleeper = load(args.sleeper)
    nflverse = load(args.nflverse)

    sleeper_to_gsis = build_sleeper_to_gsis_map(nflverse["id_crosswalk"])
    weekly_by_gsis = nflverse["weekly_stats_by_gsis_id"]
    team_pass_rate = nflverse.get("team_pass_rate", {})
    points_allowed_by_position = nflverse.get("points_allowed_by_position", {})

    merged_rosters = {}
    for roster_id, owner in sleeper["rosters_by_owner"].items():
        merged_players = []
        for player in owner["players"]:
            sleeper_id = str(player["sleeper_id"])
            gsis_id = sleeper_to_gsis.get(sleeper_id)
            advanced = weekly_by_gsis.get(gsis_id, []) if gsis_id else []
            merged_players.append(
                {
                    **player,
                    "gsis_id": gsis_id,
                    "weekly_advanced_stats": advanced,
                    # Team-level pass-volume context (the "how big is the pie"
                    # question) — same for every player on this team, included
                    # per-player so it's visible without a separate lookup.
                    "team_pass_rate_context": team_pass_rate.get(player.get("team")),
                }
            )
        merged_rosters[roster_id] = {**owner, "players": merged_players}

    output = {
        "league_id": sleeper.get("league_id"),
        "generated_for_week": sleeper["current_week"],
        "season": sleeper.get("season") or nflverse.get("season"),
        "league": sleeper["league"],
        "rosters_by_owner": merged_rosters,
        "trending_add": sleeper["trending_add"],
        "trending_drop": sleeper["trending_drop"],
        "recent_transactions": sleeper["recent_transactions"],
        "traded_picks": sleeper.get("traded_picks", []),
        # Full league-wide table, useful for matchup analysis once you know
        # this week's opponent (points_allowed_by_position isn't
        # schedule-adjusted — it's a rough proxy, not a DVOA-style stat).
        "points_allowed_by_position": points_allowed_by_position,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

