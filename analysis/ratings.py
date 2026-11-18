"""Dynamic team ratings: attack and defense that update after every game (Nov 2026).

The game model rated teams on season-to-date expected goals, shrunk toward a roster prior: a cumulative average,
so a team that changed in November still carried its October. This is a score-driven Poisson rating (in the
family of Koopman & Lit 2015 for football): each team has a log attack a and log defense d, and for team i at
team j the expected goals are

    mu_ij = exp(c + a_i + d_j + h * home_i)

After each game the ratings move along the Poisson score, scaled by its information, toward what was observed:

    a_i <- phi * a_i + alpha_a * (y_i - mu_ij) / mu_ij          (and d_j the same way with y_i)

where y is a blend of what the team generated: w_x * xGF + w_g * GF + w_s * (SOG * league shooting %), so
chance quality, finishing and shot volume each get a say. phi pulls ratings slowly back to average (form fades),
alpha sets how fast they learn. Between seasons ratings carry over at rho. Every one of those is fitted, not set
by hand: `python analysis/ratings.py fit` searches them on 2025-26 walk-forward (each game priced only from
games before it) and checks them on 2026-27.

The goalie layer stays separate (models.goalie_factor), so defense here is about chances allowed, not saves.
"""
import os
import sys
from itertools import product

import numpy as np
import pandas as pd
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Fitted Nov 18, 2026 (fit()): attack learns from xG alone; defense from 0.6 xG against + 0.2 goals against
# + 0.2 shots against at league shooting %; no fade between games (phi 1); full carryover between seasons
# (rho 1.0 beat 0.8, 0.6, 0.4 on 2026-27); home x exp(+-0.03).
#
# Same-games test against the old season-average ratings, both with our goalie and rest adjustments
# (scratch harness, Nov 18): 2025-26 from Nov 1 (1,132 games) winner log loss 0.67933 -> 0.67892, Brier
# 0.24324 -> 0.24309; 2026-27 (338) log loss 0.65995 -> 0.65339, Brier 0.23369 -> 0.23078. Paired t about 1.0
# over both, so not proven, but totals improved in both seasons (correlation with actual goals 0.092 -> 0.112 and
# 0.103 -> 0.170) and the level stopped running low (6.01 -> 6.20 predicted vs 6.24 actual). Teams spread out:
# logit sd 0.28 -> 0.44, and the calibration slope is still above 1 (1.19), so it remains a little timid.
P = dict(alpha_a=0.04, alpha_d=0.04, phi=1.0, wx=1.0, wg=0.0, ws=0.0, dx=0.6, dg=0.2, ds=0.2, rho=1.0, h=0.03)


def team_games(season):
    tg = pd.read_csv(os.path.join(ROOT, "analysis", "output", season, "team_games.csv"))
    g = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "games.csv.gz"))
    tg = tg.merge(g[["game_id", "home", "away", "home_score", "away_score"]], on="game_id")
    tg = tg[tg.game_id.astype(str).str[4:6] == "02"].copy()
    tg["is_home"] = tg.team == tg.home
    return tg.sort_values(["date", "game_id"])


def run(seasons, p=P, start=None):
    """Walk through the seasons in order. Returns one row per game with the pre-game ratings' goal means.

    seasons: list of season ids, oldest first. start: dict of {team: (a, d)} before the first season."""
    a, d = {}, {}
    if start:
        a = {t: v[0] for t, v in start.items()}
        d = {t: v[1] for t, v in start.items()}
    out = []
    for si, S in enumerate(seasons):
        if si:   # new season: carry ratings over at rho
            a = {t: p["rho"] * v for t, v in a.items()}
            d = {t: p["rho"] * v for t, v in d.items()}
        tg = team_games(S)
        lg_sh = (tg.gf.sum() / tg.sogf.sum()) if tg.sogf.sum() else 0.1
        c = np.log(3.0)
        games = tg.groupby("game_id", sort=False)
        for gid, rows in games:
            if len(rows) != 2:
                continue
            r = {row.team: row for row in rows.itertuples()}
            hm = rows[rows.is_home].iloc[0]
            H, A = hm.team, hm.opp
            mu_h = np.exp(c + a.get(H, 0) + d.get(A, 0) + p["h"])
            mu_a = np.exp(c + a.get(A, 0) + d.get(H, 0) - p["h"])
            out.append(dict(game_id=gid, date=hm.date, season=S, home=H, away=A, mu_h=mu_h, mu_a=mu_a,
                            hs=int(hm.home_score), as_=int(hm.away_score),
                            a_h=a.get(H, 0), d_h=d.get(H, 0), a_a=a.get(A, 0), d_a=d.get(A, 0)))
            # update from what happened (regulation-ish counts: these are the team's own totals)
            for T, O, mu in ((H, A, mu_h), (A, H, mu_a)):
                x = r[T]
                y_att = p["wx"] * x.xgf + p["wg"] * x.gf + p["ws"] * x.sogf * lg_sh
                y_def = p["dx"] * x.xgf + p["dg"] * x.gf + p["ds"] * x.sogf * lg_sh
                a[T] = p["phi"] * a.get(T, 0) + p["alpha_a"] * (y_att - mu) / mu
                d[O] = p["phi"] * d.get(O, 0) + p["alpha_d"] * (y_def - mu) / mu
            # league scoring level drifts too
            c = 0.98 * c + 0.02 * np.log(max(0.5, (r[H].xgf + r[A].xgf) / 2 * 0.5 + (r[H].gf + r[A].gf) / 2 * 0.5))
    run.c = c
    return pd.DataFrame(out), a, d


