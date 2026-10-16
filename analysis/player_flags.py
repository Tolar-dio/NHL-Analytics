"""Our own xG model + early-season player flags.

xG: logistic regression on unblocked shots (distance, angle, shot type, rebound, rush, strength state, plus
sequence features: time and distance since the previous event, puck movement speed, royal-road crossing,
previous event type and team, shooter's shift time), trained on last season and this one with 5-fold
out-of-fold predictions grouped by game. MoneyPuck's xGoal stays primary; this fills its gaps.

Outputs skater and goalie tables to analysis/output/.
"""
import glob, gzip, json, os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict, GroupKFold
from sklearn.metrics import roc_auc_score, log_loss

SEASON, PREV_SEASON = "20262027", "20252026"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "data", "tables", SEASON)
OUT = os.path.join(ROOT, "analysis", "output")
os.makedirs(OUT, exist_ok=True)

UNBLOCKED = ["shot-on-goal", "missed-shot", "goal"]
PREV_TYPES = ["faceoff", "hit", "giveaway", "takeaway", "blocked-shot", "missed-shot", "shot-on-goal"]


def shots_for(season):
    """Unblocked, non-empty-net shots with location, context and sequence features.

    Sequence features (added Oct 2026, AUC 0.740 -> 0.752 out of fold on 2025-27 shots; MoneyPuck 0.769):
    time since the previous event, how far and how fast the puck moved from it, whether it crossed the
    slot's centre line just before the shot ("royal road", a pass proxy), the previous event's type and
    team, and how long the shooter had been on the ice in his shift."""
    ev = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "events.csv.gz"), low_memory=False)
    ev = ev[ev.period_type != "SO"].sort_values(["game_id", "sort_order"]).reset_index(drop=True)
    ev["situation_code"] = ev.situation_code.astype(str).str.zfill(4)
    prev = ev.groupby("game_id").shift(1)
    s = ev[ev.event.isin(UNBLOCKED)].copy()
    p = prev.loc[s.index]
    is_home = s.team == s.home_team
    side = s.home_defending_side
    # home defends left -> home attacks the right net (+89); flips for away; fallback: nearer net
    attack_right = np.where(side.isin(["left", "right"]), np.where(is_home, side == "left", side == "right"), s.x >= 0)
    d = np.where(attack_right, 1.0, -1.0)
    s["dist"] = np.hypot(89.0 - s.x * d, s.y)
    s["angle"] = np.degrees(np.arctan2(np.abs(s.y), np.abs(89.0 - s.x * d)))
    # strength from shooter's perspective; code = away G, away skaters, home skaters, home G
    c = s.situation_code
    own = np.where(is_home, c.str[2], c.str[1]).astype(int)
    opp = np.where(is_home, c.str[1], c.str[2]).astype(int)
    opp_goalie_in = np.where(is_home, c.str[0], c.str[3]) == "1"
    s["state"] = np.select([own > opp, own < opp], ["PP", "SH"], "EV")
    s["dt_prev"] = (s.game_seconds - p.game_seconds).clip(0, 60).fillna(60)
    s["rebound"] = (p.event.isin(UNBLOCKED + ["blocked-shot"]) & (s.dt_prev <= 3)).astype(int)
    s["rush"] = ((s.dt_prev <= 4) & p.zone.isin(["N", "D"]) & ~p.event.isin(["faceoff", "stoppage"])).astype(int)
    px, py, sx, sy = p.x * d, p.y * d, s.x * d, s.y * d
    s["prev_dist"] = np.hypot(sx - px, sy - py).fillna(0).clip(0, 200)
    s["move_speed"] = (s.prev_dist / s.dt_prev.clip(lower=1)).clip(0, 100)
    s["royal"] = ((s.dt_prev <= 4) & (np.sign(py) * np.sign(sy) < 0) & (py.abs() >= 3) & (sy.abs() >= 3) & (sx > 25)).astype(int)
    s["same_team"] = (p.team == s.team).astype(int)
    s["prev_type"] = np.where(p.event.isin(PREV_TYPES) & (s.dt_prev <= 10), p.event + np.where(p.team == s.team, "_own", "_opp"), "other")
    sh_path = os.path.join(ROOT, "data", "tables", season, "shifts.csv.gz")
    s["shift_t"] = 40.0
    if os.path.exists(sh_path):
        sh = pd.read_csv(sh_path, usecols=["game_id", "player_id", "start_sec", "end_sec"])
        m = s[["game_id", "player1_id", "game_seconds"]].reset_index().merge(
            sh, left_on=["game_id", "player1_id"], right_on=["game_id", "player_id"], how="left")
        m = m[(m.start_sec < m.game_seconds) & (m.game_seconds <= m.end_sec)].drop_duplicates("index")
        s["shift_t"] = m.set_index("index").eval("game_seconds - start_sec").reindex(s.index).fillna(40).clip(0, 180)
    s = s[opp_goalie_in & s.x.notna()].copy()   # drop empty-net shots: they'd distort the model
    s["goal"] = (s.event == "goal").astype(int)
    s["shot_type"] = s.shot_type.fillna("unknown")
    return s


frames = [shots_for(x) for x in (PREV_SEASON, SEASON) if os.path.exists(os.path.join(ROOT, "data", "tables", x, "events.csv.gz"))]
allshots = pd.concat(frames, ignore_index=True)
F = pd.DataFrame({"dist": allshots.dist, "log_dist": np.log1p(allshots.dist), "angle": allshots.angle,
                  "rebound": allshots.rebound, "rush": allshots.rush, "prev_dist": allshots.prev_dist,
                  "move_speed": allshots.move_speed, "log_dt": np.log1p(allshots.dt_prev), "royal": allshots.royal,
                  "same_team": allshots.same_team, "shift_t": allshots.shift_t,
                  "shot_type": allshots.shot_type, "state": allshots.state, "prev_type": allshots.prev_type})
X = pd.get_dummies(F, columns=["shot_type", "state", "prev_type"], dtype=float)
X["dist_x_angle"] = X.dist * X.angle
X["royal_x_dist"] = X.royal * X.dist
X["speed_x_dist"] = X.move_speed * X.dist
X = (X - X.mean()) / X.std().replace(0, 1)

# out of fold, grouped by game so no shot is scored by a model that saw its game
model = LogisticRegression(max_iter=3000, C=1.0)
allshots["xg"] = cross_val_predict(model, X, allshots.goal, cv=GroupKFold(5), groups=allshots.game_id,
                                   method="predict_proba")[:, 1]
print(f"xG model: {len(allshots)} unblocked shots over {len(frames)} season(s), {allshots.goal.sum()} goals, "
      f"predicted {allshots.xg.sum():.1f}, AUC {roc_auc_score(allshots.goal, allshots.xg):.3f}, "
      f"log loss {log_loss(allshots.goal, allshots.xg):.4f}")
allshots.to_csv(os.path.join(OUT, "shots_with_xg.csv.gz"), index=False)
s = allshots[allshots.game_id.astype(str).str.startswith(SEASON[:4])].copy()   # this season, for the tables below
ev = pd.read_csv(os.path.join(T, "events.csv.gz"), low_memory=False)
ev = ev[ev.period_type != "SO"]

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
