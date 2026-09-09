"""
Pulls league, roster, user, matchup, transaction, and trending data from the
public Sleeper API for a given league.

No auth required. Single flat script, per design preference: no modules,
no framework, just a script you can read top to bottom.

Usage:
    python fetch_sleeper.py --league-id <id> --output output/sleeper_x.json

Writes to whatever path --output points at (default: output/sleeper.json).
The full player DB cache (output/players_cache.json) is shared across leagues
since it's league-agnostic — running this twice in one pipeline run for two
different leagues only downloads it once.
"""

import argparse
import json
import os
import time
import requests

BASE = "https://api.sleeper.app/v1"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
PLAYERS_CACHE = os.path.join(OUTPUT_DIR, "players_cache.json")
PLAYERS_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # Sleeper says: don't pull more than once/day


def get(url):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_league_settings(league_id):
    return get(f"{BASE}/league/{league_id}")


def fetch_rosters(league_id):
    return get(f"{BASE}/league/{league_id}/rosters")


def fetch_users(league_id):
    return get(f"{BASE}/league/{league_id}/users")


def fetch_nfl_state():
    return get(f"{BASE}/state/nfl")


def fetch_matchups(league_id, week):
    return get(f"{BASE}/league/{league_id}/matchups/{week}")


def fetch_transactions(league_id, round_):
    return get(f"{BASE}/league/{league_id}/transactions/{round_}")


def fetch_trending(add_or_drop, lookback_hours=24, limit=25):
    return get(
        f"{BASE}/players/nfl/trending/{add_or_drop}"
        f"?lookback_hours={lookback_hours}&limit={limit}"
    )


def fetch_traded_picks(league_id):
    """Draft pick ownership (who owns whose future picks). Mainly relevant
    for dynasty leagues where picks get traded; harmless empty list for
    redraft leagues that don't use this."""
    try:
        return get(f"{BASE}/league/{league_id}/traded_picks")
    except requests.HTTPError:
        return []


def fetch_all_players_cached():
    """The full player DB is ~5MB and Sleeper asks that you not pull it more
    than once a day. Cache it to disk and reuse if fresh. Shared across
    leagues within the same pipeline run."""
    if os.path.exists(PLAYERS_CACHE):
        age = time.time() - os.path.getmtime(PLAYERS_CACHE)
        if age < PLAYERS_CACHE_MAX_AGE_SECONDS:
            with open(PLAYERS_CACHE, "r") as f:
                return json.load(f)

    players = get(f"{BASE}/players/nfl")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PLAYERS_CACHE, "w") as f:
        json.dump(players, f)
    return players


def build_owner_map(users, rosters):
    """Map roster_id -> {username, display_name, team_name}."""
    user_by_id = {u["user_id"]: u for u in users}
    owner_map = {}
    for r in rosters:
        u = user_by_id.get(r["owner_id"], {})
        owner_map[r["roster_id"]] = {
            "username": u.get("username"),
            "display_name": u.get("display_name"),
            "team_name": (u.get("metadata") or {}).get("team_name"),
            "roster_id": r["roster_id"],
            "player_ids": r.get("players") or [],
            "starters": r.get("starters") or [],
        }
    return owner_map


def main():
    parser = argparse.ArgumentParser(description="Pull Sleeper data for one league.")
    parser.add_argument("--league-id", required=True, help="Sleeper league ID")
    parser.add_argument(
        "--output",
        default=os.path.join(OUTPUT_DIR, "sleeper.json"),
        help="Path to write the Sleeper-only JSON output",
    )
    args = parser.parse_args()
    league_id = args.league_id

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    league = fetch_league_settings(league_id)
    rosters = fetch_rosters(league_id)
    users = fetch_users(league_id)
    nfl_state = fetch_nfl_state()
    current_week = nfl_state.get("week", 1)

    owner_map = build_owner_map(users, rosters)

    trending_add = fetch_trending("add")
    trending_drop = fetch_trending("drop")
    traded_picks = fetch_traded_picks(league_id)

    # Recent transactions (last few rounds/weeks) for waiver context
    transactions = []
    for wk in range(max(1, current_week - 2), current_week + 1):
        try:
            transactions.extend(fetch_transactions(league_id, wk))
        except requests.HTTPError:
            pass

    players = fetch_all_players_cached()

    # Resolve names for each roster so downstream consumers don't need the
    # full 5MB player DB just to read a roster.
    for owner in owner_map.values():
        owner["players"] = [
            {
                "sleeper_id": pid,
                "name": players.get(pid, {}).get("full_name"),
                "position": players.get(pid, {}).get("position"),
                "team": players.get(pid, {}).get("team"),
            }
            for pid in owner["player_ids"]
        ]

    output = {
        "league_id": league_id,
        "league": league,
        "current_week": current_week,
        "season": nfl_state.get("season"),
        "rosters_by_owner": owner_map,
        "trending_add": trending_add,
        "trending_drop": trending_drop,
        "recent_transactions": transactions,
        "traded_picks": traded_picks,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

