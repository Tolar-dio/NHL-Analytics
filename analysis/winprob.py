"""Win probability at any moment of a game, and the win probability each goal, save and shot added.

The model is a scoring clock, not a black box. From any moment, each team's goals in the time left are Poisson, at
rates learned from two seasons of play-by-play:
  - even strength, power play and short-handed scoring rates, with home ice (models.HOME) on top;
  - a power play keeps going for the time its penalty has left;
  - late in a close game the trailing team pulls its goalie for about as long as teams really do (learned per deficit),
    which raises both teams' scoring;
  - a tie after regulation goes to overtime and the shootout, won by the home team as often as home teams really win them.
P(home wins) = P(home ends ahead in regulation) + P(tied) x P(home wins OT/SO). In overtime it's sudden death at
3-on-3 rates.

Credit (all in percentage points of win probability for the player's team):
  goal swing        the win probability after a goal minus before it, to the scorer
  shot value        expected: xG x (win probability if it goes in - now), to the shooter, for every unblocked shot
  saves added       for goalies: (xG - goal) x the swing a goal would have made, summed over shots faced, so a big
                    save late in a tie counts for far more than one in a blowout

    python analysis/winprob.py            # fit, check calibration, print the season's leaders
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import skellam

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import models as M  # noqa: E402
from defense import _xg  # noqa: E402

ATT = ["shot-on-goal", "missed-shot", "goal"]
REG = 3600


def _side(code, home):
    """A team's state from the 4-digit code (away goalie, away skaters, home skaters, home goalie)."""
    ag, ask, hsk, hg = int(code[0]), int(code[1]), int(code[2]), int(code[3])
    own_g, opp_g, own, opp = (hg, ag, hsk, ask) if home else (ag, hg, ask, hsk)
    if own_g == 0:
        return "en_att"
    if opp_g == 0:
        return "en_def"
    return "pp" if own > opp else "pk" if own < opp else "ev"


def load_events(season):
    ev = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "events.csv.gz"),
                     usecols=["game_id", "game_type", "event_id", "sort_order", "period", "period_type", "game_seconds", "event",
                              "situation_code", "team", "home_team", "away_team", "player1_id", "player2_id", "player3_id",
                              "goalie_id", "home_score", "away_score", "penalty_minutes", "x", "y", "home_defending_side",
                              "shot_type", "zone"])
    ev = ev[(ev.game_type == "regular") & (ev.period_type != "SO")].copy()
    ev["sc"] = ev.situation_code.fillna(1551).astype(int).astype(str).str.zfill(4)
    return ev.sort_values(["game_id", "period", "game_seconds", "sort_order"])


def fit_rates(seasons=(M.PREV, M.CUR)):
    """Goals per second by state, home and away, plus how long trailing teams keep the goalie pulled."""
    tim, gol = {}, {}
    pulled, close = {1: [0.0, 0], 2: [0.0, 0]}, {}
    ot = [0, 0]                       # OT/SO games won by home, total
    for s in seasons:
        ev = load_events(s)
        games = pd.read_csv(os.path.join(ROOT, "data", "tables", s, "games.csv.gz"))
        g2 = games[(games.game_type == "regular") & games.decided_in.isin(["OT", "SO"])]
        ot[0] += int((g2.home_score > g2.away_score).sum()); ot[1] += len(g2)
        for gid, g in ev.groupby("game_id", sort=False):
            t = g.game_seconds.values.astype(float)
            dt = np.diff(t, append=t[-1])
            codes = g.sc.values
            nxt = np.r_[codes[1:], codes[-1:]]
            ot_ = (g.period.values >= 4)
            for side in (True, False):
                st = np.array([_side(c, side) for c in nxt])
                key = np.where(ot_, "ot", st)
                for k in np.unique(key):
                    tim[(k, side)] = tim.get((k, side), 0.0) + float(dt[key == k].sum())
            goals = g[g.event == "goal"]
            for _, x in goals.iterrows():
                home = x.team == x.home_team
                k = "ot" if x.period >= 4 else _side(x.sc, home)
                gol[(k, home)] = gol.get((k, home), 0) + 1
            # goalie pulls: at 3:00 left in regulation, a team down 1 or 2; how many of the last 180 s it played 6-on-5
            reg = g[g.period <= 3]
            early = goals[goals.game_seconds <= REG - 180]
            if len(reg):
                d = int((early.team == early.home_team).sum() - (early.team != early.home_team).sum())
                if abs(d) in (1, 2):
                    trail_home = d < 0
                    m = (reg.game_seconds.values > REG - 180)
                    late = reg[m]
                    tl = late.game_seconds.values.astype(float)
                    dtl = np.diff(np.r_[REG - 180, tl])
                    st = np.array([_side(c, trail_home) for c in late.sc.values])
                    pulled[abs(d)][0] += float(dtl[st == "en_att"].sum())
                    pulled[abs(d)][1] += 1
    rate = {}
    for k in ("ev", "pp", "pk", "en_att", "en_def", "ot"):
        for side in (True, False):
            rate[(k, side)] = gol.get((k, side), 0) / max(tim.get((k, side), 1.0), 1.0)
    return dict(rate={f"{k}|{'h' if s else 'a'}": v for (k, s), v in rate.items()},
                pull={str(k): v[0] / max(v[1], 1) for k, v in pulled.items()},
                ot_home=ot[0] / max(ot[1], 1))


