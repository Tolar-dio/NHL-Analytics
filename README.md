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
- `data/external/bios/<season>/bios.jsonl`: each rostered player's NHL.com page: birth, size, draft, NHL teams, awards and every league season of his career (junior, college, Europe, minors, international tournaments, playoffs). One player per line so git stores small diffs.
- `data/external/draft/<year>.json`: every pick since 2005 (NHL records API, with player ids) and NHL Central Scouting's midterm and final rankings; `careers.jsonl` holds the careers of first- and second-round picks who aren't on a roster now, so draft comparisons include the misses.
- `data/external/wiki/`: Wikidata's map from NHL ids to English Wikipedia articles and each article's introduction (CC BY-SA 4.0), background for the AI writers; not shown on the site.

`analysis/nhle.py` learns NHL equivalency factors (what a point in the SHL, OHL, NCAA and so on is worth in the NHL) from those careers.

`scripts/buzz.py` runs hourly in the news job and writes `data/coverage/`: per-player headlines from Google News (headline, outlet, date, link only), public Bluesky posts from the reporters in `scripts/buzz_sources.json`, Reddit thread titles from r/hockey and the team subreddits (shown, never sent to the AI), and each team's YouTube videos. The site reads it straight from GitHub and shows only the last five days.

## Past seasons

The **Backfill a past season** workflow (Actions tab) pulls a full past season: every regular-season and playoff game, plus MoneyPuck shot data and season summaries. It saves progress month by month, so if it stops partway, run it again and it resumes. Last season (20252026) takes roughly 1 to 2 hours.

`data/external/moneypuck_summary/<season>/{skaters,goalies,teams,lines}.csv.gz`: MoneyPuck season-level tables, split by situation (all, 5on5, 5on4, 4on5, other). Refreshed nightly for the current season.

## The dashboard (site/)

**Built for every fan.** The site is written as a product for a general NHL audience: no default team and league-wide news sources only. Visitors pick their own team (stored in their browser) to get it first on Tonight, highlighted on the league chart and opened by the Teams tab, and can follow players and goalies from their pages. Times show in the visitor's time zone. AI-written pieces are labelled, and betting numbers carry a responsible-gambling notice.

`site/build.py` turns the data and models into JSON; `site/index.html`, `app.js` and `style.css` are a static page that reads it. The nightly workflow builds and deploys it to GitHub Pages after each data pull. Tabs: Tonight (goal and 2+ point odds with fair prices, goalie switcher), League (team map, standings with luck, goalie saves above expected), Teams, Players (shot maps, Edge tracking), My team (fantasy schedule grid from `site/config.json`, published only encrypted with the `FANTASY_PASSWORD` repository secret and hidden until unlocked), and Track record (backtest calibration and the live record). The footer links an About page (`site/about.js`) with methods, a glossary, data credits, how AI is used, responsible gambling and privacy.

To preview locally: `python site/build.py && cd site && python -m http.server`.

### Market lines, EDGE tracking and model checks

Tonight cards and previews show DraftKings' moneyline and total (published free by the NHL) next to the model's numbers, and the live record grades the model against them. NHL EDGE tracking adds shot locations by area, each player's hardest shots, per-game skating distance and goalies' high-danger save %. The props cover anytime goal and 1+, 2+ and 3+ points; model settings come from walk-forward tests documented in CLAUDE.md, and a nightly check compares shift-derived ice time with the NHL's official report.

### Lineups and the live record

Tonight's prices cover everyone who dressed in a team's last three games and is still on its roster, minus ESPN's injured list, plus players coming back from injury or just traded in; anyone who missed the last game is tagged, and every price assumes the player dresses (as sportsbooks do). Goalies are ESPN's probable starters when posted. Each game's prices are frozen at puck drop in `data/archive/` and graded the next morning by `analysis/track.py`, which feeds the "Live record" on the Track record page: the real test, since the backtest knew the actual lineups.

### Live scores and news

During games the site polls ESPN's public scoreboard every 30 seconds (scores across the top, on each Tonight card, and ESPN's probable starting goalies applied to the odds) and, on a game's live page, ESPN's play feed every minute for a live shot map, chance flow and "deserved to win", rated by an in-game xG model (`analysis/xg_live.py`). ESPN's injury report flags players on the odds, previews and My team. The News tab gathers ESPN, The Athletic, The Hockey News and Daily Faceoff headlines and groups reports of the same story; an hourly workflow (`news.yml`) has Claude write a short take on stories about players or teams we track, from the outlets' headlines and teasers plus our own numbers (about 1 cent each). It also lists worth-reading features and Substack newsletters, the latest podcast episodes (playable in the page from each show's public feed) and new YouTube videos (played through YouTube's own player). Team and player pages show the items that mention them, and game pages embed the NHL's official YouTube highlights. Sources live in `scripts/news_sources.json`; add or remove feeds there. YouTube's channel feeds fail on and off, so the job keeps the last good copy and, if a `YOUTUBE_API_KEY` secret exists (free, from Google Cloud), falls back to the YouTube Data API.

