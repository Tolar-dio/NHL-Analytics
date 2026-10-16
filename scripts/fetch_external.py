"""Supplementary data sources, run after fetch.py.

MoneyPuck shot data (free for non-commercial use; credit MoneyPuck.com):
    Downloads the season shot file, splits it into one gzipped CSV per game
    under data/external/moneypuck/<season>/, and only writes games it doesn't
    already have. Splitting keeps git history small: the season file changes
    every night, but a finished game's shots never do.

NHL Edge tracking (league puck/player tracking, season-level):
    Skating speed, bursts, distance, shot speed, zone time, shot locations
    for every skater who has played. Refreshed weekly into
    data/external/edge/<season>/skaters.csv.gz (+ raw JSON).
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import DATA, HEADERS, current_season, get_json, write_gz_csv  # noqa: E402

EDGE_REFRESH_DAYS = 5


# ---------------------------------------------------------------- MoneyPuck

def fetch_moneypuck(season):
    year = int(season[:4])
    url = f"https://peter-tanner.com/moneypuck/downloads/shots_{year}.zip"
    out = os.path.join(DATA, "external", "moneypuck", season)
    os.makedirs(out, exist_ok=True)

    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    zf = zipfile.ZipFile(io.BytesIO(blob))
    name = next(n for n in zf.namelist() if n.endswith(".csv"))
    with zf.open(name) as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
        header = next(reader)
        gcol = header.index("game_id")
        by_game = {}
        for row in reader:
            by_game.setdefault(row[gcol], []).append(row)

    # MoneyPuck game_id is the short form (20107); NHL's is 2026020107
    written = 0
    for short, rows in by_game.items():
        full = f"{year}{int(short):06d}"
        path = os.path.join(out, f"{full}.csv.gz")
        if os.path.exists(path):
            continue
        write_gz_csv(path, header, rows)
        written += 1
    print(f"MoneyPuck: {len(by_game)} games in file, {written} new")


# ---------------------------------------------------------------- NHL Edge
# Public EDGE endpoints on api-web.nhle.com, per player: skater-detail (speed, distance, zone time),
# skater-shot-location-detail (17 shot areas), skater-shot-speed-detail (10 hardest shots, with game and
# clock), skater-skating-distance-detail (last 10 games, by strength) and goalie-detail (save % by area).
# A rotation refreshes each player every EDGE_REFRESH_DAYS days, at most EDGE_MAX players a night, so the
# load is spread out (about 4 calls per skater, half a second apart). The last-10 distance lists are
# merged into a running per-game log, the only way to build per-game EDGE history from the public API.

EDGE_MAX = int(os.environ.get("EDGE_MAX", "260"))


def pct(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return ""
        obj = obj.get(k)
    return "" if obj is None else obj


def read_gz_csv(path):
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def game_of(link):
    return (link or "").rstrip("/").split("/")[-1]


def skater_row(pid, p, j):
    zt = j.get("zoneTimeDetails") or {}
    sog = {s.get("locationCode"): s for s in j.get("sogSummary") or []}
    return [pid, p["player"], p["team"], p["position"],
            pct(j, "player", "gamesPlayed"),
            pct(j, "skatingSpeed", "speedMax", "imperial"), pct(j, "skatingSpeed", "speedMax", "percentile"),
            pct(j, "skatingSpeed", "burstsOver20", "value"), pct(j, "skatingSpeed", "burstsOver20", "percentile"),
            pct(j, "totalDistanceSkated", "imperial"), pct(j, "totalDistanceSkated", "percentile"),
            pct(j, "topShotSpeed", "imperial"), pct(j, "topShotSpeed", "percentile"),
            zt.get("offensiveZonePctg", ""), zt.get("offensiveZoneEvPctg", ""),
            zt.get("neutralZonePctg", ""), zt.get("defensiveZonePctg", ""),
            pct(sog.get("high"), "shots"), pct(sog.get("mid"), "shots"), pct(sog.get("long"), "shots")]


SKATER_COLS = ["player_id", "player", "team", "position", "gp", "max_speed_mph", "max_speed_pctile", "bursts_20mph",
               "bursts_pctile", "distance_miles", "distance_pctile", "top_shot_mph", "top_shot_pctile", "oz_time_pct",
               "oz_time_ev_pct", "nz_time_pct", "dz_time_pct", "sog_high_danger", "sog_mid", "sog_long"]
AREA_COLS = ["player_id", "area", "sog", "goals", "sh_pct", "sog_pctile", "goals_pctile", "sh_pctile"]
HARD_COLS = ["player_id", "game_id", "date", "period", "time_in_period", "mph"]
DIST_COLS = ["player_id", "game_id", "date", "miles_all", "toi_all", "miles_ev", "toi_ev", "miles_pp", "toi_pp",
             "miles_pk", "toi_pk"]
GOALIE_COLS = ["goalie_id", "area", "shots_against", "saves", "goals_against", "save_pct", "save_pct_pctile", "league_save_pct"]


def fetch_edge(season, force=False):
    out = os.path.join(DATA, "external", "edge", season)
    os.makedirs(out, exist_ok=True)
    state_path = os.path.join(out, "fetched.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    today = dt.date.today()
    due = lambda pid: force or pid not in state or (today - dt.date.fromisoformat(state[pid])).days >= EDGE_REFRESH_DAYS
    with gzip.open(os.path.join(DATA, "tables", season, "players.csv.gz"), "rt") as f:
        roster = list(csv.DictReader(f))
    only = set(filter(None, os.environ.get("EDGE_ONLY", "").split(",")))   # debugging: refresh just these ids
    todo = sorted((p for p in roster if due(p["player_id"]) and (not only or p["player_id"] in only)),
                  key=lambda p: state.get(p["player_id"], ""))[:EDGE_MAX]
    if not todo:
        print("Edge: everyone refreshed recently, skipping")
        return

    # existing tables, keyed so a refreshed player's rows replace his old ones
    sk = {r["player_id"]: [r.get(c, "") for c in SKATER_COLS] for r in read_gz_csv(os.path.join(out, "skaters.csv.gz"))}
    areas = [r for r in read_gz_csv(os.path.join(out, "shot_areas.csv.gz"))]
    hard = [r for r in read_gz_csv(os.path.join(out, "hard_shots.csv.gz"))]
    dist = {(r["player_id"], r["game_id"]): r for r in read_gz_csv(os.path.join(out, "distance_games.csv.gz"))}
    gareas = [r for r in read_gz_csv(os.path.join(out, "goalie_areas.csv.gz"))]
    raw_path = os.path.join(out, "skaters_raw.json.gz")
    raw = json.load(gzip.open(raw_path, "rt")) if os.path.exists(raw_path) else {}
    base = "https://api-web.nhle.com/v1/edge"
    done = 0
    for i, p in enumerate(todo, 1):
        pid = p["player_id"]
        try:
            if p["position"] == "G":
                j = get_json(f"{base}/goalie-detail/{pid}/{season}/2", tries=2)
                gareas = [r for r in gareas if r["goalie_id"] != pid]
                for a in j.get("shotLocationDetails") or []:
                    if a.get("savePctg") is not None:
                        gareas.append(dict(goalie_id=pid, area=a["area"], shots_against="", saves=a.get("saves"),
                                           goals_against="", save_pct=a.get("savePctg"), save_pct_pctile=a.get("savePctgPercentile"),
                                           league_save_pct=""))
                for a in j.get("shotLocationSummary") or []:
                    gareas.append(dict(goalie_id=pid, area="all:" + a.get("locationCode", ""), shots_against="",
                                       saves=a.get("saves"), goals_against=a.get("goalsAgainst"), save_pct=a.get("savePctg"),
                                       save_pct_pctile=a.get("savePctgPercentile"), league_save_pct=a.get("savePctgLeagueAvg")))
            else:
                j = get_json(f"{base}/skater-detail/{pid}/{season}/2", tries=2)
                raw[pid] = j
                sk[pid] = skater_row(pid, p, j)
                time.sleep(0.4)
                loc = get_json(f"{base}/skater-shot-location-detail/{pid}/{season}/2", tries=2)
                areas = [r for r in areas if r["player_id"] != pid]
                for a in loc.get("shotLocationDetails") or []:
                    if a.get("sog"):
                        areas.append(dict(player_id=pid, area=a["area"], sog=a["sog"], goals=a.get("goals"),
                                          sh_pct=a.get("shootingPctg"), sog_pctile=a.get("sogPercentile"),
                                          goals_pctile=a.get("goalsPercentile"), sh_pctile=a.get("shootingPctgPercentile")))
                time.sleep(0.4)
                spd = get_json(f"{base}/skater-shot-speed-detail/{pid}/{season}/2", tries=2)
                hard = [r for r in hard if r["player_id"] != pid]
                for h in spd.get("hardestShots") or []:
                    hard.append(dict(player_id=pid, game_id=game_of(h.get("gameCenterLink")), date=h.get("gameDate"),
                                     period=(h.get("periodDescriptor") or {}).get("number"), time_in_period=h.get("timeInPeriod"),
                                     mph=(h.get("shotSpeed") or {}).get("imperial")))
                time.sleep(0.4)
                dd = get_json(f"{base}/skater-skating-distance-detail/{pid}/{season}/2", tries=2)
                for g in dd.get("skatingDistanceLast10") or []:
                    gid = game_of(g.get("gameCenterLink"))
                    v = lambda k: (g.get(k) or {}).get("imperial") if isinstance(g.get(k), dict) else g.get(k)
                    dist[(pid, gid)] = dict(player_id=pid, game_id=gid, date=g.get("gameDate"),
                                            miles_all=v("distanceSkatedAll"), toi_all=g.get("toiAll"),
                                            miles_ev=v("distanceSkatedEven"), toi_ev=g.get("toiEven"),
                                            miles_pp=v("distanceSkatedPP"), toi_pp=g.get("toiPP"),
                                            miles_pk=v("distanceSkatedPK"), toi_pk=g.get("toiPK"))
            state[pid] = today.isoformat()
            done += 1
        except RuntimeError:
            continue
        if i % 50 == 0:
            print(f"  Edge: {i}/{len(todo)}")
        time.sleep(0.4)

    rows = lambda recs, cols: [[r.get(c, "") for c in cols] for r in recs]
    write_gz_csv(os.path.join(out, "skaters.csv.gz"), SKATER_COLS, [sk[k] for k in sorted(sk)])
    write_gz_csv(os.path.join(out, "shot_areas.csv.gz"), AREA_COLS, rows(sorted(areas, key=lambda r: (r["player_id"], r["area"])), AREA_COLS))
    write_gz_csv(os.path.join(out, "hard_shots.csv.gz"), HARD_COLS, rows(sorted(hard, key=lambda r: (r["player_id"], -float(r["mph"] or 0))), HARD_COLS))
    write_gz_csv(os.path.join(out, "distance_games.csv.gz"), DIST_COLS, rows(sorted(dist.values(), key=lambda r: (r["player_id"], r["date"] or "")), DIST_COLS))
    write_gz_csv(os.path.join(out, "goalie_areas.csv.gz"), GOALIE_COLS, rows(sorted(gareas, key=lambda r: (r["goalie_id"], r["area"])), GOALIE_COLS))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(json.dumps(raw, separators=(",", ":"), sort_keys=True).encode())
    with open(raw_path, "wb") as f:
        f.write(buf.getvalue())
    with open(state_path, "w") as f:
        json.dump(state, f, sort_keys=True, indent=0)
    with open(os.path.join(out, "updated.txt"), "w") as f:
        f.write(today.isoformat())
    left = sum(1 for p in roster if due(p["player_id"]))
    print(f"Edge: refreshed {done} of {len(todo)} due players; {left} still due; per-game distance rows {len(dist)}")


# ---------------------------------------------------------------- player bios (NHL player landing)
# Birthplace, birth date, draft, size, the NHL teams each player has played for, and career totals THROUGH
# LAST SEASON (this season comes from our own tables, so milestones stay current without refetching).
# Fetched once per player per season and refreshed every BIO_REFRESH_DAYS, at most BIO_MAX a night.

BIO_REFRESH_DAYS = 45
BIO_MAX = int(os.environ.get("BIO_MAX", "800"))   # the first run fetches everyone (~5 min); after that only new players and 45-day refreshes
TEAM_BY_NAME = {"Ducks": "ANA", "Bruins": "BOS", "Sabres": "BUF", "Flames": "CGY", "Hurricanes": "CAR", "Blackhawks": "CHI",
                "Avalanche": "COL", "Blue Jackets": "CBJ", "Stars": "DAL", "Red Wings": "DET", "Oilers": "EDM", "Panthers": "FLA",
                "Kings": "LAK", "Wild": "MIN", "Canadiens": "MTL", "Predators": "NSH", "Devils": "NJD", "Islanders": "NYI",
                "Rangers": "NYR", "Senators": "OTT", "Flyers": "PHI", "Penguins": "PIT", "Sharks": "SJS", "Kraken": "SEA",
                "Blues": "STL", "Lightning": "TBL", "Maple Leafs": "TOR", "Canucks": "VAN", "Golden Knights": "VGK",
                "Capitals": "WSH", "Jets": "WPG", "Utah Hockey Club": "UTA", "Hockey Club": "UTA", "Mammoth": "UTA",
                "Utah Mammoth": "UTA", "Coyotes": "ARI"}
CAREER_KEYS = ["gamesPlayed", "goals", "assists", "points", "wins", "shutouts"]


def bio_of(j, season):
    nhl = [x for x in j.get("seasonTotals") or [] if x.get("leagueAbbrev") == "NHL" and x.get("gameTypeId") == 2]
    cur = [x for x in nhl if str(x.get("season")) == season]
    car = ((j.get("careerTotals") or {}).get("regularSeason") or {})
    prev = {k: (car.get(k) or 0) - sum(x.get(k) or 0 for x in cur) for k in CAREER_KEYS if k in car}
    teams = []
    for x in nhl:
        name = (x.get("teamCommonName") or {}).get("default") or (x.get("teamName") or {}).get("default", "")
        ab = TEAM_BY_NAME.get(name) or next((v for k, v in TEAM_BY_NAME.items() if name.endswith(k)), None)
        if ab:
            teams.append([int(x["season"]), ab, x.get("gamesPlayed") or 0])
    dd = j.get("draftDetails") or {}
    txt = lambda o: (o or {}).get("default") if isinstance(o, dict) else o
    return dict(name=f'{txt(j.get("firstName"))} {txt(j.get("lastName"))}', pos=j.get("position"), birth_date=j.get("birthDate"),
                birth_city=txt(j.get("birthCity")), birth_state=txt(j.get("birthStateProvince")), birth_country=j.get("birthCountry"),
                height_in=j.get("heightInInches"), weight_lb=j.get("weightInPounds"), shoots=j.get("shootsCatches"),
                draft=dict(year=dd.get("year"), team=dd.get("teamAbbrev"), round=dd.get("round"), overall=dd.get("overallPick")) if dd else None,
                nhl_teams=teams, career_prev=prev)


def fetch_bios(season):
    out = os.path.join(DATA, "external", "bios", season)
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "bios.json.gz")
    bios = json.load(gzip.open(path, "rt")) if os.path.exists(path) else {}
    today = dt.date.today()
    with gzip.open(os.path.join(DATA, "tables", season, "players.csv.gz"), "rt") as f:
        roster = list(csv.DictReader(f))
    due = [p for p in roster if p["player_id"] not in bios or
           (today - dt.date.fromisoformat(bios[p["player_id"]].get("fetched", "2000-01-01"))).days >= BIO_REFRESH_DAYS]
    due.sort(key=lambda p: bios.get(p["player_id"], {}).get("fetched", ""))
    done = 0
    for p in due[:BIO_MAX]:
        try:
            j = get_json(f"https://api-web.nhle.com/v1/player/{p['player_id']}/landing", tries=2)
        except RuntimeError:
            continue
        b = bio_of(j, season)
        b["fetched"] = today.isoformat()
        bios[p["player_id"]] = b
        done += 1
        time.sleep(0.4)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(json.dumps(bios, separators=(",", ":"), sort_keys=True).encode())
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print(f"Bios: fetched {done}; {len(bios)} on file; {max(0, len(due) - done)} still due")


# ---------------------------------------------------------------- MoneyPuck season summaries

def fetch_moneypuck_summary(season):
    """Season-level skater/goalie/team/line tables (all situations splits).

    Saved gzipped to data/external/moneypuck_summary/<season>/<type>.csv.gz.
    Rewritten only when content changes (write_gz_csv compares bytes).
    """
    year = int(season[:4])
    out = os.path.join(DATA, "external", "moneypuck_summary", season)
    for kind in ("skaters", "goalies", "teams", "lines"):
        url = f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{year}/regular/{kind}.csv"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=120) as r:
            text = r.read().decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 2:
            raise RuntimeError(f"empty {kind} summary")
        write_gz_csv(os.path.join(out, f"{kind}.csv.gz"), rows[0], rows[1:])
        print(f"MoneyPuck summary {kind}: {len(rows) - 1} rows")
        time.sleep(1.0)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=current_season(dt.date.today()))
    ap.add_argument("--force-edge", action="store_true")
    ap.add_argument("--skip-edge", action="store_true")
    a = ap.parse_args()
    jobs = [("MoneyPuck shots", lambda: fetch_moneypuck(a.season)),
            ("MoneyPuck summaries", lambda: fetch_moneypuck_summary(a.season))]
    if not a.skip_edge:
        jobs.append(("Edge", lambda: fetch_edge(a.season, a.force_edge)))
    jobs.append(("Bios", lambda: fetch_bios(a.season)))
    for name, fn in jobs:
        try:
            fn()
        except Exception as e:  # one source failing must not block the other
            print(f"! {name} failed: {e!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
