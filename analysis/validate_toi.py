"""Check our shift-derived ice time against the NHL's official time-on-ice report (stats REST API).

On-ice attribution (who was on for each shot and goal) comes from shifts.csv, so a player whose shift
total drifts from the official TOI has wrong on-ice numbers. Prints the worst gaps and a GitHub
warning when any regular is off by more than 30 seconds a game. Read-only: writes nothing.

    python analysis/validate_toi.py [season]
"""
import json, os, sys, urllib.request
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = ("https://api.nhle.com/stats/rest/en/skater/timeonice?isAggregate=false&isGame=false&limit=-1"
       "&cayenneExp=seasonId={s}%20and%20gameTypeId=2")


def main(season):
    req = urllib.request.Request(URL.format(s=season), headers={"User-Agent": "nhl-analytics-personal-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        off = pd.DataFrame(json.load(r)["data"])[["playerId", "skaterFullName", "gamesPlayed", "timeOnIce"]]
    games = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "games.csv.gz"))
    reg = set(games[games.game_type == "regular"].game_id)
    sh = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "shifts.csv.gz"))
    sh = sh[sh.game_id.isin(reg)]
    ours = sh.assign(sec=sh.end_sec - sh.start_sec).groupby("player_id").sec.sum()
    j = off.set_index("playerId").join(ours.rename("ours"), how="inner")
    j["gap_pg"] = (j.ours - j.timeOnIce) / j.gamesPlayed.clip(lower=1)
    bad = j[(j.gamesPlayed >= 3) & (j.gap_pg.abs() > 30)].sort_values("gap_pg", key=abs, ascending=False)
    print(f"TOI check {season}: {len(j)} skaters compared; median gap {j.gap_pg.abs().median():.1f} s a game; "
          f"{len(bad)} off by more than 30 s a game")
    for x in bad.head(10).itertuples():
        print(f"  {x.skaterFullName}: ours {x.ours / 60:.1f} min vs official {x.timeOnIce / 60:.1f} min over {x.gamesPlayed} games")
    if len(bad):
        print(f"::warning::{len(bad)} skaters' shift-derived TOI is off the official report by >30 s a game")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "20262027")