class WP:
    def __init__(self, params):
        self.r = {(k.split("|")[0], k.split("|")[1] == "h"): v for k, v in params["rate"].items()}
        self.pull = {int(k): v for k, v in params["pull"].items()}
        self.ot_home = params["ot_home"]
        self.cal = params.get("cal", [0.0, 1.0])

    def lam(self, home, t_left, state, pp_left):
        """Expected goals for one side over the rest of regulation."""
        r = self.r
        ev = r[("ev", home)]
        d = min(pp_left, t_left) if state in ("pp", "pk") else 0.0
        return ev * (t_left - d) + r[(state, home)] * d if state in ("pp", "pk") else ev * t_left

    def prob(self, diff, t_left, hs="ev", as_="ev", pp_left=60.0, ot=False, ot_left=300.0):
        """Home win probability. diff = home - away goals so far; t_left = regulation seconds left."""
        diff, t_left = np.asarray(diff, float), np.asarray(t_left, float)
        if ot:
            rh, ra = self.r[("ot", True)] * ot_left, self.r[("ot", False)] * ot_left
            p_any = 1 - np.exp(-(rh + ra))
            first = rh / max(rh + ra, 1e-9)
            return np.where(diff > 0, 1.0, np.where(diff < 0, 0.0, self.calibrate(p_any * first + (1 - p_any) * 0.5)))
        lh = np.array([self.lam(True, t, hs, pp_left) for t in np.atleast_1d(t_left)]).reshape(diff.shape)
        la = np.array([self.lam(False, t, as_, pp_left) for t in np.atleast_1d(t_left)]).reshape(diff.shape)
        # the trailing team pulls its goalie late: both sides score at empty-net rates for that stretch
        for k, secs in self.pull.items():
            s = np.where(t_left <= 180, np.minimum(t_left, secs), 0.0)   # the net sits empty for the last `secs` seconds
            th, ta = (diff == -k) * s, (diff == k) * s          # seconds the home / away side plays 6-on-5
            lh = lh + th * (self.r[("en_att", True)] - self.r[("ev", True)]) + ta * (self.r[("en_def", True)] - self.r[("ev", True)])
            la = la + ta * (self.r[("en_att", False)] - self.r[("ev", False)]) + th * (self.r[("en_def", False)] - self.r[("ev", False)])
        lh, la = np.maximum(lh, 1e-9), np.maximum(la, 1e-9)
        k = -diff
        win = 1 - skellam.cdf(k, lh, la)          # P(Xh - Xa > -diff)
        tie = skellam.pmf(k, lh, la)
        return self.calibrate(win + tie * self.ot_home)

    def calibrate(self, p):
        """Goals are streakier than a fixed-rate clock (teams and nights differ), so the raw clock is too sure of
        itself; a logit stretch fit on 2025-26 (a 0.04, b 0.82) fixes it and held on 2026-27 (log loss 0.4916 to 0.4877)."""
        p = np.clip(p, 1e-6, 1 - 1e-6)
        a, b = self.cal
        return 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))


