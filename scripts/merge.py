"""
Merges output/sleeper.json and output/nflverse.json into a single file keyed
by Sleeper player ID, using the nflverse id crosswalk (sleeper_id <-> gsis_id)
so a Sleeper roster player_id can be looked up straight through to their
nflverse weekly stats and snap counts.

Writes: output/latest.json  <- this is the one stable URL Claude fetches.
"""

import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def load(name):
    with open(os.path.join(OUTPUT_DIR, name)) as f:
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
    sleeper = load("sleeper.json")
    nflverse = load("nflverse.json")

    sleeper_to_gsis = build_sleeper_to_gsis_map(nflverse["id_crosswalk"])
    weekly_by_gsis = nflverse["weekly_stats_by_gsis_id"]

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
                }
            )
        merged_rosters[roster_id] = {**owner, "players": merged_players}

    output = {
        "generated_for_week": sleeper["current_week"],
        "season": sleeper.get("season") or nflverse.get("season"),
        "league": sleeper["league"],
        "rosters_by_owner": merged_rosters,
        "trending_add": sleeper["trending_add"],
        "trending_drop": sleeper["trending_drop"],
        "recent_transactions": sleeper["recent_transactions"],
    }

    out_path = os.path.join(OUTPUT_DIR, "latest.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
