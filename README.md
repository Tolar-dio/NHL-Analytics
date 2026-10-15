# NHL Analytics

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
