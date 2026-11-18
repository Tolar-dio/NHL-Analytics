"""Threat Added: what every event on the ice did to its team's chances (Nov 2026).

Only shots carry expected goals, but a takeaway at the blue line, a won defensive-zone faceoff or a giveaway in
the slot all change what happens next. Following the possession-value idea from soccer (VAEP, Decroos et al. 2019)
and hockey's Markov-game action values (Routley & Schulte 2015), we learn the value of a game state:

    V(s) = expected net expected goals (own minus opponent's) in the next 20 seconds of the same period,
           for the team that owns the event, given what the event was, where (along the rink, toward the
           team's attacking net), the strength state, the score and the period clock

with a gradient-boosted regressor fitted on both seasons. An event's value is the change it makes:

    threat(e) = own xG of e (if it's an unblocked shot) + V(after e) - V(before e)

where "before" is the previous event's value seen from e's team (minus it when the other team owned it).
The actor (player1) gets the credit; a blocked shot's blocker gets the opposite of the shooter's change, a
faceoff loser the opposite of the winner's. Empty-net play is left out. Players are rated per 60 minutes at all
strengths, centred on their position.

Run: python analysis/threat.py   (writes analysis/output/threat_events.csv.gz, data/threat.json via build)
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASONS = ("20252026", "20262027")
WINDOW = 20
TYPES = ["faceoff", "hit", "giveaway", "takeaway", "blocked-shot", "missed-shot", "shot-on-goal", "goal", "penalty", "stoppage"]


def load(season):
    ev = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "events.csv.gz"), low_memory=False)
    ev = ev[(ev.period_type != "SO") & ev.event.isin(TYPES + ["period-start", "period-end"])]
    ev = ev.sort_values(["game_id", "sort_order"]).reset_index(drop=True)
    ev["situation_code"] = ev.situation_code.astype(str).str.zfill(4)
    xg = pd.read_csv(os.path.join(ROOT, "analysis", "output", "shots_with_xg.csv.gz"), usecols=["game_id", "event_id", "xg"])
    ev = ev.merge(xg, on=["game_id", "event_id"], how="left")
    ev["xg"] = ev.xg.fillna(0.0)
    ev["season"] = season
    return ev


def features(ev):
    is_home = ev.team == ev.home_team
    side = ev.home_defending_side
    attack_right = np.where(side.isin(["left", "right"]), np.where(is_home, side == "left", side == "right"), ev.x.fillna(0) >= 0)
    d = np.where(attack_right, 1.0, -1.0)
    c = ev.situation_code
    own_sk = np.where(is_home, c.str[2], c.str[1]).astype(int)
    opp_sk = np.where(is_home, c.str[1], c.str[2]).astype(int)
    own_g = np.where(is_home, c.str[3], c.str[0]) == "1"
    opp_g = np.where(is_home, c.str[0], c.str[3]) == "1"
    # stoppages and faceoffs at centre have no meaningful owner direction for the stoppage itself; keep x anyway
    f = pd.DataFrame(index=ev.index)
    f["x"] = (ev.x * d).fillna(0.0)                    # toward the event team's attacking net is positive
    f["ay"] = ev.y.abs().fillna(0.0)
    f["sk_diff"] = own_sk - opp_sk
    f["sk_tot"] = own_sk + opp_sk
    hs, as_ = ev.groupby("game_id").home_score.ffill().fillna(0), ev.groupby("game_id").away_score.ffill().fillna(0)
    diff = np.where(is_home, hs - as_, as_ - hs)
    f["score"] = np.clip(diff, -3, 3)
    f["period"] = ev.period.clip(upper=4)
    f["t_left"] = np.where(ev.period <= 3, 1200 - (ev.game_seconds - (ev.period - 1) * 1200), 300).clip(0, 1200)
    for t in TYPES:
        f["ev_" + t] = (ev.event == t).astype(int)
    ok = own_g & opp_g & ev.team.notna()
    return f, ok


def targets(ev):
    """Net xG for the event's team in (t, t + WINDOW], same period, plus the game-level arrays to compute it."""
    out = np.zeros(len(ev))
    for gid, g in ev.groupby("game_id", sort=False):
        idx = g.index.values
        t = g.game_seconds.values
        per = g.period.values
        team = g.team.values
        sh = g[g.xg > 0]
        st, sp, steam, sxg = sh.game_seconds.values, sh.period.values, sh.team.values, sh.xg.values
        for k, i in enumerate(idx):
            if not isinstance(team[k], str):
                continue
            m = (st > t[k]) & (st <= t[k] + WINDOW) & (sp == per[k])
            if m.any():
                out[i] = sxg[m & (steam == team[k])].sum() - sxg[m & (steam != team[k])].sum()
    return out


