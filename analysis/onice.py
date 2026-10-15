"""5v5 on-ice stats per skater: who was on the ice for every shot.

xG source: MoneyPuck's xGoal where the shot matches (credit MoneyPuck.com),
otherwise our own model from player_flags.py (run that first).

Outputs analysis/output/onice_5v5.csv with, per skater:
  TOI, CF/CA (shot attempts), xGF/xGA, GF/GA, the % versions, and
  "relative" xGF% (on-ice minus the team's xGF% with him off the ice).
"""
import glob, os
import numpy as np
import pandas as pd

SEASON = "20262027"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "data", "tables", SEASON)
OUT = os.path.join(ROOT, "analysis", "output")

ev = pd.read_csv(os.path.join(T, "events.csv.gz"))
ev["situation_code"] = ev.situation_code.astype(str).str.zfill(4)
ev = ev[(ev.period_type != "SO") & (ev.situation_code == "1551")]
att = ev[ev.event.isin(["shot-on-goal", "missed-shot", "goal", "blocked-shot"])].copy()
# note: the NHL API already records blocked shots under the SHOOTING team
att["period_sec"] = att.game_seconds - (att.period.clip(upper=4) - 1) * 1200

# ---- xG per unblocked shot: MoneyPuck first, ours as fallback
ours = pd.read_csv(os.path.join(OUT, "shots_with_xg.csv.gz"))[["game_id", "event_id", "xg"]]
att = att.merge(ours, on=["game_id", "event_id"], how="left")
mp_files = glob.glob(os.path.join(ROOT, "data", "external", "moneypuck", SEASON, "*.csv.gz"))
if mp_files:
    mp = pd.concat([pd.read_csv(f, usecols=["game_id", "time", "shooterPlayerId", "xGoal", "period"])
                    for f in mp_files])
    mp = mp[mp.period <= 4]
    mp["game_id"] = int(SEASON[:4]) * 1000000 + mp.game_id
    mp = mp.rename(columns={"time": "game_seconds", "shooterPlayerId": "player1_id"})
    mp = mp.drop_duplicates(["game_id", "game_seconds", "player1_id"])
    att = att.merge(mp[["game_id", "game_seconds", "player1_id", "xGoal"]],
                    on=["game_id", "game_seconds", "player1_id"], how="left")
    att["xg"] = att.xGoal.fillna(att.xg)
att["xg"] = att.xg.fillna(0)  # blocked shots carry no xG
att["is_goal"] = (att.event == "goal").astype(int)
print(f"5v5 attempts: {len(att)}, xG from MoneyPuck on "
      f"{att.get('xGoal', pd.Series(dtype=float)).notna().sum()} shots")

# ---- who was on the ice: start < t <= end (a player changing on at t isn't credited)
sh = pd.read_csv(os.path.join(T, "shifts.csv.gz")).dropna(subset=["player_id"])
pos = pd.read_csv(os.path.join(T, "players.csv.gz")).drop_duplicates("player_id").set_index("player_id")
sh = sh[sh.player_id.map(pos.position) != "G"]
sh["player_id"] = sh.player_id.astype(int)

rows = []
for (gid, per), shots in att.groupby(["game_id", "period"]):
    on = sh[(sh.game_id == gid) & (sh.period == per)]
    if on.empty:
        continue
    for _, s in shots.iterrows():
        cur = on[(on.start_sec < s.period_sec) & (on.end_sec >= s.period_sec)]
        for _, p in cur.iterrows():
            f = p.team == s.team
            rows.append((p.player_id, p.team, gid, f, s.event != "blocked-shot", s.xg, s.is_goal))
oi = pd.DataFrame(rows, columns=["player_id", "team", "game_id", "for_", "unblocked", "xg", "goal"])

agg = oi.groupby(["player_id", "for_"]).agg(C=("xg", "size"), xG=("xg", "sum"), G=("goal", "sum")).unstack(fill_value=0)
agg.columns = [f"{m}{'F' if f else 'A'}" for m, f in agg.columns]

# ---- 5v5 TOI from shifts x 5v5 time windows is complex; use share of team
# 5v5 attempts as a proxy check, and real all-situations TOI from shifts
sh["dur"] = sh.end_sec - sh.start_sec
toi = sh.groupby("player_id").agg(toi_all=("dur", "sum"), gp=("game_id", "nunique"), team=("team", "last"))
toi["toi_all"] /= 60

df = toi.join(agg, how="inner").join(pos[["player", "position"]])
for m in ("C", "xG", "G"):
    df[f"{m}F%"] = 100 * df[f"{m}F"] / (df[f"{m}F"] + df[f"{m}A"]).replace(0, np.nan)

# relative xGF%: team's 5v5 totals minus this player's on-ice = team without him
team_tot = att.assign(home=att.home_team).groupby("team").agg(xgf=("xg", "sum"))
team_xga = att.groupby(np.where(att.team == att.home_team, att.away_team, att.home_team)).xg.sum()
df["team_xGF"] = df.team.map(team_tot.xgf)
df["team_xGA"] = df.team.map(team_xga)
off_f, off_a = df.team_xGF - df.xGF, df.team_xGA - df.xGA
df["xGF%_off"] = 100 * off_f / (off_f + off_a)
df["xGF%_rel"] = df["xGF%"] - df["xGF%_off"]
df = df.drop(columns=["team_xGF", "team_xGA"]).round(2)
df.to_csv(os.path.join(OUT, "onice_5v5.csv"))
print("wrote onice_5v5.csv,", len(df), "skaters")
