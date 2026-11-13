"""Goalie saves prices for tonight's starters.

Expected shots against = the opponent's shots on goal per game (this season, shrunk with KT games toward a target)
times the goalie's own team's shots allowed per game (same shrinkage) over the league average, times a home-ice
nudge (home teams put about 4% more pucks on net: 28.4 vs 27.3 shots a game in 2025-26). The target is the team's
own rate last season blended with league average (half and half), or league average without a last season.

Expected saves = expected shots against x SCALE x his save rate. SCALE covers the shots a starter doesn't face (an
empty net, the nights he's pulled: starters faced 97.6% of their team's shots in 2025-26). His save rate is this
season's saves over shots, shrunk with KG shots toward his last season (itself shrunk with KG shots toward league),
or toward league for a goalie we have no last season for. Save rates barely repeat, so KG is large and the number
moves mostly with the shots.

Saves follow a negative binomial with shape SIZE (a pulled goalie and blowouts make them burstier than Poisson).
Prices are conditional on the goalie starting. Saves and shots against are the official boxscore counts.

`python analysis/saves.py check` fits on 2025-26 (walk-forward, every regular-season starter, no last season) and
checks on 2026-27 with 2025-26 as the prior.

Fit Nov 12, 2026 on 2025-26 (2,482 starts from Oct 17): 24.5 saves predicted vs 24.4 actual, mean absolute error
5.10 vs 5.36 for a flat league average, NB log likelihood per start -3.273 vs -3.317; 20+ 75.4% vs 75.9%, 25+ 47.1%
vs 47.3%, 30+ 22.6% vs 21.9%; slope of actual on predicted 0.98. Checked on 2026-27 with priors (598 starts):
MAE 4.95 vs 5.09, log likelihood -3.264 vs -3.287, 25+ 44.4% vs 45.2%, 30+ 20.7% vs 19.2%. But the early 2026-27
spread is too wide (slope 0.69; top fifth 27.2 predicted vs 25.8 actual). Compressing it toward the mean helped
2026-27 and hurt 2025-26, so it's left off until the live record says otherwise. Saves are hard: the best this
can do is a modest edge on a flat average (correlation with actual saves about 0.25 to 0.30).
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import nbinom

KT, KG, HOME, SCALE, SIZE, PRIOR_W = 10, 1500, 0.02, 0.975, 30.0, 0.5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINES = (20, 25, 30)          # "20+ saves" etc. on the site; the goalie table takes any line on top


def _regular(df):
    return df[df.game_id.astype(str).str[4:6] == "02"]


def parts(rows, cur_tg, cur_gg, prev_tg, prev_gg, cut, kt=KT, kg=KG, prior_w=PRIOR_W):
    """rows: DataFrame with team, opp, home (bool), goalie_id. Returns exp_sa (team shots against) and sv (save rate)."""
    tg = _regular(cur_tg)
    tg = tg[tg.date < cut]
    lg = tg.sogf.mean() if len(tg) >= 20 else _regular(prev_tg).sogf.mean() if prev_tg is not None else 28.0
    f = tg.groupby("team").sogf.agg(["sum", "count"])
    a = tg.groupby("team").soga.agg(["sum", "count"])
    if prev_tg is not None and len(prev_tg):
        p = _regular(prev_tg)
        tf, ta = p.groupby("team").sogf.mean(), p.groupby("team").soga.mean()
    else:
        tf = ta = pd.Series(dtype=float)
    d = rows.copy()
    tgt_f = prior_w * d.opp.map(tf).fillna(lg) + (1 - prior_w) * lg
    tgt_a = prior_w * d.team.map(ta).fillna(lg) + (1 - prior_w) * lg
    off = (d.opp.map(f["sum"]).fillna(0) + kt * tgt_f) / (d.opp.map(f["count"]).fillna(0) + kt)
    dfn = (d.team.map(a["sum"]).fillna(0) + kt * tgt_a) / (d.team.map(a["count"]).fillna(0) + kt)
    d["exp_sa"] = off * dfn / lg * np.where(d.home, 1 - HOME, 1 + HOME)    # the shooting side is the opponent
    gg = _regular(cur_gg)
    gg = gg[gg.date < cut]
    lsv = gg.saves.sum() / gg.sa.sum() if gg.sa.sum() > 2000 else 0.902
    if prev_gg is not None and len(prev_gg):
        pv = _regular(prev_gg).groupby("player_id")[["saves", "sa"]].sum()
        prior = (pv.saves + kg * lsv) / (pv.sa + kg)
    else:
        prior = pd.Series(dtype=float)
    c = gg.groupby("player_id")[["saves", "sa"]].sum()
    pr = d.goalie_id.map(prior).fillna(lsv)
    d["sv"] = (d.goalie_id.map(c.saves).fillna(0) + kg * pr) / (d.goalie_id.map(c.sa).fillna(0) + kg)
    d["sv_season"] = d.goalie_id.map(c.saves / c.sa)
    return d


def tail(mu, k, size=SIZE):
    return 1 - nbinom.cdf(k - 1, size, size / (size + mu))


def prices(rows, cur_tg, cur_gg, prev_tg, prev_gg, cut):
    """One row per (game, side): exp_sa, sv, exp_saves, p_saves20/25/30 and the NB shape for the site's own lines."""
    d = parts(rows, cur_tg, cur_gg, prev_tg, prev_gg, cut)
    d["exp_sa"] = d.exp_sa * SCALE
    d["exp_saves"] = d.exp_sa * d.sv
    for k in LINES:
        d[f"p_saves{k}"] = tail(d.exp_saves, k)
    return d


