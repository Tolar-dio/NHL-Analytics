"""Nightly NHL data pull.

Downloads every completed game of the season from the NHL's public API
(play-by-play, boxscore, shift charts), stores the raw JSON gzipped, then
rebuilds flat CSV tables that are easy to analyze.

Standard library only, so the GitHub Action needs no installs.

Usage:
    python scripts/fetch.py                 # current season, all finished games not yet saved
    python scripts/fetch.py --season 20262027 --start 2026-09-01
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"

FINISHED = {"OFF", "FINAL"}
GAME_TYPES = {2: "regular", 3: "playoffs"}  # preseason (1) is skipped
SHIFT_RETRY_DAYS = 7    # shift charts sometimes post late; keep retrying this long
SHIFT_MIN_ATTEMPTS = 5  # ...and never give up before this many separate tries

HEADERS = {"User-Agent": "nhl-analytics-personal-research/1.0"}


# ---------------------------------------------------------------- helpers

def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = 2 ** attempt
            print(f"  ! {url} failed ({e}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def write_gz_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))


def read_gz_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_gz_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # mtime=0 keeps the file byte-identical when content is unchanged,
    # so git doesn't record a pointless change every night
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding="utf-8", newline="") as t:
            w = csv.writer(t)
            w.writerow(header)
            w.writerows(rows)
    data = buf.getvalue()
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return
    with open(path, "wb") as f:
        f.write(data)


def name_of(obj, key):
    v = obj.get(key)
    if isinstance(v, dict):
        return v.get("default", "")
    return v or ""


def mmss_to_sec(s):
    if not s or ":" not in s:
        return None
    m, sec = s.split(":")
    return int(m) * 60 + int(sec)


def current_season(today):
    # NHL seasons start in fall; before August we're still in last season
    y = today.year if today.month >= 8 else today.year - 1
    return f"{y}{y + 1}"


# ---------------------------------------------------------------- schedule

def finished_games(start, end, season=None):
    """All completed regular-season and playoff games between two dates.

    Game IDs start with the season's first year (2025020107 -> 2025-26), so
    filtering on that keeps a backfill from filing next season's games under
    the wrong season.
    """
    games, day = {}, start
    while day <= end:
        sched = get_json(f"{WEB}/schedule/{day.isoformat()}")
        for week in sched.get("gameWeek", []):
            if not (start.isoformat() <= week.get("date", "") <= end.isoformat()):
                continue
            for g in week.get("games", []):
                if season and str(g["id"])[:4] != season[:4]:
                    continue
                if g.get("gameType") in GAME_TYPES and g.get("gameState") in FINISHED:
                    games[g["id"]] = {
                        "game_id": g["id"],
                        "date": week.get("date"),
                        "game_type": GAME_TYPES[g["gameType"]],
                    }
        day += dt.timedelta(days=7)  # each schedule call returns a full week
        time.sleep(0.3)
    return games


# ---------------------------------------------------------------- download

def game_dir(season, gid):
    return os.path.join(DATA, "raw", season, str(gid))


def download_game(season, gid, game_date, want_detail=False):
    d = game_dir(season, gid)
    status_path = os.path.join(d, "status.json")
    status = json.load(open(status_path)) if os.path.exists(status_path) else {}

    if not status.get("pbp"):
        write_gz_json(os.path.join(d, "pbp.json.gz"),
                      get_json(f"{WEB}/gamecenter/{gid}/play-by-play"))
        status["pbp"] = True
        time.sleep(0.3)

    if not status.get("boxscore"):
        write_gz_json(os.path.join(d, "boxscore.json.gz"),
                      get_json(f"{WEB}/gamecenter/{gid}/boxscore"))
        status["boxscore"] = True
        time.sleep(0.3)

    if not status.get("shifts"):
        try:
            sh = get_json(f"{STATS}/shiftcharts?cayenneExp=gameId={gid}")
            if sh.get("data"):
                write_gz_json(os.path.join(d, "shifts.json.gz"), sh)
                status["shifts"] = True
        except RuntimeError as e:
            print(f"  ! shifts unavailable for {gid}: {e}", file=sys.stderr)
        # The JSON shift feed is empty for many games. Fall back to the NHL's
        # official HTML time-on-ice reports (home TH / visitor TV), saved raw
        # so they can be parsed into the shifts table.
        if not status.get("shifts") and not status.get("shifts_html"):
            got = save_toi_html(season, gid, d)
            if got:
                status["shifts_html"] = True
        if not status.get("shifts") and not status.get("shifts_html"):
            status["shift_attempts"] = status.get("shift_attempts", 0) + 1
            age = (dt.date.today() - dt.date.fromisoformat(game_date)).days
            # give up only after a week AND several separate tries, so one bad
            # run (rate limiting, API hiccup) can't permanently drop a game
            if age > SHIFT_RETRY_DAYS and status["shift_attempts"] >= SHIFT_MIN_ATTEMPTS:
                status["shifts"] = "missing"
        time.sleep(1.0)

    if want_detail and not status.get("detail"):
        fetch_detail(gid, game_date, d, status)

    os.makedirs(d, exist_ok=True)
    with open(status_path, "w") as f:
        json.dump(status, f)


DETAIL_RETRY_DAYS = 3  # highlight clips post a few hours after the game; keep checking this long


def fetch_detail(gid, game_date, d, status):
    """Gamecenter landing (goals with highlight clips, three stars) and right-rail
    (3-minute recap / condensed game video IDs, season series, linescore).

    Marked done once every goal has a highlight clip, or after DETAIL_RETRY_DAYS.
    """
    try:
        landing = get_json(f"{WEB}/gamecenter/{gid}/landing", tries=2)
        time.sleep(0.4)
        rail = get_json(f"{WEB}/gamecenter/{gid}/right-rail", tries=2)
        time.sleep(0.4)
    except RuntimeError as e:
        print(f"  ! detail unavailable for {gid}: {e}", file=sys.stderr)
        return
    write_gz_json(os.path.join(d, "landing.json.gz"), landing)
    write_gz_json(os.path.join(d, "rightrail.json.gz"), rail)
    goals = [g for per in (landing.get("summary") or {}).get("scoring", []) for g in per.get("goals", [])]
    clips_ready = all(g.get("highlightClip") for g in goals) and \
        bool((rail.get("gameVideo") or {}).get("threeMinRecap"))
    age = (dt.date.today() - dt.date.fromisoformat(game_date)).days
    status["detail"] = bool(clips_ready or age > DETAIL_RETRY_DAYS)


def save_toi_html(season, gid, d):
    """Download home (TH) and visitor (TV) HTML time-on-ice reports."""
    num = str(gid)[4:]  # 2026020006 -> 020006
    ok = True
    for code in ("TH", "TV"):
        url = f"https://www.nhl.com/scores/htmlreports/{season}/{code}{num}.HTM"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read()
            if len(html) < 5000:  # an error page, not a report
                ok = False
                continue
            os.makedirs(d, exist_ok=True)
            with gzip.open(os.path.join(d, f"toi_{code}.htm.gz"), "wb") as f:
                f.write(html)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  ! {code} report unavailable for {gid}: {e}", file=sys.stderr)
            ok = False
        time.sleep(1.0)
    return ok


def needs_work(season, gid, want_detail=False):
    p = os.path.join(game_dir(season, gid), "status.json")
    if not os.path.exists(p):
        return True
    s = json.load(open(p))
    core = s.get("pbp") and s.get("boxscore") and (s.get("shifts") or s.get("shifts_html"))
    return not core or (want_detail and not s.get("detail"))


# ---------------------------------------------------------------- flat tables

EVENT_COLS = [
    "game_id", "date", "game_type", "event_id", "sort_order", "period",
    "period_type", "time_in_period", "game_seconds", "event", "situation_code",
    "team", "home_team", "away_team", "home_defending_side", "x", "y", "zone",
    "shot_type", "player1_id", "player1", "player2_id", "player2",
    "player3_id", "player3", "goalie_id", "goalie", "home_score", "away_score",
    "penalty_type", "penalty_minutes", "reason",
]

# which detail fields hold the primary / secondary / tertiary player per event
PLAYER_KEYS = {
    "goal": ("scoringPlayerId", "assist1PlayerId", "assist2PlayerId"),
    "shot-on-goal": ("shootingPlayerId", None, None),
    "missed-shot": ("shootingPlayerId", None, None),
    "blocked-shot": ("shootingPlayerId", "blockingPlayerId", None),
    "faceoff": ("winningPlayerId", "losingPlayerId", None),
    "hit": ("hittingPlayerId", "hitteePlayerId", None),
    "giveaway": ("playerId", None, None),
    "takeaway": ("playerId", None, None),
    "penalty": ("committedByPlayerId", "drawnByPlayerId", "servedByPlayerId"),
}


TOI_HEADING = re.compile(r'class="playerHeading[^"]*"[^>]*>\s*(\d+)\s+([^<]+?)\s*</td>')
TOI_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
PERIOD_NUM = {"OT": 4, "SO": 5}


def parse_toi_html(path):
    """Yield (sweater, name, [(shift_no, period, start, end)]) per player.

    Start/end are elapsed time within the period ("12:34"), matching the
    JSON shift feed's convention.
    """
    with gzip.open(path, "rb") as f:
        html = f.read().decode("utf-8", "replace")
    heads = list(TOI_HEADING.finditer(html))
    for i, m in enumerate(heads):
        block = html[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
            cells = [re.sub(r"<[^>]+>|&nbsp;", "", c).strip() for c in TOI_CELL.findall(tr)]
            # real shift rows show "elapsed / game" times; this skips header
            # rows and the per-period summary table under each player
            if len(cells) < 5 or not cells[0].isdigit() or "/" not in cells[2]:
                continue
            per = PERIOD_NUM.get(cells[1], cells[1])
            if not str(per).isdigit():
                continue
            start = cells[2].split("/")[0].strip()
            end = cells[3].split("/")[0].strip()
            rows.append((int(cells[0]), int(per), start, end))
        yield m.group(1), m.group(2), rows


def merge_overlapping_shifts(rows):
    """The JSON feed sometimes repeats or overlaps a player's shifts, which
    would double-count ice time. Merge overlaps within (game, player, period)."""
    groups = {}
    for r in rows:
        groups.setdefault((r[0], r[1], r[4]), []).append(r)
    out = []
    for key in sorted(groups, key=lambda k: (k[0], str(k[1]), k[2] or 0)):
        rs = sorted(groups[key], key=lambda r: (r[8] if r[8] is not None else -1))
        cur = None
        for r in rs:
            if cur and r[8] is not None and cur[9] is not None and r[8] < cur[9]:
                if r[9] is not None and r[9] > cur[9]:
                    cur[7], cur[9] = r[7], r[9]
                continue
            if cur:
                out.append(cur)
            cur = list(r)
        if cur:
            out.append(cur)
    return out


def build_tables(season):
    raw = os.path.join(DATA, "raw", season)
    if not os.path.isdir(raw):
        return
    games_rows, event_rows, shift_rows, player_rows = [], [], [], {}

    for gid in sorted(os.listdir(raw)):
        d = os.path.join(raw, gid)
        pbp_path = os.path.join(d, "pbp.json.gz")
        if not os.path.exists(pbp_path):
            continue
        pbp = read_gz_json(pbp_path)

        home, away = pbp.get("homeTeam", {}), pbp.get("awayTeam", {})
        team_abbr = {home.get("id"): home.get("abbrev"), away.get("id"): away.get("abbrev")}
        roster = {}
        for p in pbp.get("rosterSpots", []):
            pid = p.get("playerId")
            nm = f"{name_of(p, 'firstName')} {name_of(p, 'lastName')}".strip()
            roster[pid] = nm
            player_rows[pid] = [pid, nm, team_abbr.get(p.get("teamId"), ""),
                                p.get("positionCode", ""), p.get("sweaterNumber", "")]

        date = pbp.get("gameDate", "")
        gtype = GAME_TYPES.get(pbp.get("gameType"), str(pbp.get("gameType")))
        outcome = (pbp.get("gameOutcome") or {}).get("lastPeriodType", "")
        games_rows.append([gid, date, gtype, home.get("abbrev"), away.get("abbrev"),
                           home.get("score"), away.get("score"), outcome,
                           pbp.get("venue", {}).get("default", "")
                           if isinstance(pbp.get("venue"), dict) else ""])

        for ev in pbp.get("plays", []):
            det = ev.get("details", {}) or {}
            kind = ev.get("typeDescKey", "")
            pdesc = ev.get("periodDescriptor", {}) or {}
            per = pdesc.get("number")
            tip = ev.get("timeInPeriod")
            secs = mmss_to_sec(tip)
            gsec = None if secs is None or per is None else (min(per, 4) - 1) * 1200 + secs
            keys = PLAYER_KEYS.get(kind, (None, None, None))
            pids = [det.get(k) if k else None for k in keys]
            goalie = det.get("goalieInNetId")
            event_rows.append([
                gid, date, gtype, ev.get("eventId"), ev.get("sortOrder"), per,
                pdesc.get("periodType", ""), tip, gsec, kind, ev.get("situationCode", ""),
                team_abbr.get(det.get("eventOwnerTeamId"), ""),
                home.get("abbrev"), away.get("abbrev"), ev.get("homeTeamDefendingSide", ""),
                det.get("xCoord"), det.get("yCoord"), det.get("zoneCode", ""),
                det.get("shotType", ""),
                pids[0], roster.get(pids[0], ""), pids[1], roster.get(pids[1], ""),
                pids[2], roster.get(pids[2], ""), goalie, roster.get(goalie, ""),
                det.get("homeScore"), det.get("awayScore"),
                det.get("descKey", "") if kind == "penalty" else "",
                det.get("duration", "") if kind == "penalty" else "",
                det.get("reason", ""),
            ])

        sh_path = os.path.join(d, "shifts.json.gz")
        if not os.path.exists(sh_path):
            # fall back to the HTML time-on-ice reports
            num_to_pid = {}
            for p in pbp.get("rosterSpots", []):
                num_to_pid[(p.get("teamId"), str(p.get("sweaterNumber")))] = p.get("playerId")
            for code, team in (("TH", home), ("TV", away)):
                hp = os.path.join(d, f"toi_{code}.htm.gz")
                if not os.path.exists(hp):
                    continue
                for num, pname, rows in parse_toi_html(hp):
                    pid = num_to_pid.get((team.get("id"), num))
                    for shift_no, per, start, end in rows:
                        shift_rows.append([
                            gid, pid, roster.get(pid, pname), team.get("abbrev"), per,
                            shift_no, start, end, mmss_to_sec(start), mmss_to_sec(end),
                        ])
        if os.path.exists(sh_path):
            for s in read_gz_json(sh_path).get("data", []):
                if s.get("typeCode") not in (517, None):  # 517 = shift; 505 = goal marker
                    continue
                pid = s.get("playerId")
                shift_rows.append([
                    gid, pid, f"{s.get('firstName', '')} {s.get('lastName', '')}".strip(),
                    s.get("teamAbbrev", ""), s.get("period"), s.get("shiftNumber"),
                    s.get("startTime"), s.get("endTime"),
                    mmss_to_sec(s.get("startTime")), mmss_to_sec(s.get("endTime")),
                ])

    shift_rows = merge_overlapping_shifts(shift_rows)
    out = os.path.join(DATA, "tables", season)
    write_gz_csv(os.path.join(out, "games.csv.gz"),
                 ["game_id", "date", "game_type", "home", "away", "home_score",
                  "away_score", "decided_in", "venue"], games_rows)
    write_gz_csv(os.path.join(out, "events.csv.gz"), EVENT_COLS, event_rows)
    write_gz_csv(os.path.join(out, "shifts.csv.gz"),
                 ["game_id", "player_id", "player", "team", "period", "shift_number",
                  "start", "end", "start_sec", "end_sec"], shift_rows)
    write_gz_csv(os.path.join(out, "players.csv.gz"),
                 ["player_id", "player", "team", "position", "number"],
                 sorted(player_rows.values(), key=lambda r: r[0]))
    print(f"tables: {len(games_rows)} games, {len(event_rows)} events, "
          f"{len(shift_rows)} shifts, {len(player_rows)} players")


# ---------------------------------------------------------------- main

def main():
    today = dt.date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=current_season(today))
    ap.add_argument("--start", help="first date to scan (default: Sept 1 of season)")
    ap.add_argument("--end", help="last date to scan (default: today)")
    ap.add_argument("--tables-only", action="store_true")
    ap.add_argument("--skip-tables", action="store_true", help="download only (backfill chunks)")
    a = ap.parse_args()

    if not a.tables_only:
        start = dt.date.fromisoformat(a.start) if a.start else dt.date(int(a.season[:4]), 9, 1)
        season_end = dt.date(int(a.season[4:]), 8, 31)
        end = min(dt.date.fromisoformat(a.end) if a.end else today, season_end)
        games = finished_games(start, end, a.season)
        detail = a.season == current_season(today)   # game-page detail only for the live season
        todo = [g for gid, g in sorted(games.items()) if needs_work(a.season, gid, detail)]
        print(f"{len(games)} finished games found, {len(todo)} need downloading")
        for i, g in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {g['game_id']} ({g['date']})")
            try:
                download_game(a.season, g["game_id"], g["date"], detail)
            except RuntimeError as e:
                print(f"  ! skipped {g['game_id']}: {e}", file=sys.stderr)

    if not a.skip_tables:
        build_tables(a.season)


if __name__ == "__main__":
    main()
