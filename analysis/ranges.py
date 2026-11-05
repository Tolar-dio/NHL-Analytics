"""Talent ranges and rest-of-season projections.

A player's numbers so far are part skill, part bounces. These estimate the skill with an honest range:

- Points per 60 (all situations): gamma-Poisson. This season's points and minutes, plus last season's at weight
  W_PREV, pulled toward his position's league rate with K_PTS minutes of weight.
- Shooting %: beta-binomial, same idea in shots on goal (K_SH), position mean.
- Shots per 60: K_SOG minutes (shot rates settle fast).
- Goalies: goals allowed relative to expected (GA / xGA) with K_GK expected goals of weight toward 1.0 and last
  season at full weight; shown as the save % he'd post against league-average shots.
- Rest of season: his remaining team games x his recent ice time (last 10 games), points and goals drawn from the
  rate's uncertainty and then game-to-game luck; assumes he dresses every night.

Weights fit on 2025-26 (first part of the season predicting the rest: points K 200-300 best, shooting 200, goalies
flat past 160 expected goals, i.e. barely any signal) and last season -> this one (W_PREV 0.75-1.0 best for points;
shooting and goalies barely care). Intervals are 80% (10th to 90th percentile).
"""
import numpy as np
import pandas as pd

K_PTS, K_SH, K_SOG, K_GK, W_PREV = 250.0, 200.0, 100.0, 300.0, 0.75
DRAWS = 4000


def _agg(pg):
    pg = pg[pg.game_type == "regular"]
    return pg.groupby("player_id").agg(pos=("pos", "last"), team=("team", "last"), gp=("game_id", "nunique"),
                                       toi=("toi", "sum"), pts=("pts", "sum"), g=("g", "sum"), sog=("sog", "sum"))


def skaters(cur_pg, prev_pg, games_left, seed=11):
    """games_left: {team: remaining regular-season games}. Returns {player_id: dict}."""
    rng = np.random.default_rng(seed)
    c, p = _agg(cur_pg), _agg(prev_pg)
    c = c.join(p[["toi", "pts", "g", "sog"]].add_prefix("p_")).fillna({"p_toi": 0, "p_pts": 0, "p_g": 0, "p_sog": 0})
    d = c.pos.eq("D")
    lg = {k: {isd: q[k].sum() / q[den].sum() for isd, q in c.groupby(d)}
          for k, den in (("pts", "toi"), ("g", "sog"), ("sog", "toi"))}
    m_pts, m_sh, m_sog = (d.map(lg[k]) for k in ("pts", "g", "sog"))
    # posteriors
    a_pts, b_pts = c.pts + W_PREV * c.p_pts + K_PTS * m_pts, c.toi + W_PREV * c.p_toi + K_PTS
    a_sh, b_sh = c.g + W_PREV * c.p_g + K_SH * m_sh, (c.sog - c.g) + W_PREV * (c.p_sog - c.p_g) + K_SH * (1 - m_sh)
    a_sog, b_sog = c.sog + W_PREV * c.p_sog + K_SOG * m_sog, c.toi + W_PREV * c.p_toi + K_SOG
    # recent ice time
    pg = cur_pg[cur_pg.game_type == "regular"].sort_values("date")
    recent = pg.groupby("player_id").tail(10).groupby("player_id").toi.mean().reindex(c.index)
    out = {}
    n = len(c)
    r_pts = rng.gamma(a_pts.values[:, None], 1 / b_pts.values[:, None], (n, DRAWS))
    r_sh = rng.beta(a_sh.values[:, None], b_sh.values[:, None], (n, DRAWS))
    r_sog = rng.gamma(a_sog.values[:, None], 1 / b_sog.values[:, None], (n, DRAWS))
    left = c.team.map(games_left).fillna(0).values * recent.fillna(0).values      # minutes left
    pts_rest = rng.poisson(r_pts * left[:, None])
    g_rest = rng.poisson(r_sog * r_sh * left[:, None])
    q = lambda x: np.percentile(x, [10, 50, 90], axis=1)
    P60, SH, PR, GR = q(r_pts * 60), q(r_sh * 100), q(pts_rest), q(g_rest)
    for i, pid in enumerate(c.index):
        r = c.iloc[i]
        out[int(pid)] = dict(
            pts60=[round(float(v), 2) for v in P60[:, i]], pts60_now=round(float(r.pts / r.toi * 60), 2) if r.toi else None,
            pts60_lg=round(float(m_pts.iloc[i] * 60), 2),
            sh=[round(float(v), 1) for v in SH[:, i]], sh_now=round(float(r.g / r.sog * 100), 1) if r.sog else None,
            sh_lg=round(float(m_sh.iloc[i] * 100), 1), sog=int(r.sog),
            proj_pts=[int(r.pts + v) for v in PR[:, i]], proj_g=[int(r.g + v) for v in GR[:, i]],
            games_left=int(games_left.get(r.team, 0)), toi_recent=round(float(recent.iloc[i]), 1) if recent.iloc[i] == recent.iloc[i] else None)
    return out


def goalies(cur_gg, prev_gg, xg_per_shot, seed=13):
    """xg_per_shot: league expected goals per shot on goal (to turn GA/xGA into a save %)."""
    rng = np.random.default_rng(seed)
    agg = lambda g: g[g.game_type == "regular"].groupby("player_id").agg(xga=("xga", "sum"), ga=("ga", "sum"))
    c = agg(cur_gg).join(agg(prev_gg).add_prefix("p_")).fillna(0)
    a, b = K_GK + c.ga + c.p_ga, K_GK + c.xga + c.p_xga
    r = rng.gamma(a.values[:, None], 1 / b.values[:, None], (len(c), DRAWS))
    sv = np.percentile(1 - r * xg_per_shot, [10, 50, 90], axis=1)
    now = 1 - (c.ga / c.xga.where(c.xga > 0)) * xg_per_shot
    return {int(pid): dict(sv=[round(float(v), 4) for v in sv[:, i]], sv_now=None if now.iloc[i] != now.iloc[i] else round(float(now.iloc[i]), 4),
                           sv_lg=round(1 - xg_per_shot, 4))
            for i, pid in enumerate(c.index)}
