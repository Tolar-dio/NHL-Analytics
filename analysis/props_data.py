"""Per-game building blocks for prop models.

Builds three tables in analysis/output/<season>/  (usage: python analysis/props_data.py 20252026):
  player_games.csv  one row per skater per game: TOI, individual xG/goals/assists,
                    on-ice (all situations) xGF/xGA/GF/GA, on-ice PP xGF, team PP xGF
  team_games.csv    one row per team per game: xGF, xGA, GF, GA, PP xGF
  goalie_games.csv  one row per goalie per game: TOI, xGA faced, GA, starter flag

xG source: MoneyPuck xGoal where the shot matches (credit MoneyPuck.com),
our own model otherwise (run analysis/player_flags.py first).
Shootouts excluded. Empty-net shots and goals are kept for skaters.
"""
import glob, gzip, json, os, sys
import numpy as np
import pandas as pd

SEASON = sys.argv[1] if len(sys.argv) > 1 else "20262027"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "data", "tables", SEASON)
OUT = os.path.join(ROOT, "analysis", "output", SEASON)
os.makedirs(OUT, exist_ok=True)

games = pd.read_csv(os.path.join(T, "games.csv.gz"))
date_of = games.set_index("game_id").date
type_of = games.set_index("game_id").game_type

ev = pd.read_csv(os.path.join(T, "events.csv.gz"))
ev = ev[(ev.period_type != "SO") & ev.situation_code.notna()].copy()
ev["sc"] = ev.situation_code.astype(int).astype(str).str.zfill(4)

ATT = ["shot-on-goal", "missed-shot", "goal", "blocked-shot"]
s = ev[ev.event.isin(ATT)].copy()   # team = shooting team for all four (verified)
is_home = s.team == s.home_team
own_sk = np.where(is_home, s.sc.str[2], s.sc.str[1]).astype(int)
opp_sk = np.where(is_home, s.sc.str[1], s.sc.str[2]).astype(int)
own_g = np.where(is_home, s.sc.str[3], s.sc.str[0]) == "1"
opp_g = np.where(is_home, s.sc.str[0], s.sc.str[3]) == "1"
s["state"] = np.select([~opp_g, ~own_g, own_sk > opp_sk, own_sk < opp_sk],
                       ["EN", "EA", "PP", "SH"], "EV")
s["opp"] = np.where(is_home, s.away_team, s.home_team)
s["is_goal"] = (s.event == "goal").astype(int)
s["unblocked"] = s.event != "blocked-shot"
s["period_sec"] = s.game_seconds - (s.period.clip(upper=4) - 1) * 1200

# ---- xG: MoneyPuck first, ours as fallback
ours_path = os.path.join(ROOT, "analysis", "output", "shots_with_xg.csv.gz")
if SEASON == "20262027" and os.path.exists(ours_path):
    ours = pd.read_csv(ours_path, usecols=["game_id", "event_id", "xg"])
    s = s.merge(ours, on=["game_id", "event_id"], how="left")
else:
    s["xg"] = np.nan
mp = pd.concat([pd.read_csv(f, usecols=["game_id", "time", "shooterPlayerId", "xGoal", "period"])
                for f in glob.glob(os.path.join(ROOT, "data", "external", "moneypuck", SEASON, "*.csv.gz"))])
mp = mp[mp.period <= 4]
mp["game_id"] = int(SEASON[:4]) * 1000000 + mp.game_id
mp = mp.rename(columns={"time": "game_seconds", "shooterPlayerId": "player1_id"}) \
       .drop_duplicates(["game_id", "game_seconds", "player1_id"])
s = s.merge(mp[["game_id", "game_seconds", "player1_id", "xGoal"]],
            on=["game_id", "game_seconds", "player1_id"], how="left")
s["xg"] = np.where(s.unblocked, s.xGoal.fillna(s.xg), 0.0)
s.loc[s.unblocked & s.xg.isna() & (s.state == "EN"), "xg"] = 0.35
s["xg"] = s.xg.fillna(0.0)
print(f"attempts {len(s)}, unblocked {s.unblocked.sum()}, MoneyPuck xG on {s.xGoal.notna().sum()}")

# ---- boxscore TOI, positions, starters
rows = []
for f in glob.glob(os.path.join(ROOT, "data", "raw", SEASON, "*", "boxscore.json.gz")):
    b = json.load(gzip.open(f, "rt"))
    for side in ("homeTeam", "awayTeam"):
        team = b[side]["abbrev"]
        for grp in ("forwards", "defense", "goalies"):
            for p in b["playerByGameStats"][side][grp]:
                m, sec = (p.get("toi") or "0:00").split(":")
                rows.append({"game_id": b["id"], "player_id": p["playerId"], "team": team,
                             "pos": "G" if grp == "goalies" else ("D" if grp == "defense" else "F"),
                             "toi": int(m) + int(sec) / 60})
box = pd.DataFrame(rows)
box = box[box.toi > 0]

# ---- on-ice attribution (all situations), vectorised per game-period
sh = pd.read_csv(os.path.join(T, "shifts.csv.gz")).dropna(subset=["player_id"])
sh["player_id"] = sh.player_id.astype(int)
gpos = box.drop_duplicates("player_id").set_index("player_id").pos
sh = sh[sh.player_id.map(gpos) != "G"]

