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

EDGE_REFRESH_DAYS = 6


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

def edge_due(out):
    stamp = os.path.join(out, "updated.txt")
    if not os.path.exists(stamp):
        return True
    last = dt.date.fromisoformat(open(stamp).read().strip())
    return (dt.date.today() - last).days >= EDGE_REFRESH_DAYS


def pct(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return ""
        obj = obj.get(k)
    return "" if obj is None else obj


def fetch_edge(season, force=False):
    out = os.path.join(DATA, "external", "edge", season)
    if not force and not edge_due(out):
        print("Edge: refreshed recently, skipping")
        return
    os.makedirs(out, exist_ok=True)

    players = os.path.join(DATA, "tables", season, "players.csv.gz")
    with gzip.open(players, "rt") as f:
        roster = [r for r in csv.DictReader(f) if r["position"] != "G"]

    raw, rows = {}, []
    for i, p in enumerate(roster, 1):
        pid = p["player_id"]
        try:
            j = get_json(f"https://api-web.nhle.com/v1/edge/skater-detail/{pid}/{season}/2", tries=2)
        except RuntimeError:
            continue
        raw[pid] = j
        zt = j.get("zoneTimeDetails") or {}
        sog = {s.get("locationCode"): s for s in j.get("sogSummary") or []}
        rows.append([
            pid, p["player"], p["team"], p["position"],
            pct(j, "player", "gamesPlayed"),
            pct(j, "skatingSpeed", "speedMax", "imperial"),
            pct(j, "skatingSpeed", "speedMax", "percentile"),
            pct(j, "skatingSpeed", "burstsOver20", "value"),
            pct(j, "skatingSpeed", "burstsOver20", "percentile"),
            pct(j, "totalDistanceSkated", "imperial"),
            pct(j, "totalDistanceSkated", "percentile"),
            pct(j, "topShotSpeed", "imperial"),
            pct(j, "topShotSpeed", "percentile"),
            zt.get("offensiveZonePctg", ""), zt.get("offensiveZoneEvPctg", ""),
            zt.get("neutralZonePctg", ""), zt.get("defensiveZonePctg", ""),
            pct(sog.get("high"), "shots"), pct(sog.get("mid"), "shots"),
            pct(sog.get("long"), "shots"),
        ])
        if i % 100 == 0:
            print(f"  Edge: {i}/{len(roster)}")
        time.sleep(0.5)

    write_gz_csv(os.path.join(out, "skaters.csv.gz"), [
        "player_id", "player", "team", "position", "gp",
        "max_speed_mph", "max_speed_pctile", "bursts_20mph", "bursts_pctile",
        "distance_miles", "distance_pctile", "top_shot_mph", "top_shot_pctile",
        "oz_time_pct", "oz_time_ev_pct", "nz_time_pct", "dz_time_pct",
        "sog_high_danger", "sog_mid", "sog_long"], rows)
    with gzip.open(os.path.join(out, "skaters_raw.json.gz"), "wt") as f:
        json.dump(raw, f, separators=(",", ":"))
    with open(os.path.join(out, "updated.txt"), "w") as f:
        f.write(dt.date.today().isoformat())
    print(f"Edge: {len(rows)} skaters")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=current_season(dt.date.today()))
    ap.add_argument("--force-edge", action="store_true")
    a = ap.parse_args()
    for name, fn in (("MoneyPuck", lambda: fetch_moneypuck(a.season)),
                     ("Edge", lambda: fetch_edge(a.season, a.force_edge))):
        try:
            fn()
        except Exception as e:  # one source failing must not block the other
            print(f"! {name} failed: {e!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
