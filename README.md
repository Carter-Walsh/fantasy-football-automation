# Fantasy Pipeline — Threat Level Monday Night

Pulls Sleeper league/roster data + nflverse advanced metrics, merges them by
player ID, and produces one file: `output/latest.json`. That file is what
Claude fetches to evaluate trades, waivers, and targets with real data instead
of memory.

## One-time setup

1. Create a new GitHub repo (public or private — doesn't matter, since GitHub
   raw file URLs work for both public repos, and private repos too as long as
   you're comfortable pasting a token-free raw link; simplest is **public**
   unless you'd rather keep roster data private).
2. Push these files to it, preserving the folder structure:
   - `scripts/fetch_sleeper.py`
   - `scripts/fetch_nflverse.py`
   - `scripts/merge.py`
   - `.github/workflows/run-pipeline.yml`
   - `output/.gitkeep` (empty file, just so the folder exists)
3. In the repo: **Settings → Actions → General → Workflow permissions** →
   select **"Read and write permissions"** → Save. (Without this, the workflow
   can't commit `output/latest.json` back to the repo.)

That's it — no API keys or secrets needed. Sleeper and nflverse are both public.

## Running it (manual trigger, from your phone)

**Option A — GitHub mobile app (easiest, no extra setup):**
1. Open the GitHub app → your repo → **Actions** tab.
2. Tap **"Fantasy Pipeline (manual)"** → **Run workflow** → **Run workflow**
   (confirm on the default branch).
3. Takes 1-3 minutes. Refresh the Actions tab to confirm it's green.

**Option B — One-tap phone Shortcut (iOS Shortcuts / Android equivalent):**
Have the shortcut send this HTTP request:

```
POST https://api.github.com/repos/<your-username>/<your-repo>/actions/workflows/run-pipeline.yml/dispatches
Headers:
  Authorization: Bearer <a GitHub Personal Access Token with "repo" + "workflow" scope>
  Accept: application/vnd.github+json
Body (JSON):
  { "ref": "main" }
```

Generate the token once at github.com → Settings → Developer settings →
Personal access tokens → generate (fine-grained, scoped just to this repo,
with Actions: read/write). Store it in the Shortcut, not anywhere public.

## Getting the data into a Claude conversation

Once a run finishes, the merged file is always at this same URL (replace with
your actual username/repo):

```
https://raw.githubusercontent.com/<your-username>/<your-repo>/main/output/latest.json
```

Save that URL next to your Sleeper API links snippet. Paste it into your
message (along with a trade screenshot, or a waiver/trade-target question) and
Claude will fetch it directly — same merged data your script produces, no
extra step on Claude's end.

## Notes

- Runs automatically every Tuesday at 12:00 UTC (adjust the cron line in the
  workflow if you want a different time — GitHub Actions cron doesn't shift
  for daylight saving, so the local time will drift an hour twice a year).
  Manual trigger still works any time on top of that, for ad-hoc checks.
- `output/players_cache.json` (the full Sleeper player DB, ~5MB) is cached and
  only re-pulled once every 24 hours, per Sleeper's API guidance.
- If a run fails, check the Actions log first — most likely cause is nflverse
  not having published current-week data yet (it usually lags a day or two
  behind Sleeper), or the workflow permissions step above not being set.
