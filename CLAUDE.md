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
- For goals, player1 is the scorer and player2/player3 the assists; for blocked shots, player1 is the shooter, player2 the blocker, and `team` is the SHOOTING team (verified against boxscores); for faceoffs, player1 won.
- Shootout events have period 5 and period_type SO; exclude them from shot metrics.

## Working style

- Separate process from results. Flag small samples explicitly; single-game line stats are noise.
- Tag confidence: [Certain], [Likely], [Guessing].
- Any betting or wager tracking belongs in a separate private repository, not here (this one is public).

## Supplementary data

- MoneyPuck shots: `data/external/moneypuck/<season>/<game_id>.csv.gz` (their `xGoal` is the benchmark for our own xG model). Credit MoneyPuck.com in anything shown publicly.
- NHL Edge: `data/external/edge/<season>/skaters.csv.gz` (flattened) and `skaters_raw.json.gz` (full per-player JSON, includes per-area shot counts and record-game overlays).
- HTML time-on-ice reports (`toi_TH.htm.gz`, `toi_TV.htm.gz` in a game's raw folder) are the fallback when the shift JSON is empty; `fetch.py` parses them into shifts.csv. Overlapping JSON shifts are merged. Validated: every player-game TOI within 30s of the boxscore.

## Past seasons

- `data/raw/<season>/` and `data/tables/<season>/` hold each season separately; 20252026 is backfilled via `.github/workflows/backfill.yml`.
- `data/external/moneypuck_summary/<season>/` has MoneyPuck season summaries (skaters, goalies, teams, lines) by situation. Use last season as the prior for this season's shrinkage instead of league average; carry player priors with the player, not the team (rosters change).

## Analysis scripts

- `analysis/player_flags.py`: our own xG model (logistic, out-of-fold) plus skater and goalie tables. Run first.
- `analysis/onice.py`: 5v5 on-ice CF/xG/G and relative xGF% per skater.
- xG source: MoneyPuck's xGoal is primary (AUC 0.78 vs ours 0.73 shot-level; aggregates correlate 0.95+). Ours fills gaps.
- On-ice attribution: a player is on ice for an event if start_sec < t <= end_sec.
- `analysis/props_data.py <season>` builds per-game tables into `analysis/output/<season>/`; run it for both seasons before modeling.
- `analysis/models.py`: anytime goal, 2+ points, and game totals, with last-season priors that follow the player. Modes: `season-backtest 20252026`, `prior-backtest`, `tonight` (reads `analysis/slate.csv`).
- Backtest results (2025-26, 1,241 games, 44k player-games, walk-forward): goal and 2+ point probabilities are well calibrated and beat a naive baseline every month. Game totals do NOT beat league average (corr 0.08, RMSE 2.288 vs 2.290): treat totals as context, never as a betting edge.

## Dashboard

- `site/build.py` writes `site/data/*.json` (gitignored); the nightly workflow's `site` job runs the models, builds, and deploys `site/` to GitHub Pages.
- Fantasy roster lives in `site/config.json` (player IDs + slots). Update it when Tolar makes moves.
- My team is private: `build.py` writes it only as `data/fantasy.lock.json` (AES-GCM, PBKDF2 key from the `FANTASY_PASSWORD` secret) and writes nothing without the secret. Never publish fantasy data in the clear. The deploy stages only index.html, *.js, style.css and data/ (no config.json or Python).
- Rink markings in the shot maps are neutral on purpose: red means goal and nothing else.
- Season constants `CUR`/`PREV` live in `analysis/models.py`; bump them (and backfill) when a new season starts.
- Game catalogue: `site/games.py` (per-game JSON: shots, xG flow, deserved-to-win via exact Poisson-binomial, goals with NHL clip links, stars, player lines, goalie GSAx) and `site/previews.py` (same-day previews, projected lines from last game's shared ice time). Front end in `site/games.js`.
- `scripts/fetch.py` also saves each game's gamecenter `landing` and `right-rail` (current season only) and re-checks for 3 days until highlight clips post.
- `scripts/write_stories.py` writes recaps/previews with the Claude API (secret ANTHROPIC_API_KEY, model claude-sonnet-5-5), cached in `data/stories/` so each game is written once. House style: no em dashes, facts from the JSON only.
- NHL goal-tracking replays (wsr.nhle.com sprites) are restricted to NHL.com; do not spoof headers to fetch them. Link to official NHL.com clips; never download or rehost video. The one embed allowed is the NHL's own YouTube uploads through YouTube's player (see News rules).
- Every game page also gets `notes` (data-only sentences: the period one team owned, best chance that didn't go in, least likely goal, comebacks, goalie swings, power plays) plus a period box and penalties, so it reads well before or without a recap. Previews get the same (`preview_notes` in `site/previews.py`).
- `site/build.py` also writes `data/team_profiles.json` (special teams, penalties, 5v5 share per team) and `data/players/<id>.json` (per-game log for each skater).
- Stories: Sonnet 5.5 thinks by default and thinking counts against max_tokens. `write_stories.py` sends `thinking={"type": "between_tools"}` with max_tokens 2000, rejects anything that stops early or doesn't end on a full sentence, and treats a cut-off cached story as missing. Fact sheets label every team number by abbreviation and precompute records and counts (v1 swapped [away, home] stats and miscounted lists); bump `STORY_VERSION` to rewrite every cached story, and the build hides stories older than the current version.
- Our own goal replays: `goal_sequences()` in `site/games.py` stores each goal's lead-up (events since the last faceoff, capped at the final 60 s) plus who was on the ice from shifts; `site/replay.js` animates it (puck between recorded moments, gaps over 6 s fast-forwarded, frame stepping, 0.25x-2x). Passes are not in the public data, so never draw or describe them. `#goals/<date>` lists every goal from one night.
- Live layer (`site/live.js`), all from ESPN's public site API (CORS open; the NHL API isn't): scoreboard every 30 s (strip, Tonight cards, probable goalies auto-applied unless the user picked one), game summary every 60 s on `#live/<nhl game id>` (shot map, xG flow, deserved-to-win, rated by `analysis/xg_live.py`, exported to `data/xg_live.json`), injuries (flags on odds, previews, My team; Out/IR sink to the bottom), headlines on `#news` and team pages. ESPN coordinates equal the NHL's; ESPN credits blocked shots to the blocking team; ESPN team ids repeat across leagues, so check the uid for `~l:90~`.
- ESPN's edge returns 403 to headless Chromium; in Playwright tests, intercept ESPN requests and fulfil them with curl.
- `scripts/write_news.py` + `.github/workflows/news.yml` (hourly, own concurrency group): `scripts/media.py` gathers ESPN plus the RSS feeds in `scripts/news_sources.json` (news outlets, Substack newsletters, podcasts, YouTube channels), tags teams and tracked players (full names only), and groups reports of one story (same player or two-word name plus same transaction family, or similar wording, within 36 h). Claude takes stories that involve players we track or 1-2 teams, from headlines and teasers plus our numbers, no web search (~1 cent each, 8 per run max); takes are reused by article id and pruned after 21 days. Everything goes to `data/news/index.json` (stories, reads, listen, watch, highlights), read by the site from raw.githubusercontent.com (no redeploy); `data/news/cache/` keeps the last good YouTube lists and the game-to-highlight map.
- News rules: show headlines, teasers and links only; never republish or rewrite full article text, and never send paywalled or full text to Claude. Podcasts play from each show's public RSS enclosure. YouTube: RSS feed first, then the Data API (`YOUTUBE_API_KEY`, optional), then cache; never scrape YouTube pages. Videos play only through YouTube's own embed (youtube-nocookie), loaded on tap; NHL highlight videos are embedded that way on game pages (the NHL's own uploads through YouTube's player), never downloaded or rehosted. The Watch list skips Shorts, sponsor reads and the NHL channel (its videos only feed game pages).