### Storylines and the Pulse

The Pulse tab is the narrative layer: who's hot and cold (last ten games against what the model expected at each player's ice time, with a verdict on whether the chances back it), point and goal streaks and droughts, breakouts (young players whose role and chances both stepped up), rookies, players due for more or due to cool off, goalie and team form, and career milestones in reach. Each preview gets storylines (schedule spots, rematches, injuries and returns, backup goalies, special-teams mismatches, players facing old teams or playing near home, milestones, model vs market) tagged with whether the model already prices them, plus three players to watch per team. Player pages get a bio and story block, team pages a few storylines. All of it is written deterministically by `site/narrative.py` from the site's own numbers and player bios from the NHL API (`fetch_external.py`), no web search or model calls.

### All Three Zones

Corey Sznajder's hand-tracked passing, zone entry and exit data (allthreezones.com, subscription) lives in a separate private repository; the nightly build reads its processed tables with a read-only token and publishes only derived, credited numbers. Player pages get a "How he plays" section: a few plain sentences on what to watch for when he's on the ice, an interactive style map placing him among every tracked forward or defenseman (shooter or playmaker, quality of looks, carrying the puck in; for D, moving the puck, defending the blue line, offense from the back), percentiles among his position, where his shots and setups come from next to a typical player, and a glossary. The points model gets a small playmaking nudge that improved 1+, 2+ and 3+ point log loss in a walk-forward test on 2025-26 and held on 2026-27. Goal prices are unchanged; tracked shooting rates didn't help them.

### Evolving-Hockey

Player pages also carry a "Value and impact" section from Evolving-Hockey's models (evolving-hockey.com), shown with their permission: wins and goals above replacement, the expected version built from chance quality, where the value came from (even-strength offense and defense, power play, penalty kill, penalties), RAPM impact on chances for and against with teammates, opponents, score and zone starts adjusted out, and a map of every forward or defenseman. The exports are downloaded by hand and kept in the private repository. They were tested as priors for the prop model and didn't improve it, so prices don't use them.

### Defense, goalies and tactics

Player pages have a Defense section: chances against at five on five with him on the ice compared with his team while he sits, high-danger chances against, blocks, takeaways and giveaways, penalty-kill minutes and how often he starts in his own end, this season next to last season, with a league map of hard minutes against results. Every goalie has a page (tap a goalie anywhere or search for him): saves above expected, save rate by shot danger against the league, rebound control, every shot he has faced, his start log and past seasons. Team pages show the coaching view: forward lines and defense pairs with their share of chances, power-play and penalty-kill units, who plays when, shift lengths, zone starts and, from All Three Zones tracking, how the team moves the puck.

### Moves and features

**Sleepers and the story layer.** Each game can get up to two Sleepers: our own under-the-radar picks, never "he's due". One is a third- or fourth-line forward whose recent shots have been dangerous, facing a defense or goalie that gives chances up. The other is a player whose chance of a point is clearly above his season pace because his ice time, power-play role, line or matchup changed. They're on Tonight and in previews with their reasons, and graded on the Track record page. `site/depthchart.py` reads the shift charts to say who's getting an injured regular's minutes (from games already played without him, or the depth chart), shown under injury storylines and on team pages and fed to news takes. Each game page has "The story" (streaks snapped, comebacks, late winners, first goals, milestones), and previews have "Where they're at" for both teams; the AI writers get both and are told to lead with the story, using only what happened. We tested moving ice time around for injuries, last game's linemates and depth-line matchups as model inputs; none held up across two seasons, so they inform the writing and the sleepers, not the probabilities (details in CLAUDE.md). One model change did hold: a role-based finishing prior, because depth forwards were being overrated.

The News tab's Moves list is every call-up, trade, signing, waiver move and coaching or front-office change from the last 30 days, from ESPN's public transactions feed, with each player's numbers alongside and a short note from Claude on trades and staff changes. Features are our own writing: a weekly "Around the league" column and player and team deep dives, written by Claude from the site's numbers only (`scripts/write_features.py`, one piece a night at most). To ask for a specific deep dive, add it to `data/features/requests.json`, for example `[{"kind": "player", "name": "Cale Makar"}, {"kind": "team", "team": "COL"}]`; the next nightly run writes it.

### Game catalogue and previews

Player pages open with the NHL headshot and bio and close with a highlight reel: every goal and assist this season with our replay of the play and the official NHL clip, plus the latest game highlights from the NHL's YouTube channel.

Every game this season gets a page (Games tab): a written recap, a "deserved to win" replay of every shot, an expected-goals flow chart, both teams' shot maps, each goal with a link to its official NHL highlight and a Replay that animates its build-up from the recorded events and shift charts (step through it moment by moment, or slow it to 0.25x), three stars, and player-by-player numbers. Tonight's games each get a preview page. Recaps and previews are written by Claude in the nightly run (needs the `ANTHROPIC_API_KEY` repository secret) and saved under `data/stories/` so each game is only written once.