def params(refit=False):
    path = os.path.join(ROOT, "data", "derived", "winprob.json")
    if os.path.exists(path) and not refit:
        return json.load(open(path))
    p = fit_rates()
    p["cal"] = [0.04, 0.821]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(p, open(path, "w"), indent=1)
    return p


def wp_at(wp, diff, t, period, sc, pen_end):
    if period >= 4:
        return float(wp.prob(np.array([diff]), np.array([0.0]), ot=True, ot_left=max(0.0, 3900 - t))[0])
    hs, as_ = _side(sc, True), _side(sc, False)
    if hs.startswith("en") or as_.startswith("en"):
        hs = as_ = "ev"
    left = max(0.0, REG - t)
    ppl = 60.0
    if hs in ("pp", "pk"):
        ends = [e for e in pen_end.values() if e > t]
        ppl = min(ends) - t if ends else 60.0
    return float(wp.prob(np.array([diff]), np.array([left]), hs, as_, ppl)[0])


def game_wp(g, wp, xg=None):
    """Win probability through one game: a chart series, every goal's swing, and expected swings for shots."""
    g = g.sort_values(["period", "game_seconds", "sort_order"])
    home, away = g.home_team.iloc[0], g.away_team.iloc[0]
    hs = as_ = 0
    pen_end = {}
    series, goals, shots = [], [], []
    last = None
    for x in g.itertuples():
        t = float(x.game_seconds)
        if x.event == "penalty" and pd.notna(x.penalty_minutes) and x.penalty_minutes in (2, 4, 5):
            pen_end[x.team] = max(pen_end.get(x.team, -1), t) + 60 * float(x.penalty_minutes)
        pe = {k: v for k, v in pen_end.items() if v > t}
        p = wp_at(wp, hs - as_, t, int(x.period), x.sc, pe)
        if last is None or abs(p - last) >= 0.004 or x.event in ("goal", "period-end"):
            series.append([int(t), round(p, 4)])
            last = p
        if x.event in ATT and x.team in (home, away):
            sh = x.team == home
            d_if = (hs - as_) + (1 if sh else -1)
            p_if = wp_at(wp, d_if, t + 0.5, int(x.period), x.sc, pe) if x.period <= 3 else (1.0 if sh else 0.0)
            swing = (p_if - p) if sh else (p - p_if)         # for the shooting team
            xv = float(xg.get(int(x.event_id), 0.0)) if xg is not None else 0.0
            shots.append(dict(eid=int(x.event_id), t=int(t), period=int(x.period), team=x.team, shooter=x.player1_id,
                              goalie=x.goalie_id, xg=xv, swing=swing, goal=x.event == "goal"))
            if x.event == "goal":
                before = p if sh else 1 - p
                hs, as_ = (hs + 1, as_) if sh else (hs, as_ + 1)
                after = wp_at(wp, hs - as_, t + 0.5, int(x.period), x.sc, pe) if x.period <= 3 else 1.0
                after = after if sh else 1 - after
                if x.period >= 4:
                    after = 1.0
                goals.append(dict(eid=int(x.event_id), t=int(t), period=int(x.period), team=x.team, scorer=x.player1_id,
                                  a1=x.player2_id, a2=x.player3_id, before=round(before, 4), after=round(after, 4),
                                  score=f"{hs}-{as_}"))
                series.append([int(t), round(after if sh else 1 - after, 4)])
                last = series[-1][1]
    return dict(series=series, goals=goals, shots=shots)


def season(season=M.CUR, wp=None):
    """Every regular-season game: per-game WP and the season's per-player totals."""
    wp = wp or WP(params())
    ev = load_events(season)
    att = _xg(season, ev[ev.event.isin(ATT)][["game_id", "event_id", "event", "game_seconds", "player1_id"]].copy())
    xgm = {gid: dict(zip(a.event_id, a.xg)) for gid, a in att.groupby("game_id")}
    games, sk, gk = {}, {}, {}
    for gid, g in ev.groupby("game_id", sort=False):
        r = game_wp(g, wp, xgm.get(gid, {}))
        games[int(gid)] = r
        for s in r["shots"]:
            if pd.notna(s["shooter"]):
                a = sk.setdefault(int(s["shooter"]), [0.0, 0.0, 0])
                a[0] += s["swing"] * s["goal"]
                a[1] += s["swing"] * s["xg"]
                a[2] += 1
            if pd.notna(s["goalie"]):
                b = gk.setdefault(int(s["goalie"]), [0.0, 0])
                b[0] += s["swing"] * (s["xg"] - s["goal"])
                b[1] += 1
    return games, sk, gk


