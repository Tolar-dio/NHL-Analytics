# NHL Analytics

**Dashboard:** https://tolar-dio.github.io/NHL-Analytics/ (rebuilt every morning and again mid-afternoon)

Personal NHL analytics project for the 2026-27 season. A GitHub Action pulls every completed game from the NHL's public API each night and stores it here.

## What's in here

`data/raw/<season>/<game_id>/` holds the untouched API responses for each game, gzipped:
- `pbp.json.gz`: play-by-play, including every shot with rink coordinates and shot type
- `boxscore.json.gz`: team and player box score
- `shifts.json.gz`: every player shift (who was on the ice when)
- `status.json`: which of the three downloaded successfully

`data/tables/<season>/` holds flat tables rebuilt from the raw files every run:
- `games.csv.gz`: one row per game with final score and how it was decided (REG / OT / SO)
- `events.csv.gz`: one row per event (shots, goals, faceoffs, hits, penalties, giveaways...)
- `shifts.csv.gz`: one row per player shift
- `players.csv.gz`: player IDs, names, teams, positions

## Running it

The workflow runs automatically at about 4:17 AM Denver time. To run it by hand (for example, the first backfill), go to the **Actions** tab, choose **Nightly NHL pull**, and press **Run workflow**.

Data source: the NHL's public API (api-web.nhle.com and api.nhle.com). Preseason games are skipped.

## Supplementary sources

`scripts/fetch_external.py` runs after the main pull:
- `data/external/moneypuck/<season>/<game_id>.csv.gz`: MoneyPuck's shot data, one file per game, including their expected goals (`xGoal`) and shot features. **Shot data courtesy of [MoneyPuck.com](https://moneypuck.com)**, used under their free non-commercial terms.
- `data/external/edge/<season>/skaters.csv.gz`: NHL Edge tracking per skater (top skating speed, 20+ mph bursts, distance, top shot speed, zone time, shots by danger area). Refreshed weekly.

## Past seasons

The **Backfill a past season** workflow (Actions tab) pulls a full past season: every regular-season and playoff game, plus MoneyPuck shot data and season summaries. It saves progress month by month, so if it stops partway, run it again and it resumes. Last season (20252026) takes roughly 1 to 2 hours.

`data/external/moneypuck_summary/<season>/{skaters,goalies,teams,lines}.csv.gz`: MoneyPuck season-level tables, split by situation (all, 5on5, 5on4, 4on5, other). Refreshed nightly for the current season.

## The dashboard (site/)

`site/build.py` turns the data and models into JSON; `site/index.html`, `app.js` and `style.css` are a static page that reads it. The nightly workflow builds and deploys it to GitHub Pages after each data pull. Tabs: Tonight (goal and 2+ point odds with fair prices, goalie switcher), League (team map, standings with luck, goalie saves above expected), Teams, Players (shot maps, Edge tracking), My team (fantasy schedule grid from `site/config.json`, published only encrypted with the `FANTASY_PASSWORD` repository secret and hidden until unlocked), and Trust the model? (backtest calibration).

To preview locally: `python site/build.py && cd site && python -m http.server`.

### Live scores and news

During games the site polls ESPN's public scoreboard every 30 seconds (scores across the top, on each Tonight card, and ESPN's probable starting goalies applied to the odds) and, on a game's live page, ESPN's play feed every minute for a live shot map, chance flow and "deserved to win", rated by an in-game xG model (`analysis/xg_live.py`). ESPN's injury report flags players on the odds, previews and My team. The News tab gathers ESPN, The Athletic, The Hockey News and Daily Faceoff headlines and groups reports of the same story; an hourly workflow (`news.yml`) has Claude write a short take on stories about players or teams we track, from the outlets' headlines and teasers plus our own numbers (about 1 cent each). It also lists worth-reading features and Substack newsletters, the latest podcast episodes (playable in the page from each show's public feed) and new YouTube videos (played through YouTube's own player). Team and player pages show the items that mention them, and game pages embed the NHL's official YouTube highlights. Sources live in `scripts/news_sources.json`; add or remove feeds there. YouTube's channel feeds fail on and off, so the job keeps the last good copy and, if a `YOUTUBE_API_KEY` secret exists (free, from Google Cloud), falls back to the YouTube Data API.

### Game catalogue and previews

Every game this season gets a page (Games tab): a written recap, a "deserved to win" replay of every shot, an expected-goals flow chart, both teams' shot maps, each goal with a link to its official NHL highlight and a Replay that animates its build-up from the recorded events and shift charts (step through it moment by moment, or slow it to 0.25x), three stars, and player-by-player numbers. Tonight's games each get a preview page. Recaps and previews are written by Claude in the nightly run (needs the `ANTHROPIC_API_KEY` repository secret) and saved under `data/stories/` so each game is only written once.
