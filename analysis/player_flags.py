"""Simple xG model + early-season player flags.

xG: logistic regression on unblocked shots (distance, angle, shot type,
rebound, rush, strength state), trained on this season's games with
5-fold out-of-fold predictions so no shot is scored by a model that saw it.

Outputs skater and goalie tables to analysis/output/.
"""
import glob, gzip, json, os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import roc_auc_score, log_loss

SEASON = "20262027"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "data", "tables", SEASON)
OUT = os.path.join(ROOT, "analysis", "output")
os.makedirs(OUT, exist_ok=True)

ev = pd.read_csv(os.path.join(T, "events.csv.gz"))
ev = ev[ev.period_type != "SO"].sort_values(["game_id", "sort_order"]).reset_index(drop=True)
ev["situation_code"] = ev.situation_code.astype(str).str.zfill(4)

# ---- context features from the previous event in the same game
prev = ev.groupby("game_id").shift(1)
ev["dt_prev"] = ev.game_seconds - prev.game_seconds
ev["prev_event"] = prev.event
ev["prev_team"] = prev.team
ev["prev_zone"] = prev.zone

UNBLOCKED = ["shot-on-goal", "missed-shot", "goal"]
s = ev[ev.event.isin(UNBLOCKED)].copy()

# ---- shooting direction: which net is the shooter attacking?
is_home = s.team == s.home_team
side = s.home_defending_side
# home defends left -> home attacks the right net (+89); flips for away
attack_right = np.where(side.isin(["left", "right"]),
                        np.where(is_home, side == "left", side == "right"),
                        s.x >= 0)  # fallback: nearer net
net_x = np.where(attack_right, 89.0, -89.0)
s["dist"] = np.hypot(net_x - s.x, s.y)
s["angle"] = np.degrees(np.arctan2(np.abs(s.y), np.abs(net_x - s.x)))

# strength from shooter's perspective; code = away G, away skaters, home skaters, home G
c = s.situation_code
away_sk, home_sk = c.str[1].astype(int), c.str[2].astype(int)
own = np.where(is_home, home_sk, away_sk)
opp = np.where(is_home, away_sk, home_sk)
opp_goalie_in = np.where(is_home, c.str[0], c.str[3]) == "1"
s["state"] = np.select([own > opp, own < opp], ["PP", "SH"], "EV")
s = s[opp_goalie_in]  # drop empty-net shots: they'd distort the model

s["rebound"] = ((s.prev_event.isin(UNBLOCKED + ["blocked-shot"])) & (s.dt_prev <= 3)).astype(int)
s["rush"] = ((s.dt_prev <= 4) & (s.prev_zone.isin(["N", "D"])) &
             ~s.prev_event.isin(["faceoff", "stoppage"])).astype(int)
s["goal"] = (s.event == "goal").astype(int)
s["shot_type"] = s.shot_type.fillna("unknown")

X = pd.get_dummies(pd.DataFrame({
    "dist": s.dist, "log_dist": np.log1p(s.dist), "angle": s.angle,
    "rebound": s.rebound, "rush": s.rush,
    "shot_type": s.shot_type, "state": s.state}), columns=["shot_type", "state"], dtype=float)
X["dist_x_angle"] = X.dist * X.angle
X = (X - X.mean()) / X.std().replace(0, 1)

model = LogisticRegression(max_iter=2000, C=1.0)
s["xg"] = cross_val_predict(model, X, s.goal, cv=5, method="predict_proba")[:, 1]
print(f"xG model: {len(s)} unblocked shots, {s.goal.sum()} goals, "
      f"predicted {s.xg.sum():.1f}, AUC {roc_auc_score(s.goal, s.xg):.3f}, "
      f"log loss {log_loss(s.goal, s.xg):.4f}")
s.to_csv(os.path.join(OUT, "shots_with_xg.csv.gz"), index=False)

# ---- TOI and games from boxscores
rows = []
for f in glob.glob(os.path.join(ROOT, "data", "raw", SEASON, "*", "boxscore.json.gz")):
    b = json.load(gzip.open(f, "rt"))
    for side_ in ("homeTeam", "awayTeam"):
        team = b[side_]["abbrev"]
        for grp in ("forwards", "defense", "goalies"):
            for p in b["playerByGameStats"][side_][grp]:
                m, sec = (p.get("toi") or "0:00").split(":")
                rows.append({"player_id": p["playerId"], "team": team, "pos": p.get("position"),
                             "toi": int(m) + int(sec) / 60, "game_id": b["id"],
                             "is_goalie": grp == "goalies"})
box = pd.DataFrame(rows)
box = box[box.toi > 0]
players = pd.read_csv(os.path.join(T, "players.csv.gz"))[["player_id", "player"]].drop_duplicates("player_id")

# ---- skaters
sk = box[~box.is_goalie].groupby("player_id").agg(
    team=("team", "last"), pos=("pos", "last"), gp=("game_id", "nunique"), toi=("toi", "sum"))
ind = s.groupby("player1_id").agg(shots=("goal", "size"), goals=("goal", "sum"), ixg=("xg", "sum"))
ev_s = s[s.state == "EV"].groupby("player1_id").agg(ev_ixg=("xg", "sum"))
goals = ev[ev.event == "goal"]
a = pd.concat([goals.player2_id, goals.player3_id]).dropna().astype(int).value_counts().rename("assists")
sk = sk.join(ind).join(ev_s).join(a).fillna(0).join(players.set_index("player_id"))
sk["points"] = sk.goals + sk.assists
sk["g_minus_xg"] = sk.goals - sk.ixg
sk["ixg_60"] = sk.ixg / sk.toi * 60
sk["shots_60"] = sk.shots / sk.toi * 60
sk["sh_pct"] = np.where(sk.shots > 0, sk.goals / sk.shots, np.nan)
sk = sk.round(3)
sk.to_csv(os.path.join(OUT, "skaters.csv"))

# ---- goalies: shots faced while in net
gl = s.dropna(subset=["goalie_id"]).groupby("goalie_id").agg(
    shots_faced=("goal", "size"), ga=("goal", "sum"), xga=("xg", "sum"))
gbox = box[box.is_goalie].groupby("player_id").agg(team=("team", "last"), gp=("game_id", "nunique"), toi=("toi", "sum"))
gl = gl.join(gbox).join(players.set_index("player_id"))
gl["gsax"] = gl.xga - gl.ga
gl["gsax_60"] = gl.gsax / gl.toi * 60
gl.round(3).to_csv(os.path.join(OUT, "goalies.csv"))
print("wrote", OUT)
