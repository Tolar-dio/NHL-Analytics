"""Live xG model for the browser.

The live game page rates shots from ESPN's play feed while a game is on, so this model
uses only features ESPN gives us (its rink coordinates are identical to the NHL's):
distance, angle, shot type, strength, rebound (any shot attempt in the previous 3 s) and
rush (the previous event, within 4 s, happened outside the shooter's offensive zone and
wasn't a faceoff or stoppage). Trained on unblocked, non-empty-net shots from last season
and this one; the coefficients and standardisation are exported as JSON for site/live.js.

The nightly game pages keep MoneyPuck's xG; this only covers the hours before it exists.
"""
import json, os, sys
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import roc_auc_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASONS = ["20252026", "20262027"]
SHOT_TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around"]
UNBLOCKED = ["shot-on-goal", "missed-shot", "goal"]
ATTEMPTS = UNBLOCKED + ["blocked-shot"]


def features(s):
    """s needs: x, y, dir (+1 attacking the right net, -1 the left), shot_type, state,
    rebound, rush. Mirrors featurise() in site/live.js exactly."""
    net_x = 89.0 * s["dir"]
    dist = np.hypot(net_x - s.x, s.y)
    angle = np.degrees(np.arctan2(np.abs(s.y), np.abs(net_x - s.x)))
    X = pd.DataFrame({"dist": dist, "log_dist": np.log1p(dist), "angle": angle, "dist_x_angle": dist * angle,
                      "rebound": s.rebound.astype(float), "rush": s.rush.astype(float),
                      "pp": (s.state == "PP").astype(float), "sh": (s.state == "SH").astype(float)})
    st = s.shot_type.where(s.shot_type.isin(SHOT_TYPES), "other")
    for t in SHOT_TYPES + ["other"]:
        X["st_" + t] = (st == t).astype(float)
    return X


def load_shots():
    frames = []
    for season in SEASONS:
        p = os.path.join(ROOT, "data", "tables", season, "events.csv.gz")
        if not os.path.exists(p):
            continue
        ev = pd.read_csv(p, low_memory=False)
        ev = ev[(ev.period_type != "SO") & (ev.game_type.isin(["regular", "playoff"]) if "game_type" in ev else True)]
        ev = ev.sort_values(["game_id", "sort_order"]).reset_index(drop=True)
        ev["situation_code"] = ev.situation_code.astype(str).str.zfill(4)
        is_home = ev.team == ev.home_team
        side = ev.home_defending_side
        ev["dir"] = np.where(side.isin(["left", "right"]),
                             np.where(np.where(is_home, side == "left", side == "right"), 1.0, -1.0),
                             np.where(ev.x.fillna(0) >= 0, 1.0, -1.0))
        prev = ev.groupby("game_id").shift(1)
        dt = ev.game_seconds - prev.game_seconds
        s = ev[ev.event.isin(UNBLOCKED)].copy()
        p_ = prev.loc[s.index]
        dt_ = dt.loc[s.index]
        s["rebound"] = (p_.event.isin(ATTEMPTS) & (dt_ <= 3)).astype(int)
        # the previous event's spot, seen from the shooter's end: offensive zone is beyond the blue line (x*dir > 25)
        prev_in_oz = (p_.x * s["dir"]) > 25
        s["rush"] = ((dt_ <= 4) & ~prev_in_oz & p_.x.notna() & ~p_.event.isin(["faceoff", "stoppage"])).astype(int)
        c = s.situation_code
        home = s.team == s.home_team
        own = np.where(home, c.str[2], c.str[1]).astype(int)
        opp = np.where(home, c.str[1], c.str[2]).astype(int)
        opp_g = np.where(home, c.str[0], c.str[3]) == "1"
        s["state"] = np.select([own > opp, own < opp], ["PP", "SH"], "EV")
        s = s[opp_g & s.x.notna() & s.y.notna()]
        s["goal"] = (s.event == "goal").astype(int)
        s["shot_type"] = s.shot_type.fillna("other")
        frames.append(s)
    return pd.concat(frames, ignore_index=True)


def train(out_path):
    s = load_shots()
    X = features(s)
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = (X - mu) / sd
    model = LogisticRegression(max_iter=3000, C=1.0)
    oof = cross_val_predict(model, Z, s.goal, cv=5, method="predict_proba")[:, 1]
    model.fit(Z, s.goal)
    auc = roc_auc_score(s.goal, oof)
    out = dict(features=list(X.columns), mean=[round(float(v), 6) for v in mu], std=[round(float(v), 6) for v in sd],
               coef=[round(float(v), 6) for v in model.coef_[0]], intercept=round(float(model.intercept_[0]), 6),
               shot_types=SHOT_TYPES, shots=int(len(s)), goals=int(s.goal.sum()), auc=round(float(auc), 3))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"  xg_live.json: {len(s)} shots, AUC {auc:.3f} out of fold")
    return out


if __name__ == "__main__":
    train(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "site", "data", "xg_live.json"))