def calibration(season=M.PREV, wp=None):
    """Log loss and buckets of the win probability at every event, against who won."""
    wp = wp or WP(params())
    ev = load_events(season)
    games = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "games.csv.gz")).set_index("game_id")
    P, Y, T = [], [], []
    for gid, g in ev.groupby("game_id", sort=False):
        if gid not in games.index:
            continue
        y = int(games.loc[gid].home_score > games.loc[gid].away_score)
        r = game_wp(g, wp)
        for t, p in r["series"]:
            P.append(p); Y.append(y); T.append(t)
    P, Y, T = np.clip(np.array(P), 1e-4, 1 - 1e-4), np.array(Y), np.array(T)
    ll = -np.mean(Y * np.log(P) + (1 - Y) * np.log(1 - P))
    b = pd.cut(P, [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1])
    tab = pd.DataFrame(dict(p=P, y=Y, b=b)).groupby("b", observed=True).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"))
    return ll, tab


if __name__ == "__main__":
    p = params(refit=True)
    print(json.dumps(p, indent=1))
    ll, tab = calibration()
    print(f"2025-26 log loss at every moment {ll:.4f}"); print(tab.round(3))


def summary(r, names, home, away):
    """What a game page needs: the chart, the goals that swung it, the biggest save, and who added the most."""
    nm = lambda i: names.get(int(i)) if i is not None and i == i else None
    s = r["series"]
    if len(s) > 160:                              # keep the shape: every goal, plus an even thinning of the rest
        keep = {i for i, (t, _) in enumerate(s) if i == 0 or i == len(s) - 1}
        gt = {g["t"] for g in r["goals"]}
        step = max(1, len(s) // 120)
        keep |= {i for i in range(0, len(s), step)} | {i for i, (t, _) in enumerate(s) if t in gt}
        s = [s[i] for i in sorted(keep)]
    goals = [dict(t=g["t"], period=g["period"], team=g["team"], id=int(g["scorer"]) if g["scorer"] == g["scorer"] else None,
                  name=nm(g["scorer"]), before=g["before"], after=g["after"], swing=round(g["after"] - g["before"], 4), score=g["score"])
             for g in r["goals"]]
    saves = [x for x in r["shots"] if not x["goal"] and x["goalie"] == x["goalie"] and x["xg"] > 0]
    best = max(saves, key=lambda x: x["xg"] * x["swing"], default=None)
    add = {}
    for x in r["shots"]:
        if x["goal"] and x["shooter"] == x["shooter"]:
            add[int(x["shooter"])] = add.get(int(x["shooter"]), 0) + x["swing"]
        if x["goalie"] == x["goalie"]:
            add[int(x["goalie"])] = add.get(int(x["goalie"]), 0) + x["swing"] * (x["xg"] - x["goal"])
    top = sorted(add.items(), key=lambda kv: -kv[1])[:3]
    return dict(series=s, goals=goals,
                save=dict(t=best["t"], period=best["period"], goalie=int(best["goalie"]), name=nm(best["goalie"]),
                          shooter=nm(best["shooter"]), xg=round(best["xg"], 3), value=round(best["xg"] * best["swing"], 4),
                          swing=round(best["swing"], 4)) if best and best["xg"] * best["swing"] >= 0.01 else None,
                top=[dict(id=i, name=nm(i), added=round(v, 4)) for i, v in top if v > 0.02])


def season_table(sk, gk, names):
    """Wins added per player this season: by his goals, by his shots on average (expected), and for goalies by saves."""
    sk_rows = [dict(id=i, name=names.get(i), goals=round(v[0], 3), expected=round(v[1], 3), clutch=round(v[0] - v[1], 3), shots=v[2])
               for i, v in sk.items()]
    gk_rows = [dict(id=i, name=names.get(i), saves_added=round(v[0], 3), shots=v[1]) for i, v in gk.items()]
    return dict(skaters=sorted(sk_rows, key=lambda r: -r["goals"]), goalies=sorted(gk_rows, key=lambda r: -r["saves_added"]))