pairs = []
sh_groups = dict(tuple(sh.groupby(["game_id", "period"])))
for key, shots in s.groupby(["game_id", "period"]):
    on = sh_groups.get(key)
    if on is None:
        continue
    t = shots.period_sec.values
    m = (on.start_sec.values[:, None] < t[None, :]) & (on.end_sec.values[:, None] >= t[None, :])
    i, j = np.nonzero(m)
    pairs.append(pd.DataFrame({
        "game_id": key[0], "player_id": on.player_id.values[i], "p_team": on.team.values[i],
        "s_team": shots.team.values[j], "xg": shots.xg.values[j], "goal": shots.is_goal.values[j],
        "state": shots.state.values[j]}))
oi = pd.concat(pairs, ignore_index=True)
oi["for_"] = oi.p_team == oi.s_team
oi["xgf"] = np.where(oi.for_, oi.xg, 0.0)
oi["xga"] = np.where(~oi.for_, oi.xg, 0.0)
oi["gf"] = np.where(oi.for_, oi.goal, 0)
oi["ga"] = np.where(~oi.for_, oi.goal, 0)
oi["pp_xgf"] = np.where(oi.for_ & (oi.state == "PP"), oi.xg, 0.0)
on_ice = oi.groupby(["game_id", "player_id"])[["xgf", "xga", "gf", "ga", "pp_xgf"]].sum()

# ---- individual
u = s[s.unblocked]
ind = u.groupby(["game_id", "player1_id"]).agg(ixg=("xg", "sum"), g=("is_goal", "sum"),
                                              sog=("event", lambda x: x.isin(["shot-on-goal", "goal"]).sum()))
ind.index.names = ["game_id", "player_id"]
gl = s[s.is_goal == 1]
a1 = gl.groupby(["game_id", "player2_id"]).size().rename("a1")
a2 = gl.groupby(["game_id", "player3_id"]).size().rename("a2")
a1.index.names = a2.index.names = ["game_id", "player_id"]

# ---- team-game
tg = s.groupby(["game_id", "team"]).agg(xgf=("xg", "sum"), gf=("is_goal", "sum"))
tg_pp = s[s.state == "PP"].groupby(["game_id", "team"]).xg.sum().rename("pp_xgf")
tg = tg.join(tg_pp).fillna(0).reset_index()
opp_map = games.set_index("game_id")[["home", "away"]]
tg["opp"] = np.where(tg.team == tg.game_id.map(opp_map.home), tg.game_id.map(opp_map.away),
                     tg.game_id.map(opp_map.home))
tg = tg.merge(tg[["game_id", "team", "xgf", "gf"]].rename(columns={"team": "opp", "xgf": "xga", "gf": "ga"}),
              on=["game_id", "opp"])
gtoi = box[box.pos == "G"].groupby(["game_id", "team"]).toi.sum().clip(lower=60).rename("toi")
tg = tg.merge(gtoi.reset_index(), on=["game_id", "team"], how="left")
tg["toi"] = tg.toi.fillna(60)
tg["date"] = tg.game_id.map(date_of)
tg["game_type"] = tg.game_id.map(type_of)
tg.to_csv(os.path.join(OUT, "team_games.csv"), index=False)

# ---- goalie-game (non-empty-net shots only)
gs = s[s.unblocked & (s.state != "EN") & s.goalie_id.notna()]
gg = gs.groupby(["game_id", "goalie_id"]).agg(xga=("xg", "sum"), ga=("is_goal", "sum")).reset_index()
gg = gg.rename(columns={"goalie_id": "player_id"})
gb = box[box.pos == "G"].copy()
gb["starter"] = gb.groupby(["game_id", "team"]).toi.rank(ascending=False, method="first") == 1
gg = gb.merge(gg, on=["game_id", "player_id"], how="left").fillna({"xga": 0, "ga": 0})
gg["date"] = gg.game_id.map(date_of)
gg["game_type"] = gg.game_id.map(type_of)
gg.to_csv(os.path.join(OUT, "goalie_games.csv"), index=False)

# ---- player-game
pg = box[box.pos != "G"].set_index(["game_id", "player_id"])
pg = pg.join(on_ice).join(ind).join(a1).join(a2).fillna(0).reset_index()
pg["a"] = pg.a1 + pg.a2
pg["pts"] = pg.g + pg.a
pg = pg.merge(tg[["game_id", "team", "pp_xgf"]].rename(columns={"pp_xgf": "team_pp_xgf"}),
              on=["game_id", "team"], how="left")
pg = pg.merge(tg[["game_id", "team", "opp"]], on=["game_id", "team"], how="left")
pg["date"] = pg.game_id.map(date_of)
pg["game_type"] = pg.game_id.map(type_of)
pg.to_csv(os.path.join(OUT, "player_games.csv"), index=False)

# sanity checks
chk = pg.groupby(["game_id", "team"]).agg(g=("g", "sum")).reset_index().merge(tg[["game_id", "team", "gf"]])
print("player goals == team goals:", (chk.g == chk.gf).mean().round(3))
print("on-ice skaters per goal (should be ~5 for, ~5 against):",
      round(pg.gf.sum() / tg.gf.sum(), 2), round(pg.ga.sum() / tg.ga.sum(), 2))
print(f"player_games {len(pg)}, team_games {len(tg)}, goalie_games {len(gg)}")