def _walk(cur_tg, cur_gg, prev_tg, prev_gg, games, kt, kg, prior_w):
    st = _regular(cur_gg)
    st = st[st.starter].merge(_regular(cur_tg)[["game_id", "team", "opp"]], on=["game_id", "team"])
    st["home"] = st.team == st.game_id.map(games.set_index("game_id").home)
    st = st.rename(columns={"player_id": "goalie_id"})
    out = [parts(r, cur_tg, cur_gg, prev_tg, prev_gg, cut, kt, kg, prior_w) for cut, r in st.groupby("date")]
    return pd.concat(out)


def _score(d, scale, size):
    mu = d.exp_sa * scale * d.sv
    return -nbinom.logpmf(d.saves.astype(int), size, size / (size + mu)).mean()


def _report(d, label, scale, size):
    mu = d.exp_sa * scale * d.sv
    print(f"{label}: {len(d)} starts, saves {mu.mean():.2f} predicted vs {d.saves.mean():.2f} actual, "
          f"MAE {np.abs(mu - d.saves).mean():.2f} (flat league mean {np.abs(d.saves.mean() - d.saves).mean():.2f}), "
          f"loglik/start {-_score(d, scale, size):.4f}, flat {nbinom.logpmf(d.saves.astype(int), size, size / (size + d.saves.mean())).mean():.4f}")
    print(f"  corr with actual saves {np.corrcoef(mu, d.saves)[0, 1]:.3f}; shots against corr {np.corrcoef(d.exp_sa * scale, d.sa)[0, 1]:.3f}")
    for k in LINES:
        p = tail(mu, k, size)
        y = (d.saves >= k).astype(int)
        ll = -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
        base = y.mean()
        llb = -(y * np.log(base) + (1 - y) * np.log(1 - base)).mean()
        print(f"  {k}+ saves: {100 * p.mean():.1f}% predicted vs {100 * y.mean():.1f}% actual, log loss {ll:.4f} (flat {llb:.4f})")
    q = d.assign(mu=mu, b=pd.qcut(mu, 5))
    print(q.groupby("b", observed=True).agg(n=("saves", "size"), pred=("mu", "mean"), act=("saves", "mean"),
                                            p25=("saves", lambda s: (s >= 25).mean())).round(2).to_string())


if __name__ == "__main__" and sys.argv[1:2] == ["check"]:
    out = os.path.join(ROOT, "analysis", "output")
    ld = lambda s, f: pd.read_csv(os.path.join(out, s, f))
    tg25, gg25, tg26, gg26 = ld("20252026", "team_games.csv"), ld("20252026", "goalie_games.csv"), \
        ld("20262027", "team_games.csv"), ld("20262027", "goalie_games.csv")
    g25 = pd.read_csv(os.path.join(ROOT, "data", "tables", "20252026", "games.csv.gz"))
    g26 = pd.read_csv(os.path.join(ROOT, "data", "tables", "20262027", "games.csv.gz"))
    best = None
    for kt in (5, 10, 20, 40):
        for kg in (500, 1500, 4000):
            d = _walk(tg25, gg25, None, None, g25, kt, kg, PRIOR_W)
            d = d[d.date >= "2025-10-17"]
            for sc in (0.96, 0.975, 0.99):
                for sz in (15, 30, 60, 120):
                    s = _score(d, sc, sz)
                    if best is None or s < best[0]:
                        best = (s, kt, kg, sc, sz)
    print("best on 2025-26 (KT, KG, SCALE, SIZE):", best[1:])
    _, kt, kg, sc, sz = best
    d = _walk(tg25, gg25, None, None, g25, kt, kg, PRIOR_W)
    _report(d[d.date >= "2025-10-17"], "2025-26 fit", sc, sz)
    for pw in (0.0, 0.5, 0.8):
        d = _walk(tg26, gg26, tg25, gg25, g26, kt, kg, pw)
        _report(d, f"2026-27 check (2025-26 prior, team weight {pw})", sc, sz)
