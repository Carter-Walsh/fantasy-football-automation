"""
Pulls league, roster, user, matchup, transaction, and trending data from the
public Sleeper API for the "Threat Level Monday Night" league.

No auth required. Single flat script, per design preference: no modules,
no framework, just a script you can read top to bottom.

Writes: output/sleeper.json
"""

import json
import os
import time
import requests

LEAGUE_ID = "1370995280203223040"
BASE = "https://api.sleeper.app/v1"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
PLAYERS_CACHE = os.path.join(OUTPUT_DIR, "players_cache.json")
PLAYERS_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # Sleeper says: don't pull more than once/day


def get(url):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_league_settings():
    return get(f"{BASE}/league/{LEAGUE_ID}")


def fetch_rosters():
    return get(f"{BASE}/league/{LEAGUE_ID}/rosters")


def fetch_users():
    return get(f"{BASE}/league/{LEAGUE_ID}/users")


def fetch_nfl_state():
    return get(f"{BASE}/state/nfl")


def fetch_matchups(week):
    return get(f"{BASE}/league/{LEAGUE_ID}/matchups/{week}")


def fetch_transactions(round_):
    return get(f"{BASE}/league/{LEAGUE_ID}/transactions/{round_}")


def fetch_trending(add_or_drop, lookback_hours=24, limit=25):
    return get(
        f"{BASE}/players/nfl/trending/{add_or_drop}"
        f"?lookback_hours={lookback_hours}&limit={limit}"
    )


def fetch_all_players_cached():
    """The full player DB is ~5MB and Sleeper asks that you not pull it more
    than once a day. Cache it to disk and reuse if fresh."""
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    league = fetch_league_settings()
    rosters = fetch_rosters()
    users = fetch_users()
    nfl_state = fetch_nfl_state()
    current_week = nfl_state.get("week", 1)

    owner_map = build_owner_map(users, rosters)

    trending_add = fetch_trending("add")
    trending_drop = fetch_trending("drop")

    # Recent transactions (last few rounds/weeks) for waiver context
    transactions = []
    for wk in range(max(1, current_week - 2), current_week + 1):
        try:
            transactions.extend(fetch_transactions(wk))
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
        "league": league,
        "current_week": current_week,
        "season": nfl_state.get("season"),
        "rosters_by_owner": owner_map,
        "trending_add": trending_add,
        "trending_drop": trending_drop,
        "recent_transactions": transactions,
    }

    out_path = os.path.join(OUTPUT_DIR, "sleeper.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
