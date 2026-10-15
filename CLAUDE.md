# Notes for Claude

This is Tolar's NHL analytics repository. The goal is league-wide analysis: team strength from xG and shot share, luck regression (shooting % and save % vs process), goaltender GSAx, deployment and line usage, special teams, and betting and fantasy hockey angles.

## Data

- Load the flat tables first: `data/tables/<season>/{games,events,shifts,players}.csv.gz` (pandas reads .gz directly).
- Raw API JSON lives in `data/raw/<season>/<game_id>/` if a field is missing from the tables.
- `scripts/fetch.py` downloads and rebuilds; `python scripts/fetch.py --tables-only` rebuilds tables from raw files without network access.
- The sandbox usually cannot reach the NHL API, so don't try to fetch there; the GitHub Action does that nightly.

## Conventions in events.csv

- `situation_code` is the NHL's 4-digit code: away goalie, away skaters, home skaters, home goalie. "1551" is 5v5; "1451" is a home power play 5v4; a 0 in a goalie slot means empty net.
- `x`, `y` are rink coordinates in feet from center ice. Which net a team shoots at flips by period; use `home_defending_side` to normalize before computing shot distance.
- For goals, player1 is the scorer and player2/player3 the assists; for blocked shots, player2 is the blocker; for faceoffs, player1 won.
- Shootout events have period 5 and period_type SO; exclude them from shot metrics.

## Working style

- Separate process from results. Flag small samples explicitly; single-game line stats are noise.
- Tag confidence: [Certain], [Likely], [Guessing].
- Any betting or wager tracking belongs in a separate private repository, not here (this one is public).

## Supplementary data

- MoneyPuck shots: `data/external/moneypuck/<season>/<game_id>.csv.gz` (their `xGoal` is the benchmark for our own xG model). Credit MoneyPuck.com in anything shown publicly.
- NHL Edge: `data/external/edge/<season>/skaters.csv.gz` (flattened) and `skaters_raw.json.gz` (full per-player JSON, includes per-area shot counts and record-game overlays).
- HTML time-on-ice reports (`toi_TH.htm.gz`, `toi_TV.htm.gz` in a game's raw folder) are the fallback when the shift JSON is empty. They still need a parser into shifts.csv.