def current(seasons=("20252026", "20262027"), p=P):
    """Ratings after every finished game: {team: (attack, defense)}, the league level c and the home term."""
    _, a, d = run(list(seasons), p)
    return dict(a=a, d=d, c=run.c, h=p["h"])


def goal_means(cur, away, home):
    """Pre-game expected goals (away, home) from current(), before goalies and rest."""
    la = np.exp(cur["c"] + cur["a"].get(away, 0) + cur["d"].get(home, 0) - cur["h"])
    lh = np.exp(cur["c"] + cur["a"].get(home, 0) + cur["d"].get(away, 0) + cur["h"])
    return la, lh


def win_prob(la, lh, maxg=15):
    k = np.arange(maxg + 1)
    j = np.outer(poisson.pmf(k, la), poisson.pmf(k, lh))
    return np.triu(j, 1).sum() + np.trace(j) * 0.514      # home OT/shootout share (winprob.py)


def score(R, burn="10-20"):
    """Winner log loss and Brier, and goal log likelihood, after a burn-in (ratings need a few games)."""
    ph = np.array([win_prob(a, h) for a, h in zip(R.mu_a, R.mu_h)])
    y = (R.hs > R.as_).astype(int).values
    ll = -np.mean(y * np.log(ph) + (1 - y) * np.log(1 - ph))
    br = np.mean((ph - y) ** 2)
    gl = (poisson.logpmf(R.hs, R.mu_h) + poisson.logpmf(R.as_, R.mu_a)).mean()
    lo = np.log(ph / (1 - ph))
    return dict(n=len(R), ll=round(ll, 5), brier=round(br, 5), goal_ll=round(gl, 4), logit_sd=round(lo.std(), 3))


def fit():
    """Search the constants on 2025-26 (from Nov 1, after a burn-in), then check on 2026-27 with carryover."""
    grid = dict(alpha=(0.02, 0.04, 0.07, 0.1), phi=(0.99, 0.995, 1.0), mix=((1, 0, 0), (0.6, 0.2, 0.2), (0.5, 0.3, 0.2), (0.7, 0.3, 0)),
                dmix=((1, 0, 0), (0.8, 0, 0.2), (0.6, 0.2, 0.2)), h=(0.03, 0.05))
    best = None
    for al, ph, mx, dm, h in product(*grid.values()):
        p = dict(P, alpha_a=al, alpha_d=al, phi=ph, wx=mx[0], wg=mx[1], ws=mx[2], dx=dm[0], dg=dm[1], ds=dm[2], h=h)
        R, _, _ = run(["20252026"], p)
        s = score(R[R.date >= "2025-11-01"])
        if best is None or s["ll"] < best[0]["ll"]:
            best = (s, p)
    print("best on 2025-26:", best[0], {k: best[1][k] for k in ("alpha_a", "phi", "wx", "wg", "ws", "dx", "dg", "ds", "h")})
    for rho in (0.4, 0.6, 0.8):
        p = dict(best[1], rho=rho)
        R, _, _ = run(["20252026", "20262027"], p)
        print(f"  2026-27 with carryover rho {rho}:", score(R[R.season == "20262027"]))
    return best[1]


if __name__ == "__main__" and sys.argv[1:2] == ["fit"]:
    fit()