def fit_values(ev, f, ok):
    y = targets(ev)
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=200)
    # out of sample by season: each season's values come from a model fitted on the other one
    v = np.zeros(len(ev))
    vm = np.zeros(len(ev))       # faceoffs: the same faceoff won by the other team, from its side (mirrored)
    fo = (ev.event == "faceoff").values
    mir = f.copy()
    mir["x"], mir["sk_diff"], mir["score"] = -f.x, -f.sk_diff, -f.score
    for s in SEASONS:
        tr, te = ok & (ev.season != s), ok & (ev.season == s)
        model.fit(f[tr], y[tr])
        v[te.values] = model.predict(f[te])
        m = te.values & fo
        if m.any():
            vm[m] = model.predict(mir[m])
    return v, y, vm


def credit(ev, v, ok, vm=None):
    """threat(e) = own xG + V(e) - V(prev, from e's team's side); zero across period boundaries and EN states.

    A faceoff is judged against the coin flip at that dot, not against the zone: before it, the winner's team
    expected 0.5 V(win) - 0.5 V(opponent wins), so winning is worth 0.5 (V(win) + V(opponent wins)). Otherwise a
    defensive centre "loses value" for every own-zone draw he's sent out to take."""
    prev_v = ev.assign(v=v).groupby("game_id").v.shift(1).fillna(0).values
    prev_team = ev.groupby("game_id").team.shift(1).values
    prev_per = ev.groupby("game_id").period.shift(1).values
    same = (prev_team == ev.team.values)
    before = np.where(same, prev_v, -prev_v)
    before = np.where((prev_per == ev.period.values) & ok.values, before, 0.0)
    if vm is not None:
        fo = (ev.event == "faceoff").values
        before = np.where(fo, 0.5 * v - 0.5 * vm, before)
    th = np.where(ok, ev.xg.values + v - before, 0.0)
    th = np.where(ev.event.isin(["stoppage", "period-start", "period-end"]), 0.0, th)
    return th


def main():
    ev = pd.concat([load(s) for s in SEASONS], ignore_index=True)
    f, ok = features(ev)
    v, y, vm = fit_values(ev, f, ok)
    ev["v"], ev["target"] = v, y
    ev["threat"] = credit(ev, v, ok, vm)
    keep = ["game_id", "season", "date", "event_id", "period", "game_seconds", "event", "team", "x", "y", "player1_id", "player2_id", "xg", "v", "threat"]
    out = os.path.join(ROOT, "analysis", "output", "threat_events.csv.gz")
    ev.loc[ok, keep].to_csv(out, index=False)
    q = ev[ok]
    print(f"{len(q)} events; value model R^2 out of season "
          f"{1 - np.mean((q.target - q.v) ** 2) / np.var(q.target):.3f}")
    print(q.groupby("event").threat.agg(["count", "mean"]).round(4).sort_values("mean").to_string())
    return ev


def player_credit(te):
    """One row per (player, game, kind): the actor's credit, plus the opposite for blockers, faceoff losers and
    players who drew a penalty."""
    a = te[["game_id", "season", "player1_id", "event", "threat"]].rename(columns={"player1_id": "player_id"})
    opp = te[te.event.isin(["blocked-shot", "faceoff", "penalty"])][["game_id", "season", "player2_id", "event", "threat"]]
    opp = opp.rename(columns={"player2_id": "player_id"}).assign(threat=lambda d: -d.threat,
                                                                 event=lambda d: d.event.map({"blocked-shot": "block", "faceoff": "faceoff", "penalty": "penalty drawn"}))
    c = pd.concat([a, opp]).dropna(subset=["player_id"])
    c["player_id"] = c.player_id.astype(int)
    c["kind"] = c.event.map({"shot-on-goal": "shooting", "missed-shot": "shooting", "goal": "shooting", "blocked-shot": "shooting",
                             "faceoff": "faceoffs", "hit": "physical", "block": "physical", "giveaway": "puck", "takeaway": "puck",
                             "penalty": "discipline", "penalty drawn": "discipline"})
    return c


def ratings(season, te=None):
    """Per skater: Threat Added per 60 (all strengths), by kind, centred on his position."""
    te = te if te is not None else pd.read_csv(os.path.join(ROOT, "analysis", "output", "threat_events.csv.gz"))
    c = player_credit(te[te.season.astype(str) == season])
    pg = pd.read_csv(os.path.join(ROOT, "analysis", "output", season, "player_games.csv"))
    toi = pg.groupby("player_id").agg(toi=("toi", "sum"), pos=("pos", "last"), gp=("game_id", "nunique"))
    k = c.pivot_table(index="player_id", columns="kind", values="threat", aggfunc="sum").fillna(0)
    r = toi.join(k, how="left").fillna(0)
    kinds = [x for x in ("shooting", "puck", "faceoffs", "physical", "discipline") if x in r]
    r["total"] = r[kinds].sum(axis=1)
    for col in kinds + ["total"]:
        r[col + "60"] = r[col] / r.toi * 60
        for pos in ("F", "D"):
            m = (r.pos == pos) & (r.toi >= 200)
            mean = (r.loc[m, col].sum() / r.loc[m, "toi"].sum() * 60) if m.any() else 0
            r.loc[r.pos == pos, col + "60"] -= mean
    return r


def check():
    """Is it a skill (split-half), and does it say anything on-ice xG doesn't about the rest of the season?"""
    te = pd.read_csv(os.path.join(ROOT, "analysis", "output", "threat_events.csv.gz"))
    S = "20252026"
    c = player_credit(te[te.season.astype(str) == S])
    pg = pd.read_csv(os.path.join(ROOT, "analysis", "output", S, "player_games.csv"))
    pg = pg[pg.game_id.astype(str).str[4:6] == "02"]
    dates = sorted(pg.date.unique()); mid = dates[len(dates) // 2]
    gdate = pg.drop_duplicates("game_id").set_index("game_id").date
    c["date"] = c.game_id.map(gdate)
    for lab, cond_c, cond_p in (("odd/even", lambda d: d.game_id % 2 == 0, lambda d: d.game_id % 2 == 0),
                                ("first/second half", lambda d: d.date < mid, lambda d: d.date < mid)):
        out = []
        for h in (True, False):
            cc, pp = c[cond_c(c) == h], pg[cond_p(pg) == h]
            t = pp.groupby("player_id").agg(toi=("toi", "sum"), pos=("pos", "last"), xgf=("xgf", "sum"), xga=("xga", "sum"),
                                            gf=("gf", "sum"), ga=("ga", "sum"), pts=("pts", "sum"))
            t["ta"] = cc.groupby("player_id").threat.sum()
            t = t.fillna(0)
            for col in ("ta", "xgf", "xga", "gf", "ga", "pts"):
                t[col + "60"] = t[col] / t.toi * 60
            out.append(t)
        a, b = out
        j = a.join(b, lsuffix="_1", rsuffix="_2").dropna()
        j = j[(j.toi_1 >= 300) & (j.toi_2 >= 300)]
        for pos in ("F", "D"):
            q = j[j.pos_1 == pos]
            r = lambda x, y: np.corrcoef(q[x], q[y])[0, 1]
            print(f"{lab} {pos} (n {len(q)}): Threat Added/60 repeat r {r('ta60_1', 'ta60_2'):.2f}; on-ice xG diff repeat "
                  f"{np.corrcoef(q.xgf60_1 - q.xga60_1, q.xgf60_2 - q.xga60_2)[0, 1]:.2f}")
            if lab.startswith("first"):
                y = q.gf60_2 - q.ga60_2
                X1 = np.c_[np.ones(len(q)), q.xgf60_1 - q.xga60_1]
                X2 = np.c_[X1, q.ta60_1]
                rss = lambda X: np.sum((y - X @ np.linalg.lstsq(X, y, rcond=None)[0]) ** 2)
                print(f"   second-half on-ice goal diff/60: R^2 from xG diff {1 - rss(X1) / np.sum((y - y.mean()) ** 2):.3f}, "
                      f"plus Threat Added {1 - rss(X2) / np.sum((y - y.mean()) ** 2):.3f}; "
                      f"second-half points/60 from first-half TA/60 r {np.corrcoef(q.ta60_1, q.pts60_2)[0, 1]:.2f} vs points/60 r {np.corrcoef(q.pts60_1, q.pts60_2)[0, 1]:.2f}")


if __name__ == "__main__":
    check() if sys.argv[1:2] == ["check"] else main()
